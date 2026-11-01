import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from lifecycle import Lifecycle
from stage import deduplicate_plugins

MODULE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('launcher', MODULE / 'resources/launch-netplan.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.life = Lifecycle(self.root, lambda args, **kw: self.calls.append(args))
        self.home = self.make_dir('/opt/eclipse/kura/framework')
        (self.home / 'netplan-profile.json').write_text('{"profile":"netplan"}')
        defaults = self.make_dir('/usr/share/kura-netplan/defaults/user/snapshots')
        self.make_dir('/usr/share/kura-netplan/defaults/user/security')
        source = MODULE.parent / 'src/main/resources/unfiltered/pkg/user/snapshots/snapshot_0.xml'
        (defaults / 'snapshot_0.xml').write_bytes(source.read_bytes())

    def make_dir(self, name):
        path = self.life.path(name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def initialize(self):
        self.life.initialize(os.getuid(), os.getgid())

    def test_fresh_secrets_and_private_snapshot(self):
        self.initialize()
        key = self.life.path('/etc/kura-netplan/crypto.key')
        self.assertEqual(32, len(key.read_bytes()))
        password = self.life.path('/etc/kura-netplan/bootstrap-admin')
        self.assertGreaterEqual(len(password.read_text()), 24)
        self.assertEqual(0o600, password.stat().st_mode & 0o777)
        seed = self.life.path('/var/lib/kura-netplan/user/snapshots/snapshot_0.xml')
        self.assertNotIn('>old<', seed.read_text())
        self.assertNotIn(password.read_text(), seed.read_text())
        self.assertEqual(0o600, seed.stat().st_mode & 0o777)
        from xml.dom import minidom
        self.assertEqual(15, len(minidom.parse(str(seed)).getElementsByTagName('esf:configuration')))
        self.assertTrue(all(args[0] == '/usr/bin/keytool' for args in self.calls))

    def test_upgrade_and_reinstall_preserve_all_state(self):
        self.initialize()
        snapshot = self.life.path('/var/lib/kura-netplan/user/snapshots/snapshot_9.xml')
        snapshot.write_text('user modified encrypted snapshot')
        before = {p: p.read_bytes() for base in ['/etc/kura-netplan', '/var/lib/kura-netplan']
                  for p in self.life.path(base).rglob('*') if p.is_file()}
        self.life.dispatch('preinst', 'upgrade')
        self.initialize()
        self.life.dispatch('postrm', 'remove')
        self.life.dispatch('preinst', 'install')
        self.initialize()
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_missing_key_does_not_reseed(self):
        self.initialize()
        self.life.path('/etc/kura-netplan/crypto.key').unlink()
        with self.assertRaisesRegex(RuntimeError, 'original crypto key'):
            self.initialize()
        self.assertFalse(self.life.path('/etc/kura-netplan/crypto.key').exists())

    def test_interrupted_initialization_is_not_overwritten(self):
        state = self.make_dir('/var/lib/kura-netplan')
        (state / '.initializing').write_text('interrupted')
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            self.initialize()
        self.assertEqual('interrupted', (state / '.initializing').read_text())

    def test_legacy_directory_refused(self):
        (self.home / 'netplan-profile.json').unlink()
        with self.assertRaisesRegex(RuntimeError, 'explicit migration'):
            self.life.preflight()

    def test_legacy_retained_data_refused(self):
        self.make_dir('/var/lib/kura-retained')
        with self.assertRaisesRegex(RuntimeError, 'Legacy Kura state'):
            self.life.preflight()

    def test_symlink_root_refused(self):
        other = self.make_dir('/outside')
        self.make_dir('/var/lib')
        self.life.path('/var/lib/kura-netplan').symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            self.initialize()

    def test_purge_has_fixed_scope(self):
        self.initialize()
        sentinels = []
        for name in ['/etc/netplan', '/etc/systemd/network', '/var/lib/kura-management-agent', '/home/user']:
            path = self.make_dir(name) / 'keep'
            path.write_text('untouched')
            sentinels.append(path)
        # Nested symlinks must be unlinked, never traversed.
        self.life.path('/var/lib/kura-netplan/external').symlink_to(sentinels[-1].parent)
        self.life.purge()
        self.assertTrue(all(p.read_text() == 'untouched' for p in sentinels))
        self.assertFalse(self.life.path('/var/lib/kura-netplan').exists())

    def test_purge_rejects_symlink_before_deleting_anything(self):
        self.initialize()
        self.life.path('/var/log').mkdir(parents=True)
        self.life.path('/var/log/kura-netplan').symlink_to(self.make_dir('/outside'))
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            self.life.purge()
        self.assertTrue(self.life.path('/etc/kura-netplan/crypto.key').exists())

    def test_lifecycle_only_controls_own_unit(self):
        self.make_dir('/run/systemd/system')
        self.life.dispatch('prerm', 'upgrade')
        self.life.dispatch('postrm', 'upgrade')
        self.assertEqual([['/bin/systemctl', 'stop', 'kura-netplan.service']], self.calls)


class WriterTest(unittest.TestCase):
    def test_factory_snapshot_retains_kura_required_esf_prefix(self):
        import xml.etree.ElementTree as ET
        from xml.dom import minidom
        source = MODULE.parent / 'src/main/resources/unfiltered/pkg/user/snapshots/snapshot_0.xml'
        encoded = ET.tostring(ET.parse(source).getroot(), encoding='utf-8')
        document = minidom.parseString(encoded)
        # The current Java mapper uses getElementsByTagName("esf:configuration").
        self.assertGreater(len(document.getElementsByTagName('esf:configuration')), 0)

    def test_build_deduplicates_only_byte_identical_jars(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            plugin = home / 'plugins/3'
            plugin.mkdir(parents=True)
            jar = plugin / 'first.jar'
            with zipfile.ZipFile(jar, 'w') as archive:
                archive.writestr('META-INF/MANIFEST.MF', 'Bundle-SymbolicName: example\n\n')
            import shutil
            shutil.copy2(jar, plugin / 'second.jar')
            deduplicate_plugins(home, launcher)
            self.assertEqual(1, len(list(plugin.glob('*.jar'))))
            with zipfile.ZipFile(plugin / 'different.jar', 'w') as archive:
                archive.writestr('META-INF/MANIFEST.MF', 'Bundle-SymbolicName: example\nDifferent: true\n\n')
            with self.assertRaisesRegex(ValueError, 'Different payloads'):
                deduplicate_plugins(home, launcher)

    def test_runtime_rejects_writer_and_duplicate_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            plugin = home / 'plugins/5s'
            plugin.mkdir(parents=True)
            for name in ['org.eclipse.kura.nm', 'org.eclipse.kura.netplan']:
                jar = plugin / 'test.jar'
                with zipfile.ZipFile(jar, 'w') as archive:
                    archive.writestr('META-INF/MANIFEST.MF', 'Bundle-SymbolicName: ' + name + '\n\n')
                if name == 'org.eclipse.kura.nm':
                    with self.assertRaisesRegex(ValueError, 'Conflicting network writer'):
                        launcher.check_bundles(home)
                else:
                    import shutil
                    shutil.copy2(jar, plugin / 'duplicate.jar')
                    with self.assertRaisesRegex(ValueError, 'duplicate bundle'):
                        launcher.check_bundles(home)


if __name__ == '__main__':
    unittest.main()
