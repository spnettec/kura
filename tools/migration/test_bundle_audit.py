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

    def test_named_classes_cannot_silently_disappear(self):
        old = inspect(self.jar('old.jar', resources={'Api.class': b'ecj', 'Api$Builder.class': b'ecj'}))
        new = inspect(self.jar('new.jar', resources={'Api.class': b'javac'}))
        self.assertEqual(['Api$Builder.class'], compare(old, new)['classes']['removed'])

    def test_header_order_spacing_and_default_classpath_are_semantic(self):
        old = inspect(self.jar('old.jar', 'Import-Package: a; version="[1,2)",b\r\nBundle-ClassPath: .\r\n'))
        new = inspect(self.jar('new.jar', 'Import-Package: b,a;version="[1,2)"\r\n'))
        self.assertEqual({}, compare(old, new)['headers'])

    def test_attribute_order_and_token_quoting_preserve_capabilities(self):
        old = inspect(self.jar('old.jar', 'Import-Package: a;version="1.0";resolution:=optional\r\n'
                               'Provide-Capability: osgi.serviceloader;osgi.serviceloader=javax.script.ScriptEngineFactory\r\n'))
        new = inspect(self.jar('new.jar', 'Import-Package: a;resolution:=optional;version="1.0"\r\n'
                               'Provide-Capability: osgi.serviceloader;osgi.serviceloader="javax.script.ScriptEngineFactory"\r\n'))
        self.assertEqual({}, compare(old, new)['headers'])

    def test_optional_cannot_replace_mandatory_import(self):
        old = inspect(self.jar('old.jar', 'Import-Package: a;version="1.0"\r\n'))
        new = inspect(self.jar('new.jar', 'Import-Package: a;version="1.0";resolution:=optional\r\n'))
        self.assertIn('Import-Package', compare(old, new)['headers'])

    def test_resource_source_paths_may_change_but_packaged_bytes_may_not(self):
        old = inspect(self.jar('old.jar', 'Include-Resource: lib/a.jar=/old/cache/a.jar\r\n',
                               {'lib/a.jar': b'old'}))
        new = inspect(self.jar('new.jar', 'Include-Resource: lib/a.jar=/new/cache/a.jar\r\n',
                               {'lib/a.jar': b'new'}))
        self.assertEqual({}, compare(old, new)['headers'])
        self.assertIn('lib/a.jar', compare(old, new)['resources'])


if __name__ == '__main__':
    unittest.main()
