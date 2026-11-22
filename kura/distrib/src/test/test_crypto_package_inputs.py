#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""A stale consumer must fail distribution preparation before an unusable deb."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location('prepare_key_service',
    Path(__file__).resolve().parents[2] / 'kura-core/prepare-key-service.py')
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class CryptoPackageInputsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.assembly = self.root / 'assembly'
        self.modules = self.root / 'modules'
        self.provider = self.bundle('org.eclipse.kura.api', export='2.0.0')
        self.consumer = self.bundle('org.eclipse.kura.http.server.manager', imports='[2.0,3.0)')

    def manifest(self, name, *, export=None, imports=None):
        rows = ['Manifest-Version: 1.0', 'Bundle-SymbolicName: ' + name]
        for header, version in (('Import-Package', imports), ('Export-Package', export)):
            if version is not None:
                rows.append(header + ': javax.net.ssl,org.eclipse.kura.crypto;\r\n version="' + version + '"')
        return ('\r\n'.join(rows) + '\r\n\r\n').encode()

    def bundle(self, name, **versions):
        source = self.modules / name / 'META-INF/MANIFEST.MF'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(self.manifest(name, **versions))
        target = self.assembly / 'plugins/4s' / (name + '.jar')
        target.parent.mkdir(parents=True, exist_ok=True)
        self.replace_jar(target, name, **versions)
        return target

    def replace_jar(self, target, name, **versions):
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF', self.manifest(name, **versions))

    def verify(self):
        return PREPARE.verify_crypto_imports(self.assembly, self.modules)

    def test_current_folded_contracts_are_accepted(self):
        self.assertEqual(2, len(self.verify()))

    def test_old_http_consumer_is_rejected(self):
        self.replace_jar(self.consumer, 'org.eclipse.kura.http.server.manager', imports='[1.2,2.0)')
        with self.assertRaisesRegex(RuntimeError, 'Stale crypto API build input.*http.server.manager'):
            self.verify()

    def test_stale_provider_is_rejected(self):
        self.replace_jar(self.provider, 'org.eclipse.kura.api', export='1.3.0')
        with self.assertRaisesRegex(RuntimeError, 'Stale crypto API build input.*org.eclipse.kura.api'):
            self.verify()

    def test_missing_new_consumer_import_is_rejected(self):
        self.replace_jar(self.consumer, 'org.eclipse.kura.http.server.manager')
        with self.assertRaisesRegex(RuntimeError, 'Stale crypto API build input.*http.server.manager'):
            self.verify()

    def test_missing_current_source_contract_is_rejected(self):
        (self.modules / 'org.eclipse.kura.http.server.manager/META-INF/MANIFEST.MF').unlink()
        with self.assertRaisesRegex(RuntimeError, 'Missing handwritten crypto contract'):
            self.verify()

    def test_duplicate_provider_is_rejected(self):
        self.replace_jar(self.provider.with_name('duplicate.jar'), 'org.eclipse.kura.api', export='2.0.0')
        with self.assertRaisesRegex(RuntimeError, 'Duplicate crypto API build input'):
            self.verify()

    def test_incomplete_assembly_is_rejected(self):
        self.consumer.unlink()
        with self.assertRaisesRegex(RuntimeError, 'Incomplete crypto API build inputs'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
