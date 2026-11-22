#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Private package inventory and actual locks; Root/Main request outcomes are modeled."""
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

import test_key_gwt_sender_namespace as fixtures
lifecycle=fixtures.lifecycle


class GwtClosedIntentInventoryTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.GwtSenderNamespaceTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.policy=self.fixture.policy;self.data=self.fixture.data

    def seed(self,kind='LEGACY',verify=False,closed=True):
        identity=str(uuid.uuid4())
        if kind=='LEGACY':
            identity,slot=self.fixture.legacy();metadata=dict(schema=1,operationId=identity,action='backup-create',operator='model-admin')
            paths={p.name:p for p in slot.iterdir()}
        elif kind=='GENERATION':
            metadata=dict(schema=1,operationId=identity,action='generation-backup-verify' if verify else 'generation-prepare',operator='model-admin')
            if verify:metadata.update(preparationId=str(uuid.uuid4()),expectedRingSha256='1'*64,backupSha256='2'*64)
            else:metadata['expectedSource']=dict(keySha256='1'*64,ringSha256=None)
            path=self.data/'gateway-key-generations'/(identity+'.json');self.fixture.file(path,lifecycle.encoded(metadata));paths={'intent':path}
        else:
            metadata=dict(schema=1,action='generation-handoff-create',operator='model-admin',expectedRingSha256='1'*64,
                expectedCohortSha256='2'*64,**{key:str(uuid.uuid4()) for key in lifecycle.HANDOFF_IDS})
            identity=metadata['handoffId'];path=self.data/'gateway-key-handoffs'/(identity+'.json');self.fixture.file(path,lifecycle.encoded(metadata));paths={'intent':path}
        parent=self.data/'gateway-key-admissions'
        if not parent.exists():self.fixture.directory(parent)
        slot=parent/identity;self.fixture.directory(slot);admission=str(uuid.uuid4())
        attempt=dict(schema=1,purpose='yofc.kura.sender-attempt.v1',admissionId=admission,kind=kind,nativeOperationId=identity,request=metadata)
        raw=lifecycle.encoded(attempt);self.fixture.file(slot/'intent.json',raw);self.fixture.file(slot/'complete',(hashlib.sha256(raw).hexdigest()+'\n').encode())
        namespace=dict(schema=1,namespaceSha256=self.fixture.binding['namespaceSha256']);self.fixture.file(slot/'namespace.json',lifecycle.encoded(namespace))
        receipt=dict(schema=1,purpose='yofc.kura.gwt-unconsumed-intent.v1',admissionId=admission,kind=kind,nativeOperationId=identity,
            namespaceSha256=namespace['namespaceSha256'],files={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in paths.items()})
        if closed:self.fixture.file(slot/'closed.json',lifecycle.encoded(receipt))
        root=dict(schema=1,purpose=lifecycle.SENDER_ADMISSION_PURPOSE,admissionId=admission,source='gwt',namespaceSha256=namespace['namespaceSha256'],
            owner=dict(pid=111,uid=self.fixture.uid,startTicks='1',bootId=str(uuid.uuid4())),requestTag='a'*64,
            target=dict(directory='handoffs' if kind=='HANDOFF' else 'operations',operationId=identity,action=metadata['action'],requestTag='a'*64,continuation=False),
            parentAdmissionId=None,state='NOT_ADMITTED')
        self.write_root(root)
        return slot,paths,root

    def write_root(self,value):
        value=dict(value);value.pop('receiptTag',None);value['receiptTag']=hmac.new(self.fixture.secret,lifecycle.SENDER_ADMISSION_CONTEXT+lifecycle.encoded(value),hashlib.sha256).hexdigest()
        self.fixture.fixture.write(self.policy.state/'sender-admissions'/(value['admissionId']+'.json'),lifecycle.encoded(value),0o600)

    def rejected(self):
        with self.assertRaises((lifecycle.Refused,OSError)):self.fixture.check()

    def test_all_original_intent_types_only_settle_with_bound_root_and_retained_bytes(self):
        for kind,verify in [('LEGACY',False),('GENERATION',False),('GENERATION',True),('HANDOFF',False)]:self.seed(kind,verify)
        before=self.fixture.snapshot();self.assertEqual(4,self.fixture.check());self.assertEqual(before,self.fixture.snapshot())

    def test_root_non_admission_without_explicit_private_closure_does_not_settle_the_intent(self):
        self.seed('HANDOFF',closed=False);before=self.fixture.snapshot();self.rejected();self.assertEqual(before,self.fixture.snapshot())

    def test_root_intake_without_native_original_cannot_be_hidden_by_a_private_closure(self):
        _,_,root=self.seed('GENERATION');self.write_root(dict(root,state='INTAKE'));self.rejected()

    def test_another_native_action_or_directory_does_not_match_the_original_closed_intent(self):
        _,_,root=self.seed('HANDOFF');target=dict(root['target'],directory='operations',action='backup-create');self.write_root(dict(root,target=target));self.rejected()

    def test_foreign_namespace_and_wrong_closed_fingerprint_remain_unresolved(self):
        slot,_,_=self.seed();receipt=json.loads((slot/'closed.json').read_bytes());receipt['namespaceSha256']='f'*64
        self.fixture.file(slot/'closed.json',lifecycle.encoded(receipt));self.rejected()

    def test_changed_or_missing_original_intent_is_never_skipped(self):
        _,paths,_=self.seed('GENERATION');self.fixture.file(paths['intent'],b'{}');self.rejected()

    def test_arbitrary_file_names_are_rejected_before_any_other_private_file_is_opened(self):
        slot,_,_=self.seed();value=json.loads((slot/'closed.json').read_bytes());value['files']['../../outside']='a'*64
        self.fixture.file(slot/'closed.json',lifecycle.encoded(value));self.rejected()

    def test_legacy_closure_cannot_ignore_an_added_partial_result(self):
        _,paths,_=self.seed();self.fixture.file(paths['request.json'].parent/'result.json',b'{}');self.rejected()

    def test_a_cross_directory_root_record_cannot_be_concealed_by_non_admission(self):
        slot,_,_=self.seed();self.fixture.fixture.write(self.policy.state/'startups'/(slot.name+'.json'),b'{}',0o600);self.rejected()

    def test_the_package_gate_uses_the_actual_java_legacy_key_lock(self):
        lock=self.data/'gateway-key-operations/.key.lock'
        script="import fcntl,sys;f=open(sys.argv[1],'r+');fcntl.lockf(f,fcntl.LOCK_EX);print('HELD',flush=True);sys.stdin.readline()"
        process=subprocess.Popen([sys.executable,'-B','-c',script,str(lock)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual('HELD',process.stdout.readline().strip());self.rejected()
        finally:process.communicate('\n',timeout=3)
        self.assertEqual(0,self.fixture.check())


if __name__=='__main__':unittest.main()
