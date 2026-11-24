# SPDX-License-Identifier: EPL-2.0
from io import BytesIO
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
from threading import Thread
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_journal_export as export
import kura_main_generation_proof as proof
import kura_clock_broker as clock


class JournalExportTest(unittest.TestCase):
    def test_main_uses_the_export_socket_without_kernel_log_capability(self):
        template = Path(__file__).resolve().parents[1] / 'main/resources/filtered/pkg/install/kura.service'
        unit = dict(line.split('=', 1) for line in template.read_text().splitlines()
                    if line.startswith(('Wants=', 'AmbientCapabilities=', 'CapabilityBoundingSet=')))
        self.assertIn(export.SOCKET_UNIT, unit['Wants'].split())
        for key in ('AmbientCapabilities', 'CapabilityBoundingSet'):
            self.assertNotIn('cap_syslog', unit[key].lower().split())

    def test_release_pair_survives_installer_removing_staging_tree(self):
        with TemporaryDirectory() as folder:
            home = Path(folder)
            (home / 'libexec').mkdir()
            for name in [*export.SOURCES, 'install/' + export.MAIN_UNIT]:
                target = home / name
                target.parent.mkdir(exist_ok=True)
                target.write_text(name)
            export.package_cohort(home)
            shutil.rmtree(home / 'install')
            retained = home / export.PAIR_DIRECTORY
            manifest = export.decode((retained / export.COHORT).read_bytes())
            self.assertEqual(set(manifest['files']), set(export.FILES))
            for name, digest in manifest['files'].items():
                self.assertEqual(export.file_hash((retained / name).read_bytes()), digest)

    def test_main_only_pairs_reviewed_networking_drop_ins(self):
        main = b'reviewed main'
        unit = export.MAIN_UNIT
        fragment = next(iter(export.VENDOR_UNIT_ROOTS)) / unit
        loaded = {'Id': unit, 'Names': unit, 'LoadState': 'loaded', 'FragmentPath': str(fragment),
                  'SourcePath': '', 'DropInPaths': str(export.NETWORKING_DROPIN),
                  'NeedDaemonReload': 'no', 'Transient': 'no'}
        dependencies = (b'[Unit]\nWants=NetworkManager.service ModemManager.service\n'
                        b'After=NetworkManager.service ModemManager.service\n')
        legacy = dependencies + b'\n[Service]\nAmbientCapabilities=cap_net_admin cap_net_raw\n'
        with patch.object(export, 'unit_properties', return_value=loaded), \
                patch.object(export, 'public_file') as read:
            for template in (dependencies, legacy):
                read.side_effect = [main, template]
                self.assertEqual(export.paired_unit(unit, unit, export.file_hash(main), main=True), loaded)
            read.side_effect = [main, dependencies + b'\n']
            with self.assertRaisesRegex(export.Refused, 'UNPAIRED_EXPORT'):
                export.paired_unit(unit, unit, export.file_hash(main), main=True)

    def test_only_main_can_pair_the_published_generation_drop_in(self):
        unit = export.MAIN_UNIT
        fragment = next(iter(export.VENDOR_UNIT_ROOTS)) / unit
        generation = str(export.GENERATION_DROPIN)
        loaded = {'Id': unit, 'Names': unit, 'LoadState': 'loaded', 'FragmentPath': str(fragment),
                  'SourcePath': '', 'DropInPaths': f'{generation} {export.NETWORKING_DROPIN}',
                  'NeedDaemonReload': 'no', 'Transient': 'no'}
        digest = export.file_hash(b'reviewed')
        with patch.object(export, 'unit_properties', return_value=loaded), \
                patch.object(export, 'public_file', return_value=b'reviewed'), \
                patch.object(export, 'NETWORKING_SHAS', {digest}), \
                patch.object(export, 'verify_generation_dropin') as verify:
            self.assertEqual(export.paired_unit(unit, unit, digest, main=True), loaded)
            verify.assert_called_once()
            for dropins in (f'{generation} {generation}', f'{generation} /run/systemd/system/site.conf'):
                loaded['DropInPaths'] = dropins
                with self.assertRaisesRegex(export.Refused, 'UNPAIRED_EXPORT'):
                    export.paired_unit(unit, unit, digest, main=True)
            loaded['DropInPaths'] = generation
            with self.assertRaisesRegex(export.Refused, 'UNPAIRED_EXPORT'):
                export.paired_unit(unit, unit, digest)
            loaded['NeedDaemonReload'] = 'yes'
            verify.reset_mock()
            with self.assertRaisesRegex(export.Refused, 'UNPAIRED_EXPORT'):
                export.paired_unit(unit, unit, digest, main=True)
            verify.assert_not_called()

    @unittest.skipUnless(os.geteuid() == 0 and sys.platform == 'linux', 'requires Linux root file ownership')
    def test_generation_drop_in_is_paired_to_exact_private_file(self):
        template = (Path(__file__).resolve().parents[1]
                    / 'main/resources/unfiltered/pkg/share/key-management/key-generations.conf')
        contents = template.read_bytes()
        self.assertEqual(export.file_hash(contents), export.GENERATION_SHA)
        with TemporaryDirectory() as location:
            parent = Path(location)
            installed = parent / export.GENERATION_DROPIN.name
            alternate = parent / 'other.conf'
            # Exercise the real file read below the private directory, using a temporary top level.
            with patch.object(export, 'GENERATION_DROPIN', installed), \
                    patch.object(export, 'protected', return_value=installed):
                installed.write_bytes(contents)
                installed.chmod(0o400)
                export.verify_generation_dropin()
                parent.chmod(0o755)
                with self.assertRaisesRegex(export.Refused, 'UNPAIRED_EXPORT'):
                    export.verify_generation_dropin()
                parent.chmod(0o700)
                installed.chmod(0o440)
                with self.assertRaisesRegex(export.Refused, 'UNPAIRED_EXPORT'):
                    export.verify_generation_dropin()
                installed.write_bytes(contents + b'# drift\n')
                installed.chmod(0o400)
                with self.assertRaisesRegex(export.Refused, 'UNPAIRED_EXPORT'):
                    export.verify_generation_dropin()
                installed.write_bytes(contents)
                os.link(installed, alternate)
                with self.assertRaisesRegex(export.Refused, 'UNPAIRED_EXPORT'):
                    export.verify_generation_dropin()
                installed.unlink()
                installed.symlink_to(alternate)
                with self.assertRaisesRegex(export.Refused, 'UNPAIRED_EXPORT'):
                    export.verify_generation_dropin()

    def test_service_allows_only_the_exact_container_adapter(self):
        unit = export.ACTOR_UNIT
        fragment = next(iter(export.VENDOR_UNIT_ROOTS)) / unit
        loaded = {'Id': unit, 'Names': unit, 'LoadState': 'loaded', 'FragmentPath': str(fragment),
                  'SourcePath': '', 'DropInPaths': str(clock.CONTAINER_ADAPTER),
                  'NeedDaemonReload': 'no', 'Transient': 'no'}
        content = b'[Service]\nProtectSystem=no\n'
        with patch.object(export, 'unit_properties', return_value=loaded), \
                patch.object(export, 'public_file', return_value=b'paired unit'), \
                patch.object(clock, 'public_file', return_value=content), \
                patch.object(clock, 'CONTAINER_ADAPTER_SHA256', export.file_hash(content)), \
                patch.object(clock.subprocess, 'run', return_value=subprocess.CompletedProcess(
                    ['systemd-detect-virt'], 0, b'lxc\n')):
            expected = export.file_hash(b'paired unit')
            self.assertEqual(loaded, export.paired_unit(unit, unit, expected))
            loaded['DropInPaths'] += ' /etc/systemd/system/service.d/site.conf'
            with self.assertRaisesRegex(export.Refused, '^UNPAIRED_EXPORT$'):
                export.paired_unit(unit, unit, expected)

    def test_generation_proof_binds_the_live_invocation_and_paired_worker(self):
        unit = 'kura-journal-export@1-10-11.service'
        invocation = '1' * 32
        request = f'{invocation} {unit}\n'.encode('ascii')
        peer = (10, 0, 0, 3)
        main = {'ActiveState': 'active', 'User': 'kurad', 'Group': 'kurad', 'MainPID': '6',
                'ControlGroup': '/system.slice/kura.service', 'InvocationID': invocation,
                'DropInPaths': str(export.GENERATION_DROPIN)}
        with patch.object(proof, 'verify_worker') as worker, patch.object(proof, 'verify_alive'), \
                patch.object(proof, 'paired_unit', return_value=main):
            self.assertEqual(proof.answer(peer, request, 'main-pin'), invocation.encode() + b'\n')
            worker.assert_called_once_with(peer, unit, 'main-pin')
            main['InvocationID'] = '2' * 32
            with self.assertRaisesRegex(export.Refused, 'UNPAIRED_EXPORT'):
                proof.answer(peer, request, 'main-pin')
            with self.assertRaisesRegex(export.Refused, 'INVALID_PROOF_REQUEST'):
                proof.answer(peer, request.rstrip(), 'main-pin')

    def test_root_handshake_does_not_replace_the_worker_pid_and_cgroup_checks(self):
        unit = 'kura-journal-export@1-10-11.service'
        group = '/system.slice/system-kura\x2djournal\x2dexport.slice/' + unit
        account = SimpleNamespace(pw_uid=21, pw_gid=22)
        status = {'Uid': '21 21 21 21', 'Gid': '22 22 22 22', 'NoNewPrivs': '1',
                  **{name: '0' for name in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb')}}
        pin = export.file_hash(b'paired unit')
        manifest = export.encode({'mainUnitSha256': 'main-pin', 'files': {export.ACTOR_UNIT: pin}})
        actor = {'ActiveState': 'active', 'MainPID': '10', 'User': export.ACTOR,
                 'Group': export.ACTOR, 'ControlGroup': group}
        with patch.object(proof.pwd, 'getpwnam', return_value=account), \
                patch.object(proof, 'proc_status', return_value=status), patch.object(proof, 'verify_alive'), \
                patch.object(proof, 'paired_unit', return_value=actor), \
                patch.object(proof, 'proc_file', return_value=('0::' + group + '\n').encode()) as read, \
                patch.object(proof, 'public_file') as file:
            file.side_effect = [manifest, b'paired unit']
            proof.verify_worker((10,0,0,3), unit, 'main-pin')
            file.side_effect = [manifest, b'paired unit']
            read.return_value = b'0::/user.slice/session-2.scope\n'
            with self.assertRaisesRegex(export.Refused, 'UNAUTHORIZED'):
                proof.verify_worker((10,0,0,3), unit, 'main-pin')
            with self.assertRaisesRegex(export.Refused, 'UNAUTHORIZED'):
                proof.verify_worker((10,21,22,3), unit, 'main-pin')
            with self.assertRaisesRegex(export.Refused, 'UNAUTHORIZED'):
                proof.verify_worker((10,0,0,3), 'incorrect@worker.service', 'main-pin')

    def test_typed_scope_and_fields(self):
        self.assertEqual(export.request('kura', 'MESSAGE,_BOOT_ID'),
                         {'schema': 1, 'scope': 'kura', 'fields': 'MESSAGE,_BOOT_ID'})
        for scope, fields in [('ssh.service', 'MESSAGE'), ('system', 'MESSAGE,'),
                              ('system', 'MESSAGE;id'), ('system', '--file=/etc/shadow'),
                              ('system', 'MESSAGE\n'), ('system', ','.join(['MESSAGE'] * 33))]:
            with self.subTest(scope=scope, fields=fields), self.assertRaises(export.Refused):
                export.request(scope, fields)

    def test_command_has_only_the_fixed_journal_selectors(self):
        for scope in ('kura', 'system'):
            sink = BytesIO()
            popen = subprocess.Popen
            def produce(argv, **options):
                expected = ['/usr/bin/journalctl', '--no-pager', '--quiet', '--output=verbose',
                            '--output-fields=MESSAGE']
                if scope == 'kura':
                    expected.append('--unit=kura.service')
                self.assertEqual(argv, expected)
                return popen([sys.executable, '-c', 'print("fixture")'], **options)
            with patch.object(export, 'protected'), patch.object(export.subprocess, 'Popen', side_effect=produce):
                self.assertEqual(export.read_journal(export.request(scope, 'MESSAGE'), sink), 8)
                self.assertEqual(sink.read(), b'fixture\n')

    def test_oversize_output_is_refused_before_it_can_be_published(self):
        popen = subprocess.Popen
        with patch.object(export, 'protected'), patch.object(export, 'MAX_DATA', 8), \
                patch.object(export.subprocess, 'Popen', side_effect=lambda argv, **options:
                             popen([sys.executable, '-c', 'print("unpublished data")'], **options)):
            with self.assertRaisesRegex(export.Refused, 'EXPORT_TOO_LARGE'):
                export.read_journal(export.request('system', 'MESSAGE'), BytesIO())

    def exchange(self, incoming, expected, reject):
        server, client = socket.socketpair()
        self.addCleanup(server.close)
        self.addCleanup(client.close)
        errors = []

        def work():
            with server, patch.object(export, 'verify_actor'), patch.object(export, 'socket_peer') as peer, \
                    patch.object(export, 'main_peer', return_value=expected), \
                    patch.object(export, 'read_journal', side_effect=lambda value, out:
                                 self.write_fixture(out)) as journal:
                peer.return_value.__enter__.return_value = object()
                try:
                    export.serve(server, 'kura-journal-export@fixture.service')
                except export.Refused as error:
                    errors.append(str(error))
                if reject:
                    journal.assert_not_called()

        worker = Thread(target=work)
        worker.start()
        export.send(client, incoming)
        client.settimeout(3)
        with client.makefile('rb') as stream:
            raw = stream.read()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        if reject:
            self.assertEqual(errors, ['INVALID_EXPORT'])
            self.assertEqual(raw, b'')
        else:
            self.assertEqual(errors, [])
            self.assertEqual(raw, struct.pack('>I', 3) + b'log')

    def write_fixture(self, out):
        out.write(b'log')
        out.seek(0)
        return 3

    def test_kernel_peer_selected_command_must_match_the_entire_wire_request(self):
        expected = export.request('kura', 'MESSAGE')
        self.exchange(export.request('system', 'MESSAGE'), expected, reject=True)
        self.exchange(dict(expected, schema=True), expected, reject=True)
        self.exchange(expected, expected, reject=False)


if __name__ == '__main__':
    unittest.main()
