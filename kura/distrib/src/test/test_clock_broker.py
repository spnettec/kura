#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Clock protocol/fault contracts. The injected clock never sets OS time."""
import errno
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import uuid
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_clock_broker as broker
import kura_clock_client as client
import kura_clock_journal as journal


class Policy:
    cohort = 'a' * 64

    def check(self):
        return None

    def peer(self, value, stopping=False):
        journal.require(value == (123, 996, 989), 'UNAUTHORIZED')


class ClockBrokerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.private = self.root / 'actor'; self.private.mkdir(mode=0o700)
        self.data = self.root / 'data'; self.data.mkdir(mode=0o700)
        self.policy = Policy()
        self.journal = journal.Journal(self.private, boot_id=lambda: "8119db2b-caa2-4d24-be38-471711ad9faa")
        self.writes = []
        self.rtc_writes = []
        self.manager = broker.Manager(self.policy, self.journal, self.writes.append,
                                      lambda device, binding: self.rtc_writes.append(device),
                                      bind_rtc=journal.digest)
        self.peer = (123, 996, 989)
        self.calls = []
        clock = mock.patch.object(journal.time, 'time_ns', return_value=1794949974000000000)
        clock.start(); self.addCleanup(clock.stop)

    def exchange(self, value):
        self.calls.append(value.copy())
        return self.manager.handle(value, self.peer)

    def context(self):
        return self.exchange(dict(schema=1, action='context'))

    def command(self):
        context = self.context()
        return dict(schema=1, namespace=context['namespace'], requestId=str(uuid.uuid4()),
                    action='adjust-realtime', correctionMillis=500, cohortSha256=self.policy.cohort)

    def rtc_command(self, device='/dev/rtc0'):
        value = self.command()
        del value['correctionMillis']
        return dict(value, action='sync-rtc', rtcDevice=device)

    def prepare(self, value):
        return self.exchange(dict(value, action='prepare-adjust'))

    def commit(self, value):
        return self.exchange(dict(value, action='commit-adjust'))

    def status(self, value):
        return self.exchange(dict(schema=1, action='status', namespace=value['namespace'],
                                  requestId=value['requestId'], requestSha256=journal.digest(value)))

    def sender(self, exchange=None):
        return client.Client(self.data, exchange=exchange or self.exchange, policy=self.policy)

    def test_chrony_status_uses_main_peer_without_allocating_a_clock_identity(self):
        status = dict(schema=1, unit='chrony.service', active=False)
        request = dict(schema=1, action='chrony-status')
        with mock.patch.object(broker, 'chrony_status', return_value=status) as inspect:
            with self.assertRaisesRegex(journal.Refused, 'UNAUTHORIZED'):
                self.manager.handle(request, None)
            with self.assertRaises(journal.Refused):
                self.exchange(dict(request, unit='chrony.service'))
            self.assertEqual(status, self.exchange(request))
        inspect.assert_called_once_with()
        self.assertEqual([], list(self.private.iterdir()))
        self.assertEqual([], list(self.data.iterdir()))

    def test_chrony_step_rejects_unpaired_peer_or_any_request_parameters(self):
        request = dict(schema=1, action='chrony-last-step')
        response = dict(schema=1, realtimeMicros=10, monotonicMicros=20)
        with mock.patch.object(broker, 'chrony_last_step', return_value=response) as read:
            with self.assertRaisesRegex(journal.Refused, 'UNAUTHORIZED'):
                self.manager.handle(request, None)
            with self.assertRaises(journal.Refused):
                self.exchange(dict(request, requestId=str(uuid.uuid4())))
            self.assertEqual(response, self.exchange(request))
        read.assert_called_once_with()
        self.assertEqual([], list(self.private.iterdir()))

    def test_chrony_job_timeout_blocks_a_second_dispatch(self):
        request = dict(schema=1, namespace=self.context()['namespace'], requestId=str(uuid.uuid4()),
                       action='start-chrony', chronyStartUnit='chrony.service', cohortSha256=self.policy.cohort)
        with mock.patch.object(broker, 'chrony_binding', return_value='d' * 64):
            self.assertEqual('PREPARED', self.exchange(dict(request, action='prepare-chrony-start'))['state'])
        with mock.patch.object(broker, 'change_chrony', side_effect=journal.Refused('UNCERTAIN_CHRONY_RESULT')) as run:
            with self.assertRaisesRegex(journal.Refused, 'UNCERTAIN_CHRONY_RESULT'):
                self.exchange(dict(request, action='commit-chrony-start'))
            self.assertEqual('UNKNOWN', self.status(request)['state'])
            self.assertEqual('UNKNOWN', self.exchange(dict(request, action='commit-chrony-start'))['state'])
            run.assert_called_once_with('start-chrony', 'chrony.service', 'd' * 64)
        self.assertFalse(self.context()['acceptingWrites'])

    def test_missing_bus_identity_is_a_terminal_failure_without_actuation(self):
        with mock.patch.object(client, 'caller_uid', return_value=os.geteuid()), \
                mock.patch.object(broker, 'chrony_target', return_value=('d' * 64, 'inactive')), \
                mock.patch.object(broker.subprocess, 'check_output', return_value=b'{"type":"a{sv}","data":[{}]}'), \
                mock.patch.object(broker, 'change_chrony') as change:
            result = self.sender().submit('start-chrony', 'chrony.service')
        self.assertEqual(('FAILED', 'OS_ERROR'), (result['state'], result['reason']))
        self.assertFalse((self.data / 'clock-broker/pending.json').exists())
        path = self.data / 'clock-broker/completed' / (result['requestId'] + '.json')
        self.assertEqual(errno.EOPNOTSUPP, json.loads(path.read_bytes())['result']['errno'])
        self.assertTrue(self.context()['acceptingWrites'])
        change.assert_not_called()

    def test_teardown_admits_only_explicit_stop_stages(self):
        def deactivating(peer, stopping=False):
            journal.require(peer == self.peer and stopping, 'UNAUTHORIZED')
        with mock.patch.object(self.policy, 'peer', side_effect=deactivating), \
                mock.patch.object(broker, 'chrony_binding', return_value='d' * 64), \
                mock.patch.object(broker, 'change_chrony') as change:
            context = self.exchange(dict(schema=1, action='chrony-stop-context'))
            for action in ('context', 'chrony-status', 'prepare-chrony-start', 'commit-adjust', 'status'):
                with self.subTest(action=action), self.assertRaisesRegex(journal.Refused, 'UNAUTHORIZED'):
                    self.exchange(dict(schema=1, action=action))
            value = dict(schema=1, namespace=context['namespace'], requestId=str(uuid.uuid4()),
                         action='prepare-chrony-stop', chronyStopUnit='chrony.service',
                         cohortSha256=self.policy.cohort)
            self.assertEqual('PREPARED', self.exchange(value)['state'])
            self.assertEqual('CHRONY_STOPPED', self.exchange(dict(value, action='commit-chrony-stop'))['reason'])
            change.assert_called_once_with('stop-chrony', 'chrony.service', 'd' * 64)

    def test_prepare_does_not_write_and_first_commit_is_durable(self):
        value = self.command()
        self.assertEqual('PREPARED', self.prepare(value)['state']); self.assertEqual([], self.writes)
        self.assertEqual('PREPARED', self.status(value)['state'])
        result = self.commit(value)
        self.assertEqual('APPLIED', result['state'])
        self.assertEqual([1794949974000000000 + value['correctionMillis'] * 1000000], self.writes)
        self.assertEqual(result, self.status(value))
        self.assertTrue(self.context()['acceptingWrites'])

    def test_repeated_prepare_and_commit_only_return_original_receipt(self):
        value = self.command(); self.prepare(value); result = self.commit(value)
        before = {p.relative_to(self.private): p.read_bytes() for p in self.private.rglob('*.json')}
        for _ in range(3):
            self.assertEqual(result, self.prepare(value)); self.assertEqual(result, self.commit(value))
        self.assertEqual(1, len(self.writes))
        self.assertEqual(before, {p.relative_to(self.private): p.read_bytes() for p in self.private.rglob('*.json')})

    def test_commit_without_prepare_has_no_syscall(self):
        value = self.command()
        with self.assertRaisesRegex(journal.Refused, 'NOT_PREPARED'):
            self.commit(value)
        self.assertEqual([], self.writes); self.assertEqual([], list((self.private / 'operations').iterdir()))

    def test_conflicting_original_id_never_changes_its_input(self):
        value = self.command(); self.prepare(value)
        with self.assertRaisesRegex(journal.Refused, 'CONFLICT'):
            self.commit(dict(value, correctionMillis=value['correctionMillis'] + 1))
        self.assertEqual('PREPARED', self.status(value)['state']); self.assertEqual([], self.writes)

    def test_prepared_or_unknown_operation_blocks_new_ids(self):
        value = self.command(); self.prepare(value)
        other = dict(value, requestId=str(uuid.uuid4()))
        with self.assertRaisesRegex(journal.Refused, 'ADMISSION_CLOSED'):
            self.prepare(other)
        self.assertFalse(self.context()['acceptingWrites']); self.assertEqual([], self.writes)

    def test_foreign_namespace_is_refused_before_id_lookup(self):
        value = self.command(); self.prepare(value)
        with mock.patch.object(self.journal, 'status', side_effect=AssertionError('Old ID was looked up')):
            with self.assertRaisesRegex(journal.Refused, 'FOREIGN_NAMESPACE'):
                self.status(dict(value, namespace=str(uuid.uuid4())))
        self.assertEqual([], self.writes)

    def test_wrong_peer_and_source_never_admit_an_intent(self):
        value = self.command()
        with self.assertRaisesRegex(journal.Refused, 'UNAUTHORIZED'):
            self.manager.handle(dict(value, action='prepare-adjust'), (123, 0, 0))
        with self.assertRaisesRegex(journal.Refused, 'UNPAIRED_CODE'):
            self.prepare(dict(value, cohortSha256='b' * 64))
        self.assertEqual([], list((self.private / 'operations').iterdir()))

    def test_source_is_rechecked_under_admission(self):
        value = self.command(); calls = []
        def changed():
            calls.append(1)
            if len(calls) == 2:
                self.policy.cohort = 'b' * 64
        self.policy.check = changed
        with self.assertRaisesRegex(journal.Refused, 'UNPAIRED_CODE'):
            self.prepare(value)
        self.assertEqual([], list((self.private / 'operations').iterdir()))

    def test_invalid_fields_numbers_and_commands_are_rejected(self):
        original = self.command()
        for value in [dict(original, path='/etc/passwd'), dict(original, argv=['date']), dict(original, correctionMillis=True),
                      dict(original, correctionMillis=1.5), dict(original, correctionMillis=-9223372036855), dict(original, correctionMillis=9223372036855),
                      dict(original, schema=True), dict(original, requestId='../outside')]:
            with self.subTest(value=value), self.assertRaises(journal.Refused):
                self.prepare(value)
        self.assertEqual([], list((self.private / 'operations').iterdir())); self.assertEqual([], self.writes)

    def test_duplicate_json_and_nonfinite_values_are_rejected(self):
        for raw in [b'{"schema":1,"schema":1}', b'{"schema":NaN}', b'{"schema":Infinity}', b'[]', b'{}x', b'\xff']:
            with self.subTest(raw=raw), self.assertRaises(journal.Refused):
                journal.decode(raw)

    def test_crash_after_commit_intent_preserves_unknown_and_never_replays(self):
        value = self.command(); self.prepare(value)
        def crashed(nanos):
            self.writes.append(nanos)
            raise RuntimeError('Injected interruption after syscall admission')
        self.manager.adjust_realtime = crashed
        with self.assertRaises(RuntimeError):
            self.commit(value)
        self.assertEqual('UNKNOWN', self.status(value)['state'])
        self.manager = broker.Manager(self.policy, journal.Journal(self.private, boot_id=lambda: "8119db2b-caa2-4d24-be38-471711ad9faa"), self.writes.append)
        for _ in range(2):
            self.assertEqual('UNKNOWN', self.commit(value)['state'])
        self.assertEqual(1, len(self.writes))
        with self.assertRaisesRegex(journal.Refused, 'ADMISSION_CLOSED'):
            self.prepare(dict(value, requestId=str(uuid.uuid4())))

    def test_receipt_write_fault_keeps_original_intent_and_syscall_count(self):
        value = self.command(); self.prepare(value)
        real_create = journal.create
        def fail_receipt(path, data, mode=0o600):
            if path.name == 'result.json':
                raise OSError(errno.ENOSPC, 'Injected write fault; no real disk-full test')
            return real_create(path, data, mode)
        with mock.patch.object(journal, 'create', side_effect=fail_receipt), self.assertRaises(OSError):
            self.commit(value)
        self.assertEqual('UNKNOWN', self.status(value)['state'])
        self.assertEqual('UNKNOWN', self.commit(value)['state']); self.assertEqual(1, len(self.writes))

    def test_definite_kernel_error_is_failed_and_not_retried(self):
        value = self.command(); self.prepare(value)
        def denied(nanos):
            self.writes.append(nanos); raise PermissionError(errno.EPERM, 'Injected syscall denial')
        self.manager.adjust_realtime = denied
        result = self.commit(value)
        self.assertEqual(('FAILED', errno.EPERM), (result['state'], result['errno']))
        self.assertEqual(result, self.commit(value)); self.assertEqual(1, len(self.writes))

    def assert_damage_preserved(self, name):
        value = self.command(); self.prepare(value)
        if name != 'intent.json':
            self.commit(value)
        path = self.private / 'operations' / value['requestId'] / name
        path.write_bytes(b'{')
        before = len(self.writes)
        self.assertEqual('UNKNOWN', self.status(value)['state'])
        self.assertEqual('UNKNOWN', self.commit(value)['state']); self.assertEqual(before, len(self.writes))

    def test_damaged_intent_never_gains_a_clock_write(self):
        self.assert_damage_preserved('intent.json')

    def test_damaged_commit_never_gains_a_second_clock_write(self):
        self.assert_damage_preserved('commit-intent.json')

    def test_damaged_result_never_gains_a_second_clock_write(self):
        self.assert_damage_preserved('result.json')

    def test_existing_empty_operation_directory_is_unknown(self):
        value = self.command()
        (self.private / 'operations' / value['requestId']).mkdir(mode=0o700)
        self.assertEqual('UNKNOWN', self.prepare(value)['state'])
        self.assertEqual('UNKNOWN', self.commit(value)['state']); self.assertEqual([], self.writes)

    def test_maintenance_blocks_new_admission(self):
        value = self.command()
        journal.create(self.private / 'maintenance.json', dict(schema=1), 0o644)
        with self.assertRaisesRegex(journal.Refused, 'ADMISSION_CLOSED'):
            self.prepare(value)
        self.assertEqual([], self.writes)

    def test_expired_sample_fails_without_clock_syscall(self):
        value = self.command(); self.prepare(value)
        prepared = json.loads((self.private / 'operations' / value['requestId'] / 'prepared-context.json').read_text())
        with mock.patch.object(journal.time, 'monotonic_ns', return_value=prepared['preparedMonotonicNs'] + journal.MAX_SAMPLE_AGE_NS + 1):
            result = self.commit(value)
        self.assertEqual(('FAILED', 'STALE_SAMPLE'), (result['state'], result['reason']))
        self.assertEqual([], self.writes); self.assertEqual(result, self.commit(value))

    def test_cross_boot_sample_fails_without_clock_syscall(self):
        value = self.command(); self.prepare(value)
        self.journal.boot_id = lambda: '6d0bbf37-3c96-481e-b690-c18b8856c199'
        result = self.commit(value)
        self.assertEqual(('FAILED', 'STALE_SAMPLE'), (result['state'], result['reason'])); self.assertEqual([], self.writes)

    def test_correction_range_is_checked_at_actuation(self):
        for correction in (-9223372036854, 9223372036854):
            value = dict(self.command(), correctionMillis=correction)
            self.prepare(value); result = self.commit(value)
            self.assertEqual(('FAILED', 'CLOCK_RANGE'), (result['state'], result['reason']))
        self.assertEqual([], self.writes)

    def test_latency_is_compensated_using_realtime_at_actuation(self):
        value = self.command(); self.prepare(value)
        with mock.patch.object(journal.time, 'time_ns', return_value=1794949979000000000):
            result = self.commit(value)
        self.assertEqual('APPLIED', result['state'])
        self.assertEqual([1794949979500000000], self.writes)

    def test_incomplete_prepare_stays_unknown_without_any_clock_write(self):
        value = self.command(); self.prepare(value)
        path = self.private / 'operations' / value['requestId'] / 'prepared-context.json'
        path.write_bytes(b'{')
        self.assertEqual('UNKNOWN', self.status(value)['state'])
        self.assertEqual('UNKNOWN', self.commit(value)['state']); self.assertEqual([], self.writes)

    def test_sender_success_persists_original_receipt_and_commit_marker(self):
        result = self.sender().update(500)
        self.assertEqual(('APPLIED', True), (result['state'], result['currentSample']))
        root = self.data / 'clock-broker'; self.assertFalse((root / 'pending.json').exists())
        self.assertTrue((root / 'issued' / (result['requestId'] + '.json')).is_file())
        self.assertTrue((root / 'completed' / (result['requestId'] + '.json')).is_file())
        self.assertEqual(['context', 'prepare-adjust', 'commit-adjust'], [v['action'] for v in self.calls])

    def test_prepare_reply_loss_resumes_only_original_first_commit(self):
        def lost(value):
            result = self.exchange(value)
            if value['action'] == 'prepare-adjust':
                raise TimeoutError('Injected lost prepare reply')
            return result
        with self.assertRaises(TimeoutError):
            self.sender(lost).update(500)
        pending = journal.decode(journal.read(self.data / 'clock-broker/pending.json', os.geteuid()))
        result = self.sender().update(9999)
        self.assertEqual(('APPLIED', False, pending['requestId'], pending['correctionMillis']),
                         (result['state'], result['currentSample'], result['requestId'], result['correctionMillis']))
        self.assertEqual([1794949974500000000], self.writes)
        self.assertEqual(1, sum(v['action'] == 'prepare-adjust' for v in self.calls))
        self.assertEqual(1, sum(v['action'] == 'commit-adjust' for v in self.calls))

    def test_lost_commit_reply_only_queries_original_result(self):
        def lost(value):
            result = self.exchange(value)
            if value['action'] == 'commit-adjust':
                raise TimeoutError('Injected lost commit reply')
            return result
        with self.assertRaises(TimeoutError):
            self.sender(lost).update(500)
        result = self.sender().update(9999)
        self.assertEqual(('APPLIED', False), (result['state'], result['currentSample']))
        self.assertEqual(1, len(self.writes))
        self.assertEqual(1, sum(v['action'] == 'commit-adjust' for v in self.calls))

    def test_lost_commit_before_dispatch_never_reissues_even_when_prepared(self):
        def lost(value):
            if value['action'] == 'commit-adjust':
                self.calls.append(value.copy()); raise TimeoutError('Injected commit transport loss before actor')
            return self.exchange(value)
        with self.assertRaises(TimeoutError):
            self.sender(lost).update(500)
        before = (self.data / 'clock-broker/pending.json').read_bytes()
        for _ in range(2):
            self.assertEqual('UNKNOWN', self.sender().update(9999)['state'])
        self.assertEqual(before, (self.data / 'clock-broker/pending.json').read_bytes())
        self.assertEqual([], self.writes)
        self.assertEqual(1, sum(v['action'] == 'commit-adjust' for v in self.calls))

    def test_lost_prepare_before_dispatch_remains_unseen_without_resend(self):
        def lost(value):
            if value['action'] == 'prepare-adjust':
                self.calls.append(value.copy()); raise TimeoutError('Injected prepare transport loss before actor')
            return self.exchange(value)
        with self.assertRaises(TimeoutError):
            self.sender(lost).update(500)
        self.assertEqual('UNKNOWN', self.sender().update(9999)['state'])
        self.assertEqual(1, sum(v['action'] == 'prepare-adjust' for v in self.calls)); self.assertEqual([], self.writes)

    def test_sender_never_queries_old_id_at_a_foreign_root(self):
        def lost(value):
            result = self.exchange(value)
            if value['action'] == 'prepare-adjust':
                raise TimeoutError('Injected lost prepare reply')
            return result
        with self.assertRaises(TimeoutError):
            self.sender(lost).update(500)
        foreign_calls = []
        def foreign(value):
            foreign_calls.append(value)
            return dict(schema=1, state='READY', namespace=str(uuid.uuid4()), cohortSha256=self.policy.cohort, acceptingWrites=True)
        with self.assertRaisesRegex(journal.Refused, 'FOREIGN_NAMESPACE'):
            self.sender(foreign).update(9999)
        self.assertEqual(['context'], [v['action'] for v in foreign_calls]); self.assertEqual([], self.writes)

    def test_malformed_prepare_reply_does_not_issue_commit(self):
        def malformed(value):
            result = self.exchange(value)
            return dict(result, schema=True) if value['action'] == 'prepare-adjust' else result
        with self.assertRaisesRegex(journal.Refused, 'INVALID_REPLY'):
            self.sender(malformed).update(500)
        self.assertFalse(any(v['action'] == 'commit-adjust' for v in self.calls)); self.assertEqual([], self.writes)

    def test_new_sender_does_not_allocate_id_when_actor_is_unsettled(self):
        value = self.command(); self.prepare(value)
        with self.assertRaisesRegex(journal.Refused, 'ADMISSION_CLOSED'):
            self.sender().update(9999)
        self.assertFalse((self.data / 'clock-broker/pending.json').exists()); self.assertEqual([], self.writes)

    def test_rtc_sender_records_a_distinct_typed_receipt(self):
        result = self.sender().submit('sync-rtc', '/dev/rtc4')
        self.assertEqual(('APPLIED', 'RTC_SET_RETURNED', '/dev/rtc4', True),
                         (result['state'], result['reason'], result['rtcDevice'], result['currentSample']))
        self.assertEqual(['/dev/rtc4'], self.rtc_writes)
        self.assertEqual([], self.writes)
        self.assertEqual(['context', 'prepare-rtc', 'commit-rtc'], [v['action'] for v in self.calls])
        self.assertEqual('RTC_SET_RETURNED', self.exchange(self.calls[-1])['reason'])
        self.assertEqual(['/dev/rtc4'], self.rtc_writes)

    def test_rtc_protocol_rejects_non_rtc_paths_and_extra_fields(self):
        value = dict(self.rtc_command(), action='prepare-rtc')
        for device in ('/dev/null', '/dev/../dev/rtc0', '/dev/rtc01', '/tmp/rtc0', '/dev/rtc0\n', [], True):
            with self.subTest(device=device), self.assertRaisesRegex(journal.Refused, 'INVALID_ARGUMENT'):
                self.exchange(dict(value, rtcDevice=device))
        with self.assertRaisesRegex(journal.Refused, 'INVALID_ARGUMENT'):
            self.exchange(dict(value, rtcDevice='/dev/rtc0', argv=['hwclock']))
        self.assertEqual([], list((self.private / 'operations').iterdir()))
        self.assertEqual([], self.rtc_writes)

    def test_rtc_ambiguous_ioctl_blocks_wall_clock_and_is_never_reissued(self):
        def ambiguous(device, binding):
            self.assertEqual(journal.digest(device), binding)
            self.rtc_writes.append(device)
            raise journal.Refused('UNCERTAIN_RTC_RESULT')

        self.manager.sync_rtc = ambiguous
        with self.assertRaisesRegex(journal.Refused, 'UNCERTAIN_RTC_RESULT'):
            self.sender().submit('sync-rtc', '/dev/rtc0')
        original = (self.data / 'clock-broker/pending.json').read_bytes()
        original_id = journal.decode(original)['requestId']
        for _ in range(2):
            result = self.sender().update(500)
            self.assertEqual(('UNKNOWN', False, original_id, '/dev/rtc0'),
                             (result['state'], result['currentSample'], result['requestId'], result['rtcDevice']))
        self.assertEqual(original, (self.data / 'clock-broker/pending.json').read_bytes())
        self.assertEqual(['context', 'prepare-rtc', 'commit-rtc', 'context', 'status', 'context', 'status'],
                         [v['action'] for v in self.calls])
        self.assertEqual(['/dev/rtc0'], self.rtc_writes)
        self.assertEqual([], self.writes)

    def test_rtc_prepared_device_identity_survives_actor_restart(self):
        value = self.rtc_command()
        original = '5' * 64
        self.manager.bind_rtc = mock.Mock(return_value=original)
        self.assertEqual('PREPARED', self.exchange(dict(value, action='prepare-rtc'))['state'])
        self.manager.bind_rtc.assert_called_once_with(value['rtcDevice'])
        context = self.private / 'operations' / value['requestId'] / 'prepared-context.json'
        self.assertEqual({'sha256': original}, journal.decode(context.read_bytes())['rtcBinding'])
        def dispatch(device, binding):
            self.assertEqual((value['rtcDevice'], original), (device, binding))
            raise OSError(errno.ESTALE, 'prepared device was replaced')
        self.manager = broker.Manager(self.policy, self.journal, self.writes.append, sync_rtc=mock.Mock(side_effect=dispatch))
        self.assertEqual('PREPARED', self.status(value)['state'])
        result = self.exchange(dict(value, action='commit-rtc'))
        self.assertEqual(('FAILED', errno.ESTALE), (result['state'], result['errno']))
        self.assertEqual(result, self.status(value))
        self.manager.sync_rtc.assert_called_once_with(value['rtcDevice'], original)

    def test_rtc_device_absent_at_prepare_does_not_become_a_new_write(self):
        value = self.rtc_command()
        self.manager.bind_rtc = mock.Mock(side_effect=FileNotFoundError(errno.ENOENT, 'absent during prepare'))
        self.assertEqual('PREPARED', self.exchange(dict(value, action='prepare-rtc'))['state'])
        self.manager.bind_rtc.side_effect = None
        self.manager.bind_rtc.return_value = '6' * 64
        result = self.exchange(dict(value, action='commit-rtc'))
        self.assertEqual(('FAILED', errno.ENOENT), (result['state'], result['errno']))
        self.assertEqual(result, self.status(value))
        self.manager.bind_rtc.assert_called_once()
        self.assertEqual([], self.rtc_writes)

    def test_legacy_unbound_rtc_prepare_is_unknown_and_cannot_dispatch(self):
        value = self.rtc_command()
        self.exchange(dict(value, action='prepare-rtc'))
        operation = self.private / 'operations' / value['requestId']
        path = operation / 'prepared-context.json'
        prepared = journal.decode(path.read_bytes())
        del prepared['rtcBinding']
        original = journal.encode(prepared)
        path.write_bytes(original)
        found = self.status(value)
        self.assertEqual(('UNKNOWN', 'UNRESOLVED_PREPARE'), (found['state'], found['reason']))
        self.assertEqual(found, self.exchange(dict(value, action='commit-rtc')))
        self.assertEqual(original, path.read_bytes())
        self.assertFalse((operation / 'commit-intent.json').exists())
        self.assertFalse(self.context()['acceptingWrites'])
        self.assertEqual([], self.rtc_writes)

    def test_legacy_terminal_rtc_result_stays_readable_without_binding(self):
        value = self.rtc_command()
        self.exchange(dict(value, action='prepare-rtc'))
        original = self.exchange(dict(value, action='commit-rtc'))
        operation = self.private / 'operations' / value['requestId']
        path = operation / 'prepared-context.json'
        prepared = journal.decode(path.read_bytes())
        del prepared['rtcBinding']
        path.write_bytes(journal.encode(prepared))
        before = {file: file.read_bytes() for file in operation.iterdir()}
        self.assertEqual(original, self.status(value))
        self.assertTrue(self.context()['acceptingWrites'])
        self.assertEqual(before, {file: file.read_bytes() for file in operation.iterdir()})
        self.assertEqual([value['rtcDevice']], self.rtc_writes)

    def test_rtc_status_never_accepts_wall_clock_success_for_same_id(self):
        result = self.sender().submit('sync-rtc', '/dev/rtc0')
        path = self.private / 'operations' / result['requestId'] / 'result.json'
        path.write_bytes(journal.encode(dict(journal.decode(path.read_bytes()), reason='CLOCK_SET_RETURNED')))
        self.assertEqual('UNKNOWN', self.exchange(self.calls[-1])['state'])
        self.assertEqual(['/dev/rtc0'], self.rtc_writes)

    def test_wall_clock_pending_is_resolved_without_starting_a_new_rtc_write(self):
        def lost(value):
            result = self.exchange(value)
            if value['action'] == 'commit-adjust':
                raise TimeoutError('Lost wall-clock receipt')
            return result

        with self.assertRaises(TimeoutError):
            self.sender(lost).update(500)
        pending = journal.decode((self.data / 'clock-broker/pending.json').read_bytes())
        result = self.sender().submit('sync-rtc', '/dev/rtc')
        self.assertEqual((False, pending['requestId'], 500, 'CLOCK_SET_RETURNED'),
                         (result['currentSample'], result['requestId'], result['correctionMillis'], result['reason']))
        self.assertEqual([], self.rtc_writes)
        self.assertEqual(1, len(self.writes))
        self.assertEqual(['context', 'prepare-adjust', 'commit-adjust', 'context', 'status'],
                         [v['action'] for v in self.calls])


