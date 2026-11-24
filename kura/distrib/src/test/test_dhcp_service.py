# SPDX-License-Identifier: EPL-2.0
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
import os
import tempfile
import socket
import struct
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_dhcp_configuration as config
import kura_dhcp_service as service
import kura_dhcp_listeners as listeners
from kura_clock_journal import Refused
from kura_reboot_broker import receive, send


FIRST = 'link0,192.0.2.1,24,192.0.2.100,192.0.2.120,192.0.2.1,900,1'
SECOND = 'link1,198.51.100.1,24,198.51.100.100,198.51.100.120,,600,0'


class DhcpServiceTest(unittest.TestCase):
    def test_daemon_reads_only_the_systemd_projected_configuration(self):
        units = Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/install'
        fields = dict(line.split('=', 1) for line in (units / service.DAEMON_UNIT).read_text().splitlines()
                      if '=' in line)
        view = '/run/kura-dhcp-config.conf'
        self.assertEqual(f'{service.CONFIG}:{view}', fields['BindReadOnlyPaths'])
        self.assertTrue(fields['ExecStart'].startswith(
            f'/usr/bin/setpriv --no-new-privs {service.DAEMON} --conf-file={view} '))
        self.assertEqual('dnsmasq', fields['User'])
        self.assertEqual('yes', fields['NoNewPrivileges'])

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

    @unittest.skipUnless(os.geteuid() == 0, 'exercise the root-owned actor journal')
    def test_only_the_original_dhcp_model_can_recover_its_receipt(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(service, 'STATE', Path(temp)), patch.object(
                service, 'state_binding', return_value=['machine', 1, 2]) as binding:
            root = binding.return_value
            scope = service.digest(root)
            operation = str(uuid4())
            action = 'apply:' + scope + ':'
            original = service.request(action + FIRST, operation)
            intent = dict(root=root, request=original, deliveryProtocol=service.outcomes.PROTOCOL)
            service.create(service.STATE / 'root.json', dict(schema=1, root=root))
            service.create(service.STATE / (operation + '.intent'), intent)
            token = service.outcomes.commit(service.STATE / (operation + '.result'), intent)
            def lookup(model):
                expected = service.request('paired-outcome:' + action + model, operation)
                return service.operate(expected, {}, lambda: True)
            self.assertEqual(lookup(FIRST), ('APPLIED', token))
            with self.assertRaisesRegex(Refused, 'UNPAIRED_OUTCOME_REQUEST'):
                lookup(SECOND)
            self.assertFalse((service.STATE / (operation + '.delivered')).exists())

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
            self.assertEqual((listeners.Link(9, frozenset({IPv4Address('192.0.2.1')})),),
                             service.observe_interfaces(model))
        with patch.object(service.subprocess, 'check_output', return_value=payload.replace(b'24', b'25')):
            with self.assertRaises(Refused):
                service.observe_interfaces(model)

    def test_only_exact_cgroup_can_own_the_requested_listener(self):
        requested = listeners.Link(9, frozenset(map(IPv4Address, ('192.0.2.1', '192.0.2.255'))), 42)
        other = listeners.Listener(10, IPv4Address(0), 311)
        managed = listeners.Listener(9, IPv4Address(0), 312)
        with patch.object(listeners, 'snapshot', return_value=[other, managed]):
            listeners.check((requested,), 312, ready=True)
            with self.assertRaisesRegex(Refused, 'DHCP_PORT_IN_USE'):
                listeners.check((requested,), None)
        with patch.object(listeners, 'snapshot', return_value=[other]):
            listeners.check((requested,), None)
            with self.assertRaisesRegex(Refused, 'DHCP_SOCKET_OWNERSHIP_UNVERIFIED'):
                listeners.check((requested,), 312, ready=True)

    def test_exact_wildcard_and_master_scope_conflicts(self):
        link = listeners.Link(3, frozenset(map(IPv4Address, ('192.0.2.1', '192.0.2.255'))), 13)
        for index, host in ((3, '0.0.0.0'), (13, '0.0.0.0'), (0, '0.0.0.0'), (0, '255.255.255.255'),
                            (0, '192.0.2.255'), (0, '192.0.2.1')):
            with self.subTest(index=index, address=host), patch.object(
                    listeners, 'snapshot', return_value=[listeners.Listener(index, IPv4Address(host), None)]):
                with self.assertRaisesRegex(Refused, 'DHCP_PORT_IN_USE'):
                    listeners.check((link,), None)
        for index, host in ((4, '0.0.0.0'), (0, '198.51.100.1')):
            with self.subTest(index=index, address=host), patch.object(
                    listeners, 'snapshot', return_value=[listeners.Listener(index, IPv4Address(host), None)]):
                listeners.check((link,), None)

    def test_linux_diagnostic_keeps_dual_stack_and_cgroup_identity(self):
        payload = bytearray(72)
        payload[0] = socket.AF_INET6
        struct.pack_into('!H', payload, 4, 67)
        struct.pack_into('=I', payload, 40, 3)
        payload[8:24] = IPv6Address('::ffff:192.0.2.1').packed
        payload.extend(struct.pack('=HHQ', 12, listeners.INET_DIAG_CGROUP_ID, 123456789))
        self.assertEqual(listeners.Listener(3, IPv4Address('192.0.2.1'), 123456789),
                         listeners.listen_record(bytes(payload), socket.AF_INET6))
        payload.extend(struct.pack('=HHB3x', 5, listeners.INET_DIAG_SKV6ONLY, 1))
        self.assertIsNone(listeners.listen_record(bytes(payload), socket.AF_INET6))

    def test_multiple_links_use_one_owned_wildcard_socket(self):
        links = (listeners.Link(9, frozenset()), listeners.Link(10, frozenset()))
        managed = listeners.Listener(0, IPv4Address(0), 312)
        foreign = listeners.Listener(11, IPv4Address(0), 314)
        with patch.object(listeners, 'snapshot', return_value=[managed]):
            listeners.check(links, 312, ready=True)
            with self.assertRaisesRegex(Refused, 'DHCP_SOCKET_OWNERSHIP_UNVERIFIED'):
                listeners.check(links[:1], 312, ready=True)
        with patch.object(listeners, 'snapshot', return_value=[managed, foreign]):
            with self.assertRaisesRegex(Refused, 'DHCP_PORT_IN_USE'):
                listeners.check(links, 312)
        with patch.object(listeners, 'snapshot', return_value=[foreign]):
            with self.assertRaisesRegex(Refused, 'DHCP_PORT_IN_USE'):
                listeners.check(links, None)

    def test_socket_verification_rechecks_configuration_identity_and_invocation(self):
        model = config.render(config.parse(FIRST))
        published = ((1, 2, 3), model)
        links = (listeners.Link(9, frozenset()),)
        unit = ('release', 'active', 'invocation', 312)
        with patch.object(service, 'current_config', return_value=published), patch.object(
                listeners, 'check') as check, patch.object(service, 'target', return_value=unit):
            service.check_active_target({}, unit, links, published)
            check.assert_called_once_with(links, 312, ready=True)
        with patch.object(service, 'current_config', return_value=((1, 2, 4), model)), patch.object(
                listeners, 'check'), patch.object(service, 'target', return_value=unit):
            with self.assertRaisesRegex(Refused, 'DHCP_TARGET_CHANGED'):
                service.check_active_target({}, unit, links, published)
        with patch.object(service, 'current_config', return_value=published), patch.object(
                listeners, 'check'), patch.object(service, 'target', return_value=('release','active','changed',312)):
            with self.assertRaisesRegex(Refused, 'DHCP_TARGET_CHANGED'):
                service.check_active_target({}, unit, links, published)
