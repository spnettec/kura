# SPDX-License-Identifier: EPL-2.0
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_bind_service as bind


class BindOperationTest(unittest.TestCase):
    def test_only_fixed_job_verbs_and_unit(self):
        operation = str(uuid.uuid4())
        with self.assertRaisesRegex(bind.Refused, 'INVALID_BIND_REQUEST'):
            bind.request('named.service', operation)
        with patch.object(bind.subprocess, 'run') as run:
            bind.write_job('restart')
        self.assertEqual(run.call_args.args[0], [
            '/usr/bin/systemctl', '--system', '--no-ask-password', '--no-pager', '--job-mode=fail',
            'restart', 'named.service',
        ])

    def test_loaded_override_is_rejected_before_job(self):
        fields = dict(Id='named.service', Names='bind9.service named.service',
            LoadState='loaded', SourcePath='', DropInPaths='/etc/systemd/system/named.service.d/override.conf',
            FragmentPath='/usr/lib/systemd/system/named.service', Transient='no', NeedDaemonReload='no',
            ActiveState='inactive', MainPID='0', InvocationID='')
        with patch.object(bind, 'unit_properties', return_value=fields):
            with self.assertRaisesRegex(bind.Refused, 'UNPAIRED_BIND_UNIT'):
                bind.target()