class RtcDeviceTest(unittest.TestCase):
    def setUp(self):
        self.node = SimpleNamespace(st_dev=1, st_ino=2, st_uid=0, st_gid=125, st_mode=stat.S_IFCHR | 0o640,
                                    st_nlink=1, st_size=0, st_mtime_ns=5, st_ctime_ns=6, st_rdev=os.makedev(254, 4))
        self.hardware = dict(major=254, minor=4, inode=924, path='/sys/devices/platform/example/rtc/rtc4')
        self.kernel = self.enterContext(mock.patch.object(broker, 'rtc_hardware', return_value=self.hardware))
        self.catalog = self.enterContext(mock.patch.object(broker, 'rtc_catalog', return_value=dict(
            schema=1, nodes={'rtc4': self.hardware}, aliases={'/dev/rtc': 'rtc4'})))
        self.enterContext(mock.patch.object(broker.pwd, 'getpwnam', return_value=SimpleNamespace(pw_gid=125)))
        self.admitted = self.enterContext(mock.patch.object(Path, 'lstat', return_value=self.node))
        self.opened = self.enterContext(mock.patch.object(broker.os, 'open', return_value=7))
        self.fd = self.enterContext(mock.patch.object(broker.os, 'fstat', return_value=self.node))
        self.closed = self.enterContext(mock.patch.object(broker.os, 'close'))
        self.ioctl = self.enterContext(mock.patch.object(broker.ctypes, 'CDLL')).return_value.ioctl
        self.enterContext(mock.patch.object(broker.sys, 'platform', 'linux'))
        self.enterContext(mock.patch.object(broker.os, 'uname', return_value=SimpleNamespace(machine='aarch64')))
        self.binding = broker.rtc_binding('/dev/rtc')

    def test_rtc_write_uses_utc_and_one_read_only_kernel_descriptor(self):
        def write(fd, request, fields):
            self.assertEqual((7, 0x4024700a), (fd.value, request.value))
            self.assertEqual([6, 5, 4, 3, 1, 126, 2, 33, 0], list(fields._obj))
            return 0

        self.ioctl.side_effect = write
        utc = broker.time.struct_time((2026, 2, 3, 4, 5, 6, 1, 34, 0))
        with mock.patch.object(broker.time, 'gmtime', return_value=utc):
            broker.rtc_set_time('/dev/rtc', self.binding)
        self.opened.assert_called_once_with(broker.RTC_PROJECTION / 'rtc4',
                                            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.ioctl.assert_called_once()
        self.closed.assert_called_once_with(7)

    def test_invalid_device_mapping_and_replaced_device_never_invoke_ioctl(self):
        self.kernel.return_value = dict(self.hardware, inode=925)
        with self.assertRaises(OSError) as failure:
            broker.rtc_set_time('/dev/rtc4', self.binding)
        self.assertEqual(errno.ENODEV, failure.exception.errno)
        self.opened.assert_not_called()
        self.kernel.return_value = self.hardware
        self.fd.return_value = SimpleNamespace(**vars(self.node))
        self.fd.return_value.st_ino = 30
        with self.assertRaises(OSError):
            broker.rtc_set_time('/dev/rtc4', self.binding)
        self.closed.assert_called_once_with(7)
        self.ioctl.assert_not_called()

    def test_kernel_identity_change_after_open_never_invokes_ioctl(self):
        self.kernel.side_effect = [self.hardware, dict(self.hardware, inode=925)]
        with self.assertRaises(OSError) as failure:
            broker.rtc_set_time('/dev/rtc', self.binding)
        self.assertEqual(errno.ENODEV, failure.exception.errno)
        self.closed.assert_called_once_with(7)
        self.ioctl.assert_not_called()

    def test_ioctl_failure_remains_ambiguous_with_no_retry(self):
        self.ioctl.return_value = -1
        self.closed.side_effect = OSError(errno.EINTR, 'Close interrupted')
        with self.assertRaisesRegex(journal.Refused, 'UNCERTAIN_RTC_RESULT'):
            broker.rtc_set_time('/dev/rtc4', self.binding)
        self.ioctl.assert_called_once()
        self.closed.assert_called_once_with(7)

    def test_republished_projection_does_not_substitute_device_even_with_same_number(self):
        self.admitted.return_value = SimpleNamespace(**dict(vars(self.node), st_ino=self.node.st_ino + 1))
        with self.assertRaises(OSError) as failure:
            broker.rtc_set_time('/dev/rtc', self.binding)
        self.assertEqual(errno.ESTALE, failure.exception.errno)
        self.opened.assert_not_called()
        self.ioctl.assert_not_called()

    def test_retargeted_legacy_alias_does_not_open_the_replacement(self):
        alternate = dict(self.hardware, inode=925, minor=6, path='/sys/devices/platform/example/rtc/rtc6')
        self.catalog.return_value = dict(schema=1, nodes={'rtc6': alternate}, aliases={'/dev/rtc': 'rtc6'})
        self.kernel.return_value = alternate
        self.admitted.return_value = SimpleNamespace(**dict(vars(self.node), st_rdev=os.makedev(254, 6)))
        with self.assertRaises(OSError) as failure:
            broker.rtc_set_time('/dev/rtc', self.binding)
        self.assertEqual(errno.ESTALE, failure.exception.errno)
        self.opened.assert_not_called()
        self.ioctl.assert_not_called()


class ChronyStatusTest(unittest.TestCase):
    def test_status_uses_only_fixed_units_and_preserves_canonical_alias(self):
        with mock.patch.object(broker, 'systemd_properties', side_effect=[
                dict(Id='chrony.service', LoadState='not-found', ActiveState='inactive'),
                dict(Id='chronyd.service', LoadState='loaded', ActiveState='reloading')]) as read_unit:
            self.assertEqual(dict(schema=1, unit='chronyd.service', active=True), broker.chrony_status())
        self.assertEqual(list(broker.CHRONY_UNITS), [call.args[1] for call in read_unit.call_args_list])
        with mock.patch.object(broker, 'systemd_properties', return_value=dict(
                Id='chronyd.service', LoadState='loaded', ActiveState='inactive')) as read_unit:
            self.assertEqual(dict(schema=1, unit='chronyd.service', active=False), broker.chrony_status())
        read_unit.assert_called_once_with(('Id', 'LoadState', 'ActiveState'), 'chrony.service')

    def test_no_provider_is_reported_only_when_both_units_are_missing(self):
        def missing(properties, unit):
            return dict(Id=unit, LoadState='not-found', ActiveState='inactive')
        with mock.patch.object(broker, 'systemd_properties', side_effect=missing):
            self.assertEqual(dict(schema=1, unit='', active=False), broker.chrony_status())

    def test_masked_invalid_or_unexpected_unit_is_not_a_missing_provider(self):
        for props in [dict(Id='chrony.service', LoadState='masked', ActiveState='inactive'),
                      dict(Id='other.service', LoadState='loaded', ActiveState='active'),
                      dict(Id='chrony.service', LoadState='loaded', ActiveState='bogus')]:
            with mock.patch.object(broker, 'systemd_properties', return_value=props) as read_unit:
                with self.assertRaisesRegex(journal.Refused, 'INVALID_CHRONY_STATUS'):
                    broker.chrony_status()
            read_unit.assert_called_once()


class ChronyControlTest(unittest.TestCase):
    def test_stable_source_and_confirmed_state_are_required(self):
        observed = ('d' * 64, 'inactive')
        with mock.patch.object(broker, 'chrony_target', side_effect=[('d' * 64, 'active'), observed]), \
                mock.patch.object(broker, 'require_chrony_bus_identity'), \
                mock.patch.object(broker.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            broker.change_chrony('stop-chrony', 'chrony.service', observed[0])
        self.assertEqual(['/usr/bin/systemctl', '--system', '--no-ask-password', '--no-pager',
                          '--job-mode=fail', 'stop', 'chrony.service'], run.call_args.args[0])
        run.assert_called_once()

    def test_mismatched_prepared_source_never_dispatches(self):
        with mock.patch.object(broker, 'chrony_binding', return_value='f' * 64), \
                mock.patch.object(broker.subprocess, 'run') as run:
            with self.assertRaises(OSError) as error:
                broker.change_chrony('start-chrony', 'chronyd.service', 'e' * 64)
        self.assertEqual(errno.ESTALE, error.exception.errno)
        run.assert_not_called()

    def test_lost_job_or_unconfirmed_state_remains_unknown(self):
        for result in (-1, 0):
            with mock.patch.object(broker, 'chrony_target', return_value=('a' * 64, 'activating')), \
                    mock.patch.object(broker, 'require_chrony_bus_identity'), \
                    mock.patch.object(broker.subprocess, 'run', return_value=SimpleNamespace(returncode=result)) as run:
                with self.assertRaisesRegex(journal.Refused, 'UNCERTAIN_CHRONY_RESULT'):
                    broker.change_chrony('start-chrony', 'chrony.service', 'a' * 64)
                run.assert_called_once()

    def test_only_canonical_vendor_unit_is_paired(self):
        good = dict(Id='chrony.service', LoadState='loaded', FragmentPath='/usr/lib/systemd/system/chrony.service',
                    SourcePath='', DropInPaths='', NeedDaemonReload='no', Transient='no', ActiveState='inactive')
        def read(path):
            return broker.CHRONY_RULE if path == broker.CHRONY_POLICY else b'vendor unit'
        with mock.patch.object(broker, 'public_file', side_effect=read), \
                mock.patch.object(broker, 'require_chrony_bus_identity'):
            with mock.patch.object(broker, 'systemd_properties', return_value=dict(good)):
                self.assertEqual(64, len(broker.chrony_binding('chrony.service')))
            for change in [dict(NeedDaemonReload='yes'), dict(DropInPaths='/etc/test.conf'),
                           dict(Id='chronyd.service'), dict(FragmentPath='/etc/systemd/system/chrony.service')]:
                with mock.patch.object(broker, 'systemd_properties', return_value=dict(good, **change)):
                    with self.assertRaises(OSError):
                        broker.chrony_binding('chrony.service')

    def test_only_a_bus_process_descriptor_for_system_manager_is_accepted(self):
        credentials = dict(ProcessID=dict(type='u', data=1), UnixUserID=dict(type='u', data=0),
                           ProcessFD=dict(type='h', data=3))
        cases = [credentials, dict(credentials, ProcessID=dict(type='u', data=2)),
                 dict(credentials, UnixUserID=dict(type='u', data=100)), dict(credentials, ProcessFD=dict(type='u', data=3)),
                 {name: value for name, value in credentials.items() if name != 'ProcessFD'}]
        for reply in cases:
            with self.subTest(reply=reply), mock.patch.object(broker.subprocess, 'check_output',
                    return_value=json.dumps(dict(type='a{sv}', data=[reply])).encode()) as probe:
                if reply is credentials:
                    broker.require_chrony_bus_identity()
                else:
                    with self.assertRaises(OSError) as error:
                        broker.require_chrony_bus_identity()
                    self.assertEqual(errno.EOPNOTSUPP, error.exception.errno)
                self.assertEqual(['GetConnectionCredentials', 's', 'org.freedesktop.systemd1'], probe.call_args.args[0][-3:])


class ChronyJournalTest(unittest.TestCase):
    def test_only_authenticated_fields_are_queried_and_only_timestamps_are_returned(self):
        boot = uuid.uuid4()
        entry = {'__REALTIME_TIMESTAMP': '1794949974000000', '__MONOTONIC_TIMESTAMP': '1000000',
                 '_BOOT_ID': boot.hex, '_SYSTEMD_UNIT': 'chronyd.service', '_EXE': '/usr/sbin/chronyd'}
        reply = SimpleNamespace(returncode=0, stdout=json.dumps(entry).encode(), stderr=b'')
        with mock.patch.object(broker.subprocess, 'run', return_value=reply) as run, \
                mock.patch.object(broker.Path, 'read_text', return_value=str(boot) + '\n'):
            self.assertEqual(dict(schema=1, realtimeMicros=1794949974000000, monotonicMicros=1000000),
                             broker.chrony_last_step())
        arguments = run.call_args.args[0]
        self.assertEqual('/usr/bin/journalctl', arguments[0])
        self.assertIn('--boot', arguments)
        self.assertIn('--lines=1', arguments)
        self.assertIn('--output-fields=_EXE,_SYSTEMD_UNIT', arguments)
        self.assertEqual(['_SYSTEMD_UNIT=chrony.service', '_SYSTEMD_UNIT=chronyd.service',
                          '_EXE=/usr/sbin/chronyd', '_EXE=/usr/bin/chronyd'], arguments[-4:])
        self.assertEqual(3, run.call_args.kwargs['timeout'])

    def test_foreign_source_noncanonical_timestamp_and_failed_query_are_not_steps(self):
        boot = uuid.uuid4()
        entry = {'__REALTIME_TIMESTAMP': '1', '__MONOTONIC_TIMESTAMP': '1', '_BOOT_ID': boot.hex,
                 '_SYSTEMD_UNIT': 'chrony.service', '_EXE': '/usr/sbin/chronyd'}
        for fields in (dict(_EXE='/usr/bin/logger'), dict(_SYSTEMD_UNIT='other.service'), dict(_BOOT_ID=uuid.uuid4().hex),
                       dict(__MONOTONIC_TIMESTAMP=['1', '2']), dict(__REALTIME_TIMESTAMP='9223372036854775808'),
                       dict(__REALTIME_TIMESTAMP='0')):
            data = json.dumps(dict(entry, **fields)).encode()
            with self.subTest(fields=fields), mock.patch.object(broker.Path, 'read_text', return_value=str(boot)), \
                    mock.patch.object(broker.subprocess, 'run', return_value=SimpleNamespace(
                        returncode=0, stdout=data, stderr=b'')):
                with self.assertRaisesRegex(journal.Refused, 'UNAVAILABLE_CHRONY_JOURNAL'):
                    broker.chrony_last_step()
        with mock.patch.object(broker.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stdout=b'', stderr=b'journal unavailable')):
            with self.assertRaisesRegex(journal.Refused, 'UNAVAILABLE_CHRONY_JOURNAL'):
                broker.chrony_last_step()
        with mock.patch.object(broker.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stdout=b'', stderr=b'')):
            self.assertEqual(dict(schema=1, realtimeMicros=0, monotonicMicros=0), broker.chrony_last_step())


if __name__ == '__main__':
    unittest.main()
