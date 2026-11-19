# SPDX-License-Identifier: EPL-2.0
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

RESOURCES = Path(__file__).resolve().parents[1] / 'main/resources'
sys.path.insert(0, str(RESOURCES / 'unfiltered/pkg/bin'))
import kura_modem_cohort as cohort


class PackageAdmissionTest(unittest.TestCase):
    def test_unsettled_package_state_fails_closed(self):
        with patch.object(cohort, 'dpkg', return_value=subprocess.CompletedProcess(
                [], 0, stdout=b'unpacked\n', stderr=b'')):
            with self.assertRaisesRegex(ValueError, 'not in a settled state'):
                cohort.active_provider()

    def test_main_drops_module_capability_and_checks_provider(self):
        unit = (RESOURCES / 'filtered/pkg/install/kura.service').read_text()
        self.assertNotIn('cap_sys_module', unit.lower())
        self.assertIn('ExecStartPre=/usr/bin/python3 -I -B INSTALL_DIR/kura/bin/kura_modem_cohort.py', unit)


@unittest.skipUnless(os.geteuid() == 0, 'exercise the installed file rules as Root')
class ProviderFingerprintTest(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/run')))
        self.installation = root / 'kura_6.0.0_linux'
        self.installation.mkdir()
        self.home = root / 'kura'
        self.home.symlink_to(self.installation.name)
        self.enterContext(patch.object(cohort, 'HOME', self.home))
        self.package = 'kura-networking'
        folder = self.home / 'siblings' / cohort.PROVIDERS[self.package] / '4'
        folder.mkdir(parents=True)
        self.provider = folder / 'org.eclipse.kura.linux.net-6.0.0.jar'
        self.proof = root / 'modem-provider.json'
        self.owner = self.enterContext(patch.object(cohort, 'require_ownership'))

    def test_provider_hash_binds_the_only_jar(self):
        self.provider.write_bytes(b'built modem bundle')
        self.proof.write_text(json.dumps(dict(
            schema=1, modemProtocol=1, provider=self.provider.name,
            sha256=hashlib.sha256(self.provider.read_bytes()).hexdigest())))
        args = (self.package, self.provider.parent, self.proof)
        cohort.check_provider(*args, {self.provider})
        self.owner.assert_any_call(self.provider, self.package)
        with self.assertRaisesRegex(ValueError, 'one paired'):
            cohort.check_provider(*args, {self.provider, self.provider.with_name('old.jar')})
        self.provider.write_bytes(b'other modem bundle')
        with self.assertRaisesRegex(ValueError, 'fingerprint changed'):
            cohort.check_provider(*args, {self.provider})

    def test_core_alone_and_orphan_provider(self):
        with patch.object(cohort, 'active_provider', return_value=None):
            cohort.check()
            self.provider.write_bytes(b'detached modem bundle')
            with self.assertRaisesRegex(ValueError, 'Detached Networking'):
                cohort.check()
