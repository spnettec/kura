#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Protected package/start chains and public TLS material; isolated roots only."""
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/bin'))
import kura_key_service as protocol
import kura_key_service_lifecycle as lifecycle
import kura_key_recovery as recovery
import kura_key_recovery_start as start
import test_key_recovery_handoff as old
import test_key_service_lifecycle as package_tests


class Maintenance(unittest.TestCase):
    def setUp(self):
        self.base=old.ProtectedStarter('test_original_read_never_dispatches_or_creates_a_record')
        self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.manager=self.base.manager;self.starter=self.base.starter
        self.first_request=dict(self.base.request);self.first=self.starter.handle(self.first_request)
        self.manifest='e'*64;self.starter.manifest_digest=lambda:self.manifest
        self.history=self.manager.state/'package-history';self.history.mkdir(mode=0o700)
        self.maintenance_id=str(uuid.uuid4());self.archive(self.maintenance_id,None,[self.first['operationId']])
        self.request=dict(schema=1,action='core-start-after-maintenance',operationId=str(uuid.uuid4()),
            restoreOperationId=self.base.restore_id,expectedKeySha256=self.base.sha,
            predecessorStartOperationId=self.first['operationId'],maintenanceId=self.maintenance_id,manifestSha256=self.manifest)

    def archive(self, identity, parent, ids, manifest=None):
        value=dict(schema=1,maintenanceId=identity,previousMaintenanceId=parent,firstAction='upgrade',
            manifestSha256=self.manifest if manifest is None else manifest,keySha256=self.base.sha,precedingStartupIds=sorted(ids))
        self.manager.atomic(self.history/(identity+'.json'),protocol.encode(value))

    def plan(self):return self.starter.handle(dict(schema=1,action='core-start-plan',restoreOperationId=self.base.restore_id,expectedKeySha256=self.base.sha))

    def dispatch(self, request=None):
        value=self.request if request is None else request;self.base.request=value
        return self.starter.handle(value)

    def refused(self,reason,request=None):
        with self.assertRaises(protocol.Failure) as found:self.dispatch(request)
        self.assertEqual(reason,found.exception.reason)

    def test_read_only_plan_requires_protected_terminal_predecessor_and_new_maintenance(self):
        before={str(f):f.read_bytes() for folder in (self.history,self.starter.directory) for f in folder.iterdir()}
        plan=self.plan();self.assertTrue(plan['startAllowed']);self.assertEqual(self.first['operationId'],plan['predecessorStartOperationId'])
        self.assertEqual(before,{str(f):f.read_bytes() for folder in (self.history,self.starter.directory) for f in folder.iterdir()})
        self.assertEqual(1,len(self.base.calls))

    def test_explicit_new_start_once_preserves_old_original_and_consumes_maintenance(self):
        original=self.starter.record(self.first['operationId']);result=self.dispatch()
        self.assertEqual('core-start-after-maintenance',result['action']);self.assertEqual(self.maintenance_id,result['maintenanceId'])
        self.assertEqual(original,self.starter.record(self.first['operationId']))
        self.assertEqual(result,self.dispatch());self.assertFalse(self.plan()['startAllowed'])
        self.refused('CONFLICT',dict(self.request,operationId=str(uuid.uuid4())))
        self.assertEqual(2,len(self.base.calls))

    def test_unknown_new_start_is_not_settled_by_old_success_key_or_new_uuid(self):
        self.base.timeout=True;self.refused('UNKNOWN')
        plan=self.plan();self.assertFalse(plan['startAllowed']);self.assertEqual(self.request['operationId'],plan['blockingOperationId'])
        self.assertEqual('UNKNOWN',self.dispatch()['state'])
        self.assertEqual('SUCCEEDED',self.starter.handle(self.first_request)['state'])
        self.refused('UNRESOLVED_OPERATION',dict(self.request,operationId=str(uuid.uuid4())))
        with self.assertRaises(lifecycle.Refused):self.base.lifecycle.check_records()
        self.assertEqual(2,len(self.base.calls))

    def test_stale_package_manifest_is_not_start_authority(self):
        self.manifest='f'*64;self.assertFalse(self.plan()['startAllowed']);self.refused('CONFLICT')
        self.assertEqual(1,len(self.base.calls))

    def test_maintenance_without_this_predecessor_cannot_authorize_start(self):
        self.archive(self.maintenance_id,None,[])
        self.assertFalse(self.plan()['startAllowed']);self.refused('CONFLICT')

    def test_wrong_predecessor_or_maintenance_id_rejected_before_intent(self):
        for key in ['predecessorStartOperationId','maintenanceId']:
            self.refused('CONFLICT',dict(self.request,**{key:str(uuid.uuid4())}))
        self.assertEqual(1,len(self.starter.records()));self.assertEqual(1,len(self.base.calls))

    def test_unrelated_package_history_heads_fail_closed(self):
        self.archive(str(uuid.uuid4()),None,[self.first['operationId']])
        self.refused('UNSAFE_JOURNAL');self.assertEqual(1,len(self.base.calls))

    def test_disconnected_cycle_in_package_history_fails_closed(self):
        left=str(uuid.uuid4());right=str(uuid.uuid4())
        self.archive(left,right,[]);self.archive(right,left,[])
        self.refused('UNSAFE_JOURNAL');self.assertEqual(1,len(self.base.calls))

    def test_new_upgrade_requires_explicit_new_request_after_new_terminal_predecessor(self):
        second=self.dispatch();next_id=str(uuid.uuid4())
        self.archive(next_id,self.maintenance_id,[self.first['operationId'],second['operationId']])
        self.assertTrue(self.plan()['startAllowed']);self.assertEqual(2,len(self.base.calls))
        self.request=dict(self.request,operationId=str(uuid.uuid4()),maintenanceId=next_id,predecessorStartOperationId=second['operationId'])
        third=self.dispatch();self.assertEqual(next_id,third['maintenanceId']);self.assertEqual(3,len(self.base.calls))

    def controller(self):
        path=self.base.root/'local-recovery';path.mkdir(mode=0o700)
        journal=recovery.Journal(path)
        journal.admit(dict(schema=1,operationId=self.base.restore_id,expectedKeySha256=self.base.sha,backupSha256='a'*64))
        journal.mark(self.base.restore_id,self.base.sha)
        journal.write_new(journal.starts/(self.first['operationId']+'.json'),dict(schema=1,operationId=self.first['operationId'],
            restoreOperationId=self.base.restore_id,expectedKeySha256=self.base.sha))
        def client(request):
            with patch.object(start,'Starter',return_value=self.starter):return self.manager.handle(request,recovery_only=True)
        return recovery.Controller(client,journal)

    def test_adapter_restart_picks_new_leaf_and_queries_without_redispatch(self):
        controller=self.controller();value={k:v for k,v in self.request.items() if k not in ('schema','action')}
        self.base.request=self.request
        result=controller.start(value,maintenance=True);self.assertEqual('SUCCEEDED',result['state'])
        self.assertEqual(self.request['operationId'],controller.status()['pendingStart']['operationId'])
        self.assertEqual(result,controller.start(value,maintenance=True));self.assertEqual(2,len(self.base.calls))
        with self.assertRaises(protocol.Failure):controller.complete(dict(operationId=self.first['operationId']))
        self.assertTrue((controller.journal.directory/'pending.json').exists())


