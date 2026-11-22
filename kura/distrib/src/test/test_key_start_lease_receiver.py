#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Production receiver/admissions and retained files; Root/Main replies are explicit models."""
import copy
from pathlib import Path
import tempfile
import unittest
import uuid

from test_key_receiver_admission_recovery import AdmissionRoot, recovery, protocol


class LeaseRoot(AdmissionRoot):
    def __init__(self):
        super().__init__()
        self.lose = False; self.leases = {}; self.lease_window = False
        self.lose_lease_reply = False; self.drop_lease_native = False; self.lease_writes = 0

    def __call__(self, request):
        request = recovery.SenderAdmission.wrap(request)
        action = request['action']
        if action == 'sender-reserve' and request['request'].get('command') == 'start-renew':
            native = request['request']
            reply = dict(schema=1, admissionId=request['admissionId'], source='recovery', namespaceSha256=self.namespace,
                nativeOperationId=native['operationId'], nativeAction='generation-start-lease', state='RESERVED', newlyReserved=True)
            self.records[request['admissionId']] = reply
            if self.lose: raise OSError('modeled lost reservation reply')
            return copy.deepcopy(reply)
        if action == 'sender-command':
            admission = self.records[request['admissionId']]
            protocol.require(admission['state'] == 'RESERVED', 'UNRESOLVED_OPERATION')
            admission['state'] = 'INTAKE'; native = request['request']; command = native.get('command')
            if command == 'start-renew':
                self.lease_writes += 1
                if self.drop_lease_native: raise OSError('modeled intake without original')
                info = self.handoff.info; identity = native['operationId']
                self.leases[identity] = dict(schema=1, operationId=identity, action='generation-start-lease', state='SUCCEEDED',
                    purpose='yofc.kura.generation-start-lease.v1', scope='ORIGINAL_FIRST_START_ONLY',
                    handoffId=info['handoffId'], publicationId=info['publicationId'], startOperationId=info['startOperationId'],
                    publicationSha256=native['expectedPublicationSha256'], grantSha256='d'*64, namespaceSha256=self.namespace,
                    bootId=str(uuid.uuid4()), issuedBoottimeNs=10, expiresBoottimeNs=900000000010,
                    issuedAt=4000, expiresAt=4900, credentialsChanged=False, startRequested=False, receiptTag='e'*64)
                self.lease_window = True; admission['state'] = 'TERMINAL'
                if self.lose_lease_reply: raise OSError('modeled lost successful lease reply')
                return copy.deepcopy(self.leases[identity])
            result = self.handoff(native); admission['state'] = 'TERMINAL'; return result
        if action == 'generation-handoff-command' and request.get('command') in ('start-lease-read','start-lease-status'):
            protocol.require(request['token'] == self.handoff.token, 'FORBIDDEN')
            if request['command'] == 'start-lease-read':
                return copy.deepcopy(self.leases.get(request['operationId'], dict(schema=1, operationId=request['operationId'],
                    state='NOT_RECORDED', scope='ORIGINAL_OPERATION_ONLY')))
            info = self.handoff.info; published = self.handoff.publication
            valid = published is not None and published['state'] == 'SUCCEEDED' and self.handoff.start is None
            return dict(schema=1, state='START_LEASE_STATUS', scope='ORIGINAL_FIRST_START_ONLY',
                handoffId=info['handoffId'], publicationId=info['publicationId'], startOperationId=info['startOperationId'],
                publicationSha256=published['publicationSha256'] if valid else None,
                renewalOperationId=next(reversed(self.leases)) if self.leases and self.lease_window and valid else None,
                windowOpen=bool(valid and self.lease_window), renewalAllowed=bool(valid and not self.lease_window and not info['mutationWindowOpen']
                    and all(row['state'] in ('TERMINAL','NOT_ADMITTED') for row in self.records.values())))
        return super().__call__(request)


class ReceiverStartLeaseTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='kura-receiver-start-lease-'); self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name); self.path.chmod(0o700)
        self.root = LeaseRoot(); self.root.handoff.publication = self.root.handoff.published()
        self.root.handoff.info['mutationWindowOpen'] = False
        self.journal = recovery.Journal(self.path); self.controller = recovery.HandoffController(self.root, self.journal)
        self.token = self.root.handoff.token

    def call(self, command='query', **extra):
        return self.controller.execute(dict(token=self.token, command=command, **extra))

    def renew(self, identity=None):
        return self.call('start-renew', operationId=identity or str(uuid.uuid4()),
            expectedPublicationSha256=self.root.handoff.publication['publicationSha256'])

    def files(self):
        return {str(path.relative_to(self.path)): path.read_bytes() for path in self.path.rglob('*') if path.is_file()}

    def test_explicit_renewal_then_separate_start_uses_the_original_start_id(self):
        self.assertTrue(self.call()['renewalAllowed']); self.assertFalse(self.call()['allowed']['start'])
        identity = str(uuid.uuid4()); result = self.renew(identity)
        self.assertFalse(result['renewalAllowed']); self.assertTrue(result['allowed']['start'])
        self.assertEqual('SUCCEEDED', result['startRenewals'][0]['state'])
        self.assertEqual(0, self.root.handoff.writes['start']); self.assertTrue(self.controller.pending())
        raw = b''.join(self.files().values()); self.assertNotIn(self.token.encode(), raw)
        result = self.call('start'); self.assertEqual('SUCCEEDED', result['start']['state'])
        self.assertEqual(self.root.handoff.info['startOperationId'], result['start']['operationId'])
        self.call('start'); self.assertEqual(1, self.root.handoff.writes['start'])

    def test_reload_and_read_never_extend_the_original_lease_or_redispatch_it(self):
        identity = str(uuid.uuid4()); self.renew(identity); before = self.files()
        self.controller = recovery.HandoffController(self.root, recovery.Journal(self.path))
        self.renew(identity); self.call(); self.assertEqual(before, self.files()); self.assertEqual(1, self.root.lease_writes)
        self.root.lease_window = False; self.assertTrue(self.call()['renewalAllowed'])
        self.renew(); self.assertEqual(2, self.root.lease_writes)
        self.assertEqual(2, len(self.call()['startRenewals']))

    def test_successful_root_reply_loss_is_resolved_only_by_original_reads(self):
        self.root.lose_lease_reply = True; self.renew()
        self.assertTrue(self.call()['allowed']['start']); self.assertEqual(1, self.root.lease_writes)

    def test_intake_without_original_stays_unknown_and_blocks_every_new_lease(self):
        self.root.drop_lease_native = True; identity = str(uuid.uuid4()); self.renew(identity)
        result = self.call(); self.assertEqual('UNKNOWN', result['startRenewals'][0]['state'])
        self.assertFalse(result['startRenewals'][0]['closeAllowed']); self.assertFalse(result['allowed']['start'])
        self.assertFalse(result['renewalAllowed'])
        with self.assertRaises(protocol.Failure): self.renew()
        with self.assertRaises(protocol.Failure): self.call('renewal-close', operationId=identity)
        self.renew(identity); self.assertEqual(1, self.root.lease_writes)

    def test_unconsumed_reservation_must_be_explicitly_closed_before_new_lease(self):
        self.root.lose = True; identity = str(uuid.uuid4())
        with self.assertRaises(OSError): self.renew(identity)
        before = self.files(); result = self.call(); self.assertTrue(result['startRenewals'][0]['closeAllowed'])
        self.assertEqual(before, self.files()); self.assertEqual(0, self.root.closes)
        result = self.call('renewal-close', operationId=identity)
        self.assertEqual('NOT_ADMITTED', result['startRenewals'][0]['state']); self.assertTrue(result['renewalAllowed'])
        self.renew(identity); self.assertEqual(0, self.root.lease_writes)
        self.root.lose = False; self.renew(); self.assertEqual(1, self.root.lease_writes)
        for name, raw in before.items(): self.assertEqual(raw, self.files()[name])

    def test_torn_or_foreign_namespace_receipts_block_new_controls_without_overwrite(self):
        identity = str(uuid.uuid4()); self.renew(identity)
        self.root.leases[identity]['namespaceSha256'] = 'f'*64
        before = self.files()
        with self.assertRaises(protocol.Failure): self.call()
        self.assertEqual(before, self.files())

    def test_original_start_attempt_or_wrong_publication_cannot_be_bypassed(self):
        self.root.lose = True; binding = self.root.handoff.info
        with self.assertRaises(OSError): self.controller.sender.submit('handoff-start', binding['startOperationId'],
            dict(schema=1, action='generation-handoff-command', command='start', token=self.token), lambda: self.fail('lost reservation'))
        self.assertFalse(self.call()['renewalAllowed'])
        with self.assertRaises(protocol.Failure): self.renew()
        self.assertEqual(0, self.root.lease_writes)

    def test_invalid_ids_or_wrong_original_publication_fail_before_metadata_intent(self):
        before = self.files()
        for key in recovery.HandoffController.IDS:
            with self.assertRaises(protocol.Failure): self.renew(self.root.handoff.info[key])
        with self.assertRaises(protocol.Failure): self.call('start-renew', operationId=str(uuid.uuid4()), expectedPublicationSha256='f'*64)
        self.assertEqual(before, self.files()); self.assertEqual(0, self.root.lease_writes)


if __name__ == '__main__': unittest.main()
