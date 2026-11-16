#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""New receiver reservation recovery; Root authority, decryption and native results modeled."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/bin'))
import kura_key_recovery as recovery
from test_key_recovery import FakeRoot, BACKUP, PASSWORD, SHA
from test_key_handoff_recovery import Root as HandoffRoot
protocol=recovery.protocol


class AdmissionRoot:
    def __init__(self):
        self.cold=FakeRoot();self.handoff=HandoffRoot();self.namespace='c'*64;self.records={};self.calls=[]
        self.lose=True;self.lose_close=False;self.native_writes=0;self.closes=0

    def __call__(self,request):
        self.calls.append(request['action']);action=request['action']
        if action=='gwt-sender-namespace':return dict(schema=1,namespaceSha256=self.namespace,rootDevice='1',rootInode='9')
        if action=='sender-reserve':
            native=request['request'];handoff=native['action']=='generation-handoff-command'
            identity=self.handoff.info['startOperationId' if native.get('command')=='start' else 'publicationId'] if handoff else native['operationId']
            reply=dict(schema=1,admissionId=request['admissionId'],source='recovery',namespaceSha256=self.namespace,
                nativeOperationId=identity,nativeAction=('generation-core-start' if native.get('command')=='start' else 'generation-publish') if handoff else native['action'],state='RESERVED',newlyReserved=True)
            self.records[request['admissionId']]=reply
            if self.lose:raise OSError('modeled lost reservation reply')
            return copy.deepcopy(reply)
        if action in ('sender-admission-read','sender-admission-close'):
            record=self.records[request['admissionId']]
            if action.endswith('-close'):
                protocol.require(record['state'] in ('RESERVED','NOT_ADMITTED'),'UNRESOLVED_OPERATION')
                self.closes+=1;record['state']='NOT_ADMITTED'
                if self.lose_close:raise OSError('modeled lost close reply')
            return dict(record,newlyReserved=False)
        if action=='sender-command' or protocol.sender_mutation(request):
            self.native_writes+=1;raise AssertionError('Metadata recovery must not invoke a native writer')
        if action=='generation-handoff-command':
            if request.get('token')!=self.handoff.token:return dict(schema=1,error='FORBIDDEN')
            return self.handoff(request)
        if action=='core-start-read':return dict(schema=1,state='NOT_FOUND')
        if action=='core-start-plan':return dict(schema=1,state='START_PLAN',startAllowed=False,maintenanceId=None,
            predecessorStartOperationId=None,manifestSha256=None,blockingOperationId=None)
        return self.cold(request)


