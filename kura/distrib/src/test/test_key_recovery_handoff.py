#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""New start and restart contracts, isolated from every installed gateway."""
import hashlib
import http.client
import ssl
import threading
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/bin'))
import kura_key_service as protocol
import kura_key_service_lifecycle as lifecycle
import kura_key_recovery_start as start
import kura_key_recovery as recovery
import kura_key_recovery_setup as setup
from test_key_recovery import Fixture, PASSWORD, BACKUP, SHA
from sender_admission_model import SenderModel


class Adapter(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.start_records={};self.start_writes=0;self.loss=False;self.unknown=False
        root=self.root
        def client(request):
            if request['action']=='core-start-plan':
                return dict(schema=1,state='START_PLAN',startAllowed=False,maintenanceId=None,
                    predecessorStartOperationId=None,manifestSha256=None,blockingOperationId=None)
            if request['action']=='core-start-read':
                return self.start_records.get(request['operationId'],dict(schema=1,state='NOT_FOUND'))
            if request['action']=='core-start':
                self.start_writes+=1
                value=dict(schema=1,operationId=request['operationId'],restoreOperationId=request['restoreOperationId'],
                    state='SUCCEEDED',action='core-start',keySha256=SHA,scope='SYSTEMD_JOB_ACCEPTED',jobPath='/org/freedesktop/systemd1/job/12')
                self.start_records[request['operationId']]=dict(schema=1,operationId=request['operationId'],state='UNKNOWN') if self.unknown else value
                if self.loss:raise OSError('Synthetic reply loss')
                return value
            return root(request)
        self.client=client;self.controller=recovery.Controller(client,self.journal, sender=SenderModel())
        self.start_request=dict(operationId=str(uuid.uuid4()),restoreOperationId=self.request['operationId'],expectedKeySha256=SHA)

    def test_zero_monotonic_origin_allows_first_inspection_then_throttles(self):
        material=dict(backupJson=json.dumps(BACKUP),passphrase=PASSWORD)
        with patch.object(recovery.time,'monotonic',return_value=0.0):
            self.controller.inspect(material)
            self.failure('BUSY',lambda:self.controller.inspect(material))

    def test_present_key_restart_recovers_server_pending_without_new_restore(self):
        self.controller.restore(self.request)
        before=(self.path/'pending.json').read_bytes()
        restored=recovery.Controller(self.client,recovery.Journal(self.path), sender=SenderModel())
        state=restored.status()
        self.assertTrue(state['keyReady']);self.assertEqual(self.request['operationId'],state['pendingRestore']['operationId'])
        self.assertEqual('ROOT_ORIGINAL',restored.original(state['pendingRestore']['operationId'])['resultSource'])
        self.assertEqual(before,(self.path/'pending.json').read_bytes());self.assertEqual(1,self.root.writes)

    def test_start_reply_loss_restart_and_new_uuid_never_repeat_start(self):
        self.controller.restore(self.request);self.loss=True
        result=self.controller.start(self.start_request)
        self.assertEqual('SYSTEMD_JOB_ACCEPTED',result['scope']);self.assertEqual('ROOT_ORIGINAL',result['resultSource'])
        restored=recovery.Controller(self.client,recovery.Journal(self.path), sender=SenderModel())
        self.assertEqual(self.start_request['operationId'],restored.status()['pendingStart']['operationId'])
        self.assertEqual(result,restored.start(self.start_request))
        other=dict(self.start_request,operationId=str(uuid.uuid4()))
        self.failure('CONFLICT',lambda:restored.start(other));self.assertEqual(1,self.start_writes)

    def test_unknown_start_is_not_settled_by_present_key_and_cannot_complete(self):
        self.controller.restore(self.request);self.unknown=True;self.loss=True
        self.assertEqual('UNKNOWN',self.controller.start(self.start_request)['state'])
        self.assertTrue(self.controller.status()['keyReady'])
        self.failure('UNRESOLVED_OPERATION',lambda:self.controller.complete(dict(operationId=self.start_request['operationId'])))
        self.assertEqual('UNKNOWN',self.controller.start(self.start_request)['state']);self.assertEqual(1,self.start_writes)
        self.assertTrue((self.path/'pending.json').exists())

    def test_complete_preserves_every_original_record_and_only_clears_marker(self):
        self.controller.restore(self.request);self.controller.start(self.start_request)
        before={str(f):f.read_bytes() for folder in (self.journal.operations,self.journal.starts) for f in folder.iterdir()}
        self.controller.complete(dict(operationId=self.start_request['operationId']))
        self.assertIsNone(self.controller.status()['pendingRestore'])
        self.assertEqual(before,{str(f):f.read_bytes() for folder in (self.journal.operations,self.journal.starts) for f in folder.iterdir()})
        self.assertEqual(1,self.start_writes);self.assertEqual(1,self.root.writes)


class ProtectedStarter(unittest.TestCase):
    def setUp(self):
        old=os.umask(0o077);self.addCleanup(os.umask,old)
        temporary=tempfile.TemporaryDirectory(prefix='kura-new-start-contract-');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.manager=protocol.Manager(self.root,os.geteuid())
        self.lifecycle=lifecycle.Lifecycle(self.root,os.geteuid());self.lifecycle.initialize()
        self.lifecycle.create(self.manager.state/'journal.key',b'j'*32)
        (self.manager.state/'startups').mkdir(mode=0o700)
        credentials=self.root/'etc/kura/credentials';credentials.mkdir(parents=True,mode=0o700)
        self.key=b'k'*32;self.sha=hashlib.sha256(self.key).hexdigest()
        for name,value,mode in [('kura_encryption_key',self.key,0o400),('.provision.lock',b'',0o600),
                ('provisioned.json',protocol.encode(dict(schema=1,keySha256=self.sha,origin='fresh',legacyKey=False,unitDigests=[])),0o600)]:
            (credentials/name).write_bytes(value);(credentials/name).chmod(mode)
        self.restore_id=str(uuid.uuid4())
        self.original=dict(schema=1,operationId=self.restore_id,action='restore',state='SUCCEEDED',keySha256=self.sha,keyChanged=True,existingReceiptPreserved=True)
        self.save_restore()
        self.calls=[];self.timeout=False
        self.starter=start.Starter(self.manager,self.runner)
        self.request=dict(schema=1,action='core-start',operationId=str(uuid.uuid4()),restoreOperationId=self.restore_id,expectedKeySha256=self.sha)

    def save_restore(self):
        record=dict(schema=1,operationId=self.restore_id,action='restore',requestTag='a'*64,state='SUCCEEDED',response=self.original)
        self.manager.atomic(self.manager.operations/(self.restore_id+'.json'),protocol.encode(record))

    def runner(self, command, **_):
        self.calls.append(command)
        # An INTENT must be durable before even a failed manager call.
        record=self.starter.record(self.request['operationId']);self.assertEqual('INTENT',record['state'])
        if self.timeout:raise subprocess.TimeoutExpired(command,18)
        return SimpleNamespace(returncode=0,stdout='o "/org/freedesktop/systemd1/job/42"\n')

    def refused(self,reason,request):
        with self.assertRaises(protocol.Failure) as found:self.starter.handle(request)
        self.assertEqual(reason,found.exception.reason)

    def test_only_fixed_unit_command_once_with_original_job_receipt(self):
        result=self.starter.handle(self.request)
        self.assertEqual('SYSTEMD_JOB_ACCEPTED',result['scope']);self.assertEqual([list(start.COMMAND)],self.calls)
        self.assertEqual(result,self.starter.handle(self.request));self.assertEqual(1,len(self.calls))
        self.refused('CONFLICT',dict(self.request,operationId=str(uuid.uuid4())))

    def test_timeout_preserves_unknown_and_fences_a_new_uuid(self):
        self.timeout=True;self.refused('UNKNOWN',self.request)
        self.assertEqual('UNKNOWN',self.starter.handle(self.request)['state'])
        self.refused('UNRESOLVED_OPERATION',dict(self.request,operationId=str(uuid.uuid4())))
        self.assertEqual(1,len(self.calls))
        with self.assertRaises(lifecycle.Refused):self.lifecycle.check_records()

    def test_arbitrary_unit_or_verb_is_rejected_before_admission(self):
        for extra in [dict(unit='other.service'),dict(verb='restart'),dict(argv=['/bin/sh'])]:
            self.refused('INVALID_ARGUMENT',dict(self.request,**extra))
        self.assertEqual([],self.calls);self.assertEqual([],self.starter.records())

    def test_same_key_noop_restore_is_not_authority_to_start(self):
        self.original['keyChanged']=False;self.save_restore()
        self.refused('CONFLICT',self.request);self.assertEqual([],self.calls)

    def test_mismatched_fingerprint_and_missing_original_are_rejected(self):
        self.refused('CONFLICT',dict(self.request,expectedKeySha256='b'*64))
        self.refused('UNRESOLVED_OPERATION',dict(self.request,restoreOperationId=str(uuid.uuid4())))
        self.assertEqual([],self.calls)

    def test_original_read_never_dispatches_or_creates_a_record(self):
        result=self.starter.handle(dict(schema=1,action='core-start-read',operationId=self.request['operationId']))
        self.assertEqual('NOT_FOUND',result['state']);self.assertEqual([],self.calls);self.assertEqual([],self.starter.records())

    def test_root_start_namespace_is_private_even_with_package_umask_022(self):
        path=self.manager.state/'startups';path.rmdir()
        before=os.umask(0o022)
        try:self.lifecycle.directory(path,private=True,create=True)
        finally:os.umask(before)
        self.assertEqual(0o700,path.stat().st_mode&0o777)

    def test_old_cold_local_slot_migrates_from_protected_receipt_without_restore(self):
        account=SimpleNamespace(pw_uid=os.geteuid(),pw_gid=os.getegid())
        installer=setup.Setup(self.root,os.geteuid())
        installer.state(account)
        slot=dict(schema=1,operationId=self.restore_id,expectedKeySha256=self.sha,backupSha256='c'*64)
        path=self.root/'var/lib/kura-key-recovery/operations'/(self.restore_id+'.json')
        path.write_bytes(protocol.encode(slot));path.chmod(0o600)
        before=path.stat();key_before=(self.root/'etc/kura/credentials/kura_encryption_key').read_bytes()
        installer.resume_marker(account)
        marker=path.parent.parent/'pending.json';data=marker.read_bytes();marker_before=marker.stat()
        installer.resume_marker(account)
        self.assertEqual(self.restore_id,json.loads(data)['operationId'])
        self.assertEqual(data,marker.read_bytes());self.assertEqual(marker_before.st_ino,marker.stat().st_ino)
        self.assertEqual(before.st_mtime_ns,path.stat().st_mtime_ns)
        self.assertEqual(key_before,(self.root/'etc/kura/credentials/kura_encryption_key').read_bytes())
        self.assertEqual([],self.calls)

    def test_completed_protected_start_does_not_recreate_a_cleared_marker(self):
        self.starter.handle(self.request)
        account=SimpleNamespace(pw_uid=os.geteuid(),pw_gid=os.getegid())
        installer=setup.Setup(self.root,os.geteuid());installer.state(account)
        path=self.root/'var/lib/kura-key-recovery/operations'/(self.restore_id+'.json')
        path.write_bytes(protocol.encode(dict(schema=1,operationId=self.restore_id,expectedKeySha256=self.sha,backupSha256='c'*64)));path.chmod(0o600)
        installer.resume_marker(account)
        self.assertFalse((path.parent.parent/'pending.json').exists());self.assertEqual(1,len(self.calls))


class HttpsRestart(unittest.TestCase):
    def test_same_port_restarts_after_tls_response_but_parallel_listener_is_refused(self):
        with tempfile.TemporaryDirectory(prefix='kura-new-restart-tls-') as temporary:
            key=Path(temporary)/'key.pem';cert=Path(temporary)/'cert.pem'
            subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                '-subj','/CN=localhost','-keyout',str(key),'-out',str(cert)],check=True,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
            tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key)
            directory=Path(temporary)/'receiver';directory.mkdir(mode=0o700)
            journal=recovery.Journal(directory)
            controller=recovery.Controller(lambda request: self.fail('TLS listener test must not call Root'),journal,sender=SenderModel())
            first=recovery.RecoveryServer(('127.0.0.1',0),controller,tls,assets=Path(recovery.__file__).parent.parent/"share/key-recovery")
            address=first.server_address
            thread=threading.Thread(target=first.serve_forever,daemon=True);thread.start()
            try:
                # A live listener must remain exclusive despite SO_REUSEADDR.
                with self.assertRaises(OSError):recovery.RecoveryServer(address,controller,tls,assets=Path(recovery.__file__).parent.parent/"share/key-recovery")
                connection=http.client.HTTPSConnection(*address,context=ssl._create_unverified_context(),timeout=5)
                connection.request('GET','/');response=connection.getresponse();self.assertEqual(200,response.status)
                response.read();connection.close()
            finally:first.shutdown();first.server_close();thread.join(5)
            with recovery.RecoveryServer(address,controller,tls,assets=Path(recovery.__file__).parent.parent/"share/key-recovery") as second:
                self.assertEqual(address,second.server_address)


if __name__=='__main__':unittest.main()
