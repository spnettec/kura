#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Actual private files/locks/Root HMAC. Main, historical native outcomes and backup inspection are models."""
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import ssl
import subprocess
import threading
import unittest
from unittest.mock import patch
import uuid

import test_key_service_lifecycle as original
import kura_key_service as service
import kura_key_recovery as recovery

lifecycle=original.lifecycle


@unittest.skipUnless(sys.platform=='linux','Immutable metadata uses Linux renameat2')
class RecoveryPrivateArchiveTest(unittest.TestCase):
    def setUp(self):
        self.base=original.LifecycleTest();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.policy=self.base.policy;self.policy.initialize()
        self.base.write(self.policy.state/'journal.key',os.urandom(32))
        self.manager=service.Manager(self.base.root,os.geteuid());self.module=self.policy.journal_module()
        self.directory=self.base.root/'var/lib/kura-key-recovery';self.directory.mkdir(mode=0o700)
        self.journal=recovery.Journal(self.directory,archive_module=self.module)
        self.journal.archive_client=self.client;self.history=self.journal.history();self.calls=[]
        self.manager.recovery_sender_owner=lambda *args:None  # Explicit identity/Main model.
        self.secret=self.manager.sender_admissions.secret();self.namespace=self.manager.gwt_namespace()['namespaceSha256']
        self.key=hashlib.sha256(self.base.key).hexdigest();self.lose=None

    def client(self,request):
        self.calls.append(copy.deepcopy(request));action=request['action']
        if action=='gwt-sender-namespace':return dict(schema=1,**self.manager.gwt_namespace())
        if action=='backup-inspect':
            # Authorization contract model; never presented as another real decryption acceptance.
            return dict(schema=1,backupOperationId=request['backup']['operationId'],keySha256=self.key,
                createdAt='2026-11-17T00:00:00Z',sameDeviceKey=True,keyReady=True,restoreAllowed=False)
        if action in service.ARCHIVE_ACTIONS:
            if action=='journal-archive' and self.lose=='before':raise OSError('modeled reply loss before Root original')
            result=self.manager.archive_journal(request,111,os.geteuid(),os.geteuid()+1,os.geteuid())
            if action=='journal-archive' and self.lose=='after':raise OSError('modeled reply loss after Root receipt')
            return result
        raise AssertionError('Private archive must not invoke a key writer: '+action)

    def files(self,directory=None):
        directory=self.directory if directory is None else directory
        return {str(p.relative_to(directory)):(p.read_bytes(),lifecycle.GwtSenderInventory.identity(p.lstat()))
            for p in directory.rglob('*') if p.is_file()}

    def restore(self,*,native=True,identity=None):
        identity=str(uuid.uuid4()) if identity is None else identity
        backup=dict(format=service.FORMAT,operationId=str(uuid.uuid4()),encrypted='YQ==')
        local=dict(schema=1,operationId=identity,expectedKeySha256=self.key,backupSha256=hashlib.sha256(service.encode(backup)).hexdigest())
        self.journal.write_new(self.journal.operations/(identity+'.json'),local)
        if native:
            response=dict(schema=1,action='restore',operationId=identity,state='SUCCEEDED',keySha256=self.key,keyChanged=True,existingReceiptPreserved=True)
            self.manager.atomic(self.manager.operations/(identity+'.json'),service.encode(dict(schema=1,action='restore',operationId=identity,
                requestTag='1'*64,state='SUCCEEDED',response=response)))
        return identity,local,backup

    def start(self,restore=None):
        if restore is None:restore=self.restore()[0]
        identity=str(uuid.uuid4());local=dict(schema=1,operationId=identity,restoreOperationId=restore,expectedKeySha256=self.key)
        self.journal.write_new(self.journal.starts/(identity+'.json'),local)
        native=dict(local,action='core-start');response=dict(schema=1,operationId=identity,restoreOperationId=restore,keySha256=self.key,
            action='core-start',state='SUCCEEDED',scope='SYSTEMD_JOB_ACCEPTED',jobPath='/org/freedesktop/systemd1/job/42')
        parent=self.manager.state/'startups';parent.mkdir(mode=0o700,exist_ok=True)
        self.manager.atomic(parent/(identity+'.json'),service.encode(dict(schema=1,operationId=identity,restoreOperationId=restore,
            keySha256=self.key,requestTag=self.manager.sender_admissions.tag(native),state='SUCCEEDED',response=response)))
        return identity,local

    def negative(self,kind='restore',identity=None,*,owning=False,closed=False):
        identity=str(uuid.uuid4()) if identity is None else identity
        if kind=='restore':
            if owning:identity,local,_=self.restore(native=False,identity=identity)
            else:local=dict(schema=1,operationId=identity,expectedKeySha256=self.key,backupSha256='2'*64)
            metadata=dict(local,action='restore')
        else:
            metadata=dict(schema=1,action='core-start',operationId=identity,restoreOperationId=str(uuid.uuid4()),expectedKeySha256=self.key)
            if owning:self.journal.write_new(self.journal.starts/(identity+'.json'),{k:v for k,v in metadata.items() if k!='action'})
        admission=str(uuid.uuid4());attempt=dict(schema=1,purpose='yofc.kura.sender-attempt.v1',admissionId=admission,kind=kind,nativeOperationId=identity,request=metadata)
        parent=self.directory/'admissions';parent.mkdir(mode=0o700,exist_ok=True);slot=parent/(identity+'-'+kind);slot.mkdir(mode=0o700)
        self.journal.write_new(slot/'intent.json',attempt);self.journal.write_new(slot/'namespace.json',dict(schema=1,namespaceSha256=self.namespace))
        target=self.manager.sender_admissions.native_target(metadata,directory='startups' if kind=='start' else 'operations')
        self.manager.sender_admissions.write(dict(schema=1,purpose=lifecycle.SENDER_ADMISSION_PURPOSE,admissionId=admission,source='recovery',
            namespaceSha256=self.namespace,owner=dict(uid=os.geteuid(),pid=os.getpid(),startTicks='1',bootId=str(uuid.uuid4())),
            requestTag=self.manager.sender_admissions.tag(metadata),target=target,parentAdmissionId=None,state='NOT_ADMITTED'),create=True)
        if closed:
            self.journal.write_new(slot/'closed.json',dict(schema=1,purpose='yofc.kura.sender-not-admitted.v1',admissionId=admission,
                kind=kind,nativeOperationId=identity,namespaceSha256=self.namespace))
            if owning and kind=='restore':self.journal.write_new(slot/'pending.json',dict(schema=1,operationId=identity,expectedKeySha256=self.key))
        return identity,attempt

    def inventory(self):
        fmt=self.module.RecoveryPrivateFormat(self.directory,os.geteuid(),self.directory.stat().st_gid,self.journal.read,self.journal.check_directory)
        return fmt.inventory(self.policy,dict(schema=1,**self.manager.gwt_namespace()))

    def test_preview_is_readonly_and_restore_capacity_retains_all_originals_and_old_ids(self):
        identities=[self.restore()[0] for _ in range(32)];identity=identities[0];before=self.files();root_before=self.files(self.manager.state)
        self.assertEqual('ARCHIVABLE',self.history.archive('RESTORE',identity,preview=True)['state'])
        self.assertEqual(before,self.files());self.assertEqual(root_before,self.files(self.manager.state));self.assertFalse((self.directory/'archives').exists())
        result=self.history.archive('RESTORE',identity);self.assertEqual('ARCHIVE_RECORDED',result['state'])
        self.restore();self.assertEqual(33,len(self.journal.records()));self.assertEqual(32,self.journal.active_count('RESTORE',self.journal.records()))
        for name,value in before.items():self.assertEqual(value,self.files()[name])
        self.assertIn(('RESTORE',identity,None),self.inventory())
        controller=recovery.Controller(self.client,self.journal)
        with patch.object(controller,'original',return_value={'state':'SUCCEEDED'}) as read:
            with self.assertRaises(service.Failure):controller.restore(dict(operationId=identity,expectedKeySha256=self.key,backupJson=json.dumps(dict(format=service.FORMAT,operationId=str(uuid.uuid4()),encrypted='YQ==')),passphrase='synthetic invalid old request passphrase'))
            read.assert_not_called()  # Changed immutable metadata must conflict before a writer.

    def test_start_capacity_and_root_metadata_keep_parent_restore_and_all_originals(self):
        restore=self.restore()[0];identities=[self.start(restore)[0] for _ in range(32)];identity=identities[0];before=self.files()
        self.history.archive('START',identity);self.start(restore)
        self.assertEqual(33,len(self.journal.start_records()));self.assertIn(('START',identity,None),self.inventory())
        for name,value in before.items():self.assertEqual(value,self.files()[name])
        response=self.history.archive('START',identity,preview=True);self.assertEqual(restore,response['correlation']['intent']['restoreOperationId'])

    def test_negative_sender_and_owning_restore_adopt_one_original_root_archive(self):
        identity,attempt=self.negative(owning=True,closed=True);before=self.files();root_before=self.files(self.manager.sender_admissions.directory)
        self.history.archive('RESTORE',identity);self.history.archive('ADMISSION',identity,'restore')
        self.assertEqual(1,len(self.manager.archives()['archived']));self.assertEqual(root_before,self.files(self.manager.sender_admissions.directory))
        self.assertIn(('ADMISSION',identity,'restore'),self.inventory())
        for name,value in before.items():self.assertEqual(value,self.files()[name])

    def test_negative_sender_requires_closed_owning_and_retired_pending_before_archive(self):
        identity,_=self.negative(owning=True);before=self.files()
        with self.assertRaises(lifecycle.Refused):self.history.archive('ADMISSION',identity,'restore')
        self.assertEqual(before,self.files());self.assertFalse((self.directory/'archives').exists())

    def test_sender_capacity_releases_only_positive_metadata_and_never_reuses_attempt(self):
        identities=[self.negative()[0] for _ in range(256)];identity=identities[0]
        self.history.archive('ADMISSION',identity,'restore');self.negative()
        sender=recovery.SenderAdmission(self.client,self.journal);paths=list((self.directory/'admissions').iterdir())
        self.assertEqual(257,len(paths));self.assertEqual(256,self.journal.active_count('ADMISSION',paths))
        attempt=sender.load('restore',identity)[0];request=attempt['request']
        with self.assertRaises(service.Failure):sender.submit('restore',identity,request,lambda:self.fail('old attempt writer'))
        self.assertEqual(1,len(self.manager.archives()['archived']))

    def test_lost_positive_reply_repeated_call_queries_only_and_preserves_every_file(self):
        identity=self.restore()[0];self.lose='after'
        with self.assertRaises(OSError):self.history.archive('RESTORE',identity)
        self.lose=None;before=self.files();root_before=self.files(self.manager.state);count=sum(v['action']=='journal-archive' for v in self.calls)
        self.assertTrue(self.history.archived('RESTORE',identity));self.history.archive('RESTORE',identity)
        self.assertEqual(count,sum(v['action']=='journal-archive' for v in self.calls));self.assertEqual(before,self.files());self.assertEqual(root_before,self.files(self.manager.state))

    def test_missing_root_intent_stays_active_and_cannot_be_late_first_send(self):
        identity=self.restore()[0];self.lose='before'
        with self.assertRaises(OSError):self.history.archive('RESTORE',identity)
        self.lose=None;self.assertFalse(self.history.archived('RESTORE',identity));self.history.archive('RESTORE',identity)
        with self.assertRaises(lifecycle.Refused):self.history.archive('RESTORE',identity,continue_metadata=True)
        self.assertEqual(1,sum(v['action']=='journal-archive' for v in self.calls));self.assertEqual(set(),self.inventory())

    def test_pending_original_requires_explicit_same_metadata_continuation(self):
        identity=self.restore()[0];atomic=self.manager.atomic
        def lose(path,value,**kw):
            if path.name.endswith('.receipt.json'):raise OSError('modeled metadata interruption')
            return atomic(path,value,**kw)
        with patch.object(self.manager,'atomic',side_effect=lose):
            with self.assertRaises(service.Failure):self.history.archive('RESTORE',identity)
        self.assertFalse(self.history.archived('RESTORE',identity));before=self.files(self.manager.state)
        self.history.archive('RESTORE',identity);self.assertEqual(before,self.files(self.manager.state))
        self.assertEqual('ARCHIVE_RECORDED',self.history.archive('RESTORE',identity,continue_metadata=True)['state'])
        self.assertEqual(1,sum(v['action']=='journal-archive' for v in self.calls));self.assertEqual(1,sum(v['action']=='journal-archive-continue' for v in self.calls))

    def test_changed_private_bytes_links_permissions_and_namespace_cannot_free_capacity(self):
        identity=self.restore()[0];self.history.archive('RESTORE',identity);path=self.journal.operations/(identity+'.json');raw=path.read_bytes()
        path.write_bytes(b'{}')
        with self.assertRaises((lifecycle.Refused,KeyError)):self.history.archived('RESTORE',identity)
        path.write_bytes(raw);marker=self.history.format.path('RESTORE',identity);marker.chmod(0o640)
        with self.assertRaises(service.Failure):self.history.archived('RESTORE',identity)
        marker.chmod(0o600);link=self.directory/'linked';os.link(marker,link)
        with self.assertRaises(service.Failure):self.history.archived('RESTORE',identity)
        link.unlink();self.manager.atomic(self.manager.state/'journal.key',os.urandom(32))
        with self.assertRaises(lifecycle.Refused):self.history.archived('RESTORE',identity)

    def test_true_unknown_missing_original_and_foreign_uid_never_get_archive_proof(self):
        identity,_,_=self.restore(native=False);before=self.files()
        with self.assertRaises(service.Failure):self.history.archive('RESTORE',identity)
        self.assertEqual(before,self.files());self.assertFalse((self.directory/'archives').exists())
        request=dict(schema=1,action='journal-archive-recovery-reference-read',namespaceSha256=self.namespace,directory='operations',operationId=identity)
        with self.assertRaises(service.Failure):self.manager.archive_journal(request,111,99999,99999,os.geteuid())

    def test_mutating_api_requires_exact_original_backup_and_root_key_check_and_keeps_secrets_out(self):
        identity,local,backup=self.restore();controller=recovery.Controller(self.client,self.journal)
        request=dict(command='archive',kind='RESTORE',operationId=identity,backupJson=json.dumps(backup),passphrase='synthetic archive authorization only 52!')
        wrong=copy.deepcopy(backup);wrong['encrypted']='Yg=='
        with patch.object(controller,'inspect',return_value=dict(sameDeviceKey=True,keySha256=self.key)) as inspect:
            with self.assertRaises(service.Failure):controller.archive(dict(request,backupJson=json.dumps(wrong)))
            inspect.assert_not_called();self.assertFalse((self.directory/'archives').exists())
            self.assertEqual('ARCHIVE_RECORDED',controller.archive(request)['state']);inspect.assert_called_once()
        for raw,_ in self.files().values():
            self.assertNotIn(request['passphrase'].encode(),raw);self.assertNotIn(json.dumps(backup).encode(),raw)

    def test_readonly_api_needs_no_secret_and_wrong_key_authorization_cannot_archive(self):
        identity,local,backup=self.restore();controller=recovery.Controller(self.client,self.journal)
        with patch.object(controller,'inspect',side_effect=AssertionError('Preview cannot inspect a backup')):
            self.assertEqual('ARCHIVABLE',controller.archive(dict(command='preview',kind='RESTORE',operationId=identity))['state'])
        with patch.object(controller,'inspect',return_value=dict(sameDeviceKey=False,keySha256='f'*64)):
            with self.assertRaises(service.Failure):controller.archive(dict(command='archive',kind='RESTORE',operationId=identity,backupJson=json.dumps(backup),passphrase='synthetic wrong recovery material 52!'))
        self.assertFalse((self.directory/'archives').exists())

    def test_actual_https_route_checks_origin_csrf_cookie_and_material_before_archive(self):
        identity,local,backup=self.restore();controller=recovery.Controller(self.client,self.journal)
        key=self.base.root/'https-test.key';cert=self.base.root/'https-test.crt'
        subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost',
            '-keyout',str(key),'-out',str(cert)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=20)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_2;tls.load_cert_chain(cert,key)
        assets=Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/share/key-recovery'
        server=recovery.RecoveryServer(('127.0.0.1',0),controller,tls,assets)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        origin='https://127.0.0.1:'+str(server.server_port)
        def post(body,extra=None):
            headers={'Host':'127.0.0.1:'+str(server.server_port),'Origin':origin,'Content-Type':'application/json',
                'X-Kura-Recovery-CSRF':server.token,'Cookie':recovery.COOKIE+'='+server.token};headers.update(extra or {})
            connection=http.client.HTTPSConnection('127.0.0.1',server.server_port,context=ssl._create_unverified_context(),timeout=8)
            connection.request('POST','/api/archive',json.dumps(body),headers);response=connection.getresponse();raw=response.read();connection.close()
            return response.status,json.loads(raw)
        preview=dict(command='preview',kind='RESTORE',operationId=identity)
        for headers in [{'Origin':'https://foreign.invalid'},{'X-Kura-Recovery-CSRF':'wrong'},{'Cookie':'unrelated=value'}]:self.assertEqual(400,post(preview,headers)[0])
        self.assertEqual([],self.calls);self.assertEqual('ARCHIVABLE',post(preview)[1]['state'])
        request=dict(preview,command='archive',backupJson=json.dumps(backup),passphrase='synthetic HTTPS authorization material 52!')
        wrong=dict(backup,operationId=str(uuid.uuid4()));self.assertEqual(400,post(dict(request,backupJson=json.dumps(wrong)))[0])
        self.assertFalse((self.directory/'archives').exists());status,result=post(request)
        self.assertEqual(200,status);self.assertEqual('ARCHIVE_RECORDED',result['state']);self.assertEqual(1,sum(v['action']=='journal-archive' for v in self.calls))


if __name__=='__main__':unittest.main()
