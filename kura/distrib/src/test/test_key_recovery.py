#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""New cold-recovery adapter contracts. Never contact an installed gateway."""
import copy
from contextlib import closing
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/bin'))
import kura_key_recovery as recovery
from sender_admission_model import SenderModel
protocol = recovery.protocol
PASSWORD = 'synthetic cold recovery passphrase 52!'
SHA = hashlib.sha256(b'isolated cold adapter synthetic key').hexdigest()
BACKUP = dict(format=protocol.FORMAT, operationId=str(uuid.uuid4()), encrypted='fixture-ciphertext')
RING = hashlib.sha256(b'isolated cold adapter synthetic ring').hexdigest()
LEGACY = hashlib.sha256(b'isolated cold adapter synthetic prior generation').hexdigest()
NAMESPACE = hashlib.sha256(b'isolated cold adapter synthetic root namespace').hexdigest()


class FakeRoot:
    def __init__(self):
        self.writes=0;self.calls=[];self.records={};self.key_ready=False;self.loss=False;self.intent_only=False

    def __call__(self, request):
        action=request['action'];self.calls.append(action)
        if action=='status':return dict(schema=1,keyReady=self.key_ready,keySha256=SHA,legacyKey=False,agentRequired=False)
        if action=='operation-read':return copy.deepcopy(self.records.get(request['operationId'],dict(schema=1,state='NOT_FOUND')))
        if action=='backup-inspect':
            if request['passphrase']!=PASSWORD:return dict(schema=1,error='BACKUP_REJECTED')
            return dict(schema=1,backupOperationId=request['backup']['operationId'],keySha256=SHA,createdAt='2026-11-15T00:00:00Z',sameDeviceKey=True,keyReady=self.key_ready,restoreAllowed=not self.key_ready)
        if action=='restore':
            self.writes+=1;self.key_ready=True;identity=request['operationId']
            self.records[identity]=(dict(schema=1,operationId=identity,state='UNKNOWN') if self.intent_only else
                dict(schema=1,operationId=identity,state='SUCCEEDED',action='restore',keySha256=SHA,keyChanged=True,existingReceiptPreserved=True))
            if self.loss:raise OSError('Synthetic reply loss')
            return copy.deepcopy(self.records[identity])
        raise AssertionError('Unexpected Root action')


class GenerationRoot(FakeRoot):
    def __init__(self):
        super().__init__()
        self.ring_ready = False
        self.start_allowed = True
        self.starts = {}

    def __call__(self, request):
        action = request['action']
        if action == 'status':
            return dict(schema=1, error='GENERATION_REQUIRED')
        if action == 'generation-recovery-status':
            return dict(schema=1, activeKeySha256=SHA, ringSha256=RING, activeKeyReady=self.key_ready,
                        keyringReady=self.ring_ready, namespaceSha256=NAMESPACE)
        if action == 'generation-backup-inspect':
            if request['passphrase'] != PASSWORD:
                return dict(schema=1, error='BACKUP_REJECTED')
            return dict(schema=1, backupOperationId=request['backup']['operationId'], createdAt='2026-11-22T00:00:00Z',
                        ringSha256=RING, activeKeySha256=SHA, legacyKeySha256=LEGACY, keySha256s=[LEGACY,SHA],
                        matchesRetainedReceipt=True, activeKeyReady=self.key_ready, keyringReady=self.ring_ready,
                        restoreSupported=True, restoreAllowed=not (self.key_ready and self.ring_ready),
                        restoreBlockedByUnresolvedOperation=False)
        if action == 'generation-restore':
            assert request['expectedKeySha256'] == SHA and request['expectedRingSha256'] == RING
            self.writes += 1
            identity = request['operationId']
            if self.intent_only:
                self.records[identity] = dict(schema=1, state='UNKNOWN', operationId=identity)
                raise OSError('Interrupted original restore')
            result = dict(schema=1, operationId=identity, action=action, state='SUCCEEDED',
                          activeKeySha256=SHA, ringSha256=RING, activeKeyRestored=not self.key_ready,
                          keyringRestored=not self.ring_ready, existingReceiptPreserved=True)
            self.records[identity] = result
            self.key_ready = self.ring_ready = True
            return result
        if action == 'generation-recovery-start-check':
            if not self.start_allowed:
                return dict(schema=1, error='CONFLICT')
            return dict(schema=1, state='GENERATION_RECOVERY_START_READY')
        if action == 'core-start-read':
            return self.starts.get(request['operationId'], dict(schema=1, state='NOT_FOUND'))
        if action == 'core-start-plan':
            return dict(schema=1, state='START_PLAN', startAllowed=False, maintenanceId=None,
                        predecessorStartOperationId=None, manifestSha256=None, blockingOperationId=None)
        if action == 'core-start':
            result = dict(schema=1, operationId=request['operationId'], restoreOperationId=request['restoreOperationId'],
                          action=action, state='SUCCEEDED', keySha256=SHA, scope='SYSTEMD_JOB_ACCEPTED',
                          jobPath='/org/freedesktop/systemd1/job/13')
            self.starts[request['operationId']] = result
            return result
        return super().__call__(request)


