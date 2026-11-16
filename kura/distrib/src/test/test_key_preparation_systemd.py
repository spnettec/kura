#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""New preparation/history contract against archive assets and actual systemd.

Fresh disposable Linux container only. Extracting the archive is not package
installation acceptance. No Main, generation publication or existing key is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import stat
import struct
import subprocess
import sys
import unittest
import uuid


OPTIONS = None
SOCKET = '/run/kura-key-service/control.sock'


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def rpc(request):
    # One connection and one dispatch. A missing response never causes a retry.
    data = encode(request)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(25)
        stream.connect(SOCKET)
        stream.sendall(struct.pack('!I', len(data)) + data)
        stream.shutdown(socket.SHUT_WR)

        def read(size):
            result = bytearray()
            while len(result) < size:
                chunk = stream.recv(size - len(result))
                if not chunk:
                    raise RuntimeError('Original response disconnected; do not dispatch again')
                result.extend(chunk)
            return bytes(result)

        size = struct.unpack('!I', read(4))[0]
        if not 0 < size <= 65536:
            raise RuntimeError('Invalid original response frame')
        return json.loads(read(size))


class PreparationSystemdTest(unittest.TestCase):
    def command(self, *arguments):
        completed = subprocess.run(list(map(str, arguments)), capture_output=True, text=True, timeout=60)
        self.assertEqual(0, completed.returncode, completed.stderr[-1500:])
        return completed.stdout

    @staticmethod
    def put(path, data, mode=0o600):
        with path.open('xb') as stream:
            stream.write(data)
        path.chmod(mode)

    @staticmethod
    def files(directory):
        result = {}
        for path in sorted(directory.rglob('*')):
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                result[str(path.relative_to(directory))] = (
                    info.st_ino, info.st_uid, info.st_gid, info.st_mode, info.st_nlink,
                    info.st_mtime_ns, info.st_ctime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        return result

    @staticmethod
    def history(cursor=None, limit=16):
        return rpc(dict(schema=1, action='generation-history', afterPreparationId=cursor, limit=limit))

    def setUp(self):
        if OPTIONS is None:
            self.skipTest('Requires explicitly authorized fresh disposable systemd container')
        self.assertEqual('linux', sys.platform)
        self.assertEqual(0, os.geteuid())
        self.assertTrue(Path('/.dockerenv').is_file())
        self.assertEqual('systemd', Path('/proc/1/comm').read_text().strip())
        for name in ('/opt/eclipse/kura', '/etc/kura', '/var/lib/kura-key-service',
                     '/run/kura-key-service', '/usr/bin/java', '/etc/systemd/system/kura-management-agent.service'):
            self.assertFalse(os.path.lexists(name), 'Never adopt an existing runtime')
        self.assertEqual(OPTIONS.package_sha256, hashlib.sha256(OPTIONS.package.read_bytes()).hexdigest())
        self.command('dpkg-deb', '--extract', OPTIONS.package, '/')
        homes = list(Path('/opt/eclipse').glob('kura_*/libexec/key-backup/manifest.json'))
        self.assertEqual(1, len(homes))
        Path('/opt/eclipse/kura').symlink_to(homes[0].parents[2].name)
        self.home = Path('/opt/eclipse/kura').resolve(strict=True)
        self.assertEqual(Path('/opt/eclipse'), self.home.parent)
        sys.path.insert(0, str(self.home / 'bin'))
        import kura_key_service as service
        import kura_key_service_lifecycle as lifecycle
        self.service = service
        for unit in lifecycle.UNITS:
            target = Path('/lib/systemd/system') / unit
            self.assertFalse(os.path.lexists(target))
            shutil.copyfile(self.home / 'install' / unit, target)
            target.chmod(0o644)
        self.command('groupadd', '--system', 'kura-key-control')
        self.command('useradd', '--system', '--user-group', '--groups', 'kura-key-control',
                     '--shell', '/usr/sbin/nologin', 'kurad')
        self.command('useradd', '--system', '--user-group', '--groups', 'kura-key-control',
                     '--shell', '/usr/sbin/nologin', 'kura-key-recovery')
        Path('/usr/bin/java').symlink_to(OPTIONS.java)
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        self.credentials = Path('/etc/kura/credentials')
        self.credentials.mkdir(parents=True, mode=0o700)
        self.state = Path('/var/lib/kura-key-service')
        (self.state / 'operations').mkdir(parents=True, mode=0o700)
        (self.state / 'startups').mkdir(mode=0o700)
        key = secrets.token_bytes(32)
        self.source = dict(keySha256=hashlib.sha256(key).hexdigest(), ringSha256=None)
        self.put(self.credentials / 'kura_encryption_key', key, 0o400)
        self.put(self.credentials / 'provisioned.json', encode(dict(
            schema=1, origin='fresh', legacyKey=False, keySha256=self.source['keySha256'], unitDigests=[])))
        self.put(self.credentials / '.provision.lock', b'')
        self.put(self.state / 'admission.lock', b'')
        self.put(self.state / 'journal.key', secrets.token_bytes(32))
        lifecycle.Lifecycle().no_overrides()
        lifecycle.Lifecycle().assets()
        self.command('systemctl', 'daemon-reload')
        self.command('systemctl', 'start', 'kura-key-service.socket')
        self.before_credentials = self.files(self.credentials)

    def mutation(self, action, **fields):
        identity = str(uuid.uuid4())
        marker = Path('/run/key-preparation-original-ids.json')
        ids = json.loads(marker.read_bytes()) if marker.exists() else []
        ids.append(dict(operationId=identity, action=action))
        # The owning runner retains this new fixture on any subsequent failure.
        marker.write_bytes(encode(ids))
        response = rpc(dict(schema=1, action=action, operationId=identity, **fields))
        self.assertEqual('SUCCEEDED', response.get('state'), 'Inspect the original record; never repeat this request')
        self.assertEqual(identity, response['operationId'])
        return response

    def worker(self):
        pid = int(self.command('systemctl', 'show', 'kura-key-service.service', '--property=MainPID', '--value'))
        self.assertGreater(pid, 1)
        status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
        self.assertEqual('0', status['Uid'].split()[0])
        for field in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
            self.assertEqual(0, int(status[field].strip(), 16), field)
        self.assertEqual('1', status['NoNewPrivs'].strip())
        return pid

    def test_original_cancellation_history_survives_real_worker_restart(self):
        initial = self.history()
        self.assertIn('entries', initial, initial)
        self.assertEqual([], initial['entries'])
        original_pid = self.worker()
        password = 'Disposable archive fixture passphrase 21!'
        prepared = self.mutation('generation-prepare', expectedSource=self.source, passphrase=password)
        directory = self.state / 'generations' / prepared['operationId']
        original_preparation = self.files(directory)
        verified = self.mutation('generation-backup-verify', preparationId=prepared['operationId'],
                                 expectedRingSha256=prepared['generation']['ringSha256'],
                                 backup=prepared['backup'], passphrase=password)
        self.assertFalse(verified['published'])
        self.assertEqual('VERIFIED', self.history()['entries'][0]['state'])
        cancelled = self.mutation('generation-cancel', preparationId=prepared['operationId'],
                                  expectedHistorySha256=prepared['historySha256'],
                                  expectedRingSha256=prepared['generation']['ringSha256'])
        self.assertFalse(cancelled['credentialsChanged'])
        self.assertTrue(cancelled['historyRetained'])
        after_cancel = self.files(directory)
        self.assertEqual(original_preparation, {name: value for name, value in after_cancel.items()
                                               if name in original_preparation})
        self.assertEqual({'cancellation.json'}, set(after_cancel) - set(original_preparation))
        state_before_restart = self.files(self.state)
        self.command('systemctl', 'restart', 'kura-key-service.service')
        # Type=simple returns before exec/sandbox setup. A read-only response is
        # the readiness barrier; inspecting the just-forked PID is too early.
        original = rpc(dict(schema=1, action='operation-read', operationId=cancelled['operationId']))
        self.assertEqual(cancelled, original)
        self.assertNotEqual(original_pid, self.worker())
        history = self.history()
        self.assertEqual('HISTORICAL_EVENTS_ONLY', history['scope'])
        self.assertFalse(history['hasUnresolvedRecords'])
        self.assertEqual('CANCELLED', history['entries'][0]['state'])
        self.assertEqual(state_before_restart, self.files(self.state))
        # Exercise authorization using real Unix peer UIDs and agent cgroup.
        for user in ('kurad', 'kura-key-recovery'):
            response = json.loads(self.command('runuser', '-u', user, '--', 'python3', '-B', __file__, '--probe-peer'))
            if user == 'kurad':
                self.assertEqual(history, response)
            else:
                self.assertEqual('FORBIDDEN', response.get('error'))
        agent_unit = Path('/etc/systemd/system/kura-management-agent.service')
        self.put(agent_unit, ('[Service]\nType=oneshot\nUser=root\nNoNewPrivileges=true\n'
                             'CapabilityBoundingSet=\nAmbientCapabilities=\n'
                             f'ExecStart=/usr/bin/python3 -B {__file__} --probe-agent\n').encode(), 0o644)
        self.command('systemctl', 'daemon-reload')
        self.command('systemctl', 'start', 'kura-management-agent.service')
        self.assertEqual('FORBIDDEN', json.loads(Path('/run/key-preparation-agent-result.json').read_bytes()).get('error'))
        # A settled cancellation permits a new round while retaining the whole old one.
        before_second = self.files(directory)
        second = self.mutation('generation-prepare', expectedSource=self.source, passphrase=password)
        self.mutation('generation-cancel', preparationId=second['operationId'],
                      expectedHistorySha256=second['historySha256'],
                      expectedRingSha256=second['generation']['ringSha256'])
        self.assertEqual(before_second, self.files(directory))
        page = self.history(limit=1)
        self.assertIsNotNone(page['nextAfterPreparationId'])
        tail = self.history(page['nextAfterPreparationId'], 1)
        self.assertIsNone(tail['nextAfterPreparationId'])
        self.assertEqual({prepared['operationId'], second['operationId']},
                         {row['preparationId'] for row in page['entries'] + tail['entries']})
        self.assertTrue(all(row['state'] == 'CANCELLED' for row in page['entries'] + tail['entries']))
        self.assertEqual(self.before_credentials, self.files(self.credentials))
        self.assertEqual([], list((self.state / 'startups').iterdir()))
        self.assertFalse(Path('/lib/systemd/system/kura.service').exists())
        self.assertEqual(5, len(list((self.state / 'operations').iterdir())))
        self.command('systemctl', 'stop', 'kura-key-service.service', 'kura-key-service.socket')
        print('PREPARATION_SYSTEMD_OK ' + json.dumps(dict(
            schema=1, scope='archive-assets-actual-systemd-preparation', actualRootWorker=True,
            archiveSha256=OPTIONS.package_sha256, packagedUnitsUnmodified=True,
            noNewPrivileges=True, workerCapabilitiesEmpty=True, originalCancelReadAfterWorkerRestart=True,
            actualKuradAllowed=True, actualRecoveryDenied=True, actualRootAgentCgroupDenied=True,
            twoCancelledRoundsRetained=True, originalCredentialsFullMetadataUnchanged=True,
            mainStarted=False, generationPublished=False, fullPackageInstallationAccepted=False,
            unknownRedispatched=False), sort_keys=True))


if __name__ == '__main__':
    if sys.argv[1:] in (['--probe-peer'], ['--probe-agent']):
        response = PreparationSystemdTest.history()
        if sys.argv[1] == '--probe-agent':
            Path('/run/key-preparation-agent-result.json').write_bytes(encode(response))
        else:
            print(json.dumps(response))
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument('--package', required=True, type=Path)
        parser.add_argument('--package-sha256', required=True)
        parser.add_argument('--java', required=True, type=Path)
        parser.add_argument('--disposable-fixture', required=True, action='store_true')
        OPTIONS, remaining = parser.parse_known_args()
        unittest.main(argv=[sys.argv[0], *remaining])
