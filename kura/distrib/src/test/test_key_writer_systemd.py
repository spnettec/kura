#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""One fresh disposable systemd container, real Root socket and unprivileged JDK21.

This validates the lease sandbox, not a Core/provider boot or generation publication.
All fixed destinations must be absent before the fixture installs any files.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import unittest

import test_key_generation_cohort as package
import test_key_writer_lease as writer

service = package.service
JAVA = None
CORE_CAPABILITIES = False


class SystemdWriterTest(unittest.TestCase):
    copy = staticmethod(package.GenerationPackageTest.copy)
    put = staticmethod(writer.WriterLeaseTest.put)

    def command(self, *arguments):
        return subprocess.run(list(arguments), check=True, capture_output=True, text=True, timeout=30).stdout

    def setUp(self):
        self.assertEqual('linux', sys.platform)
        self.assertEqual(0, os.geteuid())
        self.assertTrue(Path('/.dockerenv').is_file(), 'Only a fresh disposable container is allowed')
        self.assertEqual('systemd', Path('/proc/1/comm').read_text().strip())
        destinations = ['/opt/eclipse/kura', '/etc/kura', '/var/lib/kura-key-service',
                        '/etc/systemd/system/kura.service.d', '/etc/systemd/system/kura-lease-probe.service',
                        '/run/kura-key-service']
        destinations += ['/lib/systemd/system/' + n for n in (*getattr(package.lifecycle, "NATIVE_VALIDATION_UNITS", package.lifecycle.UNITS), 'kura.service')]
        self.assertFalse(any(os.path.lexists(p) for p in destinations), 'Existing Kura files or state must never be adopted or changed')
        writer.WriterLeaseTest.setUp(self)
        self.policy.leave()
        for source, destination in ((self.home, Path('/opt/eclipse/kura')),
                                    (self.directory.parent, Path('/etc/kura')),
                                    (self.state, Path('/var/lib/kura-key-service')),
                                    (self.root / 'etc/systemd/system/kura.service.d', Path('/etc/systemd/system/kura.service.d'))):
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            shutil.move(str(source), str(destination))
        self.home = Path('/opt/eclipse/kura')
        self.home.parent.chmod(0o755)
        for path in [self.home, *self.home.rglob('*')]:
            path.chmod(0o755 if path.is_dir() else 0o644)
        for name in (*getattr(package.lifecycle, "NATIVE_VALIDATION_UNITS", package.lifecycle.UNITS), 'kura.service'):
            self.copy(self.root / 'lib/systemd/system' / name, Path('/lib/systemd/system') / name)
        self.command('/usr/sbin/groupadd', '--system', 'kura-key-control')
        self.command('/usr/sbin/useradd', '--system', '--user-group', '--no-create-home',
                     '--shell', '/usr/sbin/nologin', '--groups', 'kura-key-control', 'kurad')
        self.manager = service.Manager()
        source = self.home / 'libexec/LeaseProbe.java'
        source.write_text('import java.nio.file.*; import java.util.concurrent.*; class LeaseProbe {'
                          'public static void main(String[] a) throws Exception {'
                          'Files.writeString(Path.of(a[0]),Long.toString(ProcessHandle.current().pid()));'
                          'new CountDownLatch(1).await(); }}')
        source.chmod(0o644)
        unit = '''[Unit]
Requires=kura-key-service.socket
After=kura-key-service.socket
[Service]
User=kurad
Group=kurad
SupplementaryGroups=kura-key-control
RuntimeDirectory=kura-lease-probe
RuntimeDirectoryMode=0700
Environment=PATH=/java/bin:/usr/bin:/bin
ExecStart=/usr/bin/python3 -I -B /opt/eclipse/kura/bin/kura_key_store.py exec-java -Xms16m -Xmx96m /opt/eclipse/kura/libexec/LeaseProbe.java /run/kura-lease-probe/ready
LoadCredential=kura_encryption_key:/etc/kura/credentials/kura_encryption_key
NoNewPrivileges=true
CapabilityBoundingSet=
AmbientCapabilities=
ProtectSystem=strict
ReadOnlyPaths=/opt/eclipse /etc/kura /run/kura-key-service
InaccessiblePaths=/etc/kura/credentials /var/lib/kura-key-service
PrivateTmp=true
MemoryMax=192M
KillMode=control-group
'''
        if CORE_CAPABILITIES:
            source_unit = (package.SOURCE / 'filtered/pkg/install/kura.service').read_text().splitlines()
            for setting in ('AmbientCapabilities=', 'CapabilityBoundingSet='):
                values = [line for line in source_unit if line.startswith(setting)]
                self.assertEqual(1, len(values))
                unit = unit.replace(setting+'\n', values[0]+'\n')
            unit = unit.replace('NoNewPrivileges=true', 'NoNewPrivileges=false')
            wrapper = self.home / 'libexec/exec-lease-probe.py'
            wrapper.write_text('import json, os, sys\n'
                               'print("LEASE_KERNEL_METADATA " + json.dumps(dict(procOwner=os.stat("/proc/self").st_uid, effectiveUid=os.geteuid())), flush=True)\n'
                               'os.execv("/usr/bin/python3", ["python3", "-I", "-B", "/opt/eclipse/kura/bin/kura_key_store.py", "exec-java", *sys.argv[1:]])\n')
            wrapper.chmod(0o644)
            unit = unit.replace('/opt/eclipse/kura/bin/kura_key_store.py exec-java', str(wrapper))
        Path('/etc/systemd/system/kura-lease-probe.service').write_text(unit)
        self.command('/usr/bin/systemctl', 'daemon-reload')
        self.command('/usr/bin/systemctl', 'start', 'kura-key-service.socket')
        self.probe_stopped = False
        self.addCleanup(self.stop_owned_probe)

    def stop_owned_probe(self):
        if not self.probe_stopped:
            self.command('/usr/bin/systemctl', 'stop', 'kura-lease-probe.service')
            self.probe_stopped = True

    def rpc(self, request):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            stream.settimeout(5)
            stream.connect(service.SOCKET)
            service.send_frame(stream, request)
            stream.shutdown(socket.SHUT_WR)
            response = service.decode(service.read_frame(stream))
            self.assertEqual(b'', stream.recv(1))
            return response

    def test_real_sandboxed_root_and_unprivileged_jvm_preserve_kernel_lease(self):
        self.command('/usr/bin/systemctl', 'start', 'kura-lease-probe.service')
        marker = Path('/run/kura-lease-probe/ready')
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not marker.exists():
            self.fail(self.command('/usr/bin/journalctl', '-u', 'kura-key-service.service', '-u', 'kura-lease-probe.service', '--no-pager', '-n', '20'))
        pid = int(marker.read_text())
        self.assertEqual(str(pid), self.command('/usr/bin/systemctl', 'show', 'kura-lease-probe.service', '--property=MainPID', '--value').strip())
        registration = self.manager.writer_registration(pid)
        self.assertGreater(registration['uid'], 0)
        status = dict(line.split(':', 1) for line in Path('/proc', str(pid), 'status').read_text().splitlines() if ':' in line)
        self.assertEqual(CORE_CAPABILITIES, int(status['CapEff'].strip(), 16) != 0)
        self.assertEqual('0' if CORE_CAPABILITIES else '1', status['NoNewPrivs'].strip())
        mounts = Path('/proc', str(pid), 'mountinfo').read_text().splitlines()
        actual = Path('/proc', str(pid), 'root/run/kura-key-service')
        self.assertTrue(os.statvfs(actual).f_flag & os.ST_RDONLY,
                        str([(row.split()[4], row.split()[5]) for row in mounts if row.split()[4].startswith('/run')]))
        with self.assertRaises(service.Failure) as failure:
            with self.manager.exclusive_writers():
                pass
        self.assertEqual('WRITERS_ACTIVE', failure.exception.reason)
        root_pid = self.command('/usr/bin/systemctl', 'show', 'kura-key-service.service', '--property=MainPID', '--value').strip()
        self.assertEqual('INVALID_ARGUMENT', self.rpc(dict(schema=1, action='core-start-plan',
                         restoreOperationId='invalid', expectedKeySha256='0' * 64))['error'])
        self.assertTrue(self.rpc(dict(schema=1, action='status'))['keyReady'])
        self.assertEqual(root_pid, self.command('/usr/bin/systemctl', 'show', 'kura-key-service.service', '--property=MainPID', '--value').strip())
        self.stop_owned_probe()
        with self.manager.exclusive_writers():
            pass
        self.assertEqual(self.binding['keySha256'], hashlib.sha256(Path(service.KEY_PATH).read_bytes()).hexdigest())
        self.assertEqual([], list(self.manager.operations.iterdir()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--java', type=Path, required=True)
    parser.add_argument('--disposable-fixture', action='store_true', required=True)
    parser.add_argument('--core-capabilities', action='store_true')
    args, remaining = parser.parse_known_args()
    package.CONFIG = args.repository.resolve()
    JAVA = args.java.resolve()
    CORE_CAPABILITIES = args.core_capabilities
    if JAVA != Path('/java/bin/java'):
        parser.error('The disposable fixture requires the explicit read-only /java toolchain mount')
    unittest.main(argv=[sys.argv[0], *remaining])
