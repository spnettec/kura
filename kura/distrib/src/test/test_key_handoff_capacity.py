#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Actual Root storage/HMAC/crypto/flock; historical padding and Core/systemd are models."""
import argparse
import hashlib
import hmac
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

import test_key_handoff as original

service = original.service


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Disposable Linux Root/JDK21 only')
class HandoffCapacityTest(unittest.TestCase):
    def setUp(self):
        self.fixture = original.HandoffTest(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.manager, self.auth = self.fixture.manager, self.fixture.auth
        self.request = self.fixture.grant_request; self.token = None
        self.addCleanup(patch.stopall)
        patch.object(self.manager, 'handoff_component', return_value=self.auth).start()
        self.reset_coordinator()

    def reset_coordinator(self):
        self.coordinator = service.SenderAdmissions(self.manager); self.manager.sender_admissions = self.coordinator
        self.coordinator.owner = lambda source,pid,uid,*args: dict(pid=pid, uid=uid, startTicks='123',
            bootId=Path('/proc/sys/kernel/random/boot_id').read_text().strip())

    def create(self):
        self.token = self.fixture.create()['token']

    def wire(self, command, **extra):
        return dict(schema=1, action='generation-handoff-command', token=self.token, command=command, **extra)

    def frame(self, native, source='local-admin'):
        return dict(schema=1, action='sender-reserve', admissionId=str(uuid.uuid4()), source=source,
            namespaceSha256=self.manager.gwt_namespace()['namespaceSha256'], request=native)

    def reserve(self, frame):
        return self.coordinator.reserve(frame, os.getpid(), 0 if frame['source']=='local-admin' else 42, 1001, 42)

    def execute(self, frame):
        return self.coordinator.execute(dict(frame, action='sender-command'), os.getpid(), 0, 1001, 42,
            lambda wire: service.serve_request(self.manager, wire, os.getpid(), 0, 1001, 42, None))[0]

    def send(self, native):
        frame = self.frame(native); self.assertTrue(self.reserve(frame)['newlyReserved'])
        return self.execute(frame)

    def close(self, frame):
        query = {k:frame[k] for k in ('schema','admissionId','source','namespaceSha256')}
        return self.coordinator.read(dict(query,action='sender-admission-close'), os.getpid(), 0, 1001, 42, close=True)

    def publish(self, *, expire=False):
        self.create(); self.published = self.auth.command(self.wire('publish'), os.getpid(), 0, 1001, 42)
        if expire: self.fixture.expire()

    def renewal(self):
        return self.wire('start-renew', operationId=str(uuid.uuid4()), expectedPublicationSha256=self.published['publicationSha256'])

    def backup(self):
        return dict(schema=1, action='generation-backup-create', operationId=str(uuid.uuid4()), passphrase=self.fixture.password)

    def fill_native(self, count):
        while len(list(self.manager.operations.iterdir())) < count:
            identity = str(uuid.uuid4()); native = dict(schema=1, action='backup-create', operationId=identity, passphrase='modeled-history-padding')
            record = dict(schema=1, operationId=identity, action='backup-create', requestTag=self.coordinator.tag(native),
                state='SUCCEEDED', response=dict(schema=1, operationId=identity, action='backup-create', state='SUCCEEDED',
                    backup=dict(format=service.FORMAT, operationId=identity, encrypted='YQ==')))
            self.manager.atomic(self.manager.operations/(identity+'.json'), service.encode(record))

    def fill_shared(self, count):
        while len(self.coordinator.records()) < count:
            native = dict(schema=1, action='backup-create', operationId=str(uuid.uuid4()), passphrase='modeled-history-padding')
            self.coordinator.write(dict(schema=1, purpose=service.SENDER_ADMISSION_PURPOSE, admissionId=str(uuid.uuid4()),
                source='local-admin', namespaceSha256=self.manager.gwt_namespace()['namespaceSha256'],
                owner=self.coordinator.owner('local-admin',os.getpid(),0), requestTag=self.coordinator.tag(native),
                target=self.coordinator.native_target(native), parentAdmissionId=None, state='NOT_ADMITTED'), create=True)

    def rejected(self, frame, reason='CAPACITY'):
        before = self.fixture.snapshot()
        self.fixture.refused(reason, lambda:self.reserve(frame))
        self.assertIsNone(self.coordinator.load(frame['admissionId']))
        self.assertEqual(before,self.fixture.snapshot())

    def no_start_reservation(self):
        identity = self.request['startOperationId']
        self.assertIsNone(self.manager.record(identity))
        self.assertFalse(any(row['target']['operationId']==identity for row in self.coordinator.records()))

    def clone_historical_grant(self):
        value = self.auth.load(self.request['handoffId']); other = dict(value)
        other['request'] = dict(value['request'],**{key:str(uuid.uuid4()) for key in
            ('handoffId','preparationId','verificationId','publicationId','startOperationId')})
        other['requestTag'] = self.coordinator.tag(other['request']); other.pop('receiptTag')
        other['receiptTag'] = hmac.new(self.auth.secret(),b'yofc-kura-generation-handoff-receipt-v1\0'+service.encode(other),hashlib.sha256).hexdigest()
        self.manager.atomic(self.manager.state/'handoffs'/(other['request']['handoffId']+'.json'),service.encode(other),mode=0o400,no_replace=True)
        return other

    def test_255_shared_rows_refuse_renewal_before_any_reservation_or_intake(self):
        self.publish(expire=True); self.fill_shared(255); self.no_start_reservation()
        frame = self.frame(self.renewal()); self.rejected(frame)
        self.assertIsNone(self.manager.record(frame['request']['operationId'])); self.no_start_reservation()
        self.assertTrue(self.reserve(self.frame(self.wire('start')))['newlyReserved'])

    def test_255_native_rows_refuse_renewal_before_any_reservation_or_intake(self):
        self.publish(expire=True); self.fill_native(255); self.no_start_reservation()
        frame = self.frame(self.renewal()); self.rejected(frame)
        self.assertIsNone(self.manager.record(frame['request']['operationId'])); self.no_start_reservation()
        self.assertTrue(self.reserve(self.frame(self.wire('start')))['newlyReserved'])

    def test_254_both_rows_allow_one_renewal_and_the_same_original_start_to_finish_at_256(self):
        self.publish(expire=True); self.fill_shared(254); self.fill_native(254); self.no_start_reservation()
        grant = self.fixture.snapshot()[str((self.manager.state/'handoffs'/(self.request['handoffId']+'.json')).relative_to(self.fixture.root))]
        lease = self.send(self.renewal()); self.assertEqual('SUCCEEDED',lease['state']); self.no_start_reservation()
        started = self.send(self.wire('start'))
        self.assertEqual(self.request['startOperationId'],started['operationId'])
        self.assertEqual('SYSTEMD_JOB_ACCEPTED',started['scope'])
        self.assertEqual(256,len(self.coordinator.records())); self.assertEqual(256,len(list(self.manager.operations.iterdir())))
        self.assertEqual(grant,self.fixture.snapshot()[str((self.manager.state/'handoffs'/(self.request['handoffId']+'.json')).relative_to(self.fixture.root))])
        self.assertEqual(1,sum(command[0]=='/usr/bin/busctl' for command in self.fixture.commands))

    def test_unrelated_backup_cannot_spend_the_original_start_capacity(self):
        self.publish(); self.fill_shared(254); self.fill_native(254)
        self.assertEqual('SUCCEEDED',self.send(self.backup())['state'])
        self.rejected(self.frame(self.backup())); self.no_start_reservation()
        self.assertEqual(self.request['startOperationId'],self.send(self.wire('start'))['operationId'])

    def test_another_sender_denial_cannot_spend_pending_issuer_promises(self):
        self.fill_shared(253); self.fill_native(254)
        frame = self.frame(self.request); self.reserve(frame)
        restore = dict(schema=1,action='restore',operationId=str(uuid.uuid4()),expectedKeySha256='1'*64,
            backup=dict(format=service.FORMAT,operationId=str(uuid.uuid4()),encrypted='YQ=='),passphrase=self.fixture.password)
        self.rejected(self.frame(restore,source='recovery'))
        self.assertEqual('RESERVED',self.coordinator.load(frame['admissionId'])['state'])
        self.assertFalse((self.manager.state/'handoffs').exists())

    def test_issuer_requires_own_admission_and_two_future_admissions_before_intake(self):
        self.fill_shared(254); self.rejected(self.frame(self.request))
        self.assertFalse((self.manager.state/'handoffs').exists()); self.assertEqual(0,self.fixture.count_stops())

    def test_issuer_requires_two_native_slots_before_intake(self):
        self.fill_native(255); self.rejected(self.frame(self.request))
        self.assertFalse((self.manager.state/'handoffs').exists()); self.assertEqual(0,self.fixture.count_stops())

    def test_direct_native_issuer_also_refuses_an_overcommitted_grant_without_side_effects(self):
        self.fill_native(255); before = self.fixture.snapshot()
        self.fixture.refused('CAPACITY',self.create); self.assertEqual(before,self.fixture.snapshot())

    def test_pending_issuer_survives_coordinator_recreation_and_materializes_without_double_counting(self):
        self.fill_shared(253); self.fill_native(254); frame = self.frame(self.request); self.reserve(frame)
        before = self.fixture.snapshot(); self.reset_coordinator()
        self.rejected(self.frame(self.backup())); self.assertEqual(before,self.fixture.snapshot())
        self.token = self.execute(frame)['token']; self.no_start_reservation()
        self.assertEqual(254,len(self.coordinator.records())); self.assertEqual(254,len(list(self.manager.operations.iterdir())))
        self.send(self.wire('publish')); self.send(self.wire('start'))
        self.assertEqual(256,len(self.coordinator.records())); self.assertEqual(256,len(list(self.manager.operations.iterdir())))

    def test_only_explicit_positive_no_admission_releases_pending_issuer_promises(self):
        self.fill_shared(253); self.fill_native(254); frame = self.frame(self.request); self.reserve(frame)
        before = self.fixture.snapshot(); self.reset_coordinator(); self.rejected(self.frame(self.backup()))
        self.assertEqual(before,self.fixture.snapshot()); self.assertEqual('NOT_ADMITTED',self.close(frame)['state'])
        self.assertTrue(self.reserve(self.frame(self.backup()))['newlyReserved'])
        self.fixture.refused('UNRESOLVED_OPERATION',lambda:self.execute(frame))
        self.assertFalse((self.manager.state/'handoffs').exists())

    def test_saved_old_reservation_cannot_enter_intake_when_its_native_slot_would_steal_start(self):
        self.publish(expire=True); self.fill_native(255); frame = self.frame(self.renewal())
        target = self.coordinator.target(frame['request'],'local-admin',os.getpid(),0,1001)
        self.coordinator.write(dict(schema=1,purpose=service.SENDER_ADMISSION_PURPOSE,admissionId=frame['admissionId'],
            source='local-admin',namespaceSha256=frame['namespaceSha256'],owner=self.coordinator.owner('local-admin',os.getpid(),0),
            requestTag=self.coordinator.tag(frame['request']),target=target,parentAdmissionId=None,state='RESERVED'),create=True)
        before = self.fixture.snapshot(); self.fixture.refused('CAPACITY',lambda:self.execute(frame))
        self.assertEqual(before,self.fixture.snapshot()); self.assertEqual('RESERVED',self.coordinator.load(frame['admissionId'])['state'])
        self.assertIsNone(self.manager.record(frame['request']['operationId'])); self.no_start_reservation()

    def test_old_shared_overcommit_remains_reserved_before_any_native_dispatch(self):
        self.publish(expire=True); frame = self.frame(self.renewal()); self.reserve(frame); self.fill_shared(256)
        before = self.fixture.snapshot(); self.fixture.refused('CAPACITY',lambda:self.execute(frame))
        self.assertEqual(before,self.fixture.snapshot()); self.assertEqual('RESERVED',self.coordinator.load(frame['admissionId'])['state'])
        self.assertIsNone(self.manager.record(frame['request']['operationId'])); self.no_start_reservation()

    def test_old_intake_missing_original_stays_unknown_and_cannot_close_or_redispatch(self):
        self.publish(expire=True); frame = self.frame(self.renewal()); self.reserve(frame)
        self.coordinator.write(dict(self.coordinator.load(frame['admissionId']),state='INTAKE'))
        before = self.fixture.snapshot()
        for action in (lambda:self.execute(frame),lambda:self.close(frame)):
            self.fixture.refused('UNRESOLVED_OPERATION',action)
        self.assertEqual(before,self.fixture.snapshot()); self.assertIsNone(self.manager.record(frame['request']['operationId']))

    def test_issued_grant_promises_do_not_expire_or_turn_into_actual_start_reservations(self):
        self.create(); self.fill_shared(254); self.fill_native(254); self.fixture.expire(); self.reset_coordinator()
        self.no_start_reservation(); self.rejected(self.frame(self.backup())); self.no_start_reservation()
        self.assertEqual(0,self.fixture.count_stops())

    def test_positive_unused_revocation_releases_both_promises_but_fences_old_ids(self):
        self.create(); self.fill_shared(254); self.fill_native(254); self.rejected(self.frame(self.backup()))
        result = self.auth.command(self.wire('revoke'),os.getpid(),0,1001,42)
        self.assertEqual('UNUSED_AUTHORITY_REVOKED',result['state'])
        self.assertTrue(self.reserve(self.frame(self.backup()))['newlyReserved'])
        self.rejected(self.frame(self.wire('publish')),'HANDOFF_REVOKED')

    def test_durable_revocation_fences_a_late_frame_even_before_reserved_sender_is_closed(self):
        self.create(); frame = self.frame(self.wire('publish')); self.reserve(frame)
        with patch.object(self.coordinator,'write',side_effect=OSError('interrupt after immutable revocation')):
            with self.assertRaises(OSError):self.auth.command(self.wire('revoke'),os.getpid(),0,1001,42)
        self.fill_native(255); before = self.fixture.snapshot()
        # Capacity is released by the permanent Root fence; the old reservation
        # is retained and still has to be explicitly settled by its owner.
        with self.coordinator.locked(),self.manager.lock(self.manager.state/'admission.lock',False):
            self.coordinator.require_capacity()
        self.fixture.refused('HANDOFF_REVOKED',lambda:self.execute(frame))
        self.assertEqual(before,self.fixture.snapshot()); self.assertEqual('RESERVED',self.coordinator.load(frame['admissionId'])['state'])
        self.auth.command(self.wire('revoke'),os.getpid(),0,1001,42)
        self.assertEqual('NOT_ADMITTED',self.coordinator.load(frame['admissionId'])['state'])
        self.assertTrue(self.reserve(self.frame(self.backup()))['newlyReserved'])

    def test_issued_closed_original_start_still_cannot_be_replaced_or_renewed(self):
        self.publish(expire=True); frame = self.frame(self.wire('start')); self.reserve(frame); self.close(frame)
        self.rejected(self.frame(self.wire('start')),'CONFLICT')
        before = self.fixture.snapshot()
        self.fixture.refused('UNRESOLVED_OPERATION',lambda:self.auth.command(self.renewal(),os.getpid(),0,1001,42))
        self.assertEqual(before,self.fixture.snapshot())

    def test_other_directory_or_request_tag_cannot_consume_an_original_promise(self):
        self.create()
        native = self.auth.operation_request(self.auth.load(self.request['handoffId']),start=True)
        self.rejected(self.frame(dict(native,expectedCohortSha256='0'*64)),'CONFLICT')
        self.rejected(self.frame(dict(schema=1,action='core-start',operationId=native['operationId'],
            restoreOperationId=str(uuid.uuid4()),expectedKeySha256='1'*64)),'CONFLICT')
        before = self.fixture.snapshot()
        self.fixture.refused('CONFLICT',lambda:self.manager.handle(dict(native,expectedCohortSha256='0'*64)))
        self.assertEqual(before,self.fixture.snapshot()); self.no_start_reservation()

    def test_corrupted_grant_and_foreign_admission_namespace_are_not_rebuilt(self):
        self.create(); path = self.manager.state/'handoffs'/(self.request['handoffId']+'.json')
        raw = path.read_bytes(); value = service.decode(raw); value['receiptTag']='0'*64
        self.manager.atomic(path,service.encode(value),mode=0o400)
        self.rejected(self.frame(self.backup()),'UNSAFE_JOURNAL')
        self.manager.atomic(path,raw,mode=0o400)
        self.fill_shared(1); row = self.coordinator.records()[0]
        value = dict(row,namespaceSha256='f'*64); value.pop('receiptTag')
        value['receiptTag'] = hmac.new(self.coordinator.secret(),service.SENDER_ADMISSION_CONTEXT+service.encode(value),hashlib.sha256).hexdigest()
        self.manager.atomic(self.coordinator.directory/(value['admissionId']+'.json'),service.encode(value))
        before = self.fixture.snapshot(); self.fixture.refused('CONFLICT',lambda:self.reserve(self.frame(self.backup())))
        self.assertEqual(before,self.fixture.snapshot())

    def test_multiple_authenticated_historical_grants_keep_separate_fixed_promises(self):
        self.create(); self.clone_historical_grant()
        self.fill_shared(252); self.fill_native(252); self.rejected(self.frame(self.backup()))
        self.no_start_reservation(); self.assertEqual(0,self.fixture.count_stops())

    def test_full_authority_table_refuses_another_issuer_before_intake(self):
        self.create()
        for _ in range(31):self.clone_historical_grant()
        request = dict(self.request,**{key:str(uuid.uuid4()) for key in ('handoffId','publicationId','startOperationId')})
        self.rejected(self.frame(request)); self.assertEqual(32,len(list((self.manager.state/'handoffs').iterdir())))

    def test_old_missing_grant_intake_keeps_anonymous_promises_and_is_not_closed_by_reads(self):
        self.fill_shared(253); self.fill_native(254); frame = self.frame(self.request); self.reserve(frame)
        self.coordinator.write(dict(self.coordinator.load(frame['admissionId']),state='INTAKE')); self.reset_coordinator()
        before = self.fixture.snapshot(); self.rejected(self.frame(self.backup()))
        self.fixture.refused('UNRESOLVED_OPERATION',lambda:self.close(frame))
        self.fixture.refused('UNRESOLVED_OPERATION',lambda:self.execute(frame))
        self.assertEqual(before,self.fixture.snapshot()); self.assertFalse((self.manager.state/'handoffs').exists())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository',required=True,type=Path); parser.add_argument('--java',required=True,type=Path)
    parser.add_argument('--cipher-jar',required=True,type=Path); options,remaining = parser.parse_known_args()
    original.base.package.CONFIG=options.repository.resolve(); original.base.JAVA=options.java.resolve(); original.base.CIPHER=options.cipher_jar.resolve()
    unittest.main(argv=[sys.argv[0],*remaining])
