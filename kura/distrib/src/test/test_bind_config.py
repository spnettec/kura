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
        self.assertIn(b'include "/etc/bind/named.conf.local";', result)
        self.assertNotIn(b'include "/etc/bind/named.conf.options";', result)

    def test_rejects_untyped_text_and_incomplete_active_configuration(self):
        for field in ('configure:enable:127.0.0.2:192.0.2.0/128',
                      'configure:enable:127.0.0.2:',
                      'configure:keep:127.0.0.2,include "file";:',
                      'configure:enable:127.0.0.2:192.0.2.0/24,'):
            with self.subTest(field=field), self.assertRaisesRegex(bind.Refused, 'INVALID_BIND_CONFIGURATION'):
                config.decode_fields(field)

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
