# SPDX-License-Identifier: EPL-2.0
"""Installed-code versus mutable-data ownership and preservation boundaries."""
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

HELPER=Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/bin/kura_runtime_ownership.py'
spec=importlib.util.spec_from_file_location('runtime_ownership_test',HELPER)
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)


class RuntimeOwnership(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name);self.home=self.base/'runtime';self.home.mkdir(mode=0o700)
        for name in ['bin/start.sh','install/manager.sh','plugins/core.jar','framework/kura.properties',
                     'siblings/example.jar','framework/sibling-install-order','user/security/httpskeystore.ks','user/snapshots/snapshot_1.xml',
                     'data/store.save','packages/app.dp','log/kura.log','.data/snapshot_0.xml']:
            path=self.home/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('fixture '+name).encode());path.chmod(0o600)
        for name in ['bin/start.sh','install/manager.sh']:(self.home/name).chmod(0o700)
        self.policy=P.Ownership(self.home,os.geteuid(),os.getegid(),code_uid=os.geteuid(),code_gid=os.getegid())

    def state(self,root=None):
        root=root or self.home
        return {str(p.relative_to(root)):(p.stat().st_ino,hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_all_file_bytes_and_inodes_survive_ownership_change(self):
        before=self.state();self.policy.apply();self.assertEqual(self.state(),before)

    def test_code_is_group_readable_without_daemon_group_write(self):
        self.policy.apply()
        for name in ['plugins/core.jar','framework/kura.properties','siblings/example.jar']:
            self.assertEqual((self.home/name).stat().st_mode&0o777,0o640)
        for name in ['bin/start.sh','install/manager.sh']:
            self.assertEqual((self.home/name).stat().st_mode&0o777,0o750)
        self.assertEqual(self.home.stat().st_mode&0o777,0o750)

    def test_missing_sibling_registry_is_created_empty_and_protected(self):
        path=self.home/'framework/sibling-install-order';path.unlink()
        self.policy.apply()
        self.assertEqual(path.read_bytes(),b'')
        self.assertEqual(path.stat().st_mode&0o777,0o640)

    def test_existing_sibling_registry_order_and_inode_are_preserved(self):
        path=self.home/'framework/sibling-install-order';path.write_bytes(b'networking\nmanagement-ui\n')
        before=path.stat().st_ino
        self.policy.apply()
        self.assertEqual(path.read_bytes(),b'networking\nmanagement-ui\n')
        self.assertEqual(path.stat().st_ino,before)

    def test_mutable_data_stays_private_and_existing_executable_flag_is_retained(self):
        executable=self.home/'user/job.sh';executable.write_bytes(b'#!/bin/sh\n');executable.chmod(0o700)
        self.policy.apply()
        for name in P.MUTABLE:self.assertEqual((self.home/name).stat().st_mode&0o777,0o700)
        self.assertEqual((self.home/'data/store.save').stat().st_mode&0o777,0o600)
        self.assertEqual(executable.stat().st_mode&0o777,0o700)

    def test_repeat_application_does_not_change_metadata(self):
        self.policy.apply()
        before={str(p):P.Ownership.identity(p.lstat()) for p in self.home.rglob('*')}
        self.assertEqual(self.policy.apply(),0)
        self.assertEqual(before,{str(p):P.Ownership.identity(p.lstat()) for p in self.home.rglob('*')})

    def test_missing_mutable_trees_are_created_with_private_modes(self):
        for name in ['log/kura.log','packages/app.dp']:(self.home/name).unlink()
        (self.home/'log').rmdir();(self.home/'packages').rmdir()
        self.policy.apply()
        self.assertEqual((self.home/'log').stat().st_mode&0o777,0o700)
        self.assertEqual((self.home/'packages').stat().st_mode&0o777,0o700)

    def test_external_credentials_and_recovery_copies_are_not_touched(self):
        for name in ['credentials/kura_encryption_key','kura_old/user/security/key']:
            path=self.base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(os.urandom(32));path.chmod(0o400)
        before=self.state(self.base);self.policy.apply();self.assertEqual(self.state(self.base),before)
        self.assertEqual((self.base/'credentials/kura_encryption_key').stat().st_mode&0o777,0o400)

    def test_hardlinked_data_is_held_before_any_permission_change(self):
        original=self.home/'data/store.save';os.link(original,self.base/'outside-hardlink')
        before=self.home.stat().st_mode
        with self.assertRaises(P.Refused):self.policy.apply()
        self.assertEqual(self.home.stat().st_mode,before)
        self.assertEqual(original.stat().st_mode&0o777,0o600)

    def test_static_symlink_is_held_without_changing_external_target(self):
        outside=self.base/'outside';outside.write_bytes(b'unchanged');before=outside.stat()
        (self.home/'bin/unreviewed').symlink_to(outside)
        with self.assertRaises(P.Refused):self.policy.apply()
        self.assertEqual(outside.read_bytes(),b'unchanged');self.assertEqual(outside.stat().st_mode,before.st_mode)

    def test_mutable_root_symlink_is_not_followed_or_replaced(self):
        (self.home/'log/kura.log').unlink();(self.home/'log').rmdir();outside=self.base/'outside';outside.mkdir()
        (self.home/'log').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(P.Refused):self.policy.apply()
        self.assertTrue((self.home/'log').is_symlink());self.assertEqual(list(outside.iterdir()),[])

    def test_mutable_child_symlink_does_not_change_target(self):
        outside=self.base/'outside';outside.write_bytes(b'unchanged');outside.chmod(0o400);before=outside.stat()
        (self.home/'user/reference').symlink_to(outside)
        self.policy.apply()
        self.assertEqual(outside.read_bytes(),b'unchanged');self.assertEqual(outside.stat().st_mode,before.st_mode)

    def test_fifo_and_special_mode_are_held_before_changes(self):
        fifo=self.home/'data/fifo';os.mkfifo(fifo)
        with self.assertRaises(P.Refused):self.policy.apply()
        fifo.unlink();path=self.home/'user/special';path.write_bytes(b'site-owned');path.chmod(0o4700)
        with self.assertRaises(P.Refused):self.policy.apply()
        self.assertEqual(path.read_bytes(),b'site-owned')

    def test_regular_file_at_mutable_root_is_held_before_changes(self):
        (self.home/'log/kura.log').unlink();(self.home/'log').rmdir()
        (self.home/'log').write_bytes(b'original retained data')
        before=self.home.stat().st_mode
        with self.assertRaises(P.Refused):self.policy.apply()
        self.assertEqual(self.home.stat().st_mode,before)
        self.assertEqual((self.home/'log').read_bytes(),b'original retained data')

    def test_physical_runtime_must_not_itself_be_a_symlink(self):
        alias=self.base/'alias';alias.symlink_to(self.home,target_is_directory=True)
        with self.assertRaises(P.Refused):P.Ownership(alias,os.geteuid(),os.getegid()).plan()

    def test_replaced_node_is_held_without_following_the_new_alias(self):
        outside=self.base/'outside';outside.write_bytes(b'unchanged');outside.chmod(0o400)
        target=self.home/'plugins/core.jar';original=self.policy.plan;calls=0
        def replace_after_plan():
            nonlocal calls
            rows=original();calls+=1
            if calls==2:
                target.rename(self.home/'plugins/original-retained.jar');target.symlink_to(outside)
            return rows
        with patch.object(self.policy,'plan',side_effect=replace_after_plan):
            with self.assertRaises(P.Refused):self.policy.apply()
        self.assertEqual(outside.read_bytes(),b'unchanged');self.assertEqual(outside.stat().st_mode&0o777,0o400)
        self.assertTrue((self.home/'plugins/original-retained.jar').exists())

    def test_code_only_normalization_preserves_intentional_data_owner_and_mode(self):
        path=self.home/'user/security/httpskeystore.ks';path.chmod(0o400)
        before={str(p):P.Ownership.identity(p.lstat()) for name in P.MUTABLE for p in [self.home/name,*(self.home/name).rglob('*')]}
        data=self.state()
        self.policy.apply(code_only=True)
        self.assertEqual(self.state(),data)
        self.assertEqual(before,{str(p):P.Ownership.identity(p.lstat()) for name in P.MUTABLE for p in [self.home/name,*(self.home/name).rglob('*')]})
        self.assertEqual((self.home/'framework/kura.properties').stat().st_mode&0o777,0o640)

    def test_code_only_creates_missing_data_directory_without_touching_existing_data(self):
        (self.home/'log/kura.log').unlink();(self.home/'log').rmdir()
        before=(self.home/'user/security/httpskeystore.ks').stat()
        self.policy.apply(code_only=True)
        self.assertEqual((self.home/'log').stat().st_mode&0o777,0o700)
        self.assertEqual((self.home/'log').stat().st_uid,os.geteuid())
        self.assertEqual(P.Ownership.identity((self.home/'user/security/httpskeystore.ks').stat()),P.Ownership.identity(before))

    def test_code_only_does_not_modify_retained_runtime_socket(self):
        import socket
        path=self.home/'data/preserved.sock';sock=socket.socket(socket.AF_UNIX)
        try:
            sock.bind(str(path));before=P.Ownership.identity(path.lstat())
            self.policy.apply(code_only=True)
            self.assertEqual(P.Ownership.identity(path.lstat()),before)
        finally:sock.close()

    def test_postinst_propagates_installer_failure_before_removing_recovery_scripts(self):
        import re,subprocess
        control=HELPER.parents[3]/'variants/linux/unfiltered/deb/control/postinst'
        # Use the actual shipped function; a failed child must stop it before cleanup.
        function=re.search(r'^function postInstall \{\n.*?^\}',control.read_text(),re.M|re.S).group()
        root=self.base/'candidate'
        folder=root/'kura_test/install'
        folder.mkdir(parents=True)
        marker=root/'child-ran'
        driver=folder/'kura_install.sh'
        driver.write_text('#!/bin/sh\nprintf attempted > "$INSTALL_DIR/child-ran"\nexit 42\n')
        phase='''packageConfigure() {
            printf '%s\n' "$1" >> "$INSTALL_DIR/phases"
            printf 'NEW install %s/kura_test\n' "$INSTALL_DIR"
        }'''
        env=dict(os.environ,INSTALL_DIR=str(root),LOG=str(root/'installer.log'))
        result=subprocess.run(['bash','-c',phase+'\n'+function+'\npostInstall\n'],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,1)
        self.assertEqual(marker.read_text(),'attempted')
        self.assertEqual((root/'phases').read_text(),'status\nbegin\n')
        self.assertTrue(driver.exists())

    def test_installer_cli_rejects_arguments_without_touching_layout(self):
        before=self.state()
        self.assertEqual(P.main(['/unreviewed/path']),1)
        self.assertEqual(self.state(),before)


if __name__=='__main__':unittest.main()