class Fixture:
    def setUp(self):
        prior=os.umask(0o077);self.addCleanup(os.umask,prior)
        temporary=tempfile.TemporaryDirectory(prefix='kura-new-cold-ui-');self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name);self.root=FakeRoot()
        self.journal=recovery.Journal(self.path)
        self.controller=recovery.Controller(self.root,self.journal, sender=SenderModel())
        self.request=dict(operationId=str(uuid.uuid4()),expectedKeySha256=SHA,
                          backupJson=json.dumps(BACKUP),passphrase=PASSWORD)

    def failure(self,reason,call):
        with self.assertRaises(protocol.Failure) as found:call()
        self.assertEqual(reason,found.exception.reason)


class AdapterTest(Fixture, unittest.TestCase):
    def test_production_entrypoint_requires_a_distinct_nonlogin_recovery_identity(self):
        for uid,recovery_uid,daemon_uid,shell in [(0,998,997,'/usr/sbin/nologin'),
                (997,997,997,'/usr/sbin/nologin'),(501,998,997,'/usr/sbin/nologin'),(998,998,997,'/bin/sh')]:
            def account(name):return SimpleNamespace(pw_uid=recovery_uid if name=='kura-key-recovery' else daemon_uid,pw_shell=shell)
            with patch.object(recovery.os,'geteuid',return_value=uid),patch.object(recovery.sys,'platform','linux'),patch.object(recovery.pwd,'getpwnam',side_effect=account):
                self.failure('FORBIDDEN',recovery.serve)

    def test_correct_material_dispatches_once_and_journal_contains_public_hashes_only(self):
        result=self.controller.restore(self.request)
        self.assertEqual('SUCCEEDED',result['state']);self.assertEqual(1,self.root.writes)
        raw=next(self.journal.operations.iterdir()).read_bytes()
        self.assertNotIn(PASSWORD.encode(),raw);self.assertNotIn(BACKUP['encrypted'].encode(),raw)
        self.assertEqual({'schema','operationId','expectedKeySha256','backupSha256'},set(json.loads(raw)))
        self.assertEqual(0o600,next(self.journal.operations.iterdir()).stat().st_mode&0o777)

    def test_restart_and_same_uuid_never_redispatch_even_with_wrong_password(self):
        original=self.controller.restore(self.request)
        self.request['passphrase']='changed synthetic passphrase'
        restarted=recovery.Controller(self.root,recovery.Journal(self.path), sender=SenderModel())
        self.assertEqual(original,restarted.restore(self.request));self.assertEqual(1,self.root.writes)

    def test_lost_write_reply_uses_proven_original_success(self):
        self.root.loss=True
        self.assertEqual('ROOT_ORIGINAL',self.controller.restore(self.request)['resultSource'])
        self.assertEqual(1,self.root.writes)

    def test_present_key_never_settles_unknown_and_blocks_new_uuid(self):
        self.root.loss=True;self.root.intent_only=True
        self.assertEqual('UNKNOWN',self.controller.restore(self.request)['state'])
        self.assertTrue(self.root.key_ready)
        self.assertEqual('UNKNOWN',self.controller.original(self.request['operationId'])['state'])
        self.assertEqual('UNKNOWN',self.controller.restore(self.request)['state'])
        other=dict(self.request,operationId=str(uuid.uuid4()))
        self.failure('UNRESOLVED_OPERATION',lambda:self.controller.restore(other))
        self.assertEqual(1,self.root.writes)

    def test_intent_without_any_root_record_survives_restart_and_never_retries(self):
        self.journal.admit(dict(schema=1,operationId=self.request['operationId'],expectedKeySha256=SHA,
            backupSha256=hashlib.sha256(protocol.encode(BACKUP)).hexdigest()))
        restarted=recovery.Controller(self.root,recovery.Journal(self.path), sender=SenderModel())
        self.assertEqual('UNKNOWN',restarted.restore(self.request)['state']);self.assertEqual(0,self.root.writes)

    def test_existing_root_original_without_local_slot_is_never_dispatched(self):
        self.root.records[self.request['operationId']]=dict(schema=1,operationId=self.request['operationId'],
            state='SUCCEEDED',action='restore',keySha256=SHA,keyChanged=True,existingReceiptPreserved=True)
        self.assertEqual('SUCCEEDED',self.controller.restore(self.request)['state'])
        self.assertEqual(0,self.root.writes);self.assertEqual([],list(self.journal.operations.iterdir()))

    def test_existing_key_conflict_is_rejected_before_journal_and_writer(self):
        self.root.key_ready=True
        self.failure('CONFLICT',lambda:self.controller.restore(self.request))
        self.assertEqual(0,self.root.writes);self.assertEqual([],list(self.journal.operations.iterdir()))

    def test_foreign_retained_fingerprint_is_rejected_before_material_or_writer(self):
        self.request['expectedKeySha256']='a'*64
        self.failure('CONFLICT',lambda:self.controller.restore(self.request))
        self.assertNotIn('backup-inspect',self.root.calls);self.assertEqual(0,self.root.writes)

    def test_wrong_password_creates_no_admission(self):
        self.request['passphrase']='wrong synthetic recovery passphrase'
        self.failure('BACKUP_REJECTED',lambda:self.controller.restore(self.request))
        self.assertEqual([],list(self.journal.operations.iterdir()));self.assertEqual(0,self.root.writes)

    def test_duplicate_backup_json_keys_are_rejected_before_root_call(self):
        self.request['backupJson']='{"format":"x","format":"y"}'
        self.failure('INVALID_ARGUMENT',lambda:self.controller.restore(self.request))
        self.assertEqual([],self.root.calls)

    def test_unknown_paths_actions_and_extra_fields_never_reach_root(self):
        self.request['path']='/etc/kura/credentials/kura_encryption_key'
        self.failure('INVALID_ARGUMENT',lambda:self.controller.restore(self.request))
        self.assertEqual([],self.root.calls)

    def test_different_backup_for_admitted_uuid_conflicts_without_second_writer(self):
        self.controller.restore(self.request)
        self.request['backupJson']=json.dumps(dict(BACKUP,encrypted='another-fixture-ciphertext'))
        self.failure('CONFLICT',lambda:self.controller.restore(self.request));self.assertEqual(1,self.root.writes)

    def test_torn_and_symlinked_journal_slots_block_new_work(self):
        identity=str(uuid.uuid4());path=self.journal.operations/(identity+'.json');path.write_bytes(b'{');path.chmod(0o600)
        self.failure('INVALID_ARGUMENT',lambda:self.controller.restore(self.request));self.assertEqual(0,self.root.writes)
        path.unlink();path.symlink_to(self.path/'admission.lock')
        with self.assertRaises(OSError):self.controller.restore(self.request)
        self.assertEqual(0,self.root.writes)

    def test_busy_admission_never_dispatches(self):
        with self.journal.lock():self.failure('BUSY',lambda:self.controller.restore(self.request))
        self.assertEqual(0,self.root.writes)

    def test_reading_original_does_not_repair_or_add_local_records(self):
        identity=str(uuid.uuid4());self.assertEqual('UNKNOWN',self.controller.original(identity)['state'])
        self.assertEqual([],list(self.journal.operations.iterdir()));self.assertEqual(0,self.root.writes)

    def test_inspection_does_not_allow_same_key_noop_in_cold_ui(self):
        self.root.key_ready=True
        value=self.controller.inspect(dict(backupJson=json.dumps(BACKUP),passphrase=PASSWORD))
        self.assertFalse(value['restoreAllowed']);self.assertEqual(0,self.root.writes)


