#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Disposable Linux Root/FD/JDK21 fixtures, no installed service or mutation replay."""
import argparse
import array
import hashlib
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import threading
import unittest
import uuid
from unittest.mock import Mock, patch

import test_key_generation_cohort as package
import test_key_writer_lease as writer

service = package.service
JAVA = None

SEED = r'''
import java.io.*;
import java.nio.file.*;
import java.util.*;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.*;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.eclipse.kura.internal.xml.marshaller.unmarshaller.XmlJavaComponentConfigurationsMapper;
class Seed {
  public static void main(String[] args) throws Exception {
    Path dir=Path.of(args[0]);
    byte[] ring=Files.readAllBytes(dir.resolve("kura_encryption_keyring"));
    byte[] old=Files.readAllBytes(dir.resolve("old"));
    var legacy=CryptoServiceImpl.forSnapshotRecovery(old,false);
    var current=CryptoServiceImpl.forKeyRingRecovery(ring);
    var cfg=new XmlComponentConfigurations();
    cfg.setConfigurations(List.of(new ComponentConfigurationImpl("test.delegation",null,Map.of(
      "old",new Password(legacy.encryptAes("old-private-canary".toCharArray())),
      "current",new Password(current.encryptAes("new-private-canary".toCharArray()))))));
    var out=new ByteArrayOutputStream();new XmlJavaComponentConfigurationsMapper(current).marshal(out,cfg);
    byte[] xml=out.toByteArray();Files.write(dir.resolve("plain.xml"),xml);
    try(var encrypted=current.aesEncryptingStream(Files.newOutputStream(dir.resolve("current.aes")))){encrypted.write(xml);}
    try(var encrypted=legacy.aesEncryptingStream(Files.newOutputStream(dir.resolve("old.aes")))){encrypted.write(xml);}
  }
}
'''


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Disposable Linux Root and JDK21 required')
class CoreSnapshotValidationTest(unittest.TestCase):
    copy = staticmethod(package.GenerationPackageTest.copy)
    put = staticmethod(writer.WriterLeaseTest.put)
    refused = writer.WriterLeaseTest.refused

    def setUp(self):
        writer.WriterLeaseTest.setUp(self)
        self.component = self.manager.validation_component()
        self.component.runner = self.run_worker
        self.calls = []
        self.input = self.root / 'snapshot'
        self.put(self.input, b'not an XML snapshot')

    def snapshot(self):
        return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_ino, p.stat().st_mode, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
                for directory in (self.directory, self.state)
                for p in directory.rglob('*') if p.is_file()}

    def run_worker(self, arguments, **options):
        self.calls.append(arguments)
        self.assertTrue(options['close_fds'])
        self.assertEqual({'PATH': '/usr/bin:/bin', 'LANG': 'C'}, options['env'])
        self.assertEqual('/', options['cwd'])
        # Test-only rooted package mapping; production always uses its fixed installed paths.
        command = [str(JAVA)] + [str(self.root / a.lstrip('/')) if a.startswith(('/opt/eclipse/kura/', '/etc/kura/')) else a
                                for a in arguments[1:]]
        return subprocess.run(command, **options)

    def info(self):
        return self.manager.handle(dict(schema=1, action='core-validation-info'))

    def request_for(self, path=None, mode='plain'):
        return dict(schema=1, action='core-snapshot-validate', snapshotSha256=hashlib.sha256((path or self.input).read_bytes()).hexdigest(),
                    mode=mode, passwordPolicy='authenticated', expectedBindingSha256=self.info()['bindingSha256'])

    def validate(self, request=None, path=None):
        with (path or self.input).open('rb') as source:
            return self.component.validate(request or self.request_for(path), source.fileno(), os.geteuid())

    def seed(self):
        old = secrets.token_bytes(16)
        raw = service.encode_key_generations([old, self.key], 1, 0)
        _, metadata = service.key_generations(raw)
        self.put(self.directory / 'kura_encryption_keyring', raw)
        self.put(self.directory / 'key-generations.json', service.encode(dict(schema=1, purpose=service.GENERATION_FORMAT, **metadata)))
        self.put(self.directory / 'old', old)
        source = self.root / 'Seed.java'; source.write_text(SEED)
        worker = self.home / 'libexec/key-recovery/kura-offline-recovery.jar'
        classpath = str(worker) + ':' + str(worker.parent / 'lib/*')
        compile_result = subprocess.run([str(JAVA.parent / 'javac'), '-cp', classpath, str(source)], capture_output=True, timeout=20)
        self.assertEqual(0, compile_result.returncode, compile_result.stderr.decode()[-2000:])
        result = subprocess.run([str(JAVA), '-Xmx128m', '-cp', str(self.root) + ':' + classpath, 'Seed', str(self.directory)],
                                capture_output=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr.decode()[-2000:])
        self.assertEqual(b'', result.stdout)
        for name in ('plain.xml', 'current.aes', 'old.aes'):
            (self.directory / name).chmod(0o600)

    def test_info_exposes_fingerprints_only_and_creates_no_journal(self):
        before = self.snapshot()
        result = self.info()
        self.assertEqual('CORE_CREDENTIALS_READY', result['state'])
        self.assertEqual(self.binding['keySha256'], result['binding']['activeKeySha256'])
        self.assertIsNone(result['binding']['ringSha256'])
        self.assertEqual(hashlib.sha256(service.encode(result['binding'])).hexdigest(), result['bindingSha256'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual([], self.calls)

    def test_real_worker_decrypts_old_and_new_generations_without_exposing_keys_or_passwords(self):
        self.seed()
        before = self.snapshot()
        for name, mode in (('plain.xml', 'plain'), ('current.aes', 'aes-gcm'), ('old.aes', 'aes-gcm')):
            path = self.directory / name
            with path.open('rb') as source:
                source.seek(3)
                result = self.component.validate(self.request_for(path, mode), source.fileno(), os.geteuid())
                self.assertEqual(3, source.tell(), 'pread must preserve the input FD offset')
            self.assertEqual('CORE_SNAPSHOT_VALIDATED', result['state'])
            self.assertEqual(2, result['report']['authenticatedPasswordCount'])
            self.assertFalse(result['report']['fullRecoveryVerified'])
            self.assertNotIn(b'private-canary', service.encode(result))
            self.assertNotIn(self.key, service.encode(result))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(3, len(self.calls))
        self.assertTrue(all('--keyring-file' in args and '--key-file' not in args for args in self.calls))

    def test_invalid_artifact_and_mismatched_fingerprint_refuse_without_mutation(self):
        before = self.snapshot()
        self.refused('VALIDATION_REJECTED', self.validate)
        self.assertEqual(before, self.snapshot())
        for patch_value in (dict(snapshotSha256='0' * 64), dict(expectedBindingSha256='1' * 64)):
            self.refused('CONFLICT', lambda: self.validate(dict(self.request_for(), **patch_value)))
        self.assertEqual(1, len(self.calls))
        self.assertEqual(before, self.snapshot())

    def test_input_is_private_single_link_regular_bounded_and_readonly(self):
        request = self.request_for()
        with self.input.open('rb+') as writable:
            self.refused('UNSAFE_VALIDATION_INPUT', lambda: self.component.validate(request, writable.fileno(), 0))
        self.input.chmod(0o644)
        self.refused('UNSAFE_VALIDATION_INPUT', self.validate)
        self.input.chmod(0o600)
        os.link(self.input, self.root / 'alias')
        self.refused('UNSAFE_VALIDATION_INPUT', self.validate)
        (self.root / 'alias').unlink()
        with self.input.open('rb') as source:
            self.refused('UNSAFE_VALIDATION_INPUT', lambda: self.component.validate(request, source.fileno(), 65534))
        self.put(self.input, b'')
        self.refused('UNSAFE_VALIDATION_INPUT', self.validate)
        self.assertEqual([], self.calls)

    def test_timeout_and_invalid_report_fail_closed_without_journals_or_forwarded_output(self):
        self.component.runner = Mock(side_effect=subprocess.TimeoutExpired('fixed-worker', 35))
        self.refused('VALIDATION_UNAVAILABLE', self.validate)
        for output in (b'{"unexpected":"private-canary"}', b'not-json', b'x' * 4097):
            self.component.runner = Mock(return_value=subprocess.CompletedProcess([], 0, output, b''))
            with self.assertRaises(service.Failure): self.validate()
        self.assertEqual([], list((self.state / 'operations').iterdir()))

    def test_attested_helper_change_refuses_while_base_cold_recovery_remains_available(self):
        path = self.home / 'bin/kura_key_validation.py'
        path.write_bytes(path.read_bytes() + b'\n# changed\n')
        self.refused('COHORT_UNAVAILABLE', self.info)
        self.assertEqual(2, self.policy.assets()['protocol'])

    def test_original_unresolved_intent_blocks_readonly_validation_without_settlement(self):
        starts=self.state / 'startups'; starts.mkdir(mode=0o700)
        identity=str(uuid.uuid4())
        self.put(starts / (identity+'.json'),service.encode(dict(schema=1,operationId=identity,
                 restoreOperationId=str(uuid.uuid4()),keySha256=self.binding['keySha256'],
                 requestTag='1'*64,state='INTENT',response=None)))
        before=self.snapshot()
        self.refused('UNRESOLVED_OPERATION',self.info)
        self.assertEqual(before,self.snapshot());self.assertEqual([],self.calls)

    def test_changed_snapshot_is_rejected_after_worker_and_temporary_copy_is_removed(self):
        request=self.request_for()
        paths=[]
        def worker(arguments,**_):
            paths.append(Path(arguments[arguments.index('--input')+1]))
            self.input.write_bytes(b'changed after copy')
            report=dict(schema=1,artifactSha256=request['snapshotSha256'],mode='plain',configurationCount=1,
                        factoryCount=0,propertyCount=0,passwordValueCount=0,authenticatedPasswordCount=0,
                        legacyPasswordCount=0,keyAuthenticated=False,fullRecoveryVerified=False)
            return subprocess.CompletedProcess(arguments,0,service.encode(report),b'')
        self.component.runner=worker
        self.refused('CONFLICT',lambda:self.validate(request))
        self.assertTrue(paths);self.assertTrue(all(not p.exists() for p in paths))
        self.assertEqual([],list((self.state/'operations').iterdir()))


@unittest.skipUnless(sys.platform == 'linux', 'Linux SCM_RIGHTS and MSG_CMSG_CLOEXEC required')
class CoreValidationFrameTest(unittest.TestCase):
    def receive(self, write):
        left, right = socket.socketpair()
        left.settimeout(2); right.settimeout(2)
        def send():
            try: write(left)
            finally: left.close()
        thread = threading.Thread(target=send); thread.start()
        try: return service.read_request_frame(right)
        finally: right.close(); thread.join(timeout=3)

    def test_fragmented_header_and_fd_at_payload_are_received_once_cloexec(self):
        with open(__file__, 'rb') as source:
            data = service.encode(dict(schema=1, action='core-snapshot-validate'))
            def write(stream):
                stream.sendall(struct.pack('!I', len(data))[:2]); stream.sendall(struct.pack('!I', len(data))[2:])
                stream.sendmsg([data], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [source.fileno()]))])
            request, fd = self.receive(write)
            try:
                self.assertEqual('core-snapshot-validate', request['action'])
                self.assertFalse(os.get_inheritable(fd))
                self.assertEqual(os.fstat(source.fileno()).st_ino, os.fstat(fd).st_ino)
            finally: os.close(fd)

    def test_malformed_extra_and_truncated_descriptor_requests_leak_no_fd(self):
        with open(__file__, 'rb') as source:
            data = service.encode(dict(schema=1, action='status'))
            for count in (2, 8):
                before = len(os.listdir('/proc/self/fd'))
                def write(stream):
                    stream.sendmsg([struct.pack('!I', len(data)) + data],
                        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [source.fileno()] * count))])
                with self.assertRaises(service.Failure): self.receive(write)
                self.assertEqual(before, len(os.listdir('/proc/self/fd')))

    def test_agent_peer_cannot_enter_admin_backup_writer_or_start_protocol(self):
        manager = Mock()
        with patch.object(service, 'agent_peer', return_value=True):
            for action in ('backup-create', 'restore', 'generation-publish', 'core-start', 'writer-lease-acquire'):
                with self.assertRaises(service.Failure) as caught:
                    service.serve_request(manager, dict(schema=1, action=action), 1, 0, 100, 101, None)
                self.assertEqual('FORBIDDEN', caught.exception.reason)
        manager.assert_not_called()
        manager.handle.assert_not_called()
        manager.acquire_writer_lease.assert_not_called()

    def test_descriptors_are_for_validation_only_and_recovery_peer_is_not_authorized(self):
        with patch.object(service, 'agent_peer', return_value=False):
            for request, uid, fd in ((dict(action='status'), 0, 8), (dict(action='core-snapshot-validate'), 0, None),
                                      (dict(action='core-snapshot-validate'), 101, 8)):
                with self.assertRaises(service.Failure): service.serve_request(Mock(), request, 1, uid, 100, 101, fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    config, remaining = parser.parse_known_args()
    package.CONFIG = config.repository.resolve(); JAVA = config.java.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
