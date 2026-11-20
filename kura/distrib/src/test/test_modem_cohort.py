# SPDX-License-Identifier: EPL-2.0
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
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

    def test_only_native_core_preinst_can_consider_a_replacement_archive(self):
        missing = cohort.MissingProviderProof(
            'kura-networking', Path('/usr/share/kura-networking/modem-provider.json'), 'modemProtocol')
        with patch.dict(os.environ, {cohort.COHORT_HASH: 'a' * 64}, clear=True), \
                patch.object(cohort, 'check', side_effect=missing) as installed, \
                patch.object(cohort, 'current_dpkg_archives') as archives:
            with self.assertRaises(cohort.MissingProviderProof):
                cohort.check_package_upgrade('1', '2')
            installed.assert_called_once_with()
            archives.assert_not_called()

    def test_missing_file_claimed_by_installed_package_does_not_admit_cohort(self):
        path = Path('/usr/share/kura-networking/modem-provider.json')

        def check(on_missing):
            on_missing(cohort.MissingProviderProof('kura-networking', path, 'modemProtocol'))

        environment = {
            cohort.COHORT_HASH: 'a' * 64, 'DPKG_MAINTSCRIPT_PACKAGE': 'kura-core',
            'DPKG_MAINTSCRIPT_NAME': 'preinst', 'DPKG_ADMINDIR': '/var/lib/dpkg'
        }
        listed = subprocess.CompletedProcess([], 0, stdout=os.fsencode(path) + b'\n', stderr=b'')
        with patch.dict(os.environ, environment, clear=True), patch.object(cohort, 'check', check), \
                patch.object(cohort, 'dpkg', return_value=listed), \
                patch.object(cohort, 'current_dpkg_archives') as archives:
            with self.assertRaises(cohort.MissingProviderProof):
                cohort.check_package_upgrade('1', '2')
            archives.assert_not_called()


class ArchiveProofTest(unittest.TestCase):
    def setUp(self):
        package = 'kura-networking'
        prefix = cohort.HOME / 'siblings' / 'networking'
        names = {
            cohort.MODEM_NAME: 'org.eclipse.kura.linux.net-6.0.0.jar',
            cohort.BIND_NAME: 'org.eclipse.kura.linux.systemd.provider-6.0.0.jar',
            cohort.NM_NAME: 'org.eclipse.kura.nm-2.0.0.jar',
        }
        rules = b'synthetic Networking policy'
        rule_digest = hashlib.sha256(rules).hexdigest()
        self.enterContext(patch.object(cohort, 'NETWORKING_LOCATION_POLICY_SHA256', rule_digest))
        self.members = {cohort.NETWORKING_RULE: rules}
        for tier, filename, pattern, protocol, policy in cohort.provider_contracts(package):
            jar = prefix / tier / names[pattern]
            content = os.fsencode(jar.name)
            self.members[jar] = content
            proof = {'schema': 1, protocol: 1, 'provider': jar.name, 'sha256': hashlib.sha256(content).hexdigest()}
            if policy is not None:
                proof['policySha256'] = rule_digest
            self.members[cohort.SHARE / package / filename] = json.dumps(proof).encode()

    def tar_stream(self):
        result = io.BytesIO()
        with tarfile.open(mode='w', fileobj=result) as archive:
            for path, data in self.members.items():
                entry = tarfile.TarInfo('.' + str(path))
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        result.seek(0)
        return result

    def test_exact_cohort_is_accepted_and_replaced_bundle_is_refused(self):
        cohort.read_networking_assets(self.tar_stream())
        jar = cohort.HOME / 'siblings/networking/5s/org.eclipse.kura.nm-2.0.0.jar'
        self.members[jar] = b'different bundle'
        with self.assertRaisesRegex(ValueError, 'unpaired dhcpNmProtocol provider'):
            cohort.read_networking_assets(self.tar_stream())

    def test_archive_with_only_some_of_the_protocols_is_refused(self):
        self.members.pop(cohort.SHARE / 'kura-networking/modem-location-provider.json')
        with self.assertRaisesRegex(ValueError, 'invalid for modemLocationProtocol'):
            cohort.read_networking_assets(self.tar_stream())


