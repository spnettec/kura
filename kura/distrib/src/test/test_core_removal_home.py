# SPDX-License-Identifier: EPL-2.0
"""Run against a private directory on Linux. No live installation is used."""
import importlib.util
import json
import os
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
        self.home.capture(self.retained)

    def test_replaced_public_link_preserves_both_directories(self):
        other = self.home.PARENT / 'kura_other'
        other.mkdir()
        self.home.HOME.unlink()
        self.home.HOME.symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'link was replaced'):
            self.home.remove(self.retained)
        self.assertTrue(self.target.is_dir())
        self.assertEqual(other, self.home.HOME.resolve(strict=True))

    def test_missing_public_link_does_not_admit_replacement_physical_directory(self):
        self.home.HOME.unlink()
        moved = self.target.rename(self.home.PARENT / 'previous')
        self.target.mkdir()
        with self.assertRaisesRegex(ValueError, 'directory was replaced'):
            self.home.remove(self.retained)
        self.assertTrue(self.target.is_dir())
        self.assertTrue(moved.is_dir())

    def test_refuses_changed_removal_witness(self):
        (self.target / ('.kura-remove-' + self.op)).write_text('changed')
        with self.assertRaisesRegex(ValueError, 'witness changed'):
            self.home.remove(self.retained)
        self.assertEqual(self.target, self.home.HOME.resolve(strict=True))

    def test_interrupted_cleanup_continues_only_at_the_original_private_name(self):
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
