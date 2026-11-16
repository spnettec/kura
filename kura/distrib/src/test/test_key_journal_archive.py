#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Actual Root journal/HMAC/crypto/flock; historical padding and Core/systemd are modeled."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid
from types import SimpleNamespace

import test_key_handoff as original
import test_key_handoff_capacity as capacity
import kura_key_service_lifecycle as lifecycle
import kura_key_recovery_start as starting

service=original.service


@unittest.skipUnless(sys.platform=='linux' and os.geteuid()==0,'Disposable Linux Root/JDK21 only')
class JournalArchiveTest(unittest.TestCase):
    def setUp(self):
        self.fixture=capacity.HandoffCapacityTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.manager=self.fixture.manager;self.auth=self.fixture.auth;self.shared=self.manager.sender_admissions
        self.base=self.fixture.fixture;self.namespace=self.manager.gwt_namespace()['namespaceSha256']

    def call(self,request,*,uid=0):
        return service.serve_request(self.manager,request,os.getpid(),uid,1001,42,None)[0]

    def query(self,identity):
        return self.call(dict(schema=1,action='journal-archive-read',namespaceSha256=self.namespace,archiveId=identity))

    def request(self,references):
        plan=self.call(dict(schema=1,action='journal-archive-plan',namespaceSha256=self.namespace,entries=references))
        return dict(schema=1,action='journal-archive',namespaceSha256=self.namespace,archiveId=str(uuid.uuid4()),
            entries=references,expectedEntriesSha256=plan['entriesSha256'])

    def archive(self,*references):
        request=self.request(list(references));return request,self.call(request)

    @staticmethod
    def ref(directory,identity):return dict(directory=directory,operationId=identity)

    def backups(self,count):
        self.fixture.fill_native(count)
        return [p.name[:-5] for p in self.manager.operations.iterdir() if self.manager.record(p.name[:-5])['action']=='backup-create']

    def originals(self):
        return {k:v for k,v in self.base.snapshot().items() if not k.startswith('var/lib/kura-key-service/archives/')}

    def startup(self):
        identity=str(uuid.uuid4());restore=str(uuid.uuid4());fingerprint=self.manager.canonical()[1]['keySha256']
        self.manager.atomic(self.manager.operations/(restore+'.json'),service.encode(dict(schema=1,action='restore',
            operationId=restore,requestTag='a'*64,state='SUCCEEDED',response=dict(schema=1,action='restore',
            operationId=restore,state='SUCCEEDED',keySha256=fingerprint,keyChanged=True,existingReceiptPreserved=True))))
        native=dict(schema=1,action='core-start',operationId=identity,restoreOperationId=restore,expectedKeySha256=fingerprint)
        result=dict(schema=1,operationId=identity,restoreOperationId=restore,keySha256=fingerprint,action='core-start',
            state='SUCCEEDED',scope='SYSTEMD_JOB_ACCEPTED',jobPath='/org/freedesktop/systemd1/job/42')
        value=dict(schema=1,operationId=identity,restoreOperationId=restore,keySha256=fingerprint,requestTag=self.shared.tag(native),state='SUCCEEDED',response=result)
        parent=self.manager.state/'startups';parent.mkdir(mode=0o700,exist_ok=True)
        self.manager.atomic(parent/(identity+'.json'),service.encode(value));return value

    def maintenance(self,identity,parent=None):
        value=dict(schema=1,maintenanceId=identity,firstAction='upgrade',manifestSha256='e'*64,
            keySha256=self.manager.canonical()[1]['keySha256'],precedingStartupIds=[],previousMaintenanceId=parent)
        directory=self.manager.state/'package-history';directory.mkdir(mode=0o700,exist_ok=True)
        self.manager.atomic(directory/(identity+'.json'),service.encode(value));return value

    def test_preview_and_unknown_archive_queries_preserve_every_original_and_make_no_directory(self):
        identities=self.backups(4);before=self.base.snapshot();calls=list(self.base.commands)
        request=self.request([self.ref('operations',identities[0])]);result=self.query(request['archiveId'])
        self.assertEqual('NOT_RECORDED',result['state']);self.assertEqual(before,self.base.snapshot())
        self.assertEqual(calls,self.base.commands);self.assertFalse((self.manager.state/'archives').exists())

    def test_native_capacity_is_released_without_deleting_or_recreating_any_original(self):
        identities=self.backups(256);before=self.originals();native=self.fixture.backup()
        self.fixture.rejected(self.fixture.frame(native))
        request,result=self.archive(*[self.ref('operations',v) for v in identities[:2]])
        self.assertEqual('ARCHIVE_RECORDED',result['state']);self.assertEqual(before,self.originals())
        self.assertEqual(256,len(list(self.manager.operations.iterdir())))
        self.assertEqual(254,self.manager.active_records('operations',[p.name[:-5] for p in self.manager.operations.iterdir()]))
        self.assertEqual('SUCCEEDED',self.fixture.send(dict(schema=1,action='backup-create',operationId=str(uuid.uuid4()),passphrase=self.base.password))['state'])
        self.assertEqual(257,len(list(self.manager.operations.iterdir())));self.assertEqual(result,self.query(request['archiveId']))
        lifecycle.Lifecycle(self.manager.root,self.manager.owner).check_records()

    def test_shared_capacity_is_released_but_closed_original_uuid_and_late_frame_stay_fenced(self):
        self.fixture.fill_shared(256);rows=self.shared.records();before=self.originals()
        self.fixture.rejected(self.fixture.frame(self.fixture.backup()))
        self.archive(*[self.ref('sender-admissions',row['admissionId']) for row in rows[:2]])
        self.assertEqual(before,self.originals());self.assertEqual(256,len(self.shared.records()))
        self.assertTrue(self.fixture.reserve(self.fixture.frame(self.fixture.backup()))['newlyReserved'])
        target=rows[0]['target'];native=dict(schema=1,action='backup-create',operationId=target['operationId'],passphrase='modeled-history-padding')
        self.fixture.rejected(self.fixture.frame(native),'CONFLICT')
        self.assertIsNone(self.manager.record(target['operationId']))

    def test_completed_authority_keeps_the_original_publication_start_and_ordinary_boot_proof(self):
        self.fixture.publish();self.fixture.send(self.fixture.wire('start'));before=self.originals();calls=list(self.base.commands)
        request=self.fixture.request;refs=[self.ref('handoffs',request['handoffId'])]
        refs+=[self.ref('operations',request[k]) for k in ('publicationId','startOperationId')]
        self.archive(*refs);self.assertEqual(before,self.originals());self.assertEqual(calls,self.base.commands)
        self.auth.generations.require_start(dict(keySha256=self.fixture.published['activeKeySha256'],
            ringSha256=self.fixture.published['ringSha256']),self.base.cohort)
        policy=lifecycle.Lifecycle(self.manager.root,self.manager.owner);policy.initialize();policy.check_records()
        self.assertEqual(request['publicationId'],self.auth.generations.current()['operationId'])

    def test_unfinished_or_merely_published_authority_cannot_be_archived(self):
        self.fixture.create();ref=self.ref('handoffs',self.fixture.request['handoffId']);before=self.base.snapshot()
        self.base.refused('ARCHIVE_UNSETTLED',lambda:self.request([ref]));self.assertEqual(before,self.base.snapshot())
        self.fixture.published=self.auth.command(self.fixture.wire('publish'),os.getpid(),0,1001,42);before=self.base.snapshot()
        self.base.refused('ARCHIVE_UNSETTLED',lambda:self.request([ref]));self.assertEqual(before,self.base.snapshot())

    def test_positive_unused_revocation_is_archivable_and_never_reactivates_the_old_grant(self):
        self.fixture.create();frame=self.fixture.frame(self.fixture.wire('publish'));self.fixture.reserve(frame)
        self.auth.command(self.fixture.wire('revoke'),os.getpid(),0,1001,42);before=self.originals()
        self.archive(self.ref('handoffs',self.fixture.request['handoffId']),self.ref('sender-admissions',frame['admissionId']))
        self.assertEqual(before,self.originals());self.fixture.rejected(self.fixture.frame(self.fixture.wire('publish')),'HANDOFF_REVOKED')
        self.assertEqual('UNUSED_AUTHORITY_REVOKED',self.auth.command(self.fixture.wire('revocation-read'),os.getpid(),0,1001,42)['state'])

    def test_reserved_or_intake_admission_never_becomes_an_archived_absence_proof(self):
        frame=self.fixture.frame(self.fixture.backup());self.fixture.reserve(frame);ref=self.ref('sender-admissions',frame['admissionId'])
        for state in ('RESERVED','INTAKE'):
            self.shared.write(dict(self.shared.load(frame['admissionId']),state=state));before=self.base.snapshot()
            self.base.refused('ARCHIVE_UNSETTLED',lambda:self.request([ref]));self.assertEqual(before,self.base.snapshot())
        self.assertIsNone(self.manager.record(frame['request']['operationId']))

    def test_unrelated_unknown_native_is_preserved_while_positive_history_can_be_archived(self):
        identities=self.backups(4);unknown=str(uuid.uuid4());self.manager.atomic(self.manager.operations/(unknown+'.json'),service.encode(
            dict(schema=1,action='backup-create',operationId=unknown,requestTag='1'*64,state='INTENT',response=None)))
        path=self.manager.operations/(unknown+'.json');before=path.read_bytes();self.archive(self.ref('operations',identities[0]))
        self.assertEqual(before,path.read_bytes());self.assertEqual('UNKNOWN',self.manager.public_record(self.manager.record(unknown))['state'])
        self.base.refused('ARCHIVE_UNSETTLED',lambda:self.request([self.ref('operations',unknown)]))

    def test_receipt_failure_is_read_only_unknown_until_explicit_same_archive_continuation(self):
        identity=self.backups(4)[0];request=self.request([self.ref('operations',identity)]);atomic=self.manager.atomic
        def interrupted(path,raw,**options):
            if path.name.endswith('.receipt.json'):raise OSError('injected archive receipt failure')
            return atomic(path,raw,**options)
        with patch.object(self.manager,'atomic',side_effect=interrupted):self.base.refused('UNKNOWN',lambda:self.call(request))
        before=self.base.snapshot();self.assertEqual('UNKNOWN',self.query(request['archiveId'])['state'])
        self.assertEqual('UNKNOWN',self.call(request)['state']);self.assertEqual(before,self.base.snapshot())
        self.base.refused('UNRESOLVED_ARCHIVE',lambda:self.call(dict(request,archiveId=str(uuid.uuid4()))))
        result=self.call(dict(request,action='journal-archive-continue'));self.assertEqual('ARCHIVE_RECORDED',result['state'])
        before=self.base.snapshot();self.assertEqual(result,self.call(request));self.assertEqual(before,self.base.snapshot())

    def test_lost_reply_after_durable_receipt_is_recovered_without_a_second_metadata_writer(self):
        identity=self.backups(4)[0];request=self.request([self.ref('operations',identity)]);atomic=self.manager.atomic
        def lost(path,raw,**options):
            result=atomic(path,raw,**options)
            if path.name.endswith('.receipt.json'):raise OSError('reply lost after durable archive')
            return result
        with patch.object(self.manager,'atomic',side_effect=lost):self.base.refused('UNKNOWN',lambda:self.call(request))
        before=self.base.snapshot();self.assertEqual('ARCHIVE_RECORDED',self.query(request['archiveId'])['state'])
        self.assertEqual('ARCHIVE_RECORDED',self.call(request)['state']);self.assertEqual(before,self.base.snapshot())

    def test_changed_request_or_observed_digest_cannot_rebind_the_original_archive_id(self):
        identities=self.backups(4);request=self.request([self.ref('operations',identities[0])]);self.call(request);before=self.base.snapshot()
        self.base.refused('CONFLICT',lambda:self.call(dict(request,entries=[self.ref('operations',identities[1])])) )
        self.base.refused('CONFLICT',lambda:self.call(dict(request,expectedEntriesSha256='f'*64)))
        self.assertEqual(before,self.base.snapshot())

    def test_corrupt_receipt_or_original_never_frees_capacity_or_is_repaired(self):
        identity=self.backups(4)[0];request,_=self.archive(self.ref('operations',identity))
        receipt=self.manager.state/'archives'/(request['archiveId']+'.receipt.json');raw=receipt.read_bytes()
        value=service.decode(raw);value['receiptTag']='0'*64;self.manager.atomic(receipt,service.encode(value),mode=0o400)
        before=self.base.snapshot();self.base.refused('UNSAFE_JOURNAL',lambda:self.query(request['archiveId']));self.assertEqual(before,self.base.snapshot())
        self.manager.atomic(receipt,raw,mode=0o400);path=self.manager.operations/(identity+'.json');value=service.decode(path.read_bytes())
        value['requestTag']='f'*64;self.manager.atomic(path,service.encode(value));before=self.base.snapshot()
        self.base.refused('UNSAFE_JOURNAL',lambda:self.manager.active_records('operations',[identity]));self.assertEqual(before,self.base.snapshot())

    def test_duplicate_refs_wrong_namespace_and_unknown_tables_fail_before_any_intent(self):
        identity=self.backups(4)[0];ref=self.ref('operations',identity);before=self.base.snapshot()
        for refs in ([ref,ref],[self.ref('credentials',identity)]):
            self.base.refused('INVALID_ARGUMENT',lambda:self.request(refs))
        request=dict(schema=1,action='journal-archive-plan',namespaceSha256='0'*64,entries=[ref])
        self.base.refused('CONFLICT',lambda:self.call(request));self.assertEqual(before,self.base.snapshot())

    def test_copied_foreign_namespace_intent_and_receipt_are_rejected(self):
        identity=self.backups(4)[0];request,_=self.archive(self.ref('operations',identity))
        key=self.manager.state/'journal.key';self.manager.atomic(key,b'x'*32)
        self.namespace=self.manager.gwt_namespace()['namespaceSha256'];before=self.base.snapshot()
        self.base.refused('UNSAFE_JOURNAL',lambda:self.query(request['archiveId']));self.assertEqual(before,self.base.snapshot())

    def test_current_main_peer_and_gwt_bound_frame_are_required_before_archive_metadata(self):
        identity=self.backups(4)[0];request=self.request([self.ref('operations',identity)]);before=self.base.snapshot()
        self.base.refused('FORBIDDEN',lambda:self.call(request,uid=1001))
        with patch.object(self.manager,'recovery_sender_owner',side_effect=service.Failure('FORBIDDEN')):
            self.base.refused('FORBIDDEN',lambda:self.call(request,uid=42))
        self.assertEqual(before,self.base.snapshot())

    def test_multiple_archives_are_one_immutable_chain_and_reject_rearchiving(self):
        identities=self.backups(5);first,_=self.archive(self.ref('operations',identities[0]));second,_=self.archive(self.ref('operations',identities[1]))
        inv=self.manager.archives();self.assertEqual(second['archiveId'],inv['head'])
        self.assertEqual(first['archiveId'],inv['requests'][second['archiveId']][0]['previousArchiveId'])
        self.assertLess(inv['depths'][first['archiveId']],inv['depths'][second['archiveId']])
        self.base.refused('ALREADY_ARCHIVED',lambda:self.request([self.ref('operations',identities[0])]))

    def test_startup_archive_keeps_original_reads_beyond_32_and_preserves_a_fixed_maintenance_boundary(self):
        values=[self.startup() for _ in range(33)];selected=values[0]
        first,_=self.archive(*[self.ref('startups',value['operationId']) for value in values[:2]])
        inventory=self.manager.archives();head=inventory['head'];maintenance=self.maintenance(str(uuid.uuid4()))
        maintenance.update(schema=2,precedingArchiveId=head,
            precedingArchiveSha256=hashlib.sha256(service.encode(inventory['requests'][head][1])).hexdigest(),
            precedingStartupIds=sorted(v['operationId'] for v in values[2:]))
        self.manager.atomic(self.manager.state/'package-history'/(maintenance['maintenanceId']+'.json'),service.encode(maintenance))
        starter=starting.Starter(self.manager,runner=self.base.run_command);starter.manifest_digest=lambda:'e'*64
        self.assertEqual(33,len(starter.records()));self.assertEqual(selected,starter.record(selected['operationId']))
        self.assertTrue(starter.plan(selected['restoreOperationId'],selected['keySha256'])['startAllowed'])
        newer=self.startup();self.archive(self.ref('startups',newer['operationId']))
        self.assertFalse(starter.plan(newer['restoreOperationId'],newer['keySha256'])['startAllowed'])
        self.assertTrue(starter.plan(selected['restoreOperationId'],selected['keySha256'])['startAllowed'])
        policy=lifecycle.Lifecycle(self.manager.root,self.manager.owner);policy.initialize();policy.check_records()

    def test_package_history_above_128_retains_its_original_chain_and_reader(self):
        parent=None;identities=[]
        for _ in range(128):
            identity=str(uuid.uuid4());self.maintenance(identity,parent);identities.append(identity);parent=identity
        self.archive(*[self.ref('package-history',identity) for identity in identities[:2]])
        last=str(uuid.uuid4());self.maintenance(last,parent)
        starter=starting.Starter(self.manager,runner=self.base.run_command)
        self.assertEqual(last,starter.package_head()['maintenanceId'])
        self.assertEqual(129,len(list((self.manager.state/'package-history').iterdir())))
        lifecycle.Lifecycle(self.manager.root,self.manager.owner).check_records()

    def test_corrupt_maintenance_archive_pointer_is_not_authority_even_for_an_active_listed_startup(self):
        startup=self.startup();identity=self.backups(4)[0];self.archive(self.ref('operations',identity))
        head=self.manager.archives()['head'];value=self.maintenance(str(uuid.uuid4()))
        value.update(schema=2,precedingArchiveId=head,precedingArchiveSha256='f'*64,precedingStartupIds=[startup['operationId']])
        self.manager.atomic(self.manager.state/'package-history'/(value['maintenanceId']+'.json'),service.encode(value))
        before=self.originals();starter=starting.Starter(self.manager,runner=self.base.run_command);starter.manifest_digest=lambda:'e'*64
        self.base.refused('UNSAFE_JOURNAL',lambda:starter.plan(startup['restoreOperationId'],startup['keySha256']))
        with self.assertRaises(lifecycle.Refused):lifecycle.Lifecycle(self.manager.root,self.manager.owner).check_records()
        self.assertEqual(before,self.originals())

    def test_partial_archive_is_accepted_by_reader_without_releasing_active_capacity(self):
        identity=self.backups(4)[0];request=self.request([self.ref('operations',identity)]);atomic=self.manager.atomic
        def interrupted(path,raw,**options):
            if path.name.endswith('.receipt.json'):raise OSError('missing final metadata receipt')
            return atomic(path,raw,**options)
        with patch.object(self.manager,'atomic',side_effect=interrupted):self.base.refused('UNKNOWN',lambda:self.call(request))
        before=self.base.snapshot();policy=lifecycle.Lifecycle(self.manager.root,self.manager.owner);policy.initialize();policy.check_records()
        self.assertEqual(4,self.manager.active_records('operations',[p.name[:-5] for p in self.manager.operations.iterdir()]))
        self.assertEqual(before,self.base.snapshot())

    def test_revoked_authority_history_above_32_is_still_readable_and_does_not_reuse_old_fixed_ids(self):
        identities=[]
        for _ in range(32):
            self.fixture.create();identities.append(self.fixture.request['handoffId'])
            self.auth.command(self.fixture.wire('revoke'),os.getpid(),0,1001,42)
            self.fixture.request.update(**{key:str(uuid.uuid4()) for key in ('handoffId','publicationId','startOperationId')})
            self.base.grant_request=self.fixture.request
        before=self.originals();self.archive(*[self.ref('handoffs',identity) for identity in identities])
        self.assertEqual(before,self.originals());self.fixture.create()
        self.auth.command(self.fixture.wire('revoke'),os.getpid(),0,1001,42)
        self.assertEqual(33,len(list((self.manager.state/'handoffs').iterdir())))
        self.assertEqual(33,len(lifecycle.handoff_revocations(self.manager)))
        self.assertEqual(1,self.manager.active_records('handoffs',identities+[self.fixture.request['handoffId']]))
        policy=lifecycle.Lifecycle(self.manager.root,self.manager.owner);policy.initialize();policy.check_records()
        self.assertEqual(0,self.base.count_stops())

    def test_archiving_a_lease_preserves_its_window_but_does_not_request_or_reserve_start(self):
        self.fixture.publish(expire=True);lease=self.fixture.send(self.fixture.renewal());before=self.originals();calls=list(self.base.commands)
        self.archive(self.ref('operations',lease['operationId']));self.assertEqual(before,self.originals())
        self.fixture.no_start_reservation();self.assertEqual(calls,self.base.commands)
        self.assertTrue(self.auth.command(self.fixture.wire('start-lease-status'),os.getpid(),0,1001,42)['windowOpen'])
        started=self.fixture.send(self.fixture.wire('start'));self.assertEqual(self.fixture.request['startOperationId'],started['operationId'])

    def test_matching_but_foreign_publication_and_start_response_fields_do_not_close_authority(self):
        self.fixture.publish();self.fixture.send(self.fixture.wire('start'))
        for key in ('publicationId','startOperationId'):
            path=self.manager.operations/(self.fixture.request[key]+'.json');value=service.decode(path.read_bytes())
            value['response']['ringSha256']='f'*64;self.manager.atomic(path,service.encode(value))
        before=self.base.snapshot()
        self.base.refused('ARCHIVE_UNSETTLED',lambda:self.request([self.ref('handoffs',self.fixture.request['handoffId'])]))
        self.base.refused('ARCHIVE_UNSETTLED',lambda:self.request([self.ref('operations',self.fixture.request['publicationId'])]))
        self.assertEqual(before,self.base.snapshot())

    def test_wrong_startup_request_tag_does_not_become_a_signed_archive_proof(self):
        startup=self.startup();path=self.manager.state/'startups'/(startup['operationId']+'.json')
        startup['requestTag']='f'*64;self.manager.atomic(path,service.encode(startup));before=self.base.snapshot()
        self.base.refused('ARCHIVE_UNSETTLED',lambda:self.request([self.ref('startups',startup['operationId'])]))
        self.assertEqual(before,self.base.snapshot())

    def test_preparation_with_missing_original_history_cannot_be_archived(self):
        identity=self.fixture.request['preparationId'];path=self.manager.state/'generations'/identity/'history.json'
        path.unlink();before=self.base.snapshot()
        self.base.refused('ARCHIVE_UNSETTLED',lambda:self.request([self.ref('operations',identity)]))
        self.assertEqual(before,self.base.snapshot())

    def test_current_package_writer_emits_a_fixed_archive_boundary_without_expanding_the_active_startup_array(self):
        values=[self.startup() for _ in range(33)]
        self.archive(*[self.ref('startups',value['operationId']) for value in values[:2]])
        policy=lifecycle.Lifecycle(self.manager.root,self.manager.owner)
        identity=str(uuid.uuid4());marker=dict(schema=1,id=identity,state='MAINTENANCE',firstAction='upgrade')
        self.manager.atomic(self.manager.state/'maintenance.json',service.encode(marker))
        policy.leave();path=self.manager.state/'package-history'/(identity+'.json')
        snapshot=lifecycle.validate_maintenance(service.decode(path.read_bytes()),identity)
        self.assertEqual(2,snapshot['schema']);self.assertEqual(31,len(snapshot['precedingStartupIds']))
        self.assertTrue(lifecycle.maintenance_includes_startup(policy,snapshot,values[0]['operationId']))
        self.assertFalse((self.manager.state/'maintenance.json').exists())
        (self.manager.root/'run/systemd/system').mkdir(parents=True)
        calls=[]
        def runner(args,**options):
            calls.append(args);return SimpleNamespace(returncode=0,
                stdout='LoadState=loaded\nActiveState=inactive\nMainPID=0\nControlPID=0\n' if args[1]=='show' else '',stderr='')
        policy.runner=runner;policy.enter('upgrade');self.assertTrue(calls)
        self.assertEqual(snapshot,service.decode(path.read_bytes()))

    def test_archive_id_cannot_alias_any_fixed_unattempted_handoff_id(self):
        self.fixture.create();identity=self.backups(4)[0];request=self.request([self.ref('operations',identity)])
        before=self.base.snapshot()
        for key in ('handoffId','preparationId','verificationId','publicationId','startOperationId'):
            self.base.refused('CONFLICT',lambda:self.call(dict(request,archiveId=self.fixture.request[key])))
        self.assertEqual(before,self.base.snapshot());self.fixture.no_start_reservation()

    def test_archived_metadata_id_cannot_become_a_new_native_key_operation(self):
        identity=self.backups(4)[0];request,_=self.archive(self.ref('operations',identity));before=self.base.snapshot()
        native=dict(schema=1,action='backup-create',operationId=request['archiveId'],passphrase=self.base.password)
        self.fixture.rejected(self.fixture.frame(native),'CONFLICT')
        self.base.refused('CONFLICT',lambda:self.manager.handle(native));self.assertEqual(before,self.base.snapshot())

    def test_unmaterialized_issuer_prevents_an_archive_from_claiming_its_unknown_future_ids(self):
        identity=self.backups(4)[0];request=self.request([self.ref('operations',identity)])
        frame=self.fixture.frame(self.fixture.request);self.fixture.reserve(frame);before=self.base.snapshot()
        self.base.refused('UNRESOLVED_OPERATION',lambda:self.call(request));self.assertEqual(before,self.base.snapshot())
        self.assertEqual('RESERVED',self.shared.load(frame['admissionId'])['state'])

    def test_new_issuer_cannot_reserve_an_already_archived_metadata_id_for_publication(self):
        identity=self.backups(4)[0];request,_=self.archive(self.ref('operations',identity));before=self.base.snapshot()
        grant=dict(self.fixture.request,publicationId=request['archiveId']);frame=self.fixture.frame(grant)
        self.fixture.rejected(frame,'CONFLICT');self.assertEqual(before,self.base.snapshot())


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repository',required=True,type=Path)
    parser.add_argument('--java',required=True,type=Path);parser.add_argument('--cipher-jar',required=True,type=Path)
    options,remaining=parser.parse_known_args();original.base.package.CONFIG=options.repository.resolve()
    original.base.JAVA=options.java.resolve();original.base.CIPHER=options.cipher_jar.resolve()
    unittest.main(argv=[sys.argv[0],*remaining])
