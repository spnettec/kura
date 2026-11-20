# SPDX-License-Identifier: EPL-2.0
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_key_service_lifecycle as fixtures


module = Path(__file__).resolve().parents[2] / 'kura-core/preinst-upgrade-copy.py'
spec = importlib.util.spec_from_file_location('preinst_upgrade_copy', module)
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


class UpgradeCopyTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LifecycleTest('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.policy = self.fixture.policy
        self.fence = self.policy.enter('upgrade')
        self.control = self.policy.path('/var/lib/dpkg/tmp.ci/preinst')
        self.fixture.write(self.control, b'incoming preinst', 0o750)
        self.copy = self.controller()
        self.original = self.fixture.physical / 'user/snapshots/snapshot_1.xml'
        self.fixture.write(self.original, b'original retained data')

    def controller(self, successor='6.0.0-2'):
        return upgrade.UpgradeCopy(fixtures.lifecycle, self.policy, self.control, '6.0.0-1', successor)

    def test_retries_only_the_authenticated_unpublished_copy_from_the_intact_source(self):
        partial = self.copy.prepare()
        self.fixture.write(partial / 'user/snapshots/snapshot_1.xml', b'original')
        self.assertFalse(self.copy.destination.exists())
        self.assertEqual(b'original retained data', self.original.read_bytes())
        self.assertEqual(self.fence, self.policy.fence())
        with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'another source, package or Root'):
            self.controller('6.0.0-3').prepare()
        self.assertTrue(partial.exists())
        again = self.controller().prepare()
        self.assertNotEqual(partial, again)
        self.assertFalse(partial.exists())
        self.assertFalse(self.copy.destination.exists())
        self.assertEqual(b'original retained data', self.original.read_bytes())
        self.assertEqual(self.fence, self.policy.fence())

    def test_existing_historical_copy_blocks_even_with_an_original_fence(self):
        self.fixture.write(self.copy.destination / 'data', b'historical')
        with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'Existing recovery copy'):
            self.copy.prepare()
        self.assertEqual(b'historical', (self.copy.destination / 'data').read_bytes())

    @unittest.skipUnless(sys.platform == 'linux', 'Linux package uses atomic no-replace rename')
    def test_sync_failure_leaves_the_original_unpublished_copy_and_never_replaces_a_destination(self):
        stage = self.copy.prepare()
        payload = stage / 'user/snapshots/snapshot_1.xml'
        self.fixture.write(payload, self.original.read_bytes())
        before = stage.stat().st_ino
        with patch.object(upgrade.os, 'sync', side_effect=InterruptedError), self.assertRaises(InterruptedError):
            self.copy.publish(stage)
        self.assertFalse(self.copy.destination.exists())
        self.assertEqual(b'original retained data', payload.read_bytes())
        with patch.object(upgrade.os, 'sync'):
            self.copy.publish(stage)
        self.assertEqual(before, self.copy.destination.stat().st_ino)
        self.assertEqual(b'original retained data', (self.copy.destination / payload.relative_to(stage)).read_bytes())
        self.assertEqual(b'original retained data', self.original.read_bytes())
        with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'Existing recovery copy'):
            self.copy.prepare()
