# SPDX-License-Identifier: EPL-2.0
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

RESOURCES = Path(__file__).resolve().parents[1] / 'main/resources'
sys.path.insert(0, str(RESOURCES / 'unfiltered/pkg/bin'))
import kura_command_executor as executor


class IcmpProbeTest(unittest.TestCase):
    def test_typed_targets(self):
        for family, address in (('-4', '127.0.0.1'), ('-6', '::1'), ('-6', 'fe80::1%eth0'),
                                ('-6', 'gateway.example.'), ('-4', 'xn--bcher-kva.example')):
            with self.subTest(family=family, address=address):
                self.assertEqual(executor.icmp_request(family, address), (family, address))

        for family, address in (('-I', 'lo'), ('-4', '::1'), ('-6', 'fd00:::1'), ('-6', 'fe80::1%'),
                                ('-6', 'fe80::1%eth0%lo'), ('-4', '-f'), ('-4', 'host\n'),
                                ('-6', 'a' * 254), ('-4', 'host -f'), ('-4', '')):
            with self.subTest(family=family, address=address):
                with self.assertRaisesRegex(executor.Refused, 'INVALID_ICMP_TARGET'):
                    executor.icmp_request(family, address)

    def test_only_the_paired_main_child_selects_the_fixed_probe(self):
        stream = Mock()
        unit = 'kura-icmp-probe@fixture.service'
        with patch.object(executor, 'verify_actor', return_value='main-unit-hash') as verify, \
                patch.object(executor, 'socket_peer') as peer, \
                patch.object(executor, 'main_peer') as main, patch.object(executor, 'protected') as protected, \
                patch.object(executor.subprocess, 'run') as run:
            identity = peer.return_value.__enter__.return_value
            main.side_effect = executor.Refused('UNAUTHORIZED')
            with self.assertRaisesRegex(executor.Refused, 'UNAUTHORIZED'):
                executor.serve_icmp(stream, unit)
            run.assert_not_called()
            stream.sendall.assert_not_called()

            for returncode, wire in ((0, b'\x00'), (1, b'\x01'), (2, b'\x01')):
                with self.subTest(returncode=returncode):
                    main.reset_mock()
                    main.side_effect = None
                    main.return_value = ('-6', '::1')
                    run.return_value.returncode = returncode
                    executor.serve_icmp(stream, unit)
                    verify.assert_called_with(unit, account_name=executor.ICMP_ACCOUNT,
                                              socket_unit=executor.ICMP_SOCKET_UNIT, template=executor.ICMP_SERVICE,
                                              capabilities=executor.CAP_NET_RAW)
                    self.assertEqual(main.call_count, 2)
                    main.assert_called_with(identity, 'main-unit-hash', executor.ICMP_CLIENT,
                                            2, executor.icmp_request, generation_proof=None)
                    protected.assert_called_with(executor.ICMP_BINARY)
                    run.assert_called_with(['/usr/bin/ping', '-6', '-n', '-c', '5', '-W', '1', '--', '::1'],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, env=executor.ENVIRONMENT, timeout=12)
                    stream.sendall.assert_called_with(wire)

    def test_main_and_ordinary_executor_do_not_receive_the_probe_capability(self):
        main = (RESOURCES / 'filtered/pkg/install/kura.service').read_text().lower()
        units = RESOURCES / 'unfiltered/pkg/install'
        ordinary = (units / executor.SERVICE).read_text().lower()
        actor = (units / executor.ICMP_SERVICE).read_text().lower()
        self.assertIn(executor.ICMP_SOCKET_UNIT, main)
        self.assertNotIn('cap_net_raw', main)
        self.assertNotIn('cap_net_raw', ordinary)
        self.assertIn('\ncapabilityboundingset=cap_net_raw\n', actor)
        self.assertIn('\nambientcapabilities=cap_net_raw\n', actor)
        self.assertIn('\nnonewprivileges=yes\n', actor)


if __name__ == '__main__':
    unittest.main()
