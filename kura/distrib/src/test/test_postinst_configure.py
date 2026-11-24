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
import uuid

import test_key_service_lifecycle as fixtures

MODULE = Path(__file__).resolve().parents[2] / 'kura-core/postinst-configure.py'
spec = importlib.util.spec_from_file_location('postinst_configure', MODULE)
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)
repair = MODULE.with_name('prelayout-repair.py').read_bytes()
exec(compile(repair, 'prelayout-repair.py', 'exec'), vars(configure))
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

    def test_unpacked_main_placeholder_requires_empty_core_owned_directory(self):
        logical = self.policy.path('/opt/eclipse/kura')
        logical.unlink()
        logical.mkdir()
        logical.chmod(0o755)
        with patch.object(subprocess, 'check_output', return_value='kura-core: /opt/eclipse/kura\n'):
            self.assertTrue(os.path.samestat(logical.lstat(), self.configure.unpacked_main_directory(logical)))
            (logical / 'site-data').touch()
            with self.assertRaisesRegex(lifecycle.Refused, 'occupied Main directory'):
                self.configure.unpacked_main_directory(logical)
        (logical / 'site-data').unlink()
        with patch.object(subprocess, 'check_output', return_value='kura-core, addon: /opt/eclipse/kura\n'):
            with self.assertRaisesRegex(lifecycle.Refused, 'Core-owned'):
                self.configure.unpacked_main_directory(logical)
        self.assertTrue(logical.is_dir())

    def test_current_retained_profile_requires_the_exact_manifest_unit_set(self):
        units = {name: '1' * 64 for name in lifecycle.NATIVE_MAIN_UNITS}
        manifest = dict(schema=2, protocol=2,
                        files={name: '2' * 64 for name in lifecycle.SNAPSHOT_PUBLICATION_ASSETS},
                        units=units, generation={})
        self.assertEqual(units, configure.retained_vendor_profile(lifecycle, manifest, tuple(units)))
        manifest['units'] = {name: '1' * 64 for name in lifecycle.NATIVE_VALIDATION_UNITS}
        with self.assertRaisesRegex(lifecycle.Refused, 'Unpaired retained key-service unit profile'):
            configure.retained_vendor_profile(lifecycle, manifest, tuple(units))

    def test_removed_generation_successor_requires_both_manifest_pins_and_original_start(self):
        installed, origin, incoming = '1' * 64, '2' * 64, '3' * 64
        release = dict(manifestSha256=installed, publicationManifestSha256=origin)
        publication = dict(operationId=str(uuid.uuid4()))
        scope = dict(require=lifecycle.require, _KURA_INCOMING_KEY_MANIFEST_SHA256=incoming)
        source = MODULE.with_name('retained-generation-preflight.py')
        exec(compile(source.read_bytes(), str(source), 'exec'), scope)
        secret = self.policy.read(self.policy.state / 'journal.key', limit=32)

        def admit(pins):
            scope['_KURA_INCOMING_KEY_PREDECESSORS'] = pins
            scope['check_removed_generation_release'](lifecycle, self.policy, release, publication, secret)

        scope['_KURA_INCOMING_KEY_MANIFEST_SHA256'] = installed
        admit(())
        scope['_KURA_INCOMING_KEY_MANIFEST_SHA256'] = incoming
        for pins in ((installed,), (origin,)):
            with self.subTest(pins=pins):
                with self.assertRaisesRegex(lifecycle.Refused, 'differs from the retained generation cohort'):
                    admit(pins)

        pins = (installed, origin)
        with self.assertRaisesRegex(lifecycle.Refused, 'original completed generation startup'):
            admit(pins)
        operation = str(uuid.uuid4())
        record = dict(schema=1, operationId=operation, action='generation-core-start', requestTag='4' * 64,
                      state='SUCCEEDED')
        response = dict(schema=1, operationId=operation, action=record['action'], state=record['state'],
                        publicationId=publication['operationId'], scope='SYSTEMD_JOB_ACCEPTED',
                        jobPath='/org/freedesktop/systemd1/job/42', ringSha256='5' * 64, activeKeySha256='6' * 64,
                        cohortSha256='7' * 64)
        self.policy.create(self.policy.state / 'operations' / f'{operation}.json',
                           lifecycle.encoded(dict(record, response=response)))
        with patch.object(lifecycle, 'archive_entry', side_effect=lifecycle.Refused('Invalid original startup proof')):
            with self.assertRaisesRegex(lifecycle.Refused, 'Invalid original startup proof'):
                admit(pins)
        with patch.object(lifecycle, 'archive_entry') as verify:
            admit(pins)
            verify.assert_called_once_with(self.policy, dict(directory='operations', operationId=operation), secret)

    def test_retained_repair_requires_the_exact_signed_source_and_successor(self):
        source = self.configure
        retained = source.copies['reinstall']
        retained.mkdir(mode=0o700)
        source.apply('begin')
        original = self.fence['id']
        raw = (self.stage / 'intent.json').read_bytes()
        recovery, secret = source.read_intent(self.stage, original)
        predecessor = {key: value for key, value in source.binding.items() if key != 'schema'}
        successor = configure.Configure(lifecycle, self.policy, source.physical, '6.0.0-2',
                                         self.manifest_sha, '2' * 64, predecessor)
        with self.assertRaisesRegex(lifecycle.Refused, 'another package or Root'):
            successor.read_intent(self.stage, original)
        target = {key: value for key, value in successor.binding.items() if key != 'schema'}
        receipt = configure.layout_repair_receipt(lifecycle, self.policy, original, raw, recovery,
                                                  predecessor, target, secret)
        marker = self.stage / configure.LAYOUT_REPAIR
        self.policy.create(marker, receipt)
        self.assertEqual((recovery, secret), successor.read_intent(self.stage, original))
        self.assertEqual(raw, (self.stage / 'intent.json').read_bytes())
        with self.assertRaisesRegex(lifecycle.Refused, 'handed off'):
            source.read_intent(self.stage, original)
        other = configure.Configure(lifecycle, self.policy, source.physical, '6.0.0-2',
                                     self.manifest_sha, '3' * 64, predecessor)
        with self.assertRaisesRegex(lifecycle.Refused, 'Unpaired retained layout repair receipt'):
            other.read_intent(self.stage, original)

    def test_prelayout_retry_allows_postinst_published_ahead_of_dpkg_version(self):
        self.configure.copies['reinstall'].mkdir(mode=0o700)
        intent = self.stage / 'intent.json'
        receipt = self.stage / configure.LAYOUT_REPAIR
        old_version, new_version = '6.0.0-1', '6.0.0-2'
        old_control, new_control = b'predecessor postinst', b'successor postinst'
        predecessor = dict(packageVersion=old_version, manifestSha256=self.manifest_sha,
                           postinstSha256=hashlib.sha256(old_control).hexdigest())
        source = configure.Configure(lifecycle, self.policy, self.fixture.physical.resolve(), old_version,
                                     self.manifest_sha, predecessor['postinstSha256'])
        source.apply('begin')
        original_intent = intent.read_bytes()
        fields = dict(_KURA_LAYOUT_REPAIR_PREDECESSOR=predecessor,
                      _KURA_LAYOUT_REPAIR_HOME=self.fixture.physical.name,
                      _KURA_INCOMING_KEY_MANIFEST_SHA256=self.manifest_sha,
                      _KURA_LAYOUT_REPAIR_POSTINST_SHA256=hashlib.sha256(new_control).hexdigest(),
                      require=lifecycle.require, paired_lifecycle=lambda: lifecycle,
                      prepare_retained_generation=lambda *, unpacked_layout: (0 if unpacked_layout else 1))
        environment = dict(DPKG_MAINTSCRIPT_PACKAGE='kura-core', DPKG_MAINTSCRIPT_NAME='preinst',
                           DPKG_ROOT='', DPKG_ADMINDIR='/var/lib/dpkg')
        control = self.policy.path('/var/lib/dpkg/info/kura-core.postinst')
        self.policy.path('/opt/eclipse/kura').unlink()
        for unit in lifecycle.UNITS:
            self.policy.path('/lib/systemd/system/' + unit).unlink()
        interrupted = 'install reinstreq half-installed'
        active_fence = dict(self.fence, firstAction='remove')
        parked_main = dict(MainPID='0', ControlPID='0', LoadState='not-found', ActiveState='inactive')
        with patch.dict(configure.__dict__, fields), patch.dict(os.environ, environment), \
                patch.object(lifecycle, 'Lifecycle', return_value=self.policy), \
                patch.object(self.policy, 'fence', return_value=active_fence), \
                patch.object(self.policy, 'main_unit_properties', return_value=parked_main), \
                patch.object(configure.subprocess, 'check_output') as dpkg_query:
            dpkg_query.return_value = f'{interrupted}\n{old_version}'
            self.fixture.write(control, new_control, 0o755)
            with self.assertRaisesRegex(lifecycle.Refused, 'Unpaired installed Core postinst'):
                configure.admit_prelayout_repair(old_version, new_version)
            self.assertFalse(receipt.exists())

            self.fixture.write(control, old_control, 0o755)
            configure.admit_prelayout_repair(old_version, new_version)
            signed = receipt.read_bytes()
            identity = receipt.stat().st_ino
            self.fixture.write(control, new_control, 0o755)
            configure.admit_prelayout_repair(old_version, new_version)
            self.assertEqual((signed, identity), (receipt.read_bytes(), receipt.stat().st_ino))

            for state, version, raw in (
                ('install ok unpacked', old_version, new_control),
                (interrupted, old_version, b'unpaired postinst'),
                (interrupted, new_version, old_control),
            ):
                with self.subTest(state=state, version=version, control=raw):
                    dpkg_query.return_value = f'{state}\n{version}'
                    self.fixture.write(control, raw, 0o755)
                    with self.assertRaisesRegex(lifecycle.Refused, 'Unpaired installed Core postinst'):
                        configure.admit_prelayout_repair(version, new_version)
                    self.assertEqual((signed, identity), (receipt.read_bytes(), receipt.stat().st_ino))

            dpkg_query.return_value = f'{interrupted}\n{old_version}'
            self.fixture.write(control, new_control, 0o755)
            receipt.write_bytes(signed.replace(new_version.encode(), b'6.0.0-3'))
            with self.assertRaisesRegex(lifecycle.Refused, 'Original layout repair authorization changed'):
                configure.admit_prelayout_repair(old_version, new_version)
            self.assertEqual(original_intent, intent.read_bytes())

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
        saved_manifest = old / 'libexec/key-backup/manifest.json'
        saved_manifest.parent.mkdir(parents=True)
        saved_manifest.write_bytes((physical / 'libexec/key-backup/manifest.json').read_bytes())
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

    def test_retained_layout_syncs_pid_one_before_issuing_intent(self):
        controller = self.configure
        controller.copies['reinstall'].mkdir(mode=0o700)
        self.policy.create(self.policy.state / 'generation-current.json', b'paired generation')
        controller.apply('begin')
        intent = self.stage / 'setup-layout-intent.json'
        unit = 'kura-key-recovery.service'
        vendor = self.policy.path('/lib/systemd/system/' + unit)
        vendor.unlink()
        load_state = 'error'
        fail_reload = True
        command = self.policy.command

        def restore(original, *, purged):
            self.assertEqual(self.fence['id'], original)
            self.assertFalse(purged)
            self.assertFalse(intent.exists())
            vendor.write_bytes(b'paired vendor unit')

        def manager(arguments):
            nonlocal load_state
            if arguments == ['daemon-reload']:
                self.assertEqual(b'paired vendor unit', vendor.read_bytes())
                self.assertFalse(intent.exists())
                if fail_reload:
                    raise lifecycle.Refused('PID 1 reload failed')
                load_state = 'loaded'
                return ''
            if arguments == ['show', unit, '--property=LoadState']:
                return f'LoadState={load_state}\n'
            return command(arguments)

        def invoke():
            self.assertTrue(intent.is_file())
            self.assertEqual(self.fence, self.policy.enter('install'))

        with patch.object(controller, 'restore_removed_generation', side_effect=restore), \
                patch.object(self.policy, 'check_extended_journal'), \
                patch.object(self.policy, 'command', side_effect=manager):
            with self.assertRaisesRegex(lifecycle.Refused, 'PID 1 reload failed'):
                controller.run_step('layout', lambda: self.fail('Dispatched after failed reload'))
            self.assertFalse(intent.exists())
            self.assertEqual(self.fence, self.policy.fence())
            fail_reload = False
            controller.run_step('layout', invoke)
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