class ReceiverAdmissionRecoveryTest(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='kura-receiver-reservation-recovery-');self.addCleanup(temporary.cleanup)
        self.directory=Path(temporary.name);self.directory.chmod(0o700);self.root=AdmissionRoot();self.journal=recovery.Journal(self.directory)
        self.sender=recovery.SenderAdmission(self.root,self.journal);self.controller=recovery.Controller(self.root,self.journal,self.sender)
        self.identity=str(uuid.uuid4());self.request=dict(schema=1,action='restore',operationId=self.identity,expectedKeySha256=SHA,backup=BACKUP,passphrase=PASSWORD)

    def seed(self,kind='restore',request=None,identity=None):
        with self.assertRaises(OSError):self.sender.submit(kind,identity or self.identity,request or self.request,lambda:self.fail('Lost reservation cannot create a key intent'))

    def view(self,command='read',**extra):
        value=dict(command=command,kind='restore',operationId=self.identity,**extra)
        if command=='close':value.update(backupJson=json.dumps(BACKUP),passphrase=PASSWORD)
        return self.controller.admission(value)

    def files(self):return {str(p.relative_to(self.directory)):p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}

    def test_read_does_not_close_and_authorized_close_retains_original_attempt_without_key_intent(self):
        self.seed();before=self.files();self.assertTrue(self.view()['closeAllowed']);self.assertEqual(before,self.files());self.assertEqual(0,self.root.closes)
        result=self.view('close');self.assertEqual('NOT_ADMITTED',result['phase']);self.assertTrue(result['closed']);self.assertFalse(result['closeAllowed'])
        self.assertEqual([],list(self.journal.operations.iterdir()));self.assertEqual(0,self.root.native_writes)
        for name,raw in before.items():self.assertEqual(raw,self.files()[name])
        with self.assertRaises(protocol.Failure):self.sender.submit('restore',self.identity,self.request,lambda:self.fail('closed original writer'))

    def test_backup_and_password_are_both_authorization_material_not_cookie_or_uuid(self):
        self.seed()
        for extra in ({},dict(backupJson=json.dumps(BACKUP),passphrase='wrong-password-material'),dict(backupJson=json.dumps(dict(BACKUP,encrypted='foreign')),passphrase=PASSWORD)):
            self.controller.last_inspect=None
            with self.assertRaises(protocol.Failure):self.controller.admission(dict(command='close',kind='restore',operationId=self.identity,**extra))
        self.assertEqual(0,self.root.closes);self.assertFalse(self.view()['closed']);self.assertEqual(0,self.root.native_writes)

    def test_a_matching_backup_cannot_authorize_a_foreign_retained_key(self):
        self.seed();self.sender.load('restore',self.identity)
        original=self.root.cold.__class__.__call__
        def foreign(root,request):
            value=original(root,request)
            if request['action']=='backup-inspect':value['sameDeviceKey']=False
            return value
        from unittest.mock import patch
        with patch.object(FakeRoot,'__call__',foreign),self.assertRaises(protocol.Failure):self.view('close')
        self.assertEqual(0,self.root.closes)

    def test_close_reply_loss_needs_fresh_read_and_explicit_idempotent_metadata_close(self):
        self.seed();self.root.lose_close=True
        with self.assertRaises(OSError):self.view('close')
        self.assertFalse(self.view()['closed']);self.assertTrue(self.view()['closeAllowed']);self.assertEqual('NOT_ADMITTED',self.view()['phase'])
        self.root.lose_close=False;self.controller.last_inspect=None
        self.assertTrue(self.view('close')['closed']);self.assertEqual(2,self.root.closes);self.assertEqual(0,self.root.native_writes)

    def test_intake_or_private_key_intent_cannot_close_or_turn_into_no_dispatch(self):
        self.seed();record=next(iter(self.root.records.values()));record['state']='INTAKE'
        self.assertEqual('UNKNOWN',self.view()['phase']);self.assertFalse(self.view()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.view('close')
        record['state']='RESERVED';self.journal.admit(dict(schema=1,operationId=self.identity,expectedKeySha256=SHA,backupSha256=hashlib.sha256(protocol.encode(BACKUP)).hexdigest()))
        self.assertFalse(self.view()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.view('close')
        self.assertEqual(0,self.root.closes)

    def test_foreign_namespace_malformed_reply_or_torn_attempt_never_enables_close(self):
        self.seed();self.root.namespace='d'*64;self.assertEqual('UNKNOWN',self.view()['phase'])
        with self.assertRaises(protocol.Failure):self.view('close')
        self.root.namespace='c'*64;next(iter(self.root.records.values()))['nativeAction']='core-start';self.assertEqual('UNKNOWN',self.view()['phase'])
        path=self.sender.path('restore',self.identity)/'intent.json';path.write_bytes(b'{')
        with self.assertRaises(protocol.Failure):self.view()
        self.assertEqual(b'{',path.read_bytes());self.assertEqual(0,self.root.closes)

    def test_another_private_sender_kind_cannot_hide_behind_a_restore_reservation(self):
        self.seed();self.journal.write_new(self.journal.starts/(self.identity+'.json'),
            dict(schema=1,operationId=self.identity,restoreOperationId=str(uuid.uuid4()),expectedKeySha256=SHA))
        self.assertFalse(self.view()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.view('close')
        self.assertEqual(0,self.root.closes)

    def test_pending_marker_before_detailed_restore_intent_with_root_intake_remains_query_only(self):
        self.seed();self.journal.mark(self.identity,SHA)
        next(iter(self.root.records.values()))['state']='INTAKE'
        self.assertFalse(self.view()['closeAllowed'])
        with self.assertRaises(protocol.Failure):self.view('close')
        self.assertEqual(0,self.root.closes);self.assertEqual(self.identity,self.journal.pending()['operationId'])

    def test_torn_handoff_first_binding_cannot_be_treated_as_no_sender_intent(self):
        handoff=recovery.HandoffController(self.root,self.journal,self.sender);info=self.root.handoff.info
        slot=handoff.directory/info['handoffId'];slot.mkdir(mode=0o700);self.journal.write_new(slot/'binding.json',handoff.binding(info))
        for key in ('publicationId','startOperationId'):self.assertTrue(self.sender.has_key_intent(info[key]))

    def test_start_close_requires_the_original_restore_backup_even_while_the_key_is_present(self):
        restore=str(uuid.uuid4());self.journal.admit(dict(schema=1,operationId=restore,expectedKeySha256=SHA,backupSha256=hashlib.sha256(protocol.encode(BACKUP)).hexdigest()))
        request=dict(schema=1,action='core-start',operationId=self.identity,restoreOperationId=restore,expectedKeySha256=SHA)
        self.seed('start',request);self.root.cold.key_ready=True
        value=self.controller.admission(dict(command='close',kind='start',operationId=self.identity,backupJson=json.dumps(BACKUP),passphrase=PASSWORD))
        self.assertTrue(value['closed']);self.assertEqual(restore,value['restoreOperationId']);self.assertEqual([],list(self.journal.starts.iterdir()));self.assertEqual(0,self.root.native_writes)

    def test_closed_receipt_cannot_be_moved_to_another_attempt_or_overwritten(self):
        self.seed();self.view('close');path=self.sender.path('restore',self.identity)/'closed.json';value=json.loads(path.read_bytes());value['admissionId']=str(uuid.uuid4());path.write_bytes(protocol.encode(value));before=path.read_bytes()
        with self.assertRaises(protocol.Failure):self.view()
        self.assertEqual(before,path.read_bytes())

    def test_handoff_close_requires_original_bearer_and_never_reuses_fixed_native_ids(self):
        handoff=recovery.HandoffController(self.root,self.journal,self.sender);token=self.root.handoff.token;identity=self.root.handoff.info['publicationId']
        self.seed('publish',dict(schema=1,action='generation-handoff-command',token=token,command='publish'),identity)
        query=dict(command='admission-read',step='publish',token=token);self.assertTrue(handoff.execute(query)['closeAllowed'])
        with self.assertRaises((AssertionError,protocol.Failure)):handoff.execute(dict(query,command='admission-close',token=token[:-1]+'b'))
        self.assertTrue(handoff.execute(dict(query,command='admission-close'))['closed']);self.assertFalse(handoff.execute(dict(command='query',token=token))['allowed']['publish'])
        with self.assertRaises(protocol.Failure):handoff.execute(dict(command='publish',token=token))
        self.assertEqual(0,self.root.native_writes)

    def test_authenticated_continuation_is_query_only_not_an_absent_native_original(self):
        handoff=recovery.HandoffController(self.root,self.journal,self.sender);token=self.root.handoff.token;identity=self.root.handoff.info['publicationId']
        self.seed('continue',dict(schema=1,action='generation-handoff-command',token=token,command='continue',expectedRecoveryReceiptSha256='a'*64),identity)
        query=dict(command='admission-read',step='continue',token=token);self.assertFalse(handoff.execute(query)['closeAllowed'])
        with self.assertRaises(protocol.Failure):handoff.execute(dict(query,command='admission-close'))
        self.assertEqual(0,self.root.closes)


if __name__=='__main__':unittest.main()
