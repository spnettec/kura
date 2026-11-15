#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""New role, TLS and package-profile contracts; no installed gateway mutation."""
import contextlib,hashlib,json,os
from pathlib import Path
import secrets,ssl,subprocess,sys,tempfile,unittest,uuid
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/bin'))
import kura_key_service as service
import kura_key_service_lifecycle as lifecycle
import kura_key_recovery_setup as setup
import kura_runtime_ownership as ownership


class Temporary(unittest.TestCase):
    def setUp(self):
        self.old_umask=os.umask(0o077);self.addCleanup(os.umask,self.old_umask)
        temporary=tempfile.TemporaryDirectory(prefix='kura-cold-install-new-');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    @staticmethod
    def write(path,data,mode=0o600):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data);path.chmod(mode)


class PeerPolicy(Temporary):
    def setUp(self):
        super().setUp();self.manager=service.Manager(self.root,os.geteuid())
        self.manager.lock=lambda *_:contextlib.nullcontext();self.manager.maintenance=lambda:None
        self.manager.read=lambda *_:b'j'*32;self.manager.record=lambda _:None;self.manager.journal_admission=lambda:None
        self.key=b'k'*32;self.sha=hashlib.sha256(self.key).hexdigest()
        self.proof=dict(schema=1,keySha256=self.sha,origin='fresh',legacyKey=False,unitDigests=[])
        self.manager.canonical=lambda *_:(self.key,self.proof)
        self.manager.atomic=lambda *_args,**_kw:self.fail('Recovery policy dispatched a forbidden mutation')

    def denied(self,reason,request):
        with self.assertRaises(service.Failure) as found:self.manager.handle(request,recovery_only=True)
        self.assertEqual(reason,found.exception.reason)

    def test_recovery_peer_cannot_export_a_backup_even_with_its_own_password(self):
        self.denied('FORBIDDEN',dict(schema=1,action='backup-create',operationId=str(uuid.uuid4()),passphrase='attacker chosen password'))

    def test_recovery_peer_cannot_read_an_existing_backup_record(self):
        self.manager.record=lambda _:dict(action='backup-create',state='INTENT')
        self.denied('FORBIDDEN',dict(schema=1,action='operation-read',operationId=str(uuid.uuid4())))

    def test_recovery_peer_rejects_any_present_key_before_decrypt_or_journal(self):
        self.manager.unpack=lambda *_:self.fail('Present-key recovery attempted decryption')
        self.denied('CONFLICT',dict(schema=1,action='restore',operationId=str(uuid.uuid4()),
            expectedKeySha256=self.sha,backup={},passphrase='synthetic matching passphrase'))

    def test_inspection_marks_present_key_unrestorable_only_for_recovery_peer(self):
        identity=str(uuid.uuid4());self.manager.unpack=lambda *_:(self.key,dict(operationId=identity,createdAt='2026-11-15',receipt=self.proof))
        request=dict(schema=1,action='backup-inspect',backup={},passphrase='synthetic matching passphrase')
        self.assertFalse(self.manager.handle(request,recovery_only=True)['restoreAllowed'])
        self.assertTrue(self.manager.handle(request)['restoreAllowed'])

    def test_status_shape_is_unchanged_for_existing_gwt_clients(self):
        result=self.manager.handle(dict(schema=1,action='status'),recovery_only=True)
        self.assertEqual({'schema','keyReady','keySha256','legacyKey','agentRequired'},set(result))

    def test_missing_previous_account_is_compatible_but_uid_alias_and_login_shell_fail(self):
        with patch.object(service.pwd,'getpwnam',side_effect=KeyError):self.assertIsNone(service.recovery_identity(997))
        for uid,shell in [(0,'/sbin/nologin'),(997,'/sbin/nologin'),(996,'/bin/sh')]:
            with patch.object(service.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=uid,pw_shell=shell)):
                with self.assertRaises(service.Failure):service.recovery_identity(997)


