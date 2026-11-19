# SPDX-License-Identifier: EPL-2.0
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_dhcp_configuration as config
import kura_dhcp_service as service
from kura_clock_journal import Refused
from kura_reboot_broker import receive, send


FIRST = 'link0,192.0.2.1,24,192.0.2.100,192.0.2.120,192.0.2.1,900,1'
SECOND = 'link1,198.51.100.1,24,198.51.100.100,198.51.100.120,,600,0'


class DhcpServiceTest(unittest.TestCase):
    def test_only_fixed_dhcp_options_are_generated(self):
        body = config.render(config.parse(SECOND + ';' + FIRST)).decode()
        self.assertEqual(body, config.render(config.parse(FIRST + ';' + SECOND)).decode())
        self.assertIn('port=0\n', body)
        self.assertIn('dhcp-range=tag:link0,set:link0,192.0.2.100,192.0.2.120,255.255.255.0,900s\n', body)
        self.assertIn('dhcp-option=tag:link0,6,192.0.2.1\n', body)
        self.assertIn('dhcp-option=tag:link1,3\n', body)
        self.assertIn('dhcp-ignore-names=tag:link1\n', body)

    def test_reject_untyped_and_ambiguous_pools(self):
        for value in (FIRST.replace('link0', 'link0\nconf-file=/tmp/injected'),
                      FIRST.replace('192.0.2.100', '192.0.2.0'),
                      FIRST.replace('192.0.2.100', '192.0.2.1'),
                      FIRST.replace('900,1', '119,1'), FIRST + ';' + FIRST,
                      FIRST + ';' + SECOND.replace('198.51.100.', '192.0.2.')):
            with self.subTest(value=value), self.assertRaises(Refused):
                config.parse(value)

    def test_original_scope_and_binary_frame_are_bounded(self):
        model = ';'.join(f'link{n},192.0.{n}.1,24,192.0.{n}.100,192.0.{n}.120,,900,0' for n in range(48))
        operation = str(uuid4())
        message = service.request('apply:' + '1' * 64 + ':' + model, operation)
        sender, reader = socket.socketpair()
        with sender, reader:
            send(sender, message, maximum=service.REQUEST_LIMIT)
            self.assertEqual(message, receive(reader, maximum=service.REQUEST_LIMIT))
        with self.assertRaises(Refused):
            service.request('apply:wrong:' + model, operation)

    def test_interface_identity_tracks_the_active_address(self):
        model = config.parse(FIRST)
        payload = b'[{"ifname":"link0","ifindex":9,"flags":["UP"],"addr_info":[{"local":"192.0.2.1","prefixlen":24}]}]'
        with patch.object(service.subprocess, 'check_output', return_value=payload):
            self.assertEqual((9,), service.observe_interfaces(model))
        with patch.object(service.subprocess, 'check_output', return_value=payload.replace(b'24', b'25')):
            with self.assertRaises(Refused):
                service.observe_interfaces(model)
