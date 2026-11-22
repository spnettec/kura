#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_recovery_input as stage
import kura_native_recovery_input as native
from kura_key_service import Failure, Lifecycle, Manager


@unittest.skipUnless(sys.platform == 'linux', 'Linux atomic publication required')
class RecoveryInputTest(unittest.TestCase):
    identity = 'rec-11111111-1111-4111-8111-111111111111'
    binding = 'a' * 64
    contents = b'fixture snapshot for a separately tested validator'
    sha = hashlib.sha256(contents).hexdigest()

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.manager = Manager(self.root, os.geteuid())
        self.lifecycle = Lifecycle(self.root, os.geteuid())
        for lock in ('/var/lib/kura-key-service/admission.lock', '/etc/kura/credentials/.provision.lock'):
            path = self.lifecycle.path(lock)
            self.lifecycle.directory(path.parent, private=True, create=True)
            self.lifecycle.create(path, b'')
        self.manager.maintenance = Mock()
        self.manager.settled = Mock()
        self.validator = Mock()
        self.validator.binding.return_value = ({}, self.binding)
        self.manager.validation_component = Mock(return_value=self.validator)
        self.stage = stage.RecoveryInput(self.manager, self.lifecycle)
        self.input = self.root / 'input'
        self.lifecycle.create(self.input, self.contents)

    def submit(self, *, expected=None):
        with self.input.open('rb') as content:
            return self.stage.stage(self.identity, content.fileno(), expected or self.sha,
                                    'aes-gcm', 'authenticated', self.binding)

    def test_stage_is_immutable_and_original_checks_stored_artifact(self):
        self.assertEqual('RECOVERY_INPUT_ABSENT', self.stage.original(self.identity)['state'])
        result = self.submit()
        self.assertEqual('RECOVERY_INPUT_STAGED', result['state'])
        self.assertEqual(result, self.stage.original(self.identity))
        self.assertEqual(self.sha, result['snapshotSha256'])
        artifact = self.stage.spool / self.identity / stage.ARTIFACT
        self.assertEqual(self.contents, artifact.read_bytes())
        self.assertEqual(0o600, artifact.stat().st_mode & 0o777)
        with self.assertRaisesRegex(Failure, 'RECOVERY_INPUT_EXISTS'):
            self.submit()
        self.validator.validate.assert_called_once()
        artifact.write_bytes(b'bad data')
        with self.assertRaisesRegex(Failure, 'UNSAFE_FILESYSTEM'):
            self.stage.original(self.identity)

    def test_receipt_ready_interruption_resumes_only_on_same_binding_without_revalidation(self):
        with patch.object(stage, 'rename_no_replace', side_effect=OSError):
            with self.assertRaisesRegex(Failure, 'UNKNOWN'):
                self.submit()
        ready = self.stage.original(self.identity)
        self.assertEqual('RECOVERY_INPUT_READY', ready['state'])
        self.assertEqual(self.sha, ready['snapshotSha256'])
        source = self.stage.spool / ('.pending-' + self.identity) / stage.ARTIFACT
        inode = source.stat().st_ino
        self.input.unlink()
        with self.assertRaisesRegex(Failure, 'RECOVERY_INPUT_EXISTS'):
            with source.open('rb') as content:
                self.stage.stage(self.identity, content.fileno(), self.sha, 'aes-gcm', 'authenticated', self.binding)
        self.validator.binding.return_value = ({}, 'b' * 64)
        with self.assertRaisesRegex(Failure, 'COHORT_CHANGED'):
            self.stage.continue_ready(self.identity)
        self.validator.binding.return_value = ({}, self.binding)
        result = self.stage.continue_ready(self.identity)
        self.assertEqual(result, self.stage.original(self.identity))
        self.assertEqual(inode, (self.stage.spool / self.identity / stage.ARTIFACT).stat().st_ino)
        self.validator.validate.assert_called_once()

    def test_wrong_digest_and_maintenance_never_publish(self):
        with self.assertRaisesRegex(Failure, 'RECOVERY_INPUT_CHANGED'):
            self.submit(expected='e' * 64)
        self.assertEqual('RECOVERY_INPUT_ABSENT', self.stage.original(self.identity)['state'])
        self.manager.maintenance.side_effect = Failure('MAINTENANCE')
        with self.assertRaisesRegex(Failure, 'MAINTENANCE'):
            self.submit()
        self.assertEqual('RECOVERY_INPUT_ABSENT', self.stage.original(self.identity)['state'])
        self.validator.validate.assert_not_called()

    def test_writable_input_and_incomplete_reservation_cannot_publish(self):
        with self.input.open('r+b') as content:
            with self.assertRaisesRegex(Failure, 'UNSAFE_RECOVERY_INPUT'):
                self.stage.stage(self.identity, content.fileno(), self.sha, 'plain', 'legacy', self.binding)
        pending = self.stage.spool / ('.pending-' + self.identity)
        pending.mkdir(mode=0o700)
        self.assertEqual('RECOVERY_INPUT_PENDING', self.stage.original(self.identity)['state'])
        with self.assertRaisesRegex(Failure, 'UNSAFE_FILESYSTEM'):
            self.stage.continue_ready(self.identity)
        self.assertTrue(pending.is_dir())
        self.validator.validate.assert_not_called()

    def delegation(self):
        options = dict(restoreId=self.identity, snapshotSha256=self.sha, size=len(self.contents),
                       mode='aes-gcm', passwordPolicy='authenticated', bindingSha256=self.binding)
        peer = dict(schema=1, purpose='test-peer', invocationId='a' * 32, bootId='test-boot',
                    rootDevice=1, rootInode=1, identitySha256='b' * 64)
        result = native.grant(self.stage, options, lambda: peer)
        self.assertEqual('RECOVERY_INPUT_GRANTED', result['state'])
        return dict(schema=1, action='recovery-input-stage', **options), peer

    def test_delegation_must_match_every_field_and_the_granted_invocation(self):
        request, peer = self.delegation()
        original = dict(schema=1, action='recovery-input-original', restoreId=self.identity)
        with self.input.open('rb') as artifact:
            for changed, authenticate in ((request | {'size': request['size'] + 1}, lambda: peer),
                                          (request, lambda: peer | {'invocationId': 'c' * 32})):
                with self.assertRaisesRegex(Failure, 'FORBIDDEN'):
                    native.handle(self.stage, changed, artifact.fileno(), self.manager.owner, authenticate)
            self.assertEqual('RECOVERY_INPUT_GRANTED',
                native.handle(self.stage, original, None, self.manager.owner, lambda: peer)['state'])
            with self.assertRaisesRegex(Failure, 'RECOVERY_INPUT_EXISTS'):
                self.submit()
            receipt = native.handle(self.stage, request, artifact.fileno(), self.manager.owner, lambda: peer)
        self.assertEqual('RECOVERY_INPUT_STAGED', receipt['state'])
        self.assertEqual(receipt, native.handle(self.stage, original, None, self.manager.owner,
                                                lambda: peer | {'invocationId': 'c' * 32}))
        with self.assertRaisesRegex(Failure, 'FORBIDDEN'):
            native.handle(self.stage, original, None, self.manager.owner, lambda: peer | {'rootInode': 2})
        self.validator.validate.assert_called_once()

    def test_failed_submission_leaves_attempt_and_never_admits_a_second_descriptor(self):
        request, peer = self.delegation()
        self.validator.validate.side_effect = Failure('VALIDATION_REJECTED')
        with self.input.open('rb') as artifact:
            with self.assertRaisesRegex(Failure, 'VALIDATION_REJECTED'):
                native.handle(self.stage, request, artifact.fileno(), self.manager.owner, lambda: peer)
            self.assertEqual('RECOVERY_INPUT_ATTEMPTED', self.stage.original(self.identity)['state'])
            with self.assertRaisesRegex(Failure, 'RECOVERY_INPUT_EXISTS'):
                native.handle(self.stage, request, artifact.fileno(), self.manager.owner, lambda: peer)
        self.validator.validate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