@unittest.skipUnless(os.geteuid() == 0, 'exercise the installed file rules as Root')
class ProviderFingerprintTest(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/run')))
        self.installation = root / 'kura_6.0.0_linux'
        self.installation.mkdir()
        self.home = root / 'kura'
        self.home.symlink_to(self.installation.name)
        self.enterContext(patch.object(cohort, 'HOME', self.home))
        self.share = root / 'usr-share'
        self.enterContext(patch.object(cohort, 'SHARE', self.share))
        self.package = 'kura-networking'
        folder = self.home / 'siblings' / cohort.PROVIDERS[self.package] / '4'
        folder.mkdir(parents=True)
        self.provider = folder / 'org.eclipse.kura.linux.net-6.0.0.jar'
        self.proof = self.share / self.package / 'modem-provider.json'
        self.proof.parent.mkdir(parents=True)
        self.owner = self.enterContext(patch.object(cohort, 'require_ownership'))
        self.rule = root / '52-kura-networking.rules'
        self.enterContext(patch.object(cohort, 'NETWORKING_RULE', self.rule))

    def test_provider_hash_binds_the_only_jar(self):
        self.provider.write_bytes(b'built modem bundle')
        self.proof.write_text(json.dumps(dict(
            schema=1, modemProtocol=1, provider=self.provider.name,
            sha256=hashlib.sha256(self.provider.read_bytes()).hexdigest())))
        args = (self.package, self.provider.parent, self.proof)
        cohort.check_provider(*args, {self.provider}, cohort.MODEM_NAME, 'modemProtocol')
        self.owner.assert_any_call(self.provider, self.package)
        with self.assertRaisesRegex(ValueError, 'one paired'):
            cohort.check_provider(*args, {self.provider, self.provider.with_name('old.jar')},
                                  cohort.MODEM_NAME, 'modemProtocol')
        self.provider.write_bytes(b'other modem bundle')
        with self.assertRaisesRegex(ValueError, 'fingerprint changed'):
            cohort.check_provider(*args, {self.provider}, cohort.MODEM_NAME, 'modemProtocol')

    def test_core_alone_and_orphan_provider(self):
        with patch.object(cohort, 'active_provider', return_value=None):
            cohort.check()
            self.provider.write_bytes(b'detached modem bundle')
            with self.assertRaisesRegex(ValueError, 'Detached Networking'):
                cohort.check()

    def test_networking_needs_the_exact_typed_bind_provider(self):
        self.provider.write_bytes(b'packaged modem bundle')
        self.proof.write_text(json.dumps(dict(
            schema=1, modemProtocol=1, provider=self.provider.name,
            sha256=hashlib.sha256(self.provider.read_bytes()).hexdigest())))
        bind_jar = self.provider.with_name('org.eclipse.kura.linux.systemd.provider-6.0.0.jar')
        bind_jar.write_bytes(b'packaged DNS bundle')
        bind_proof = self.proof.with_name('bind-provider.json')
        with patch.object(cohort, 'active_provider', return_value=self.package):
            with self.assertRaisesRegex(ValueError, 'Missing paired .* bindProtocol'):
                cohort.check()
            bind_proof.write_text(json.dumps(dict(
                schema=1, bindProtocol=1, provider=bind_jar.name,
                sha256=hashlib.sha256(bind_jar.read_bytes()).hexdigest())))
            with self.assertRaisesRegex(ValueError, 'Missing paired .* bindConfigurationProtocol'):
                cohort.check()
            bind_proof.with_name('bind-config-provider.json').write_text(json.dumps(dict(
                schema=1, bindConfigurationProtocol=1, provider=bind_jar.name,
                sha256=hashlib.sha256(bind_jar.read_bytes()).hexdigest())))
            with self.assertRaisesRegex(ValueError, 'Missing paired .* bindOutcomeProtocol'):
                cohort.check()
            bind_proof.with_name('bind-outcome-provider.json').write_text(json.dumps(dict(
                schema=1, bindOutcomeProtocol=1, provider=bind_jar.name,
                sha256=hashlib.sha256(bind_jar.read_bytes()).hexdigest())))
            with self.assertRaisesRegex(ValueError, 'Missing paired .* dhcpProtocol'):
                cohort.check()
            self.proof.with_name('dhcp-provider.json').write_text(json.dumps(dict(
                schema=1, dhcpProtocol=1, provider=self.provider.name,
                sha256=hashlib.sha256(self.provider.read_bytes()).hexdigest())))
            with self.assertRaisesRegex(ValueError, 'Missing paired .* dhcpNmProtocol'):
                cohort.check()
            nm_directory = self.provider.parent.with_name('5s')
            nm_directory.mkdir()
            nm_name = nm_directory / 'org.eclipse.kura.nm-2.0.0.jar'
            nm_name.write_bytes(b'packaged NM DHCP monitor')
            self.proof.with_name('dhcp-nm-provider.json').write_text(json.dumps(dict(
                schema=1, dhcpNmProtocol=1, provider=nm_name.name,
                sha256=hashlib.sha256(nm_name.read_bytes()).hexdigest())))
            with self.assertRaisesRegex(ValueError, 'Missing paired .* wifiNmProtocol'):
                cohort.check()
            self.rule.write_bytes(b'known packaged Networking policy')
            wifi = dict(schema=1, wifiNmProtocol=1, provider=nm_name.name,
                        sha256=hashlib.sha256(nm_name.read_bytes()).hexdigest(),
                        policySha256=hashlib.sha256(self.rule.read_bytes()).hexdigest())
            wifi_proof = self.proof.with_name('wifi-nm-provider.json')
            wifi_proof.write_text(json.dumps(wifi))
            with self.assertRaisesRegex(ValueError, 'Missing paired .* modemResetProtocol'):
                cohort.check()
            self.proof.with_name('modem-reset-provider.json').write_text(json.dumps(dict(
                schema=1, modemResetProtocol=1, provider=nm_name.name, sha256=wifi['sha256'])))
            with self.assertRaisesRegex(ValueError, 'Missing paired .* modemLocationProtocol'):
                cohort.check()
            self.proof.with_name('modem-location-provider.json').write_text(json.dumps(dict(
                schema=1, modemLocationProtocol=1, provider=nm_name.name, sha256=wifi['sha256'])))
            with self.assertRaisesRegex(ValueError, 'paired read-only ModemManager policy'):
                cohort.check()
            self.enterContext(patch.object(cohort, 'NETWORKING_LOCATION_POLICY_SHA256', wifi['policySha256']))
            cohort.check()
            self.owner.assert_any_call(self.rule, self.package)
            self.rule.write_bytes(b'foreign policy file')
            with self.assertRaisesRegex(ValueError, 'Unpaired Networking Wi-Fi policy'):
                cohort.check()
            self.owner.assert_any_call(nm_name, self.package)
            self.owner.assert_any_call(bind_jar, self.package)
            bind_jar.write_bytes(b'different DNS bundle')
            with self.assertRaisesRegex(ValueError, 'fingerprint changed .* bindProtocol'):
                cohort.check()
