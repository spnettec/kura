#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh systemd container only: declared package install, real Core and original data.

The original legacy unit comes from a separate known baseline archive. It is never
started. All data/operation IDs belong to this disposable test; no retained scene
or external gateway is contacted. Full provider/platform/release coverage remains
separate from this one real Crypto/configuration consumer.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import uuid
import zipfile

OPTIONS = None


class CoreGenerationTest(unittest.TestCase):
    def step(self, text):
        print(text, flush=True)

    def run_command(self, arguments, *, timeout=45, log=None, env=None):
        if log is None:
            result = subprocess.run(list(map(str, arguments)), capture_output=True, text=True,
                                    timeout=timeout, env=env)
            self.assertEqual(0, result.returncode, result.stderr[-3000:])
            return result.stdout
        with log.open('wb') as output:
            result = subprocess.run(list(map(str, arguments)), stdout=output, stderr=subprocess.STDOUT,
                                    timeout=timeout, env=env)
        if result.returncode:
            self.fail('Command failed; disposable log tail: ' + log.read_text(errors='replace')[-3500:])
        return ''

    def setUp(self):
        if OPTIONS is None:
            self.skipTest('Requires explicit fresh disposable systemd fixture')
        self.assertEqual('linux', sys.platform)
        self.assertEqual(0, os.geteuid())
        self.assertTrue(Path('/.dockerenv').is_file())
        self.assertEqual('systemd', Path('/proc/1/comm').read_text().strip())
        for name in ('/opt/eclipse/kura', '/etc/kura', '/var/lib/kura-key-service',
                     '/lib/systemd/system/kura.service', '/run/kura-key-service'):
            self.assertFalse(os.path.lexists(name), 'Refuse to adopt any existing Kura installation')
        temporary = tempfile.TemporaryDirectory(prefix='kura-real-generation-')
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.package = OPTIONS.package.resolve()
        self.assertEqual(OPTIONS.package_sha256, hashlib.sha256(self.package.read_bytes()).hexdigest())
        # Suppress automatic distro-daemon startup during dependency installation.
        Path('/usr/sbin/policy-rc.d').write_text('#!/bin/sh\nexit 101\n')
        Path('/usr/sbin/policy-rc.d').chmod(0o755)
        process = subprocess.Popen(['dpkg-deb', '--fsys-tarfile', str(OPTIONS.legacy_baseline)], stdout=subprocess.PIPE)
        found = None
        with tarfile.open(fileobj=process.stdout, mode='r|*') as archive:
            for item in archive:
                if item.isfile() and item.name.endswith('/install/kura.service'):
                    self.assertIsNone(found)
                    found = archive.extractfile(item).read()
        process.stdout.close()
        self.assertEqual(0, process.wait())
        self.assertIsNotNone(found)
        unit = Path('/lib/systemd/system/kura.service')
        unit.write_bytes(found.replace(b'INSTALL_DIR', b'/opt/eclipse'))
        unit.chmod(0o644)
        self.run_command(['/usr/bin/systemctl', 'daemon-reload'])
        self.step('Installing declared package dependencies and current archive in the fresh container')
        environment = dict(os.environ, DEBIAN_FRONTEND='noninteractive')
        self.run_command(['apt-get', 'update'], timeout=180, log=self.temporary/'apt-update.log', env=environment)
        self.run_command(['apt-get', '-y', '--no-install-recommends', 'install', 'openjdk-21-jre-headless',
                          'locales', str(self.package)], timeout=360, log=self.temporary/'install.log', env=environment)
        self.home = Path('/opt/eclipse/kura').resolve(strict=True)
        self.assertEqual(Path('/opt/eclipse'), self.home.parent)
        sys.path.insert(0, str(self.home/'bin'))
        import kura_key_service as service
        self.service = service
        self.manager = service.Manager()
        key, proof = self.manager.canonical()
        self.assertTrue(proof['legacyKey'], 'The original baseline key must be retained, never regenerated')
        self.original_key_hash = hashlib.sha256(key).hexdigest()
        self.assertIn(key, (service.CORE_DEFAULT, service.OLD_DEVELOPMENT))
        self.assertEqual('inactive', self.run_command(['systemctl', 'show', 'kura.service', '--property=ActiveState', '--value']).strip())
        for name in ('start_kura.sh', 'start_kura_background.sh', 'start_kura_debug.sh'):
            path = self.home/'bin'/name
            raw = path.read_bytes()
            raw, count = re.subn(rb'-Xms[0-9]+[kKmMgG]? -Xmx[0-9]+[kKmMgG]?', b'-Xms256m -Xmx256m', raw)
            self.assertEqual(1, count)
            path.write_bytes(raw)
        self.install_probe()
        self.run_command(['/usr/bin/python3', '-I', self.home/'bin/kura_runtime_ownership.py', '--code-only'])
        self.run_command(['/usr/bin/systemctl', 'daemon-reload'])
        self.initial_operations = len(list(self.manager.operations.iterdir()))
        self.assertEqual(0, self.initial_operations)
        Path('/run/kura-generation-install-ready').touch()
        self.step('INSTALL_READY: waiting for the owning runner to disconnect this fixture network')
        deadline = time.monotonic()+30
        while not Path('/run/kura-generation-network-off').exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(Path('/run/kura-generation-network-off').exists(), 'Owning runner must disconnect the fixture network')

    def install_probe(self):
        classes = self.temporary/'classes'
        classes.mkdir()
        plugins = self.home/'plugins'
        classpath = []
        for name in ('org.eclipse.kura.api-*.jar', 'org.eclipse.osgi-*.jar', 'org.osgi.service.component-*.jar'):
            matches = list(plugins.rglob(name))
            self.assertEqual(1, len(matches))
            classpath.append(str(matches[0]))
        source = Path(__file__).resolve().parent/'resources/key-generation-probe/GenerationProbe.java'
        self.run_command([OPTIONS.java.parent/'javac', '--release', '21', '-encoding', 'UTF-8', '-cp',
                          ':'.join(classpath), '-d', classes, source])
        manifest = ('Manifest-Version: 1.0\nBundle-ManifestVersion: 2\n'
                    'Bundle-SymbolicName: org.eclipse.kura.tests.keygeneration\nBundle-Version: 1.0.0\n'
                    'Import-Package: org.eclipse.kura.crypto,org.eclipse.kura.configuration,\n org.osgi.framework,org.osgi.service.component\n'
                    'Service-Component: OSGI-INF/probe.xml\nBundle-RequiredExecutionEnvironment: JavaSE-21\n\n')
        descriptor = ('<component xmlns="http://www.osgi.org/xmlns/scr/v1.4.0" name="generation-probe" immediate="true" activate="activate">'
                      '<implementation class="org.eclipse.kura.tests.keygeneration.GenerationProbe"/>'
                      '<reference name="crypto" interface="org.eclipse.kura.crypto.CryptoService" bind="setCrypto"/>'
                      '<reference name="configuration" interface="org.eclipse.kura.configuration.ConfigurationService" bind="setConfiguration"/>'
                      '</component>')
        destination = plugins/'5s/org.eclipse.kura.tests.keygeneration-1.0.0.jar'
        destination.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('META-INF/MANIFEST.MF', manifest)
            archive.writestr('OSGI-INF/probe.xml', descriptor)
            for path in classes.rglob('*.class'):
                archive.write(path, path.relative_to(classes).as_posix())
        self.expected_classes = {}
        roles = json.loads((self.home/'libexec/key-backup/manifest.json').read_text())['generation']['readers']
        for role, name in (('crypto', 'org/eclipse/kura/core/crypto/CryptoServiceImpl.class'),
                           ('configuration', 'org/eclipse/kura/core/configuration/ConfigurationServiceAuditFacade.class')):
            with zipfile.ZipFile(self.home/roles[role]) as archive:
                self.expected_classes[role] = hashlib.sha256(archive.read(name)).hexdigest()

    def rpc(self, request, *, timeout=75):
        data = self.service.encode(request)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            stream.settimeout(timeout)
            stream.connect(self.service.SOCKET)
            stream.sendall(struct.pack('!I', len(data)) + data)
            stream.shutdown(socket.SHUT_WR)
            response = self.service.decode(self.service.read_frame(stream))
            self.assertEqual(b'', stream.recv(1))
        self.assertNotIn('error', response, 'Root refused: ' + str(response.get('error')))
        return response

    def wait_probe(self, previous=None):
        path = self.home/'data/key-generation-probe/status.properties'
        deadline = time.monotonic()+55
        while time.monotonic() < deadline:
            if path.is_file():
                values = dict(line.split('=', 1) for line in path.read_text().splitlines() if line and not line.startswith('#') and '=' in line)
                pid = int(values['pid'])
                if pid != previous:
                    actual = self.run_command(['systemctl', 'show', 'kura.service', '--property=MainPID', '--value']).strip()
                    if actual == str(pid):
                        return values
            time.sleep(0.2)
        log = Path('/var/log/kura-console.log')
        tail = log.read_text(errors='replace')[-9000:] if log.is_file() else 'No Core console file'
        self.fail('Real Core provider readiness unavailable: '+tail)

    def assert_providers(self, value):
        for role, expected in self.expected_classes.items():
            self.assertEqual(expected, value[role+'ClassSha256'], role + ' provider/audit facade must match the actual package')
            self.assertEqual('32', value[role+'State'])
        self.assertEqual('32', value['snapshotState'])
        self.assertEqual('true', value['originalDecrypted'])
        self.assertEqual('true', value['currentDecrypted'])

    def test_actual_core_publish_restart_preserves_original_cipher_and_changes_new_key_id(self):
        # Network is disabled by the owning host runner before this test starts Core.
        self.assertFalse(Path('/sys/class/net/eth0').exists(), 'Disconnect the fixture network before Core startup')
        self.step('Starting the real paired Core unit and DS Crypto/configuration probe')
        self.run_command(['systemctl', 'start', 'kura.service'])
        before = self.wait_probe()
        self.assert_providers(before)
        self.assertEqual('false', before['currentHasGeneration'])
        old_pid = int(before['pid'])
        self.assertEqual(self.original_key_hash, self.manager.writer_registration(old_pid)['keySha256'])
        password = uuid.uuid4().hex + uuid.uuid4().hex
        preparation, verification, publication, startup = [str(uuid.uuid4()) for _ in range(4)]
        identifiers = dict(preparation=preparation, verification=verification, publication=publication, startup=startup)
        (self.temporary/'original-ids.json').write_text(json.dumps(identifiers))
        self.step('Preparing the retained generation set and verifying its downloaded encrypted archive')
        prepared = self.rpc(dict(schema=1, action='generation-prepare', operationId=preparation,
                                 passphrase=password, expectedSource=dict(keySha256=self.original_key_hash, ringSha256=None)))
        self.assertEqual('SUCCEEDED', prepared['state'])
        archive = self.temporary/'downloaded-encrypted-backup.json'
        archive.write_text(json.dumps(prepared['backup']))
        verified = self.rpc(dict(schema=1, action='generation-backup-verify', operationId=verification,
                                 preparationId=preparation, expectedRingSha256=prepared['generation']['ringSha256'],
                                 backup=json.loads(archive.read_text()), passphrase=password))
        self.assertEqual('SUCCEEDED', verified['state'])
        plan = self.rpc(dict(schema=1, action='generation-publication-plan', preparationId=preparation,
                            verificationId=verification, expectedRingSha256=prepared['generation']['ringSha256']))
        self.assertEqual(old_pid, plan['corePid'])
        self.step('Publishing once through actual Root/systemd stop, cgroup drain and writer exclusion')
        published = self.rpc(dict(schema=1, action='generation-publish', operationId=publication,
                                 preparationId=preparation, verificationId=verification,
                                 expectedRingSha256=prepared['generation']['ringSha256'], expectedCohortSha256=plan['cohortSha256']))
        self.assertEqual('SUCCEEDED', published['state'], 'Original uncertain publication is never redispatched')
        self.assertEqual('0', self.run_command(['systemctl', 'show', 'kura.service', '--property=MainPID', '--value']).strip())
        self.assertEqual('SUCCEEDED', self.rpc(dict(schema=1, action='operation-read', operationId=publication))['state'])
        self.step('Requesting independent generation start; waiting for real new JVM provider results')
        started = self.rpc(dict(schema=1, action='generation-core-start', operationId=startup,
                               publicationId=publication, expectedRingSha256=published['ringSha256'],
                               expectedCohortSha256=plan['cohortSha256']))
        self.assertEqual('SYSTEMD_JOB_ACCEPTED', started['scope'])
        after = self.wait_probe(previous=old_pid)
        self.assert_providers(after)
        self.assertEqual(before['originalSha256'], after['originalSha256'])
        self.assertEqual('true', after['currentHasGeneration'])
        self.assertEqual(published['activeKeySha256'], after['currentKeyId'])
        self.assertNotEqual(old_pid, int(after['pid']))
        registration = self.manager.writer_registration(int(after['pid']))
        self.assertEqual(published['ringSha256'], registration['ringSha256'])
        self.assertEqual(plan['cohortSha256'], registration['cohortSha256'])
        self.assertEqual(self.initial_operations+4, len(list(self.manager.operations.iterdir())))
        self.run_command(['systemctl', 'stop', 'kura.service'])
        with self.manager.exclusive_writers():
            pass
        self.step('REAL_CORE_GENERATIONS_OK '+json.dumps(dict(realCryptoAndConfigurationProviders=True,
                  snapshotBundleActive=True, oldCipherPreserved=True, oldCipherDecryptedAfterRestart=True,
                  newCipherKeyIdMatches=True, originalCorePid=old_pid, newCorePid=int(after['pid']),
                  originalOperationIds=identifiers, noUnknownRedispatch=True)))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--package-sha256', required=True)
    parser.add_argument('--legacy-baseline', type=Path, required=True)
    parser.add_argument('--java', type=Path, required=True)
    parser.add_argument('--disposable-fixture', action='store_true', required=True)
    OPTIONS, remaining=parser.parse_known_args()
    unittest.main(argv=[sys.argv[0], *remaining])
