# SPDX-License-Identifier: EPL-2.0
"""PAM paired-rule lifecycle and preservation boundaries; native auth is separate."""
import fcntl
import hashlib
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'main/resources/unfiltered/pkg/bin/kura_su_pam.py'
SPEC = importlib.util.spec_from_file_location('kura_su_policy_test', HELPER)
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
BASE = b'# local site comment\nauth       sufficient pam_rootok.so\n# preserve these unrelated auth rules\nauth required pam_group.so\n@include common-auth\naccount required pam_unix.so\n@include common-session\n'
PAIR = (P.TARGET + '\n' + P.CALLER + '\n').encode()


class SuPamPolicy(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.file = self.root / 'su'
        self.file.write_bytes(BASE)
        self.file.chmod(0o644)
        for name,data in {'common-auth':b'auth required pam_unix.so\n',
                          'common-session':b'session required pam_unix.so\nsession optional pam_systemd.so\n',
                          'common-session-noninteractive':b'session required pam_unix.so\n'}.items():
            (self.root/name).write_bytes(data)
            (self.root/name).chmod(0o644)
        self.policy = P.Policy(self.file)

    def legacy(self, count=1):
        self.file.write_bytes(BASE.replace(b'# preserve', PAIR * count + b'# preserve'))

    def unchanged(self, original):
        self.assertEqual(self.file.read_bytes(), original)

    def test_check_is_readonly_and_creates_no_lock_or_backup(self):
        before = self.file.stat()
        names = sorted(p.name for p in self.root.iterdir())
        self.assertFalse(self.policy.apply('check'))
        self.assertEqual(self.file.stat().st_ino, before.st_ino)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), names)

    def test_install_and_remove_preserve_all_site_lines_and_modes(self):
        self.assertTrue(self.policy.apply('install'))
        self.assertIn(PAIR, self.file.read_bytes())
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o644)
        self.assertTrue(self.policy.apply('remove'))
        self.unchanged(BASE)

    def test_repeat_install_and_remove_are_idempotent_with_no_inode_churn(self):
        self.policy.apply('install')
        before = self.file.stat().st_ino
        backups = sorted(self.root.glob('*.kurasave'))
        self.assertFalse(self.policy.apply('install'))
        self.assertEqual(before, self.file.stat().st_ino)
        self.assertEqual(backups, sorted(self.root.glob('*.kurasave')))
        self.policy.apply('remove')
        before = self.file.stat().st_ino
        self.assertFalse(self.policy.apply('remove'))
        self.assertEqual(before, self.file.stat().st_ino)

    def test_repeated_legacy_upgrades_collapse_to_one_pair(self):
        self.legacy(5)
        original = self.file.read_bytes()
        self.policy.apply('install')
        self.assertEqual(self.file.read_text().count(P.TARGET), 1)
        self.assertEqual(self.file.read_text().count(P.CALLER), 1)
        self.assertEqual((self.root / ('su.' + hashlib.sha256(original).hexdigest() + '.kurasave')).read_bytes(), original)
        self.policy.apply('remove')
        self.unchanged(BASE)

    def test_remove_retires_every_legacy_pair(self):
        self.legacy(5)
        self.policy.apply('remove')
        self.unchanged(BASE)

    def test_interrupted_old_uninstall_orphan_grant_is_removed(self):
        self.file.write_bytes(BASE.replace(b'# preserve', (P.CALLER + '\n').encode() + b'# preserve'))
        self.policy.apply('remove')
        self.unchanged(BASE)

    def test_install_repairs_orphan_legacy_grant_without_duplicate(self):
        self.file.write_bytes(BASE.replace(b'# preserve', (P.CALLER + '\n').encode() + b'# preserve'))
        self.policy.apply('install')
        self.assertEqual(self.file.read_text().count(P.CALLER), 1)
        self.assertEqual(self.file.read_text().count(P.TARGET), 1)

    def test_remove_keeps_unrelated_lines_immediately_after_rootok(self):
        self.policy.apply('remove')
        self.unchanged(BASE)
        self.assertIn(b'auth required pam_group.so', self.file.read_bytes())

    def test_backup_is_private_content_addressed_and_exact(self):
        self.policy.apply('install')
        backup = self.root / ('su.' + hashlib.sha256(BASE).hexdigest() + '.kurasave')
        self.assertEqual(backup.read_bytes(), BASE)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_conflicting_backup_is_not_overwritten(self):
        backup = self.root / ('su.' + hashlib.sha256(BASE).hexdigest() + '.kurasave')
        backup.write_bytes(b'site-owned-conflict'); backup.chmod(0o600)
        with self.assertRaises(P.Refused): self.policy.apply('install')
        self.unchanged(BASE)
        self.assertEqual(backup.read_bytes(), b'site-owned-conflict')

    def test_symlink_backup_is_not_followed(self):
        target = self.root / 'outside'; target.write_bytes(b'untouched')
        backup = self.root / ('su.' + hashlib.sha256(BASE).hexdigest() + '.kurasave')
        backup.symlink_to(target)
        with self.assertRaises(OSError): self.policy.apply('install')
        self.unchanged(BASE)
        self.assertEqual(target.read_bytes(), b'untouched')

    def test_source_symlink_hardlink_fifo_and_writable_mode_are_refused(self):
        outside = self.root / 'other'; outside.write_bytes(BASE)
        self.file.unlink(); self.file.symlink_to(outside)
        with self.assertRaises(OSError): self.policy.apply('install')
        self.file.unlink(); os.link(outside, self.file)
        with self.assertRaises(P.Refused): self.policy.apply('install')
        self.file.unlink(); os.mkfifo(self.file)
        with self.assertRaises(P.Refused): self.policy.apply('install')
        self.file.unlink(); self.file.write_bytes(BASE); self.file.chmod(0o666)
        with self.assertRaises(P.Refused): self.policy.apply('install')
        self.unchanged(BASE)

    def test_untrusted_parent_and_owner_are_refused(self):
        self.root.chmod(0o777)
        with self.assertRaises(P.Refused): self.policy.apply('install')
        self.root.chmod(0o700)
        with self.assertRaises(P.Refused): P.Policy(self.file, owner=os.geteuid()+1).apply('install')
        self.unchanged(BASE)

    def test_missing_ambiguous_or_custom_rootok_anchor_is_held(self):
        for data in [BASE.replace(b'pam_rootok.so', b'pam_site.so'), BASE + b'auth sufficient pam_rootok.so\n', BASE.replace(b'pam_rootok.so', b'pam_rootok.so debug')]:
            self.file.write_bytes(data)
            with self.assertRaises(P.Refused): self.policy.apply('check')
            with self.assertRaises(P.Refused): self.policy.apply('install')
            self.unchanged(data)

    def test_remove_does_not_require_unmodified_site_anchor(self):
        data=BASE.replace(b'pam_rootok.so', b'pam_site.so')
        self.file.write_bytes(data + PAIR)
        self.policy.apply('remove')
        self.unchanged(data)

    def test_malformed_owned_block_is_held_without_removing_local_policy(self):
        for block in [P.BEGIN+'\n'+P.CALLER+'\n'+P.END+'\n', P.BEGIN+'\n'+P.TARGET+'\n', P.END+'\n', P.BEGIN+'\n'+P.BEGIN+'\n']:
            data=BASE+block.encode(); self.file.write_bytes(data)
            with self.assertRaises(P.Refused): self.policy.apply('install')
            with self.assertRaises(P.Refused): self.policy.apply('remove')
            self.unchanged(data)

    def test_site_admin_grants_and_non_utf8_comments_are_preserved(self):
        data=BASE+b'# local bytes: \xff\nauth sufficient pam_succeed_if.so use_uid user = siteadmin\n'
        self.file.write_bytes(data)
        self.policy.apply('install'); self.policy.apply('remove')
        self.unchanged(data)

    def test_crlf_policy_round_trips_without_rewriting_site_lines(self):
        data=BASE.replace(b'\n',b'\r\n'); self.file.write_bytes(data)
        self.policy.apply('install'); self.policy.apply('remove')
        self.unchanged(data)

    def test_nul_and_oversize_sources_are_held(self):
        for data in [BASE+b'\0',BASE+b'#'*(P.LIMIT+1)]:
            self.file.write_bytes(data)
            with self.assertRaises(P.Refused): self.policy.apply('install')
            self.unchanged(data)

    def test_concurrent_policy_lock_refuses_before_change(self):
        lock=os.open(self.root/'.kura-su-policy.lock',os.O_RDWR|os.O_CREAT,0o600)
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError): self.policy.apply('install')
            self.unchanged(BASE)
        finally: os.close(lock)

    def test_failed_staging_keeps_original_policy(self):
        create=self.policy.create
        def fail(directory,name,*args):
            if name.startswith('.kura-su-policy-'): raise OSError('test write failure')
            return create(directory,name,*args)
        with patch.object(self.policy,'create',side_effect=fail):
            with self.assertRaises(OSError): self.policy.apply('install')
        self.unchanged(BASE)

    def test_concurrent_site_edit_is_not_overwritten(self):
        create=self.policy.create; site=BASE+b'# concurrent site edit\n'
        def edit(directory,name,*args):
            if name.startswith('.kura-su-policy-'): self.file.write_bytes(site)
            return create(directory,name,*args)
        with patch.object(self.policy,'create',side_effect=edit):
            with self.assertRaises(P.Refused): self.policy.apply('install')
        self.unchanged(site)

    def test_pair_is_published_in_one_replace_without_intermediate_orphan(self):
        self.policy.apply('install')
        replace=os.replace; seen=[]
        def observe(*args,**kwargs):
            data=self.file.read_bytes(); seen.append(data)
            self.assertIn(PAIR,data)
            return replace(*args,**kwargs)
        with patch.object(P.os,'replace',side_effect=observe): self.policy.apply('remove')
        self.assertEqual(len(seen),1)
        self.unchanged(BASE)

    def test_session_route_is_only_for_daemon_and_normal_stack_is_preserved(self):
        self.policy.apply('install')
        text=self.file.read_text()
        for rule in P.SESSION_RULES:self.assertIn(rule,text)
        self.assertEqual(text.count(P.SESSION_BEGIN),1)
        self.policy.apply('remove');self.unchanged(BASE)

    def test_readonly_installed_check_rejects_missing_or_changed_policy(self):
        with self.assertRaises(P.Refused):self.policy.apply('check-installed')
        self.policy.apply('install');before=self.file.stat().st_ino
        self.assertFalse(self.policy.apply('check-installed'))
        self.assertEqual(self.file.stat().st_ino,before)
        self.file.write_text(self.file.read_text().replace(P.SESSION_RULES[0],P.SESSION_RULES[0]+' debug'))
        with self.assertRaises(P.Refused):self.policy.apply('check-installed')

    def test_noninteractive_systemd_direct_or_nested_is_held_before_grant(self):
        source=self.root/'common-session-noninteractive'
        for data in [b'session optional pam_systemd.so\n',b'@include nested-session\n']:
            (self.root/'nested-session').write_bytes(b'session optional /lib/security/pam_systemd.so\n')
            source.write_bytes(data)
            with self.assertRaises(P.Refused):self.policy.apply('install')
            self.unchanged(BASE)

    def test_uncontrolled_su_session_include_cannot_create_another_scope(self):
        data=BASE+b'@include site-session\n';self.file.write_bytes(data)
        (self.root/'site-session').write_bytes(b'session optional pam_systemd.so\n')
        with self.assertRaises(P.Refused):self.policy.apply('install')
        self.unchanged(data)

    def test_cycle_missing_or_unsafe_session_dependency_is_held(self):
        source=self.root/'common-session-noninteractive'
        source.write_bytes(b'@include common-session-noninteractive\n')
        with self.assertRaises(P.Refused):self.policy.apply('install')
        source.unlink()
        with self.assertRaises(FileNotFoundError):self.policy.apply('install')
        source.write_bytes(b'session required pam_unix.so\n');source.chmod(0o666)
        with self.assertRaises(P.Refused):self.policy.apply('install')
        self.unchanged(BASE)

    def test_removal_restores_original_session_include_spacing_and_crlf(self):
        data=BASE.replace(b'@include common-session\n',b'  @include\tcommon-session\r\n')
        self.file.write_bytes(data);self.policy.apply('install');self.policy.apply('remove')
        self.unchanged(data)

    def test_non_ascii_nel_comment_round_trips_as_one_physical_line(self):
        data=BASE+b'# keep non-ASCII bytes: \x85 auth sufficient pam_succeed_if.so use_uid user = kurad\n'
        self.file.write_bytes(data);self.policy.apply('install');self.policy.apply('remove')
        self.unchanged(data)

    def test_concurrent_session_stack_edit_is_not_overwritten_or_published(self):
        create=self.policy.create;source=self.root/'common-session-noninteractive'
        def edit(directory,name,*args):
            if name.startswith('.kura-su-policy-'):source.write_bytes(b'session optional pam_systemd.so\n')
            return create(directory,name,*args)
        with patch.object(self.policy,'create',side_effect=edit):
            with self.assertRaises(P.Refused):self.policy.apply('install')
        self.unchanged(BASE)

    def test_standalone_preflight_rejects_before_files_keys_accounts_or_services(self):
        install=ROOT/'main/resources/variants/linux/unfiltered/pkg/install/kura_install.sh'
        driver=self.root/'kura_install.sh';driver.write_bytes(install.read_bytes())
        manager=self.root/'manage_kura_users.sh';manager.write_text('#!/bin/sh\n[ "$1" = --check-polkit ] && exit 0\n[ "$1" = --check-pam ] && exit 1\nexit 99\n')
        marker=self.root/'mutation';stub=self.root/'bin';stub.mkdir()
        for name in ['cp','ln','rm','python3','systemctl','useradd','sed','mkdir','chmod']:
            f=stub/name;f.write_text('#!/bin/sh\nprintf attempt >> '+shlex.quote(str(marker))+'\nexit 98\n');f.chmod(0o755)
        result=subprocess.run(['sh',str(driver)],capture_output=True,env=dict(os.environ,PATH=str(stub)+':'+os.environ['PATH']))
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(marker.exists())


if __name__=='__main__': unittest.main()
