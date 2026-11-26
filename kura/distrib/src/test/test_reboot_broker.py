# SPDX-License-Identifier: EPL-2.0
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'main/resources/unfiltered/pkg/bin'))
import kura_reboot_broker as broker  # noqa: E402
from kura_clock_journal import Refused, encode  # noqa: E402


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(broker, 'protected'))
        self.launch = self.enterContext(patch.object(broker.subprocess, 'Popen'))

    def test_dispatch_is_fixed_and_reply_only_confirms_acceptance(self):
        self.launch.return_value.wait.return_value = 0
        self.assertEqual(('ACCEPTED', 'MANAGER_ACCEPTED'), broker.dispatch_reboot())
        self.launch.assert_called_once_with(
            ('/usr/bin/systemctl', '--system', '--no-ask-password', '--no-wall', '--no-block', 'reboot'),
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
                 'SYSTEMCTL_SKIP_AUTO_KEXEC': '1', 'SYSTEMCTL_SKIP_AUTO_SOFT_REBOOT': '1'},
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def test_launch_failure_is_distinct_from_nonzero_reply(self):
        self.launch.side_effect = OSError('no process')
        self.assertEqual(('FAILED', 'NOT_STARTED'), broker.dispatch_reboot())
        self.launch.side_effect = None
        self.launch.return_value.wait.return_value = 1
        self.assertEqual(('UNKNOWN', 'DISPATCH_UNCONFIRMED'), broker.dispatch_reboot())

    def test_losing_reply_cannot_confirm_dispatch_failure(self):
        process = self.launch.return_value
        process.wait.side_effect = [subprocess.TimeoutExpired(broker.DISPATCH_ARGS, 12), -9]
        self.assertEqual(('UNKNOWN', 'DISPATCH_UNCONFIRMED'), broker.dispatch_reboot())
        process.kill.assert_called_once_with()
        self.launch.assert_called_once()


class PairingTest(unittest.TestCase):
    def setUp(self):
        self.peer = (202, 997, 991, 42)
        self.binding = {'callerUid': 997, 'callerGid': 991}
        self.manager = {'MainPID': '201', 'ControlGroup': '/system.slice/kura.service',
                        'ActiveState': 'active', 'InvocationID': 'a' * 32}
        self.main = self.enterContext(patch.object(broker, 'manager_properties', return_value=self.manager))
        self.enterContext(patch.object(broker, 'verify_alive'))
        self.status = self.enterContext(patch.object(broker, 'proc_status', return_value={
            'PPid': '201', 'Uid': '997 997 997 997', 'Gid': '991 991 991 991',
        }))
        self.argv = b'\0'.join(arg.encode() for arg in broker.CLIENT_ARGS) + b'\0'
        self.cgroup = broker.MAIN_CGROUP.encode() + b'\n'
        self.files = self.enterContext(patch.object(broker, 'proc_file', side_effect=self.proc_file))

    def proc_file(self, pid, name):
        return self.argv if name == 'cmdline' else self.cgroup

    def test_fixed_helper_has_matching_parent_and_current_cgroup(self):
        self.assertTrue(broker.main_peer(self.peer, self.binding))
        self.assertEqual(2, self.main.call_count)
        broker.verify_alive.assert_called_with(42)

    def test_same_uid_outside_main_parent_and_cgroup_is_refused(self):
        self.status.return_value['PPid'] = '203'
        with self.assertRaisesRegex(Refused, '^UNAUTHORIZED$'):
            broker.main_peer(self.peer, self.binding)
        self.status.return_value['PPid'] = '201'
        self.cgroup += b'1:extra:/unpaired\n'
        with self.assertRaisesRegex(Refused, '^UNAUTHORIZED$'):
            broker.main_peer(self.peer, self.binding)

    def test_exact_helper_and_primary_group_are_both_required(self):
        self.argv += b'--different\0'
        with self.assertRaisesRegex(Refused, '^UNAUTHORIZED$'):
            broker.main_peer(self.peer, self.binding)
        with self.assertRaisesRegex(Refused, '^UNAUTHORIZED$'):
            broker.main_peer((202, 997, 992, 42), self.binding)

    def test_main_replacement_during_authentication_is_refused(self):
        self.main.side_effect = [self.manager, dict(self.manager, InvocationID='b' * 32)]
        with self.assertRaisesRegex(Refused, '^UNAUTHORIZED$'):
            broker.main_peer(self.peer, self.binding)


class PackagePairingTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.home / 'libexec').mkdir()
        inputs = [name for name in broker.FILES if not name.startswith('libexec/')]
        for name in [*inputs, *('install/' + unit for unit in broker.UNITS)]:
            real = ROOT / 'main/resources/unfiltered/pkg' / name
            if name == 'install/kura.service':
                real = ROOT / 'main/resources/filtered/pkg' / name
            path = self.home / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(real.read_bytes())

    def test_packaged_python_and_units_are_checked_against_live_copies(self):
        manifest = broker.package_cohort(self.home)
        vendor = self.home / 'vendor'
        vendor.mkdir()
        for unit in broker.UNITS:
            (vendor / unit).write_bytes((self.home / 'install' / unit).read_bytes())
            (self.home / 'install' / unit).unlink()
        (self.home / 'install').rmdir()
        actor = (vendor / broker.UNITS[0]).read_text().splitlines()
        self.assertIn('ExecStart=/usr/bin/setpriv --no-new-privs /usr/bin/python3 -I -B '
                      '/opt/eclipse/kura/bin/kura_reboot_broker.py serve', actor)
        self.assertIn('CapabilityBoundingSet=', actor)
        self.assertIn('KillMode=mixed', actor)
        marker = dict(schema=1, namespace='0101db50-edc1-4ea5-a461-28dcb898e596', callerUid=997, callerGid=991)
        def loaded(unit, _):
            return dict(Id=unit, Names=unit, LoadState='loaded', FragmentPath=str(vendor / unit),
                        SourcePath='', DropInPaths='', NeedDaemonReload='no', Transient='no')
        with patch.multiple(broker, HOME=self.home, VENDOR_UNIT_ROOTS=(vendor,), public_file=Path.read_bytes,
                            verify_unit_sources=Mock(return_value=False), manager_properties=Mock(side_effect=loaded),
                            account_binding=Mock(return_value=marker)):
            self.assertEqual((broker.digest(manifest), marker), broker.Policy().check(actor=True))
            broker.account_binding.assert_called_once_with()
            view = f'BindReadOnlyPaths=-{broker.AUTHORITY}:{broker.MAIN_AUTHORITY}'
            self.assertIn(view, (vendor / broker.MAIN_UNIT).read_text().splitlines())
            with patch.object(broker.os, 'statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)) as flags:
                self.assertEqual((broker.digest(manifest), marker), broker.Policy().check(actor=False))
                flags.assert_called_once_with(broker.MAIN_AUTHORITY)
                broker.account_binding.assert_called_with(broker.MAIN_AUTHORITY)
                flags.return_value.f_flag = 0
                broker.account_binding.reset_mock()
                with self.assertRaisesRegex(Refused, '^UNPAIRED_INSTALLATION$'):
                    broker.Policy().check(actor=False)
                broker.account_binding.assert_not_called()
            (vendor / broker.MAIN_UNIT).write_bytes(b'unpaired main')
            with self.assertRaisesRegex(Refused, '^UNPAIRED_UNIT$'):
                broker.Policy().check(actor=True)
            with self.assertRaisesRegex(Refused, '^UNPAIRED_UNIT$'):
                broker.Policy().check(actor=False)
            (self.home / 'bin/kura_reboot_protocol.py').write_bytes(b'unpaired protocol')
            with self.assertRaisesRegex(Refused, '^UNPAIRED_CODE$'):
                broker.Policy().check(actor=True)

    def test_runtime_and_vendor_dropins_are_refused_even_when_dangling(self):
        for directory, name in [('etc', 'kura-reboot-broker.socket'), ('lib', 'kura-.service.d')]:
            root = self.home / directory
            root.mkdir()
            (root / name).symlink_to('/no/such/config')
            with patch.multiple(broker, VENDOR_UNIT_ROOTS=(self.home / 'lib',), unit_load_paths=Mock(return_value=[root]),
                                unit_directory_present=Mock(return_value=True)):
                with self.assertRaisesRegex(Refused, '^UNPAIRED_UNIT$'):
                    broker.verify_unit_sources()

    def test_only_the_configured_networking_package_and_reviewed_vendor_copy_are_paired(self):
        vendor = self.home / 'vendor'
        target = vendor / 'kura.service.d/kura-networking.conf'
        target.parent.mkdir(parents=True)
        raw = b'[Unit]\nWants=NetworkManager.service ModemManager.service\nAfter=NetworkManager.service ModemManager.service\n'
        target.write_bytes(raw)
        template = self.home / 'libexec/kura-networking.conf'
        template.write_bytes(raw)
        installed = SimpleNamespace(returncode=0, stdout='installed\n')
        owner = SimpleNamespace(returncode=0, stdout=f'kura-networking: {template}\n')
        with patch.multiple(broker, NETWORKING_DROPIN=target, NETWORKING_TEMPLATE=template,
                            VENDOR_UNIT_ROOTS=(vendor,), public_file=lambda path, limit: path.read_bytes(),
                            unit_directory_present=Mock(return_value=True), unit_load_paths=Mock(return_value=(vendor,))), \
                patch.object(broker.subprocess, 'run', side_effect=[installed, owner] * 4):
            broker.verify_unit_sources()
            target.write_bytes(raw + b'PartOf=site.service\n')
            with self.assertRaisesRegex(Refused, '^UNPAIRED_UNIT$'):
                broker.verify_unit_sources()
            target.write_bytes(raw)
            installed.stdout = 'unpacked\n'
            with self.assertRaisesRegex(Refused, '^UNPAIRED_UNIT$'):
                broker.verify_unit_sources()
            installed.stdout = 'installed\n'
            (target.parent / 'site.conf').write_bytes(b'[Unit]\n')
            with self.assertRaisesRegex(Refused, '^UNPAIRED_UNIT$'):
                broker.verify_unit_sources()

    def test_authority_marker_pins_original_account_ids(self):
        marker = dict(schema=1, namespace='0101db50-edc1-4ea5-a461-28dcb898e596', callerUid=997, callerGid=991)
        with patch.multiple(broker, public_file=Mock(return_value=encode(marker))), patch.object(
                broker.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=997, pw_gid=991)) as lookup:
            self.assertEqual(marker, broker.account_binding())
            lookup.return_value.pw_gid = 990
            with self.assertRaisesRegex(Refused, '^UNPAIRED_ACCOUNT$'):
                broker.account_binding()

    def test_private_main_dropin_directory_accepts_only_the_generation_declaration(self):
        root = self.home / 'system'
        root.mkdir()
        reserved = root / 'kura.service.d'
        reserved.mkdir(mode=0o700)
        lstat = Path.lstat

        def root_owned(path):
            actual = lstat(path)
            if path == reserved:
                values = {name: getattr(actual, name) for name in dir(actual) if name.startswith('st_')}
                values.update(st_uid=0, st_gid=0)
                return SimpleNamespace(**values)
            return actual

        generation = reserved / broker.GENERATION_DROPIN.name
        with patch.multiple(broker, KEY_DROPINS=reserved, GENERATION_DROPIN=generation,
                            unit_load_paths=Mock(return_value=[root]),
                            unit_directory_present=Mock(return_value=True),
                            verify_generation_dropin=Mock()), patch.object(Path, 'lstat', root_owned):
            self.assertFalse(broker.verify_unit_sources())
            generation.write_text('reviewed fixture')
            self.assertTrue(broker.verify_unit_sources())
            broker.verify_generation_dropin.assert_called_once_with()
            unapproved = reserved / 'site.conf'
            unapproved.write_text('[Service]\n')
            with self.assertRaisesRegex(Refused, '^UNPAIRED_UNIT$'):
                broker.verify_unit_sources()
            self.assertFalse(broker.verify_unit_sources(broker.UNITS[:2]))

    def test_generation_layout_is_verified_by_the_actor_and_must_match_the_manager(self):
        manifest = broker.package_cohort(self.home)
        vendor = self.home / 'install'
        binding = {'callerUid': 991, 'callerGid': 992}
        main_dropins = str(broker.GENERATION_DROPIN)

        def properties(unit, _):
            return dict(Id=unit, Names=unit, LoadState='loaded', FragmentPath=str(vendor / unit),
                        SourcePath='', DropInPaths=main_dropins if unit == broker.MAIN_UNIT else '',
                        NeedDaemonReload='no', Transient='no')

        with patch.multiple(broker, HOME=self.home, VENDOR_UNIT_ROOTS=(vendor,), public_file=Path.read_bytes,
                            verify_unit_sources=Mock(return_value=True), verify_generation_dropin=Mock(),
                            manager_properties=Mock(side_effect=properties), account_binding=Mock(return_value=binding)), \
                patch.object(broker.os, 'statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
            self.assertEqual((broker.digest(manifest), binding), broker.Policy().check(actor=False))
            broker.verify_generation_dropin.assert_not_called()
            self.assertEqual((broker.digest(manifest), binding), broker.Policy().check(actor=True))
            broker.verify_generation_dropin.assert_called_once_with()
            broker.verify_generation_dropin.side_effect = Refused('UNPAIRED_UNIT')
            with self.assertRaisesRegex(Refused, '^UNPAIRED_UNIT$'):
                broker.Policy().check(actor=True)
            broker.verify_generation_dropin.side_effect = None
            main_dropins = ''
            with self.assertRaisesRegex(Refused, '^UNPAIRED_UNIT$'):
                broker.Policy().check(actor=True)
            main_dropins = str(broker.GENERATION_DROPIN) + ' /run/systemd/system/service.d/site.conf'
            with self.assertRaisesRegex(Refused, '^UNPAIRED_UNIT$'):
                broker.Policy().check(actor=False)


class SocketFrameTest(unittest.TestCase):
    def test_extra_frame_and_oversize_are_refused(self):
        for content in (struct.pack('>I', broker.MAX_FRAME + 1),
                        struct.pack('>I', 2) + b'{}' + b'!'):
            connection, peer = socket.socketpair()
            with connection, peer:
                connection.sendall(content)
                connection.shutdown(socket.SHUT_WR)
                with self.assertRaisesRegex(Refused, '^INVALID_FRAME$'):
                    broker.receive(peer)

    @unittest.skipUnless(sys.platform == 'linux', 'requires Linux Unix peer descriptors')
    def test_real_kernel_authenticated_socket_round_trip(self):
        # No systemd dispatch is registered for this private socketpair.
        connection, peer = socket.socketpair()
        with connection, peer:
            advertised = dict(schema=1, action='context')
            with broker.socket_peer(connection) as credentials:
                self.assertEqual((os.getpid(), os.getuid(), os.getgid()), credentials[:3])
                self.assertFalse(os.get_inheritable(credentials[3]))
                broker.verify_alive(credentials[3])
            protocol = Mock()
            protocol.authorize.side_effect = lambda current: current[:3] == (os.getpid(), os.getuid(), os.getgid())
            protocol.handle.return_value = {'readOnly': True}
            worker = threading.Thread(target=broker.serve_socket, args=(peer, protocol), daemon=True)
            worker.start()
            broker.send(connection, advertised)
            self.assertEqual({'ok': True, 'result': {'readOnly': True}}, broker.receive(connection))
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(advertised, protocol.handle.call_args.args[0])

    @unittest.skipUnless(sys.platform == 'linux', 'requires Linux Unix peer descriptors')
    def test_unauthorized_kernel_peer_is_refused_without_reading_frame(self):
        connection, peer = socket.socketpair()
        with connection, peer:
            protocol = Mock()
            protocol.authorize.return_value = False
            broker.serve_socket(peer, protocol)
            self.assertEqual({'ok': False, 'reason': 'UNAUTHORIZED'}, broker.receive(connection))
            protocol.handle.assert_not_called()

    def test_sigterm_finishes_active_request_before_accepting_any_more(self):
        with tempfile.TemporaryDirectory() as tmp, socket.socket(socket.AF_UNIX) as listener, \
                socket.socket(socket.AF_UNIX) as first, socket.socket(socket.AF_UNIX) as queued:
            path = str(Path(tmp) / 'control.sock')
            listener.bind(path)
            listener.listen()
            first.connect(path)
            queued.connect(path)
            outcome = Path(tmp) / 'result'
            previous = signal.getsignal(signal.SIGTERM)

            def finish(connection, protocol):
                signal.raise_signal(signal.SIGTERM)
                outcome.write_bytes(b'current request finished')

            with patch.object(broker, 'serve_socket', side_effect=finish) as serve:
                broker.serve_connections(listener, Mock())
            serve.assert_called_once()
            self.assertEqual(b'current request finished', outcome.read_bytes())
            self.assertEqual(previous, signal.getsignal(signal.SIGTERM))


if __name__ == '__main__':
    unittest.main()
