#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_snapshot_inventory as reader


class SnapshotInventoryTest(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.root = Path(home.name)

    def write(self, name, data):
        file = self.root / name
        file.write_bytes(data)
        file.chmod(0o600)
        return file

    def inspect(self):
        return reader.inventory(self.root, os.geteuid(), os.getegid())

    def test_fingerprints_active_and_quarantined_files_without_opening_retained_tree(self):
        self.write('snapshot_2.xml', b'private sample')
        self.write('snapshot_1.xml.bad', b'quarantine')
        retained = self.root / '.recovery-retained'
        retained.mkdir(mode=0o700)
        (retained / 'not-inspected').symlink_to('/unrelated')
        result = self.inspect()
        self.assertEqual([row['name'] for row in result['files']], ['snapshot_1.xml.bad', 'snapshot_2.xml'])
        self.assertEqual(result['files'][1]['sha256'], hashlib.sha256(b'private sample').hexdigest())
        self.assertEqual(result['files'][1]['metadata']['mode'], 0o600)
        self.assertTrue(result['retainedDirectoryPresent'])
        self.assertNotIn('private sample', repr(result))

    def test_rejects_symlink_hardlink_and_nonprivate_entry(self):
        held = self.write('snapshot_0.xml', b'original')
        alias = self.root / 'snapshot_1.xml'
        alias.symlink_to(held)
        with self.assertRaises(ValueError):
            self.inspect()
        alias.unlink()
        os.link(held, alias)
        with self.assertRaises(ValueError):
            self.inspect()
        alias.unlink()
        held.chmod(0o640)
        with self.assertRaises(ValueError):
            self.inspect()

    def test_rejects_an_observation_when_file_changes_during_inventory(self):
        item = self.write('snapshot_0.xml', b'original')
        scan = reader.entries
        count = 0

        def changed(fd):
            nonlocal count
            count += 1
            if count == 2:
                item.write_bytes(b'changed concurrently')
            return scan(fd)

        with patch.object(reader, 'entries', side_effect=changed), self.assertRaises(ValueError):
            self.inspect()


if __name__ == '__main__':
    unittest.main()