class PackageProfiles(Temporary):
    def profile(self,legacy):
        files=lifecycle.LEGACY_ASSETS if legacy else lifecycle.ASSETS
        units=lifecycle.LEGACY_UNITS if legacy else lifecycle.UNITS
        home=self.root/'opt/eclipse/kura_6.0.0-SNAPSHOT_linux';home.mkdir(parents=True)
        (home.parent/'kura').symlink_to(home.name,target_is_directory=True)
        for name in files:self.write(home/name,('packaged '+name).encode(),0o640)
        for name in units:self.write(self.root/'lib/systemd/system'/name,('unit '+name).encode(),0o644)
        manifest=dict(schema=1,protocol=1,files={name:hashlib.sha256((home/name).read_bytes()).hexdigest() for name in files},
            units={name:hashlib.sha256((self.root/'lib/systemd/system'/name).read_bytes()).hexdigest() for name in units})
        self.write(home/'libexec/key-backup/manifest.json',lifecycle.encoded(manifest),0o640)
        (self.root/'run/systemd/system').mkdir(parents=True)
        self.commands=[]
        def runner(command,**_):
            self.commands.append(command)
            name=command[2] if len(command)>2 else ''
            loaded=(self.root/'lib/systemd/system'/name).exists()
            return SimpleNamespace(returncode=0,stdout=('LoadState='+('loaded' if loaded else 'not-found')+'\nActiveState=inactive\nMainPID=0\nControlPID=0\n'))
        return lifecycle.Lifecycle(self.root,os.geteuid(),runner)

    def test_previous_two_unit_manifest_is_read_only_accepted_for_migration(self):
        manager=self.profile(True);self.assertEqual(set(lifecycle.LEGACY_UNITS),set(manager.assets()['units']))
        manager.enter('upgrade');self.assertTrue((manager.state/'maintenance.json').exists())

    def test_new_three_unit_manifest_is_accepted(self):
        manager=self.profile(False);self.assertEqual(set(lifecycle.UNITS),set(manager.assets()['units']))

    def test_old_manifest_cannot_adopt_an_unlisted_recovery_unit(self):
        manager=self.profile(True);self.write(self.root/'lib/systemd/system/kura-key-recovery.service',b'foreign',0o644)
        with self.assertRaises(lifecycle.Refused):manager.enter('upgrade')
        self.assertFalse(manager.state.exists());self.assertFalse(any('stop' in c for c in self.commands))

    def test_unresolved_cold_intent_blocks_package_before_stop_or_root_fence(self):
        manager=self.profile(False);manager.initialize();manager.create(manager.state/'journal.key',b'j'*32)
        state=self.root/'var/lib/kura-key-recovery';operations=state/'operations';operations.mkdir(parents=True,mode=0o700)
        identity=str(uuid.uuid4());self.write(state/'admission.lock',b'')
        self.write(operations/(identity+'.json'),lifecycle.encoded(dict(schema=1,operationId=identity,expectedKeySha256='a'*64,backupSha256='b'*64)))
        uid=os.geteuid() or 996;gid=os.getegid() if os.geteuid() else 990
        for path in [state,operations,*state.rglob('*')]:os.chown(path,uid,gid)
        account=lambda name:SimpleNamespace(pw_uid=uid if name=='kura-key-recovery' else uid+1,pw_gid=gid,pw_shell='/sbin/nologin')
        with patch.object(lifecycle.pwd,'getpwnam',side_effect=account):
            with self.assertRaises((OSError,lifecycle.Refused)):manager.enter('upgrade')
        self.assertFalse((manager.state/'maintenance.json').exists());self.assertFalse(any('stop' in c for c in self.commands))


class TlsMaterial(Temporary):
    def setUp(self):
        super().setUp();self.setup=setup.Setup(self.root,os.geteuid())

    @unittest.skipUnless(sys.platform=='linux','First publication uses Linux renameat2; native check required')
    def test_first_tls_pair_is_independent_and_repeated_install_preserves_all_metadata(self):
        with self.setup.lock():self.setup.tls_material()
        def snapshot():
            return {str(p):(p.read_bytes(),p.stat().st_ino,p.stat().st_uid,p.stat().st_gid,p.stat().st_mode,p.stat().st_mtime_ns,p.stat().st_ctime_ns)
                for p in self.setup.tls.iterdir()}
        before=snapshot()
        with self.setup.lock():self.setup.tls_material()
        self.assertEqual(before,snapshot());self.assertEqual(0o400,(self.setup.tls/'server.key').stat().st_mode&0o777)
        self.assertFalse((self.root/'etc/kura/credentials').exists())

    def test_incomplete_existing_tls_is_retained_and_never_regenerated(self):
        self.setup.tls.mkdir(parents=True,mode=0o700);self.write(self.setup.tls/'server.key',b'original retained key',0o400)
        before=(self.setup.tls/'server.key').read_bytes()
        with self.assertRaises(setup.Refused):self.setup.tls_material()
        self.assertEqual(before,(self.setup.tls/'server.key').read_bytes());self.assertFalse((self.setup.tls/'server.crt').exists())

    def test_old_staging_material_blocks_another_generation(self):
        path=self.setup.base/'.recovery-tls-interrupted';path.mkdir(parents=True,mode=0o700)
        self.write(path/'server.key',b'retained interrupted material',0o400)
        with self.assertRaises(setup.Refused):self.setup.tls_material()
        self.assertFalse(self.setup.tls.exists())

    def test_symlinked_tls_directory_is_not_adopted(self):
        target=self.root/'retained';target.mkdir();self.setup.base.mkdir(parents=True)
        self.setup.tls.symlink_to(target,target_is_directory=True)
        with self.assertRaises(setup.Refused):self.setup.tls_material()
        self.assertTrue(self.setup.tls.is_symlink())


