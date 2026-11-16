#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh installed Core/Root worker: actual partial rename failure and continuation.

Only installation/probe helpers are shared with the historical success test;
its test method is never called. No existing gateway or old operation is adopted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import struct
import sys
import unittest
import uuid

import test_key_generation_core_systemd as install


OPTIONS = None


class InstalledPublicationRecoveryTest(unittest.TestCase):
    step = install.CoreGenerationTest.step
    run_command = install.CoreGenerationTest.run_command
    install_probe = install.CoreGenerationTest.install_probe
    rpc = install.CoreGenerationTest.rpc
    wait_probe = install.CoreGenerationTest.wait_probe

    def setUp(self):
        if OPTIONS is None:
            self.skipTest('Requires explicit fresh installed-Core fixture')
        install.OPTIONS = OPTIONS
        install.CoreGenerationTest.setUp(self)
        self.assertIsNotNone(shutil.which('nsenter'))
        self.assertIsNotNone(shutil.which('mount'))
        self.assertEqual(0, self.initial_operations)

    @staticmethod
    def metadata(path):
        value = path.lstat()
        return dict(inode=value.st_ino, device=value.st_dev, uid=value.st_uid, gid=value.st_gid,
                    mode=stat.S_IMODE(value.st_mode), nlink=value.st_nlink,
                    mtimeNs=value.st_mtime_ns, ctimeNs=value.st_ctime_ns,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def original(self, action):
        identity = str(uuid.uuid4())
        path = Path('/run/publication-recovery-original-ids.json')
        items = json.loads(path.read_bytes()) if path.exists() else []
        items.append(dict(operationId=identity, action=action))
        path.write_bytes(json.dumps(items).encode())
        return identity

    def raw_rpc(self, request):
        data = self.service.encode(request)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            stream.settimeout(75)
            stream.connect(self.service.SOCKET)
            stream.sendall(struct.pack('!I', len(data)) + data)
            stream.shutdown(socket.SHUT_WR)
            response = self.service.decode(self.service.read_frame(stream))
            self.assertEqual(b'', stream.recv(1))
        return response  # One dispatch. A lost original response is never retried.

    def test_actual_partial_publication_continues_original_without_stop_or_start_redispatch(self):
        key_path = Path('/etc/kura/credentials/kura_encryption_key')
        # The disposable self-bind preserves the original inode/content while
        # making rename-over-key return actual EBUSY. No production fault hook.
        self.run_command(['systemctl', 'stop', 'kura-key-service.service', 'kura-key-service.socket'])
        self.run_command(['systemctl', 'start', 'kura-key-service.socket'])
        self.rpc(dict(schema=1, action='status'))  # Socket-activation readiness barrier.
        key_pid = self.run_command(['systemctl', 'show', 'kura-key-service.service', '-p', 'MainPID', '--value']).strip()
        # Inject after the sandbox's directory mounts exist, into this worker
        # namespace only. A parent bind can be hidden by ReadWritePaths.
        self.run_command(['nsenter', '--target', key_pid, '--mount', '--root', '--wd=/', '--',
                          'mount', '--bind', key_path, key_path])
        old_key = self.metadata(key_path)
        self.run_command(['systemctl', 'start', 'kura.service'])
        observed = self.wait_probe()
        self.assertEqual('true', observed['originalDecrypted'])
        data_path = self.home / 'data/key-generation-probe/original.cipher'
        original_data = self.metadata(data_path)
        source = dict(keySha256=self.original_key_hash, ringSha256=None)
        password = 'Only a disposable installed recovery fixture 21!'
        preparation = self.original('generation-prepare')
        prepared = self.rpc(dict(schema=1, action='generation-prepare', operationId=preparation,
                                 expectedSource=source, passphrase=password))
        self.assertEqual('SUCCEEDED', prepared['state'])
        verification = self.original('generation-backup-verify')
        self.assertEqual('SUCCEEDED', self.rpc(dict(schema=1, action='generation-backup-verify', operationId=verification,
            preparationId=preparation, expectedRingSha256=prepared['generation']['ringSha256'],
            backup=prepared['backup'], passphrase=password))['state'])
        plan = self.rpc(dict(schema=1, action='generation-publication-plan', preparationId=preparation,
                             verificationId=verification, expectedRingSha256=prepared['generation']['ringSha256']))
        self.assertEqual(int(observed['pid']), plan['corePid'])
        publication = self.original('generation-publish')
        reply = self.raw_rpc(dict(schema=1, action='generation-publish', operationId=publication,
                                  preparationId=preparation, verificationId=verification,
                                  expectedRingSha256=prepared['generation']['ringSha256'],
                                  expectedCohortSha256=plan['cohortSha256']))
        self.assertEqual('UNKNOWN', reply.get('error'))
        original = self.rpc(dict(schema=1, action='operation-read', operationId=publication))
        self.assertEqual('UNKNOWN', original['state'])
        self.assertEqual(old_key, self.metadata(key_path))
        ring_path = Path('/etc/kura/credentials/kura_encryption_keyring')
        self.assertTrue(ring_path.is_file())
        ring_before = self.metadata(ring_path)
        self.assertFalse(Path('/etc/kura/credentials/key-generations.json').exists())
        self.assertEqual('inactive', self.run_command(['systemctl', 'show', 'kura.service', '-p', 'ActiveState', '--value']).strip())
        self.assertEqual('0', self.run_command(['systemctl', 'show', 'kura.service', '-p', 'MainPID', '--value']).strip())
        info = self.rpc(dict(schema=1, action='generation-publication-read', operationId=publication))
        self.assertEqual('UNKNOWN', info['state'])
        self.assertFalse(info['startupAuthorized'])
        self.assertEqual(64, len(info['recoveryReceiptSha256']))
        directory = Path('/var/lib/kura-key-service/generations') / preparation
        immutable = {path.name: self.metadata(path) for path in directory.iterdir() if path.is_file()}
        self.assertGreater(int(key_pid), 1)
        self.step('Restarting only this fixture key worker; original checkpoint must survive and no Core dispatch is repeated')
        self.run_command(['systemctl', 'restart', 'kura-key-service.service'])
        after_restart = self.rpc(dict(schema=1, action='generation-publication-read', operationId=publication))
        self.assertEqual(info, after_restart)
        original_key_pid = key_pid
        key_pid = self.run_command(['systemctl', 'show', 'kura-key-service.service', '-p', 'MainPID', '--value']).strip()
        self.assertNotEqual(original_key_pid, key_pid)
        self.assertEqual(old_key, self.metadata(key_path))
        completed = self.rpc(dict(schema=1, action='generation-publication-recover', operationId=publication,
                                  expectedRecoveryReceiptSha256=info['recoveryReceiptSha256']))
        self.assertEqual('SUCCEEDED', completed['state'])
        self.assertEqual(publication, completed['operationId'])
        self.assertTrue(completed['coreStopped'])
        self.assertTrue(completed['requiresExplicitStart'])
        self.assertEqual(ring_before, self.metadata(ring_path))
        self.assertEqual(immutable, {name: self.metadata(directory / name) for name in immutable})
        self.assertEqual(original_data, self.metadata(data_path))
        self.assertEqual(old_key['sha256'], self.metadata(directory / 'source-active-key')['sha256'])
        self.assertEqual('0', self.run_command(['systemctl', 'show', 'kura.service', '-p', 'MainPID', '--value']).strip())
        self.assertEqual(key_pid, self.run_command(['systemctl', 'show', 'kura-key-service.service', '-p', 'MainPID', '--value']).strip())
        admission = self.raw_rpc(dict(schema=1, action='credential-start-admission',
                                      keySha256=prepared['generation']['activeKeySha256'],
                                      ringSha256=prepared['generation']['ringSha256']))
        self.assertEqual('GENERATION_START_REQUIRED', admission.get('error'))
        operations = list(Path('/var/lib/kura-key-service/operations').iterdir())
        self.assertEqual(3, len(operations))
        self.assertTrue(all(json.loads(path.read_bytes())['state'] == 'SUCCEEDED' for path in operations))
        self.assertEqual([], list(Path('/var/lib/kura-key-service/startups').iterdir()))
        status = dict(line.split(':', 1) for line in Path('/proc/' + key_pid + '/status').read_text().splitlines() if ':' in line)
        for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
            self.assertEqual(0, int(status[name].strip(), 16))
        self.assertEqual('1', status['NoNewPrivs'].strip())
        self.run_command(['systemctl', 'stop', 'kura-key-service.service', 'kura-key-service.socket'])
        print('PUBLICATION_RECOVERY_SYSTEMD_OK ' + json.dumps(dict(
            schema=1, scope='fresh-installed-core-real-partial-publication-continuation',
            packageSha256=OPTIONS.package_sha256, actualInstalledCore=True, actualRootWorker=True,
            actualKernelBindRenameFailure=True, originalUnknownObserved=True, sameOriginalPublicationCompleted=True,
            originalOperations=3, stopRedispatched=False, startDispatched=False, keyWorkerRestarted=True,
            originalAuthenticatedCheckpointSurvivesWorkerRestart=True,
            existingRingInodePreserved=True, immutableOriginalMaterialPreserved=True,
            oldCipherFullMetadataUnchanged=True, oldKeyRetained=True, startupStillRequiresSeparateAuthorization=True,
            rootWorkerCapabilitiesEmpty=True, noNewPrivileges=True, hardPowerOrDiskFullAccepted=False,
            customerProvidersAccepted=False, guiAccepted=False), sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--package-sha256', required=True)
    parser.add_argument('--legacy-baseline', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--disposable-fixture', required=True, action='store_true')
    OPTIONS, remaining = parser.parse_known_args()
    unittest.main(argv=[sys.argv[0], *remaining])
