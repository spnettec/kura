#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Real storage/crypto/flock; Core/systemd authority remains the explicit model."""
import argparse
import hashlib
import hmac
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

import test_key_generation_publication as base

service = base.service


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Disposable Linux Root/JDK21 only')
class HandoffTest(unittest.TestCase):
    copy = staticmethod(base.GenerationPublicationTest.copy)
    put = staticmethod(base.GenerationPublicationTest.put)
    close_lease = base.GenerationPublicationTest.close_lease
    set_group = base.GenerationPublicationTest.set_group
    run_command = base.GenerationPublicationTest.run_command
    count_stops = base.GenerationPublicationTest.count_stops
    admission = base.GenerationPublicationTest.admission
    refused = base.GenerationPublicationTest.refused

    def setUp(self):
        base.GenerationPublicationTest.setUp(self)
        self.auth = self.manager.handoff_component()
        self.auth.generations = self.component
        self.now = 100_000_000_000
        self.auth.clock = lambda: self.now
        self.grant_request = dict(schema=1, action='generation-handoff-create', handoffId=str(uuid.uuid4()),
            preparationId=self.preparation, verificationId=self.verification,
            publicationId=self.publish_request['operationId'], startOperationId=str(uuid.uuid4()),
            expectedRingSha256=self.prepared['generation']['ringSha256'], expectedCohortSha256=self.cohort['cohortSha256'],
            operator='网关管理员')

    def create(self):
        return self.auth.create(self.grant_request, os.getpid(), 0, 1001)

    def read(self, token=False):
        return self.auth.read(dict(schema=1, action='generation-handoff-token-read' if token else 'generation-handoff-read',
                                  handoffId=self.grant_request['handoffId']), os.getpid(), 0, 1001, token=token)

    def command(self, token, name, **values):
        return self.auth.command(dict(schema=1, action='generation-handoff-command', token=token, command=name, **values),
                                 os.getpid(), 42, 1001, 42)

    def snapshot(self):
        return {str(p.relative_to(self.root)): self.component.file_snapshot(p)
                for folder in (self.directory, self.state) for p in folder.rglob('*') if p.is_file()}

    def expire(self):
        self.now += 900_000_000_001

    def interrupt_publication(self, token, *, after_stop=True):
        atomic = self.manager.atomic
        def fail(path, value, **options):
            if after_stop and path == self.directory / 'kura_encryption_key':
                raise OSError('injected partial canonical write')
            return atomic(path, value, **options)
        if after_stop:
            with patch.object(self.manager, 'atomic', side_effect=fail):
                self.refused('UNKNOWN', lambda: self.command(token, 'publish'))
        else:
            import subprocess
            self.stop_error = subprocess.TimeoutExpired('original StopUnit', 50)
            self.refused('UNKNOWN', lambda: self.command(token, 'publish'))

    def test_create_records_only_authority_and_preserves_all_existing_files(self):
        before = self.snapshot(); result = self.create(); after = self.snapshot()
        self.assertEqual('GRANT_RECORDED', result['state'])
        self.assertEqual('ORIGINAL_AUTHORIZATION_ONLY', result['scope'])
        self.assertFalse(result['startupAuthorized'])
        self.assertTrue(result['mutationWindowOpen'])
        self.assertEqual(900, result['expiresAt'] - result['issuedAt'])
        self.assertEqual(before, {path: value for path, value in after.items() if path in before})
        self.assertEqual(1, len(set(after) - set(before)))
        path = self.state / 'handoffs' / (self.grant_request['handoffId'] + '.json')
        value = service.decode(path.read_bytes())
        self.assertNotIn(result['token'], path.read_text())
        self.assertNotIn('token', value)
        self.assertNotIn('keyring', value)
        self.assertNotIn('backup', value)
        self.assertEqual(0o400, path.stat().st_mode & 0o777)
        self.assertEqual(1, path.stat().st_nlink)
        self.assertEqual(0, self.count_stops())
        self.assertEqual(2, len(list(self.manager.operations.iterdir())))

    def test_same_original_authority_and_token_read_never_generate_a_new_nonce_or_extend_time(self):
        original = self.create(); before = self.snapshot(); self.now += 100
        self.assertEqual(original, self.create())
        with patch.object(self.auth.__class__.__init__.__globals__['secrets'], 'token_hex', side_effect=AssertionError('No new nonce')):
            self.assertEqual(original, self.read(token=True))
        metadata = self.read()
        self.assertNotIn('token', metadata)
        self.assertEqual(before, self.snapshot())

    def test_lost_creation_reply_is_recovered_by_reading_the_same_authority(self):
        atomic = self.manager.atomic
        def lost(path, value, **options):
            result = atomic(path, value, **options)
            if path.parent.name == 'handoffs':
                raise OSError('injected lost authority reply')
            return result
        with patch.object(self.manager, 'atomic', side_effect=lost):
            with self.assertRaises(OSError):
                self.create()
        before = self.snapshot()
        self.assertEqual('GRANT_RECORDED', self.read()['state'])
        token = self.read(token=True)['token']
        self.assertEqual(self.grant_request['publicationId'], self.command(token, 'info')['publicationId'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(0, self.count_stops())

    def test_missing_authority_does_not_mint_token_or_write_anything(self):
        before = self.snapshot()
        self.assertEqual('NOT_RECORDED', self.read(token=True)['state'])
        self.assertEqual(before, self.snapshot())

    def test_cold_principal_never_issues_or_reads_the_token_by_id(self):
        before = self.snapshot()
        self.refused('FORBIDDEN', lambda: self.auth.create(self.grant_request, 1, 42, 1001))
        self.assertEqual(before, self.snapshot())
        self.create()
        for token in (False, True):
            request = dict(schema=1, action='generation-handoff-token-read' if token else 'generation-handoff-read',
                           handoffId=self.grant_request['handoffId'])
            self.refused('FORBIDDEN', lambda: self.auth.read(request, 1, 42, 1001, token=token))

    def test_another_core_uid_process_is_not_the_registered_owner(self):
        self.refused('FORBIDDEN', lambda: self.auth.create(self.grant_request, os.getpid() + 1, 1001, 1001))
        self.assertFalse((self.state / 'handoffs').exists())

    def test_wrong_fields_ids_cohort_and_invalid_operator_are_rejected_before_authority(self):
        before = self.snapshot()
        for operator in ('', ' ', 'x\n', 'x' * 129, '\ud800'):
            request = dict(self.grant_request, operator=operator)
            self.refused('INVALID_ARGUMENT', lambda: self.auth.create(request, os.getpid(), 0, 1001))
        request = dict(self.grant_request, startOperationId=self.preparation)
        self.refused('INVALID_ARGUMENT', lambda: self.auth.create(request, os.getpid(), 0, 1001))
        request = dict(self.grant_request, expectedCohortSha256='0' * 64)
        self.refused('COHORT_CHANGED', lambda: self.auth.create(request, os.getpid(), 0, 1001))
        request = dict(self.grant_request, command='/bin/false')
        self.refused('INVALID_ARGUMENT', lambda: self.auth.create(request, os.getpid(), 0, 1001))
        self.assertEqual(before, self.snapshot())

    def test_one_preparation_cannot_issue_an_alternative_authority_or_operation_ids(self):
        self.create(); before = self.snapshot()
        request = dict(self.grant_request, handoffId=str(uuid.uuid4()), publicationId=str(uuid.uuid4()),
                       startOperationId=str(uuid.uuid4()))
        self.refused('HANDOFF_EXISTS', lambda: self.auth.create(request, os.getpid(), 0, 1001))
        request = dict(self.grant_request, operator='另一个管理员')
        self.refused('CONFLICT', lambda: self.auth.create(request, os.getpid(), 0, 1001))
        self.assertEqual(before, self.snapshot())

    def test_metadata_does_not_leak_token_or_authorize_a_missing_operation(self):
        issued = self.create(); before = self.snapshot()
        self.assertNotIn('token', self.command(issued['token'], 'info'))
        for command, field in [('publication-read', 'publicationId'), ('start-read', 'startOperationId')]:
            result = self.command(issued['token'], command)
            self.assertEqual('NOT_RECORDED', result['state'])
            self.assertEqual(self.grant_request[field], result['operationId'])
        self.assertEqual(before, self.snapshot())

    def test_modified_token_and_record_do_not_authorize_commands(self):
        issued = self.create(); token = issued['token']
        changed = token[:-1] + ('0' if token[-1] != '0' else '1')
        before = self.snapshot()
        self.refused('FORBIDDEN', lambda: self.command(changed, 'info'))
        self.assertEqual(before, self.snapshot())
        path = self.state / 'handoffs' / (self.grant_request['handoffId'] + '.json')
        value = service.decode(path.read_bytes()); value['request']['publicationId'] = str(uuid.uuid4())
        self.manager.atomic(path, service.encode(value), mode=0o400)
        before = self.snapshot()
        self.refused('UNSAFE_JOURNAL', lambda: self.command(token, 'info'))
        self.assertEqual(before, self.snapshot())

    def test_receipt_hmac_is_not_a_bearer_token(self):
        self.create()
        value = self.auth.load(self.grant_request['handoffId'])
        token = 'KURA-HANDOFF-1.' + self.grant_request['handoffId'] + '.' + value['receiptTag']
        self.refused('FORBIDDEN', lambda: self.command(token, 'info'))

    def test_foreign_same_id_publication_record_is_not_the_granted_original(self):
        token = self.create()['token']; identity = self.grant_request['publicationId']
        self.manager.atomic(self.manager.operations / (identity + '.json'), service.encode(dict(schema=1,
            operationId=identity, action='generation-publish', state='INTENT', response=None, requestTag='0' * 64)))
        before = self.snapshot()
        for command in ('publication-read', 'publish'):
            self.refused('CONFLICT', lambda: self.command(token, command))
        self.assertEqual(before, self.snapshot()); self.assertEqual(0, self.count_stops())

    def test_foreign_same_id_start_record_is_not_the_granted_original(self):
        token = self.create()['token']; identity = self.grant_request['startOperationId']
        self.manager.atomic(self.manager.operations / (identity + '.json'), service.encode(dict(schema=1,
            operationId=identity, action='generation-core-start', state='INTENT', response=None, requestTag='0' * 64)))
        before = self.snapshot()
        for command in ('start-read', 'start'):
            self.refused('CONFLICT', lambda: self.command(token, command))
        self.assertEqual(before, self.snapshot())

    def test_prior_boot_authority_only_allows_historical_queries(self):
        self.create(); path = self.state / 'handoffs' / (self.grant_request['handoffId'] + '.json')
        value = self.auth.load(self.grant_request['handoffId'])
        value['owner']['bootId'] = str(uuid.uuid4())
        value.pop('receiptTag')
        context = self.auth.__class__.__init__.__globals__['HANDOFF_RECEIPT']
        value['receiptTag'] = hmac.new(self.auth.secret(), context + service.encode(value), hashlib.sha256).hexdigest()
        self.manager.atomic(path, service.encode(value), mode=0o400)
        token = self.auth.token(value); before = self.snapshot()
        self.assertFalse(self.command(token, 'info')['mutationWindowOpen'])
        self.refused('HANDOFF_EXPIRED', lambda: self.command(token, 'publish'))
        self.assertEqual('NOT_RECORDED', self.command(token, 'publication-read')['state'])
        self.assertEqual(before, self.snapshot())

    def test_maintenance_fence_also_applies_to_bearer_metadata(self):
        token = self.create()['token']; before = self.snapshot()
        with patch.object(self.manager, 'maintenance', side_effect=service.Failure('MAINTENANCE')):
            self.refused('MAINTENANCE', lambda: self.command(token, 'info'))
        self.assertEqual(before, self.snapshot())

    def test_extra_paths_commands_and_operation_ids_are_never_forwarded(self):
        token = self.create()['token']; before = self.snapshot()
        request = dict(schema=1, action='generation-handoff-command', token=token, command='publish',
                       publicationId=str(uuid.uuid4()))
        self.refused('INVALID_ARGUMENT', lambda: self.auth.command(request, 1, 42, 1001, 42))
        self.refused('INVALID_ARGUMENT', lambda: self.command(token, 'restore'))
        self.refused('INVALID_ARGUMENT', lambda: self.command(token, 'continue', expectedRecoveryReceiptSha256=None))
        self.assertEqual(before, self.snapshot())

    def test_core_uid_cannot_mutate_through_the_independent_handoff(self):
        token = self.create()['token']; before = self.snapshot()
        for command in ('publish', 'start'):
            request = dict(schema=1, action='generation-handoff-command', token=token, command=command)
            self.refused('FORBIDDEN', lambda: self.auth.command(request, os.getpid(), 1001, 1001, 42))
        self.assertEqual(before, self.snapshot())

    def test_expiration_prevents_first_publish_but_keeps_original_queries(self):
        token = self.create()['token']; self.expire(); before = self.snapshot()
        self.assertFalse(self.command(token, 'info')['mutationWindowOpen'])
        self.refused('HANDOFF_EXPIRED', lambda: self.command(token, 'publish'))
        self.assertEqual('NOT_RECORDED', self.command(token, 'publication-read')['state'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(0, self.count_stops())

    def test_monotonic_clock_before_issue_is_not_a_new_authorization_window(self):
        token = self.create()['token']; self.now -= 1
        self.refused('HANDOFF_EXPIRED', lambda: self.command(token, 'publish'))
        self.assertEqual(0, self.count_stops())

    def test_current_owner_is_checked_inside_original_publication_admission(self):
        token = self.create()['token']; active = self.component.active_core
        def different(*args):
            unit, writer = active(*args)
            return dict(unit, InvocationID='2' * 32), writer
        before = self.snapshot()
        with patch.object(self.component, 'active_core', side_effect=different):
            self.refused('OWNER_CHANGED', lambda: self.command(token, 'publish'))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(0, self.count_stops())

    def test_explicit_publish_then_separate_start_use_only_the_recorded_ids(self):
        token = self.create()['token']
        published = self.command(token, 'publish')
        self.assertEqual(self.grant_request['publicationId'], published['operationId'])
        self.assertTrue(published['requiresExplicitStart'])
        self.assertEqual(1, self.count_stops())
        self.refused('GENERATION_START_REQUIRED', self.admission)
        self.assertFalse(any(command[0] == '/usr/bin/busctl' for command in self.commands))
        started = self.command(token, 'start')
        self.assertEqual(self.grant_request['startOperationId'], started['operationId'])
        self.assertEqual('SYSTEMD_JOB_ACCEPTED', started['scope'])
        self.assertEqual('CREDENTIAL_READY', self.admission()['state'])
        before = self.snapshot(); commands = list(self.commands); self.expire()
        self.assertEqual(published, self.command(token, 'publish'))
        self.assertEqual(started, self.command(token, 'start'))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(commands, self.commands)

    def test_expired_first_start_remains_blocked_after_committed_publication(self):
        token = self.create()['token']; self.command(token, 'publish'); self.expire(); before = self.snapshot()
        self.refused('HANDOFF_EXPIRED', lambda: self.command(token, 'start'))
        self.assertEqual(before, self.snapshot())
        self.assertFalse(any(command[0] == '/usr/bin/busctl' for command in self.commands))

    def test_replaced_runtime_lock_cannot_use_the_granted_first_start(self):
        token = self.create()['token']; self.command(token, 'publish')
        self.manager.atomic(self.manager.writer_directory() / 'lease.lock', b'')
        before = self.snapshot()
        self.refused('UNSAFE_WRITER_STATE', lambda: self.command(token, 'start'))
        self.assertEqual(before, self.snapshot())
        self.assertFalse(any(command[0] == '/usr/bin/busctl' for command in self.commands))

    def test_unknown_publication_is_query_only_on_repeat_even_after_expiry(self):
        token = self.create()['token']; self.interrupt_publication(token, after_stop=False); self.expire()
        before = self.snapshot(); commands = list(self.commands)
        self.assertEqual('UNKNOWN', self.command(token, 'publish')['state'])
        info = self.command(token, 'publication-read')
        self.assertEqual('UNKNOWN', info['state'])
        self.assertIsNone(info['recoveryReceiptSha256'])
        self.assertEqual('UNKNOWN', self.command(token, 'continue', expectedRecoveryReceiptSha256='0' * 64)['state'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(commands, self.commands)

    def test_original_local_continuation_can_finish_an_already_admitted_publication_after_window(self):
        token = self.create()['token']; self.interrupt_publication(token); self.expire()
        info = self.command(token, 'publication-read')
        directory = self.state / 'generations' / self.preparation
        before = {p.name: self.component.file_snapshot(p) for p in directory.iterdir() if p.is_file()}
        self.assertEqual('UNKNOWN', self.command(token, 'publish')['state'])
        result = self.command(token, 'continue', expectedRecoveryReceiptSha256=info['recoveryReceiptSha256'])
        self.assertEqual('SUCCEEDED', result['state'])
        self.assertEqual(self.grant_request['publicationId'], result['operationId'])
        self.assertEqual(before, {name: self.component.file_snapshot(directory / name) for name in before})
        self.assertEqual(1, self.count_stops())
        self.refused('GENERATION_START_REQUIRED', self.admission)

    def test_unknown_start_never_dispatches_a_second_systemd_job(self):
        token = self.create()['token']; self.command(token, 'publish'); atomic = self.manager.atomic
        def lost(path, value, **options):
            if path.name == self.grant_request['startOperationId'] + '.json' and service.decode(value)['state'] == 'SUCCEEDED':
                raise OSError('injected lost final start result')
            return atomic(path, value, **options)
        with patch.object(self.manager, 'atomic', side_effect=lost):
            self.refused('UNKNOWN', lambda: self.command(token, 'start'))
        commands = list(self.commands); self.expire()
        self.assertEqual('UNKNOWN', self.command(token, 'start')['state'])
        self.assertEqual('UNKNOWN', self.command(token, 'start-read')['state'])
        self.assertEqual(commands, self.commands)
        self.assertEqual(1, sum(command[0] == '/usr/bin/busctl' for command in self.commands))

    def test_other_original_unknown_does_not_disappear_behind_a_valid_grant(self):
        token = self.create()['token']; identity = str(uuid.uuid4())
        self.manager.atomic(self.manager.operations / (identity + '.json'), service.encode(dict(schema=1,
            operationId=identity, action='backup-create', state='INTENT', response=None, requestTag='0' * 64)))
        before = self.snapshot()
        self.refused('UNRESOLVED_OPERATION', lambda: self.command(token, 'publish'))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(0, self.count_stops())

    def test_arriving_agent_keeps_publication_fenced(self):
        token = self.create()['token']; unit = self.root / 'etc/systemd/system/kura-management-agent.service'
        unit.parent.mkdir(parents=True, exist_ok=True); self.put(unit, b'[Service]\nExecStart=/bin/false\n')
        before = self.snapshot()
        self.refused('AGENT_GENERATION_UNAVAILABLE', lambda: self.command(token, 'publish'))
        self.assertEqual(before, self.snapshot())

    def test_token_cannot_be_retrieved_when_the_recorded_core_owner_is_gone(self):
        self.create(); self.phase = 'stopped'; before = self.snapshot()
        self.refused('CORE_NOT_ACTIVE', lambda: self.read(token=True))
        self.assertNotIn('token', self.read())
        self.assertEqual(before, self.snapshot())

    def test_cold_backup_authority_and_agent_peer_do_not_gain_unscoped_native_actions(self):
        token = self.create()['token']; before = self.snapshot()
        for action in ('generation-publish', 'generation-publication-recover', 'generation-core-start'):
            self.refused('FORBIDDEN', lambda: self.manager.handle(dict(schema=1, action=action), recovery_only=True))
        request = dict(schema=1, action='generation-handoff-command', token=token, command='info')
        with patch.object(service, 'agent_peer', return_value=True):
            self.refused('FORBIDDEN', lambda: service.serve_request(self.manager, request, 1, 0, 1001, 42, None))
        with patch.object(service, 'agent_peer', return_value=False), patch.object(self.manager, 'handoff_component', return_value=self.auth):
            response, descriptor = service.serve_request(self.manager, request, 1, 42, 1001, 42, None)
            self.assertIsNone(descriptor); self.assertEqual('ORIGINAL_AUTHORIZATION_ONLY', response['scope'])
            self.refused('PROTOCOL_MISMATCH', lambda: service.serve_request(self.manager, request, 1, 42, 1001, 42, 9))
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--cipher-jar', required=True, type=Path)
    options, remaining = parser.parse_known_args()
    base.package.CONFIG = options.repository.resolve(); base.JAVA = options.java.resolve(); base.CIPHER = options.cipher_jar.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
