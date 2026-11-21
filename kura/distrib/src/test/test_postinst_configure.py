# SPDX-License-Identifier: EPL-2.0
import errno
import hashlib
import hmac
import importlib.util
import os
import signal
from pathlib import Path
import subprocess
import sys
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
            self.configure.apply('resume')

    @unittest.skipUnless(os.geteuid() == 0, 'checks a root-owned package fence')
    def test_abort_preserves_an_incomplete_original_configure(self):
        marker = self.policy.state / 'maintenance.json'
        configure.check_aborted_change(marker, self.configure.state)
        self.configure.apply('begin')
        self.install_steps()
        self.configure.apply('prepared')
        before = marker.read_bytes()
        with self.assertRaisesRegex(ValueError, 'still fenced'):
            configure.check_aborted_change(marker, self.configure.state)
        self.assertEqual(before, marker.read_bytes())
        self.assertFalse((self.stage / 'ready.json').exists())
        self.configure.apply('ready')
        with self.assertRaisesRegex(ValueError, 'still fenced'):
            configure.check_aborted_change(marker, self.configure.state)
        self.policy.leave()
        configure.check_aborted_change(marker, self.configure.state)

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

    def test_sibling_trigger_retries_only_after_completed_postinstall(self):
        self.configure.apply('begin')
        self.install_steps()
        self.configure.apply('prepared')
        self.configure.apply('ready')
        calls = []
        def reconcile():
            calls.append('ownership')
            if len(calls) == 1:
                raise BlockingIOError('busy ownership lock')
        with self.assertRaises(lifecycle.Refused):
            self.configure.apply('sibling-code', reconcile)
        self.policy.leave()
        self.assertEqual('CONFIGURE', self.configure.apply('configure-route')[0])
        with self.assertRaises(lifecycle.Refused):
            self.configure.apply('sibling-code', reconcile)
        self.configure.apply('configured')
        with self.assertRaises(BlockingIOError):
            self.configure.apply('sibling-code', reconcile)
        self.assertEqual('CONFIGURED', self.configure.apply('configure-route')[0])
        self.controller().apply('sibling-code', reconcile)
        self.assertEqual(['ownership', 'ownership'], calls)
        with self.assertRaises(lifecycle.Refused):
            self.controller('6.0.1-1').apply('sibling-code', reconcile)

    def test_interrupted_intent_staging_keeps_the_original_fence_available(self):
        def interrupt(pending, published):
            self.assertEqual(published, self.stage)
            self.assertFalse(published.exists())
            self.assertTrue((pending / 'intent.json').is_file())
            raise InterruptedError('before configure intent publication')

        with patch.object(configure.os, 'rename', side_effect=interrupt), self.assertRaises(InterruptedError):
            self.configure.apply('begin')
        self.assertFalse(self.stage.exists())
        self.assertEqual(self.fence, self.policy.fence())
        abandoned = self.stage.with_name(f'.{self.stage.name}-unfinished')
        abandoned.mkdir(mode=0o700)
        self.fixture.write(abandoned / 'intent.json', b'incomplete')

        self.assertEqual(('NEW', 'install'), self.controller().apply('status'))
        self.assertEqual(('NEW', 'install'), self.controller().apply('begin'))
        self.assertEqual(('INSTALLER', 'install'), self.controller().apply('status'))
        self.assertEqual(self.fence, self.policy.fence())
        self.assertEqual(list(self.stage.iterdir()), [self.stage / 'intent.json'])
        self.assertEqual((abandoned / 'intent.json').read_bytes(), b'incomplete')

    def test_existing_original_directory_without_intent_is_still_refused(self):
        self.configure.state.mkdir(mode=0o700)
        self.stage.mkdir(mode=0o700)
        with self.assertRaises(FileNotFoundError):
            self.controller().apply('begin')
        self.assertEqual(list(self.stage.iterdir()), [])
        self.assertEqual(self.fence, self.policy.fence())

    def test_an_unresolved_installer_is_never_dispatched_again(self):
        self.configure.apply('begin')
        before = (self.stage/'intent.json').read_bytes()
        calls = []

        def interrupt():
            calls.append('layout')
            raise InterruptedError()
        with self.assertRaises(InterruptedError):
            self.configure.run_step('layout', interrupt)
        for command in ('status', 'resume', 'begin', 'prepared', 'ready', 'retire-copy'):
            with self.subTest(command=command), self.assertRaisesRegex(lifecycle.Refused, 'unresolved'):
                self.controller().apply(command)
        with self.assertRaisesRegex(lifecycle.Refused, 'layout is unresolved'):
            self.configure.run_step('layout', interrupt)
        self.assertEqual(calls, ['layout'])
        self.assertEqual(before, (self.stage/'intent.json').read_bytes())
        self.assertEqual(self.fence, self.policy.fence())
        self.pairing.assert_not_called()

    def test_published_launcher_restore_resumes_before_layout_intent(self):
        controller = self.configure
        physical = controller.physical
        capture_dir = controller.copies['upgrade']
        old = capture_dir / '.old-home'
        (old / 'bin').mkdir(mode=0o700, parents=True)
        capture_dir.chmod(0o700)
        secret = self.policy.read(self.policy.state / 'journal.key', limit=32)
        original = self.fence['id']
        capture = dict(root=controller.package_identity(self.policy.root), stage=controller.package_identity(capture_dir),
                       source=dict(name=physical.name, **controller.package_identity(old)), maintenanceId=original)
        capture['tag'] = hmac.new(secret, b'kura-core-preinst-capture-v1\0' + lifecycle.encoded(capture), hashlib.sha256).hexdigest()
        self.policy.create(capture_dir / '.capture.json', lifecycle.encoded(capture))
        current = self.policy.state / 'generation-current.json'
        names = ('start_kura.sh', 'start_kura_background.sh', 'start_kura_debug.sh')
        templates = physical / 'libexec/key-backup/launchers'
        templates.mkdir(parents=True, exist_ok=True)
        for name in names:
            (templates / name).write_bytes(b'example -Xms1024m -Xmx1024m')
            (physical / 'bin' / name).write_bytes((templates / name).read_bytes())
            (old / 'bin' / name).write_bytes(b'example -Xms256m -Xmx1024m')
        def binding(home):
            hashes = {n: hashlib.sha256((home / 'bin' / n).read_bytes()).hexdigest() for n in names}
            value = dict(schema=1, purpose='yofc-kura-key-generation-package-v1',
                         manifestSha256=self.manifest_sha, launcherSha256s=hashes)
            return dict(value, cohortSha256=hashlib.sha256(lifecycle.encoded(value)).hexdigest())
        self.policy.create(current, lifecycle.encoded(dict(operationId=original, cohortSha256=binding(old)['cohortSha256'])))
        self.pairing.side_effect = lambda: binding(physical)
        controller.apply('begin')
        replace = os.replace
        def interrupt(source, dest):
            if dest.name == names[1]:
                raise InterruptedError()
            replace(source, dest)
        with patch.object(self.policy, 'check_extended_journal'), patch.object(lifecycle, 'validate_publication', side_effect=lambda v:v), patch.object(lifecycle, 'archive_entry'):
            last = old / 'bin' / names[-1]
            last.write_bytes(last.read_bytes() + b'changed')
            with self.assertRaisesRegex(lifecycle.Refused, 'Retained launchers differ'):
                controller.run_step('layout', lambda: self.fail('Unexpected dispatch'))
            self.assertEqual((templates / names[0]).read_bytes(), (physical / 'bin' / names[0]).read_bytes())
            last.write_bytes((old / 'bin' / names[0]).read_bytes())
            with patch.object(configure.os, 'replace', side_effect=interrupt), self.assertRaises(InterruptedError):
                controller.run_step('layout', lambda: self.fail('Unexpected dispatch'))
            self.assertFalse((self.stage / 'setup-layout-intent.json').exists())
            self.assertEqual((old / 'bin' / names[0]).read_bytes(), (physical / 'bin' / names[0]).read_bytes())
            self.assertEqual((templates / names[1]).read_bytes(), (physical / 'bin' / names[1]).read_bytes())
            controller.run_step('layout', lambda: self.assertEqual(binding(old), binding(physical)))
            self.assertTrue((self.stage / 'setup-layout-returned.json').is_file())

    def test_broker_quiescence_precedes_the_original_upgrade_dispatch(self):
        self.configure.copies['upgrade'].mkdir(mode=0o700)
        self.configure.apply('begin')
        self.configure.run_step('layout', lambda: None)
        self.configure.apply('resume')
        brokers_intent = self.stage / 'setup-brokers-intent.json'

        def reject_active_unpaired_broker(mode):
            self.assertEqual(mode, 'upgrade')
            self.assertFalse(brokers_intent.exists())
            raise lifecycle.Refused('Unpaired active broker')

        with self.assertRaisesRegex(lifecycle.Refused, 'Unpaired active broker'):
            self.controller().run_step(
                'brokers', lambda: self.fail('Dispatched before quiescence'),
                prepare_brokers=reject_active_unpaired_broker,
            )
        self.assertFalse(brokers_intent.exists())
        self.assertEqual(('INSTALLER', 'upgrade'), self.controller().apply('resume'))

        def interrupted_dispatch():
            self.assertTrue(brokers_intent.is_file())
            raise InterruptedError()

        with self.assertRaises(InterruptedError):
            self.controller().run_step('brokers', interrupted_dispatch, prepare_brokers=lambda mode: None)
        with self.assertRaisesRegex(lifecycle.Refused, 'brokers is unresolved'):
            self.controller().run_step(
                'brokers', lambda: self.fail('Redispatched unresolved broker setup'),
                prepare_brokers=lambda mode: self.fail('Prepared an already issued step'),
            )

    def test_new_install_can_resume_when_system_bus_was_unavailable_before_dispatch(self):
        self.configure.apply('begin')
        self.configure.run_step('layout', lambda: None)
        self.configure.apply('resume')
        original = (self.stage / 'intent.json').read_bytes()
        calls = []

        def unavailable(mode):
            self.assertEqual('install', mode)
            raise subprocess.CalledProcessError(1, 'busctl')

        with self.assertRaises(subprocess.CalledProcessError):
            self.configure.run_step('brokers', lambda: calls.append('dispatched'), prepare_brokers=unavailable)
        self.assertFalse((self.stage / 'setup-brokers-intent.json').exists())
        self.assertEqual(('INSTALLER', 'install'), self.controller().apply('resume'))
        self.controller().run_step('brokers', lambda: calls.append('dispatched'), prepare_brokers=calls.append)
        self.controller().apply('resume')
        self.assertEqual(['install', 'dispatched'], calls)
        self.assertEqual(original, (self.stage / 'intent.json').read_bytes())

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
        with patch.object(configure.os, 'sync', side_effect=InterruptedError), self.assertRaises(InterruptedError):
            self.configure.apply('ready')
        self.assertTrue(copy.is_dir())
        self.assertFalse((self.stage / 'ready.json').exists())
        self.assertEqual(('PREPARED', 'upgrade'), self.controller().apply('resume'))
        self.assertEqual(('READY', 'upgrade'), self.configure.apply('ready'))
        self.configure.apply('retire-copy')
        self.assertFalse(copy.exists())
        self.assertEqual(('READY', 'upgrade'), self.configure.apply('retire-copy'))

    @unittest.skipUnless(sys.platform == 'linux', 'Linux package uses atomic no-replace rename')
    def test_sibling_resume_ignores_partial_staging_and_preserves_an_unpacked_sibling(self):
        source = self.configure.copies['upgrade']
        source.mkdir(mode=0o700)
        self.fixture.write(source / 'siblings/retained/6s/bundle.jar', b'original bundle')
        self.fixture.write(source / 'siblings/replaced/6s/bundle.jar', b'old bundle')
        installed = self.fixture.physical / 'siblings'
        incoming = installed / 'replaced/6s/bundle.jar'
        self.fixture.write(incoming, b'incoming package bundle')
        incoming_inode = incoming.stat().st_ino
        self.configure.apply('begin')
        self.install_steps()
        self.configure.apply('prepared')
        stage = self.fixture.physical / ('.kura-restore-' + self.fence['id'])
        stale = stage / 'copy-abandoned' / 'retained/6s/bundle.jar'
        self.fixture.write(stale, b'orig')
        installed_bundle = installed / 'retained/6s/bundle.jar'
        self.pairing.side_effect = lambda: self.assertEqual([incoming], list(installed.rglob('*.jar')))

        def fail_copy(args, **kwargs):
            self.assertFalse(stale.exists())
            self.assertFalse(installed_bundle.exists())
            self.fixture.write(Path(args[-1]) / '6s/bundle.jar', b'ori')
            raise subprocess.CalledProcessError(1, args)

        with patch.object(configure.subprocess, 'run', side_effect=fail_copy), self.assertRaises(subprocess.CalledProcessError):
            self.controller().apply('restore-siblings')
        self.assertFalse(installed_bundle.exists())
        self.assertFalse((self.stage / 'ready.json').exists())
        self.assertTrue(source.is_dir())

        def fail_writeback(fd):
            self.assertEqual(stage.stat().st_ino, os.fstat(fd).st_ino)
            staged, = stage.glob('copy-*/retained/6s/bundle.jar')
            self.assertEqual(b'original bundle', staged.read_bytes())
            raise OSError(errno.EIO, 'staged filesystem writeback failed')

        with patch.object(configure, 'sync_staged_filesystem', side_effect=fail_writeback):
            with self.assertRaises(OSError) as failure:
                self.controller().apply('restore-siblings')
        self.assertEqual(errno.EIO, failure.exception.errno)
        self.assertFalse(installed_bundle.exists())
        self.assertFalse(stage.exists())
        self.assertFalse((self.stage / 'ready.json').exists())
        self.assertEqual(self.fence, self.policy.fence())
        self.assertEqual(b'original bundle', (source / 'siblings/retained/6s/bundle.jar').read_bytes())

        self.assertEqual(('PREPARED', 'upgrade'), self.controller().apply('restore-siblings'))
        installed_inode = installed_bundle.stat().st_ino
        self.pairing.side_effect = None
        self.controller().apply('restore-siblings')
        self.assertEqual(b'original bundle', installed_bundle.read_bytes())
        self.assertEqual(installed_inode, installed_bundle.stat().st_ino)
        self.assertEqual(b'incoming package bundle', incoming.read_bytes())
        self.assertEqual(incoming_inode, incoming.stat().st_ino)
        self.assertFalse(stage.exists())
        self.assertTrue(source.is_dir())
        self.assertEqual(('PREPARED', 'upgrade'), self.controller().apply('status'))
        self.assertEqual(self.fence, self.policy.fence())

    @unittest.skipUnless(sys.platform == 'linux', 'uses Linux atomic directory publication')
    def test_resume_after_process_dies_between_sibling_publications(self):
        source = self.configure.copies['upgrade'] / 'siblings'
        installed = self.fixture.physical / 'siblings'
        installed.mkdir()
        first = Path('first/3/provider.jar')
        second = Path('second/4/provider.jar')
        self.fixture.write(source / first, b'first provider')
        self.fixture.write(source / second, b'second provider')
        self.configure.apply('begin')
        self.install_steps()
        self.configure.apply('prepared')

        publish = configure.publish_sibling

        def publish_then_stop(staged, target):
            publish(staged, target)
            os.kill(os.getpid(), signal.SIGKILL)

        child = os.fork()
        if child == 0:
            try:
                with patch.object(configure, 'publish_sibling', side_effect=publish_then_stop):
                    self.controller().apply('restore-siblings')
            finally:
                os._exit(1)
        _, status = os.waitpid(child, 0)
        self.assertEqual(-signal.SIGKILL, os.waitstatus_to_exitcode(status))
        self.assertEqual(b'first provider', (installed / first).read_bytes())
        first_inode = (installed / first).stat().st_ino
        self.assertFalse((installed / second).exists())
        stage = self.fixture.physical / ('.kura-restore-' + self.fence['id'])
        self.assertEqual(1, len(list(stage.glob('copy-*/' + str(second)))))
        self.assertEqual(('PREPARED', 'upgrade'), self.controller().apply('status'))

        self.assertEqual(('PREPARED', 'upgrade'), self.controller().apply('restore-siblings'))
        self.assertEqual(first_inode, (installed / first).stat().st_ino)
        for entry in (first, second):
            self.assertEqual((source / entry).read_bytes(), (installed / entry).read_bytes())
        self.assertFalse(stage.exists())
        self.assertFalse((self.stage / 'ready.json').exists())
        self.assertEqual(self.fence, self.policy.fence())

    def test_resume_dispatches_only_remaining_steps_in_order(self):
        self.configure.apply('begin')
        self.assertEqual(('INSTALLER', 'install'), self.controller().apply('status'))
        with self.assertRaisesRegex(lifecycle.Refused, 'Out-of-order'):
            self.configure.run_step('brokers', lambda: self.fail('Out-of-order dispatch'))
        with self.assertRaisesRegex(lifecycle.Refused, 'Missing completed'):
            self.configure.apply('prepared')
        calls = []
        self.configure.run_step('layout', lambda: calls.append('layout'))
        self.configure.apply('resume')
        self.assertEqual(('INSTALLER', 'install'), self.controller().apply('status'))
        for step in configure.INSTALLER_STEPS:
            self.controller().run_step(step, lambda: calls.append(step))
            self.controller().apply('resume')
        self.assertEqual(list(configure.INSTALLER_STEPS), calls)
        self.configure.apply('prepared')

    def test_step_receipt_cannot_be_substituted_for_another_step(self):
        self.configure.apply('begin')
        self.configure.run_step('layout', lambda: None)
        self.configure.apply('resume')
        self.configure.run_step('brokers', lambda: None)
        self.configure.apply('resume')
        (self.stage/'setup-brokers-complete.json').write_bytes((self.stage/'setup-layout-complete.json').read_bytes())
        with self.assertRaisesRegex(lifecycle.Refused, 'Invalid installer step receipt'):
            self.controller().run_step('runtime', lambda: self.fail('Dispatch after invalid receipt'))
        self.assertEqual(self.fence, self.policy.fence())

    def test_resume_completes_only_the_exact_original_returned_step(self):
        self.configure.apply('begin')
        self.configure.run_step('layout', lambda: None)
        witness = self.stage / 'setup-layout-returned.json'
        receipt = self.stage / 'setup-layout-complete.json'
        before = self.fixture.data_identity()
        self.assertFalse(receipt.exists())
        with self.assertRaisesRegex(lifecycle.Refused, 'layout is unresolved'):
            self.controller().run_step('layout', lambda: self.fail('Dispatched again'))
        with self.assertRaisesRegex(lifecycle.Refused, 'another package or Root'):
            self.controller('6.0.0-2').apply('resume')
        self.assertFalse(receipt.exists())
        proof = witness.read_bytes()
        witness.write_bytes(b'{}')
        with self.assertRaisesRegex(lifecycle.Refused, 'Invalid installer success evidence'):
            self.controller().apply('resume')
        self.assertFalse(receipt.exists())
        witness.write_bytes(proof)
        self.assertEqual(('INSTALLER', 'install'), self.controller().apply('resume'))
        self.assertTrue(receipt.is_file())
        self.assertEqual(proof, witness.read_bytes())
        self.controller().run_step('layout', lambda: self.fail('Dispatched after completion'))
        self.assertEqual(self.fence, self.policy.fence())
        self.assertEqual(before, self.fixture.data_identity())
