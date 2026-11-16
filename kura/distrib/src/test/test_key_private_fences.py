#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh Root files/HMAC/flock; Main/systemd/native results are explicit models."""
import copy
import hashlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

import test_key_sender_admissions as original

service=original.service
lifecycle=original.lifecycle


@unittest.skipUnless(sys.platform=='linux','Immutable Root publication uses Linux renameat2')
class PrivateFenceTest(unittest.TestCase):
    def setUp(self):
        self.base=original.SenderAdmissionsTest();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.manager=self.base.manager;self.shared=self.base.coordinator;self.fixture=self.base.fixture
        peer=patch.object(service,'agent_peer',return_value=False);peer.start();self.addCleanup(peer.stop)

    def request(self,source='gwt',kind=None):
        identity=str(uuid.uuid4());data={k:self.fixture.binding[k] for k in lifecycle.GWT_DATA_FIELDS}
        data['dataUid']=self.base.peer[source][1]
        kind=kind or ('LEGACY' if source=='gwt' else 'restore')
        intent=dict(schema=1,action='backup-create',operationId=identity,operator='modeled-admin')
        if kind=='restore':intent=dict(schema=1,action='restore',operationId=identity,expectedKeySha256='1'*64,backupSha256='2'*64)
        if kind=='start':intent=dict(schema=1,action='core-start',operationId=identity,restoreOperationId=str(uuid.uuid4()),expectedKeySha256='1'*64)
        if kind=='GENERATION':intent=dict(schema=1,action='generation-prepare',operationId=identity,operator='modeled-admin',
            expectedSource=dict(keySha256='1'*64,ringSha256=None))
        if kind=='HANDOFF':intent=dict(schema=1,action='generation-handoff-create',operator='modeled-admin',
            **{k:str(uuid.uuid4()) for k in lifecycle.HANDOFF_IDS},expectedRingSha256='1'*64,expectedCohortSha256='2'*64)
        return dict(schema=1,action='sender-private-fence',admissionId=str(uuid.uuid4()),source=source,
            namespaceSha256=self.manager.gwt_namespace()['namespaceSha256'],**data,kind=kind,intent=intent,receiptSha256='a'*64)

    def call(self,request,*,bound=True,pid=None,uid=None):
        peer=self.base.peer[request['source']];pid=peer[0] if pid is None else pid;uid=peer[1] if uid is None else uid
        wire=dict(schema=1,action='gwt-bound-request',binding=self.fixture.binding,request=request) if bound and request['source']=='gwt' else request
        return service.serve_request(self.manager,wire,pid,uid,self.base.core,self.base.recovery,None)[0]

    def query(self,request):
        return self.call(dict({k:request[k] for k in ('schema','source','namespaceSha256','admissionId')},action='sender-private-fence-read'))

    def snapshot(self):return self.fixture.snapshot()

    def rejected(self,request,reason=None):
        before=self.snapshot()
        with self.assertRaises(service.Failure) as result:self.call(request)
        if reason:self.assertEqual(reason,result.exception.reason)
        self.assertEqual(before,self.snapshot())

    def pad(self,count):
        for _ in range(count):
            request=self.base.request();native=self.base.original(request)
            self.shared.write(dict(schema=1,purpose=lifecycle.SENDER_ADMISSION_PURPOSE,admissionId=request['admissionId'],
                source='gwt',namespaceSha256=request['namespaceSha256'],owner=self.base.owner('gwt',111,self.base.core),
                requestTag='1'*64,target=self.shared.native_target(native),parentAdmissionId=None,state='NOT_ADMITTED'),create=True)

    def test_plan_and_missing_query_do_not_create_any_file_or_permission(self):
        request=self.request();before=self.snapshot()
        plan=self.call(dict(request,action='sender-private-fence-plan'))
        self.assertEqual('PRIVATE_FENCE_PLAN',plan['state']);self.assertFalse(plan['credentialsChanged']);self.assertFalse(plan['startRequested'])
        self.assertEqual('NOT_RECORDED',self.query(request)['state']);self.assertEqual(before,self.snapshot())

    def test_distinct_immutable_proof_binds_private_bytes_namespace_uid_and_target(self):
        request=self.request();before=self.snapshot();result=self.call(request)
        self.assertEqual('PRIVATE_FENCE_RECORDED',result['state']);self.assertEqual(result,self.query(request))
        path=self.shared.directory/(request['admissionId']+'.json');raw=path.read_bytes();value=service.decode(raw)
        self.assertEqual(0o400,path.stat().st_mode&0o777);self.assertEqual(lifecycle.PRIVATE_FENCE_PURPOSE,value['purpose'])
        self.assertEqual(request['receiptSha256'],result['privateProof']['receiptSha256'])
        self.assertEqual(hashlib.sha256(service.encode(request['intent'])).hexdigest(),result['privateProof']['metadataSha256'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(),result['receiptSha256'])
        self.assertEqual([str(path)],list(set(self.snapshot())-set(before)))
        for key,row in before.items():self.assertEqual(row,self.snapshot()[key])
        self.assertEqual([],list(self.manager.operations.iterdir()))
        self.assertNotIn(b'passphrase',raw);self.assertNotIn(b'backupSha256',raw)
        lifecycle.Lifecycle(self.manager.root,self.manager.owner).initialize();self.manager.sender_admissions.require_settled()

    def test_duplicate_request_is_read_only_and_changed_private_original_conflicts(self):
        request=self.request();result=self.call(request);before=self.snapshot()
        with patch.object(self.manager,'atomic',side_effect=AssertionError('No second metadata writer')):
            self.assertEqual(result,self.call(request));self.assertEqual(result,self.query(request))
        self.assertEqual(before,self.snapshot())
        for key,value in (('receiptSha256','b'*64),('dataInode','999'),('kind','GENERATION')):
            self.rejected(dict(request,**{key:value}))

    def test_actual_sender_reservation_and_intake_are_never_reclassified(self):
        for state in ('RESERVED','INTAKE','NOT_ADMITTED'):
            with self.subTest(state=state):
                request=self.request();frame=self.base.request(identity=request['intent']['operationId']);self.base.reserve(frame)
                self.shared.write(dict(self.shared.load(frame['admissionId']),state=state))
                self.rejected(request,'UNRESOLVED_OPERATION')
                self.assertEqual(state,self.shared.load(frame['admissionId'])['state'])

    def test_unrelated_unknown_is_unchanged_and_does_not_become_a_closure(self):
        frame=self.base.request();self.base.reserve(frame);self.shared.write(dict(self.shared.load(frame['admissionId']),state='INTAKE'))
        path=self.shared.directory/(frame['admissionId']+'.json');before=path.read_bytes();self.call(self.request())
        self.assertEqual(before,path.read_bytes());self.assertEqual('INTAKE',self.shared.load(frame['admissionId'])['state'])

    def test_native_original_in_any_directory_prevents_both_plan_and_commit(self):
        for directory in ('operations','startups','handoffs'):
            request=self.request();parent=self.manager.state/directory;parent.mkdir(mode=0o700,exist_ok=True)
            self.manager.atomic(parent/(request['intent']['operationId']+'.json'),b'{}')
            self.rejected(dict(request,action='sender-private-fence-plan'),'UNRESOLVED_OPERATION')
            self.rejected(request,'UNRESOLVED_OPERATION')

    def test_lost_reply_after_publication_is_recovered_only_by_original_query(self):
        request=self.request();atomic=self.manager.atomic;writes=[]
        def lose(*args,**kwargs):
            atomic(*args,**kwargs);writes.append(str(args[0]));raise OSError('Modeled reply path failure')
        with patch.object(self.manager,'atomic',side_effect=lose):
            with self.assertRaises(service.Failure) as result:self.call(request)
        self.assertEqual('UNKNOWN',result.exception.reason);before=self.snapshot()
        self.assertEqual('PRIVATE_FENCE_RECORDED',self.query(request)['state']);self.assertEqual(before,self.snapshot());self.assertEqual(1,len(writes))

    def test_failed_publication_is_not_retried_or_inferred_from_missing_query(self):
        request=self.request()
        with patch.object(self.manager,'atomic',side_effect=OSError('Modeled failure before rename')):
            with self.assertRaises(service.Failure) as result:self.call(request)
        self.assertEqual('UNKNOWN',result.exception.reason);before=self.snapshot()
        self.assertEqual('NOT_RECORDED',self.query(request)['state']);self.assertEqual(before,self.snapshot())

    def test_late_old_target_and_fence_identity_cannot_become_native_or_new_admission(self):
        request=self.request();self.call(request);ids=[request['admissionId'],request['intent']['operationId']]
        for identity in ids:
            frame=self.base.request(identity=identity);before=self.snapshot()
            with self.assertRaises(service.Failure):self.base.reserve(frame)
            self.assertEqual(before,self.snapshot())
            frame=self.base.request();frame['admissionId']=identity
            with self.assertRaises(service.Failure):self.base.reserve(frame)
            self.assertEqual(before,self.snapshot())
        replacement=self.request();replacement['intent']['operationId']=request['intent']['operationId'];self.rejected(replacement,'CONFLICT')

    def test_fence_can_be_added_at_full_budget_without_increasing_writer_capacity(self):
        self.pad(256);request=self.request();self.call(request)
        self.assertEqual(257,len(self.shared.records()));self.assertEqual(256,self.manager.active_records('sender-admissions',
            [r['admissionId'] for r in self.shared.records()]))
        with self.assertRaises(service.Failure) as result:self.base.reserve(self.base.request())
        self.assertEqual('CAPACITY',result.exception.reason)
        lifecycle.Lifecycle(self.manager.root,self.manager.owner).check_sender_admissions()

    def test_gwt_unbound_process_wrong_data_owner_and_wrong_namespace_are_rejected(self):
        request=self.request();before=self.snapshot()
        with self.assertRaises(service.Failure):self.call(request,bound=False)
        with self.assertRaises(service.Failure):self.call(request,pid=999)
        self.assertEqual(before,self.snapshot())
        for key,value in (('source','recovery'),('namespaceSha256','f'*64),('dataUid',self.base.recovery),('dataDirectory','/srv/elsewhere')):
            self.rejected(dict(request,**{key:value}))

    def test_secret_or_backup_fields_are_rejected_instead_of_retained_in_a_fence(self):
        for key in ('passphrase','backup'):
            request=self.request();request['intent'][key]='synthetic-private-value';self.rejected(request)

    def test_private_fence_cannot_impersonate_an_ordinary_attempt_or_close_receipt(self):
        request=self.request();self.call(request);before=self.snapshot()
        query={k:request[k] for k in ('schema','admissionId','source','namespaceSha256')}
        for action in ('sender-admission-read','sender-admission-close'):
            with self.assertRaises(service.Failure) as failure:
                self.shared.read(dict(query,action=action),111,self.base.core,self.base.core,self.base.recovery,close=action.endswith('-close'))
            self.assertEqual('FORBIDDEN',failure.exception.reason)
        attempt=dict(schema=1,purpose='yofc.kura.sender-attempt.v1',admissionId=request['admissionId'],
            kind='LEGACY',nativeOperationId=request['intent']['operationId'],request=request['intent'])
        with self.assertRaises(lifecycle.Refused):lifecycle.check_sender_attempt(self.manager,attempt,
            dict(schema=1,namespaceSha256=request['namespaceSha256']),'gwt',self.base.core)
        self.assertEqual(before,self.snapshot())

    def test_packaged_agent_cgroup_cannot_use_even_metadata_only_fencing(self):
        request=self.request();before=self.snapshot()
        with patch.object(service,'agent_peer',return_value=True):
            with self.assertRaises(service.Failure) as result:self.call(request)
        self.assertEqual('FORBIDDEN',result.exception.reason);self.assertEqual(before,self.snapshot())

    def test_generation_handoff_and_recovery_receipts_have_separate_strict_shapes(self):
        for source,kind in (('gwt','GENERATION'),('gwt','HANDOFF'),('recovery','restore'),('recovery','start')):
            request=self.request(source,kind);result=self.call(request)
            self.assertEqual(kind,result['privateProof']['kind']);self.assertEqual(result,self.query(request))
            for identity in result['privateProof']['blockedIds']:
                with self.assertRaises(service.Failure):self.manager.require_not_archive_id(identity)
        self.assertEqual([],list(self.manager.operations.iterdir()))

    def test_unmaterialized_authority_blocks_fencing_undisclosed_future_ids(self):
        frame=self.base.request();frame['request']['request']=self.request(kind='HANDOFF')['intent']
        self.base.reserve(frame);self.rejected(self.request(),'UNRESOLVED_OPERATION')

    def test_existing_authority_all_five_ids_cannot_be_poisoned(self):
        _,intent=self.fixture.handoff()
        for key in lifecycle.HANDOFF_IDS:
            request=self.request();request['intent']['operationId']=intent[key];self.rejected(request)

    def test_tamper_mode_root_namespace_and_later_native_collision_fail_closed(self):
        request=self.request();self.call(request);identity=request['admissionId'];path=self.shared.directory/(identity+'.json')
        raw=path.read_bytes();value=service.decode(raw)
        for mutate in (lambda v:v.update(state='RESERVED'),lambda v:v['privateProof'].update(receiptSha256='f'*64)):
            changed=copy.deepcopy(value);mutate(changed);path.chmod(0o600);path.write_bytes(service.encode(changed));path.chmod(0o400)
            with self.assertRaises(service.Failure):self.query(request)
            with self.assertRaises(lifecycle.Refused):lifecycle.Lifecycle(self.manager.root,self.manager.owner).initialize()
        path.chmod(0o600);path.write_bytes(raw)
        with self.assertRaises(service.Failure):self.query(request)
        path.chmod(0o400);parent=self.manager.state/'startups';parent.mkdir(mode=0o700,exist_ok=True)
        self.manager.atomic(parent/(request['intent']['operationId']+'.json'),b'{}')
        with self.assertRaises(service.Failure):self.query(request)
        with self.assertRaises(lifecycle.Refused):lifecycle.Lifecycle(self.manager.root,self.manager.owner).initialize()

    def test_archiving_fence_preserves_original_bytes_and_all_permanent_blocked_ids(self):
        request=self.request();result=self.call(request);path=self.shared.directory/(request['admissionId']+'.json');before=path.read_bytes()
        refs=[dict(directory='sender-admissions',operationId=request['admissionId'])]
        plan=self.manager.archive_journal(dict(schema=1,action='journal-archive-plan',entries=refs,
            namespaceSha256=request['namespaceSha256']),333,0,self.base.core,self.base.recovery)
        self.manager.archive_journal(dict(schema=1,action='journal-archive',entries=refs,archiveId=str(uuid.uuid4()),
            expectedEntriesSha256=plan['entriesSha256'],namespaceSha256=request['namespaceSha256']),333,0,self.base.core,self.base.recovery)
        self.assertEqual(before,path.read_bytes());self.assertEqual(result,self.query(request))
        with self.assertRaises(service.Failure):self.manager.require_not_archive_id(request['intent']['operationId'])

    def test_independent_package_reader_rejects_a_later_contradictory_reservation(self):
        request=self.request();self.call(request)
        native=self.base.request(identity=request['intent']['operationId']);original=self.base.original(native)
        self.shared.write(dict(schema=1,purpose=lifecycle.SENDER_ADMISSION_PURPOSE,admissionId=native['admissionId'],
            source='gwt',namespaceSha256=native['namespaceSha256'],owner=self.base.owner('gwt',111,self.base.core),
            requestTag='1'*64,target=self.shared.native_target(original),parentAdmissionId=None,state='NOT_ADMITTED'),create=True)
        policy=lifecycle.Lifecycle(self.manager.root,self.manager.owner)
        with self.assertRaises(lifecycle.Refused):policy.initialize()
        with self.assertRaises(lifecycle.Refused):policy.check_sender_admissions()

    def reference(self,directory,identity):
        return self.manager.archive_journal(dict(schema=1,action='journal-archive-reference-read',
            namespaceSha256=self.manager.gwt_namespace()['namespaceSha256'],directory=directory,operationId=identity),
            333,0,self.base.core,self.base.recovery)

    def archive_reference(self,directory,identity):
        refs=[dict(directory=directory,operationId=identity)];namespace=self.manager.gwt_namespace()['namespaceSha256']
        plan=self.manager.archive_journal(dict(schema=1,action='journal-archive-plan',entries=refs,namespaceSha256=namespace),333,0,self.base.core,self.base.recovery)
        request=dict(schema=1,action='journal-archive',entries=refs,namespaceSha256=namespace,
            archiveId=str(uuid.uuid4()),expectedEntriesSha256=plan['entriesSha256'])
        return request,self.manager.archive_journal(request,333,0,self.base.core,self.base.recovery)

    def test_reference_lookup_is_readonly_redacted_and_adopts_original_archive(self):
        identity=str(uuid.uuid4());self.fixture.root_result(identity,'backup-create');before=self.snapshot()
        result=self.reference('operations',identity);self.assertEqual('ARCHIVABLE',result['state']);self.assertIsNone(result['archive'])
        self.assertEqual(before,self.snapshot());self.assertNotIn('backup',result['correlation']);self.assertNotIn('requestTag',str(result))
        request,proof=self.archive_reference('operations',identity);before=self.snapshot();result=self.reference('operations',identity)
        self.assertEqual('ARCHIVE_RECORDED',result['state']);self.assertEqual(proof,result['archive']);self.assertEqual(request['archiveId'],result['archive']['archiveId'])
        self.assertEqual(before,self.snapshot())

    def test_positive_intake_can_archive_but_ordinary_reads_never_rewrite_claimed_bytes(self):
        frame=self.base.request();self.base.reserve(frame);self.shared.write(dict(self.shared.load(frame['admissionId']),state='INTAKE'));self.base.success(frame)
        path=self.shared.directory/(frame['admissionId']+'.json');raw=path.read_bytes()
        self.assertEqual('ARCHIVABLE',self.reference('sender-admissions',frame['admissionId'])['state']);self.assertEqual(raw,path.read_bytes())
        self.archive_reference('sender-admissions',frame['admissionId'])
        self.assertEqual('TERMINAL',self.base.read(frame)['state']);self.shared.require_settled();self.assertEqual(raw,path.read_bytes())
        self.assertEqual('INTAKE',self.shared.load(frame['admissionId'])['state']);self.manager.archives()
        with self.assertRaises(service.Failure):self.shared.write(dict(self.shared.load(frame['admissionId']),state='TERMINAL'))
        self.assertEqual(raw,path.read_bytes())

    def test_pending_archive_also_protects_positive_intake_original_from_read_settlement(self):
        frame=self.base.request();self.base.reserve(frame);self.shared.write(dict(self.shared.load(frame['admissionId']),state='INTAKE'));self.base.success(frame)
        path=self.shared.directory/(frame['admissionId']+'.json');raw=path.read_bytes();atomic=self.manager.atomic
        def lose(path,value,**kw):
            if path.name.endswith('.receipt.json'):raise OSError('modeled metadata receipt failure')
            return atomic(path,value,**kw)
        with patch.object(self.manager,'atomic',side_effect=lose):
            with self.assertRaises(service.Failure) as failure:self.archive_reference('sender-admissions',frame['admissionId'])
        self.assertEqual('UNKNOWN',failure.exception.reason)
        self.assertEqual('TERMINAL',self.base.read(frame)['state']);self.assertEqual(raw,path.read_bytes())
        result=self.reference('sender-admissions',frame['admissionId']);self.assertEqual('UNKNOWN',result['state'])
        self.assertIsNotNone(result['archive']);self.assertTrue(result['continuationAllowed']);self.assertEqual(raw,path.read_bytes())

    def test_missing_native_or_true_intake_uncertainty_has_no_reference_archive_proof(self):
        frame=self.base.request();self.base.reserve(frame);self.shared.write(dict(self.shared.load(frame['admissionId']),state='INTAKE'));before=self.snapshot()
        for directory,identity in [('sender-admissions',frame['admissionId']),('operations',self.base.original(frame)['operationId'])]:
            with self.assertRaises(service.Failure) as failure:self.reference(directory,identity)
            self.assertEqual('ARCHIVE_UNSETTLED',failure.exception.reason)
        self.assertEqual(before,self.snapshot())


@unittest.skipUnless(sys.platform=='linux','Production Root fence requires Linux renameat2')
class NoDispatchArchiveReaderTest(unittest.TestCase):
    def setUp(self):
        self.base=PrivateFenceTest();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.fixture=self.base.fixture;self.manager=self.base.manager;self.shared=self.base.shared

    def prepare(self):
        identity,slot=self.fixture.no_dispatch();raw=(slot/'receipt.json').read_bytes();receipt=service.decode(raw)
        request=self.base.request();request.update(intent=receipt['request'],kind=receipt['kind'],receiptSha256=hashlib.sha256(raw).hexdigest())
        self.fixture.file(slot/'archive.json',service.encode(request));return identity,slot,request

    def test_only_original_root_positive_proof_releases_the_sixty_fifth_private_slot(self):
        identity,slot,request=self.prepare()
        for _ in range(64):self.fixture.no_dispatch()
        with self.assertRaises(lifecycle.Refused):self.fixture.check()
        originals=self.fixture.snapshot();self.base.call(request)
        self.assertEqual(0,self.fixture.check())
        for path,row in originals.items():self.assertEqual(row,self.fixture.snapshot()[path])
        self.assertEqual(65,len(list(slot.parent.iterdir())))
        with self.assertRaises(service.Failure):self.manager.require_not_archive_id(identity)

    def test_missing_root_fence_remains_active_without_any_replay_or_read_write(self):
        _,_,request=self.prepare()
        for _ in range(63):self.fixture.no_dispatch()
        before=self.fixture.snapshot();self.assertEqual(0,self.fixture.check());self.assertEqual(before,self.fixture.snapshot())
        self.assertEqual('NOT_RECORDED',self.base.query(request)['state'])
        self.fixture.no_dispatch()
        with self.assertRaises(lifecycle.Refused):self.fixture.check()

    def test_changed_private_bytes_cannot_inherit_a_root_fence(self):
        _,slot,request=self.prepare();self.base.call(request)
        receipt=service.decode((slot/'receipt.json').read_bytes());receipt['request']['operator']='changed-admin'
        raw=service.encode(receipt);self.fixture.file(slot/'receipt.json',raw);self.fixture.file(slot/'complete',hashlib.sha256(raw).hexdigest().encode()+b'\n')
        with self.assertRaises(lifecycle.Refused):self.fixture.check()

    def test_an_ordinary_negative_reservation_is_not_a_private_fence(self):
        _,slot,request=self.prepare();frame=self.base.base.request(identity=request['intent']['operationId'])
        self.base.base.reserve(frame);self.base.base.read(frame,close=True);request['admissionId']=frame['admissionId']
        self.fixture.file(slot/'archive.json',service.encode(request))
        with self.assertRaises(lifecycle.Refused):self.fixture.check()

    def test_replaced_namespace_wrong_data_or_retargeted_intent_is_refused(self):
        _,slot,request=self.prepare();self.base.call(request)
        for key,value in (('namespaceSha256','f'*64),('dataInode','999'),('dataUid',self.base.base.recovery),('receiptSha256','b'*64)):
            with self.subTest(key=key):
                changed=dict(request,**{key:value});self.fixture.file(slot/'archive.json',service.encode(changed))
                with self.assertRaises(lifecycle.Refused):self.fixture.check()

    def test_torn_public_or_linked_private_metadata_never_frees_capacity(self):
        _,slot,request=self.prepare();self.base.call(request);path=slot/'archive.json';raw=path.read_bytes()
        self.fixture.file(path,b'{')
        with self.assertRaises(lifecycle.Refused):self.fixture.check()
        self.fixture.file(path,raw);path.chmod(0o640)
        with self.assertRaises(lifecycle.Refused):self.fixture.check()
        path.chmod(0o600);os.link(path,slot/'linked')
        with self.assertRaises(lifecycle.Refused):self.fixture.check()


if __name__=='__main__':unittest.main()
