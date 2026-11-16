#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Original startup closure only. Native execution, decryption and Main are models."""
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


class ReceiverStartSettlementTest(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='kura-unsent-start-settlement-');self.addCleanup(temporary.cleanup)
        self.directory=Path(temporary.name);self.directory.chmod(0o700)
        self.root=AdmissionRoot();self.journal=recovery.Journal(self.directory)
        self.sender=recovery.SenderAdmission(self.root,self.journal);self.controller=recovery.Controller(self.root,self.journal,self.sender)
        self.identity=str(uuid.uuid4());self.restore_id=str(uuid.uuid4());self.root.cold.key_ready=True
        self.journal.admit(dict(schema=1,operationId=self.restore_id,expectedKeySha256=SHA,
            backupSha256=hashlib.sha256(protocol.encode(BACKUP)).hexdigest()))
        self.journal.mark(self.restore_id,SHA)
        self.root.cold.records[self.restore_id]=dict(schema=1,operationId=self.restore_id,state='SUCCEEDED',
            action='restore',keySha256=SHA,keyChanged=True,existingReceiptPreserved=True)
        self.value=dict(operationId=self.identity,restoreOperationId=self.restore_id,expectedKeySha256=SHA)

    def seed(self, *, maintenance=False):
        request=dict(schema=1,action='core-start-after-maintenance' if maintenance else 'core-start',**self.value)
        if maintenance:
            request.update(predecessorStartOperationId=str(uuid.uuid4()),maintenanceId=str(uuid.uuid4()),manifestSha256='a'*64)
        self.intent=dict(schema=2 if maintenance else 1,**{key:value for key,value in request.items() if key not in ('schema','action')})
        self.path=self.journal.starts/(self.identity+'.json');self.root.lose=False
        def before_native():
            self.journal.write_new(self.path,self.intent)
            raise OSError('modeled process loss after private startup intent, before the Root command')
        with self.assertRaises(OSError):self.sender.submit('start',self.identity,request,before_native)
        self.original=self.path.read_bytes();self.original_stat=self.path.stat()

    def admission(self,command='read',**extra):
        value=dict(command=command,kind='start',operationId=self.identity)
        if command=='close':value.update(backupJson=json.dumps(BACKUP),passphrase=PASSWORD)
        value.update(extra);return self.controller.admission(value)

    def retained(self):
        self.assertEqual(self.original,self.path.read_bytes())
        self.assertEqual(self.original_stat,self.path.stat())
        self.assertEqual(0,self.root.native_writes)

    def test_positive_original_close_retains_the_private_start_intent_and_pending_restore(self):
        self.seed();pending=(self.directory/'pending.json').read_bytes()
        self.assertTrue(self.admission()['closeAllowed']);self.assertEqual(0,self.root.closes)
        self.assertTrue(self.admission('close')['closed']);self.retained()
        self.assertEqual(pending,(self.directory/'pending.json').read_bytes())
        self.assertEqual([],self.controller.active_start_records())
        status=self.controller.status();self.assertIsNone(status['pendingStart']);self.assertEqual(self.restore_id,status['pendingRestore']['operationId'])

    def test_restart_and_a_manual_new_start_do_not_reuse_or_delete_the_old_operation(self):
        self.seed();self.admission('close')
        restarted=recovery.Controller(self.root,recovery.Journal(self.directory))
        self.assertEqual([],restarted.active_start_records())
        self.assertEqual('UNKNOWN',restarted.start(self.value)['state'])
        self.assertEqual(1,len(self.root.records))
        new_id=str(uuid.uuid4());self.root.lose=True
        with self.assertRaises(OSError):restarted.start(dict(self.value,operationId=new_id))
        self.assertEqual({'NOT_ADMITTED','RESERVED'},{r['state'] for r in self.root.records.values()})
        self.assertEqual({self.identity,new_id},{r['nativeOperationId'] for r in self.root.records.values()})
        self.assertFalse((self.journal.starts/(new_id+'.json')).exists());self.retained()

    def test_matching_private_start_still_requires_the_original_backup_and_password(self):
        self.seed()
        for material in [dict(passphrase='different-valid-length-password'),dict(backupJson=json.dumps(dict(BACKUP,encrypted='foreign')))]:
            self.controller.last_inspect=None
            with self.assertRaises(protocol.Failure):self.admission('close',**material)
        self.assertEqual(0,self.root.closes);self.retained()

    def test_intaken_start_without_a_native_original_remains_unknown(self):
        self.seed();next(iter(self.root.records.values()))['state']='INTAKE'
        self.assertFalse(self.admission()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.admission('close')
        self.assertEqual([self.intent],self.controller.active_start_records());self.assertEqual(0,self.root.closes);self.retained()

    def test_different_private_start_metadata_cannot_use_the_original_reservation(self):
        self.seed();changed=dict(self.intent,restoreOperationId=str(uuid.uuid4()));self.path.write_bytes(protocol.encode(changed))
        self.assertFalse(self.admission()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.admission('close')
        self.assertEqual(0,self.root.closes);self.assertEqual(protocol.encode(changed),self.path.read_bytes())

    def test_another_private_sender_kind_blocks_closure_of_the_same_start_uuid(self):
        self.seed();self.journal.admit(dict(schema=1,operationId=self.identity,expectedKeySha256=SHA,backupSha256='a'*64))
        self.assertFalse(self.admission()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.admission('close')
        self.assertEqual(0,self.root.closes);self.retained()

    def test_early_pending_and_handoff_bindings_cannot_be_ignored_as_a_start_intent(self):
        self.seed();pending=self.directory/'pending.json';before=pending.read_bytes()
        pending.write_bytes(protocol.encode(dict(schema=1,operationId=self.identity,expectedKeySha256=SHA)))
        self.assertFalse(self.admission()['closeAllowed']);pending.write_bytes(before)
        handoff=recovery.HandoffController(self.root,self.journal,self.sender);info=dict(self.root.handoff.info,startOperationId=self.identity)
        slot=handoff.directory/info['handoffId'];slot.mkdir(mode=0o700);self.journal.write_new(slot/'binding.json',handoff.binding(info))
        self.assertFalse(self.admission()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.admission('close')
        self.assertEqual(0,self.root.closes);self.retained()

    def test_lost_close_reply_keeps_the_private_start_active_until_explicit_completion(self):
        self.seed();self.root.lose_close=True
        with self.assertRaises(OSError):self.admission('close')
        self.assertEqual([self.intent],self.controller.active_start_records());self.assertFalse(self.admission()['closed'])
        self.root.lose_close=False;self.controller.last_inspect=None
        self.assertTrue(self.admission('close')['closed']);self.assertEqual([],self.controller.active_start_records());self.retained()

    def test_foreign_root_namespace_does_not_release_a_previously_closed_start(self):
        self.seed();self.admission('close');self.root.namespace='d'*64
        self.assertEqual([self.intent],self.controller.active_start_records())
        with self.assertRaises(protocol.Failure):self.controller.start(dict(self.value,operationId=str(uuid.uuid4())))
        self.assertEqual(1,len(self.root.records));self.retained()

    def test_a_changed_closed_private_record_or_unexpected_native_result_cannot_release_admission(self):
        self.seed();self.admission('close');self.path.write_bytes(protocol.encode(dict(self.intent,expectedKeySha256='a'*64)))
        self.assertFalse(self.admission()['closed']);self.assertFalse(self.admission()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.controller.active_start_records()
        self.path.write_bytes(self.original);call=self.controller.call
        def unexpected(action,**fields):return dict(schema=1,state='SUCCEEDED') if action=='core-start-read' else call(action,**fields)
        with patch.object(self.controller,'call',side_effect=unexpected),self.assertRaises(protocol.Failure):self.controller.active_start_records()
        self.assertEqual(self.original,self.path.read_bytes());self.assertEqual(0,self.root.native_writes)

    def test_a_later_conflicting_private_kind_blocks_acknowledgement_of_an_old_closure(self):
        self.seed();self.admission('close')
        self.journal.admit(dict(schema=1,operationId=self.identity,expectedKeySha256=SHA,backupSha256='a'*64))
        current=self.admission();self.assertFalse(current['closed']);self.assertFalse(current['closeAllowed'])
        self.assertEqual([self.intent],self.controller.active_start_records());self.retained()

    def test_maintenance_metadata_is_preserved_and_bound_in_full(self):
        self.seed(maintenance=True);self.assertTrue(self.admission()['closeAllowed'])
        self.assertTrue(self.admission('close')['closed']);self.assertEqual([],self.controller.active_start_records());self.retained()
        self.path.write_bytes(protocol.encode(dict(self.intent,manifestSha256='b'*64)))
        with self.assertRaises(protocol.Failure):self.controller.active_start_records()

    def test_closed_private_records_still_consume_the_bounded_history_capacity(self):
        self.seed();self.admission('close')
        with patch.object(recovery,'MAX_OPERATIONS',1),self.assertRaises(protocol.Failure) as caught:
            self.controller.start(dict(self.value,operationId=str(uuid.uuid4())))
        self.assertEqual('CAPACITY',caught.exception.reason);self.assertEqual(1,len(self.root.records));self.retained()


@unittest.skipUnless(sys.platform=='linux' and os.geteuid()==0,'Package-reader ownership model needs Linux root')
class ClosedStartPackageGateTest(unittest.TestCase):
    def setUp(self):
        self.model=root_models.SenderAdmissionsTest();self.model.setUp();self.addCleanup(self.model.doCleanups)
        self.policy=self.model.fixture.policy;self.manager=self.model.manager
        self.identity=str(uuid.uuid4());restore=str(uuid.uuid4());request=self.model.request('recovery',self.identity)
        request['request']=dict(schema=1,action='core-start',operationId=self.identity,restoreOperationId=restore,expectedKeySha256=SHA)
        self.model.reserve(request);self.model.read(request,close=True)
        self.request=request;self.attempt=dict(schema=1,purpose='yofc.kura.sender-attempt.v1',admissionId=request['admissionId'],
            kind='start',nativeOperationId=self.identity,request=request['request'])
        self.namespace=dict(schema=1,namespaceSha256=request['namespaceSha256'])
        self.state=self.policy.path('/var/lib/kura-key-recovery');self.state.mkdir(mode=0o700)
        for name in ['operations','starts','admissions']:(self.state/name).mkdir(mode=0o700)
        self.slot=self.state/'admissions'/(self.identity+'-start');self.slot.mkdir(mode=0o700)
        self.write(self.state/'admission.lock',b'')
        self.write(self.slot/'intent.json',self.attempt);self.write(self.slot/'namespace.json',self.namespace)
        self.write(self.slot/'closed.json',dict(schema=1,purpose='yofc.kura.sender-not-admitted.v1',
            admissionId=request['admissionId'],kind='start',nativeOperationId=self.identity,namespaceSha256=request['namespaceSha256']))
        self.local=self.state/'starts'/(self.identity+'.json');self.intent=dict(schema=1,operationId=self.identity,restoreOperationId=restore,expectedKeySha256=SHA)
        self.write(self.local,self.intent)
        backup_sha=hashlib.sha256(protocol.encode(BACKUP)).hexdigest()
        self.write(self.state/'operations'/(restore+'.json'),dict(schema=1,operationId=restore,expectedKeySha256=SHA,backupSha256=backup_sha))
        self.write(self.state/'pending.json',dict(schema=1,operationId=restore,expectedKeySha256=SHA))
        self.model.fixture.root_result(restore,'restore',dict(schema=1,operationId=restore,state='SUCCEEDED',
            action='restore',keySha256=SHA,keyChanged=True,existingReceiptPreserved=True))
        for path in [self.state,*self.state.rglob('*')]:os.chown(path,self.model.recovery,self.model.recovery)

    def write(self,path,value):
        raw=value if isinstance(value,bytes) else lifecycle.encoded(value)
        path.write_bytes(raw);path.chmod(0o600)

    def check(self):
        def account(name):return SimpleNamespace(pw_uid=self.model.recovery if name=='kura-key-recovery' else self.model.core,
            pw_gid=self.model.recovery,pw_shell='/usr/sbin/nologin')
        with patch.object(lifecycle.pwd,'getpwnam',side_effect=account),self.policy.recovery_locked():pass

    def test_exact_closed_start_is_read_only_and_needs_no_native_startup(self):
        before=self.model.fixture.snapshot();self.check()
        self.assertEqual(before,self.model.fixture.snapshot());self.assertFalse((self.policy.state/'startups'/(self.identity+'.json')).exists())

    def test_root_not_admitted_without_a_local_closed_receipt_cannot_release_a_private_start(self):
        (self.slot/'closed.json').unlink()
        with self.assertRaises((lifecycle.Refused,OSError)):self.check()
        self.assertTrue(self.local.exists())

    def test_root_intake_is_not_settled_by_the_local_closed_receipt(self):
        admission=self.manager.sender_admissions.load(self.request['admissionId'])
        self.manager.sender_admissions.write(dict(admission,state='INTAKE'))
        with self.assertRaises(lifecycle.Refused):self.check()
        self.assertTrue(self.local.exists())

    def test_complete_start_request_and_private_metadata_must_match_the_authenticated_root(self):
        self.write(self.local,dict(self.intent,expectedKeySha256='a'*64))
        with self.assertRaises(lifecycle.Refused):self.check()
        self.write(self.local,self.intent)
        changed=dict(self.attempt,request=dict(self.attempt['request'],expectedKeySha256='a'*64))
        self.write(self.slot/'intent.json',changed);self.write(self.local,dict(self.intent,expectedKeySha256='a'*64))
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_unexpected_native_or_linked_private_intent_is_not_hidden(self):
        path=self.policy.state/'startups'/(self.identity+'.json');self.model.fixture.fixture.write(path,b'{}',0o600)
        with self.assertRaises(lifecycle.Refused):self.check()
        path.unlink();os.link(self.local,self.model.fixture.fixture.root/'startup-alias')
        with self.assertRaises(lifecycle.Refused):self.check()


if __name__=='__main__':unittest.main()
