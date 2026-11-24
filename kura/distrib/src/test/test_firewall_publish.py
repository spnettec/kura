# SPDX-License-Identifier: EPL-2.0
from contextlib import redirect_stderr
from io import BytesIO, StringIO
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


BIN = Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'
sys.path.insert(0, str(BIN))
import kura_firewall_publish as broker


class FirewallPublishTest(unittest.TestCase):
    def test_worker_eof_does_not_escape_to_the_crash_reporter(self):
        worker = SimpleNamespace(stdout=BytesIO())
        unit = 'kura-firewall-publish@fixture.service'
        with (patch.object(sys, 'argv', ['broker', unit]),
              patch.object(broker.socket, 'socket') as activated,
              patch.object(broker, 'serve', side_effect=lambda stream, name: broker.worker_reply(worker)),
              redirect_stderr(StringIO()) as error):
            self.assertEqual(broker.main(), 1)
        self.assertEqual(error.getvalue(), 'Kura firewall publication refused: NO_FIREWALL_RESULT\n')
        activated.assert_called_once_with(fileno=0)
        activated.return_value.__exit__.assert_called_once()
        activated.return_value.__enter__.return_value.sendall.assert_not_called()

    def test_expected_transport_failure_has_a_bounded_diagnostic(self):
        with (patch.object(sys, 'argv', ['broker', 'kura-firewall-publish@fixture.service']),
              patch.object(broker.socket, 'socket', side_effect=OSError('untrusted detail')),
              redirect_stderr(StringIO()) as error):
            self.assertEqual(broker.main(), 1)
        self.assertEqual(error.getvalue(), 'Kura firewall publication failed: transport or invalid reply\n')

    def test_unexpected_programming_error_propagates(self):
        with (patch.object(sys, 'argv', ['broker', 'kura-firewall-publish@fixture.service']),
              patch.object(broker.socket, 'socket', side_effect=AssertionError('programming error'))):
            with self.assertRaises(AssertionError):
                broker.main()


if __name__ == '__main__':
    unittest.main()
