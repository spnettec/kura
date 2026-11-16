#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Persistent cross-identity admission using new private fixtures; identities/native results modeled."""
import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/bin'))
import kura_key_service as service
import kura_key_service_lifecycle as lifecycle
import test_key_gwt_sender_namespace as fixtures


@unittest.skipUnless(sys.platform=='linux','Production no-replace reservation uses Linux renameat2')
class SenderAdmissionsTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.GwtSenderNamespaceTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.manager=self.fixture.manager;self.coordinator=self.manager.sender_admissions
        self.core=self.fixture.uid;self.recovery=self.core+1
        self.boot=str(uuid.uuid4());self.peer={'gwt':(111,self.core),'recovery':(222,self.recovery),'local-admin':(333,0)}
        self.coordinator.owner=self.owner

    def owner(self,source,pid,uid,*_):
        service.require(self.peer.get(source)==(pid,uid),'FORBIDDEN')
        return dict(pid=pid,uid=uid,startTicks=str(pid+10),bootId=self.boot)

    def request(self,source='gwt',identity=None):
        identity=identity or str(uuid.uuid4())
        native=dict(schema=1,action='backup-create' if source=='gwt' else 'restore',operationId=identity,passphrase='synthetic-password-not-stored')
        if source=='recovery':native.update(expectedKeySha256='1'*64,backup={'format':service.FORMAT,'operationId':str(uuid.uuid4()),'encrypted':'YQ=='})
        wire=dict(schema=1,action='gwt-bound-request',binding=self.fixture.binding,request=native) if source=='gwt' else native
        return dict(schema=1,action='sender-reserve',admissionId=str(uuid.uuid4()),source=source,
            namespaceSha256=self.manager.gwt_namespace()['namespaceSha256'],request=wire)

    def reserve(self,request):
        pid,uid=self.peer[request['source']]
        return self.coordinator.reserve(request,pid,uid,self.core,self.recovery)

    def execute(self,request,callback):
        pid,uid=self.peer[request['source']]
        return self.coordinator.execute(dict(request,action='sender-command'),pid,uid,self.core,self.recovery,callback)

    def read(self,request,close=False):
        value={k:request[k] for k in ('schema','admissionId','source','namespaceSha256')};value['action']='sender-admission-close' if close else 'sender-admission-read'
        pid,uid=self.peer[request['source']]
        return self.coordinator.read(value,pid,uid,self.core,self.recovery,close=close)

    def original(self,request):
        wire=request['request'];return wire['request'] if wire['action']=='gwt-bound-request' else wire

    def success(self,request):
        native=self.original(request);value=self.fixture.root_result(native['operationId'],native['action'])
        value['requestTag']=self.coordinator.tag(native)
        self.fixture.fixture.write(self.manager.operations/(native['operationId']+'.json'),service.encode(value),0o600)

    def test_core_reservation_blocks_recovery_before_any_local_or_native_key_intent(self):
        core=self.request();result=self.reserve(core);self.assertTrue(result['newlyReserved'])
        self.assertEqual('RESERVED',result['state']);self.assertEqual([],list(self.manager.operations.iterdir()))
        self.assertEqual('NOT_ADMITTED',self.reserve(self.request('recovery'))['state'])
        self.assertEqual(2,len(self.coordinator.records()))

    def test_recovery_reservation_blocks_core_and_is_not_authorized_by_a_different_identity(self):
        recovery=self.request('recovery');self.reserve(recovery)
        self.assertEqual('NOT_ADMITTED',self.reserve(self.request())['state'])
        query={k:recovery[k] for k in ('schema','admissionId','source','namespaceSha256')};query['action']='sender-admission-read'
        with self.assertRaises(service.Failure):self.coordinator.read(query,111,self.core,self.core,self.recovery)

    def test_intake_is_forced_before_native_dispatch_and_normal_completion_releases_other_identity(self):
        core=self.request();self.reserve(core);calls=[]
        def dispatch(wire):
            self.assertEqual('INTAKE',self.coordinator.load(core['admissionId'])['state'])
            self.manager.settled()  # Only this exact in-process admission is excluded.
            calls.append(1);native=self.original(core)
            self.success(core)
            return {'model':'native-success'},None
        self.assertEqual(({'model':'native-success'},None),self.execute(core,dispatch));self.assertEqual([1],calls)
        self.assertEqual('TERMINAL',self.read(core)['state'])
        self.assertTrue(self.reserve(self.request('recovery'))['newlyReserved'])

    def test_missing_native_after_intake_remains_unknown_and_cannot_close_or_dispatch_again(self):
        request=self.request();self.reserve(request);calls=[]
        def rejected(wire):calls.append(1);raise service.Failure('BACKUP_REJECTED')
        with self.assertRaises(service.Failure):self.execute(request,rejected)
        self.assertEqual('INTAKE',self.read(request)['state'])
        with self.assertRaises(service.Failure):self.read(request,close=True)
        with self.assertRaises(service.Failure):self.execute(request,rejected)
        self.assertEqual('NOT_ADMITTED',self.reserve(self.request('recovery'))['state'])
        self.assertEqual([1],calls);self.assertEqual([],list(self.manager.operations.iterdir()))

    def test_read_never_closes_an_unconsumed_reservation_and_explicit_close_forbids_late_forward(self):
        request=self.request();self.reserve(request)
        self.assertEqual('RESERVED',self.read(request)['state'])
        self.assertEqual('NOT_ADMITTED',self.read(request,close=True)['state'])
        calls=[]
        with self.assertRaises(service.Failure):self.execute(request,lambda wire:calls.append(1))
        self.assertEqual([],calls)
        with self.assertRaises(service.Failure):self.reserve(self.request(identity=self.original(request)['operationId']))
        self.assertTrue(self.reserve(self.request('recovery'))['newlyReserved'])

    def test_repeated_reservation_is_never_a_second_first_dispatch_permission(self):
        request=self.request();self.assertTrue(self.reserve(request)['newlyReserved'])
        self.assertFalse(self.reserve(request)['newlyReserved'])
        raw=self.coordinator.manager.read(self.coordinator.directory/(request['admissionId']+'.json'))
        self.assertNotIn(b'synthetic-password',raw);self.assertNotIn(b'passphrase',raw);self.assertNotIn(b'encrypted',raw)

    def test_changed_full_request_cannot_use_the_original_permission(self):
        request=self.request();self.reserve(request);changed=json.loads(json.dumps(request))
        changed['request']['request']['passphrase']='another-password'
        with self.assertRaises(service.Failure):self.reserve(changed)
        with self.assertRaises(service.Failure):self.execute(changed,lambda wire:self.fail('foreign writer'))
        self.assertEqual('RESERVED',self.read(request)['state'])

    def test_positive_original_recovers_a_lost_response_without_repeating_native_dispatch(self):
        request=self.request();self.reserve(request);calls=[]
        def writer(wire):
            calls.append(1);self.success(request);raise OSError('response path lost')
        with self.assertRaises(OSError):self.execute(request,writer)
        self.assertEqual('INTAKE',self.coordinator.load(request['admissionId'])['state'])
        self.assertEqual('TERMINAL',self.read(request)['state'])
        with self.assertRaises(service.Failure):self.execute(request,writer)
        self.assertEqual([1],calls)

    def test_other_source_cannot_begin_while_intake_response_is_ambiguous(self):
        request=self.request('recovery');self.reserve(request)
        with self.assertRaises(OSError):self.execute(request,lambda wire:(_ for _ in ()).throw(OSError('lost')))
        self.assertEqual('NOT_ADMITTED',self.reserve(self.request())['state'])
        with self.assertRaises(service.Failure):self.manager.settled()

    def test_new_service_object_and_boot_do_not_make_an_old_reservation_a_new_writer(self):
        request=self.request();self.reserve(request)
        coordinator=service.SenderAdmissions(self.manager);coordinator.owner=self.owner
        self.assertEqual('RESERVED',coordinator.load(request['admissionId'])['state'])
        self.coordinator=coordinator;self.boot=str(uuid.uuid4())
        with self.assertRaises(service.Failure):self.execute(request,lambda wire:self.fail('new boot writer'))
        self.assertEqual('RESERVED',self.read(request)['state'])
        self.assertEqual('NOT_ADMITTED',self.read(request,close=True)['state'])

    def test_corrupt_or_foreign_namespace_record_is_not_rebuilt(self):
        request=self.request();self.reserve(request);path=self.coordinator.directory/(request['admissionId']+'.json')
        value=json.loads(path.read_bytes());value['receiptTag']='0'*64;path.write_text(json.dumps(value));before=path.read_bytes()
        with self.assertRaises(service.Failure):self.read(request)
        with self.assertRaises(service.Failure):self.reserve(self.request('recovery'))
        self.assertEqual(before,path.read_bytes())

    def test_upgrade_refuses_reserved_or_intake_before_stopping_units(self):
        request=self.request();self.reserve(request);calls=self.fixture.fixture.calls
        with self.assertRaises(lifecycle.Unresolved):self.fixture.policy.enter('upgrade')
        self.assertFalse(any(call[1]=='stop' for call in calls))

    def test_offline_upgrade_accepts_only_matching_positive_original_without_rewriting_intake(self):
        request=self.request();self.reserve(request)
        def lost(wire):self.success(request);raise OSError('response lost after durable success')
        with self.assertRaises(OSError):self.execute(request,lost)
        native=self.original(request);attempt=dict(schema=1,purpose='yofc.kura.sender-attempt.v1',
            admissionId=request['admissionId'],kind='LEGACY',nativeOperationId=native['operationId'],
            request=dict(schema=1,action=native['action'],operationId=native['operationId'],operator='model-admin'))
        namespace=dict(schema=1,namespaceSha256=request['namespaceSha256'])
        before=(self.coordinator.directory/(request['admissionId']+'.json')).read_bytes()
        root=lifecycle.check_sender_attempt(self.fixture.policy,attempt,namespace,'gwt',self.core)
        self.assertEqual('INTAKE',root['state']);self.fixture.policy.check_sender_admissions()
        self.assertEqual(before,(self.coordinator.directory/(request['admissionId']+'.json')).read_bytes())
        path=self.manager.operations/(native['operationId']+'.json');value=json.loads(path.read_bytes());value['requestTag']='0'*64
        self.fixture.fixture.write(path,service.encode(value),0o600)
        with self.assertRaises(lifecycle.Refused):lifecycle.check_sender_attempt(self.fixture.policy,attempt,namespace,'gwt',self.core)

    def test_closed_reservation_cannot_hide_an_unexpected_native_original(self):
        request=self.request();self.reserve(request);self.read(request,close=True);self.success(request)
        with self.assertRaises(service.Failure):self.read(request)
        with self.assertRaises(lifecycle.Refused):self.fixture.policy.check_sender_admissions()

    def test_handoff_original_must_retain_immutable_mode_and_canonical_authenticated_bytes(self):
        identity,intent=self.fixture.handoff();path=self.manager.state/'handoffs'/(identity+'.json')
        value=json.loads(path.read_bytes());target=dict(directory='handoffs',operationId=identity,
            action='generation-handoff-create',requestTag=value['requestTag'],continuation=False)
        self.assertEqual(value,self.coordinator.native(target))
        path.chmod(0o600)
        with self.assertRaises(service.Failure):self.coordinator.native(target)
        path.chmod(0o400);path.chmod(0o600);path.write_text(json.dumps(value,indent=2));path.chmod(0o400)
        with self.assertRaises(service.Failure):self.coordinator.native(target)

    def test_receiver_role_requires_current_fixed_service_main_and_kernel_uid(self):
        valid=dict(Id='kura-key-recovery.service',ActiveState='active',SubState='running',MainPID='222',
            ControlPID='0',User='kura-key-recovery',ControlGroup='/system.slice/kura-key-recovery.service')
        def output(value):return SimpleNamespace(returncode=0,stdout=''.join(k+'='+v+'\n' for k,v in value.items()))
        with patch.object(self.manager,'writer_process',return_value=(self.recovery,'232')):
            with patch.object(service.subprocess,'run',return_value=output(valid)):
                self.manager.recovery_sender_owner(222,self.recovery)
                with self.assertRaises(service.Failure):self.manager.recovery_sender_owner(223,self.recovery)
                with self.assertRaises(service.Failure):self.manager.recovery_sender_owner(222,self.core)
            for name,bad in (('ControlPID','224'),('User','kurad'),('ControlGroup','/other'),('ActiveState','activating')):
                with self.subTest(name=name),patch.object(service.subprocess,'run',return_value=output(dict(valid,**{name:bad}))):
                    with self.assertRaises(service.Failure):self.manager.recovery_sender_owner(222,self.recovery)

    def cancellation(self):
        request=self.request('local-admin');native=request['request'];native.pop('passphrase')
        native.update(action='generation-cancel',preparationId=str(uuid.uuid4()),
            expectedHistorySha256='3'*64,expectedRingSha256='4'*64)
        self.reserve(request)
        original=dict(schema=1,operationId=native['operationId'],action=native['action'],requestTag=self.coordinator.tag(native),
            state='INTENT',response=None,intent={k:native[k] for k in ('preparationId','expectedHistorySha256','expectedRingSha256')})
        def interrupted(wire):
            self.fixture.fixture.write(self.manager.operations/(native['operationId']+'.json'),service.encode(original),0o600)
            raise OSError('modeled cancellation interrupted after durable native intent')
        with self.assertRaises(OSError):self.execute(request,interrupted)
        continuation=dict(request,admissionId=str(uuid.uuid4()),request=dict(schema=1,action='generation-cancel-recover',
            operationId=native['operationId'],expectedCancellationSha256='5'*64))
        return request,continuation,original

    def test_explicit_cancellation_continuation_settles_original_and_own_intake_once(self):
        request,continuation,original=self.cancellation();self.assertTrue(self.reserve(continuation)['newlyReserved'])
        self.assertEqual(request['admissionId'],self.coordinator.load(continuation['admissionId'])['parentAdmissionId'])
        calls=[]
        def recovered(wire):
            calls.append(1);intent=original['intent'];result=dict(schema=1,operationId=original['operationId'],state='SUCCEEDED',
                action='generation-cancel',preparationId=intent['preparationId'],historySha256=intent['expectedHistorySha256'],
                ringSha256=intent['expectedRingSha256'],cancellationSha256='5'*64,credentialsChanged=False,historyRetained=True)
            self.fixture.fixture.write(self.manager.operations/(original['operationId']+'.json'),service.encode(dict(original,state='SUCCEEDED',response=result)),0o600)
            return result,None
        self.execute(continuation,recovered)
        self.assertEqual('TERMINAL',self.read(request)['state']);self.assertEqual('TERMINAL',self.read(continuation)['state'])
        with self.assertRaises(service.Failure):self.execute(continuation,recovered)
        self.assertEqual([1],calls)

    def test_rejected_continuation_does_not_create_false_absence_receipt_for_existing_native_original(self):
        request,continuation,original=self.cancellation()
        self.fixture.root_result(str(uuid.uuid4()),'backup-create',state='INTENT')
        with self.assertRaises(service.Failure):self.reserve(continuation)
        self.assertIsNone(self.coordinator.load(continuation['admissionId']))
        self.assertEqual('INTAKE',self.read(request)['state']);self.assertEqual(original,self.manager.record(original['operationId']))

    def test_dispatcher_forbids_every_old_mutation_format_for_root_and_recovery_too(self):
        with patch.object(service,'agent_peer',return_value=False):
            for uid in (0,self.core,self.recovery):
                for action in service.SENDER_MUTATIONS:
                    with self.subTest(uid=uid,action=action),self.assertRaises(service.Failure):
                        service.serve_request(self.manager,dict(schema=1,action=action),111,uid,self.core,self.recovery,None)


if __name__=='__main__':unittest.main()
