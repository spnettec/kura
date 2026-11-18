#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Main layout refusal must precede package-maintenance side effects."""
import hashlib
import json
import unittest

import test_key_service_lifecycle as fixtures


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
            return previous_runner(args, **kwargs)
        self.policy.runner = runner

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
        for choice in ('enabled', 'enabled-runtime', 'disabled', 'static', 'masked', 'masked-runtime'):
            with self.subTest(choice=choice):
                self.choice = choice
                self.policy.check_main_package_layout(self.policy.assets())
        self.assertFalse(self.policy.state.exists())

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


if __name__ == '__main__':
    unittest.main()
