# SPDX-License-Identifier: EPL-2.0
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_wpa_policy as policy

XML = b'<busconfig>\n    <!-- original managed policy -->\n</busconfig>\n'


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'exercise exact Root policy metadata on Linux')
class WpaPolicyTest(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/run')))
        self.site = root / 'etc/wpa_supplicant.conf'
        self.vendor = root / 'vendor/wpa_supplicant.conf'
        for name in (self.site, self.vendor):
            name.parent.mkdir()
        self.pkla = root / 'kura-wifi.pkla'
        self.modem_pkla = root / 'kura-modem.pkla'
        self.bus_path = root / 'system_bus_socket'
        self.enterContext(patch.object(policy, 'XML_FILES', (self.site, self.vendor)))
        self.enterContext(patch.object(policy, 'PKLA', self.pkla))
        self.enterContext(patch.object(policy, 'MODEM_PKLA', self.modem_pkla))
        self.enterContext(patch.object(policy, 'SYSTEM_BUS', self.bus_path))
        self.reload = self.enterContext(patch.object(policy.subprocess, 'run'))

    def write_legacy(self, name, suffix, original=XML):
        backup = name.with_name(name.name+suffix)
        backup.write_bytes(original)
        backup.chmod(0o640)
        name.write_bytes(policy.historical_xml(original))
        return backup, policy.read(backup)

    def test_exact_both_origins_restore_and_leave_backups(self):
        origins = [self.write_legacy(self.site, '.save'), self.write_legacy(self.vendor, '.kurasave', XML[:-1])]
        self.pkla.write_bytes(policy.PKLA_GRANT)
        policy.settle('check')
        self.assertIn(policy.XML_GRANT, self.site.read_bytes())
        policy.settle('apply')
        self.assertEqual(XML, self.site.read_bytes())
        self.assertEqual(XML[:-1], self.vendor.read_bytes())
        for path, old in origins:
            self.assertEqual(old, policy.read(path))
        self.assertFalse(self.pkla.exists())
        self.assertEqual(0o640, policy.read(self.site).mode)
        self.reload.assert_not_called()

    def test_legacy_with_a_site_edit_or_missing_backup_never_changes_either_path(self):
        self.write_legacy(self.site, '.save')
        self.vendor.write_bytes(policy.historical_xml(XML))
        before = policy.read(self.site)
        with self.assertRaisesRegex(ValueError, 'lacks an exact original backup'):
            policy.settle('apply')
        self.assertEqual(before, policy.read(self.site))
        self.write_legacy(self.vendor, '.kurasave')
        self.vendor.write_bytes(self.vendor.read_bytes().replace(b'original', b'changed'))
        with self.assertRaisesRegex(ValueError, 'lacks an exact original backup'):
            policy.settle('apply')
        self.assertEqual(before, policy.read(self.site))

    def test_unrelated_policy_keeps_its_identity(self):
        self.site.write_bytes(XML.replace(b'original', b'custom'))
        self.site.with_name(self.site.name+'.save').symlink_to('/nonexistent')
        before = policy.read(self.site)
        policy.settle('apply')
        self.assertEqual(before, policy.read(self.site))
        self.reload.assert_not_called()

    def test_exact_legacy_modem_grant_retires_and_unrelated_site_pkla_survives(self):
        self.modem_pkla.write_bytes(policy.MODEM_PKLA_GRANT)
        before = policy.read(self.modem_pkla)
        policy.settle('check')
        self.assertEqual(before, policy.read(self.modem_pkla))
        policy.settle('apply')
        self.assertFalse(self.modem_pkla.exists())
        self.modem_pkla.write_bytes(policy.MODEM_PKLA_GRANT.replace(b'kurad', b'operator'))
        before = policy.read(self.modem_pkla)
        policy.settle('apply')
        self.assertEqual(before, policy.read(self.modem_pkla))

    def test_ambiguous_modem_grant_fails_before_any_publication(self):
        self.write_legacy(self.site, '.save')
        self.modem_pkla.write_bytes(policy.MODEM_PKLA_GRANT + b'# Site modification\n')
        before = policy.read(self.site), policy.read(self.modem_pkla)
        for action in ('check', 'apply'):
            with self.assertRaisesRegex(ValueError, 'not the historical Kura grant'):
                policy.settle(action)
            self.assertEqual(before, (policy.read(self.site), policy.read(self.modem_pkla)))

    def test_completed_publication_resumes_reload_without_replacing_file(self):
        self.write_legacy(self.site, '.save')
        with socket.socket(socket.AF_UNIX) as stream:
            stream.bind(str(self.bus_path))
            self.reload.side_effect = subprocess.CalledProcessError(1, 'reload')
            with self.assertRaises(subprocess.SubprocessError):
                policy.settle('apply')
            published = policy.read(self.site)
            self.assertEqual(XML, published.data)
            self.reload.side_effect = None
            policy.settle('apply')
            self.assertEqual(published, policy.read(self.site))
            self.assertEqual(2, self.reload.call_count)
