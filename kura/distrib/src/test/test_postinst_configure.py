# SPDX-License-Identifier: EPL-2.0
import hashlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import test_key_service_lifecycle as fixtures

MODULE = Path(__file__).resolve().parents[2] / 'kura-core/postinst-configure.py'
spec = importlib.util.spec_from_file_location('postinst_configure', MODULE)
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)
lifecycle = fixtures.lifecycle


class ConfigureTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LifecycleTest('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.policy = self.fixture.policy
        self.fence = self.policy.enter('install')
        manifest = self.fixture.physical / 'libexec/key-backup/manifest.json'
        self.manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
        self.configure = self.controller()
        self.stage = self.configure.state / self.fence['id']
        patched = patch.object(self.policy, 'generation_assets')
        self.pairing = patched.start()
        self.addCleanup(patched.stop)

    def controller(self, version='6.0.0-1'):
        return configure.Configure(lifecycle, self.policy, self.fixture.physical.resolve(), version, self.manifest_sha, '1' * 64)

    def install_steps(self):
        for name in configure.INSTALLER_STEPS:
            self.configure.run_step(name, lambda: None)

    def test_prepared_resumes_configuration_and_original_history_after_leave(self):
        self.assertEqual(('NEW', 'install'), self.configure.apply('status'))
        self.assertFalse(self.stage.exists())
        self.configure.apply('begin')
        self.install_steps()
        self.configure.apply('prepared')
        self.assertEqual(('PREPARED', 'install'), self.controller().apply('status'))
        self.assertEqual(('READY', 'install'), self.configure.apply('ready'))
        self.configure.apply('retire-copy')
        previous = self.fixture.data_identity()
        self.policy.leave()
        self.assertEqual(('READY', 'install'), self.controller().apply('status'))
        self.policy.leave()
        self.assertEqual(previous, self.fixture.data_identity())
        self.assertEqual([self.fence['id'] + '.json'], [p.name for p in (self.policy.state/'package-history').iterdir()])
        self.assertFalse((self.policy.state/'maintenance.json').exists())

    def test_an_unresolved_installer_is_never_dispatched_again(self):
        self.configure.apply('begin')
        before = (self.stage/'intent.json').read_bytes()
        calls = []

        def interrupt():
            calls.append('layout')
            raise InterruptedError()
        with self.assertRaises(InterruptedError):
            self.configure.run_step('layout', interrupt)
        for command in ('status', 'begin', 'prepared', 'ready', 'retire-copy'):
            with self.subTest(command=command), self.assertRaisesRegex(lifecycle.Refused, 'unresolved'):
                self.controller().apply(command)
        with self.assertRaisesRegex(lifecycle.Refused, 'layout is unresolved'):
            self.configure.run_step('layout', interrupt)
        self.assertEqual(calls, ['layout'])
        self.assertEqual(before, (self.stage/'intent.json').read_bytes())
        self.assertEqual(self.fence, self.policy.fence())
        self.pairing.assert_not_called()

    def test_configuration_rejects_other_package_versions_and_incomplete_receipts(self):
        self.configure.apply('begin')
        self.install_steps()
        self.configure.apply('prepared')
        with self.assertRaisesRegex(lifecycle.Refused, 'another package or Root'):
            self.controller('6.0.0-2').apply('status')
        (self.stage/'prepared.json').write_bytes(b'{}')
        with self.assertRaisesRegex(lifecycle.Refused, 'Invalid configure setup receipt'):
            self.configure.apply('status')
        self.assertEqual(self.fence, self.policy.fence())

    def test_restore_copy_is_retired_only_after_ready_and_only_with_its_original_identity(self):
        copy = self.configure.copies['upgrade']
        copy.mkdir(mode=0o700)
        self.fixture.write(copy/'snapshot.xml', b'original')
        self.assertEqual(('NEW', 'upgrade'), self.configure.apply('begin'))
        self.install_steps()
        self.configure.apply('prepared')
        with self.assertRaises(lifecycle.Refused):
            self.configure.apply('retire-copy')
        original = copy.with_name('exact-recovery-copy')
        copy.rename(original)
        copy.mkdir(mode=0o700)
        with self.assertRaisesRegex(lifecycle.Refused, 'copy changed'):
            self.configure.apply('ready')
        copy.rmdir()
        original.rename(copy)
        self.assertEqual(('READY', 'upgrade'), self.configure.apply('ready'))
        self.configure.apply('retire-copy')
        self.assertFalse(copy.exists())
        self.assertEqual(('READY', 'upgrade'), self.configure.apply('retire-copy'))

    def test_resume_dispatches_only_remaining_steps_in_order(self):
        self.configure.apply('begin')
        self.assertEqual(('INSTALLER', 'install'), self.controller().apply('status'))
        with self.assertRaisesRegex(lifecycle.Refused, 'Out-of-order'):
            self.configure.run_step('brokers', lambda: self.fail('Out-of-order dispatch'))
        with self.assertRaisesRegex(lifecycle.Refused, 'Missing completed'):
            self.configure.apply('prepared')
        calls = []
        self.configure.run_step('layout', lambda: calls.append('layout'))
        self.assertEqual(('INSTALLER', 'install'), self.controller().apply('status'))
        for step in configure.INSTALLER_STEPS:
            self.controller().run_step(step, lambda: calls.append(step))
        self.assertEqual(list(configure.INSTALLER_STEPS), calls)
        self.configure.apply('prepared')

    def test_step_receipt_cannot_be_substituted_for_another_step(self):
        self.configure.apply('begin')
        self.configure.run_step('layout', lambda: None)
        self.configure.run_step('brokers', lambda: None)
        (self.stage/'setup-brokers-complete.json').write_bytes((self.stage/'setup-layout-complete.json').read_bytes())
        with self.assertRaisesRegex(lifecycle.Refused, 'Invalid installer step receipt'):
            self.controller().run_step('runtime', lambda: self.fail('Dispatch after invalid receipt'))
        self.assertEqual(self.fence, self.policy.fence())
