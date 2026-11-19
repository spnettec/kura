#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Run as Root in a disposable Linux fixture with only a source file and tmpfs.

No Kura identity, namespace, system policy, service or network is initialized.
Only the policy path is relocated; production ownership checks remain intact.
"""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0
                     and os.environ.get('KURA_NETWORK_POLICY_SOURCE'),
                     'requires an explicitly supplied disposable Linux Root fixture')
class NetworkPolkitPolicyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir='/opt/policy-fixture')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rules = self.root / 'rules'; self.rules.mkdir(mode=0o755)
        self.path = self.rules / 'kura-nm.rules'
        raw = Path(os.environ['KURA_NETWORK_POLICY_SOURCE']).read_text()
        marker = "<<'KURA_MANAGED_NETWORK_POLICY'\n"
        self.assertEqual(1, raw.count(marker))
        self.body = raw.split(marker, 1)[1].split('\nKURA_MANAGED_NETWORK_POLICY', 1)[0]
        fixed = "PATH = Path('/usr/share/polkit-1/rules.d/kura-nm.rules')"
        self.assertEqual(1, self.body.count(fixed))
        self.body = self.body.replace(fixed, 'PATH = Path(' + repr(str(self.path)) + ')')

    def invoke(self, action, ok=True):
        result = subprocess.run([sys.executable, '-I', '-B', '-c', self.body, action],
                                capture_output=True, text=True, timeout=5)
        if ok: self.assertEqual(0, result.returncode, result.stderr)
        else: self.assertNotEqual(0, result.returncode)
        return result

    def fingerprint(self, path=None):
        path = self.path if path is None else path
        m = path.lstat()
        # readlink itself changes a link's atime. Observe its metadata without
        # reading the target text; the link target is checked after this contract.
        if stat.S_ISLNK(m.st_mode): digest = None
        elif stat.S_ISREG(m.st_mode):
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME)
            with os.fdopen(fd, 'rb') as source: digest = hashlib.sha256(source.read()).hexdigest()
        else: digest = None
        return (m.st_dev, m.st_ino, m.st_uid, m.st_gid, m.st_mode, m.st_nlink,
                m.st_size, m.st_atime_ns, m.st_mtime_ns, m.st_ctime_ns, digest)

    def reject_all_unchanged(self):
        before = self.fingerprint()
        for action in ('check', 'install', 'remove'):
            self.invoke(action, False)
            self.assertEqual(before, self.fingerprint())

    def test_known_policy_install_check_and_remove_are_idempotent(self):
        self.invoke('check'); self.assertFalse(self.path.exists())
        self.invoke('install'); self.assertEqual(0, self.path.stat().st_uid)
        self.assertEqual(0o644, stat.S_IMODE(self.path.stat().st_mode))
        self.assertEqual('16bc6c9aa7aa9a916a18e7ed8d5eb26d1a86094af98dc4a04b04902daaa55721',
                         self.fingerprint()[-1])
        before = self.fingerprint(); self.invoke('check'); self.invoke('install')
        self.assertEqual(before, self.fingerprint())
        self.invoke('remove'); self.invoke('remove'); self.assertFalse(self.path.exists())
        self.assertEqual([], list(self.rules.iterdir()))

    def test_both_known_historical_rules_migrate_to_the_same_narrower_policy(self):
        legacy = self.body.split("LEGACY = b" + "'" * 3, 1)[1].split("'" * 3, 1)[0].encode()
        lines = legacy.splitlines(keepends=True)
        networking = lines[0] + b''.join(line[4:] for line in lines[1:])
        for rule in (legacy, networking):
            self.path.write_bytes(rule)
            before = self.fingerprint()
            self.invoke('check')
            self.assertEqual(before, self.fingerprint())
            self.invoke('retire-wpa')
            current = self.path.read_bytes()
            self.assertIn(b'org.freedesktop.NetworkManager.', current)
            self.assertIn(b'org.freedesktop.ModemManager1.', current)
            self.assertNotIn(b'fi.w1.wpa_supplicant1.', current)
            self.invoke('remove')
        self.invoke('retire-wpa')
        self.assertFalse(self.path.exists())

    def test_custom_rule_is_preserved_including_all_metadata(self):
        self.path.write_bytes(b'// Root site rule must be retained\n'); self.path.chmod(0o600)
        self.reject_all_unchanged()

    def test_symlink_is_never_followed(self):
        target = self.root / 'site'; target.write_bytes(b'keep site target\n')
        self.path.symlink_to(target); before = self.fingerprint(target)
        self.reject_all_unchanged(); self.assertEqual(before, self.fingerprint(target))
        self.assertEqual(str(target), os.readlink(self.path))

    def test_hardlink_is_preserved_without_mutation(self):
        self.invoke('install'); alias = self.rules / 'alias'; os.link(self.path, alias)
        before = self.fingerprint(alias); self.reject_all_unchanged()
        self.assertEqual(before, self.fingerprint(alias))

    def test_wrong_owner_is_rejected(self):
        self.invoke('install'); os.chown(self.path, 999, 999)
        self.reject_all_unchanged()

    def test_group_writable_rule_is_rejected(self):
        self.invoke('install'); self.path.chmod(0o664); self.reject_all_unchanged()

    def test_symlink_parent_is_rejected(self):
        self.invoke('install'); actual = self.root / 'actual'; self.rules.rename(actual)
        self.rules.symlink_to(actual, target_is_directory=True)
        self.reject_all_unchanged()

    def test_wrong_owner_parent_is_rejected(self):
        self.invoke('install'); os.chown(self.rules, 999, 999)
        self.reject_all_unchanged(); os.chown(self.rules, 0, 0)

    def test_writable_parent_is_not_repaired_or_used(self):
        self.rules.chmod(0o777); before = self.rules.stat().st_mode
        for action in ('check', 'install', 'remove'): self.invoke(action, False)
        self.assertEqual(before, self.rules.stat().st_mode); self.assertFalse(self.path.exists())

    def test_fifo_is_rejected_without_blocking(self):
        os.mkfifo(self.path); self.reject_all_unchanged()

    def test_existing_known_private_code_can_be_made_readable_to_polkit(self):
        self.invoke('install'); self.path.chmod(0o600); before = self.fingerprint()
        self.invoke('check'); self.assertEqual(before, self.fingerprint())
        self.invoke('install'); self.assertEqual(0o644, stat.S_IMODE(self.path.stat().st_mode))
        self.assertEqual(before[-1], self.fingerprint()[-1]); self.invoke('remove')

    def test_oversized_rule_and_unknown_actions_are_rejected(self):
        self.path.write_bytes(b'x' * 16385); self.reject_all_unchanged()
        self.invoke('unreviewed', False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
