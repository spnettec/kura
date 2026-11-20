# SPDX-License-Identifier: EPL-2.0
import hashlib
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
        self.boot = self.policy.path('/proc/sys/kernel/random/boot_id')
        self.fixture.write(self.boot, b'196840f8-e95f-41ce-8507-312ffe0400b9\n')
        self.copy = self.controller()
        self.original = self.fixture.physical / 'user/snapshots/snapshot_1.xml'
        self.fixture.write(self.original, b'original retained data')

    def controller(self, successor='6.0.0-2'):
        payload = b'incoming package body'
        return upgrade.UpgradeCopy(fixtures.lifecycle, self.policy, self.control, '6.0.0-1', successor,
                                   dict(home=self.fixture.physical.name, directories=['install'],
                                        files={'install/payload': (len(payload), hashlib.sha256(payload).hexdigest())}))

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
        with self.assertRaises(FileNotFoundError):
            self.copy.arrange_source(restore=True)
        self.assertEqual(b'historical', (self.copy.destination / 'data').read_bytes())

    @unittest.skipUnless(sys.platform == 'linux', 'Linux package uses atomic no-replace rename')
    def test_published_copy_reattaches_the_exact_old_tree_only_on_the_original_boot(self):
        staged = self.copy.prepare()
        for name in ('kura_encryption_key', 'provisioned.json'):
            credential = self.policy.path('/etc/kura/credentials') / name
            self.fixture.write(staged / 'encryption' / name, credential.read_bytes())
        with patch.object(upgrade.os, 'sync'):
            self.copy.publish(staged)
        old = self.original.lstat()
        with patch.object(self.policy, 'command', return_value='ActiveState=inactive\nMainPID=0\nControlPID=0\n'):
            self.copy.arrange_source(restore=False)
            parked = self.copy.destination / '.old-home'
            self.assertFalse(self.original.exists())
            self.assertEqual(old.st_ino, (parked / self.original.relative_to(self.fixture.physical)).stat().st_ino)
            with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'source, package, boot or Root'):
                self.controller('6.0.0-3').arrange_source(restore=True)
            original_boot = self.boot.read_bytes()
            self.fixture.write(self.boot, b'4aa07f18-4fd4-46a0-9233-a680c8cbc65f\n')
            with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'source, package, boot or Root'):
                self.copy.arrange_source(restore=True)
            self.fixture.write(self.boot, original_boot)
            self.fixture.physical.mkdir(mode=0o750)
            with patch.object(upgrade.UpgradeCopy, 'dpkg_payload_state'), self.assertRaisesRegex(
                    fixtures.lifecycle.Refused, 'Interrupted dpkg payload has no incoming file evidence'):
                self.copy.arrange_source(restore=True)
            self.fixture.physical.rmdir()
            self.copy.arrange_source(restore=True)
        self.assertEqual(old.st_ino, self.original.stat().st_ino)
        self.assertEqual(b'original retained data', self.original.read_bytes())
        self.assertFalse(parked.exists())
        self.assertTrue((self.copy.destination / '.capture.json').exists())
        self.assertEqual(self.fence, self.policy.fence())

    @unittest.skipUnless(sys.platform == 'linux', 'Linux package uses atomic no-replace rename')
    def test_partial_payload_is_held_across_old_source_checks_and_returned_without_replacement(self):
        stage = self.copy.prepare()
        for name in ('kura_encryption_key', 'provisioned.json'):
            credential = self.policy.path('/etc/kura/credentials') / name
            self.fixture.write(stage / 'encryption' / name, credential.read_bytes())
        with patch.object(upgrade.os, 'sync'):
            self.copy.publish(stage)
        old_inode = self.original.stat().st_ino
        with patch.object(self.policy, 'command', return_value='ActiveState=inactive\nMainPID=0\nControlPID=0\n'), +                patch.object(upgrade.UpgradeCopy, 'dpkg_payload_state'):
            self.copy.arrange_source(restore=False)
            incoming = self.fixture.physical / 'install/payload.dpkg-new'
            self.fixture.write(incoming, b'incoming pack')
            self.fixture.write(incoming.with_name('payload'), b'incoming package body')
            intruder = incoming.with_name('site-file')
            self.fixture.write(intruder, b'preserve')
            with self.assertRaisesRegex(fixtures.lifecycle.Refused, 'Unexpected file'):
                self.copy.arrange_source(restore=True)
            self.assertEqual(b'preserve', intruder.read_bytes())
            self.assertTrue(incoming.exists())
            intruder.unlink()
            partial_inode = incoming.stat().st_ino
            self.copy.arrange_source(restore=True)
            self.copy.arrange_source(restore=True)
            self.assertEqual(old_inode, self.original.stat().st_ino)
            self.assertFalse(incoming.exists())
            held = self.copy.destination / '.partial-payload/install/payload.dpkg-new'
            self.assertEqual(partial_inode, held.stat().st_ino)
            self.copy.arrange_source(restore=False)
            self.assertEqual(partial_inode, incoming.stat().st_ino)
            self.assertEqual(b'incoming pack', incoming.read_bytes())
            self.assertFalse(held.exists())
            self.assertFalse(self.original.exists())
            self.assertEqual(self.fence, self.policy.fence())

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
