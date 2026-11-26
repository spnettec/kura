# SPDX-License-Identifier: EPL-2.0
"""Run against a private directory on Linux. No live installation is used."""
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0 and os.access('/var/lib', os.W_OK),
                     'requires a private Root-owned directory on Linux')
class CoreRemovalHomeTest(unittest.TestCase):
    def setUp(self):
        module_path = Path(__file__).resolve().parents[2] / 'kura-core/removal-home.py'
        spec = importlib.util.spec_from_file_location('removal_home', module_path)
        self.home = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.home)
        tmp = tempfile.TemporaryDirectory(dir='/var/lib')
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.home.PARENT = base / 'eclipse'
        self.home.HOME = self.home.PARENT / 'kura'
        self.home.PARENT.mkdir()
        self.target = self.home.PARENT / 'kura_original'
        self.target.mkdir()
        self.home.HOME.symlink_to(self.target)
        self.retained = base / 'retained'
        self.retained.mkdir(mode=0o700)
        (self.retained / 'systemd').mkdir()
        self.op = str(uuid.uuid4())
        (self.retained / 'systemd/main-state.json').write_text(json.dumps({'maintenanceId': self.op}))
        framework = self.target / 'framework'
        framework.mkdir()
        self.registry = framework / 'sibling-install-order'
        self.registry.write_bytes(b'site-first\nsite-last')
        self.registry.chmod(0o640)
        os.chown(self.registry, 0, 1234)
        (framework / 'sibling-install-order.lock').touch(mode=0o600)

    def test_witness_resumes_only_original_unpublished_directory(self):
        base = self.retained.parent
        stage = self.retained.rename(base / '.kura-retained.tmp.A1234567')
        destination = base / 'kura-retained'
        self.home.JOURNAL_KEY = base / 'journal.key'
        self.home.JOURNAL_KEY.write_bytes(os.urandom(32))
        self.home.JOURNAL_KEY.chmod(0o600)
        fence = base / 'maintenance.json'
        def select(operation):
            fence.write_text(json.dumps(dict(id=operation, state='MAINTENANCE', firstAction='remove')))
        select(self.op)
        self.assertEqual('NEW', self.home.locate_retention(destination))
        self.home.capture(stage)
        self.assertEqual(str(stage), self.home.locate_retention(destination))
        select(str(uuid.uuid4()))
        with self.assertRaisesRegex(ValueError, 'no paired installation witness'):
            self.home.locate_retention(destination)
        select(self.op)
        original = stage.rename(base / 'original')
        shutil.copytree(original, stage)
        with self.assertRaisesRegex(ValueError, 'staging directory changed'):
            self.home.locate_retention(destination)
        shutil.rmtree(stage)
        original.rename(stage)
        stage.rename(destination)
        self.assertEqual('PUBLISHED', self.home.locate_retention(destination))
        select(str(uuid.uuid4()))
        with self.assertRaisesRegex(ValueError, 'no paired installation witness'):
            self.home.locate_retention(destination)

    def test_removal_keeps_site_precedence_and_metadata_without_copying_lock(self):
        os.setxattr(self.registry, 'user.site-label', b'order')
        self.home.capture(self.retained)
        original = self.registry.stat()
        expected = self.registry.read_bytes()
        self.home.remove(self.retained)
        framework = self.retained / 'framework'
        self.assertEqual(['sibling-install-order'], os.listdir(framework))
        saved = framework / 'sibling-install-order'
        self.assertEqual(expected, saved.read_bytes())
        self.assertEqual(b'order', os.getxattr(saved, 'user.site-label'))
        actual = saved.stat()
        for field in ('st_uid', 'st_gid', 'st_mode', 'st_mtime_ns'):
            self.assertEqual(getattr(original, field), getattr(actual, field), field)

    def test_completed_job_across_removal_and_reinstall(self):
        import hashlib
        import test_postinst_configure as configure_tests

        site = self.target / 'packages'
        site.mkdir()
        receipt = site / ('.dpa.properties.install-' + 'a' * 64 + '.done')
        receipt.write_bytes(b'completed')
        (site / 'dpa.properties').write_bytes(b'site registry')
        actual = (site.stat().st_ino, receipt.stat().st_ino)
        data = self.target / 'data'
        data.mkdir(mode=0o700)
        provider = data / 'store.save'
        provider.write_bytes(b'retained provider record')
        provider.chmod(0o600)
        original_data = data.stat()
        original_provider = provider.stat()
        root = self.home.PARENT.parent
        key = root / 'journal.key'
        key.write_bytes(os.urandom(32))
        key.chmod(0o600)
        self.home.ROOT = root
        self.home.JOURNAL_KEY = key
        self.home.capture(self.retained)
        with self.assertRaises(FileNotFoundError):
            self.home.remove(self.retained)
        self.home.park(self.retained)
        self.home.park(self.retained)
        record = self.home.package_record(self.retained)
        holder = self.home.PARENT / record['holder']
        self.home.remove(self.retained)
        self.target.mkdir()
        self.home.HOME.symlink_to(self.target)
        data.mkdir(mode=0o700)
        site.mkdir()
        (site / 'dpa.properties').write_bytes(b'factory registry')
        (site / 'new.dp').write_bytes(b'factory DP')
        manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in site.iterdir()}
        api = configure_tests.lifecycle
        policy = api.Lifecycle(root, os.geteuid())
        config = configure_tests.configure.Configure(api, policy, self.target, '1', 'a'*64, 'b'*64)
        config.copies['reinstall'] = self.retained
        config.paired_home = lambda: self.assertEqual(self.target, self.home.HOME.resolve(strict=True))
        (config.state / self.op).mkdir(mode=0o700, parents=True)
        secret = key.read_bytes()
        module = configure_tests.configure
        rename = module.rename_package_entry
        def interrupt(src, dst, flags):
            rename(src, dst, flags)
            if flags == 2:
                raise InterruptedError('after exchange')
        with patch.object(module, 'CORE_CONFIGURE_FACTORY_PACKAGES', manifest, create=True):
            with self.assertRaisesRegex(api.Refused, 'original removal Root'):
                config.restore_package_history(str(uuid.uuid4()), 'reinstall', secret)
            with patch.object(module, 'rename_package_entry', side_effect=interrupt), self.assertRaises(InterruptedError):
                config.restore_package_history(self.op, 'reinstall', secret)
            self.assertEqual('PRESERVED', config.restore_package_history(self.op, 'reinstall', secret))
        self.assertEqual(actual, (site.stat().st_ino, receipt.stat().st_ino))
        self.assertEqual(b'site registry', (site / 'dpa.properties').read_bytes())
        self.assertEqual(b'factory DP', (site / 'new.dp').read_bytes())
        with patch.object(module, 'rename_package_entry', side_effect=interrupt), self.assertRaises(InterruptedError):
            config.restore_runtime_data(self.op, 'reinstall', secret)
        with patch.object(module, 'rename_package_entry', side_effect=AssertionError('repeated exchange')):
            self.assertEqual('PRESERVED', config.restore_runtime_data(self.op, 'reinstall', secret))
        self.assertEqual(original_data.st_ino, data.stat().st_ino)
        self.assertEqual(original_provider, provider.stat())
        self.assertEqual(original_provider.st_ctime_ns, provider.stat().st_ctime_ns)
        self.assertEqual(b'retained provider record', provider.read_bytes())
        config.retire_removed_trees(self.op, self.retained, secret)
        config.retire_removed_trees(self.op, self.retained, secret)
        self.assertFalse(holder.exists())

    def published_generation(self):
        digest = lambda raw: hashlib.sha256(raw).hexdigest()
        journal = self.retained.parent / 'journal'
        journal.mkdir(mode=0o700)
        self.home.JOURNAL_KEY = journal / 'journal.key'
        self.home.write_new(self.home.JOURNAL_KEY, os.urandom(32))
        self.home.GENERATION_DROPIN = journal / 'dropin'
        self.home.write_new(self.home.GENERATION_DROPIN, b'fixture drop-in')
        self.home.GENERATION_DROPIN.chmod(0o400)
        manifest = self.target / 'libexec/key-backup/manifest.json'
        manifest.parent.mkdir(parents=True)
        self.home.write_new(manifest, b'{"generation":{}}')
        scripts = self.target / 'bin'
        scripts.mkdir()
        for name in self.home.GENERATION_LAUNCHERS:
            self.home.write_new(scripts / name, name.encode())
        binding = dict(schema=1, purpose='yofc-kura-key-generation-package-v1',
                       manifestSha256=digest(manifest.read_bytes()),
                       launcherSha256s={p.name:digest(p.read_bytes()) for p in scripts.iterdir()})
        pub = dict(operationId=str(uuid.uuid4()), cohortSha256=digest(json.dumps(
            binding, sort_keys=True, separators=(',', ':')).encode()))
        self.home.write_new(journal / 'generation-current.json', json.dumps(pub).encode())
        self.home.write_new(journal / 'maintenance.json', json.dumps(
            dict(id=self.op, state='MAINTENANCE', firstAction='remove')).encode())
        self.home.PURGED_GENERATIONS = self.retained.parent / 'purged-generations'
        self.home.capture_generation(self.target, self.retained, self.op)
        return pub

    def test_published_launchers_survive_staging_rename_and_require_original_receipt(self):
        pub = self.published_generation()
        published = self.retained.with_name('published')
        self.retained.rename(published)
        saved = self.home.retained_generation(published, self.op)
        self.assertEqual(pub['cohortSha256'], saved['cohortSha256'])
        with self.assertRaisesRegex(ValueError, 'another removal'):
            self.home.retained_generation(published, str(uuid.uuid4()))
        shutil.copytree(published, self.retained)
        with self.assertRaisesRegex(ValueError, 'another removal'):
            self.home.retained_generation(self.retained, self.op)
        (published / 'published-generation/start_kura.sh').write_bytes(b'different')
        with self.assertRaisesRegex(ValueError, 'original publication'):
            self.home.retained_generation(published, self.op)

    def test_purge_keeps_only_signed_original_cohort_and_requires_completion(self):
        pub = self.published_generation()
        original = {name: (self.target / 'bin' / name).read_bytes() for name in self.home.GENERATION_LAUNCHERS}
        self.home.capture_purged_generation(self.retained)
        self.home.capture_purged_generation(self.retained)
        with self.assertRaisesRegex(ValueError, 'Incomplete original'):
            self.home.purged_generation(self.op)
        with self.assertRaisesRegex(ValueError, 'still has application state'):
            self.home.complete_purged_generation(self.retained)
        shutil.rmtree(self.retained)
        self.home.HOME.unlink()
        shutil.rmtree(self.target)
        self.home.GENERATION_DROPIN.unlink()
        self.home.capture_purged_generation(self.retained)
        self.home.complete_purged_generation(self.retained)
        saved = self.home.PURGED_GENERATIONS / self.op
        before = {p.name: (p.stat().st_ino, p.read_bytes()) for p in saved.iterdir()}
        self.home.complete_purged_generation(self.retained)
        self.assertEqual(before, {p.name: (p.stat().st_ino, p.read_bytes()) for p in saved.iterdir()})
        self.assertEqual(pub['cohortSha256'], self.home.purged_generation(self.op)['cohortSha256'])
        self.assertEqual(original, {name: (saved / name).read_bytes() for name in original})
        self.assertEqual({*original, 'captured.json', 'completed.json', 'dropin'}, set(before))
        (saved / 'start_kura.sh').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'original publication'):
            self.home.purged_generation(self.op)

    def test_interrupted_cohort_capture_resumes_only_identical_files(self):
        self.published_generation()
        write = self.home.write_new
        def interrupt(path, raw):
            write(path, raw)
            if path.name == 'start_kura_background.sh':
                raise InterruptedError('between original launchers')
        with patch.object(self.home, 'write_new', side_effect=interrupt), self.assertRaises(InterruptedError):
            self.home.capture_purged_generation(self.retained)
        saved = self.home.PURGED_GENERATIONS / self.op
        previous = saved / 'start_kura_background.sh'
        raw = previous.read_bytes()
        inode = previous.stat().st_ino
        previous.write_bytes(b'other')
        with self.assertRaisesRegex(ValueError, 'partial purge cohort changed'):
            self.home.capture_purged_generation(self.retained)
        previous.write_bytes(raw)
        self.home.capture_purged_generation(self.retained)
        self.assertEqual(inode, previous.stat().st_ino)
        self.home.purged_generation(self.op, completed=False)

    def test_purge_cohort_rejects_changed_root_fence_signature_and_publication(self):
        self.published_generation()
        self.home.capture_purged_generation(self.retained)
        saved = self.home.PURGED_GENERATIONS / self.op
        with patch.object(self.home, 'ROOT', self.retained):
            with self.assertRaisesRegex(ValueError, 'another Root'):
                self.home.purged_generation(self.op, completed=False)
        fence = self.home.JOURNAL_KEY.parent / 'maintenance.json'
        raw = fence.read_bytes()
        fence.write_text(json.dumps(dict(id=str(uuid.uuid4()), state='MAINTENANCE', firstAction='remove')))
        with self.assertRaisesRegex(ValueError, 'original removal fence'):
            self.home.purged_generation(self.op, completed=False)
        fence.write_bytes(raw)
        receipt = saved / 'captured.json'
        raw = receipt.read_bytes()
        record = json.loads(raw)
        record['tag'] = '0' * 64
        receipt.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'another Root'):
            self.home.purged_generation(self.op, completed=False)
        receipt.write_bytes(raw)
        current = self.home.JOURNAL_KEY.parent / 'generation-current.json'
        record = json.loads(current.read_bytes())
        record['operationId'] = str(uuid.uuid4())
        current.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'original publication'):
            self.home.purged_generation(self.op, completed=False)

    def test_partial_retained_purge_resumes_after_both_inner_witnesses_are_gone(self):
        base = self.retained.parent
        self.home.JOURNAL_KEY = base / 'journal.key'
        self.home.write_new(self.home.JOURNAL_KEY, os.urandom(32))
        fence = base / 'maintenance.json'
        def select(operation):
            fence.write_text(json.dumps(dict(id=operation, state='MAINTENANCE', firstAction='remove')))
        select(self.op)
        self.home.capture(self.retained)
        self.home.remove(self.retained)
        inode = self.retained.stat().st_ino
        def interrupt(tree):
            (tree / 'systemd/main-state.json').unlink()
            (tree / 'removal-home.json').unlink()
            raise InterruptedError('after removing witnesses')
        with patch.object(shutil, 'rmtree', side_effect=interrupt), self.assertRaises(InterruptedError):
            self.home.purge_retained(self.retained)
        staged, = base.glob('.kura-retained.purging-*')
        self.assertEqual(inode, staged.stat().st_ino)
        select(str(uuid.uuid4()))
        with self.assertRaisesRegex(ValueError, 'Different original'):
            self.home.purge_retained(self.retained)
        select(self.op)
        moved = staged.rename(base / 'original')
        shutil.copytree(moved, staged)
        with self.assertRaisesRegex(ValueError, 'Different original'):
            self.home.purge_retained(self.retained)
        shutil.rmtree(staged)
        moved.rename(staged)
        self.retained.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, 'Conflicting retained'):
            self.home.purge_retained(self.retained)
        self.retained.rmdir()
        self.home.purge_retained(self.retained)
        self.assertFalse(staged.exists())
        self.assertEqual(self.op, json.loads(fence.read_bytes())['id'])

    def test_purge_checks_all_parked_identities_before_deleting(self):
        site = self.target / 'packages'
        site.mkdir()
        (site / ('.dpa.properties.uninstall-' + 'b' * 64 + '.done')).touch()
        data = self.target / 'data'
        data.mkdir()
        (data / 'store.save').write_bytes(b'original provider data')
        self.home.JOURNAL_KEY = self.home.PARENT.parent / 'journal.key'
        self.home.JOURNAL_KEY.write_bytes(os.urandom(32))
        self.home.JOURNAL_KEY.chmod(0o600)
        self.home.capture(self.retained)
        self.home.park(self.retained)
        self.home.remove(self.retained)
        holder = self.home.PARENT / self.home.package_record(self.retained)['holder']
        saved = holder / 'data'
        moved = saved.rename(holder / 'different-name')
        saved.mkdir()
        with self.assertRaisesRegex(ValueError, 'Different original directory'):
            self.home.purge_parked_trees(self.retained)
        self.assertTrue((holder / 'packages').is_dir())
        saved.rmdir()
        moved.rename(saved)
        self.home.purge_parked_trees(self.retained)
        self.home.purge_parked_trees(self.retained)
        self.assertFalse(holder.exists())

    def test_missing_legacy_registry_leaves_no_restore_input(self):
        self.registry.unlink()
        self.home.capture(self.retained)
        self.home.remove(self.retained)
        self.assertFalse((self.retained / 'framework').exists())

    def test_refuses_linked_registry_before_publishing_removal_record(self):
        self.registry.unlink()
        self.registry.symlink_to(self.target / 'missing')
        with self.assertRaisesRegex(ValueError, 'Unsafe removal record'):
            self.home.capture(self.retained)
        self.assertFalse((self.retained / 'removal-home.json').exists())
        self.assertEqual(self.target, self.home.HOME.resolve(strict=True))

    def test_replaced_public_link_preserves_both_directories(self):
        self.home.capture(self.retained)
        other = self.home.PARENT / 'kura_other'
        other.mkdir()
        self.home.HOME.unlink()
        self.home.HOME.symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'link was replaced'):
            self.home.remove(self.retained)
        self.assertTrue(self.target.is_dir())
        self.assertEqual(other, self.home.HOME.resolve(strict=True))

    def test_missing_public_link_does_not_admit_replacement_physical_directory(self):
        self.home.capture(self.retained)
        self.home.HOME.unlink()
        moved = self.target.rename(self.home.PARENT / 'previous')
        self.target.mkdir()
        with self.assertRaisesRegex(ValueError, 'directory was replaced'):
            self.home.remove(self.retained)
        self.assertTrue(self.target.is_dir())
        self.assertTrue(moved.is_dir())

    def test_refuses_changed_removal_witness(self):
        self.home.capture(self.retained)
        (self.target / ('.kura-remove-' + self.op)).write_text('changed')
        with self.assertRaisesRegex(ValueError, 'witness changed'):
            self.home.remove(self.retained)
        self.assertEqual(self.target, self.home.HOME.resolve(strict=True))

    def test_interrupted_cleanup_continues_only_at_the_original_private_name(self):
        self.home.capture(self.retained)
        self.home.HOME.unlink()
        (self.target / 'sample').write_text('fixture')
        with patch.object(self.home.shutil, 'rmtree', side_effect=OSError('interrupted')):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                self.home.remove(self.retained)
        retired = self.home.PARENT / ('.kura-removing-' + self.op)
        self.assertEqual('fixture', (retired / 'sample').read_text())
        self.target.mkdir()
        with self.assertRaisesRegex(ValueError, 'New Core installation'):
            self.home.remove(self.retained)
        self.target.rmdir()
        self.home.remove(self.retained)
        self.assertFalse(retired.exists())
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main()