class HttpTest(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.key=self.path/'tls.key';self.cert=self.path/'tls.crt'
        subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
            '-subj','/CN=localhost','-keyout',str(self.key),'-out',str(self.cert)],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=20)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_2;tls.load_cert_chain(self.cert,self.key)
        assets=Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/share/key-recovery'
        self.server=recovery.RecoveryServer(('127.0.0.1',0),self.controller,tls,assets)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.origin='https://127.0.0.1:'+str(self.server.server_port)

    def post(self,path,body,headers=None):
        defaults={'Host':'127.0.0.1:'+str(self.server.server_port),'Origin':self.origin,
            'Content-Type':'application/json','X-Kura-Recovery-CSRF':self.server.token,
            'Cookie':recovery.COOKIE+'='+self.server.token}
        defaults.update(headers or {})
        stream=http.client.HTTPSConnection('127.0.0.1',self.server.server_port,context=ssl._create_unverified_context(),timeout=10)
        stream.request('POST',path,json.dumps(body),defaults);response=stream.getresponse();raw=response.read();stream.close()
        return response.status,json.loads(raw)

    def test_cross_origin_csrf_cookie_and_rebinding_are_rejected_before_root_call(self):
        for headers in [{'Origin':'https://attacker.invalid'},{'X-Kura-Recovery-CSRF':'wrong'},
            {'Cookie':'another=value'},{'Host':'attacker.invalid:'+str(self.server.server_port)},
            {'Cookie':recovery.COOKIE+'='+self.server.token+'; '+recovery.COOKIE+'='+self.server.token}]:
            status,_=self.post('/api/status',{},headers);self.assertEqual(400,status)
        self.assertEqual([],self.root.calls)

    def test_existing_other_browser_cookies_do_not_break_the_csrf_gate(self):
        status,result=self.post('/api/status',{},dict(Cookie='locale=zh; '+recovery.COOKIE+'='+self.server.token))
        self.assertEqual(200,status);self.assertEqual('STATUS',result['state'])

    def test_known_preflight_rejection_is_explicit_and_does_not_dispatch(self):
        self.root.key_ready=True
        status,result=self.post('/api/restore',self.request)
        self.assertEqual(200,status);self.assertEqual('REJECTED',result['state'])
        self.assertEqual('SERVER_PREFLIGHT',result['resultSource']);self.assertEqual(0,self.root.writes)

    def test_post_admission_reply_loss_stays_unknown_and_is_not_retried(self):
        self.root.loss=True;self.root.intent_only=True
        for _ in range(2):
            status,result=self.post('/api/restore',self.request);self.assertEqual(200,status);self.assertEqual('UNKNOWN',result['state'])
        self.assertEqual(1,self.root.writes)

    def generation_request(self):
        self.root = self.controller.client = GenerationRoot()
        return dict(self.request, expectedRingSha256=RING,
                    backupJson=json.dumps(dict(BACKUP, format=protocol.GENERATION_FORMAT)))

    def test_generation_restore_checks_the_pair_and_only_explicit_start_requests_a_job(self):
        request = self.generation_request()
        self.root.key_ready = True
        code, view = self.post('/api/status', {})
        self.assertEqual(200, code)
        self.assertTrue(view['generation']['activeKeyReady'])
        self.assertFalse(view['keyReady'])
        materials = {key: request[key] for key in ('backupJson', 'passphrase')}
        code, checked = self.post('/api/inspect', materials)
        self.assertEqual(200, code)
        self.assertEqual((SHA, RING, 2, True),
                         tuple(checked[k] for k in ('keySha256','ringSha256','keyCount','restoreAllowed')))
        _, wrong = self.post('/api/restore', dict(request, expectedRingSha256='0'*64))
        self.assertEqual(('REJECTED', 'CONFLICT'), (wrong['state'], wrong['error']))
        self.assertEqual(0, self.root.writes)

        _, restored = self.post('/api/restore', request)
        self.assertEqual(('SUCCEEDED', 'ROOT_ORIGINAL'), (restored['state'], restored['resultSource']))
        self.assertTrue(restored['keyringRestored'])
        self.assertFalse(restored['activeKeyRestored'])
        self.assertEqual({}, self.root.starts)
        journal = self.journal.record(request['operationId'])
        self.assertEqual((2, SHA, RING), (journal['schema'], journal['expectedKeySha256'], journal['expectedRingSha256']))
        self.assertEqual({'schema','operationId','expectedKeySha256','expectedRingSha256','backupSha256'}, set(journal))
        self.assertEqual(restored, self.post('/api/original', {'operationId':request['operationId']})[1])
        start = dict(operationId=str(uuid.uuid4()), restoreOperationId=request['operationId'], expectedKeySha256=SHA)
        self.root.start_allowed = False
        self.assertEqual('REJECTED', self.post('/api/start', start)[1]['state'])
        self.assertEqual({}, self.root.starts)
        self.root.start_allowed = True
        self.assertEqual('SYSTEMD_JOB_ACCEPTED', self.post('/api/start', start)[1]['scope'])
        self.assertEqual('SUCCEEDED', self.post('/api/complete', {'operationId':start['operationId']})[1]['state'])
        self.assertIsNone(self.journal.pending())

    def test_generation_restore_lost_reply_leaves_the_original_pending_and_blocks_another_id(self):
        request = self.generation_request()
        self.root.intent_only = True
        self.assertEqual('UNKNOWN', self.post('/api/restore', request)[1]['state'])
        self.assertEqual('UNKNOWN', self.post('/api/original', {'operationId':request['operationId']})[1]['state'])
        rejected = self.post('/api/restore', dict(request, operationId=str(uuid.uuid4())))[1]
        self.assertEqual(('REJECTED','UNRESOLVED_OPERATION'), (rejected['state'], rejected['error']))
        self.assertEqual(1, self.root.writes)
        self.assertEqual(request['operationId'], self.journal.pending()['operationId'])
        self.assertEqual({}, self.root.starts)

    def test_static_html_sets_secure_cookie_csp_and_no_store(self):
        stream=http.client.HTTPSConnection('127.0.0.1',self.server.server_port,context=ssl._create_unverified_context(),timeout=5)
        stream.request('GET','/');response=stream.getresponse();body=response.read();stream.close()
        self.assertEqual(200,response.status);self.assertEqual('no-store',response.getheader('Cache-Control'))
        self.assertIn('frame-ancestors',response.getheader('Content-Security-Policy'))
        self.assertIn('Secure; HttpOnly; SameSite=Strict; Path=/',response.getheader('Set-Cookie'))
        self.assertIn(self.server.token.encode(),body);self.assertNotIn(b'KURA_RECOVERY_CSRF',body)
        self.assertEqual([],self.root.calls)

    def test_packaged_recovery_script_is_served_with_the_script_content_type(self):
        stream = http.client.HTTPSConnection('127.0.0.1', self.server.server_port,
                                             context=ssl._create_unverified_context(), timeout=5)
        with closing(stream):
            stream.request('GET', '/recovery.js')
            response = stream.getresponse()
            self.assertEqual(200, response.status)
            self.assertEqual('text/javascript; charset=utf-8', response.getheader('Content-Type'))
            self.assertEqual((self.server.assets / 'recovery.js').read_bytes(), response.read())


if __name__=='__main__':
    unittest.main(verbosity=2)
