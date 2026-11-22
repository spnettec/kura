#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""New native handoff peer test; no generation publication/start is dispatched."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import struct
import subprocess
import sys
import time
import unittest
import uuid
import zipfile

import test_key_generation_core_systemd as install

OPTIONS = None


def raw_rpc(request):
    data = json.dumps(request, sort_keys=True, separators=(',', ':')).encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(15); connection.connect('/run/kura-key-service/control.sock')
        connection.sendall(struct.pack('!I', len(data)) + data); connection.shutdown(socket.SHUT_WR)
        def read(size):
            result = bytearray()
            while len(result) < size:
                chunk = connection.recv(size - len(result))
                if not chunk: raise RuntimeError('Original frame disconnected; no retry')
                result.extend(chunk)
            return bytes(result)
        size = struct.unpack('!I', read(4))[0]
        if not 0 < size <= 65536: raise RuntimeError('Invalid original frame')
        return json.loads(read(size))


class NativeHandoffSystemdTest(unittest.TestCase):
    step = install.CoreGenerationTest.step
    run_command = install.CoreGenerationTest.run_command
    rpc = install.CoreGenerationTest.rpc
    wait_probe = install.CoreGenerationTest.wait_probe

    def setUp(self):
        if OPTIONS is None: self.skipTest('Explicit fresh disposable installed-Core fixture required')
        install.OPTIONS = OPTIONS; install.CoreGenerationTest.setUp(self)

    def install_probe(self):
        install.CoreGenerationTest.install_probe(self)
        classes = self.temporary / 'handoff-classes'; classes.mkdir()
        jar = next((self.home / 'plugins').rglob('org.eclipse.osgi-*.jar'))
        source = Path(__file__).parent / 'resources/key-handoff-probe/HandoffProbe.java'
        self.run_command([OPTIONS.java.parent / 'javac', '--release', '21', '-cp', jar, '-d', classes, source])
        destination = self.home / 'plugins/5s/org.eclipse.kura.tests.handoff-1.0.0.jar'
        manifest = ('Manifest-Version: 1.0\nBundle-ManifestVersion: 2\nBundle-SymbolicName: org.eclipse.kura.tests.handoff\n'
                    'Bundle-Version: 1.0.0\nBundle-Activator: org.eclipse.kura.tests.handoff.HandoffProbe\n'
                    'Import-Package: org.osgi.framework\nBundle-RequiredExecutionEnvironment: JavaSE-21\n\n')
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('META-INF/MANIFEST.MF', manifest)
            for path in classes.rglob('*.class'): archive.write(path, path.relative_to(classes).as_posix())
        self.probe = self.home / 'data/key-handoff-probe'; self.probe.mkdir(mode=0o700)
        user = pwd.getpwnam('kurad'); os.chown(self.probe, user.pw_uid, user.pw_gid)

    def core_call(self, name, request):
        user = pwd.getpwnam('kurad'); path = self.probe / (name + '.request.json')
        temporary = self.probe / (name + '.input')
        with temporary.open('xb') as stream: stream.write(self.service.encode(request))
        temporary.chmod(0o600); os.chown(temporary, user.pw_uid, user.pw_gid); temporary.rename(path)
        output = self.probe / (name + '.response.json'); deadline = time.monotonic() + 30
        while not output.exists() and not (self.probe / 'error.txt').exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(output.is_file(), 'Original Core peer response unavailable; do not dispatch again')
        return json.loads(output.read_bytes())

    def peer(self, user, request):
        result = subprocess.run(['runuser', '-u', user, '--', 'python3', '-B', __file__, '--probe-peer'],
                                input=json.dumps(request), capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr[-1000:])
        return json.loads(result.stdout)

    @staticmethod
    def credential_snapshot(directory):
        result = {}
        for path in directory.iterdir():
            if path.is_file():
                value = path.stat()
                result[path.name] = (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
                    value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        return result

    def test_actual_registered_core_issues_only_scoped_authority(self):
        credentials = Path('/etc/kura/credentials')
        self.run_command(['systemctl', 'start', 'kura-key-service.socket'])
        self.run_command(['systemctl', 'start', 'kura.service']); status = self.wait_probe(); core_pid = int(status['pid'])
        before = self.credential_snapshot(credentials)
        baseline = Path('/run/key-handoff-baseline.json'); baseline.write_text(json.dumps(before)); baseline.chmod(0o600)
        self.original_ids = [str(uuid.uuid4()) for _ in range(5)]
        preparation, verification, handoff, publication, start = self.original_ids
        Path('/run/key-handoff-original-ids.json').write_text(json.dumps(dict(preparationId=preparation,
            verificationId=verification, handoffId=handoff, publicationId=publication, startOperationId=start)))
        password = 'Only an owned native authority fixture 21!'
        prepared = self.rpc(dict(schema=1, action='generation-prepare', operationId=preparation,
                                 passphrase=password, expectedSource=dict(keySha256=self.original_key_hash, ringSha256=None)))
        self.rpc(dict(schema=1, action='generation-backup-verify', operationId=verification, preparationId=preparation,
                      expectedRingSha256=prepared['generation']['ringSha256'], backup=prepared['backup'], passphrase=password))
        cohort = self.manager.require_generation_cohort()
        request = dict(schema=1, action='generation-handoff-create', handoffId=handoff, preparationId=preparation,
                       verificationId=verification, publicationId=publication, startOperationId=start,
                       expectedRingSha256=prepared['generation']['ringSha256'], expectedCohortSha256=cohort['cohortSha256'],
                       operator='owned-native-core-peer')
        issued = self.core_call('create', request)
        self.assertEqual('GRANT_RECORDED', issued.get('state'), issued.get('error'))
        token = issued['token']; self.assertFalse(issued['startupAuthorized'])
        token_read = self.core_call('token', dict(schema=1, action='generation-handoff-token-read', handoffId=handoff))
        self.assertEqual(token, token_read['token'])
        authority = self.manager.handoff_component().load(handoff)
        self.assertEqual(core_pid, authority['owner']['pid'])
        self.assertEqual(pwd.getpwnam('kurad').pw_uid, authority['owner']['uid'])
        record = Path('/var/lib/kura-key-service/handoffs') / (handoff + '.json')
        self.assertNotIn(token, record.read_text()); self.assertEqual(0o400, record.stat().st_mode & 0o777)
        command = dict(schema=1, action='generation-handoff-command', token=token, command='info')
        cold = self.peer('kura-key-recovery', command)
        self.assertEqual('ORIGINAL_AUTHORIZATION_ONLY', cold.get('scope'))
        self.assertNotIn('token', cold)
        for action in ('generation-handoff-token-read', 'generation-handoff-read'):
            reply = self.peer('kura-key-recovery', dict(schema=1, action=action, handoffId=handoff))
            self.assertEqual('FORBIDDEN', reply.get('error'))
        self.assertEqual('FORBIDDEN', self.peer('kura-key-recovery', request).get('error'))
        self.assertIn(self.peer('kurad', request).get('error'), ('FORBIDDEN', 'UNMANAGED_CORE', 'UNMANAGED_WRITER'))
        self.assertEqual('FORBIDDEN', self.peer('kura-key-recovery', dict(schema=1, action='generation-publish')).get('error'))
        payload = Path('/run/key-handoff-agent-input.json'); payload.write_bytes(self.service.encode(command)); payload.chmod(0o600)
        unit = Path('/etc/systemd/system/kura-management-agent.service')
        unit.write_text('[Service]\nType=oneshot\nUser=root\nNoNewPrivileges=true\nCapabilityBoundingSet=\nAmbientCapabilities=\n'
                        'ExecStart=/usr/bin/python3 -B ' + __file__ + ' --probe-agent\n'); unit.chmod(0o644)
        self.run_command(['systemctl', 'daemon-reload']); self.run_command(['systemctl', 'start', unit.name])
        self.assertEqual('FORBIDDEN', json.loads(Path('/run/key-handoff-agent-result.json').read_bytes()).get('error'))
        self.assertEqual(before, self.credential_snapshot(credentials))
        self.assertEqual(str(core_pid), self.run_command(['systemctl', 'show', 'kura.service', '-p', 'MainPID', '--value']).strip())
        operations = list(Path('/var/lib/kura-key-service/operations').iterdir())
        self.assertEqual(2, len(operations)); self.assertTrue(all(json.loads(p.read_bytes())['state'] == 'SUCCEEDED' for p in operations))
        self.assertFalse(Path('/var/lib/kura-key-service/operations', publication + '.json').exists())
        self.assertFalse(Path('/var/lib/kura-key-service/operations', start + '.json').exists())
        self.run_command(['systemctl', 'stop', 'kura.service'])
        self.run_command(['systemctl', 'stop', 'kura-key-service.service', 'kura-key-service.socket'])
        print('NATIVE_HANDOFF_SYSTEMD_OK ' + json.dumps(dict(schema=1, scope='fresh-installed-native-handoff-peer-authority',
            packageSha256=OPTIONS.package_sha256, actualCorePeerPidAndUid=True, actualColdPeerUid=True,
            sameUidOtherProcessDenied=True, coldCannotIssueOrRetrieveBearer=True, actualAgentCgroupDenied=True,
            credentialFullFileIdentityUnchanged=True, coreNotRestarted=True, generationPublished=False,
            generationStartDispatched=False, bearerAbsentFromRootAuthorityRecord=True,
            gwtAdminXsrfAccepted=False, httpOrGuiAccepted=False, fullBrokerAccepted=False), sort_keys=True))


if __name__ == '__main__':
    if sys.argv[1:] == ['--probe-peer']:
        print(json.dumps(raw_rpc(json.load(sys.stdin))))
    elif sys.argv[1:] == ['--probe-agent']:
        Path('/run/key-handoff-agent-result.json').write_text(json.dumps(raw_rpc(json.loads(Path('/run/key-handoff-agent-input.json').read_bytes()))))
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument('--package', required=True, type=Path); parser.add_argument('--package-sha256', required=True)
        parser.add_argument('--legacy-baseline', required=True, type=Path); parser.add_argument('--java', required=True, type=Path)
        parser.add_argument('--disposable-fixture', required=True, action='store_true')
        OPTIONS, remaining = parser.parse_known_args(); unittest.main(argv=[sys.argv[0], *remaining])
