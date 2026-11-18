#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Main layout refusal must precede package-maintenance side effects."""
import hashlib
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

import test_key_service_lifecycle as fixtures

migrate_linked_main = runpy.run_path(str(Path(__file__).resolve().parents[2]
                                         / 'kura-core/main-link-migration.py'))['migrate_linked_main']


class MainLayoutAdmissionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LifecycleTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.policy = self.fixture.policy
        self.unit = self.root / 'lib/systemd/system/kura.service'
        self.original_unit = b'[Service]\nExecStart=/usr/bin/false\n[Install]\nWantedBy=multi-user.target\n'
        self.fixture.write(self.unit, self.original_unit, 0o644)
        self.choice = 'disabled'
        self.query_status = 0
        previous_runner = self.policy.runner

        def runner(args, **kwargs):
            if args[1:3] == ['show', 'kura.service'] and '--property=UnitFileState' in args:
                self.fixture.calls.append(args)
                return fixtures.types.SimpleNamespace(returncode=self.query_status,
                                                     stdout=self.choice + '\n', stderr='')
            if args[1:3] == ['show', 'kura.service'] and '--property=Id,Names' in args[3]:
                self.fixture.calls.append(args)
                return fixtures.types.SimpleNamespace(returncode=0, stdout=self.effective_main(), stderr='')
            return previous_runner(args, **kwargs)
        self.policy.runner = runner

    def effective_main(self):
        return ('Id=kura.service\nNames=kura.service\nLoadState=loaded\n'
                f'UnitFileState={self.choice}\nSourcePath=\nDropInPaths=\nNeedDaemonReload=no\n'
                'Transient=no\nFragmentPath=/lib/systemd/system/kura.service\n')

    def pair_static_main(self):
        unit = b'[Service]\nExecStart=/usr/bin/false\n'
        self.fixture.write(self.unit, unit, 0o644)
        manifest_path = self.fixture.physical / 'libexec/key-backup/manifest.json'
        manifest = json.loads(manifest_path.read_bytes())
        manifest.update(schema=2, protocol=2, generation={'unitSha256': hashlib.sha256(unit).hexdigest()})
        self.fixture.write(manifest_path, fixtures.lifecycle.encoded(manifest), 0o640)

    def assert_no_admission(self, original):
        self.assertEqual(original, self.fixture.data_identity())
        self.assertFalse(self.policy.state.exists())
        self.assertFalse(any(args[1] == 'stop' for args in self.fixture.calls))

    def test_linked_alias_and_unknown_layouts_refuse_before_initialization_or_stop(self):
        original = self.fixture.data_identity()
        for choice in ('linked', 'linked-runtime', 'alias', 'indirect', 'generated', 'transient', ''):
            for action in ('install', 'upgrade', 'remove'):
                with self.subTest(choice=choice, action=action):
                    self.choice = choice
                    with self.assertRaises(fixtures.lifecycle.Refused):
                        self.policy.enter(action)
                    self.assert_no_admission(original)
                    self.assertEqual(self.original_unit, self.unit.read_bytes())

    def test_manager_query_failure_preserves_credentials_and_has_no_fence(self):
        original = self.fixture.data_identity()
        self.query_status = 47
        with self.assertRaises(fixtures.lifecycle.Refused):
            self.policy.enter('remove')
        self.assert_no_admission(original)

    def test_unpaired_static_modification_refuses_without_requiring_all_core_readers(self):
        path = self.fixture.physical / 'libexec/key-backup/manifest.json'
        manifest = json.loads(path.read_bytes())
        manifest.update(schema=2, protocol=2,
                        generation={'unitSha256': hashlib.sha256(self.original_unit).hexdigest()})
        self.fixture.write(path, fixtures.lifecycle.encoded(manifest), 0o640)
        self.fixture.write(self.unit, b'[Service]\nExecStart=/usr/bin/false\n', 0o644)
        self.choice = 'static'
        original = self.fixture.data_identity()
        with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'differs from its package'):
            self.policy.enter('upgrade')
        self.assert_no_admission(original)
        # The independent cold base still validates; no reader/start authority
        # was introduced to allow maintenance of a damaged Main runtime.
        self.assertEqual(2, self.policy.assets()['schema'])

    def test_supported_choices_remain_available_to_new_admission(self):
        for choice in ('enabled', 'enabled-runtime', 'disabled', 'masked', 'masked-runtime'):
            with self.subTest(choice=choice):
                self.choice = choice
                self.policy.check_main_package_layout(self.policy.assets())
        self.assertFalse(self.policy.state.exists())

    def test_static_choice_requires_a_paired_vendor_definition(self):
        self.choice = 'static'
        original = self.fixture.data_identity()
        with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'no paired package definition'):
            self.policy.enter('remove')
        self.assert_no_admission(original)
        self.pair_static_main()
        marker = self.policy.enter('remove')
        self.assertEqual('remove', marker['firstAction'])

    def test_static_choice_rejects_unpaired_effective_unit_before_fence(self):
        self.choice = 'static'
        self.pair_static_main()
        original = self.fixture.data_identity()
        effective = self.effective_main()
        for before, after in (('FragmentPath=/lib', 'FragmentPath=/etc'),
                              ('DropInPaths=', 'DropInPaths=/etc/systemd/system/kura.service.d/site.conf'),
                              ('NeedDaemonReload=no', 'NeedDaemonReload=yes'),
                              ('Transient=no', 'Transient=yes'),
                              ('SourcePath=', 'SourcePath=/etc/init.d/kura'),
                              ('Names=kura.service', 'Names=kura.service other.service')):
            with self.subTest(field=before):
                self.effective_main = lambda: effective.replace(before, after)
                with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'Effective Main unit'):
                    self.policy.enter('remove')
                self.assert_no_admission(original)

    def test_absent_main_does_not_disable_independent_cold_base_maintenance(self):
        self.unit.unlink()
        self.choice = ''
        marker = self.policy.enter('install')
        self.assertEqual('MAINTENANCE', marker['state'])
        self.assertFalse(any(args[1:3] == ['show', 'kura.service'] for args in self.fixture.calls))

    def test_existing_fence_keeps_original_id_through_post_unpack_reentry(self):
        marker = self.policy.enter('upgrade')
        secret = (self.policy.state / 'journal.key').read_bytes()
        self.choice = ''
        self.fixture.calls.clear()
        self.assertEqual(marker, self.policy.enter('install'))
        self.assertEqual(secret, (self.policy.state / 'journal.key').read_bytes())
        self.assertFalse(any(args[1:3] == ['show', 'kura.service'] for args in self.fixture.calls))


class MainLinkMigrationTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LifecycleTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.policy = self.fixture.policy
        self.policy.initialize()
        self.vendor = self.policy.path('/lib/systemd/system/kura.service')
        self.source = self.policy.path('/var/lib/old-core/kura.service')
        self.unit = b'[Service]\nExecStart=/usr/bin/false\n[Install]\nWantedBy=multi-user.target\n'
        self.fixture.write(self.source, self.unit, 0o644)
        self.manifest = {'schema': 2, 'generation': {'unitSha256': hashlib.sha256(self.unit).hexdigest()}}
        self.commands = []
        self.fail_reload = False
        self.active = False
        self.pairing_error = False
        mock = patch.object(self.policy, 'assets', side_effect=self.assets)
        mock.start()
        self.addCleanup(mock.stop)
        self.policy.runner = self.runner

    def assets(self, *, generation_binding=False, _linked_main_unit=None):
        if generation_binding:
            self.assertEqual(self.unit, _linked_main_unit)
            if self.pairing_error:
                raise fixtures.lifecycle.Refused('Generation reader does not match')
        return self.manifest

    def setup_link(self, choice):
        self.choice = choice
        self.fragment = fixtures.lifecycle.MAIN_LINKS[choice]
        self.link = self.policy.path(self.fragment)
        self.link.parent.mkdir(parents=True, exist_ok=True)
        self.link.symlink_to('/var/lib/old-core/kura.service')
        self.saved = self.link.with_name(fixtures.lifecycle.MAIN_LINK_BACKUP)

    def runner(self, args, **_):
        self.commands.append(args[1])
        if args[1:] == ['daemon-reload']:
            if self.fail_reload:
                return fixtures.types.SimpleNamespace(returncode=1)
            self.choice = 'disabled'
            self.fragment = '/lib/systemd/system/kura.service'
            return fixtures.types.SimpleNamespace(returncode=0, stdout='')
        field_string = args[-1].removeprefix('--property=')
        props = dict(Id='kura.service', Names='kura.service', LoadState='loaded', SourcePath='',
                     DropInPaths='', NeedDaemonReload='no', Transient='no', UnitFileState=self.choice,
                     FragmentPath=self.fragment, ActiveState='active' if self.active else 'inactive',
                     MainPID='0', ControlPID='0', Job='')
        return fixtures.types.SimpleNamespace(returncode=0, stdout='\n'.join(
            field + '=' + props[field] for field in field_string.split(',')) + '\n')

    def test_package_paired_links_convert_without_boot_or_maintenance_intent(self):
        for choice in ('linked', 'linked-runtime'):
            with self.subTest(choice=choice):
                self.setup_link(choice)
                migrate_linked_main(self.policy)
                self.assertEqual(self.vendor.read_bytes(), self.unit)
                self.assertEqual(self.source.read_bytes(), self.unit)
                self.assertFalse(self.link.is_symlink())
                self.assertFalse(self.saved.is_symlink())
                self.assertIsNone(self.policy.fence())
                self.assertEqual(self.choice, 'disabled')
        self.assertEqual(set(self.commands), {'show', 'daemon-reload'})

    def test_daemon_reload_failure_preserves_same_link_for_continuation(self):
        self.setup_link('linked-runtime')
        self.fail_reload = True
        with self.assertRaises(fixtures.lifecycle.Refused):
            migrate_linked_main(self.policy)
        self.assertTrue(self.saved.is_symlink())
        self.assertEqual(self.vendor.read_bytes(), self.unit)
        with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'Complete the existing Main link migration'):
            self.policy.check_main_package_layout(self.manifest)
        self.fail_reload = False
        migrate_linked_main(self.policy)
        self.assertFalse(self.saved.is_symlink())
        self.assertEqual(self.source.read_bytes(), self.unit)

    def test_busy_or_unpaired_link_refuses_before_vendor_publication(self):
        self.setup_link('linked')
        self.active = True
        with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'Main must be inactive'):
            migrate_linked_main(self.policy)
        self.active = False
        self.pairing_error = True
        with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'Generation reader does not match'):
            migrate_linked_main(self.policy)
        self.pairing_error = False
        self.source.write_bytes(b'Foreign unit')
        with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'Linked Main differs'):
            migrate_linked_main(self.policy)
        self.assertFalse(self.vendor.exists())
        self.assertTrue(self.link.is_symlink())
        self.assertNotIn('daemon-reload', self.commands)


if __name__ == '__main__':
    unittest.main()
