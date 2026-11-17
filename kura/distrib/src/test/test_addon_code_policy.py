#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Root filesystem regression cases, only in a fresh disposable Linux container."""
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'kura-core'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SOURCE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = load('addon_code_policy', 'addon-code-policy.py')


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0 and Path('/.dockerenv').exists(),
                     'Requires a new disposable Linux/Root filesystem')
class AddonCodePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for path in ('/opt/eclipse', '/etc/kura', '/var/lib/kura-key-service'):
            assert not os.path.lexists(path), 'Never adopt an installed gateway'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='addon-code-policy-', dir='/run')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'original/libexec/addons'
        self.file = self.source / 'cloud/install.sh'
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b'#!/bin/sh\n# immutable test code, no key or data\nexit 0\n')
        self.file.chmod(0o640)
        os.chown(self.file, 0, 65534)
        self.backup = self.root / 'retained/libexec/addons'
        self.destination = self.root / 'new/libexec/addons'

    def test_round_trip_keeps_root_code_permissions_groups_and_bytes(self):
        before = policy.fingerprint(self.source)
        policy.transfer('preserve', self.source, self.backup)
        self.assertEqual(before, policy.fingerprint(self.backup))
        policy.transfer('restore', self.backup, self.destination)
        self.assertEqual(before, policy.fingerprint(self.destination))
        self.assertEqual(before, policy.fingerprint(self.source))

    def test_newly_unpacked_addon_wins_without_resurrecting_deleted_callbacks(self):
        policy.transfer('preserve', self.source, self.backup)
        current = self.destination / 'cloud/new-only.sh'
        current.parent.mkdir(parents=True)
        current.write_text('new package source\n')
        current.chmod(0o644)
        before = policy.fingerprint(self.destination)
        policy.transfer('restore', self.backup, self.destination)
        self.assertEqual(before, policy.fingerprint(self.destination))
        self.assertFalse((current.parent / 'install.sh').exists())

    def test_existing_recovery_copy_is_never_replaced(self):
        policy.transfer('preserve', self.source, self.backup)
        before = policy.fingerprint(self.backup)
        self.file.write_text('different installed source\n')
        with self.assertRaises(RuntimeError):
            policy.transfer('preserve', self.source, self.backup)
        self.assertEqual(before, policy.fingerprint(self.backup))

    def test_writable_or_non_root_code_refuses_before_publication(self):
        for owner, mode in ((0, 0o664), (65534, 0o644)):
            with self.subTest(owner=owner, mode=mode):
                os.chown(self.file, owner, 65534)
                self.file.chmod(mode)
                with self.assertRaises(RuntimeError):
                    policy.transfer('preserve', self.source, self.backup)
                self.assertFalse(self.backup.exists())

    def test_symlink_hardlink_fifo_and_unsafe_parent_are_refused(self):
        outside = self.root / 'personal.data'
        outside.write_bytes(b'retained opaque original\x00')
        before = outside.read_bytes()
        self.file.unlink()
        self.file.symlink_to(outside)
        with self.assertRaises(RuntimeError):
            policy.transfer('preserve', self.source, self.backup)
        self.file.unlink()
        os.link(outside, self.file)
        with self.assertRaises(RuntimeError):
            policy.transfer('preserve', self.source, self.backup)
        self.file.unlink()
        os.mkfifo(self.file)
        with self.assertRaises(RuntimeError):
            policy.transfer('preserve', self.source, self.backup)
        self.file.unlink()
        self.file.write_text('code\n')
        self.source.parent.chmod(0o777)
        with self.assertRaises(RuntimeError):
            policy.transfer('preserve', self.source, self.backup)
        self.assertEqual(before, outside.read_bytes())
        self.assertFalse(self.backup.exists())

    def test_failed_copy_never_exposes_partial_addon_or_changes_source(self):
        before = policy.fingerprint(self.source)
        with patch.object(policy.shutil, 'copytree', side_effect=OSError('declared copy failure')):
            with self.assertRaises(OSError):
                policy.transfer('preserve', self.source, self.backup)
        self.assertEqual(before, policy.fingerprint(self.source))
        self.assertFalse(self.backup.exists())
        self.assertEqual([], list(self.backup.parent.glob('.addon-code-copy-*')))

    def test_unsafe_destination_does_not_follow_a_link_into_personal_files(self):
        policy.transfer('preserve', self.source, self.backup)
        personal = self.root / 'personal'
        personal.mkdir()
        (personal / 'unchanged').write_text('personal\n')
        self.destination.parent.mkdir(parents=True)
        self.destination.symlink_to(personal, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            policy.transfer('restore', self.backup, self.destination)
        self.assertEqual(['unchanged'], [path.name for path in personal.iterdir()])

    def test_cli_refuses_non_lifecycle_paths_and_embedded_source_is_exact(self):
        with self.assertRaises(RuntimeError):
            policy.main(['preserve', str(self.source), str(self.backup)])
        builder = load('addon_policy_builder', 'prepare-key-service.py')
        token = 'raise RuntimeError("Kura addon-code policy was not embedded")'
        path = self.root / 'control'
        path.write_text(token)
        builder.embed_addon_code_policy(path, SOURCE / 'addon-code-policy.py')
        self.assertEqual((SOURCE / 'addon-code-policy.py').read_text(), path.read_text())
        for content in ('', token + '\n' + token):
            path.write_text(content)
            with self.assertRaises(RuntimeError):
                builder.embed_addon_code_policy(path, SOURCE / 'addon-code-policy.py')


if __name__ == '__main__':
    unittest.main(verbosity=2)
