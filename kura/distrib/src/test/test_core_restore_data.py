#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Preserved .data is data, including script-shaped history; code lives elsewhere."""
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'main/resources/variants/linux/unfiltered/deb/control/postinst'


class CoreRestoreDataTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name); self.home = self.root / 'opt/kura'; self.data = self.home / '.data'
        self.data.mkdir(parents=True); (self.home / 'user/snapshots').mkdir(parents=True)
        self.saved = self.root / 'preserved'; (self.saved / 'addon-data').mkdir(parents=True)
        self.calls = self.root / 'chown-called'; self.stub = self.root / 'bin'; self.stub.mkdir()
        tool = self.stub / 'chown'; tool.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\nexit 47\n'); tool.chmod(0o700)

    def invoke(self):
        text = SOURCE.read_text()
        start = text.index('        # .data contains preserved runtime state')
        end = text.index('        manageAddonCode restore ', start)
        second = text.index('        # Keep an existing recovery copy,', end)
        tail = text.index('        if [ "${RESTORE_OK}" = "1" ]; then', second)
        script = 'RESTORE_OK=1\n' + text[start:end] + text[second:tail] + '\n[ "$RESTORE_OK" = 1 ]\n'
        env = dict(os.environ, INSTALL_DIR=str(self.root / 'opt'), PRESERVE_DIR=str(self.saved),
                   LOG=str(self.root / 'restore.log'), WAS_REINSTALL='0', CALLS=str(self.calls),
                   PATH=str(self.stub) + ':/usr/bin:/bin')
        return subprocess.run(['/bin/sh', '-c', script],env=env,capture_output=True,text=True)

    @staticmethod
    def logical(path):
        m = path.stat()
        return path.read_bytes(), m.st_uid, m.st_gid, stat.S_IMODE(m.st_mode), m.st_mtime_ns

    def test_historical_snapshot_and_script_shaped_data_override_fresh_defaults(self):
        snapshots = self.home / 'user/snapshots/snapshot_0.xml'; snapshots.write_bytes(b'authoritative current snapshot\n')
        names = ['snapshot_0.xml', 'manage_kura_users.sh', 'unrecognized-runtime-state']
        original = {}
        for name in names:
            path = self.saved / 'addon-data' / name; path.write_bytes(('original historical ' + name + '\n').encode()); path.chmod(0o600)
            original[name] = self.logical(path); (self.data / name).write_bytes(b'new factory value must not win\n')
        code = self.home / 'libexec/addons/example/manage.sh'; code.parent.mkdir(parents=True); code.write_bytes(b'new trusted code\n')
        result = self.invoke(); self.assertEqual(0,result.returncode,result.stderr)
        for name in names: self.assertEqual(original[name], self.logical(self.data / name))
        self.assertEqual(b'authoritative current snapshot\n', snapshots.read_bytes())
        self.assertEqual(b'new trusted code\n', code.read_bytes())

    def test_missing_recovery_copy_is_filled_from_restored_snapshot_with_metadata(self):
        source = self.home / 'user/snapshots/snapshot_0.xml'; source.write_bytes(b'only current snapshot\n'); source.chmod(0o640)
        before = self.logical(source); result = self.invoke()
        self.assertEqual(0,result.returncode,result.stderr); self.assertEqual(before, self.logical(self.data / 'snapshot_0.xml'))

    def test_existing_recovery_data_link_is_preserved_without_following_it(self):
        (self.home / 'user/snapshots/snapshot_0.xml').write_bytes(b'current\n')
        outside = self.root / 'outside-data'; outside.write_bytes(b'keep original target\n')
        link = self.data / 'snapshot_0.xml'; link.symlink_to(outside); inode = link.lstat().st_ino
        result = self.invoke(); self.assertEqual(0,result.returncode,result.stderr)
        self.assertTrue(link.is_symlink()); self.assertEqual(inode,link.lstat().st_ino)
        self.assertEqual(b'keep original target\n',outside.read_bytes())

    def test_restore_failure_keeps_preserved_input_and_fails(self):
        old = self.saved / 'addon-data/history'; old.write_bytes(b'recovery remains available\n')
        self.data.rmdir(); self.data.write_bytes(b'existing non-directory must not be replaced\n')
        result = self.invoke(); self.assertNotEqual(0,result.returncode)
        self.assertEqual(b'recovery remains available\n',old.read_bytes())
        self.assertEqual(b'existing non-directory must not be replaced\n',self.data.read_bytes())

    def test_upgrade_does_not_chown_restored_user_or_data(self):
        (self.saved / 'addon-data/history').write_bytes(b'original data owner is retained\n')
        result = self.invoke(); self.assertEqual(0,result.returncode,result.stderr)
        self.assertFalse(self.calls.exists())


if __name__ == '__main__':
    unittest.main()
