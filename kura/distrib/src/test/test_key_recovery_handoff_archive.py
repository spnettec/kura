#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Actual Root grant/archive/HMAC/cipher and private files; historical receiver/Main/systemd are models."""
import argparse
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

import test_key_journal_archive as original
import kura_key_recovery as recovery

service=original.service
lifecycle=original.lifecycle


@unittest.skipUnless(sys.platform=='linux' and os.geteuid()==0,'Fresh Linux Root/JDK21 fixture only')
class RecoveryHandoffArchiveTest(unittest.TestCase):
    def setUp(self):
        self.base=original.JournalArchiveTest();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.fixture=self.base.fixture;self.manager,self.auth=self.fixture.manager,self.fixture.auth
        self.directory=self.manager.root/'var/lib/kura-key-recovery';self.directory.mkdir(mode=0o700)
        self.journal=recovery.Journal(self.directory,archive_module=self.manager.journal_module())
        self.controller=recovery.HandoffController(self.client,self.journal);self.history=self.journal.history();self.calls=[]

    def client(self,request):
        self.calls.append(copy.deepcopy(request))
        if request['action']=='gwt-sender-namespace':return dict(schema=1,**self.manager.gwt_namespace())
        if request['action'] in service.ARCHIVE_ACTIONS:return self.manager.archive_journal(request,os.getpid(),0,1001,0)
        if request['action']=='generation-handoff-command' and request['command'] in ('info','publication-read','start-read','revocation-read','start-lease-read'):
            return self.auth.command(request,os.getpid(),0,1001,42)
        if request['action']=='generation-handoff-revocation-read':return lifecycle.handoff_revocation_view(self.auth.revocation(self.auth.load(request['handoffId'])))
        raise AssertionError('Archive attempted a key/authority writer: '+request['action'])

    def local(self,*,completed=False,request=None):
        if request is None:
            if completed:self.fixture.publish();self.fixture.send(self.fixture.wire('start'))
            else:self.fixture.create()
            request=self.fixture.request;token=self.fixture.token
        else:token=self.auth.create(request,os.getpid(),0,1001)['token']
        info=self.auth.metadata(self.auth.load(request['handoffId']));binding=recovery.HandoffController.binding(info)
        slot=self.controller.directory/request['handoffId'];slot.mkdir(mode=0o700);self.journal.write_new(slot/'binding.json',binding)
        if completed:
            published=self.manager.record(request['publicationId'])['response'];started=self.manager.record(request['startOperationId'])['response']
            terminal=dict(binding,state='ORIGINAL_REQUESTS_CONFIRMED',publicationSha256=published['publicationSha256'],jobPath=started['jobPath'])
        else:terminal=self.auth.command(dict(schema=1,action='generation-handoff-command',token=token,command='revoke'),os.getpid(),0,1001,42)
        self.journal.write_new(slot/('completed.json' if completed else 'retired.json'),terminal)
        return request,token

    def inventory(self):
        return self.history.format.inventory(lifecycle.Lifecycle(self.manager.root,self.manager.owner),dict(schema=1,**self.manager.gwt_namespace()))

    def confirmed_archive(self,token,kind,identity,step=None):
        request=dict(token=token,command='archive-preview',kind=kind,operationId=identity)
        if step is not None:request['senderKind']=step
        view=self.controller.execute(request)
        return self.controller.execute(dict(request,command='archive-confirm',reviewSha256=view['reviewSha256']))

    def test_completed_handoff_archive_keeps_both_native_operations_and_receiver_terminal(self):
        request,token=self.local(completed=True);before=self.base.originals();private={str(p):p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}
        result=self.confirmed_archive(token,'HANDOFF',request['handoffId'])
        self.assertEqual('ARCHIVE_RECORDED',result['state']);self.assertTrue(result['archived'])
        self.assertIn(('HANDOFF',request['handoffId'],None),self.inventory());after=self.base.originals()
        self.assertEqual(before,{k:after[k] for k in before})
        for name,raw in private.items():self.assertEqual(raw,Path(name).read_bytes())
        self.controller.execute(dict(token=token,command='archive-query',kind='HANDOFF',operationId=request['handoffId']))
        self.assertEqual(1,sum(c['action']=='journal-archive' for c in self.calls))

    def test_unused_retirement_archive_and_package_reader_require_the_exact_root_revocation(self):
        request,token=self.local();identity=request['handoffId'];self.history.archive('HANDOFF',identity)
        self.assertIn(('HANDOFF',identity,None),self.inventory())
        path=self.controller.directory/identity/'retired.json';value=service.decode(path.read_bytes());value['namespaceSha256']='f'*64
        path.write_bytes(service.encode(value))
        with self.assertRaises(lifecycle.Refused):self.inventory()

    def test_handoff_active_capacity_releases_but_all_old_fixed_ids_remain_fenced(self):
        first,_=self.local();requests=[first]
        for _ in range(31):
            request=dict(first,**{k:str(uuid.uuid4()) for k in ('handoffId','publicationId','startOperationId')});self.local(request=request);requests.append(request)
        self.assertEqual(32,len(self.controller.slots()));self.history.archive('HANDOFF',first['handoffId'])
        request=dict(first,**{k:str(uuid.uuid4()) for k in ('handoffId','publicationId','startOperationId')});self.local(request=request)
        self.assertEqual(33,len(self.controller.slots()));self.assertEqual(32,self.journal.active_count('HANDOFF',self.controller.slots()))
        for key in lifecycle.HANDOFF_IDS:
            candidate=dict(first,handoffId=first[key],publicationId=str(uuid.uuid4()),startOperationId=str(uuid.uuid4()))
            with self.assertRaises(service.Failure):self.auth.create(candidate,os.getpid(),0,1001)

    def test_unfinished_handoff_and_changed_private_completion_never_release_a_slot(self):
        self.fixture.create();request=self.fixture.request;info=self.auth.metadata(self.auth.load(request['handoffId']));binding=recovery.HandoffController.binding(info)
        slot=self.controller.directory/request['handoffId'];slot.mkdir(mode=0o700);self.journal.write_new(slot/'binding.json',binding)
        with self.assertRaises(lifecycle.Refused):self.history.archive('HANDOFF',request['handoffId'])
        self.assertFalse((self.directory/'archives').exists())

    def test_wrong_original_bearer_cannot_authorize_another_private_history(self):
        first,token=self.local();second=dict(first,**{k:str(uuid.uuid4()) for k in ('handoffId','publicationId','startOperationId')});self.local(request=second)
        with self.assertRaises(service.Failure):self.controller.execute(dict(token=token,command='archive-preview',kind='HANDOFF',operationId=second['handoffId']))
        self.assertFalse((self.directory/'archives').exists());self.assertFalse(any(c['action']=='journal-archive' for c in self.calls))

    def test_history_list_is_scoped_to_the_original_grant_without_exposing_another_grant(self):
        first,token=self.local();own,_=self.negative_admission(first,'publish')
        second=dict(first,**{k:str(uuid.uuid4()) for k in ('handoffId','publicationId','startOperationId')})
        self.local(request=second);foreign,_=self.negative_admission(second,'publish')
        value=self.controller.execute(dict(token=token,command='archive-list',cursor=None))
        self.assertEqual({first['handoffId'],own},{row['operationId'] for row in value['records']})
        self.assertNotIn(foreign,str(value));self.assertNotIn(second['handoffId'],str(value))
        self.assertEqual([],self.history.list()['records'])
        self.assertFalse(any(call['action']=='journal-archive' for call in self.calls))

    def negative_admission(self,grant,step,*,completed=False):
        identity=str(uuid.uuid4()) if step=='handoff-renewal' else grant['startOperationId' if step=='handoff-start' else 'publicationId']
        command='start-renew' if step=='handoff-renewal' else 'start' if step=='handoff-start' else step
        metadata=dict(schema=1,action='generation-handoff-command',command=command,handoffId=grant['handoffId'])
        if step=='continue':metadata['expectedRecoveryReceiptSha256']='d'*64
        if step=='handoff-renewal':metadata.update(operationId=identity,expectedPublicationSha256='e'*64)
        admission=str(uuid.uuid4());attempt=dict(schema=1,purpose='yofc.kura.sender-attempt.v1',admissionId=admission,kind=step,nativeOperationId=identity,request=metadata)
        parent=self.directory/'admissions';parent.mkdir(mode=0o700,exist_ok=True);slot=parent/(identity+'-'+step);slot.mkdir(mode=0o700)
        self.journal.write_new(slot/'intent.json',attempt);self.journal.write_new(slot/'namespace.json',dict(schema=1,namespaceSha256=self.manager.gwt_namespace()['namespaceSha256']))
        native=(dict(schema=1,action='generation-start-lease',operationId=identity,handoffId=grant['handoffId'],expectedPublicationSha256='e'*64)
            if step=='handoff-renewal' else self.auth.operation_request(self.auth.load(grant['handoffId']),start=step=='handoff-start'))
        shared=self.manager.sender_admissions;target=shared.native_target(native);target['continuation']=step=='continue'
        shared.write(dict(schema=1,purpose=lifecycle.SENDER_ADMISSION_PURPOSE,admissionId=admission,source='recovery',
            namespaceSha256=self.manager.gwt_namespace()['namespaceSha256'],owner=dict(uid=0,pid=os.getpid(),startTicks='1',bootId=str(uuid.uuid4())),
            requestTag=shared.tag(metadata),target=target,parentAdmissionId=None,state='INTAKE' if completed else 'NOT_ADMITTED'),create=True)
        return identity,slot

    def test_unused_fixed_operation_sender_kinds_require_original_root_metadata(self):
        grant,token=self.local()
        for step in ('publish','handoff-start','handoff-renewal'):
            identity,_=self.negative_admission(grant,step)
            result=self.confirmed_archive(token,'ADMISSION',identity,step)
            self.assertEqual('ARCHIVE_RECORDED',result['state']);self.assertTrue(result['archived'])
            self.assertIn(('ADMISSION',identity,step),self.inventory())
        self.assertEqual(3,sum(c['action']=='journal-archive' for c in self.calls))

    def test_completed_continuation_archive_requires_original_success_and_preserves_intake(self):
        grant,token=self.local(completed=True);identity,slot=self.negative_admission(grant,'continue',completed=True)
        before=self.base.originals()
        result=self.confirmed_archive(token,'ADMISSION',identity,'continue')
        self.assertEqual('ARCHIVE_RECORDED',result['state']);self.assertTrue(result['archived'])
        self.assertIn(('ADMISSION',identity,'continue'),self.inventory());after=self.base.originals()
        self.assertEqual(before,{k:after[k] for k in before});self.assertEqual(1,sum(c['action']=='journal-archive' for c in self.calls))

    def test_changed_fixed_authority_binding_cannot_borrow_a_different_grant_receipt(self):
        first,token=self.local();identity,slot=self.negative_admission(first,'publish')
        second=dict(first,**{k:str(uuid.uuid4()) for k in ('handoffId','publicationId','startOperationId')});self.local(request=second)
        path=slot/'intent.json';value=service.decode(path.read_bytes());value['request']['handoffId']=second['handoffId'];path.write_bytes(service.encode(value))
        with self.assertRaises(service.Failure):self.history.archive('ADMISSION',identity,'publish')
        self.assertFalse((self.directory/'archives').exists());self.assertFalse(any(c['action']=='journal-archive' for c in self.calls))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repository',required=True,type=Path)
    parser.add_argument('--java',required=True,type=Path);parser.add_argument('--cipher-jar',required=True,type=Path)
    options,remaining=parser.parse_known_args();original.original.base.package.CONFIG=options.repository.resolve()
    original.original.base.JAVA=options.java.resolve();original.original.base.CIPHER=options.cipher_jar.resolve()
    unittest.main(argv=[sys.argv[0],*remaining])
