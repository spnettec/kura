#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Real classpath generation in a new disposable Root/Linux filesystem."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin/gen_config_ini.sh'
SHARE = Path('/usr/share/kura-management-agent')


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0 and Path('/.dockerenv').exists(),
                     'Requires a fresh disposable Root/Linux filesystem')
class OptionalAgentAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert not SHARE.exists() and not Path('/opt/eclipse').exists()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir='/run', prefix='optional-adapter-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.loader = self.root / 'gen_config_ini.sh'
        shutil.copyfile(SOURCE, self.loader)
        self.template = self.root / 'template.ini'
        self.template.write_text('osgi.bundles=__OSGI_BUNDLES__\n')
        self.plugins = self.root / 'plugins/3s'
        self.plugins.mkdir(parents=True)
        (self.plugins / 'core.jar').write_bytes(b'test classpath placeholder, not executed')
        self.siblings = self.root / 'siblings'
        self.siblings.mkdir()
        self.addCleanup(lambda: shutil.rmtree(SHARE) if SHARE.exists() else None)

    def prepare_adapter(self, version=1):
        (SHARE / 'java').mkdir(parents=True)
        (SHARE / ('package-v' + str(version))).write_text('kura-management-agent-v' + str(version) + '\n')
        jar = SHARE / 'java/org.eclipse.kura.management.bridge.jar'
        with zipfile.ZipFile(jar, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF', 'Bundle-SymbolicName: org.eclipse.kura.management.bridge\nBundle-Version: 1.0.0.test\n\n')
            archive.writestr('org/eclipse/kura/management/bridge/ManagementBridge.class', b'classpath fixture; not JVM execution')
        self.metadata = dict(symbolicName='org.eclipse.kura.management.bridge', version='1.0.0.test',
            path=str(jar), sha256=hashlib.sha256(jar.read_bytes()).hexdigest(), coreLoaderProtocol=1,
            coreLoaderSha256=hashlib.sha256(self.loader.read_bytes()).hexdigest())
        self.write_metadata()
        return jar

    def write_metadata(self):
        (SHARE / 'java-bridge.json').write_text(json.dumps(self.metadata))

    def run_loader(self):
        result = subprocess.run(['sh', str(self.loader), str(self.template), str(self.plugins.parent), str(self.siblings)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('core.jar', result.stdout)
        return result

    def test_core_classpath_does_not_depend_on_an_agent_package(self):
        self.assertNotIn('/usr/share/kura-management-agent', self.run_loader().stdout)

    def test_exact_paired_root_adapter_is_loaded_at_level_five(self):
        jar = self.prepare_adapter()
        result = self.run_loader()
        self.assertIn(str(jar), result.stdout)
        self.assertIn('@5', result.stdout)

    def test_native_package_loads_only_the_same_exact_root_pair(self):
        jar = self.prepare_adapter(2)
        self.assertIn(str(jar), self.run_loader().stdout)
        self.metadata['coreLoaderSha256'] = '0' * 64
        self.write_metadata()
        self.assertNotIn(str(jar), self.run_loader().stdout)

    def test_native_marker_never_falls_back_to_a_legacy_marker(self):
        jar = self.prepare_adapter(2)
        (SHARE / 'package-v1').write_text('kura-management-agent-v1\n')
        result = self.run_loader()
        self.assertNotIn(str(jar), result.stdout)
        self.assertIn('optional agent adapter rejected', result.stderr)

    def test_invalid_or_dangling_native_marker_keeps_core_independent(self):
        jar = self.prepare_adapter(2)
        marker = SHARE / 'package-v2'
        marker.write_text('kura-management-agent-v1\n')
        self.assertNotIn(str(jar), self.run_loader().stdout)
        marker.unlink()
        marker.symlink_to('/does-not-exist/native-marker')
        result = self.run_loader()
        self.assertNotIn(str(jar), result.stdout)
        self.assertIn('optional agent adapter rejected', result.stderr)

    def test_native_root_group_and_exact_modes_are_required(self):
        jar = self.prepare_adapter(2)
        for path in (SHARE / 'package-v2', SHARE / 'java-bridge.json', jar):
            path.chmod(0o640)
            self.assertNotIn(str(jar), self.run_loader().stdout)
            path.chmod(0o644)
            os.chown(path, 0, 65534)
            self.assertNotIn(str(jar), self.run_loader().stdout)
            os.chown(path, 0, 0)
        self.assertIn(str(jar), self.run_loader().stdout)

    def test_payload_or_loader_drift_is_rejected_while_core_continues(self):
        jar = self.prepare_adapter()
        for field in ('sha256', 'coreLoaderSha256'):
            original = self.metadata[field]
            self.metadata[field] = '0' * 64
            self.write_metadata()
            result = self.run_loader()
            self.assertNotIn(str(jar), result.stdout)
            self.assertIn('optional agent adapter rejected', result.stderr)
            self.metadata[field] = original

    def test_writable_linked_or_wrong_osgi_payload_is_rejected(self):
        jar = self.prepare_adapter()
        jar.chmod(0o666)
        self.assertNotIn(str(jar), self.run_loader().stdout)
        jar.chmod(0o644)
        os.link(jar, SHARE / 'second-link')
        self.assertNotIn(str(jar), self.run_loader().stdout)
        (SHARE / 'second-link').unlink()
        raw = jar.read_bytes()
        jar.unlink()
        outside = self.root / 'outside.jar'
        outside.write_bytes(raw)
        jar.symlink_to(outside)
        self.assertNotIn(str(jar), self.run_loader().stdout)
        jar.unlink()
        with zipfile.ZipFile(jar, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF', 'Bundle-SymbolicName: wrong\nBundle-Version: 1.0.0.test\n\n')
        self.metadata['sha256'] = hashlib.sha256(jar.read_bytes()).hexdigest()
        self.write_metadata()
        self.assertNotIn(str(jar), self.run_loader().stdout)

    def test_legacy_directory_never_bypasses_rejected_pairing(self):
        jar = self.prepare_adapter()
        legacy = self.siblings / 'management-agent/5s'
        legacy.mkdir(parents=True)
        shutil.copyfile(jar, legacy / jar.name)
        self.metadata['coreLoaderSha256'] = '0' * 64
        self.write_metadata()
        result = self.run_loader()
        self.assertNotIn(str(jar), result.stdout)
        self.assertNotIn(str(legacy), result.stdout)

    def test_duplicate_metadata_and_unexpected_paths_are_not_accepted(self):
        jar = self.prepare_adapter()
        self.metadata['path'] = '/untrusted/adapter.jar'
        self.write_metadata()
        self.assertNotIn(str(jar), self.run_loader().stdout)
        self.metadata['path'] = str(jar)
        raw = json.dumps(self.metadata)
        (SHARE / 'java-bridge.json').write_text(raw[:-1] + ',"coreLoaderProtocol":1}')
        self.assertNotIn(str(jar), self.run_loader().stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
