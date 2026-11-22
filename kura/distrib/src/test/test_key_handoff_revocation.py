#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Real immutable storage, cipher and admission; original Core/systemd is modeled."""
import argparse
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

import test_key_handoff as original

service = original.service


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Disposable Linux Root/JDK21 only')
class UnusedHandoffRevocationTest(unittest.TestCase):
    def setUp(self):
        self.fixture = original.HandoffTest(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.manager = self.fixture.manager; self.auth = self.fixture.auth
        self.request = self.fixture.grant_request; self.token = self.fixture.create()['token']
        self.addCleanup(patch.stopall)
        patch.object(self.manager, 'handoff_component', return_value=self.auth).start()
        self.manager.sender_admissions.owner = lambda *args: dict(pid=os.getpid(), uid=0, startTicks='123', bootId=str(uuid.UUID(int=1, version=4)))

    def command(self, name):
        return self.auth.command(dict(schema=1, action='generation-handoff-command', command=name, token=self.token),
            os.getpid(), 0, 1001, 42)

    def replacement(self):
        return dict(self.request, **{key: str(uuid.uuid4()) for key in ('handoffId', 'publicationId', 'startOperationId')})

    def reservation(self, start=False):
        native = self.auth.operation_request(self.auth.load(self.request['handoffId']), start=start)
        value = dict(schema=1, action='sender-reserve', admissionId=str(uuid.uuid4()), source='local-admin',
            namespaceSha256=self.manager.gwt_namespace()['namespaceSha256'], request=native)
        self.manager.sender_admissions.reserve(value, os.getpid(), 0, 1001, 42)
        return value

    def refused(self, code, action):
        self.fixture.refused(code, action)

    def test_revocation_retains_authority_keys_and_preparation_and_never_stops_core(self):
        before = self.fixture.snapshot(); result = self.command('revoke'); after = self.fixture.snapshot()
        self.assertEqual('UNUSED_AUTHORITY_REVOKED', result['state'])
        self.assertEqual('FIXED_OPERATIONS_NOT_ADMITTED', result['scope'])
        self.assertEqual(before, {key: value for key, value in after.items() if key in before})
        self.assertEqual(1, len(set(after) - set(before)))
        self.assertEqual(0, self.fixture.count_stops())
        path = self.manager.state/'handoff-revocations'/(self.request['handoffId']+'.json')
        self.assertEqual(0o400, path.stat().st_mode & 0o777); self.assertEqual(1, path.stat().st_nlink)
        self.assertNotIn(self.token, path.read_text()); self.assertNotIn('backup', path.read_text())
        before = self.fixture.snapshot()
        self.assertEqual(result, self.command('revocation-read')); self.assertEqual(result, self.command('revoke'))
        self.assertEqual(before, self.fixture.snapshot())
        self.assertEqual('GRANT_REVOKED', self.command('info')['state'])
        self.assertFalse(self.command('info')['mutationWindowOpen'])

    def test_expiry_alone_cannot_reissue_but_explicit_revocation_keeps_preparation_and_verification(self):
        self.fixture.expire(); replacement = self.replacement()
        self.refused('HANDOFF_EXISTS', lambda: self.auth.create(replacement, os.getpid(), 0, 1001))
        self.command('revoke'); before = self.fixture.snapshot()
        new = self.auth.create(replacement, os.getpid(), 0, 1001)
        self.assertTrue(new['mutationWindowOpen']); self.assertNotEqual(self.token, new['token'])
        for key in ('preparationId', 'verificationId'): self.assertEqual(self.request[key], new[key])
        self.assertEqual(before, {key: value for key, value in self.fixture.snapshot().items() if key in before})
        for command in ('publish', 'start'):
            self.refused('HANDOFF_REVOKED', lambda: self.command(command))
        self.assertEqual('NOT_RECORDED', self.command('publication-read')['state'])

    def test_revocation_closes_reserved_native_ids_before_any_late_generic_dispatch(self):
        request = self.reservation(); self.command('revoke')
        self.assertEqual('NOT_ADMITTED', self.manager.sender_admissions.load(request['admissionId'])['state'])
        calls = []
        self.refused('UNRESOLVED_OPERATION', lambda: self.manager.sender_admissions.execute(dict(request, action='sender-command'),
            os.getpid(), 0, 1001, 42, lambda wire: calls.append(wire)))
        self.assertEqual([], calls)
        self.refused('HANDOFF_REVOKED', self.reservation)
        self.refused('HANDOFF_REVOKED', lambda: self.reservation(start=True))
        self.refused('HANDOFF_REVOKED', lambda: self.fixture.component.request(request['request']))

    def test_read_after_interrupted_reservation_closure_does_not_finish_metadata(self):
        request = self.reservation(); write = self.manager.sender_admissions.write
        with patch.object(self.manager.sender_admissions, 'write', side_effect=OSError('closure interrupted')):
            with self.assertRaises(OSError): self.command('revoke')
        before = self.fixture.snapshot()
        self.assertEqual('GRANT_REVOKING', self.command('info')['state'])
        self.refused('UNRESOLVED_OPERATION', lambda: self.command('revocation-read'))
        self.refused('HANDOFF_REVOKED', lambda: self.command('publish'))
        self.assertEqual(before, self.fixture.snapshot())
        self.command('revoke')
        self.assertEqual('NOT_ADMITTED', self.manager.sender_admissions.load(request['admissionId'])['state'])
        self.assertEqual('GRANT_REVOKED', self.command('info')['state'])

    def test_intake_without_native_original_remains_unknown_and_cannot_be_revoked(self):
        request = self.reservation()
        def uncertain(_): raise service.Failure('UNKNOWN')
        self.refused('UNKNOWN', lambda: self.manager.sender_admissions.execute(dict(request, action='sender-command'),
            os.getpid(), 0, 1001, 42, uncertain))
        before = self.fixture.snapshot()
        self.refused('UNRESOLVED_OPERATION', lambda: self.command('revoke'))
        self.assertEqual(before, self.fixture.snapshot())
        self.assertFalse((self.manager.state/'handoff-revocations').exists())

    def test_original_publication_intent_is_not_an_unused_grant(self):
        identity = self.request['publicationId']
        self.manager.atomic(self.manager.operations/(identity+'.json'), service.encode(dict(schema=1,
            operationId=identity, action='generation-publish', requestTag='0'*64, state='INTENT', response=None)))
        before = self.fixture.snapshot()
        self.refused('UNRESOLVED_OPERATION', lambda: self.command('revoke'))
        self.assertEqual(before, self.fixture.snapshot())

    def test_original_live_owner_is_required_even_for_legacy_grants_without_reservations(self):
        self.fixture.phase = 'stopped'; before = self.fixture.snapshot()
        self.refused('CORE_NOT_ACTIVE', lambda: self.command('revoke'))
        self.assertEqual(before, self.fixture.snapshot())

    def test_recovery_service_uid_without_actual_main_process_is_rejected(self):
        before = self.fixture.snapshot()
        with patch.object(self.manager, 'recovery_sender_owner', side_effect=service.Failure('FORBIDDEN')):
            self.refused('FORBIDDEN', lambda: self.auth.revoke(self.token, os.getpid(), 42, 1001, 42))
        self.assertEqual(before, self.fixture.snapshot())

    def test_changed_operator_or_reused_fixed_ids_never_reissue(self):
        self.command('revoke'); before = self.fixture.snapshot()
        for key in ('operator', 'verificationId', 'expectedCohortSha256'):
            request = self.replacement(); request[key] = 'other-admin' if key == 'operator' else str(uuid.uuid4()) if key == 'verificationId' else '0'*64
            self.refused('CONFLICT', lambda: self.auth.create(request, os.getpid(), 0, 1001))
        request = self.replacement(); request['publicationId'] = self.request['startOperationId']
        self.refused('HANDOFF_EXISTS', lambda: self.auth.create(request, os.getpid(), 0, 1001))
        self.assertEqual(before, self.fixture.snapshot())

    def test_corrupt_revocation_or_foreign_native_uuid_blocks_future_admission(self):
        self.command('revoke')
        path = self.manager.state/'handoff-revocations'/(self.request['handoffId']+'.json')
        value = service.decode(path.read_bytes()); value['revokedAt'] += 1
        self.manager.atomic(path, service.encode(value), mode=0o400)
        self.refused('UNSAFE_JOURNAL', lambda: self.command('info'))
        self.refused('UNSAFE_JOURNAL', lambda: self.manager.require_unrevoked_operation(str(uuid.uuid4())))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--cipher-jar', required=True, type=Path)
    options, remaining = parser.parse_known_args()
    original.base.package.CONFIG = options.repository.resolve(); original.base.JAVA = options.java.resolve(); original.base.CIPHER = options.cipher_jar.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
