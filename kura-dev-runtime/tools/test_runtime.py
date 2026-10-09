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


if __name__ == '__main__':
    unittest.main()
