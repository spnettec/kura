#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Actual private bytes/HMAC/package reads; native outcomes/Main/systemd are explicit models."""
import copy
import hashlib
import os
from pathlib import Path
import secrets
import sys
import unittest
from unittest.mock import patch
import uuid

import test_key_private_fences as original

service=original.service
lifecycle=original.lifecycle


@unittest.skipUnless(sys.platform=='linux','Root metadata publication requires Linux renameat2')
class GwtPrivateArchiveTest(unittest.TestCase):
    def setUp(self):
        self.base=original.PrivateFenceTest();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.fixture=self.base.fixture;self.manager=self.base.manager;self.shared=self.base.shared
        self.data=self.fixture.data;self.namespace=self.fixture.binding['namespaceSha256']

    def file(self,path,raw):
        if not path.parent.exists():self.fixture.directory(path.parent)
        self.fixture.file(path,service.encode(raw) if isinstance(raw,dict) else raw)

    def legacy(self):
        identity,slot=self.fixture.legacy();self.fixture.root_result(identity,'backup-create');return identity

    def generation(self):
        identity=str(uuid.uuid4());old=self.fixture.fixture.key;new=secrets.token_bytes(32)
        raw=service.encode_key_generations([old,new],1,0);generation=service.key_generations(raw)[1]
        source=dict(keySha256=hashlib.sha256(old).hexdigest(),ringSha256=None)
        backup=dict(format=lifecycle.GENERATION_FORMAT,operationId=identity,encrypted='YQ==')  # Modeled cipher outcome, never a decryption acceptance.
        proof=service.decode(self.manager.read(self.manager.store.path('/etc/kura/credentials/provisioned.json')))
        proposed=dict(proof,keySha256=generation['activeKeySha256'],origin='canonical',legacyKey=False)
        history=dict(schema=1,purpose='yofc-kura-prepared-generation-v1',preparationId=identity,createdAt='2026-11-17T00:00:00Z',
            source=source,sourceReceipt=proof,sourceGenerationReceipt=None,provisioned=proposed,generation=generation,backupSha256=hashlib.sha256(service.encode(backup)).hexdigest())
        slot=self.manager.state/'generations'/identity;slot.mkdir(parents=True,mode=0o700)
        (slot.parent).chmod(0o700)
        self.manager.atomic(slot/'keyring',raw,mode=0o400);self.manager.atomic(slot/'history.json',service.encode(history),mode=0o400)
        response=dict(schema=1,operationId=identity,action='generation-prepare',state='SUCCEEDED',source=source,generation=generation,
            historySha256=hashlib.sha256(service.encode(history)).hexdigest(),backup=backup,published=False,requiresExplicitCommit=True)
        native=dict(schema=1,action='generation-prepare',operationId=identity,passphrase='synthetic-model-only',expectedSource=source)
        self.manager.atomic(self.manager.operations/(identity+'.json'),service.encode(dict(schema=1,operationId=identity,action='generation-prepare',requestTag=self.shared.tag(native),state='SUCCEEDED',response=response)))
        self.file(self.data/'gateway-key-generations'/(identity+'.json'),dict(schema=1,action='generation-prepare',operationId=identity,expectedSource=source,operator='model-admin'))
        self.manager.prepared_generation(identity)
        return identity

    def admission(self,*,handoff=False):
        frame=self.base.base.request();identity=self.base.base.original(frame)['operationId']
        if handoff:
            intent=dict(schema=1,action='generation-handoff-create',operator='model-admin',
                **{key:str(uuid.uuid4()) for key in lifecycle.HANDOFF_IDS},expectedRingSha256='1'*64,expectedCohortSha256='2'*64)
            identity=intent['handoffId'];frame['request']['request']=intent;kind='HANDOFF'
        else:intent=dict(schema=1,action='backup-create',operationId=identity,operator='model-admin');kind='LEGACY'
        self.base.base.reserve(frame);self.base.base.read(frame,close=True)
        parent=self.data/'gateway-key-admissions'
        if not parent.exists():self.fixture.directory(parent)
        slot=parent/identity;self.fixture.directory(slot)
        attempt=dict(schema=1,purpose='yofc.kura.sender-attempt.v1',admissionId=frame['admissionId'],kind=kind,nativeOperationId=identity,request=intent)
        raw=service.encode(attempt);self.file(slot/'intent.json',raw);self.file(slot/'complete',hashlib.sha256(raw).hexdigest().encode()+b'\n')
        self.file(slot/'namespace.json',dict(schema=1,namespaceSha256=self.namespace))
        if handoff:
            self.file(self.data/'gateway-key-handoffs'/(identity+'.json'),intent)
            receipt=dict(schema=1,purpose='yofc.kura.gwt-unconsumed-intent.v1',admissionId=frame['admissionId'],kind=kind,nativeOperationId=identity,
                namespaceSha256=self.namespace,files=dict(intent=hashlib.sha256(service.encode(intent)).hexdigest()))
            self.file(slot/'closed.json',receipt)
        return identity,frame['admissionId']

    def files(self,kind,identity):
        if kind=='LEGACY':slot=self.data/'gateway-key-operations'/identity;paths=list(slot.iterdir())
        elif kind in ('GENERATION','HANDOFF'):paths=[self.data/self.fixture.policy.journal_module().GwtSenderInventory.JOURNALS[kind][0]/(identity+'.json')]
        else:
            slot=self.data/('gateway-key-admissions' if kind=='ADMISSION' else 'gateway-key-not-dispatched')/identity;paths=list(slot.iterdir())
        return {str(path.relative_to(self.data)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

    def intent(self,kind,identity,directory,native_id):
        refs=[dict(directory=directory,operationId=native_id)]
        plan=self.manager.archive_journal(dict(schema=1,action='journal-archive-plan',namespaceSha256=self.namespace,entries=refs),111,self.fixture.uid,self.fixture.uid,self.base.base.recovery)
        request=dict(schema=1,action='journal-archive',archiveId=str(uuid.uuid4()),namespaceSha256=self.namespace,entries=refs,expectedEntriesSha256=plan['entriesSha256'])
        marker=dict(schema=1,purpose='yofc.kura.gwt-private-archive.v1',kind=kind,operationId=identity,binding=self.fixture.binding,
            privateFiles=self.files(kind,identity),reference=refs[0],entrySha256=plan['entries'][0]['sha256'],request=request,continuationAllowed=True)
        parent=self.data/'gateway-key-archives'
        if not parent.exists():self.fixture.directory(parent)
        self.file(parent/(kind+'-'+identity+'.json'),marker);return request,marker

    def archive(self,kind,identity,directory,native_id):
        request,marker=self.intent(kind,identity,directory,native_id)
        self.manager.archive_journal(request,111,self.fixture.uid,self.fixture.uid,self.base.base.recovery);return request,marker

    def check(self):return self.fixture.check()

    def test_legacy_sixty_fifth_slot_requires_positive_root_receipt_and_retains_every_original(self):
        ids=[self.legacy() for _ in range(64)];self.legacy()
        with self.assertRaises(lifecycle.Refused):self.check()
        before=self.fixture.snapshot();self.archive('LEGACY',ids[0],'operations',ids[0]);self.assertEqual(65,self.check())
        for name,row in before.items():self.assertEqual(row,self.fixture.snapshot()[name])
        self.assertEqual(65,len([p for p in (self.data/'gateway-key-operations').iterdir() if not p.name.startswith('.')]))

    def test_generation_sixty_fifth_slot_keeps_original_ring_history_and_private_intent(self):
        ids=[self.generation() for _ in range(65)]
        with self.assertRaises(lifecycle.Refused):self.check()
        before=self.fixture.snapshot();self.archive('GENERATION',ids[0],'operations',ids[0]);self.assertEqual(65,self.check())
        for name,row in before.items():self.assertEqual(row,self.fixture.snapshot()[name])
        lifecycle.Lifecycle(self.manager.root,self.manager.owner).initialize()

    def test_handoff_thirty_third_closed_private_slot_uses_ordinary_no_admission_original(self):
        rows=[self.admission(handoff=True) for _ in range(33)]
        with self.assertRaises(lifecycle.Refused):self.check()
        identity,admission=rows[0];self.archive('HANDOFF',identity,'sender-admissions',admission);self.assertEqual(33,self.check())
        self.assertEqual([],list((self.manager.state/'handoffs').iterdir()) if (self.manager.state/'handoffs').exists() else [])

    def test_shared_two_hundred_fifty_seventh_slot_releases_only_with_exact_admission_proof(self):
        rows=[self.admission() for _ in range(256)];identity,admission=rows[0];self.archive('ADMISSION',identity,'sender-admissions',admission)
        self.admission();self.assertEqual(0,self.check());self.assertEqual(257,len(list((self.data/'gateway-key-admissions').iterdir())))
        with self.assertRaises(service.Failure):self.base.base.reserve(self.base.base.request(identity=identity))

    def test_ordinary_no_admission_no_dispatch_receipts_use_their_own_root_original(self):
        rows=[]
        for _ in range(65):
            identity,admission=self.admission();self.fixture.no_dispatch(identity);rows.append((identity,admission))
        with self.assertRaises(lifecycle.Refused):self.check()
        identity,admission=rows[0];self.archive('NOT_DISPATCHED',identity,'sender-admissions',admission);self.assertEqual(0,self.check())

    def test_missing_or_pending_root_archive_does_not_free_capacity_or_write_during_read(self):
        ids=[self.legacy() for _ in range(65)];request,marker=self.intent('LEGACY',ids[0],'operations',ids[0]);before=self.fixture.snapshot()
        with self.assertRaises(lifecycle.Refused):self.check()
        self.assertEqual(before,self.fixture.snapshot());atomic=self.manager.atomic
        def lose(path,value,**kw):
            if path.name.endswith('.receipt.json'):raise OSError('modeled metadata receipt interruption')
            return atomic(path,value,**kw)
        with patch.object(self.manager,'atomic',side_effect=lose):
            with self.assertRaises(service.Failure):self.manager.archive_journal(request,111,self.fixture.uid,self.fixture.uid,self.base.base.recovery)
        before=self.fixture.snapshot()
        with self.assertRaises(lifecycle.Refused):self.check()
        self.assertEqual(before,self.fixture.snapshot())
        self.manager.archive_journal(dict(request,action='journal-archive-continue'),111,self.fixture.uid,self.fixture.uid,self.base.base.recovery)
        self.assertEqual(65,self.check())

    def test_changed_private_bytes_namespace_root_reference_or_data_owner_never_inherits_completion(self):
        identity=self.legacy();request,marker=self.archive('LEGACY',identity,'operations',identity);path=self.data/'gateway-key-archives'/('LEGACY-'+identity+'.json')
        for mutate in (lambda x:x['binding'].update(namespaceSha256='f'*64),lambda x:x.update(entrySha256='e'*64),
                lambda x:x['reference'].update(operationId=str(uuid.uuid4())),lambda x:x['privateFiles'].update({'gateway-key-operations/'+identity+'/request.json':'f'*64})):
            changed=copy.deepcopy(marker);mutate(changed);self.file(path,changed)
            with self.assertRaises((lifecycle.Refused,FileNotFoundError)):self.check()
        self.file(path,marker);original=self.data/'gateway-key-operations'/identity/'request.json';value=service.decode(original.read_bytes());value['operator']='another-admin';self.file(original,value)
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_torn_or_public_archive_marker_cannot_be_ignored_as_an_old_unarchived_record(self):
        identity=self.legacy();self.archive('LEGACY',identity,'operations',identity);path=self.data/'gateway-key-archives'/('LEGACY-'+identity+'.json');raw=path.read_bytes()
        self.file(path,b'{')
        with self.assertRaises(lifecycle.Refused):self.check()
        self.file(path,raw);path.chmod(0o640)
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_negative_admission_with_owning_files_needs_retained_closure_before_archive(self):
        identity,admission=self.admission(handoff=True);path=self.data/'gateway-key-admissions'/identity/'closed.json';raw=path.read_bytes();path.unlink()
        self.archive('ADMISSION',identity,'sender-admissions',admission)
        with self.assertRaises(lifecycle.Refused):self.check()
        self.file(path,raw)
        # Adding a later closure cannot silently change the private snapshot that was archived.
        with self.assertRaises(lifecycle.Refused):self.check()


if __name__=='__main__':unittest.main()
