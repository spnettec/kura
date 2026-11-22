#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Disposable filesystem/crypto models. Never adopt or mutate an installed gateway."""
import argparse
import hashlib
import stat
import sys
import unittest
from unittest.mock import patch
import uuid

import test_key_service as base

service = base.service


class PreparationHistoryTest(unittest.TestCase):
    setUp = base.KeyServiceTest.setUp
    write = base.KeyServiceTest.__dict__['write']
    request = base.KeyServiceTest.__dict__['request']
    refused = base.KeyServiceTest.refused
    prepare_request = base.KeyServiceTest.prepare_request
    verification_request = base.KeyServiceTest.verification_request
    snapshot = base.KeyServiceTest.preparation_read_snapshot

    def prepare(self, verified=False):
        result = self.manager.handle(self.prepare_request())
        if verified:
            self.manager.handle(self.verification_request(result))
        return result

    def cancel_request(self, prepared):
        return self.request('generation-cancel', operationId=str(uuid.uuid4()),
                            preparationId=prepared['operationId'], expectedHistorySha256=prepared['historySha256'],
                            expectedRingSha256=prepared['generation']['ringSha256'])

    def history(self, cursor=None, limit=16):
        return self.manager.handle(self.request('generation-history', afterPreparationId=cursor, limit=limit))

    def unknown_cancel(self, *, marker=True):
        prepared = self.prepare();request = self.cancel_request(prepared)
        original = self.manager.atomic
        def fail(path, value, **options):
            if (marker and path == self.manager.operations / (request['operationId'] + '.json')
                    and service.decode(value)['state'] == 'SUCCEEDED'):
                raise OSError('Fixture lost final cancellation receipt')
            if not marker and path.name == 'cancellation.json':
                raise OSError('Fixture lost cancellation marker')
            return original(path, value, **options)
        with patch.object(self.manager, 'atomic', side_effect=fail):
            self.refused('UNKNOWN', lambda: self.manager.handle(request))
        return prepared, request

    def recovery(self, request, fingerprint=None):
        path = self.state / 'generations' / request['preparationId'] / 'cancellation.json'
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest() if fingerprint is None else fingerprint
        return self.request('generation-cancel-recover', operationId=request['operationId'],
                            expectedCancellationSha256=fingerprint)

    def assert_preserved(self, before, except_paths=()):
        after = self.snapshot()
        for path, value in before.items():
            if path not in except_paths:self.assertEqual(value, after.get(path), path)

    def test_cancel_retains_every_original_file_and_same_request_never_writes_again(self):
        prepared = self.prepare();before = self.snapshot();request = self.cancel_request(prepared)
        with patch.object(self.manager, 'crypt', side_effect=AssertionError('Cancel must not encrypt')):
            result = self.manager.handle(request)
        self.assertEqual('SUCCEEDED', result['state']);self.assertFalse(result['credentialsChanged'])
        self.assertTrue(result['historyRetained']);self.assert_preserved(before)
        marker = self.state / 'generations' / prepared['operationId'] / 'cancellation.json'
        self.assertEqual(0o400, stat.S_IMODE(marker.stat().st_mode))
        self.assertEqual(1, marker.stat().st_nlink)
        self.assertEqual('CANCELLED', self.history()['entries'][0]['state'])
        before = self.snapshot()
        with patch.object(self.manager, 'atomic', side_effect=AssertionError('Original result is read-only')):
            self.assertEqual(result, self.manager.handle(request))
        self.assertEqual(before, self.snapshot())
        self.refused('ALREADY_CANCELLED', lambda: self.manager.handle(self.cancel_request(prepared)))

    def test_cancel_verified_preparation_allows_next_round_without_removing_history_or_switching_keys(self):
        first = self.prepare(verified=True);original = self.key_path.read_bytes();first_files = self.snapshot()
        self.manager.handle(self.cancel_request(first));self.assert_preserved(first_files)
        old_ring = self.state / 'generations' / first['operationId'] / 'keyring'
        inode = old_ring.stat().st_ino;raw = old_ring.read_bytes()
        second = self.prepare();self.assertNotEqual(first['operationId'], second['operationId'])
        self.assertNotEqual(first['generation']['activeKeySha256'], second['generation']['activeKeySha256'])
        self.assertEqual(original, self.key_path.read_bytes())
        self.assertEqual(inode, old_ring.stat().st_ino);self.assertEqual(raw, old_ring.read_bytes())
        rows = {row['preparationId']:row['state'] for row in self.history()['entries']}
        self.assertEqual({first['operationId']:'CANCELLED',second['operationId']:'PREPARED'}, rows)
        self.refused('PREPARATION_CANCELLED', lambda: self.manager.handle(self.verification_request(first)))
        self.refused('PREPARATION_CANCELLED', lambda: self.manager.require_open_preparation(first['operationId']))

    def test_open_prepared_and_verified_rounds_block_new_keys_before_any_intent(self):
        prepared = self.prepare()
        for verified in (False, True):
            if verified:self.manager.handle(self.verification_request(prepared))
            before = self.snapshot()
            with patch.object(self.manager, 'crypt', side_effect=AssertionError('Must not prepare another key')):
                self.refused('PREPARATION_PENDING', lambda: self.prepare())
            self.assertEqual(before, self.snapshot())

    def test_cancel_requires_original_fingerprints_and_strict_fields_before_intent(self):
        prepared = self.prepare();request = self.cancel_request(prepared);before = self.snapshot()
        for field in ('expectedHistorySha256', 'expectedRingSha256'):
            bad = dict(request, **{field:'0'*64})
            self.refused('CONFLICT', lambda:self.manager.handle(bad))
        for field in ('force', 'erase', 'passphrase'):
            self.refused('INVALID_ARGUMENT', lambda:self.manager.handle(dict(request, **{field:True})))
        self.refused('INVALID_ARGUMENT', lambda:self.manager.handle(dict(request, preparationId='../escape')))
        self.assertEqual(before, self.snapshot())

    def test_cancel_refuses_a_foreign_canonical_source_without_replacing_any_files(self):
        prepared = self.prepare();foreign = b'F'*32
        self.write(self.key_path, foreign, 0o400)
        proof = dict(self.proof, keySha256=hashlib.sha256(foreign).hexdigest())
        self.write(self.receipt_path, service.encode(proof), 0o600)
        before = self.snapshot()
        self.refused('CONFLICT', lambda:self.manager.handle(self.cancel_request(prepared)))
        self.assertEqual(before, self.snapshot())

    def test_lost_cancel_reply_remains_unknown_and_blocks_start_new_ids_and_preparation(self):
        prepared, request = self.unknown_cancel();before = self.snapshot()
        with patch.object(self.manager, 'atomic', side_effect=AssertionError('Do not redispatch UNKNOWN')):
            self.assertEqual('UNKNOWN', self.manager.handle(request)['state'])
            self.refused('UNRESOLVED_OPERATION', lambda:self.manager.handle(self.cancel_request(prepared)))
            self.refused('UNRESOLVED_OPERATION', lambda:self.prepare())
            self.refused('UNRESOLVED_OPERATION', lambda:self.manager.handle(self.request(
                'credential-start-admission', keySha256=self.proof['keySha256'], ringSha256=None)))
        history = self.history();self.assertTrue(history['hasUnresolvedRecords'])
        self.assertEqual('UNKNOWN', history['entries'][0]['state'])
        self.assertIn('cancellationSha256', history['entries'][0])
        self.assertEqual(before, self.snapshot())

    def test_recovery_finishes_only_the_existing_original_marker_and_keeps_its_inode(self):
        prepared, request = self.unknown_cancel();before = self.snapshot();recovery = self.recovery(request)
        original_atomic = self.manager.atomic;writes = []
        journal = self.manager.operations / (request['operationId'] + '.json')
        def finish(path, value, **options):
            self.assertEqual(journal, path);writes.append(path)
            return original_atomic(path, value, **options)
        with patch.object(self.manager, 'atomic', side_effect=finish):
            result = self.manager.handle(recovery)
        self.assertEqual([journal], writes);self.assertEqual(request['operationId'], result['operationId'])
        self.assertEqual('SUCCEEDED', result['state'])
        self.assert_preserved(before, [str(journal.relative_to(self.root))])
        before = self.snapshot()
        with patch.object(self.manager, 'atomic', side_effect=AssertionError('Only read the original result')):
            self.assertEqual(result, self.manager.handle(recovery));self.assertEqual(result, self.manager.handle(request))
        self.assertEqual(before, self.snapshot());self.assertFalse(self.history()['hasUnresolvedRecords'])
        self.assertEqual('CANCELLED', self.history()['entries'][0]['state'])
        self.prepare()  # A new round is authorized only after the original cancellation is settled.

    def test_missing_original_cancel_marker_is_never_fabricated_or_reaccepted(self):
        prepared, request = self.unknown_cancel(marker=False);before = self.snapshot()
        with patch.object(self.manager, 'atomic', side_effect=AssertionError('No original marker')):
            self.assertEqual('UNKNOWN', self.manager.handle(self.recovery(request, '0'*64))['state'])
            self.assertEqual('UNKNOWN', self.manager.handle(request)['state'])
        self.assertNotIn('cancellationSha256', self.history()['entries'][0])
        self.assertEqual(before, self.snapshot())
        self.refused('UNRESOLVED_OPERATION', lambda:self.prepare())

    def test_cancel_recovery_cannot_ignore_any_other_original_unknown(self):
        _, request = self.unknown_cancel()
        other = str(uuid.uuid4())
        self.write(self.manager.operations / (other + '.json'), service.encode(dict(schema=1,
            operationId=other, action='backup-create', requestTag='b'*64, state='INTENT', response=None)), 0o600)
        before = self.snapshot()
        self.refused('UNRESOLVED_OPERATION', lambda:self.manager.handle(self.recovery(request)))
        self.assertEqual(before, self.snapshot())

    def test_tampered_cancel_marker_and_wrong_recovery_hash_cannot_settle_the_original_record(self):
        prepared, request = self.unknown_cancel();before = self.snapshot()
        self.refused('CONFLICT', lambda:self.manager.handle(self.recovery(request, '0'*64)))
        self.assertEqual(before, self.snapshot())
        marker = self.state / 'generations' / prepared['operationId'] / 'cancellation.json'
        original = marker.read_bytes();value = service.decode(original);value['createdAt'] = 'forged'
        self.write(marker, service.encode(value), 0o400);before = self.snapshot()
        self.refused('UNSAFE_JOURNAL', lambda:self.manager.handle(self.recovery(request)))
        self.assertEqual('UNAVAILABLE', self.history()['entries'][0]['state'])
        self.assertEqual(before, self.snapshot())

    def test_cancel_intent_cannot_be_retargeted_after_an_unknown_result(self):
        _, request = self.unknown_cancel();path = self.manager.operations / (request['operationId'] + '.json')
        record = service.decode(path.read_bytes());record['intent']['preparationId'] = str(uuid.uuid4())
        self.write(path, service.encode(record), 0o600);before = self.snapshot()
        self.refused('UNSAFE_JOURNAL', lambda:self.manager.record(request['operationId']))
        self.assertEqual(before, self.snapshot())

    def test_missing_completed_cancel_receipt_or_its_operation_never_reopens_a_preparation(self):
        prepared = self.prepare();request = self.cancel_request(prepared);self.manager.handle(request)
        marker = self.state / 'generations' / prepared['operationId'] / 'cancellation.json'
        raw = marker.read_bytes();marker.unlink()
        self.refused('UNSAFE_JOURNAL', lambda:self.manager.require_open_preparation(prepared['operationId']))
        self.refused('UNSAFE_JOURNAL', lambda:self.prepare())
        self.write(marker, raw, 0o400)
        (self.manager.operations / (request['operationId'] + '.json')).unlink()
        self.refused('UNSAFE_JOURNAL', lambda:self.prepare())

    def test_history_pages_original_events_and_preserves_every_file(self):
        identities = []
        for _ in range(4):
            prepared = self.prepare();identities.append(prepared['operationId'])
            self.manager.handle(self.cancel_request(prepared))
        before = self.snapshot();seen = [];cursor = None;revision = None
        while True:
            page = self.history(cursor, 2)
            self.assertEqual('HISTORICAL_EVENTS_ONLY', page['scope'])
            if revision is None:revision = page['historyRevision']
            self.assertEqual(revision, page['historyRevision'])
            seen += [row['preparationId'] for row in page['entries']]
            cursor = page['nextAfterPreparationId']
            if cursor is None:break
        self.assertEqual(sorted(identities), seen);self.assertEqual(before, self.snapshot())
        self.assertNotIn(base.PASSWORD.encode(), service.encode(page))
        self.refused('CONFLICT', lambda:self.history(str(uuid.uuid4())))
        for limit in (True, 0, 17):self.refused('INVALID_ARGUMENT', lambda:self.history(limit=limit))

    def test_orphaned_original_history_blocks_new_preparation_and_is_not_removed(self):
        identity = str(uuid.uuid4());directory = self.state / 'generations' / identity
        directory.mkdir(parents=True, mode=0o700);self.write(directory / 'keyring', b'original-private-orphan', 0o400)
        before = self.snapshot();self.assertEqual('ORPHANED', self.history()['entries'][0]['state'])
        self.refused('PREPARATION_PENDING', lambda:self.prepare())
        self.assertEqual(before, self.snapshot())

    def test_recovery_and_agent_peers_cannot_dispatch_cancel_or_history(self):
        for action in ('generation-cancel', 'generation-cancel-recover', 'generation-history'):
            request = self.request(action)
            self.refused('FORBIDDEN', lambda:self.manager.handle(request, recovery_only=True))
            with patch.object(service, 'agent_peer', return_value=True):
                self.refused('FORBIDDEN', lambda:service.serve_request(self.manager, request, 123, 0, 999, None, None))


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--cipher-jar', required=True)
    parser.add_argument('--java', default='/usr/bin/java');base.CONFIG, remaining = parser.parse_known_args()
    unittest.main(argv=[sys.argv[0], *remaining])
