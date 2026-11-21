# SPDX-License-Identifier: EPL-2.0
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess, DEVNULL

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_firewall_tables as reader


class FirewallTableReaderTest(unittest.TestCase):
    def test_checks_every_table_in_the_selected_family(self):
        for family, program in reader.FAMILIES.items():
            with self.subTest(family=family), patch.object(reader.subprocess, 'run') as run:
                run.return_value = CompletedProcess([], 0)
                self.assertEqual(reader.check_tables(family), b'1')
                self.assertEqual([c.args[0] for c in run.call_args_list],
                                 [[program, '-t', t, '-S'] for t in ('filter', 'nat', 'mangle')])
                for call in run.call_args_list:
                    self.assertEqual(call.kwargs['stdout'], DEVNULL)
                    self.assertEqual(call.kwargs['stderr'], DEVNULL)

    def test_refuses_unknown_requests_and_identifies_failed_table(self):
        with patch.object(reader.subprocess, 'run') as run:
            with self.assertRaises(reader.markers.Refused):
                reader.check_tables(b'x')
            run.assert_not_called()
            run.side_effect = [CompletedProcess([], 0), CompletedProcess([], 1)]
            self.assertEqual(reader.check_tables(b'4'), b'N')
            self.assertEqual(run.call_count, 2)
