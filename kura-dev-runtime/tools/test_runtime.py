"""Protect persistent data and reject incomplete or already running runtimes."""
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import runtime


class RuntimeSafetyTest(unittest.TestCase):
    def test_initialization_never_replaces_existing_snapshot_or_key(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            values = {'KURA_HTTP_PORT': 18080, 'KURA_HTTPS_PORT': 18443, 'KURA_CLIENT_AUTH_PORT': 18444}
            runtime.initialize(home, values)
            snapshot = home / 'user/snapshots/snapshot_0.xml'
            text = snapshot.read_text()
            self.assertNotIn('@KURA_DEV_HOME@', text)
            self.assertNotIn('@KEYSTORE_PASSWORD@', text)
            self.assertIn('18443', text)
            self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
            snapshot.write_text('user modified snapshot')
            key = home / 'user/security/test.key'
            key.write_bytes(b'private user data')
            runtime.initialize(home, values)
            self.assertEqual(snapshot.read_text(), 'user modified snapshot')
            self.assertEqual(key.read_bytes(), b'private user data')

    def test_data_cannot_be_in_clean_output(self):
        with patch.dict(os.environ, {'KURA_DEV_HOME': str(runtime.ROOT / 'target/data')}):
            with self.assertRaisesRegex(ValueError, 'outside target'):
                runtime.data_home('macos')

    def test_busy_port_fails_with_exact_port(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(ValueError, str(port)):
                runtime.check_ports({'KURA_HTTP_PORT': port})

    def test_suspended_debugger_is_protected_even_without_http_port(self):
        output = f' 9876 /jdk/bin/java -agentlib:jdwp=suspend=y -jar {runtime.RUNTIME}/launcher.jar\n'
        with patch('runtime.subprocess.run', return_value=subprocess.CompletedProcess([], 0, output)):
            with self.assertRaisesRegex(ValueError, 'JVM 9876'):
                runtime.guard()

    def test_missing_nested_jar_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'broken.jar'
            with zipfile.ZipFile(path, 'w') as jar:
                jar.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\nBundle-ClassPath: .,\n lib/missing.jar\n')
            with self.assertRaisesRegex(ValueError, 'missing Bundle-ClassPath lib/missing.jar'):
                runtime.read_manifest(path)


class RuntimeDataTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / 'home'
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        runtime.initialize(self.home, runtime.ports())

    def test_existing_snapshot_ports_are_used_without_overwriting_data(self):
        seed = self.home / 'user/snapshots/snapshot_0.xml'
        original = seed.read_bytes()
        with patch.dict(os.environ, {'KURA_HTTP_PORT': '18080'}):
            values = runtime.ports(self.home)
            runtime.apply_port_overrides(self.home, values)
        self.assertEqual(18080, runtime.ports(self.home)['KURA_HTTP_PORT'])
        self.assertEqual(original, seed.read_bytes())
        runtime.initialize(self.home, runtime.ports())
        self.assertEqual(original, seed.read_bytes())
        self.assertEqual(2, len(list(seed.parent.glob('snapshot_*.xml'))))

    def test_port_override_preserves_cdata_and_malformed_snapshot(self):
        seed = self.home / 'user/snapshots/snapshot_0.xml'
        text = seed.read_text()
        # Add CDATA to a known value without depending on the root element name.
        text = text.replace('<esf:value>8080</esf:value>', '<esf:value><![CDATA[8080]]></esf:value>')
        seed.write_text(text)
        bad = seed.parent / 'snapshot_1.xml'
        bad.write_text('<malformed')
        with patch.dict(os.environ, {'KURA_HTTPS_PORT': '18443'}):
            runtime.apply_port_overrides(self.home, runtime.ports(self.home))
        self.assertEqual('<malformed', bad.read_text())
        self.assertIn('<![CDATA[8080]]>', (seed.parent / 'snapshot_2.xml').read_text())

    def test_explicit_import_relocates_paths_and_leaves_source_unchanged(self):
        destination = self.home.parent / 'imported'
        secret = self.home / 'user/security/test.ks'
        secret.write_bytes(b'test-keystore')
        (self.home / 'data/example.db').write_bytes(b'test-db')
        before = (self.home / 'user/snapshots/snapshot_0.xml').read_bytes()
        with patch.dict(os.environ, {'KURA_DEV_HOME': str(destination)}), patch.object(runtime, 'guard'):
            runtime.import_data('macos', self.home)
            with self.assertRaisesRegex(ValueError, 'empty KURA_DEV_HOME'):
                runtime.import_data('macos', self.home)
        self.assertEqual(before, (self.home / 'user/snapshots/snapshot_0.xml').read_bytes())
        self.assertEqual(b'test-keystore', (destination / 'user/security/test.ks').read_bytes())
        self.assertEqual(b'test-db', (destination / 'data/example.db').read_bytes())
        self.assertTrue(str(destination.resolve()) in (destination / 'user/snapshots/snapshot_0.xml').read_text())
        self.assertFalse((destination / 'configuration').exists())

    def test_eclipse_layout_imports_snapshots_keystores_and_camel_scripts(self):
        (self.home / 'user/snapshots').rename(self.home / 'snapshots')
        scripts = self.home / 'camel/scripts'
        scripts.mkdir(parents=True)
        script = scripts / 'init.groovy'
        script.write_text(f'new File("{self.home}/camel/routes/example.xml")')
        key = self.home / 'user/security/https.ks'
        key.write_bytes(b'private-key-store')
        source_files = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        destination = self.home.parent / 'imported'
        with patch.dict(os.environ, {'KURA_DEV_HOME': str(destination)}), patch.object(runtime, 'guard'):
            runtime.import_data('macos', self.home)
        self.assertEqual(source_files, {p.relative_to(self.home): p.read_bytes()
                                      for p in self.home.rglob('*') if p.is_file()})
        self.assertIsNotNone(runtime.snapshot(destination)[1])
        self.assertIn(str(destination), (destination / 'camel/scripts/init.groovy').read_text())
        self.assertNotIn(str(self.home), (destination / 'camel/scripts/init.groovy').read_text())
        self.assertEqual(b'private-key-store', (destination / 'user/security/https.ks').read_bytes())
        self.assertEqual(0o600, (destination / 'user/security/https.ks').stat().st_mode & 0o777)

    def test_import_rejects_ambiguous_snapshot_layout_and_linked_scripts(self):
        destination = self.home.parent / 'imported'
        (self.home / 'snapshots').mkdir()
        with patch.dict(os.environ, {'KURA_DEV_HOME': str(destination)}), patch.object(runtime, 'guard'):
            with self.assertRaisesRegex(ValueError, 'exactly one snapshot directory'):
                runtime.import_data('macos', self.home)
            (self.home / 'snapshots').rmdir()
            (self.home / 'camel').mkdir()
            (self.home / 'camel/external').symlink_to(self.home / 'user/security', target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                runtime.import_data('macos', self.home)
        self.assertFalse(destination.exists())



if __name__ == '__main__':
    unittest.main()