@unittest.skipUnless(os.geteuid() == 0, 'exercise the durable Root state as root')
class BindJournalTest(unittest.TestCase):
    def setUp(self):
        self.state = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(bind, 'STATE', self.state))
        self.root = self.enterContext(patch.object(bind, 'state_binding', return_value=['machine', 1, 2]))
        self.runtime = ('a' * 64, 'inactive', '')
        self.target = self.enterContext(patch.object(bind, 'target', side_effect=lambda: self.runtime))
        self.job = self.enterContext(patch.object(bind, 'write_job'))

    def scoped(self, verb, operation=None):
        scope = bind.digest(self.root.return_value)
        return bind.request('scoped:' + scope + ':' + verb, operation or str(uuid.uuid4()))

    def lookup(self, expected):
        scope = expected['rootScope']
        return bind.request('outcome:' + scope, expected['operationId'])

    def acknowledge(self, expected, token):
        action = 'acknowledge:' + expected['rootScope'] + ':' + token
        return bind.request(action, expected['operationId'])

    def test_restart_receipt_answers_exact_request_without_another_service_job(self):
        expected = self.scoped('restart')

        def activate(verb):
            self.assertEqual(verb, 'restart')
            self.assertTrue((self.state / (expected['operationId'] + '.intent')).exists())
            self.runtime = ('a' * 64, 'active', 'b' * 32)

        self.job.side_effect = activate
        state, token = bind.operate(expected, lambda: True)
        self.assertEqual(state, 'APPLIED')
        self.assertEqual(bind.operate(expected, lambda: True), ('UNKNOWN', None))
        self.assertEqual(bind.operate(self.lookup(expected), lambda: True), ('APPLIED', token))
        self.assertFalse((self.state / (expected['operationId'] + '.delivered')).exists())
        self.assertEqual(bind.operate(self.scoped('stop'), lambda: True), ('UNKNOWN', None))
        with self.assertRaisesRegex(bind.Refused, 'UNPAIRED_BIND_DELIVERY'):
            bind.operate(self.acknowledge(expected, '0' * 64), lambda: True)
        self.assertEqual(bind.operate(self.acknowledge(expected, token), lambda: True), ('APPLIED', None))
        self.assertTrue((self.state / (expected['operationId'] + '.delivered')).is_file())
        self.job.assert_called_once_with('restart')
        with self.assertRaisesRegex(bind.Refused, 'BIND_OPERATION_ID_CONFLICT'):
            bind.operate(dict(expected, action='stop'), lambda: True)

    def test_unknown_fences_new_mutations_but_allows_read_only_status(self):
        expected = self.scoped('restart')
        self.job.side_effect = subprocess.TimeoutExpired('systemctl', 28)
        with self.assertRaises(subprocess.TimeoutExpired):
            bind.operate(expected, lambda: True)
        self.assertEqual(bind.operate(self.lookup(expected), lambda: True), ('UNKNOWN', None))
        self.assertEqual(bind.operate(self.scoped('stop'), lambda: True), ('UNKNOWN', None))
        status = bind.request('status', str(uuid.uuid4()))
        self.assertEqual(bind.operate(status, lambda: True), ('INACTIVE', None))
        self.job.assert_called_once_with('restart')

    def test_replaced_root_fails_before_any_further_write(self):
        self.assertEqual(bind.operate(self.scoped('stop'), lambda: True)[0], 'APPLIED')
        self.root.return_value = ['machine', 1, 3]
        with self.assertRaisesRegex(bind.Refused, 'UNPAIRED_BIND_STATE'):
            bind.operate(self.scoped('start'), lambda: True)
        self.job.assert_not_called()

    def test_configuration_refusal_precedes_intent_publication_and_service_jobs(self):
        expected = self.scoped('configure:enable:127.0.0.2:127.0.0.1/32')
        with patch.object(bind.configuration, 'prepare', side_effect=bind.Refused('UNOWNED_BIND_CONFIGURATION')):
            with self.assertRaisesRegex(bind.Refused, 'UNOWNED_BIND_CONFIGURATION'):
                bind.operate(expected, lambda: True)
        self.assertFalse(list(self.state.glob('*.intent')))
        self.job.assert_not_called()

    def test_configuration_is_staged_then_journaled_before_publication_and_activation(self):
        expected = self.scoped('configure:enable:127.0.0.2:127.0.0.1/32')
        payload = b'typed configuration'
        publication = dict(revision=1, before='a' * 64, published='b' * 64, stockSha256='a' * 64)
        effects = []

        @contextmanager
        def stage(*_):
            self.assertFalse(list(self.state.glob('*.intent')))
            effects.append('validated')
            yield Path('/staged'), [1, 2, 0, 0, 0o100640, 1, 10, 3000]

        def publish(*_):
            self.assertTrue((self.state / (expected['operationId'] + '.intent')).exists())
            effects.append('published')

        def start(action):
            self.assertEqual(action, 'start')
            effects.append('activated')
            self.runtime = ('a' * 64, 'active', 'c' * 32)

        self.job.side_effect = start
        with (patch.object(bind.configuration, 'prepare', return_value=('original', payload, publication)),
              patch.object(bind.configuration, 'stage', side_effect=stage),
              patch.object(bind.configuration, 'publish', side_effect=publish),
              patch.object(bind.configuration, 'read_current', return_value=('published',payload))):
            self.assertEqual(bind.operate(expected, lambda: True)[0], 'APPLIED')
        self.assertEqual(effects, ['validated', 'published', 'activated'])

    def test_another_root_does_not_look_up_the_original_operation(self):
        expected = self.scoped('stop')
        read_only = self.lookup(expected)
        self.root.return_value = ['another-machine', 1, 2]
        with (patch.object(bind.outcomes, 'intent_at') as lookup,
              self.assertRaisesRegex(bind.Refused, 'UNPAIRED_BIND_QUERY')):
            bind.operate(read_only, lambda: True)
        lookup.assert_not_called()

    def test_partial_intent_or_receipt_cannot_clear_the_original_operation(self):
        root = ['machine', self.state.stat().st_dev, self.state.stat().st_ino]
        self.root.return_value = root
        bind.create(self.state / 'root.json', dict(schema=1, root=root))
        expected = self.scoped('restart')
        path = self.state / (expected['operationId'] + '.intent')
        with (patch.object(bind, 'verify_actor', return_value='unit'),
              patch.object(bind, 'socket_peer'), patch.object(bind, 'active_provider', return_value='kura-networking'),
              patch.object(bind, 'main_peer', return_value=expected), patch.object(bind, 'receive', return_value=expected),
              patch.object(bind, 'send') as send):
            path.touch(mode=0o600)
            path.write_bytes(b'{"request":')
            bind.serve(None, 'unit')
        self.assertEqual(send.call_args.args[1], dict(schema=1, operationId=expected['operationId'], state='UNKNOWN'))
        self.assertEqual(bind.operate(self.lookup(expected), lambda: True), ('UNKNOWN', None))
        self.assertEqual(path.read_bytes(), b'{"request":')
        self.job.assert_not_called()

        # A separate request has a valid intent but a truncated terminal record.
        other = self.scoped('stop')
        bind.create(self.state / (other['operationId'] + '.intent'),
                    dict(root=root, request=other, deliveryProtocol=1))
        receipt = self.state / (other['operationId'] + '.result')
        receipt.touch(mode=0o600)
        receipt.write_bytes(b'{"deliveryToken":')
        self.assertEqual(bind.operate(self.lookup(other), lambda: True), ('UNKNOWN', None))
        self.assertEqual(receipt.read_bytes(), b'{"deliveryToken":')
        self.assertFalse(list(self.state.glob('*.delivered')))

    def test_write_failure_requires_absence_in_the_original_paired_directory(self):
        root = ['machine', self.state.stat().st_dev, self.state.stat().st_ino]
        self.root.return_value = root
        expected = self.scoped('start')
        self.assertEqual(bind.outcomes.failed_write_state(self.state, expected, self.root), 'REFUSED')
        bind.create(self.state / 'root.json', dict(schema=1, root=root))
        self.assertEqual(bind.outcomes.failed_write_state(self.state, expected, self.root), 'REFUSED')

        self.root.return_value = ['other-machine', *root[1:]]
        with patch.object(bind.outcomes.os, 'open') as opened:
            self.assertEqual(bind.outcomes.failed_write_state(self.state, expected, self.root), 'UNKNOWN')
            opened.assert_not_called()
        self.root.return_value = root
        (self.state / 'root.json').write_bytes(b'{')
        self.assertEqual(bind.outcomes.failed_write_state(self.state, expected, self.root), 'UNKNOWN')
        with self.assertRaises(bind.Refused):
            bind.operate(self.lookup(expected), lambda: True)

    def test_outcome_on_unpaired_intent_is_still_refused(self):
        expected = self.scoped('stop')
        root = self.root.return_value
        bind.create(self.state / 'root.json', dict(schema=1, root=root))
        path = self.state / (expected['operationId'] + '.intent')
        bind.create(path, dict(root=['other-machine', *root[1:]], request=expected))
        with self.assertRaisesRegex(bind.Refused, 'UNPAIRED_BIND_STATE'):
            bind.operate(self.lookup(expected), lambda: True)
        path.chmod(0o640)
        with self.assertRaisesRegex(bind.Refused, 'UNSAFE_STATE'):
            bind.operate(self.lookup(expected), lambda: True)
        self.job.assert_not_called()

    def test_previous_terminal_receipts_are_compatible_on_the_original_root(self):
        operation = str(uuid.uuid4())
        root = self.root.return_value
        intent = dict(root=root, request=dict(schema=1, action='stop', operationId=operation))
        bind.create(self.state / 'root.json', dict(schema=1, root=root))
        bind.create(self.state / (operation + '.intent'), intent)
        bind.create(self.state / (operation + '.result'), dict(intentSha256=bind.digest(intent), state='APPLIED'))
        query = bind.request('outcome:' + bind.digest(root), operation)
        self.assertEqual(bind.operate(query, lambda: True), ('APPLIED', None))
        self.assertEqual(bind.operate(self.scoped('stop'), lambda: True)[0], 'APPLIED')
        self.job.assert_not_called()

    def unsettled_file_intent(self, *, mode='keep', paired_boot=True):
        operation = str(uuid.uuid4())
        root = self.root.return_value
        request = self.scoped('configure:' + mode + ':127.0.0.2:127.0.0.1/32', operation)
        file = [1, 2, 0, 0, 0o100640, 1, 10, 3000]
        boot = bind.boot_identity() if paired_boot else str(uuid.uuid4())
        intent = dict(root=root, request=request, target=self.runtime[0], state=self.runtime[1],
                      invocation=self.runtime[2], deliveryProtocol=1, publication=dict(published='c' * 64),
                      stagedPublication=dict(boot=boot, file=file))
        bind.create(self.state / 'root.json', dict(schema=1, root=root))
        bind.create(self.state / (operation + '.intent'), intent)
        return intent, bind.request('settle-publication:' + bind.digest(root), operation)

    def test_file_publication_settlement_commits_without_dispatching_or_acknowledging(self):
        intent, settle = self.unsettled_file_intent()
        operation = settle['operationId']
        with (patch.object(bind.configuration, 'published', return_value=True) as proof,
              patch.object(bind.configuration, 'sync_publication') as sync):
            state, token = bind.operate(settle, lambda: True)
        self.assertEqual(state, 'APPLIED')
        proof.assert_called_with(intent['stagedPublication']['file'], intent['publication']['published'])
        sync.assert_called_once_with()
        receipt = bind.outcomes.result_at(self.state, operation, intent)
        self.assertEqual(receipt['recovery'], 'paired-file-publication')
        self.assertEqual(receipt['deliveryToken'], token)
        self.assertFalse((self.state / (operation + '.delivered')).exists())
        self.job.assert_not_called()

    def test_mismatched_published_inode_leaves_original_intent_unsettled(self):
        _, settle = self.unsettled_file_intent()
        with patch.object(bind.configuration, 'published', return_value=False):
            self.assertEqual(bind.operate(settle, lambda: True), ('UNKNOWN', None))
        self.assertFalse(list(self.state.glob('*.result')))
        self.job.assert_not_called()

    def test_service_activation_cannot_be_inferred_from_a_matching_file(self):
        _, settle = self.unsettled_file_intent(mode='enable')
        with patch.object(bind.configuration, 'published') as verifier:
            self.assertEqual(bind.operate(settle, lambda: True), ('UNKNOWN', None))
        verifier.assert_not_called()
        self.assertFalse(list(self.state.glob('*.result')))
        self.job.assert_not_called()
