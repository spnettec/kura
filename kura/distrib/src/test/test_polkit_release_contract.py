"""Check installer rejection before user/filesystem mutation using real dpkg comparison."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/install/manage_kura_users.sh'


@unittest.skipUnless(shutil.which('dpkg'), 'Requires native dpkg; run in the Linux release fixture')
class PolkitReleaseContractTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.mutations = self.root / 'mutation-attempts'
        # These commands must never run for either preflight or rejected install.
        for name in ['useradd', 'userdel', 'passwd', 'gpasswd', 'sed', 'chown', 'chmod',
                     'mkdir', 'cp', 'mv', 'rm', 'awk', 'systemctl']:
            self.command(name, '#!/bin/sh\nprintf "%s\\n" ' + shlex.quote(name) +
                         ' >> ' + shlex.quote(str(self.mutations)) + '\nexit 97\n')

    def command(self, name, source):
        path = self.bin / name
        path.write_text(source)
        path.chmod(0o755)

    def check(self, record, exit_code=0, option='--check-polkit'):
        self.command('dpkg-query', '#!/bin/sh\nprintf "%s" ' + shlex.quote(record) +
                     '\nexit ' + str(exit_code) + '\n')
        result = subprocess.run(['bash', str(SCRIPT), option], capture_output=True, text=True,
                                env=dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH']), timeout=10)
        self.assertFalse(self.mutations.exists(), self.mutations.read_text() if self.mutations.exists() else '')
        return result

    def test_current_release_daemon_passes_without_mutations(self):
        self.assertEqual(self.check('installed 124-2ubuntu1.24.04.4').returncode, 0)

    def test_backend_boundary_passes_without_mutations(self):
        self.assertEqual(self.check('installed 0.106-1').returncode, 0)

    def test_supported_epoch_does_not_break_preflight(self):
        self.assertEqual(self.check('installed 1:124-1').returncode, 0)

    def test_legacy_backend_is_rejected_without_mutations(self):
        self.assertNotEqual(self.check('installed 0.105-33').returncode, 0)

    def test_epoch_cannot_disguise_legacy_backend(self):
        self.assertNotEqual(self.check('installed 1:0.105-33').returncode, 0)

    def test_missing_daemon_is_rejected_without_mutations(self):
        self.assertNotEqual(self.check('', exit_code=1).returncode, 0)

    def test_unconfigured_daemon_is_rejected_without_mutations(self):
        self.assertNotEqual(self.check('unpacked 124-1').returncode, 0)

    def test_malformed_version_is_rejected_without_mutations(self):
        self.assertNotEqual(self.check('installed not/a/version').returncode, 0)

    def test_normal_install_rejects_legacy_before_creating_users(self):
        self.assertNotEqual(self.check('installed 0.105-33', option='-i').returncode, 0)


if __name__ == '__main__':
    unittest.main()