class PackageArchive(unittest.TestCase):
    def setUp(self):
        self.base=package_tests.LifecycleTest('test_initial_admission_creates_private_independent_journal_and_fence')
        self.base.setUp();self.addCleanup(self.base.doCleanups)

    def test_leave_records_stopped_terminal_predecessors_privately_and_idempotently(self):
        policy=self.base.policy;fence=policy.enter('upgrade');old_mask=os.umask(0o022)
        try:policy.leave()
        finally:os.umask(old_mask)
        path=policy.state/'package-history'/(fence['id']+'.json');record=json.loads(path.read_text())
        self.assertEqual([],record['precedingStartupIds']);self.assertIsNone(record['previousMaintenanceId'])
        self.assertEqual(0o700,path.parent.stat().st_mode&0o777);self.assertEqual(0o600,path.stat().st_mode&0o777)
        before=path.read_bytes();policy.leave();self.assertEqual(before,path.read_bytes())

    def test_running_core_refuses_archive_and_preserves_maintenance_fence(self):
        policy=self.base.policy;policy.enter('upgrade');self.base.states['kura.service']='active'
        with self.assertRaises(lifecycle.Refused):policy.leave()
        self.assertTrue((policy.state/'maintenance.json').exists());self.assertFalse((policy.state/'package-history').exists())


class PublicRecoveryInfo(unittest.TestCase):
    def test_only_public_certificate_is_read_and_der_fingerprint_matches(self):
        old_mask=os.umask(0o077);self.addCleanup(os.umask,old_mask)
        with tempfile.TemporaryDirectory(prefix='kura-public-recovery-info-') as temporary:
            root=Path(temporary).resolve();manager=protocol.Manager(root,os.geteuid())
            policy=lifecycle.Lifecycle(root,os.geteuid());policy.initialize()
            directory=root/'etc/kura/recovery-tls';directory.mkdir(parents=True,mode=0o700)
            key=directory/'server.key';cert=directory/'server.crt'
            subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost',
                '-keyout',str(key),'-out',str(cert)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=20)
            key.chmod(0o400);cert.chmod(0o600);before=key.stat()
            raw_read=manager.read;reads=[]
            def read(path,*args):
                self.assertNotEqual(key,path);reads.append(path.name);return raw_read(path,*args)
            manager.read=read
            result=manager.handle(dict(schema=1,action='recovery-info'),recovery_only=True)
            self.assertEqual(9443,result['recoveryPort']);self.assertFalse(result['agentRequired'])
            self.assertEqual(hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest(),result['certificateSha256'])
            self.assertNotIn('PRIVATE KEY',result['certificatePem']);self.assertEqual(['server.crt'],reads)
            self.assertEqual(before.st_mtime_ns,key.stat().st_mtime_ns);self.assertEqual(before.st_ino,key.stat().st_ino)


if __name__=='__main__':unittest.main()
