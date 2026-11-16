#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Actual cipher, durable records and locks; Core/systemd remains the explicit model."""
import argparse
import os
from pathlib import Path
import sys
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import test_key_handoff as original

service = original.service


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Disposable Linux Root/JDK21 only')
class StartLeaseTest(unittest.TestCase):
    def setUp(self):
        self.fixture = original.HandoffTest(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.manager, self.auth = self.fixture.manager, self.fixture.auth
        self.request = self.fixture.grant_request; self.token = self.fixture.create()['token']
        self.addCleanup(patch.stopall)
        patch.object(self.manager, 'handoff_component', return_value=self.auth).start()
        self.manager.sender_admissions.owner = lambda source,pid,uid,*args: dict(pid=pid, uid=uid,
            startTicks='123', bootId=self.auth.load(self.request['handoffId'])['owner']['bootId'])

    def command(self, command, **extra):
        return self.auth.command(dict(schema=1, action='generation-handoff-command', token=self.token,
            command=command, **extra), os.getpid(), 0, 1001, 42)

    def publish(self):
        self.published = self.command('publish'); self.fixture.expire()

    def renew(self, identity=None, **extra):
        return self.command('start-renew', operationId=identity or str(uuid.uuid4()),
            expectedPublicationSha256=extra.pop('publication', self.published['publicationSha256']), **extra)

    def test_expired_post_publication_lease_only_reopens_the_fixed_first_start(self):
        self.publish(); before = self.fixture.snapshot()
        grant = (self.manager.state/'handoffs'/(self.request['handoffId']+'.json')).read_bytes()
        self.assertTrue(self.command('start-lease-status')['renewalAllowed'])
        self.assertEqual(before, self.fixture.snapshot())
        lease = self.renew()
        self.assertFalse(lease['credentialsChanged']); self.assertFalse(lease['startRequested'])
        self.assertEqual(1, self.fixture.count_stops())
        self.assertFalse(any(command[0] == '/usr/bin/busctl' for command in self.fixture.commands))
        self.assertEqual(grant, (self.manager.state/'handoffs'/(self.request['handoffId']+'.json')).read_bytes())
        after = self.fixture.snapshot()
        for path, metadata in before.items(): self.assertEqual(metadata, after[path], path)
        self.assertTrue(self.command('start-lease-status')['windowOpen'])
        started = self.command('start')
        self.assertEqual(self.request['startOperationId'], started['operationId'])
        self.assertEqual(1, self.fixture.count_stops())
        self.assertEqual(1, sum(command[0] == '/usr/bin/busctl' for command in self.fixture.commands))

    def test_original_lease_reads_and_repeated_request_never_extend_its_window(self):
        self.publish(); lease = self.renew(); before = self.fixture.snapshot()
        self.fixture.now += 10
        self.assertEqual(lease, self.command('start-lease-read', operationId=lease['operationId']))
        self.assertEqual(lease, self.renew(lease['operationId']))
        self.assertEqual(before, self.fixture.snapshot())
        self.fixture.expire(); self.assertFalse(self.command('start-lease-status')['windowOpen'])
        self.fixture.refused('HANDOFF_EXPIRED', lambda: self.command('start'))
        next_lease = self.renew()
        self.assertNotEqual(lease['operationId'], next_lease['operationId'])
        self.assertEqual(lease, self.command('start-lease-read', operationId=lease['operationId']))

    def test_no_publication_unknown_publication_or_current_window_cannot_renew(self):
        self.published = {'publicationSha256': '0'*64}
        self.fixture.refused('HANDOFF_WINDOW_OPEN', self.renew)
        self.fixture.expire(); self.fixture.refused('UNRESOLVED_OPERATION', self.renew)
        self.assertFalse(self.command('start-lease-status')['renewalAllowed'])

    def test_new_lease_never_replaces_any_original_id_or_wrong_publication(self):
        self.publish(); before = self.fixture.snapshot()
        for name in ('handoffId','preparationId','verificationId','publicationId','startOperationId'):
            self.fixture.refused('CONFLICT', lambda: self.renew(self.request[name]))
        self.fixture.refused('CONFLICT', lambda: self.renew(publication='0'*64))
        self.assertEqual(before, self.fixture.snapshot())

    def test_already_requested_or_unknown_start_is_never_renewed(self):
        self.published = self.command('publish'); self.command('start'); self.fixture.expire()
        before = self.fixture.snapshot(); self.fixture.refused('UNRESOLVED_OPERATION', self.renew)
        self.assertEqual(before, self.fixture.snapshot())

    def test_a_closed_original_start_reservation_is_still_permanently_fenced(self):
        self.publish(); value = self.auth.load(self.request['handoffId'])
        native = self.auth.operation_request(value, start=True)
        reservation = dict(schema=1, action='sender-reserve', admissionId=str(uuid.uuid4()), source='local-admin',
            namespaceSha256=self.manager.gwt_namespace()['namespaceSha256'], request=native)
        self.manager.sender_admissions.reserve(reservation, os.getpid(), 0, 1001, 42)
        read = {k:reservation[k] for k in ('schema','admissionId','source','namespaceSha256')};read['action']='sender-admission-close'
        self.manager.sender_admissions.read(read, os.getpid(), 0, 1001, 42, close=True)
        self.fixture.refused('UNRESOLVED_OPERATION', self.renew)

    def test_modified_lease_hmac_does_not_authorize_start(self):
        self.publish(); lease = self.renew(); path = self.manager.operations/(lease['operationId']+'.json')
        record = service.decode(path.read_bytes()); record['response']['issuedAt'] += 1; record['response']['expiresAt'] += 1
        self.manager.atomic(path, service.encode(record))
        self.fixture.refused('UNSAFE_JOURNAL', lambda: self.command('start-lease-status'))
        self.fixture.refused('UNSAFE_JOURNAL', lambda: self.command('start'))

    def test_changed_publication_request_tag_or_current_cohort_never_mints_a_lease(self):
        self.publish(); path = self.manager.operations/(self.request['publicationId']+'.json')
        raw = path.read_bytes(); record = service.decode(raw); record['requestTag'] = 'f'*64
        self.manager.atomic(path, service.encode(record)); before = self.fixture.snapshot()
        self.fixture.refused('UNRESOLVED_OPERATION', self.renew); self.assertEqual(before, self.fixture.snapshot())
        self.manager.atomic(path, raw)
        with patch.object(self.manager, 'require_generation_cohort', return_value=dict(self.fixture.cohort,cohortSha256='0'*64)):
            with self.assertRaises(service.Failure): self.renew()

    def test_core_principal_and_another_recovery_process_cannot_renew(self):
        self.publish(); before = self.fixture.snapshot()
        request = dict(schema=1,action='generation-handoff-command',token=self.token,command='start-renew',
            operationId=str(uuid.uuid4()),expectedPublicationSha256=self.published['publicationSha256'])
        self.fixture.refused('FORBIDDEN', lambda: self.auth.command(request,os.getpid(),1001,1001,42))
        with patch.object(self.manager,'recovery_sender_owner',side_effect=service.Failure('FORBIDDEN')):
            self.fixture.refused('FORBIDDEN', lambda: self.auth.command(request,os.getpid(),42,1001,42))
        self.assertEqual(before,self.fixture.snapshot())

    def test_previous_boot_and_cross_directory_start_alias_never_mint_a_lease(self):
        self.publish(); read = Path.read_text; foreign = str(uuid.uuid4())
        with patch.object(Path,'read_text',lambda path,*args,**kwargs:foreign if str(path)=='/proc/sys/kernel/random/boot_id' else read(path,*args,**kwargs)):
            self.fixture.refused('OWNER_CHANGED',self.renew)
        parent=self.manager.state/'startups';parent.mkdir(mode=0o700,exist_ok=True)
        self.fixture.put(parent/(self.request['startOperationId']+'.json'),b'preserved incompatible native alias')
        before=self.fixture.snapshot();self.fixture.refused('UNRESOLVED_OPERATION',self.renew);self.assertEqual(before,self.fixture.snapshot())

    def test_lost_reply_recovers_only_original_and_partial_intent_never_becomes_a_new_lease(self):
        self.publish(); identity = str(uuid.uuid4()); atomic = self.manager.atomic
        def interrupt(path, raw, **options):
            if path == self.manager.operations/(identity+'.json') and service.decode(raw)['state'] == 'SUCCEEDED':
                raise OSError('injected lease completion failure')
            return atomic(path, raw, **options)
        with patch.object(self.manager, 'atomic', side_effect=interrupt):
            self.fixture.refused('UNKNOWN', lambda: self.renew(identity))
        before = self.fixture.snapshot()
        self.assertEqual('UNKNOWN', self.command('start-lease-read', operationId=identity)['state'])
        self.assertEqual('UNKNOWN', self.renew(identity)['state'])
        self.fixture.refused('UNRESOLVED_OPERATION', self.renew)
        self.assertEqual(before, self.fixture.snapshot())

    def test_shared_intake_is_durable_before_lease_and_late_frames_never_run_twice(self):
        self.publish(); identity = str(uuid.uuid4())
        wire = dict(schema=1, action='generation-handoff-command', token=self.token, command='start-renew',
            operationId=identity, expectedPublicationSha256=self.published['publicationSha256'])
        request = dict(schema=1, action='sender-reserve', admissionId=str(uuid.uuid4()), source='recovery',
            namespaceSha256=self.manager.gwt_namespace()['namespaceSha256'], request=wire)
        self.manager.sender_admissions.reserve(request, os.getpid(), 42, 1001, 42)
        calls = []
        def dispatch(_):
            self.assertEqual('INTAKE', self.manager.sender_admissions.load(request['admissionId'])['state'])
            calls.append(1)
            return self.command('start-renew', operationId=identity, expectedPublicationSha256=self.published['publicationSha256']), None
        result, _ = self.manager.sender_admissions.execute(dict(request, action='sender-command'), os.getpid(), 42, 1001, 42, dispatch)
        self.assertEqual(identity, result['operationId'])
        import kura_key_service_lifecycle as lifecycle
        metadata = {key:value for key,value in wire.items() if key != 'token'}; metadata['handoffId'] = self.request['handoffId']
        attempt = dict(schema=1,purpose='yofc.kura.sender-attempt.v1',admissionId=request['admissionId'],
            kind='handoff-renewal',nativeOperationId=identity,request=metadata)
        policy = SimpleNamespace(state=self.manager.state,read=self.manager.read,directory=self.manager.directory)
        namespace = dict(schema=1,namespaceSha256=request['namespaceSha256'])
        self.assertEqual('TERMINAL',lifecycle.check_sender_attempt(policy,attempt,namespace,'recovery',42)['state'])
        changed = dict(attempt,request=dict(metadata,expectedPublicationSha256='f'*64))
        with self.assertRaises(lifecycle.Refused):lifecycle.check_sender_attempt(policy,changed,namespace,'recovery',42)
        self.fixture.refused('UNRESOLVED_OPERATION', lambda: self.manager.sender_admissions.execute(
            dict(request, action='sender-command'), os.getpid(), 42, 1001, 42, dispatch))
        self.assertEqual([1], calls)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--cipher-jar', required=True, type=Path)
    options, remaining = parser.parse_known_args()
    original.base.package.CONFIG = options.repository.resolve(); original.base.JAVA = options.java.resolve(); original.base.CIPHER = options.cipher_jar.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
