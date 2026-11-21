# SPDX-License-Identifier: EPL-2.0
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_ownership_markers as markers


class OwnershipMarkersTest(unittest.TestCase):
    def test_request_has_two_fixed_names(self):
        self.assertEqual(set(markers.MARKERS), {b'N', b'F'})
        with self.assertRaises(markers.Refused):
            markers.observe(b'')

    @unittest.skipUnless(os.geteuid() == 0, 'requires a root-owned directory')
    def test_directory_entries_are_observed_afresh_without_opening_them(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(markers.observe(b'N', folder), b'0')
            entry = folder / 'network-owner-agent'
            entry.symlink_to('absent')
            self.assertEqual(markers.observe(b'N', folder), b'1')
            self.assertEqual(markers.observe(b'F', folder), b'0')
            entry.unlink()
            self.assertEqual(markers.observe(b'N', folder), b'0')
            (folder / 'firewall-owner-agent').mkdir()
            self.assertEqual(markers.observe(b'F', folder), b'1')
            with self.assertRaises(FileNotFoundError):
                markers.observe(b'N', folder / 'missing')


if __name__ == '__main__':
    unittest.main()
