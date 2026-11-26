#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Disposable credentials and real Linux FD/JDK21 leases; never start installed Core."""
import argparse
import array
import fcntl
import hashlib
import os
from pathlib import Path
import secrets
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import test_key_generation_cohort as package

service = package.service
import kura_key_store as policy
JAVA = None


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Requires disposable Linux Root and JDK21')
class WriterLeaseTest(unittest.TestCase):
    copy = staticmethod(package.GenerationPackageTest.copy)

    def setUp(self):
        package.GenerationPackageTest.setUp(self)
        self.directory = self.root / 'etc/kura/credentials'
        self.directory.mkdir(parents=True, mode=0o700)
        self.state = self.root / 'var/lib/kura-key-service'
        (self.state / 'operations').mkdir(parents=True, mode=0o700)
        (self.root / 'run/kura-key-service').mkdir(parents=True, mode=0o755)
        self.key = secrets.token_bytes(32)
        self.binding = dict(keySha256=hashlib.sha256(self.key).hexdigest(), ringSha256=None)
        self.put(self.directory / 'kura_encryption_key', self.key, 0o400)
        self.put(self.directory / 'provisioned.json', service.encode(dict(schema=1, origin='fresh',
                 legacyKey=False, keySha256=self.binding['keySha256'], unitDigests=[])))
        self.put(self.directory / '.provision.lock', b'')
        self.put(self.state / 'admission.lock', b'')
        self.put(self.state / 'journal.key', secrets.token_bytes(32))
        self.manager = service.Manager(self.root)
        self.request = dict(schema=1, action='writer-lease-acquire', **self.binding)

    @staticmethod
    def put(path, data, mode=0o600):
        path.write_bytes(data)
        path.chmod(mode)

    def acquire(self, request=None):
        return self.manager.acquire_writer_lease(self.request if request is None else request, os.getpid(), os.geteuid())

    def refused(self, reason, call):
        with self.assertRaises(service.Failure) as failure:
            call()
        self.assertEqual(reason, failure.exception.reason)

    def exclusive(self, manager=None):
        with (self.manager if manager is None else manager).exclusive_writers():
            pass

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
                for base in (self.directory, self.state) for p in base.rglob('*') if p.is_file()}

    def test_empty_read_only_lease_blocks_publish_and_survives_broker_instance(self):
        before = self.snapshot()
        response, descriptor = self.acquire()
        try:
            self.assertEqual('WRITER_LEASE_GRANTED', response['state'])
            metadata = os.fstat(descriptor)
            self.assertEqual((0, 1, 0o600, 0), (metadata.st_uid, metadata.st_nlink, stat.S_IMODE(metadata.st_mode), metadata.st_size))
            self.assertEqual(os.O_RDONLY, fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE)
            with self.assertRaises(OSError):
                os.write(descriptor, b'not-key-material')
            self.refused('WRITERS_ACTIVE', self.exclusive)
            other = service.Manager(self.root)
            self.refused('WRITERS_ACTIVE', lambda: self.exclusive(other))
            self.assertEqual(self.binding['keySha256'], other.writer_registration(os.getpid())['keySha256'])
        finally:
            os.close(descriptor)
        self.exclusive()
        self.assertEqual(before, self.snapshot())
        self.refused('WRITER_ALREADY_REGISTERED', self.acquire)

    def test_publication_exclusion_refuses_new_writer_without_registration(self):
        fd = self.manager.writer_lock(create=True)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.refused('WRITERS_FENCED', self.acquire)
            self.assertEqual(['lease.lock'], sorted(p.name for p in self.manager.writer_directory().iterdir()))
        finally:
            os.close(fd)

    def test_cold_boot_maintenance_creates_only_volatile_lock_and_fences_new_writers(self):
        before = self.snapshot()
        self.assertFalse((self.root / 'run/kura-key-service/writers').exists())
        with self.manager.exclusive_writers() as metadata:
            original = metadata.st_ino
            self.assertEqual((0, 1, 0o600, 0),
                             (metadata.st_uid, metadata.st_nlink, stat.S_IMODE(metadata.st_mode), metadata.st_size))
            self.refused('WRITERS_FENCED', self.acquire)
            self.assertEqual(['lease.lock'], sorted(p.name for p in self.manager.writer_directory().iterdir()))
        with service.Manager(self.root).exclusive_writers() as metadata:
            self.assertEqual(original, metadata.st_ino)
        self.assertEqual(before, self.snapshot())

    def test_cold_boot_maintenance_keeps_pending_while_ordinary_writer_stays_refused(self):
        self.put(self.state / 'provider-rewrap-pending.json', b'original pending intent')
        before = self.snapshot()
        with self.manager.exclusive_writers():
            self.refused('UNRESOLVED_OPERATION', self.acquire)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(['lease.lock'], sorted(p.name for p in self.manager.writer_directory().iterdir()))

    def test_lease_binds_exact_package_and_launcher_bytes_before_exec(self):
        expected = self.policy.generation_assets()['cohortSha256']
        response, descriptor = self.acquire()
        try:
            self.assertEqual(expected, response['cohortSha256'])
            path = self.home / 'bin/start_kura_background.sh'
            path.write_bytes(path.read_bytes().replace(b'1024m', b'768m'))
            self.assertNotEqual(expected, self.policy.generation_assets()['cohortSha256'])
            self.assertEqual(expected, self.manager.writer_registration(os.getpid())['cohortSha256'])
        finally:
            os.close(descriptor)

    def test_wrong_loaded_key_or_ring_refuses_before_creating_runtime_state(self):
        before = self.snapshot()
        for changed in (dict(keySha256='0' * 64), dict(ringSha256='1' * 64)):
            self.refused('CONFLICT', lambda: self.acquire(dict(self.request, **changed)))
        self.assertFalse((self.root / 'run/kura-key-service/writers').exists())
        self.assertEqual(before, self.snapshot())

    def test_original_unknown_start_refuses_lease_and_keeps_all_journals(self):
        starts = self.state / 'startups'
        starts.mkdir(mode=0o700)
        identity = str(uuid.uuid4())
        self.put(starts / (identity + '.json'), service.encode(dict(schema=1, operationId=identity,
                 restoreOperationId=str(uuid.uuid4()), keySha256=self.binding['keySha256'],
                 requestTag='1' * 64, state='INTENT', response=None)))
        before = self.snapshot()
        self.refused('UNRESOLVED_OPERATION', self.acquire)
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.root / 'run/kura-key-service/writers').exists())

    def test_damaged_package_refuses_even_single_key_writer_but_keeps_cold_base(self):
        (self.home / self.generation['readers']['crypto']).unlink()
        self.assertEqual(2, self.policy.assets()['protocol'])
        self.refused('COHORT_UNAVAILABLE', self.acquire)
        self.assertFalse((self.root / 'run/kura-key-service/writers').exists())

    def test_stale_runtime_cache_is_pruned_without_settling_operation_results(self):
        response, descriptor = self.acquire()
        os.close(descriptor)
        root = self.manager.writer_directory()
        path = root / (str(os.getpid()) + '-' + response['startTicks'] + '.json')
        value = service.decode(path.read_bytes())
        value['bootId'] = str(uuid.uuid4())
        self.put(path, service.encode(value))
        before = self.snapshot()
        _, descriptor = self.acquire()
        os.close(descriptor)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(Path('/proc/sys/kernel/random/boot_id').read_text().strip(), service.decode(path.read_bytes())['bootId'])

    def test_malformed_runtime_record_is_preserved_and_refused(self):
        response, descriptor = self.acquire()
        os.close(descriptor)
        root = self.manager.writer_directory()
        path = root / (str(os.getpid()) + '-' + response['startTicks'] + '.json')
        value = service.decode(path.read_bytes())
        value.update(uid=True, bootId='invalid')
        self.put(path, service.encode(value))
        before = path.read_bytes()
        self.refused('UNSAFE_WRITER_STATE', self.acquire)
        self.assertEqual(before, path.read_bytes())

    def test_nonempty_linked_or_exposed_coordinator_is_not_replaced(self):
        fd = self.manager.writer_lock(create=True)
        os.close(fd)
        path = self.manager.writer_directory() / 'lease.lock'
        inode = path.stat().st_ino
        path.write_bytes(b'foreign-state')
        self.refused('UNSAFE_WRITER_STATE', self.acquire)
        self.refused('UNSAFE_WRITER_STATE', self.exclusive)
        self.assertEqual(inode, path.stat().st_ino)
        path.write_bytes(b'')
        path.chmod(0o644)
        self.refused('UNSAFE_WRITER_STATE', self.acquire)
        self.refused('UNSAFE_WRITER_STATE', self.exclusive)
        path.chmod(0o600)
        os.link(path, path.parent / 'foreign-hardlink')
        self.refused('UNSAFE_WRITER_STATE', self.acquire)
        self.refused('UNSAFE_WRITER_STATE', self.exclusive)
        self.assertEqual(inode, path.stat().st_ino)

    def broker(self, sender=None):
        path = Path(service.SOCKET)
        self.assertTrue(path.parent.is_dir(), 'Use the disposable test /run tmpfs')
        self.assertFalse(os.path.lexists(path), 'Never connect to or remove an existing service socket')
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        listener.listen(1)
        listener.settimeout(10)
        errors = []
        def serve_one():
            descriptor = None
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(5)
                    pid, uid, _ = service.peer(connection)
                    request = service.decode(service.read_frame(connection))
                    self.assertEqual(b'', connection.recv(1))
                    response, descriptor = self.manager.acquire_writer_lease(request, pid, uid)
                    (service.send_descriptor_frame if sender is None else sender)(connection, response, descriptor)
            except BaseException as error:
                errors.append(error)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        thread = threading.Thread(target=serve_one, daemon=True)
        thread.start()
        def finish():
            listener.close()
            thread.join(11)
            if path.exists():
                path.unlink()
            self.assertFalse(thread.is_alive())
            if errors:
                raise errors[0]
        self.addCleanup(finish)
        return thread

    def test_multiple_received_descriptors_are_closed_before_refusal(self):
        def send_multiple(connection, response, descriptor):
            data = service.encode(response)
            connection.sendmsg([struct.pack('!I', len(data)) + data],
                               [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [descriptor, descriptor]))])
        thread = self.broker(send_multiple)
        descriptors = len(list(Path('/proc/self/fd').iterdir()))
        with self.assertRaises(policy.Refused):
            policy.root_exchange(self.request, descriptor=True)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(descriptors, len(list(Path('/proc/self/fd').iterdir())))
        self.exclusive()

    def test_grant_without_received_descriptor_refuses_start(self):
        thread = self.broker(lambda connection, response, _: service.send_frame(connection, response))
        with self.assertRaises(policy.Refused):
            policy.root_exchange(self.request, descriptor=True)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.exclusive()

    def test_mismatched_response_binding_never_executes_java_and_releases_descriptor(self):
        def send_wrong_binding(connection, response, descriptor):
            service.send_descriptor_frame(connection, dict(response, keySha256='0' * 64), descriptor)
        thread = self.broker(send_wrong_binding)
        with patch.dict(os.environ, CREDENTIALS_DIRECTORY=str(self.directory)), patch.object(os, 'execvp') as execute:
            with self.assertRaises(policy.Refused):
                policy.exec_java(['-version'])
            execute.assert_not_called()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.exclusive()

    def test_actual_isolated_python_exec_and_jdk21_hold_lease_until_jvm_exit(self):
        probe = self.root / 'LeaseProbe.java'
        probe.write_text('import java.nio.file.*; class LeaseProbe { public static void main(String[] a) throws Exception {'
                         'Files.writeString(Path.of(a[0]), Long.toString(ProcessHandle.current().pid())); System.in.read(); }}')
        marker = self.root / 'jvm-started'
        env = dict(os.environ, CREDENTIALS_DIRECTORY=str(self.directory), PATH=str(JAVA.parent) + ':/usr/bin:/bin')
        thread = self.broker()
        process = subprocess.Popen([sys.executable, '-I', '-B', str(self.home / 'bin/kura_key_store.py'),
                                    'exec-java', '-Xms16m', '-Xmx96m', str(probe), str(marker)],
                                   env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 15
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if not marker.exists() and process.poll() is not None:
                _, errors = process.communicate(timeout=5)
                self.fail('Managed JVM failed before main: ' + errors.decode())
            self.assertTrue(marker.exists(), 'Managed JVM did not reach main')
            self.assertEqual(process.pid, int(marker.read_text()), 'exec must preserve the systemd/PIDFile PID')
            thread.join(2)
            self.assertFalse(thread.is_alive(), 'Root must release its descriptor after SCM_RIGHTS transfer')
            self.refused('WRITERS_ACTIVE', self.exclusive)
            self.refused('WRITERS_ACTIVE', lambda: self.exclusive(service.Manager(self.root)))
            self.assertEqual(self.binding['keySha256'], self.manager.writer_registration(process.pid)['keySha256'])
            process.stdin.close()
            process.stdin = None
            output, errors = process.communicate(timeout=10)
            self.assertEqual(0, process.returncode, errors.decode())
            self.assertEqual(b'', output)
            self.exclusive()
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--java', type=Path, required=True)
    args, remaining = parser.parse_known_args()
    package.CONFIG = args.repository.resolve()
    JAVA = args.java.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
