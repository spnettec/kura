# SPDX-License-Identifier: EPL-2.0
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_bind_service import bind

config = bind.configuration
STOCK = (b'// Stock Debian file\n'
         b'include "/etc/bind/named.conf.options";\n'
         b'include "/etc/bind/named.conf.local";\n'
         b'include "/etc/bind/named.conf.root-hints";\n')


class BindConfigurationTest(unittest.TestCase):
    def test_ipv4_and_cidr_fields_are_canonical_and_render_only_fixed_directives(self):
        value = config.decode_fields('configure:enable:127.0.0.2,127.0.0.2:192.0.2.9/24')
        self.assertEqual(value, dict(mode='enable', forwarders=['127.0.0.2'], networks=['192.0.2.0/24']))
        result = config.render(value, STOCK)
        self.assertIn(b'allow-query {192.0.2.0/24;};', result)
        self.assertIn(b'allow-recursion {192.0.2.0/24;};', result)
        self.assertNotIn(b'listen-on {', result)
        self.assertIn(b'include "/etc/bind/named.conf.local";', result)
        self.assertNotIn(b'include "/etc/bind/named.conf.options";', result)

    def test_rejects_untyped_text_and_incomplete_active_configuration(self):
        for field in ('configure:enable:127.0.0.2:192.0.2.0/128',
                      'configure:enable:127.0.0.2:',
                      'configure:enable-lan:127.0.0.1,192.0.2.5:203.0.113.0/24',
                      'configure:enable-lan:127.0.0.1,127.0.0.53:203.0.113.0/24',
                      'configure:enable-lan:127.0.0.2:203.0.113.0/24',
                      'configure:enable-lan::203.0.113.0/24',
                      'configure:keep:127.0.0.2,include "file";:',
                      'configure:enable:127.0.0.2:192.0.2.0/24,'):
            with self.subTest(field=field), self.assertRaisesRegex(bind.Refused, 'INVALID_BIND_CONFIGURATION'):
                config.decode_fields(field)

    def test_lan_listener_excludes_loopback_and_uses_only_verified_client_prefixes(self):
        for resolver in ('127.0.0.1', '127.0.0.53', '127.0.0.54', '192.0.2.10'):
            candidate = config.decode_fields('configure:enable-lan:' + resolver + ':203.0.113.9/24')
            result = config.render(candidate, STOCK)
            self.assertIn(b'listen-on {!127.0.0.0/8;203.0.113.0/24;};', result)
            self.assertIn(b'listen-on-v6 { none; };', result)
            self.assertIn(b'allow-recursion {!localhost;203.0.113.0/24;};', result)
            self.assertIn(('forwarders {' + resolver + ';};').encode(), result)
            self.assertIn(b'forward only;', result)

    def test_dual_stack_listener_and_upstream_are_typed_independently(self):
        value = config.decode_fields('configure:enable-lan-dual:20010db8000200000000000000000053:'
                                     '203.0.113.1/24,fd370000000000000000000000000001/64')
        self.assertEqual(value['forwarders'], ['2001:db8:2::53'])
        self.assertEqual(value['networks'], ['203.0.113.0/24', 'fd37::/64'])
        result = config.render(value, STOCK)
        self.assertIn(b'listen-on {!127.0.0.0/8;203.0.113.0/24;};', result)
        self.assertIn(b'listen-on-v6 {!::1;fd37::/64;};', result)
        self.assertIn(b'allow-query {!localhost;203.0.113.0/24;fd37::/64;};', result)
        self.assertIn(b'forwarders {2001:db8:2::53;};', result)
        value['networks'] = ['fd37::/64']
        self.assertIn(b'listen-on { none; };', config.render(value, STOCK))

    def test_dual_stack_rejects_unscoped_upstream_wildcards_and_unsafe_lan_prefixes(self):
        v6_lan = 'fd370000000000000000000000000001/64'
        for address in ('fe800000000000000000000000000053', 'ff010000000000000000000000000053',
                        '00000000000000000000ffff7f000001', '00000000000000000000000000000000',
                        '127.0.0.53,192.0.2.53'):
            with self.subTest(address=address), self.assertRaisesRegex(bind.Refused, 'INVALID_BIND_CONFIGURATION'):
                config.decode_fields('configure:enable-lan-dual:' + address + ':' + v6_lan)
        for network in ('fd370000000000000000000000000001/0', 'fd370000000000000000000000000001/129',
                        'fe800000000000000000000000000001/64'):
            with self.subTest(network=network), self.assertRaisesRegex(bind.Refused, 'INVALID_BIND_CONFIGURATION'):
                config.decode_fields('configure:enable-lan-dual:192.0.2.53:' + network)

    def test_link_local_forwarders_preserve_their_bound_zone_identity(self):
        base = 'configure:enable-lan-scoped:fe800000000000000000000000000053'
        network = ':fd370000000000000000000000000001/64'
        value = config.decode_fields(base + '%wan0.15@104' + network)
        self.assertEqual(value['forwarders'], ['fe80::53%wan0.15'])
        self.assertEqual(value['scopes'], {'wan0.15': 104})
        self.assertIn(b'forwarders {fe80::53%104;};', config.render(value, STOCK))
        with patch.object(config.socket, 'if_nametoindex', return_value=104):
            config.check_scopes(value)
        with (patch.object(config.socket, 'if_nametoindex', return_value=105),
              self.assertRaisesRegex(bind.Refused, 'BIND_RESOLVER_INTERFACE_CHANGED')):
            config.check_scopes(value)
        for suffix in ('', '%wan0@0', '%wan0@1;include', '%wan0@2147483648',
                       '%wan0@7,fe800000000000000000000000000053%wan0@8'):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(bind.Refused, 'INVALID_BIND_CONFIGURATION'):
                config.decode_fields(base + suffix + network)

    def test_only_stock_or_the_latest_matched_publication_is_eligible(self):
        files = {str(config.CONFIG): config.md5(STOCK)}
        self.assertEqual(config.paired_stock(STOCK, [], files), STOCK)
        with self.assertRaisesRegex(bind.Refused, 'UNOWNED_BIND_CONFIGURATION'):
            config.paired_stock(STOCK + b'// local changes\n', [], files)
        import base64
        managed = config.render(config.decode_fields('configure:enable:127.0.0.2:127.0.0.1/32'), STOCK)
        entry = dict(revision=1, before=config.sha(STOCK), published=config.sha(managed),
                     stockSha256=config.sha(STOCK), stock=base64.b64encode(STOCK).decode('ascii'))
        self.assertEqual(config.paired_stock(managed, [entry], files), STOCK)
        with self.assertRaisesRegex(bind.Refused, 'UNOWNED_BIND_CONFIGURATION'):
            config.paired_stock(STOCK, [entry], files)
        self.assertEqual(config.render(config.decode_fields('configure:disable::'), STOCK), STOCK)


@unittest.skipUnless(os.geteuid() == 0, 'exercise Root ownership and atomic publication')
class BindConfigFileTest(unittest.TestCase):
    def test_replacement_preserves_group_and_mode_and_rejects_stale_identity(self):
        parent = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/run')))
        parent.chmod(0o2750)
        file = parent / 'named.conf'
        file.write_bytes(STOCK)
        file.chmod(0o640)
        with patch.object(config, 'CONFIG', file):
            identity, _ = config.read_current()
            payload = b'paired publication'
            with (patch.object(config.subprocess, 'run'),
                  config.stage(identity, payload, lambda: None, {}) as (staged, expected)):
                config.publish(identity, payload, staged, expected)
                observed, raw = config.read_current()
                self.assertEqual(observed[2:5], identity[2:5])
                self.assertEqual(config.publication_identity(observed), expected)
                self.assertEqual(raw, payload)
                with self.assertRaisesRegex(bind.Refused, 'BIND_CONFIGURATION_CHANGED'):
                    config.publish(identity, payload, staged, expected)