class CodeReaders(Temporary):
    def test_control_group_does_not_change_private_mutable_data_gid_or_mode(self):
        home=self.root/'home';home.mkdir();(home/'user').mkdir();self.write(home/'user/store.save',b'synthetic encrypted bytes')
        plan=ownership.Ownership(home,997,991,code_uid=0,code_gid=989).plan()
        values={str(p.relative_to(home)):(uid,gid,mode) for p,_,uid,gid,mode in plan}
        self.assertEqual((0,989,0o750),values['.']);self.assertEqual((997,991,0o600),values['user/store.save'])

    def test_extra_control_members_are_rejected_before_any_ownership_changes(self):
        daemon=SimpleNamespace(pw_uid=997,pw_gid=991);recovery=SimpleNamespace(pw_uid=996,pw_gid=990)
        with patch.object(ownership.pwd,'getpwnam',return_value=recovery),patch.object(ownership.grp,'getgrnam',
                return_value=SimpleNamespace(gr_gid=989,gr_mem=['kurad','kura-key-recovery','foreign'])):
            with self.assertRaises(ownership.Refused):ownership.code_reader_group(daemon)


class AccountPolicy(unittest.TestCase):
    def policy(self,foreign=False,unlocked=False,alias=False):
        daemon=SimpleNamespace(pw_name='kurad',pw_uid=997,pw_gid=991,pw_shell='/sbin/nologin',pw_dir='/nonexistent')
        account=SimpleNamespace(pw_name='kura-key-recovery',pw_uid=996,pw_gid=990,pw_shell='/usr/sbin/nologin',pw_dir='/nonexistent')
        private=SimpleNamespace(gr_name='kura-key-recovery',gr_gid=990,gr_mem=[])
        control=SimpleNamespace(gr_name='kura-key-control',gr_gid=989,gr_mem=['kurad','kura-key-recovery']+(['foreign'] if foreign else []))
        people=[daemon,account]+([SimpleNamespace(pw_name='foreign',pw_uid=996,pw_gid=2000)] if alias else [])
        commands=[]
        def runner(command,**_):
            commands.append(command)
            return SimpleNamespace(returncode=0,stdout='kura-key-recovery '+('P' if unlocked else 'L')+' 2026-11-15 0 99999 7 -1\n')
        policy=setup.Setup(runner=runner)
        patches=[patch.object(setup.os,'geteuid',return_value=0),
            patch.object(setup.pwd,'getpwnam',side_effect=lambda name:account if name=='kura-key-recovery' else daemon),
            patch.object(setup.pwd,'getpwall',return_value=people),
            patch.object(setup.grp,'getgrnam',side_effect=lambda name:private if name=='kura-key-recovery' else control),
            patch.object(setup.grp,'getgrall',return_value=[private,control])]
        return policy,patches,commands

    def test_valid_existing_identity_is_read_only_and_keeps_its_uid(self):
        policy,patches,commands=self.policy()
        with contextlib.ExitStack() as stack:
            for item in patches:stack.enter_context(item)
            self.assertEqual(996,policy.accounts().pw_uid)
        self.assertEqual([['/usr/bin/passwd','--status','kura-key-recovery']],commands)

    def test_unlocked_or_aliased_existing_account_is_refused_without_repair(self):
        for options in [dict(unlocked=True),dict(alias=True)]:
            policy,patches,commands=self.policy(**options)
            with contextlib.ExitStack() as stack:
                for item in patches:stack.enter_context(item)
                with self.assertRaises(setup.Refused):policy.accounts()
            self.assertTrue(all(c[0]=='/usr/bin/passwd' for c in commands))

    def test_foreign_control_member_is_refused_without_membership_changes(self):
        policy,patches,commands=self.policy(foreign=True)
        with contextlib.ExitStack() as stack:
            for item in patches:stack.enter_context(item)
            with self.assertRaises(setup.Refused):policy.accounts()
        self.assertTrue(all(c[0]=='/usr/bin/passwd' for c in commands))


if __name__=='__main__':unittest.main(verbosity=2)
