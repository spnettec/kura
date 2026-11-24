#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""PID1 pairing and maintenance-failure contracts; never change a clock."""
import fcntl
import hashlib
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

    def test_clock_workers_keep_no_new_privileges_with_the_lxc_adapter(self):
        packaged = Path(broker.__file__).resolve().parent.parent / 'install'
        entrypoints = {'kura-clock-broker.service': 'serve',
                       'kura-clock-rtc-devices.service': 'serve-rtc',
                       'kura-clock-chrony-step.service': 'serve-chrony-step',
                       'kura-clock-chrony-config.service': 'serve-chrony-config'}
        self.assertEqual(set(entrypoints), {name for name in broker.UNITS if name.endswith('.service')})
        for name, action in entrypoints.items():
            with self.subTest(name=name):
                settings = (packaged / name).read_text().splitlines()
                self.assertIn('NoNewPrivileges=true', settings)
                self.assertIn('ExecStart=/usr/bin/setpriv --no-new-privs /usr/bin/python3 -I -B '
                              '/usr/libexec/kura-clock-broker/bin/kura_clock_broker.py ' + action, settings)

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

    def test_orbstack_adapter_requires_the_exact_content_and_runtime(self):
        adapter = broker.CONTAINER_ADAPTER
        approved = b'[Service]\nProtectSystem=no\n'
        sha = hashlib.sha256(approved).hexdigest()
        with mock.patch.object(broker, 'CONTAINER_ADAPTER_SHA256', sha), \
                mock.patch.object(broker, 'public_file', return_value=approved) as read, \
                mock.patch.object(broker.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout=b'lxc\n')) as probe:
            broker.check_loaded_dropins(broker.UNITS[1], str(adapter))
            read.assert_called_once_with(adapter, 4096)
            with self.assertRaisesRegex(broker.Refused, '^UNPAIRED_CODE$'):
                broker.check_loaded_dropins(broker.UNITS[0], str(adapter))
            with self.assertRaisesRegex(broker.Refused, '^UNPAIRED_CODE$'):
                broker.check_loaded_dropins(broker.UNITS[1], str(Path('/usr/lib') / adapter.name))
            probe.return_value.stdout = b'docker\n'
            with self.assertRaisesRegex(broker.Refused, '^UNPAIRED_CODE$'):
                broker.check_loaded_dropins(broker.UNITS[1], str(adapter))
            probe.return_value.stdout = b'lxc\n'
            read.return_value = approved + b'User=root\n'
            with self.assertRaisesRegex(broker.Refused, '^UNPAIRED_CODE$'):
                broker.check_loaded_dropins(broker.UNITS[1], str(adapter))

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


@unittest.skipUnless(os.geteuid() == 0, 'uses actual Root-owned actor staging metadata')
class ClockActorStagingTest(unittest.TestCase):
    def test_partial_copy_preserves_inode_and_completes_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / 'stage'
            stage.mkdir(mode=0o700)
            setup.stage_actor_directory(stage, 65534)
            path = stage / 'actor'
            setup.stage_actor_file(path, 65534, b'paired-')
            inode = path.stat().st_ino
            setup.stage_actor_file(path, 65534, b'paired-actor')
            self.assertEqual((path.read_bytes(), path.stat().st_ino), (b'paired-actor', inode))
            modified = path.stat().st_ctime_ns
            setup.stage_actor_file(path, 65534, b'paired-actor')
            self.assertEqual(path.stat().st_ctime_ns, modified)

    def test_busy_stage_preserves_the_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'actor'
            setup.stage_actor_file(path, 65534, b'prefix')
            with path.open('rb') as reader:
                fcntl.flock(reader, fcntl.LOCK_SH)
                with self.assertRaisesRegex(broker.Refused, 'BUSY'):
                    setup.stage_actor_file(path, 65534, b'prefix-complete')
                self.assertEqual(path.read_bytes(), b'prefix')
            setup.stage_actor_file(path, 65534, b'prefix-complete')
            self.assertEqual(path.read_bytes(), b'prefix-complete')

    def test_different_prefix_and_linked_file_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'actor'
            setup.stage_actor_file(path, 65534, b'original')
            with self.assertRaisesRegex(broker.Refused, 'UNPAIRED_CODE'):
                setup.stage_actor_file(path, 65534, b'otherwise')
            os.link(path, path.with_suffix('.saved'))
            with self.assertRaisesRegex(broker.Refused, 'UNPAIRED_CODE'):
                setup.stage_actor_file(path, 65534, b'original-bundle')
            self.assertEqual(path.read_bytes(), b'original')


