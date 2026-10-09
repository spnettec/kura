import tempfile
import unittest
import zipfile
from pathlib import Path
from bundle_audit import inspect, compare


class BundleAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def jar(self, name, extra='', resources=None):
        path = Path(self.temp.name) / name
        with zipfile.ZipFile(path, 'w') as jar:
            jar.writestr('META-INF/MANIFEST.MF',
                         'Manifest-Version: 1.0\r\nBundle-SymbolicName: test.bundle\r\n'
                         'Bundle-Version: 1.2.3.baseline\r\n' + extra + '\r\n')
            for key, value in (resources or {}).items():
                jar.writestr(key, value)
        return path

    def test_missing_embedded_jar_fails(self):
        result = inspect(self.jar('bad.jar', 'Bundle-ClassPath: .,lib/missing.jar\r\n'))
        self.assertEqual(['Missing Bundle-ClassPath entry: lib/missing.jar'], result['errors'])

    def test_missing_ds_descriptor_fails(self):
        result = inspect(self.jar('bad.jar', 'Service-Component: OSGI-INF/*.xml\r\n'))
        self.assertEqual(['Missing Service-Component descriptor: OSGI-INF/*.xml'], result['errors'])

    def test_embedded_jar_and_wildcard_ds_are_accepted(self):
        result = inspect(self.jar('valid.jar', 'Bundle-ClassPath: .,lib/a.jar\r\nService-Component: OSGI-INF/*.xml\r\n',
                                  {'lib/a.jar': b'data', 'OSGI-INF/a.xml': '<component/>'}))
        self.assertEqual([], result['errors'])

    def test_import_range_change_fails(self):
        old = inspect(self.jar('old.jar', 'Import-Package: api;version="[1,2)"\r\n'))
        new = inspect(self.jar('new.jar', 'Import-Package: api;version="[2,3)"\r\n'))
        self.assertIn('Import-Package', compare(old, new)['headers'])

    def test_license_and_embedded_bytes_are_protected(self):
        old = inspect(self.jar('old.jar', resources={'about.html': 'license', 'lib/a.jar': b'old'}))
        new = inspect(self.jar('new.jar', resources={'lib/a.jar': b'new'}))
        self.assertEqual({'about.html', 'lib/a.jar'}, set(compare(old, new)['resources']))

    def test_ecj_javac_bytecode_difference_is_separate_from_resources(self):
        old = inspect(self.jar('old.jar', resources={'A.class': b'ecj'}))
        new = inspect(self.jar('new.jar', resources={'A.class': b'javac'}))
        self.assertEqual({}, compare(old, new)['resources'])


if __name__ == '__main__':
    unittest.main()
