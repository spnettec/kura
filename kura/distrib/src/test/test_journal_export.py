# SPDX-License-Identifier: EPL-2.0
from io import BytesIO
from pathlib import Path
import socket
import struct
import subprocess
import sys
from threading import Thread
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_journal_export as export


class JournalExportTest(unittest.TestCase):
    def test_typed_scope_and_fields(self):
        self.assertEqual(export.request('kura', 'MESSAGE,_BOOT_ID'),
                         {'schema': 1, 'scope': 'kura', 'fields': 'MESSAGE,_BOOT_ID'})
        for scope, fields in [('ssh.service', 'MESSAGE'), ('system', 'MESSAGE,'),
                              ('system', 'MESSAGE;id'), ('system', '--file=/etc/shadow'),
                              ('system', 'MESSAGE\n'), ('system', ','.join(['MESSAGE'] * 33))]:
            with self.subTest(scope=scope, fields=fields), self.assertRaises(export.Refused):
                export.request(scope, fields)

    def test_command_has_only_the_fixed_journal_selectors(self):
        for scope in ('kura', 'system'):
            sink = BytesIO()
            popen = subprocess.Popen
            def produce(argv, **options):
                expected = ['/usr/bin/journalctl', '--no-pager', '--quiet', '--output=verbose',
                            '--output-fields=MESSAGE']
                if scope == 'kura':
                    expected.append('--unit=kura.service')
                self.assertEqual(argv, expected)
                return popen([sys.executable, '-c', 'print("fixture")'], **options)
            with patch.object(export, 'protected'), patch.object(export.subprocess, 'Popen', side_effect=produce):
                self.assertEqual(export.read_journal(export.request(scope, 'MESSAGE'), sink), 8)
                self.assertEqual(sink.read(), b'fixture\n')

    def test_oversize_output_is_refused_before_it_can_be_published(self):
        popen = subprocess.Popen
        with patch.object(export, 'protected'), patch.object(export, 'MAX_DATA', 8), \
                patch.object(export.subprocess, 'Popen', side_effect=lambda argv, **options:
                             popen([sys.executable, '-c', 'print("unpublished data")'], **options)):
            with self.assertRaisesRegex(export.Refused, 'EXPORT_TOO_LARGE'):
                export.read_journal(export.request('system', 'MESSAGE'), BytesIO())

    def exchange(self, incoming, expected, reject):
        server, client = socket.socketpair()
        self.addCleanup(server.close)
        self.addCleanup(client.close)
        errors = []

        def work():
            with server, patch.object(export, 'verify_actor'), patch.object(export, 'socket_peer') as peer, \
                    patch.object(export, 'main_peer', return_value=expected), \
                    patch.object(export, 'read_journal', side_effect=lambda value, out:
                                 self.write_fixture(out)) as journal:
                peer.return_value.__enter__.return_value = object()
                try:
                    export.serve(server, 'kura-journal-export@fixture.service')
                except export.Refused as error:
                    errors.append(str(error))
                if reject:
                    journal.assert_not_called()

        worker = Thread(target=work)
        worker.start()
        export.send(client, incoming)
        client.settimeout(3)
        with client.makefile('rb') as stream:
            raw = stream.read()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        if reject:
            self.assertEqual(errors, ['INVALID_EXPORT'])
            self.assertEqual(raw, b'')
        else:
            self.assertEqual(errors, [])
            self.assertEqual(raw, struct.pack('>I', 3) + b'log')

    def write_fixture(self, out):
        out.write(b'log')
        out.seek(0)
        return 3

    def test_kernel_peer_selected_command_must_match_the_entire_wire_request(self):
        expected = export.request('kura', 'MESSAGE')
        self.exchange(export.request('system', 'MESSAGE'), expected, reject=True)
        self.exchange(dict(expected, schema=True), expected, reject=True)
        self.exchange(expected, expected, reject=False)


if __name__ == '__main__':
    unittest.main()
