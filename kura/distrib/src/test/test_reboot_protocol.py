# SPDX-License-Identifier: EPL-2.0
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

BIN = Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'
sys.path.insert(0, str(BIN))
from kura_clock_journal import Refused, digest, encode  # noqa: E402
from kura_reboot_journal import RebootJournal, admission_lock, reference  # noqa: E402
from kura_reboot_protocol import RebootProtocol, RebootSender  # noqa: E402


NAMESPACE = '01ca8900-1dff-4709-9015-95dec91c056a'
FOREIGN = 'abed35d8-6f20-4ca8-8513-24e4929a0d39'
BOOT = '17c1ff95-30ee-4881-bce2-3b873c3c308e'
NEXT_BOOT = 'd2db8691-e1f8-4222-a6ad-af9de996bf48'
THIRD_BOOT = '9982b509-1046-4600-978b-38545a482d25'
COHORT = 'a' * 64
NEW_COHORT = 'b' * 64
PEER = (17, 123, 456)
FIRST = 'f4975ca4-f51c-4b9e-a80e-429db32044b3'
SECOND = '37ea3c66-466a-4402-9127-45cf76ce220e'


class RebootContractTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(directory) / 'root'
        self.root.mkdir(mode=0o700)
        self.local = Path(directory) / 'main'
        self.local.mkdir(mode=0o700)
        self.boot = BOOT
        self.dispatch = Mock(return_value=('ACCEPTED', 'MANAGER_ACCEPTED'))
        self.journal = self.new_journal()
        self.protocol = self.new_protocol(self.journal)
        self.sent = []
        self.journal.initialize()

    def new_journal(self, namespace=NAMESPACE, cohort=COHORT):
        return RebootJournal(self.root, namespace, cohort, lambda: self.boot)

    def new_protocol(self, journal):
        return RebootProtocol(journal, lambda peer: peer == PEER, self.dispatch)

    def new_sender(self, exchange=None, namespace=NAMESPACE, cohort=COHORT):
        return RebootSender(self.local, namespace, cohort, exchange or self.exchange, lambda: self.boot)

    def message(self, operation=FIRST, **updates):
        value = dict(schema=1, action='reboot', namespace=NAMESPACE, bootId=self.boot,
                     cohortSha256=COHORT, requestId=operation)
        return dict(value, **updates)

    def exchange(self, value):
        self.sent.append(value.copy())
        return self.protocol.handle(value, PEER)

    def observe(self, original, journal=None):
        bound = reference(original)
        return (journal or self.journal).status(bound['namespace'], bound['requestId'], bound['requestSha256'])

    def pending_hash(self):
        return hashlib.sha256((self.local / 'pending.json').read_bytes()).hexdigest()

    def crash_process(self, body, expected_exit):
        setup = """import os
import sys
sys.path.insert(0, sys.argv[1])
from kura_clock_journal import decode
from kura_reboot_journal import RebootJournal
from kura_reboot_protocol import RebootProtocol, RebootSender
intent = decode(sys.stdin.buffer.read())
boot_id = lambda: intent['bootId']
journal = RebootJournal(sys.argv[2], intent['namespace'], intent['cohortSha256'], boot_id)
"""
        result = subprocess.run([sys.executable, '-B', '-c', setup + body, str(BIN), str(self.root),
                                 str(self.local)], input=encode(self.message()), capture_output=True, timeout=10)
        self.assertEqual(expected_exit, result.returncode, result.stderr.decode())

    def test_same_boot_acceptance_excludes_new_id_and_is_not_completion(self):
        original = self.message()
        result = self.exchange(original)
        self.assertEqual(('ACCEPTED', BOOT, BOOT),
                         (result['state'], result['bootId'], result['observedBootId']))
        self.assertEqual(result, self.exchange(original))
        self.assertEqual(result, self.observe(original, self.new_journal()))
        self.assertFalse(self.journal.context()['acceptingWrites'])
        with self.assertRaisesRegex(Refused, '^REBOOT_ALREADY_ACCEPTED$'):
            self.exchange(self.message(SECOND))
        self.dispatch.assert_called_once_with()

    def test_boot_change_is_read_only_and_cannot_replay_old_request(self):
        original = self.message()
        self.exchange(original)
        saved = (self.root / 'operations' / FIRST / 'result.json').read_bytes()
        self.boot = NEXT_BOOT
        journal = self.new_journal()
        status = self.observe(original, journal)
        self.assertEqual(('ACCEPTED', BOOT, NEXT_BOOT),
                         (status['state'], status['bootId'], status['observedBootId']))
        self.assertEqual(saved, (self.root / 'operations' / FIRST / 'result.json').read_bytes())
        self.assertEqual(status, self.new_protocol(journal).handle(original, PEER))
        self.assertTrue(journal.context()['acceptingWrites'])
        self.dispatch.assert_called_once_with()

    def test_dispatch_exception_after_durable_intent_blocks_all_further_dispatch(self):
        original = self.message()
        def lose_reply():
            self.assertTrue((self.root / 'operations' / FIRST / 'intent.json').is_file())
            raise ConnectionError('simulated manager disconnect')
        self.dispatch.side_effect = lose_reply
        with self.assertRaises(ConnectionError):
            self.exchange(original)
        self.boot = NEXT_BOOT
        journal = self.new_journal()
        expected = self.observe(original, journal)
        self.assertEqual(('UNKNOWN', 'NO_DURABLE_RESULT', NEXT_BOOT),
                         (expected['state'], expected['reason'], expected['observedBootId']))
        self.assertEqual(expected, self.new_protocol(journal).handle(original, PEER))
        self.assertFalse(journal.context()['acceptingWrites'])
        with self.assertRaisesRegex(Refused, '^ADMISSION_CLOSED$'):
            self.new_protocol(journal).handle(self.message(SECOND), PEER)
        self.dispatch.assert_called_once_with()

    def test_known_launch_failure_allows_next_new_request(self):
        self.dispatch.side_effect = [('FAILED', 'NOT_STARTED'), ('ACCEPTED', 'MANAGER_ACCEPTED')]
        first = self.exchange(self.message())
        self.assertEqual(('FAILED', 'NOT_STARTED'), (first['state'], first['reason']))
        self.assertTrue(self.journal.context()['acceptingWrites'])
        self.assertEqual(first, self.exchange(self.message()))
        self.assertEqual('ACCEPTED', self.exchange(self.message(SECOND))['state'])
        self.assertEqual(2, self.dispatch.call_count)

    def test_explicit_unknown_is_durable_and_blocks_later_boot(self):
        self.dispatch.return_value = ('UNKNOWN', 'DISPATCH_UNCONFIRMED')
        request = self.message()
        self.assertEqual('DISPATCH_UNCONFIRMED', self.exchange(request)['reason'])
        self.boot = NEXT_BOOT
        self.assertEqual('DISPATCH_UNCONFIRMED', self.observe(request, self.new_journal())['reason'])
        self.assertFalse(self.new_journal().context()['acceptingWrites'])
        self.dispatch.assert_called_once_with()

    def test_new_stale_boot_is_refused_before_persisting_an_intent(self):
        original = self.message()
        self.boot = NEXT_BOOT
        with self.assertRaisesRegex(Refused, '^STALE_BOOT$'):
            self.exchange(original)
        self.assertEqual('UNSEEN', self.observe(original)['state'])
        self.dispatch.assert_not_called()

    def test_inflight_boot_change_does_not_call_dispatch(self):
        second_read = Mock(side_effect=[BOOT, NEXT_BOOT, NEXT_BOOT])
        journal = RebootJournal(self.root, NAMESPACE, COHORT, second_read)
        result = journal.submit(self.message(), self.dispatch)
        self.assertEqual(('FAILED', 'STALE_BOOT', NEXT_BOOT),
                         (result['state'], result['reason'], result['observedBootId']))
        self.dispatch.assert_not_called()

    def test_caller_must_be_authorized_before_dispatch_or_journal_lookup(self):
        messages = (dict(schema=1, action='context'), dict(reference(self.message()), action='status'), self.message())
        for message in messages:
            with self.subTest(action=message['action']):
                with self.assertRaisesRegex(Refused, '^UNAUTHORIZED$'):
                    self.protocol.handle(message, (99, *PEER[1:]))
        self.dispatch.assert_not_called()

    def test_fixed_protocol_rejects_extra_arguments_and_arbitrary_actions(self):
        messages = (self.message(action='shutdown'), self.message(command='reboot -f'),
                    self.message(schema=True), self.message(bootId='../../state'),
                    dict(schema=1, action='context', requestId=FIRST))
        for message in messages:
            with self.subTest(message=message):
                with self.assertRaisesRegex(Refused, '^INVALID_ARGUMENT$'):
                    self.exchange(message)
        self.assertEqual([], list((self.root / 'operations').iterdir()))
        self.dispatch.assert_not_called()

    def test_foreign_namespace_is_refused_before_key_or_hash_lookup(self):
        with self.assertRaisesRegex(Refused, '^FOREIGN_NAMESPACE$'):
            self.journal.status(FOREIGN, 'malformed-not-checked', 'malformed-not-checked')
        with self.assertRaisesRegex(Refused, '^FOREIGN_NAMESPACE$'):
            self.new_journal(FOREIGN).context()
        with self.assertRaisesRegex(Refused, '^FOREIGN_NAMESPACE$'):
            self.exchange(self.message(namespace=FOREIGN))
        self.dispatch.assert_not_called()

    def test_cohort_upgrade_allows_read_of_original_id_only(self):
        original = self.message()
        self.exchange(original)
        journal = self.new_journal(cohort=NEW_COHORT)
        with self.assertRaisesRegex(Refused, '^UNPAIRED_CODE$'):
            journal.submit(original, self.dispatch)
        with self.assertRaisesRegex(Refused, '^CONFLICT$'):
            journal.status(NAMESPACE, FIRST, digest(dict(original, cohortSha256=NEW_COHORT)))
        self.assertEqual('ACCEPTED', self.observe(original, journal)['state'])
        self.dispatch.assert_called_once_with()

    def test_runtime_cannot_reinitialize_missing_operations(self):
        (self.root / 'operations').rmdir()
        with self.assertRaises(FileNotFoundError):
            self.journal.context()
        with self.assertRaisesRegex(Refused, '^STATE_ALREADY_PRESENT$'):
            self.journal.initialize()
        self.assertFalse((self.root / 'operations').exists())
        self.dispatch.assert_not_called()

    def test_marker_and_lock_must_exist_without_aliases(self):
        marker = self.root / 'namespace.json'
        alias = self.root / 'marker-copy'
        marker.rename(alias)
        marker.symlink_to(alias)
        with self.assertRaises(OSError):
            self.exchange(self.message())
        marker.unlink()
        alias.rename(marker)
        lock = self.root / 'admission.lock'
        lock.unlink()
        with self.assertRaises(FileNotFoundError):
            self.journal.context()
        self.assertFalse(lock.exists())
        self.dispatch.assert_not_called()

    def test_incomplete_or_corrupt_inputs_keep_original_ambiguity(self):
        original = self.message()
        operation = self.root / 'operations' / FIRST
        operation.mkdir(mode=0o700)
        self.assertEqual('UNRESOLVED_INTENT', self.observe(original)['reason'])
        self.assertFalse(self.journal.context()['acceptingWrites'])
        self.dispatch.assert_not_called()

    def test_corrupt_receipt_does_not_acquire_a_new_accepted_state(self):
        original = self.message()
        self.exchange(original)
        receipt = self.root / 'operations' / FIRST / 'result.json'
        receipt.write_bytes(b'{"schema":true}')
        self.boot = NEXT_BOOT
        self.assertEqual('UNRESOLVED_RESULT', self.observe(original)['reason'])
        self.assertFalse(self.journal.context()['acceptingWrites'])
        self.dispatch.assert_called_once_with()

    def test_actor_process_death_after_intent_survives_reopen(self):
        self.crash_process("journal.submit(intent, lambda: os._exit(44))\n", 44)
        self.assertEqual('NO_DURABLE_RESULT', self.observe(self.message(), self.new_journal())['reason'])
        self.assertEqual('UNKNOWN', self.exchange(self.message())['state'])
        self.assertFalse(self.journal.context()['acceptingWrites'])
        self.dispatch.assert_not_called()

    def test_sender_process_death_after_accepted_commit_keeps_first_id(self):
        self.crash_process("""actor = RebootProtocol(journal, lambda _: True, lambda: ('ACCEPTED', 'MANAGER_ACCEPTED'))
def exchange(message):
    reply = actor.handle(message, None)
    if message['action'] == 'reboot':
        os._exit(45)
    return reply
RebootSender(sys.argv[3], intent['namespace'], intent['cohortSha256'], exchange, boot_id).submit()
""", 45)
        saved = self.pending_hash()
        self.assertEqual(1, len(list((self.root / 'operations').iterdir())))
        result = self.new_sender().submit()
        self.assertEqual('ACCEPTED', result['state'])
        self.assertFalse(result['currentRequest'])
        self.assertEqual(saved, self.pending_hash())
        self.assertEqual(['context', 'status'], [message['action'] for message in self.sent])
        self.dispatch.assert_not_called()

    def test_locked_admission_serializes_writers_and_maintenance_preserves_status(self):
        original = self.message()
        self.exchange(original)
        self.boot = NEXT_BOOT
        (self.root / 'maintenance.json').touch(mode=0o600)
        self.assertEqual('ACCEPTED', self.observe(original)['state'])
        self.assertFalse(self.journal.context()['acceptingWrites'])
        with admission_lock(self.root / 'admission.lock', self.journal.owner):
            with self.assertRaisesRegex(Refused, '^BUSY$'):
                self.new_journal().submit(self.message(SECOND), self.dispatch)
        with self.assertRaisesRegex(Refused, '^ADMISSION_CLOSED$'):
            self.new_journal().submit(self.message(SECOND), self.dispatch)
        self.dispatch.assert_called_once_with()

    def test_new_sender_recovers_lost_reboot_reply_from_same_root(self):
        def lost_reply(value):
            result = self.exchange(value)
            if value['action'] == 'reboot':
                self.assertTrue((self.local / 'pending.json').exists())
                raise ConnectionError('simulated lost acknowledgement')
            return result
        with self.assertRaises(ConnectionError):
            self.new_sender(lost_reply).submit()
        saved = self.pending_hash()
        first = self.new_sender().submit()
        self.assertFalse(first['currentRequest'])
        self.assertEqual('ACCEPTED', first['state'])
        self.assertEqual(saved, self.pending_hash())
        self.boot = NEXT_BOOT
        final = self.new_sender().submit()
        self.assertEqual((first['requestId'], NEXT_BOOT), (final['requestId'], final['observedBootId']))
        self.assertFalse((self.local / 'pending.json').exists())
        self.assertTrue((self.local / 'completed' / (first['requestId'] + '.json')).is_file())
        self.assertEqual(['context', 'reboot', 'context', 'status', 'context', 'status'],
                         [message['action'] for message in self.sent])
        self.dispatch.assert_called_once_with()

    def test_sender_never_resends_if_transport_lost_before_root_intent(self):
        def lose_before_dispatch(value):
            if value['action'] == 'reboot':
                self.sent.append(value.copy())
                raise ConnectionError('simulated failed transport')
            return self.exchange(value)
        with self.assertRaises(ConnectionError):
            self.new_sender(lose_before_dispatch).submit()
        before = self.pending_hash()
        self.boot = NEXT_BOOT
        result = self.new_sender().submit()
        self.assertEqual(('UNKNOWN', 'NO_LOCAL_INTENT'), (result['state'], result['reason']))
        self.assertEqual(before, self.pending_hash())
        self.assertEqual(['context', 'reboot', 'context', 'status'], [message['action'] for message in self.sent])
        self.dispatch.assert_not_called()

    def test_sender_disclosing_no_old_id_to_foreign_root(self):
        sender = self.new_sender()
        sender.submit()
        before = self.pending_hash()
        other = Mock(return_value=dict(self.journal.context(), namespace=FOREIGN))
        with self.assertRaisesRegex(Refused, '^FOREIGN_NAMESPACE$'):
            self.new_sender(other).submit()
        other.assert_called_once_with(dict(schema=1, action='context'))
        self.assertEqual(before, self.pending_hash())
        self.dispatch.assert_called_once_with()

    def test_failed_receipt_fsync_keeps_original_reboot_pending_on_retry(self):
        original = self.new_sender().submit()
        self.boot = NEXT_BOOT
        target = self.local / 'completed' / (original['requestId'] + '.json')
        pending = self.pending_hash()
        fsync = os.fsync

        def fail_receipt_sync(fd):
            if target.exists() and os.path.samestat(os.fstat(fd), target.stat()):
                raise OSError('receipt fsync interrupted')
            fsync(fd)

        with patch('os.fsync', side_effect=fail_receipt_sync):
            for _ in range(2):
                with self.assertRaisesRegex(OSError, 'receipt fsync interrupted'):
                    self.new_sender().submit()
                self.assertEqual(pending, self.pending_hash())
        receipt = target.read_bytes()
        inode = target.stat().st_ino
        self.assertEqual(original['requestId'], self.new_sender().submit()['requestId'])
        self.assertEqual((receipt, inode), (target.read_bytes(), target.stat().st_ino))
        self.assertFalse((self.local / 'pending.json').exists())
        self.dispatch.assert_called_once_with()

    def test_sender_retains_first_completed_observation_if_unlink_is_interrupted(self):
        sender = self.new_sender()
        original = sender.submit()
        self.boot = NEXT_BOOT
        observed = self.new_sender()
        path = self.local / 'pending.json'
        backup = path.read_bytes()
        observed.submit()
        record = self.local / 'completed' / (original['requestId'] + '.json')
        saved = record.read_bytes()
        path.touch(mode=0o600)
        path.write_bytes(backup)
        self.boot = THIRD_BOOT
        final = self.new_sender().submit()
        self.assertEqual(THIRD_BOOT, final['observedBootId'])
        self.assertFalse(path.exists())
        self.assertEqual(saved, record.read_bytes())
        self.dispatch.assert_called_once_with()

    def test_sender_rejects_unpaired_context_and_tampered_original_reply(self):
        wrong = Mock(return_value=dict(self.journal.context(), cohortSha256=NEW_COHORT))
        with self.assertRaisesRegex(Refused, '^UNPAIRED_CODE$'):
            self.new_sender(wrong).submit()
        self.assertFalse((self.local / 'pending.json').exists())
        def tamper(value):
            result = self.exchange(value)
            return dict(result, requestId=SECOND) if value['action'] == 'reboot' else result
        with self.assertRaisesRegex(Refused, '^INVALID_REPLY$'):
            self.new_sender(tamper).submit()
        self.assertTrue((self.local / 'pending.json').exists())
        self.assertEqual('ACCEPTED', self.new_sender().submit()['state'])
        self.dispatch.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
