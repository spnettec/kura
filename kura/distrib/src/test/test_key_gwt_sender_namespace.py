#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""New private fixtures only. Main/systemd and Root results are explicit models."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/bin'))
import kura_key_service as service
import kura_key_service_lifecycle as lifecycle
import test_key_service_lifecycle as fixtures


class GwtSenderNamespaceTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LifecycleTest(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.policy = self.fixture.policy; self.policy.initialize()
        self.secret = secrets.token_bytes(32)
        self.fixture.write(self.policy.state/'journal.key', self.secret, 0o600)
        self.uid = os.geteuid() or 65534
        self.data = self.policy.path('/srv/kura-data'); self.data.mkdir(parents=True, mode=0o700)
        self.binding = dict(schema=1, purpose=lifecycle.GWT_BINDING_PURPOSE,
            **lifecycle.gwt_namespace(self.policy.state, self.secret), dataDirectory='/srv/kura-data',
            dataDevice=str(self.data.stat().st_dev), dataInode=str(self.data.stat().st_ino), dataUid=self.uid)
        self.file(self.data/'.gateway-key-admission.lock', b'')
        for directory, lock, _ in lifecycle.GwtSenderInventory.JOURNALS.values():
            self.directory(self.data/directory); self.file(self.data/directory/lock, b'')
        self.file(self.data/'gateway-key-namespace.json', lifecycle.encoded(self.binding))
        self.fixture.write(self.policy.state/'gwt-sender.json', lifecycle.encoded(self.binding), 0o600)
        if os.geteuid() == 0: os.chown(self.data, self.uid, 0)
        self.manager = service.Manager(self.fixture.root, os.geteuid())
        self.owner_calls = []
        self.manager.gwt_sender_owner = lambda *args: self.owner_calls.append(args)
        self.account = patch.object(lifecycle.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=self.uid))
        self.account.start(); self.addCleanup(self.account.stop)

    def directory(self, path):
        path.mkdir(mode=0o700)
        if os.geteuid() == 0: os.chown(path, self.uid, 0)

    def file(self, path, raw):
        path.write_bytes(raw); path.chmod(0o600)
        if os.geteuid() == 0: os.chown(path, self.uid, 0)

    def request(self):
        return dict(schema=1, action='gwt-sender-bind', **{k: self.binding[k]
            for k in lifecycle.GWT_DATA_FIELDS | lifecycle.GWT_NAMESPACE_FIELDS})

    def snapshot(self):
        return {str(p): (*lifecycle.GwtSenderInventory.identity(p.lstat()), hashlib.sha256(p.read_bytes()).hexdigest())
            for p in self.fixture.root.rglob('*') if p.is_file()}

    def check(self):
        with self.policy.gwt_locked() as inventory:
            return inventory.check()

    def root_result(self, identity, action, response=None, state='SUCCEEDED'):
        if response is None:
            response=dict(schema=1,operationId=identity,state='SUCCEEDED',action=action,
                backup=dict(format=lifecycle.FORMAT,operationId=identity,encrypted='YQ=='))
        value=dict(schema=1,operationId=identity,action=action,requestTag='a'*64,state=state,
            response=None if state=='INTENT' else response)
        lifecycle.validate_record(value,identity)
        self.fixture.write(self.policy.state/'operations'/(identity+'.json'),lifecycle.encoded(value),0o600)
        return value

    def legacy(self, *, cached=None):
        identity=str(uuid.uuid4());slot=self.data/'gateway-key-operations'/identity;self.directory(slot)
        request=dict(schema='yofc.kura.gateway-key.request.v1',operationId=identity,action='backup-create',
            operator='model-admin',createdAtUnixMs=1)
        raw=json.dumps(request,separators=(',',':')).encode();digest=hashlib.sha256(raw).hexdigest()
        self.file(slot/'request.json',raw);self.file(slot/'request-complete',(digest+'\n').encode())
        if cached is not None:
            cached=dict(cached,operationId=identity,action='backup-create')
            result=lifecycle.encoded(dict(schema='yofc.kura.gateway-key.result.v1',requestSha256=digest,result=cached))
            self.file(slot/'result.json',result);self.file(slot/'result-complete',(hashlib.sha256(result).hexdigest()+'\n').encode())
        return identity,slot

    def generation(self, *, verify=False):
        identity=str(uuid.uuid4());action='generation-backup-verify' if verify else 'generation-prepare'
        intent=dict(schema=1,action=action,operationId=identity,operator='model-admin')
        result=dict(schema=1,action=action,operationId=identity,state='SUCCEEDED',published=False,requiresExplicitCommit=True)
        if verify:
            preparation=str(uuid.uuid4());intent.update(preparationId=preparation,expectedRingSha256='3'*64,backupSha256='4'*64)
            result.update(preparationId=preparation,ringSha256='3'*64,backupSha256='4'*64)
        else:
            source=dict(keySha256='1'*64,ringSha256=None);intent['expectedSource']=source
            generation=dict(ringSha256='3'*64,legacyKeySha256='1'*64,activeKeySha256='2'*64,keySha256s=['1'*64,'2'*64])
            result.update(source=source,generation=generation,historySha256='5'*64,
                backup=dict(format=lifecycle.GENERATION_FORMAT,operationId=identity,encrypted='YQ=='))
        self.file(self.data/'gateway-key-generations'/(identity+'.json'),lifecycle.encoded(intent))
        self.root_result(identity,action,result)
        return identity,intent

    def handoff(self):
        intent=dict(schema=1,action='generation-handoff-create',operator='model-admin',
            expectedRingSha256='3'*64,expectedCohortSha256='4'*64,**{k:str(uuid.uuid4()) for k in lifecycle.HANDOFF_IDS})
        identity=intent['handoffId'];self.file(self.data/'gateway-key-handoffs'/(identity+'.json'),lifecycle.encoded(intent))
        value=dict(schema=1,purpose='yofc-kura-generation-handoff-v1',request=intent,
            requestTag=hmac.new(self.secret,lifecycle.encoded(intent),hashlib.sha256).hexdigest(),
            owner=dict(pid=111,uid=self.uid,startTicks='1',bootId=str(uuid.uuid4()),invocationId='a'*32,lockDevice=0,lockInode=1),
            source=dict(keySha256='1'*64,ringSha256=None),
            generation=dict(ringSha256='3'*64,legacyKeySha256='1'*64,activeKeySha256='2'*64,keySha256s=['1'*64,'2'*64]),
            historySha256='5'*64,nonce='6'*64,issuedBoottimeNs=1,expiresBoottimeNs=900000000001,issuedAt=1,expiresAt=901)
        value['receiptTag']=hmac.new(self.secret,b'yofc-kura-generation-handoff-receipt-v1\0'+lifecycle.encoded(value),hashlib.sha256).hexdigest()
        self.fixture.write(self.policy.state/'handoffs'/(identity+'.json'),lifecycle.encoded(value),0o400)
        return identity,intent

    def no_dispatch(self, identity=None):
        identity=identity or str(uuid.uuid4());parent=self.data/'gateway-key-not-dispatched'
        if not parent.exists():self.directory(parent)
        slot=parent/identity;self.directory(slot)
        receipt=dict(schema='yofc.kura.gateway-key.no-dispatch.v1',kind='LEGACY',dataDirectory='/srv/kura-data',
            dataDevice=self.binding['dataDevice'],dataInode=self.binding['dataInode'],
            request=dict(schema=1,action='backup-create',operationId=identity,operator='model-admin'))
        raw=lifecycle.encoded(receipt);self.file(slot/'receipt.json',raw)
        self.file(slot/'complete',(hashlib.sha256(raw).hexdigest()+'\n').encode());return identity,slot

    def test_registered_empty_inventories_are_read_without_rewriting_files(self):
        before=self.snapshot(); self.assertEqual(0,self.check()); self.assertEqual(before,self.snapshot())

    def test_namespace_is_stable_across_service_objects_and_changes_after_root_secret_replacement(self):
        self.assertEqual(self.manager.gwt_namespace(),service.Manager(self.fixture.root,os.geteuid()).gwt_namespace())
        before=self.snapshot(); self.fixture.write(self.policy.state/'journal.key',secrets.token_bytes(32),0o600)
        with self.assertRaises(lifecycle.Refused):self.check()
        self.assertNotEqual(before,self.snapshot())

    def test_binding_is_idempotent_and_never_admits_a_key_operation(self):
        before=self.snapshot(); result=self.manager.bind_gwt_sender(self.request(),111,self.uid,self.uid)
        self.assertEqual('GWT_SENDER_BOUND',result.pop('state'));self.assertEqual(self.binding,result)
        self.assertEqual(before,self.snapshot());self.assertEqual([(111,self.uid,self.uid)],self.owner_calls)
        self.assertEqual([],list(self.manager.operations.iterdir()))

    @unittest.skipUnless(sys.platform == 'linux', 'Production no-replace renameat2 is Linux-only')
    def test_first_binding_is_immutable_and_persisted_under_root(self):
        p=self.policy.state/'gwt-sender.json';p.unlink()
        self.manager.bind_gwt_sender(self.request(),111,self.uid,self.uid)
        self.assertEqual(self.binding,json.loads(p.read_bytes())); self.assertEqual(0o600,p.stat().st_mode&0o777)
        self.assertEqual(os.geteuid(),p.stat().st_uid)

    def test_reconfiguration_root_replacement_and_false_owner_are_rejected_without_overwrite(self):
        for key,value in (('dataDirectory','/srv/other-data'),('dataInode','99'),('namespaceSha256','0'*64),('dataUid',self.uid+1)):
            with self.subTest(key=key):
                request=self.request(); request[key]=value; before=self.snapshot()
                with self.assertRaises(service.Failure):self.manager.bind_gwt_sender(request,111,self.uid,self.uid)
                self.assertEqual(before,self.snapshot())

    def test_canonical_bounded_data_identity_is_required(self):
        for key,value in (('dataDirectory','/srv/../data'),('dataDirectory','/srv/data/'),('dataDirectory','/'),('dataDirectory','//srv/data'),
                          ('dataDirectory','/srv/\nsecret'),('dataInode','01'),('dataInode','0'),('dataDevice',True),('dataUid',True)):
            with self.subTest(key=key,value=value):
                request=self.request();request[key]=value
                with self.assertRaises(service.Failure):self.manager.bind_gwt_sender(request,111,self.uid,self.uid)

    def test_raw_daemon_mutations_are_refused_before_any_component(self):
        with patch.object(service,'agent_peer',return_value=False):
            for action in service.GWT_MUTATIONS:
                with self.subTest(action=action), self.assertRaises(service.Failure) as error:
                    service.serve_request(self.manager,dict(schema=1,action=action),111,self.uid,self.uid,self.uid+1,None)
                self.assertEqual('FORBIDDEN',error.exception.reason)
        self.assertEqual([],list(self.manager.operations.iterdir()))

    def test_envelope_requires_the_same_persisted_binding_and_allows_only_fixed_gwt_actions(self):
        inner=dict(schema=1,action='backup-create',operationId=str(uuid.uuid4()),passphrase='synthetic-only')
        envelope=dict(schema=1,action='gwt-bound-request',binding=dict(self.binding),request=inner)
        self.assertEqual(inner,self.manager.unwrap_gwt_request(envelope,111,self.uid,self.uid))
        before=self.snapshot();envelope['binding']['dataInode']='999'
        with self.assertRaises(service.Failure):self.manager.unwrap_gwt_request(envelope,111,self.uid,self.uid)
        self.assertEqual(before,self.snapshot());envelope['binding']=dict(self.binding);envelope['request']['action']='core-start'
        with self.assertRaises(service.Failure):self.manager.unwrap_gwt_request(envelope,111,self.uid,self.uid)

    def test_main_identity_is_required_and_no_registered_writer_lease_is_assumed_for_legacy_keys(self):
        owner=service.Manager.gwt_sender_owner.__get__(self.manager)
        state=dict(ActiveState='active',SubState='running',ControlPID='0',MainPID='111',
            ControlGroup='/system.slice/kura.service',InvocationID='a'*32)
        core=SimpleNamespace(unit=lambda **kw:state,process_group=lambda pid:'/system.slice/kura.service')
        self.manager.generation_component=lambda:(core,None)
        self.manager.writer_process=lambda pid:(self.uid,'321')
        owner(111,self.uid,self.uid)
        for change in ({'MainPID':'112'},{'ActiveState':'inactive'},{'ControlPID':'2'},{'InvocationID':''}):
            with patch.dict(state,change),self.assertRaises(service.Failure):owner(111,self.uid,self.uid)
        with self.assertRaises(service.Failure):owner(111,0,self.uid)
        core.process_group=lambda pid:'/system.slice/foreign.service'
        with self.assertRaises(service.Failure):owner(111,self.uid,self.uid)

    def test_moved_data_directory_or_local_namespace_is_refused(self):
        before=self.snapshot();marker=self.data/'gateway-key-namespace.json';value=dict(self.binding);value['namespaceSha256']='e'*64
        self.file(marker,lifecycle.encoded(value))
        with self.assertRaises(lifecycle.Refused):self.check()
        self.file(marker,lifecycle.encoded(self.binding));self.data.rename(self.data.with_name('old-data'));self.data.mkdir(mode=0o700)
        if os.geteuid()==0:os.chown(self.data,self.uid,0)
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_actual_posix_lock_from_an_independent_process_blocks_the_package_reader(self):
        script="import fcntl,sys;f=open(sys.argv[1],'r+');fcntl.lockf(f,fcntl.LOCK_EX|fcntl.LOCK_NB);print('LOCKED',flush=True);sys.stdin.read()"
        child=subprocess.Popen([sys.executable,'-B','-c',script,str(self.data/'.gateway-key-admission.lock')],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual('LOCKED',child.stdout.readline().strip());before=self.snapshot()
            with self.assertRaises(lifecycle.Refused):self.check()
            self.assertEqual(before,self.snapshot())
        finally:
            child.stdin.close();child.wait(timeout=5);child.stdout.close()

    def test_unsafe_or_linked_local_metadata_is_refused_without_repair(self):
        marker=self.data/'gateway-key-namespace.json';marker.chmod(0o640)
        with self.assertRaises(lifecycle.Refused):self.check()
        marker.chmod(0o600);alias=self.data/'alias';os.link(marker,alias)
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_unregistered_legacy_discovery_is_not_claimed_as_covered(self):
        (self.policy.state/'gwt-sender.json').unlink()
        with self.policy.gwt_locked() as inventory:self.assertIsNone(inventory)

    def test_missing_or_intent_root_result_refuses_upgrade_before_stopping_any_unit(self):
        identity,_=self.legacy();before=self.snapshot()
        with self.assertRaises((lifecycle.Refused,OSError)):self.policy.enter('upgrade')
        self.assertFalse(any(call[1]=='stop' for call in self.fixture.calls));self.assertEqual(before,self.snapshot())
        self.root_result(identity,'backup-create',state='INTENT')
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_legacy_success_requires_the_actual_root_result_even_with_a_saved_local_success(self):
        identity,slot=self.legacy();root=self.root_result(identity,'backup-create')
        self.assertEqual(1,self.check())
        raw=self.read_request(slot);digest=hashlib.sha256(raw).hexdigest()
        saved=lifecycle.encoded(dict(schema='yofc.kura.gateway-key.result.v1',requestSha256=digest,
            result=dict(operationId=identity,action='backup-create',state='SUCCEEDED',resultSource='ROOT_ORIGINAL',original=root['response'])))
        self.file(slot/'result.json',saved);self.file(slot/'result-complete',(hashlib.sha256(saved).hexdigest()+'\n').encode())
        self.assertEqual(1,self.check());(self.policy.state/'operations'/(identity+'.json')).unlink()
        with self.assertRaises((lifecycle.Refused,OSError)):self.check()

    def read_request(self,slot):return (slot/'request.json').read_bytes()

    def test_proven_server_preflight_is_accepted_but_old_root_preflight_plus_absence_is_not(self):
        identity,slot=self.legacy(cached=dict(state='REJECTED',resultSource='SERVER_PREFLIGHT',error='UNAVAILABLE'))
        self.assertEqual(1,self.check());raw=json.loads((slot/'result.json').read_bytes());raw['result']['resultSource']='ROOT_PREFLIGHT'
        encoded=lifecycle.encoded(raw);self.file(slot/'result.json',encoded);self.file(slot/'result-complete',(hashlib.sha256(encoded).hexdigest()+'\n').encode())
        with self.assertRaises((lifecycle.Refused,OSError)):self.check()

    def test_generation_prepare_and_verification_require_matching_original_metadata(self):
        self.generation();identity,_=self.generation(verify=True);self.assertEqual(2,self.check())
        path=self.policy.state/'operations'/(identity+'.json');record=json.loads(path.read_bytes());record['response']['backupSha256']='f'*64
        self.fixture.write(path,lifecycle.encoded(record),0o600)
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_handoff_inventory_requires_the_authenticated_root_authority_not_publication_or_start_assumptions(self):
        identity,_=self.handoff();self.assertEqual(1,self.check())
        path=self.policy.state/'handoffs'/(identity+'.json');record=json.loads(path.read_bytes());record['receiptTag']='0'*64
        self.fixture.write(path,lifecycle.encoded(record),0o400)
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_complete_no_dispatch_receipt_is_read_without_mutation_and_cannot_conceal_a_root_operation(self):
        identity,slot=self.no_dispatch();before=self.snapshot();self.assertEqual(0,self.check());self.assertEqual(before,self.snapshot())
        self.root_result(identity,'backup-create')
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_no_dispatch_cannot_conceal_any_of_the_five_fixed_handoff_ids(self):
        _,grant=self.handoff();self.no_dispatch(grant['publicationId'])
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_no_dispatch_with_torn_hash_or_wrong_data_inode_is_not_rebuilt(self):
        _,slot=self.no_dispatch();self.file(slot/'complete',b'0'*64+b'\n');before=self.snapshot()
        with self.assertRaises(lifecycle.Refused):self.check()
        self.assertEqual(before,self.snapshot());value=json.loads((slot/'receipt.json').read_bytes());value['dataInode']='999'
        raw=lifecycle.encoded(value);self.file(slot/'receipt.json',raw);self.file(slot/'complete',(hashlib.sha256(raw).hexdigest()+'\n').encode())
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_colliding_local_id_or_unknown_fields_are_not_ignored(self):
        identity,intent=self.generation();self.no_dispatch(identity)
        with self.assertRaises(lifecycle.Refused):self.check()
        p=self.data/'gateway-key-generations'/(identity+'.json');intent['passphrase']='must-not-be-present';self.file(p,lifecycle.encoded(intent))
        with self.assertRaises(lifecycle.Refused):self.check()

    def test_new_package_gate_holds_the_core_lock_until_after_stop_units(self):
        self.assertEqual(0,self.check());observed=[];original=self.policy.stop_units
        def stopping():
            script="import fcntl,sys;f=open(sys.argv[1],'r+');fcntl.lockf(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
            result=subprocess.run([sys.executable,'-B','-c',script,str(self.data/'.gateway-key-admission.lock')],capture_output=True)
            observed.append(result.returncode);original()
        self.policy.stop_units=stopping;self.policy.enter('upgrade');self.assertEqual(1,len(observed));self.assertNotEqual(0,observed[0])


if __name__=='__main__':unittest.main()
