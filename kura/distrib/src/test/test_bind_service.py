# SPDX-License-Identifier: EPL-2.0
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

    def operation(self, verb):
        return bind.request(verb, str(uuid.uuid4()))

    def test_restart_receipt_answers_exact_request_without_another_service_job(self):
        expected = self.operation('restart')

        def activate(verb):
            self.assertEqual(verb, 'restart')
            self.assertTrue((self.state / (expected['operationId'] + '.intent')).exists())
            self.runtime = ('a' * 64, 'active', 'b' * 32)

        self.job.side_effect = activate
        self.assertEqual(bind.operate(expected, lambda: True), 'APPLIED')
        self.assertEqual(bind.operate(expected, lambda: True), 'APPLIED')
        self.job.assert_called_once_with('restart')
        with self.assertRaisesRegex(bind.Refused, 'BIND_OPERATION_ID_CONFLICT'):
            bind.operate(dict(expected, action='stop'), lambda: True)

    def test_unknown_fences_new_mutations_but_allows_read_only_status(self):
        expected = self.operation('restart')
        self.job.side_effect = subprocess.TimeoutExpired('systemctl', 28)
        with self.assertRaises(subprocess.TimeoutExpired):
            bind.operate(expected, lambda: True)
        self.assertEqual(bind.operate(expected, lambda: True), 'UNKNOWN')
        self.assertEqual(bind.operate(self.operation('stop'), lambda: True), 'UNKNOWN')
        self.assertEqual(bind.operate(self.operation('status'), lambda: True), 'INACTIVE')
        self.job.assert_called_once_with('restart')

    def test_replaced_root_fails_before_any_further_write(self):
        self.assertEqual(bind.operate(self.operation('stop'), lambda: True), 'APPLIED')
        self.root.return_value = ['machine', 1, 3]
        with self.assertRaisesRegex(bind.Refused, 'UNPAIRED_BIND_STATE'):
            bind.operate(self.operation('start'), lambda: True)
        self.job.assert_not_called()
