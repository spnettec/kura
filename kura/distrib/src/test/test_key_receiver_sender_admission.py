#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Receiver attempt/RPC boundaries; Root responses modeled, no key or service mutation."""
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/bin'))
import kura_key_recovery as recovery
import kura_key_service as protocol


class ReceiverSenderAdmissionTest(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='receiver-sender-admission-');self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name);self.journal=recovery.Journal(self.path)
        self.reservations=0;self.writes=[];self.lost=False;self.existing=False;self.bad=False
        self.sender=recovery.SenderAdmission(self.client,self.journal)
        self.identity=str(uuid.uuid4());self.request=dict(schema=1,action='restore',operationId=self.identity,
            expectedKeySha256='1'*64,backup=dict(format=protocol.FORMAT,operationId=str(uuid.uuid4()),encrypted='YQ=='),
            passphrase='synthetic-recovery-password')

    def client(self,request):
        wire=recovery.SenderAdmission.wrap(request)
        if wire['action']=='gwt-sender-namespace':
            return dict(schema=1,namespaceSha256='a'*64,rootDevice='1',rootInode='9')
        if wire['action']=='sender-reserve':
            self.reservations+=1
            if self.lost:raise OSError('Root reservation response lost')
            self.last_admission=wire['admissionId'];target=wire['request'];action=target['action']
            if action=='generation-handoff-command':action='generation-core-start' if target['command']=='start' else 'generation-publish'
            return dict(schema=1,admissionId=wire['admissionId'],state='RESERVED',source='recovery',namespaceSha256='a'*64,
                nativeOperationId=self.identity,nativeAction='core-start' if self.bad else action,newlyReserved=not self.existing)
        if protocol.sender_mutation(request):
            self.assertEqual('sender-command',wire['action']);self.assertEqual(self.last_admission,wire['admissionId'])
            self.assertEqual(request,wire['request']);self.writes.append(wire);return dict(schema=1,state='MODEL')
        return dict(schema=1,state='READ_ONLY_MODEL')

    def test_root_reservation_precedes_the_private_key_intent_and_forward(self):
        def forward():
            self.assertEqual(1,self.reservations);self.assertEqual([],list(self.journal.operations.iterdir()))
            self.journal.admit(dict(schema=1,operationId=self.identity,expectedKeySha256='1'*64,backupSha256='2'*64))
            return self.client(self.request)
        result=self.sender.submit('restore',self.identity,self.request,forward)
        self.assertEqual('MODEL',result['state']);self.assertEqual(1,len(self.writes))
        for file in self.path.rglob('*'):
            if file.is_file():self.assertNotIn(b'synthetic-recovery-password',file.read_bytes());self.assertNotIn(b'YQ==',file.read_bytes())
        self.assertIsNone(recovery.SenderAdmission.context.current)

    def test_reservation_loss_consumes_the_attempt_without_creating_key_intent_or_retry(self):
        self.lost=True;callbacks=[]
        with self.assertRaises(OSError):self.sender.submit('restore',self.identity,self.request,lambda:callbacks.append(1))
        self.lost=False
        with self.assertRaises(protocol.Failure):self.sender.submit('restore',self.identity,self.request,lambda:callbacks.append(1))
        self.assertEqual([],callbacks);self.assertEqual(1,self.reservations);self.assertEqual([],list(self.journal.operations.iterdir()))

    def test_existing_or_wrong_root_permission_never_runs_a_writer(self):
        self.existing=True;callbacks=[]
        with self.assertRaises(protocol.Failure):self.sender.submit('restore',self.identity,self.request,lambda:callbacks.append(1))
        self.assertEqual([],callbacks)
        self.identity=str(uuid.uuid4());self.request['operationId']=self.identity;self.existing=False;self.bad=True
        with self.assertRaises(protocol.Failure):self.sender.submit('restore',self.identity,self.request,lambda:callbacks.append(1))
        self.assertEqual([],callbacks)

    def test_changed_request_is_not_wrapped_and_scope_clears_after_native_failure(self):
        changed=dict(self.request,passphrase='changed')
        def forward():
            with self.assertRaises(protocol.Failure):recovery.SenderAdmission.wrap(changed)
            raise OSError('native reply lost')
        with self.assertRaises(OSError):self.sender.submit('restore',self.identity,self.request,forward)
        self.assertIsNone(recovery.SenderAdmission.context.current);self.assertEqual(self.request,recovery.SenderAdmission.wrap(self.request))

    def test_original_handoff_queries_are_not_mutations_or_intakes(self):
        def forward():
            for command in ('info','publication-read','start-read'):
                value=dict(schema=1,action='generation-handoff-command',command=command,token='synthetic-read-token')
                self.assertFalse(protocol.sender_mutation(value));self.assertEqual(value,recovery.SenderAdmission.wrap(value))
            value=dict(schema=1,action='operation-read',operationId=self.identity)
            self.assertEqual(value,recovery.SenderAdmission.wrap(value))
        self.sender.submit('restore',self.identity,self.request,forward);self.assertEqual([],self.writes)

    def test_fixed_publication_and_continuation_have_separate_attempts_without_storing_bearer(self):
        token='KURA-HANDOFF-1.'+str(uuid.uuid4())+'.'+'b'*64
        publish=dict(schema=1,action='generation-handoff-command',token=token,command='publish')
        self.sender.submit('publish',self.identity,publish,lambda:self.client(publish))
        continuation=dict(publish,command='continue',expectedRecoveryReceiptSha256='c'*64)
        self.sender.submit('continue',self.identity,continuation,lambda:self.client(continuation))
        self.assertEqual(2,len(self.writes));self.assertNotEqual(self.writes[0]['admissionId'],self.writes[1]['admissionId'])
        for file in self.sender.directory.rglob('*'):
            if file.is_file():self.assertNotIn(token.encode(),file.read_bytes())


if __name__=='__main__':unittest.main()
