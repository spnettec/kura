#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""PID1 pairing and maintenance-failure contracts; never change a clock."""
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_clock_broker as broker
import kura_clock_setup as setup


class ClockUnitPairingTest(unittest.TestCase):
    def loaded(self, name):
        return dict(Id=name, Names=name, LoadState='loaded', FragmentPath='/usr/lib/systemd/system/' + name,
                    SourcePath='', DropInPaths='', NeedDaemonReload='no', Transient='no')

    def test_pid1_properties_use_fixed_system_environment_and_include_empty_values(self):
        response = SimpleNamespace(returncode=0, stdout='Id=kura-clock-broker.service\nDropInPaths=\n')
        with mock.patch.object(broker.subprocess, 'run', return_value=response) as run:
            value = broker.systemd_properties(('Id', 'DropInPaths'), broker.UNITS[1])
        self.assertEqual('', value['DropInPaths'])
        self.assertEqual(['/usr/bin/systemctl', '--system', '--no-ask-password', 'show', '--all',
                          '--property=Id,DropInPaths', 'kura-clock-broker.service'], run.call_args.args[0])
        self.assertEqual({'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}, run.call_args.kwargs['env'])
        with self.assertRaises(broker.Refused):
            broker.systemd_properties(('Id',), 'caller-controlled.service')

    def test_missing_duplicate_unknown_failed_and_unavailable_pid1_are_refused(self):
        for code, stdout in [(0, ''), (0, 'Id=a\nId=a\n'), (0, 'Id=a\nOther=1\n'),
                             (0, 'Id\n'), (1, 'Id=a\n'), (0, 'Id=' + 'a' * broker.MAX_BYTES)]:
            with self.subTest(code=code, size=len(stdout)):
                with mock.patch.object(broker.subprocess, 'run', return_value=SimpleNamespace(returncode=code, stdout=stdout)):
                    with self.assertRaisesRegex(broker.Refused, 'UNPAIRED_CODE'):
                        broker.systemd_properties(('Id',))
        for error in [OSError('unavailable'), subprocess.TimeoutExpired('systemctl', 5), UnicodeError('invalid')]:
            with mock.patch.object(broker.subprocess, 'run', side_effect=error):
                with self.assertRaisesRegex(broker.Refused, 'UNPAIRED_CODE'):
                    broker.systemd_properties(('Id',))

    def test_loaded_original_vendor_fragments_are_accepted_in_both_usrmerge_forms(self):
        for root in broker.VENDOR_UNIT_ROOTS:
            def properties(fields, name):
                return dict(self.loaded(name), FragmentPath=str(root / name))
            with mock.patch.object(broker, 'systemd_properties', side_effect=properties):
                broker.effective_units()

    def test_stale_transient_generated_aliased_overridden_or_missing_loaded_units_are_refused(self):
        changes = [('Id', 'other.service'), ('Names', 'kura-clock-broker.service alias.service'),
                   ('LoadState', 'not-found'), ('LoadState', 'masked'), ('NeedDaemonReload', 'yes'),
                   ('Transient', 'yes'), ('SourcePath', '/etc/init.d/old-clock'),
                   ('FragmentPath', '/run/systemd/transient/kura-clock-broker.service'),
                   ('DropInPaths', '/run/systemd/system.control/kura-clock-broker.service.d/50.conf')]
        for key, changed in changes:
            with self.subTest(property=key, value=changed):
                def properties(fields, name):
                    return dict(self.loaded(name), **{key: changed})
                with mock.patch.object(broker, 'systemd_properties', side_effect=properties):
                    with self.assertRaisesRegex(broker.Refused, 'UNPAIRED_CODE'):
                        broker.effective_units()

    def test_load_path_comes_from_pid1_including_attached_and_control_roots(self):
        raw = '/etc/systemd/system.control /run/systemd/system.attached /usr/lib/systemd/system'
        with mock.patch.object(broker, 'systemd_properties', return_value={'UnitPath': raw}):
            self.assertEqual(tuple(Path(p) for p in raw.split()), broker.unit_load_paths())
        for raw in ['', '/etc/systemd/system', '/usr/lib/systemd/system relative',
                    '/usr/lib/systemd/system /tmp/../other', '/usr/lib/systemd/system /tmp//other',
                    '/usr/lib/systemd/system /tmp/quoted\\x20path']:
            with mock.patch.object(broker, 'systemd_properties', return_value={'UnitPath': raw}):
                with self.assertRaises(broker.Refused):
                    broker.unit_load_paths()

    def test_all_applicable_dropin_and_dependency_names_are_rejected_in_any_load_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # Ownership is checked separately; this tests actual directory lookups.
            with mock.patch.object(broker, 'unit_load_paths', return_value=(root,)), \
                    mock.patch.object(broker, 'unit_directory_present', return_value=True):
                broker.unit_sources()
                for name in broker.UNITS:
                    for entry in [name, *broker.unit_input_names(name)]:
                        path = root / entry; path.mkdir()
                        with self.subTest(entry=entry):
                            with self.assertRaisesRegex(broker.Refused, 'UNPAIRED_CODE'):
                                broker.unit_sources()
                        path.rmdir()
        self.assertIn('service.d', broker.unit_input_names(broker.UNITS[1]))
        self.assertIn('kura-clock-.service.d', broker.unit_input_names(broker.UNITS[1]))
        self.assertIn('kura-.service.d', broker.unit_input_names(broker.UNITS[1]))

    def test_unreadable_lookup_does_not_become_absence(self):
        with mock.patch.object(broker, 'unit_load_paths', return_value=(Path('/etc/systemd/system.control'),)), \
                mock.patch.object(broker.Path, 'lstat', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(broker.Refused, 'UNPAIRED_CODE'):
                broker.unit_sources()

    def test_unit_directory_rejects_nonroot_writable_and_linked_ancestors(self):
        for uid, mode in [(1, stat.S_IFDIR | 0o755), (0, stat.S_IFDIR | 0o775),
                          (0, stat.S_IFREG | 0o644), (0, stat.S_IFLNK | 0o777)]:
            with mock.patch.object(broker.Path, 'lstat', return_value=SimpleNamespace(st_uid=uid, st_mode=mode)):
                with self.assertRaises(broker.Refused):
                    broker.unit_directory_present(Path('/etc/systemd/system'))


class ClockMaintenancePairingTest(unittest.TestCase):
    def test_override_preflight_precedes_account_state_and_code_mutation(self):
        with mock.patch.object(setup, 'Policy'), mock.patch.object(setup, 'inactive'), \
                mock.patch.object(setup, 'unit_sources', side_effect=broker.Refused('UNPAIRED_CODE')), \
                mock.patch.object(setup, 'account') as account, mock.patch.object(setup, 'install_actor_code') as code:
            with self.assertRaisesRegex(broker.Refused, 'UNPAIRED_CODE'):
                setup.install()
        account.assert_not_called(); code.assert_not_called()

    def resume_case(self, fail=None):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder); flag = state / 'maintenance.json'; original = b'original maintenance purpose\n'
            flag.write_bytes(original); calls = []; record = {'uid': os.getuid()}

            class Policy:
                cohort = 'a' * 64
                def __init__(self, actor=False):
                    self.actor = actor
                def check(self, effective=True):
                    calls.append(('check', self.actor, effective))
                    if fail == ('check', len(calls)):
                        raise broker.Refused('UNPAIRED_CODE')

            def run(*arguments):
                self.assertEqual(original, flag.read_bytes())
                calls.append(arguments)
                if fail == arguments[-1]:
                    raise subprocess.CalledProcessError(1, arguments)

            with mock.patch.object(setup, 'STATE', state), mock.patch.object(setup, 'Policy', Policy), \
                    mock.patch.object(setup, 'account', return_value=record), mock.patch.object(setup, 'run', side_effect=run), \
                    mock.patch.object(setup, 'maintenance', return_value={'original': True}):
                if fail is None:
                    setup.resume(); self.assertFalse(flag.exists())
                else:
                    with self.assertRaises((broker.Refused, subprocess.CalledProcessError)):
                        setup.resume()
                    self.assertEqual(original, flag.read_bytes())
            return calls

    def test_resume_keeps_original_gate_through_reload_validation_and_socket_start(self):
        calls = self.resume_case()
        self.assertEqual([('check', False, False), ('check', True, False),
                          ('/usr/bin/systemctl', 'daemon-reload'), ('check', False, True), ('check', True, True),
                          ('/usr/bin/systemctl', 'enable', '--now', 'kura-clock-broker.socket'),
                          ('check', False, True), ('check', True, True)], calls)

    def test_reload_pairing_and_socket_failures_retain_the_original_gate(self):
        for fail in ['daemon-reload', ('check', 4), ('check', 5), 'kura-clock-broker.socket',
                     ('check', 7), ('check', 8)]:
            with self.subTest(failure=fail):
                self.resume_case(fail)


if __name__ == '__main__':
    unittest.main()
