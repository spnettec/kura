#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Installer re-entry after fixed handoff; synthetic Root receipts, no key operations."""
import fcntl
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/bin'))
import kura_key_recovery_setup as setup
import test_key_handoff_recovery as handoff


class RecoverySetupHandoffTest(unittest.TestCase):
    def setUp(self):
        self.fixture=handoff.HandoffPackageGateTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        self.account=SimpleNamespace(pw_uid=f.recovery_uid,pw_gid=f.recovery_gid,pw_shell='/usr/sbin/nologin')
        self.setup=setup.Setup(f.path,owner=os.geteuid())

    def adopt(self):
        if os.geteuid()==0:
            for path in [*self.fixture.journal.directory.rglob('*'),self.fixture.journal.directory]:os.chown(path,self.account.pw_uid,self.account.pw_gid)

    def complete(self):
        f=self.fixture;f.execute('publish');f.execute('start');f.execute('complete');f.originals();self.adopt()

    def snapshot(self):
        import hashlib
        values={}
        for base in (self.fixture.journal.directory,self.fixture.gate.state):
            for p in base.rglob('*'):
                if p.is_file():
                    s=p.lstat();values[str(p)]=(s.st_ino,s.st_uid,s.st_gid,s.st_mode,s.st_nlink,s.st_mtime_ns,s.st_ctime_ns,hashlib.sha256(p.read_bytes()).hexdigest())
        return values

    def test_completed_handoff_can_be_configured_again_without_rewriting_sender_or_root_records(self):
        self.complete();before=self.snapshot();self.setup.state(self.account);self.assertEqual(before,self.snapshot())

    def test_empty_handoff_inventory_is_accepted_with_the_existing_private_layout(self):
        self.assertEqual([],list((self.fixture.journal.directory/'handoffs').iterdir()));self.adopt();self.setup.state(self.account)

    def test_unconfirmed_handoff_is_refused_without_rewriting_any_original(self):
        self.fixture.root.absent=True;self.fixture.execute('publish');self.adopt();before=self.snapshot()
        with self.assertRaises(setup.Refused):self.setup.state(self.account)
        self.assertEqual(before,self.snapshot())

    def test_local_completion_cannot_replace_a_missing_root_original(self):
        self.complete();f=self.fixture;(f.gate.state/'operations'/(f.root.info['startOperationId']+'.json')).unlink();before=self.snapshot()
        with self.assertRaises(setup.Refused):self.setup.state(self.account)
        self.assertEqual(before,self.snapshot())

    def test_local_completion_cannot_settle_a_root_intent(self):
        import json
        self.complete();f=self.fixture;p=f.gate.state/'operations'/(f.root.info['publicationId']+'.json')
        value=json.loads(p.read_bytes());value.update(state='INTENT',response=None);p.write_text(json.dumps(value));before=self.snapshot()
        with self.assertRaises(setup.Refused):self.setup.state(self.account)
        self.assertEqual(before,self.snapshot())

    def test_active_recovery_lock_prevents_installer_reentry(self):
        self.complete();fd=os.open(self.fixture.journal.directory/'admission.lock',os.O_RDONLY|os.O_NOFOLLOW)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);before=self.snapshot()
            with self.assertRaises(setup.Refused):self.setup.state(self.account)
            self.assertEqual(before,self.snapshot())
        finally:os.close(fd)

    def test_installer_isolated_python_loads_its_own_ledger_from_an_untrusted_working_directory(self):
        self.complete();before=self.snapshot();f=self.fixture
        with tempfile.TemporaryDirectory(prefix='untrusted-installer-cwd-') as name:
            working=Path(name);(working/'kura_key_service_lifecycle.py').write_text("raise AssertionError('untrusted ledger loaded')\n")
            script='''import importlib.util,sys,pwd
from pathlib import Path
from types import SimpleNamespace
p=Path(sys.argv[1]);spec=importlib.util.spec_from_file_location('setup_under_test',p)
m=importlib.util.module_from_spec(spec);exec(compile(p.read_bytes(),str(p),'exec'),m.__dict__)
account=SimpleNamespace(pw_uid=int(sys.argv[3]),pw_gid=int(sys.argv[4]),pw_shell='/usr/sbin/nologin')
pwd.getpwnam=lambda name: account if name=='kura-key-recovery' else SimpleNamespace(pw_uid=account.pw_uid+1)
m.Setup(Path(sys.argv[2]),owner=int(sys.argv[5])).state(account)
print('ISOLATED_SETUP_HANDOFF_OK')
'''
            result=subprocess.run([sys.executable,'-I','-c',script,setup.__file__,str(f.path),str(self.account.pw_uid),str(self.account.pw_gid),str(os.geteuid())],
                                  cwd=working,env=dict(os.environ,PYTHONPATH=str(working)),capture_output=True,text=True,timeout=10)
            self.assertEqual(0,result.returncode,result.stderr);self.assertEqual('ISOLATED_SETUP_HANDOFF_OK',result.stdout.strip())
        self.assertEqual(before,self.snapshot())

    def test_companion_ledger_must_be_a_single_protected_regular_file(self):
        with tempfile.TemporaryDirectory(prefix='installer-companion-') as name:
            directory=Path(name);directory.chmod(0o700)
            original=Path(setup.__file__);anchor=directory/original.name;ledger=directory/'kura_key_service_lifecycle.py'
            shutil.copyfile(original,anchor);shutil.copyfile(original.with_name(ledger.name),ledger)
            anchor.chmod(0o600);ledger.chmod(0o600)
            import importlib.util
            spec=importlib.util.spec_from_file_location('copied_setup',anchor);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            module.Setup.handoff_ledger()
            ledger.chmod(0o620)
            with self.assertRaises(module.Refused):module.Setup.handoff_ledger()
            ledger.chmod(0o600);extra=directory/'extra';os.link(ledger,extra)
            with self.assertRaises(module.Refused):module.Setup.handoff_ledger()
            extra.unlink();ledger.rename(extra);ledger.symlink_to(extra)
            with self.assertRaises(module.Refused):module.Setup.handoff_ledger()

    def test_checked_source_is_used_instead_of_a_timestamp_matching_poisoned_bytecode_cache(self):
        import importlib.util
        import marshal
        import struct
        with tempfile.TemporaryDirectory(prefix='installer-bytecode-') as name, patch.object(sys,'pycache_prefix',None):
            directory=Path(name);directory.chmod(0o700);original=Path(setup.__file__)
            anchor=directory/original.name;ledger=directory/'kura_key_service_lifecycle.py'
            shutil.copyfile(original,anchor);shutil.copyfile(original.with_name(ledger.name),ledger);anchor.chmod(0o600);ledger.chmod(0o600)
            cache=Path(importlib.util.cache_from_source(str(ledger)));cache.parent.mkdir(mode=0o700)
            s=ledger.stat();poison=importlib.util.MAGIC_NUMBER+struct.pack('<III',0,int(s.st_mtime)&0xffffffff,s.st_size)
            poison+=marshal.dumps(compile("raise AssertionError('poisoned cache loaded')",str(ledger),'exec'));cache.write_bytes(poison)
            spec=importlib.util.spec_from_file_location('copied_setup_no_cache',anchor);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            loaded=module.Setup.handoff_ledger();self.assertTrue(hasattr(loaded.Lifecycle,'recovery_locked'));self.assertEqual(poison,cache.read_bytes())


if __name__=='__main__':unittest.main()
