#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""New original-restore settlement fixtures; Main, native execution and decryption are models."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from test_key_receiver_admission_recovery import AdmissionRoot, recovery, protocol, BACKUP, PASSWORD, SHA
import kura_key_service_lifecycle as lifecycle
import test_key_sender_admissions as root_models


def metadata(path):
    s=path.lstat()
    return (s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)


@unittest.skipUnless(sys.platform=='linux','Original marker publication uses Linux no-replace rename')
class ReceiverRestoreSettlementTest(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='kura-original-restore-settlement-');self.addCleanup(temporary.cleanup)
        self.directory=Path(temporary.name);self.directory.chmod(0o700)
        self.root=AdmissionRoot();self.root.lose=False;self.journal=recovery.Journal(self.directory)
        self.sender=recovery.SenderAdmission(self.root,self.journal);self.controller=recovery.Controller(self.root,self.journal,self.sender)
        self.identity=str(uuid.uuid4());self.value=dict(operationId=self.identity,expectedKeySha256=SHA,backupJson=json.dumps(BACKUP),passphrase=PASSWORD)
        self.intent=dict(schema=1,operationId=self.identity,expectedKeySha256=SHA,backupSha256=hashlib.sha256(protocol.encode(BACKUP)).hexdigest())
        self.request=dict(schema=1,action='restore',operationId=self.identity,expectedKeySha256=SHA,backup=BACKUP,passphrase=PASSWORD)
        self.pending=self.directory/'pending.json';self.record=self.journal.operations/(self.identity+'.json')
        self.archive=self.sender.path('restore',self.identity)/'pending.json'

    def seed(self, *, early=False):
        def before_native():
            self.journal.mark(self.identity,SHA)
            if not early:self.journal.admit(self.intent)
            raise OSError('modeled interruption before the Root restore command')
        with self.assertRaises(OSError):self.sender.submit('restore',self.identity,self.request,before_native)
        self.pending_bytes=self.pending.read_bytes();self.pending_metadata=metadata(self.pending)
        self.record_before=(self.record.read_bytes(),metadata(self.record)) if self.record.exists() else None

    def admission(self, command='read', **changes):
        value=dict(command=command,kind='restore',operationId=self.identity)
        if command=='close':value.update(backupJson=json.dumps(BACKUP),passphrase=PASSWORD)
        value.update(changes);return self.controller.admission(value)

    def retained(self):
        self.assertEqual(0,self.root.native_writes)
        if self.record_before is not None:self.assertEqual(self.record_before,(self.record.read_bytes(),metadata(self.record)))

    def test_read_does_not_move_a_matching_private_pending_marker(self):
        self.seed();before=metadata(self.pending)
        self.assertTrue(self.admission()['closeAllowed']);self.assertTrue(self.pending.exists());self.assertFalse(self.archive.exists())
        self.assertEqual(before,metadata(self.pending));self.assertEqual(0,self.root.closes);self.retained()

    def test_authorized_close_moves_the_original_pending_inode_and_retains_the_private_intent(self):
        self.seed();self.assertTrue(self.admission('close')['closed'])
        self.assertFalse(self.pending.exists());self.assertEqual(self.pending_bytes,self.archive.read_bytes())
        self.assertEqual(self.pending_metadata[:8],metadata(self.archive)[:8]);self.retained()
        self.assertEqual([],self.controller.active_restore_records());self.assertIsNone(self.controller.status()['pendingRestore'])

    def test_early_pending_before_the_detailed_intent_has_the_same_authorized_retirement(self):
        self.seed(early=True);self.assertFalse(self.record.exists());self.assertTrue(self.admission('close')['closed'])
        self.assertEqual(self.pending_bytes,self.archive.read_bytes());self.assertEqual(self.pending_metadata[:8],metadata(self.archive)[:8])
        self.assertFalse(self.pending.exists());self.assertFalse(self.record.exists());self.retained()

    def test_original_id_is_never_sent_again_and_a_manual_new_restore_is_admitted_after_closure(self):
        self.seed();self.admission('close');self.assertEqual('UNKNOWN',self.controller.restore(self.value)['state'])
        self.assertEqual(1,len(self.root.records));new=str(uuid.uuid4());self.root.lose=True
        with self.assertRaises(OSError):self.controller.restore(dict(self.value,operationId=new))
        self.assertEqual({'NOT_ADMITTED','RESERVED'},{v['state'] for v in self.root.records.values()})
        self.assertEqual({self.identity,new},{v['nativeOperationId'] for v in self.root.records.values()});self.retained()

    def test_original_backup_and_password_are_required_even_with_a_matching_marker(self):
        self.seed()
        for changes in [dict(passphrase='different-password-material'),dict(backupJson=json.dumps(dict(BACKUP,encrypted='foreign')))]:
            self.controller.last_inspect=None
            with self.assertRaises(protocol.Failure):self.admission('close',**changes)
        self.assertEqual(0,self.root.closes);self.assertTrue(self.pending.exists());self.assertFalse(self.archive.exists());self.retained()

    def test_intake_with_no_native_result_does_not_release_either_private_record(self):
        self.seed();next(iter(self.root.records.values()))['state']='INTAKE'
        self.assertEqual('UNKNOWN',self.admission()['phase']);self.assertFalse(self.admission()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.admission('close')
        self.assertEqual(self.pending_bytes,self.pending.read_bytes());self.assertFalse(self.archive.exists());self.retained()

    def test_lost_root_close_reply_requires_fresh_authorization_before_marker_retirement(self):
        self.seed();self.root.lose_close=True
        with self.assertRaises(OSError):self.admission('close')
        self.assertTrue(self.pending.exists());self.assertFalse(self.archive.exists());self.assertFalse(self.admission()['closed'])
        self.root.lose_close=False;self.controller.last_inspect=None
        self.assertTrue(self.admission('close')['closed']);self.assertFalse(self.pending.exists());self.retained()

    def test_interruption_after_local_closed_receipt_keeps_the_marker_active_until_explicit_finish(self):
        self.seed()
        with patch.object(protocol,'rename_no_replace',side_effect=OSError('modeled archive interruption')):
            with self.assertRaises(OSError):self.admission('close')
        view=self.admission();self.assertEqual('NOT_ADMITTED',view['phase']);self.assertFalse(view['closed']);self.assertTrue(view['closeAllowed'])
        self.assertTrue(self.pending.exists());self.assertTrue((self.archive.parent/'closed.json').exists())
        self.controller.last_inspect=None;self.assertTrue(self.admission('close')['closed']);self.assertFalse(self.pending.exists());self.retained()

    def test_source_fsync_failure_retains_the_original_marker_and_blocks_acknowledgement(self):
        self.seed();inode=self.pending.stat().st_ino;sync=os.fsync
        def unavailable(fd):
            if os.fstat(fd).st_ino==inode:raise OSError('modeled source durability failure')
            return sync(fd)
        with patch.object(recovery.os,'fsync',side_effect=unavailable),self.assertRaises(OSError):self.admission('close')
        self.assertTrue(self.pending.exists());self.assertFalse(self.archive.exists());self.assertFalse(self.admission()['closed'])
        self.controller.last_inspect=None;self.assertTrue(self.admission('close')['closed']);self.retained()

    def test_a_lost_local_reply_after_atomic_move_is_read_from_positive_original_records(self):
        self.seed();sync=self.journal.sync
        def interrupted(directory):
            if self.archive.exists():raise OSError('modeled response loss after the move')
            return sync(directory)
        with patch.object(self.journal,'sync',side_effect=interrupted),self.assertRaises(OSError):self.admission('close')
        self.assertTrue(self.admission()['closed']);self.assertEqual(self.pending_bytes,self.archive.read_bytes());self.retained()

    def test_missing_pending_marker_for_a_detailed_intent_is_not_inferred_as_a_completed_archive(self):
        self.seed();self.pending.unlink()
        self.assertFalse(self.admission()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.admission('close')
        self.assertEqual(0,self.root.closes);self.assertFalse(self.archive.exists());self.retained()

    def test_a_foreign_or_changed_pending_marker_is_not_moved(self):
        self.seed();changed=dict(schema=1,operationId=self.identity,expectedKeySha256='a'*64)
        self.pending.write_bytes(protocol.encode(changed));before=self.pending.read_bytes()
        self.assertFalse(self.admission()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.admission('close')
        self.assertEqual(before,self.pending.read_bytes());self.assertFalse(self.archive.exists());self.retained()

    def test_a_linked_source_marker_is_refused_without_a_root_close(self):
        self.seed();os.link(self.pending,self.directory/'alias')
        with self.assertRaises(protocol.Failure):self.admission('close')
        self.assertEqual(0,self.root.closes);self.assertTrue(self.pending.exists());self.assertFalse(self.archive.exists());self.retained()

    def test_private_start_children_block_parent_retirement_even_with_distinct_operation_ids(self):
        self.seed();child=str(uuid.uuid4());self.journal.write_new(self.journal.starts/(child+'.json'),
            dict(schema=1,operationId=child,restoreOperationId=self.identity,expectedKeySha256=SHA))
        self.assertFalse(self.admission()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.admission('close')
        self.assertEqual(0,self.root.closes);self.assertTrue(self.pending.exists());self.retained()

    def test_changed_root_namespace_keeps_a_retired_private_intent_unresolved(self):
        self.seed();self.admission('close');self.root.namespace='d'*64
        self.assertEqual([self.intent],self.controller.active_restore_records())
        with self.assertRaises(protocol.Failure):self.controller.restore(dict(self.value,operationId=str(uuid.uuid4())))
        self.assertEqual(1,len(self.root.records));self.retained()

    def test_a_broken_or_recreated_retirement_marker_is_not_silently_repaired(self):
        self.seed();self.admission('close');self.archive.write_bytes(b'{')
        with self.assertRaises(protocol.Failure):self.admission()
        self.assertEqual(b'{',self.archive.read_bytes());self.assertFalse(self.pending.exists())

    def test_no_replace_move_does_not_overwrite_either_original(self):
        self.seed();self.journal.write_new(self.archive,dict(schema=1,operationId=self.identity,expectedKeySha256=SHA))
        with self.assertRaises(protocol.Failure):self.journal.retire_pending(self.archive,dict(schema=1,operationId=self.identity,expectedKeySha256=SHA))
        self.assertEqual(self.pending_bytes,self.pending.read_bytes());self.assertEqual(self.pending_bytes,self.archive.read_bytes());self.retained()

    def test_disappearance_during_a_private_read_is_not_treated_as_absence(self):
        self.seed();read=os.read
        def disappearing(fd,limit):
            value=read(fd,limit);self.record.unlink();return value
        with patch.object(recovery.os,'read',side_effect=disappearing),self.assertRaises(protocol.Failure) as found:self.journal.record(self.identity)
        self.assertEqual('UNSAFE_JOURNAL',found.exception.reason)

    def test_retired_records_still_count_toward_the_bounded_history_capacity(self):
        self.seed();self.admission('close')
        with patch.object(recovery,'MAX_OPERATIONS',1),self.assertRaises(protocol.Failure) as found:
            self.controller.restore(dict(self.value,operationId=str(uuid.uuid4())))
        self.assertEqual('CAPACITY',found.exception.reason);self.assertEqual(1,len(self.root.records));self.retained()


@unittest.skipUnless(sys.platform=='linux' and os.geteuid()==0,'Installer permission model needs Linux root')
class RetiredRestorePackageGateTest(unittest.TestCase):
    def setUp(self):
        self.model=root_models.SenderAdmissionsTest();self.model.setUp();self.addCleanup(self.model.doCleanups)
        self.policy=self.model.fixture.policy;self.manager=self.model.manager;request=self.model.request('recovery')
        self.model.reserve(request);self.model.read(request,close=True);self.request=request;native=self.model.original(request)
        self.identity=native['operationId'];self.intent=dict(schema=1,operationId=self.identity,expectedKeySha256='1'*64,backupSha256='2'*64)
        self.attempt=dict(schema=1,purpose='yofc.kura.sender-attempt.v1',admissionId=request['admissionId'],kind='restore',nativeOperationId=self.identity,
            request=dict(schema=1,action='restore',operationId=self.identity,expectedKeySha256='1'*64,backupSha256='2'*64))
        self.state=self.policy.path('/var/lib/kura-key-recovery');self.state.mkdir(mode=0o700)
        for name in ['operations','starts','admissions']:(self.state/name).mkdir(mode=0o700)
        self.slot=self.state/'admissions'/(self.identity+'-restore');self.slot.mkdir(mode=0o700)
        self.write(self.state/'admission.lock',b'');self.write(self.slot/'intent.json',self.attempt)
        self.write(self.slot/'namespace.json',dict(schema=1,namespaceSha256=request['namespaceSha256']))
        self.write(self.slot/'closed.json',dict(schema=1,purpose='yofc.kura.sender-not-admitted.v1',admissionId=request['admissionId'],
            kind='restore',nativeOperationId=self.identity,namespaceSha256=request['namespaceSha256']))
        self.write(self.slot/'pending.json',dict(schema=1,operationId=self.identity,expectedKeySha256='1'*64))
        self.local=self.state/'operations'/(self.identity+'.json');self.write(self.local,self.intent)
        for path in [self.state,*self.state.rglob('*')]:os.chown(path,self.model.recovery,self.model.recovery)

    def write(self,path,value):
        path.write_bytes(value if isinstance(value,bytes) else lifecycle.encoded(value));path.chmod(0o600)

    def check(self):
        def account(name):return SimpleNamespace(pw_uid=self.model.recovery if name=='kura-key-recovery' else self.model.core,
            pw_gid=self.model.recovery,pw_shell='/usr/sbin/nologin')
        with patch.object(lifecycle.pwd,'getpwnam',side_effect=account),self.policy.recovery_locked():pass

    def test_exact_retired_restore_is_read_without_changing_its_originals(self):
        before=self.model.fixture.snapshot();self.check();self.assertEqual(before,self.model.fixture.snapshot())

    def test_early_marker_archive_without_a_detailed_intent_is_accepted_without_recreating_it(self):
        self.local.unlink();before=self.model.fixture.snapshot();self.check();self.assertEqual(before,self.model.fixture.snapshot())

    def test_missing_or_conflicting_retirement_marker_does_not_release_the_restore(self):
        path=self.slot/'pending.json';path.unlink()
        with self.assertRaises((lifecycle.Refused,OSError)):self.check()
        self.write(path,dict(schema=True,operationId=self.identity,expectedKeySha256='1'*64));os.chown(path,self.model.recovery,self.model.recovery)
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_root_intake_or_a_native_original_cannot_be_hidden_by_a_retired_marker(self):
        original=self.manager.sender_admissions.load(self.request['admissionId']);self.manager.sender_admissions.write(dict(original,state='INTAKE'))
        with self.assertRaises(lifecycle.Refused):self.check()
        self.manager.sender_admissions.write(original)
        self.model.fixture.fixture.write(self.manager.operations/(self.identity+'.json'),b'{}',0o600)
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_duplicate_active_pending_and_private_start_children_are_refused(self):
        pending=self.state/'pending.json';self.write(pending,dict(schema=1,operationId=self.identity,expectedKeySha256='1'*64));os.chown(pending,self.model.recovery,self.model.recovery)
        with self.assertRaises(lifecycle.Refused):self.check()
        pending.unlink();child=self.state/'starts'/(str(uuid.uuid4())+'.json')
        self.write(child,dict(schema=1,operationId=child.stem,restoreOperationId=self.identity,expectedKeySha256='1'*64));os.chown(child,self.model.recovery,self.model.recovery)
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_changed_private_restore_or_wrong_root_target_is_refused(self):
        self.write(self.local,dict(self.intent,backupSha256='a'*64))
        with self.assertRaises(lifecycle.Refused):self.check()
        self.write(self.local,self.intent)
        root=self.manager.sender_admissions.load(self.request['admissionId']);root['target']=dict(root['target'],action='backup-create')
        self.manager.sender_admissions.write(root)
        with self.assertRaises(lifecycle.Refused):self.check()


if __name__=='__main__':unittest.main()