class ClockMaintenancePairingTest(unittest.TestCase):
    def test_interrupted_publication_requires_the_original_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'actor'
            record = {'cohortSha256': 'original', 'purposeId': 'same-purpose'}
            with mock.patch.object(setup, 'ACTOR_HOME', home):
                archive = setup.archived_actor(record)
                class Policy:
                    def __init__(self, actor):
                        self.home = home
                    def check(self, installed, allow_legacy):
                        self.cohort = self.home.read_text()
                        return {'cohort': self.cohort}
                with mock.patch.object(setup, 'Policy', Policy):
                    home.write_text('original')
                    self.assertEqual(setup.previous_actor(record, 'candidate'), {'cohort': 'original'})
                    home.rename(archive)
                    self.assertEqual(setup.previous_actor(record, 'candidate'), {'cohort': 'original'})
                    home.write_text('candidate')
                    self.assertEqual(setup.previous_actor(record, 'candidate'), {'cohort': 'original'})
                    archive.write_text('other')
                    with self.assertRaisesRegex(broker.Refused, 'UNPAIRED_CODE'):
                        setup.previous_actor(record, 'candidate')
                    archive.unlink()
                    with self.assertRaisesRegex(broker.Refused, 'UNRESOLVED_CODE_PUBLICATION'):
                        setup.previous_actor(record, 'candidate')
                    home.unlink()
                    with self.assertRaisesRegex(broker.Refused, 'UNRESOLVED_CODE_PUBLICATION'):
                        setup.previous_actor(record, 'candidate')
                    self.assertIsNone(setup.previous_actor(None, 'candidate'))

    def test_legacy_device_retirement_requires_the_original_paired_unit_set(self):
        unit = broker.RTC_UNIT
        previous = {'files': {'libexec/clock-broker/' + unit: 'a' * 64}}
        original = {'units': {unit: 'a' * 64}, 'cohortSha256': broker.digest(previous)}
        current = dict(previous['files'])
        current['libexec/clock-broker/' + broker.RTC_SOCKET_UNIT] = 'b' * 64
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'projection'
            source.mkdir()
            with mock.patch.object(broker, 'RTC_SOURCE', source), mock.patch.object(broker, 'rtc_catalog') as checked:
                for old, flag in [(None, None), (None, original),
                                  (previous, dict(original, cohortSha256='c' * 64)),
                                  (previous, dict(original, units={unit: 'c' * 64})),
                                  (previous, dict(original, units={unit: 'a' * 64, broker.RTC_SOCKET_UNIT: 'b' * 64})),
                                  ({'files': current}, dict(original, cohortSha256=broker.digest({'files': current})))]:
                    with self.subTest(old=old, flag=flag), self.assertRaisesRegex(broker.Refused, 'UNPAIRED_RTC_PROJECTION'):
                        broker.retire_rtc_projection(old, flag)
                checked.assert_not_called()
                self.assertEqual([source], list(Path(temp).iterdir()))

    def test_paired_retirement_preserves_the_projection_under_a_private_parent(self):
        unit = broker.RTC_UNIT
        previous = {'files': {'libexec/clock-broker/' + unit: 'a' * 64}}
        original = {'units': {unit: 'a' * 64}, 'cohortSha256': broker.digest(previous)}
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'projection'
            source.mkdir()
            manifest = source / broker.RTC_MANIFEST
            manifest.write_bytes(b'original')
            inode = manifest.stat().st_ino
            def move(src, dest, replace):
                self.assertFalse(replace)
                self.assertEqual(0o700, stat.S_IMODE(dest.parent.stat().st_mode))
                os.rename(src, dest)
            with mock.patch.object(broker, 'RTC_SOURCE', source), mock.patch.object(broker, 'unit_directory_present', return_value=True), \
                    mock.patch.object(broker, 'rtc_catalog') as checked, mock.patch.object(broker, 'publish_path', side_effect=move):
                broker.retire_rtc_projection(previous, original)
                broker.retire_rtc_projection(None, None)
                checked.assert_called_once_with(source)
                archived, = Path(temp).glob('.kura-clock-rtc-retired-*/projection/devices.json')
                self.assertEqual((inode, b'original'), (archived.stat().st_ino, archived.read_bytes()))
                self.assertFalse(source.exists())

    def test_only_main_mask_is_an_inactive_install_state(self):
        response=SimpleNamespace(returncode=0,stdout='LoadState=masked\nActiveState=inactive\nMainPID=0\nControlPID=0\n')
        with mock.patch.object(setup.subprocess,'run',return_value=response), mock.patch.object(setup,'main_masked') as masks:
            setup.inactive('kura.service');masks.assert_called_once()
            for name in broker.UNITS:
                with self.assertRaisesRegex(broker.Refused,'UNSAFE_UNIT'):setup.inactive(name)
            self.assertEqual(1,masks.call_count)

    def test_main_mask_still_requires_explicit_zero_processes_and_inactive_state(self):
        for tail in ('ActiveState=active\nMainPID=5\nControlPID=0\n',
                     'ActiveState=inactive\nMainPID=0\nControlPID=5\n',
                     'ActiveState=inactive\nControlPID=0\n'):
            response=SimpleNamespace(returncode=0,stdout='LoadState=masked\n'+tail)
            with mock.patch.object(setup.subprocess,'run',return_value=response),mock.patch.object(setup,'main_masked'):
                with self.assertRaisesRegex(broker.Refused,'UNIT_RUNNING'):setup.inactive('kura.service')

    def test_deployment_generator_mask_requires_an_idle_manager_job(self):
        fields = f'LoadState=masked\nActiveState=inactive\nMainPID=0\nControlPID=0\nFragmentPath={setup.DEPLOYMENT_MASK}\n'
        for job in ('Job=\n', 'Job=13\n', ''):
            response = SimpleNamespace(returncode=0, stdout=fields + job)
            with self.subTest(job=job), mock.patch.object(setup.subprocess, 'run', return_value=response), \
                    mock.patch.object(setup, 'main_masked') as verify:
                if job == 'Job=\n':
                    setup.inactive('kura.service')
                else:
                    with self.assertRaisesRegex(broker.Refused, 'UNIT_RUNNING'):
                        setup.inactive('kura.service')
                verify.assert_called_once_with(str(setup.DEPLOYMENT_MASK))

    def test_main_mask_fixed_target_owner_link_count_and_parent_are_not_generalized(self):
        good=dict(st_mode=stat.S_IFLNK|0o777,st_uid=0,st_gid=0,st_nlink=1,st_dev=1,st_ino=2,
                  st_size=9,st_mtime_ns=3,st_ctime_ns=4)
        for changes,target,parent in [({},'/dev/null',True),({'st_uid':1},'/dev/null',True),
            ({'st_nlink':2},'/dev/null',True),({'st_mode':stat.S_IFREG|0o644},'/dev/null',True),
            ({},'/elsewhere',True),({},'/dev/null',False)]:
            with self.subTest(changes=changes,target=target,parent=parent), \
                mock.patch.object(setup.os.path,'lexists',return_value=True), \
                mock.patch.object(setup,'unit_directory_present',return_value=parent), \
                mock.patch.object(setup.Path,'lstat',return_value=SimpleNamespace(**dict(good,**changes))), \
                mock.patch.object(setup.os,'readlink',return_value=target):
                if not changes and target=='/dev/null' and parent:setup.main_masked('/etc/systemd/system/kura.service')
                else:
                    with self.assertRaisesRegex(broker.Refused,'UNSAFE_UNIT'):setup.main_masked('/etc/systemd/system/kura.service')

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
                    mock.patch.object(setup, 'chrony_policy'), \
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
                          ('/usr/bin/systemctl', 'enable', '--now', broker.STEP_SOCKET_UNIT),
                          ('/usr/bin/systemctl', 'enable', '--now', broker.CONFIG_SOCKET_UNIT),
                          ('/usr/bin/systemctl', 'enable', '--now', broker.RTC_SOCKET_UNIT),
                          ('check', False, True), ('check', True, True)], calls)

    def test_reload_pairing_and_socket_failures_retain_the_original_gate(self):
        for fail in ['daemon-reload', ('check', 4), ('check', 5), 'kura-clock-broker.socket',
                     broker.STEP_SOCKET_UNIT, broker.CONFIG_SOCKET_UNIT, broker.RTC_SOCKET_UNIT, ('check', 10), ('check', 11)]:
            with self.subTest(failure=fail):
                self.resume_case(fail)


if __name__ == '__main__':
    unittest.main()
