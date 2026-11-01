"""Verify owner selection, isolated outputs and preservation of existing runtime/data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

import generate_pom
import network_profiles
import runtime


class NetworkProfileTest(unittest.TestCase):
    def test_explicit_netplan_selection_reserves_owner_and_keeps_all_common_bundles(self):
        base, properties = network_profiles.profile_spec('none')
        selected, selected_properties = network_profiles.profile_spec('netplan')
        self.assertEqual({}, properties)
        self.assertEqual(base['bundles'], selected['bundles'][:len(base['bundles'])])
        self.assertEqual({'org.eclipse.kura.management.bridge', 'org.eclipse.kura.netplan'},
                         {b['symbolicName'] for b in selected['bundles'][len(base['bundles']):]})
        self.assertEqual('netplan', selected_properties['kura.networking.provider'])
        self.assertEqual('org.eclipse.kura.net.admin.NetworkConfigurationService',
                         selected_properties['kura.configuration.external.pids'])

    def test_conflicting_writer_is_rejected_instead_of_silently_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copy2(network_profiles.ROOT / 'network-providers.json', root)
            for name in ['org.eclipse.kura.nm', 'org.eclipse.kura.linux.net', 'org.eclipse.kura.net.admin.firewall',
                         'org.eclipse.kura.network.threat.manager']:
                (root / 'runtime.json').write_text(json.dumps({'bundles': [{'symbolicName': name}]}))
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                    network_profiles.profile_spec('netplan', root)

    def test_unknown_provider_and_duplicate_bundle_fail(self):
        with self.assertRaisesRegex(ValueError, 'Supported network providers'):
            network_profiles.profile_spec('auto-enable')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'runtime.json').write_text(json.dumps({'bundles': [{'symbolicName': 'duplicate'}] * 2}))
            with self.assertRaisesRegex(ValueError, 'Duplicate symbolic'):
                network_profiles.profile_spec('none', root)

    def test_maven_collection_has_explicit_artifacts_and_reactor_dependencies_for_both_variants(self):
        root = ET.fromstring(generate_pom.pom())
        ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
        dependencies = {d.findtext('m:artifactId', namespaces=ns): d
                        for d in root.findall('./m:dependencies/m:dependency', ns)}
        artifacts = {d.findtext('m:artifactId', namespaces=ns) for d in root.findall('.//m:artifactItem', ns)}
        for name in ['org.eclipse.kura.management.bridge', 'org.eclipse.kura.netplan']:
            self.assertIn(name, artifacts)
            self.assertEqual('pom', dependencies[name].findtext('m:type', namespaces=ns))
            self.assertEqual('*', dependencies[name].findtext('m:exclusions/m:exclusion/m:artifactId', namespaces=ns))
        self.assertIn('--network-provider', [n.text for n in root.findall('.//m:argument', ns)])
        base, _ = network_profiles.profile_spec('none')
        self.assertNotIn('org.eclipse.kura.netplan', {b['symbolicName'] for b in base['bundles']})

    def test_clean_guard_protects_every_variant_but_separate_assembly_does_not_block(self):
        output = f'12345 java -jar {runtime.runtime_directory("netplan")}/launcher.jar\n'
        with patch('runtime.subprocess.run', return_value=subprocess.CompletedProcess([], 0, output)):
            with self.assertRaisesRegex(ValueError, 'JVM 12345'):
                runtime.guard()
            runtime.guard('macos', 'none')
            with self.assertRaisesRegex(ValueError, 'JVM 12345'):
                runtime.guard('macos', 'netplan')

    def test_default_home_and_output_are_distinct_between_variants(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertNotEqual(runtime.data_home('macos'), runtime.data_home('macos', 'netplan'))
        self.assertNotEqual(runtime.runtime_directory(), runtime.runtime_directory('netplan'))

    def test_socket_and_peer_validation_rejects_relative_paths_or_arg_injection(self):
        for env in [{'KURA_MANAGEMENT_SOCKET': 'relative.sock'},
                    {'KURA_MANAGEMENT_SOCKET': '/run/control.sock\n-Dother=true'},
                    {'KURA_MANAGEMENT_AGENT_USER': 'root\n-Dother=true'}]:
            with self.subTest(env=env), patch.dict(os.environ, env), self.assertRaises(ValueError):
                runtime.bridge_options('netplan')

    def test_real_assembly_isolates_output_and_never_rewrites_existing_user_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'module'
            root.mkdir()
            shutil.copytree(runtime.ROOT / 'src/main/resources', root / 'src/main/resources')
            shutil.copy2(network_profiles.ROOT / 'network-providers.json', root)
            base = {'bundles': [{'symbolicName': 'base', 'coordinates': 'g:base:1', 'startLevel': 5, 'start': True}],
                    'framework': 'g:framework:1', 'launcher': 'g:launcher:1',
                    'defaultStartLevel': 5, 'frameworkStartLevel': 6}
            (root / 'runtime.json').write_text(json.dumps(base))
            cache = root / 'target/bundle-cache'
            cache.mkdir(parents=True)
            selected, _ = network_profiles.profile_spec('netplan', root)
            for bundle in selected['bundles'] + [{'coordinates': 'g:framework:1', 'symbolicName': 'framework'},
                                                {'coordinates': 'g:launcher:1', 'symbolicName': 'launcher'}]:
                with zipfile.ZipFile(cache / generate_pom.filename(bundle['coordinates']), 'w') as jar:
                    jar.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\n'
                                 f'Bundle-SymbolicName: {bundle["symbolicName"]}\nBundle-Version: 1.0.0\n\n')
            legacy = root / 'target/runtime'
            legacy.mkdir()
            (legacy / 'sentinel').write_text('existing runtime')
            home = Path(temp) / 'persistent'
            runtime.initialize(home, runtime.ports())
            seed = home / 'user/snapshots/snapshot_0.xml'
            key = home / 'user/security/private.key'
            key.write_bytes(b'existing private key')
            original = seed.read_bytes()
            with patch.object(runtime, 'ROOT', root), patch.object(runtime, 'RUNTIME', legacy), \
                    patch.object(runtime, 'guard'), patch.object(runtime, 'check_ports'), \
                    patch.dict(os.environ, {'KURA_DEV_HOME': str(home), 'KURA_MANAGEMENT_SOCKET': '/run/test/control.sock',
                                            'KURA_MANAGEMENT_AGENT_USER': 'root'}, clear=True):
                runtime.assemble('linux', 'netplan')
                directory = runtime.runtime_directory('netplan')
                self.assertIn('kura.networking.provider=netplan', (directory / 'configuration/config.ini').read_text())
                self.assertIn('kura.have.net.admin=true', (directory / 'configuration/kura.properties').read_text())
                self.assertIn('-Dkura.management.socket=/run/test/control.sock', (directory / 'jvm.args').read_text())
                inventory = json.loads((directory / 'inventory.json').read_text())
                self.assertEqual({'base', 'org.eclipse.kura.management.bridge', 'org.eclipse.kura.netplan', 'framework', 'launcher'},
                                 {b['symbolicName'] for b in inventory})
                self.assertEqual('netplan', json.loads((directory / 'launch.json').read_text())['networkProvider'])
                configuration = directory / 'configuration/config.ini'
                configuration.write_text(configuration.read_text().replace('kura.configuration.external.pids=', 'missing='))
                with self.assertRaisesRegex(ValueError, 'owner reservation'):
                    runtime.prepare('linux', 'netplan')
            self.assertEqual('existing runtime', (legacy / 'sentinel').read_text())
            self.assertEqual(original, seed.read_bytes())
            self.assertEqual(b'existing private key', key.read_bytes())


if __name__ == '__main__':
    unittest.main()
