#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Package contracts; synthetic class headers are not runtime/OSGi proof."""
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[1] / 'main/resources'
sys.path.insert(0, str(SOURCE / 'unfiltered/pkg/bin'))
import kura_clock_broker as broker


class ClockPackageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def assembly(self, capability=True, client=True):
        home = self.root / 'package'; home.mkdir()
        for name in broker.HELPERS:
            target = home / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / 'unfiltered/pkg' / name, target)
        for name in broker.UNITS:
            target = home / 'libexec/clock-broker' / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / 'unfiltered/pkg/install' / name, target)
        jar = home / 'plugins/4/org.eclipse.kura.linux.clock-2.0.0-SNAPSHOT.jar'
        jar.parent.mkdir(parents=True)
        manifest = 'Manifest-Version: 1.0\nBundle-SymbolicName: org.eclipse.kura.linux.clock\n'
        if capability:
            manifest += 'Provide-Capability: kura.clock.privilege;version:Version=1.0.0\n'
        with zipfile.ZipFile(jar, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF', manifest + '\n')
            if client:
                archive.writestr('org/eclipse/kura/linux/clock/ClockPrivilegeClient.class', b'\xca\xfe\xba\xbe\0\0\0A')
        return home

    def test_manifest_binds_all_helpers_units_and_clock_consumer(self):
        home = self.assembly(); value = broker.package_cohort(home)
        self.assertEqual(8, len(value['files']))
        self.assertEqual(set(broker.HELPERS), {name for name in value['files'] if name.startswith('bin/')})
        self.assertEqual(['adjust-realtime', 'sync-rtc'], value['actions'])
        self.assertEqual(0o644, stat.S_IMODE((home / broker.COHORT).stat().st_mode))

    def test_main_has_no_system_clock_capability(self):
        raw = (SOURCE / 'filtered/pkg/install/kura.service').read_text()
        for key in ('CapabilityBoundingSet', 'AmbientCapabilities'):
            with self.subTest(key=key):
                values = [line.partition('=')[2].split() for line in raw.splitlines() if line.startswith(key + '=')]
                self.assertEqual(1, len(values))
                self.assertNotIn('cap_sys_time', [cap.lower() for cap in values[0]])

    def test_cached_old_clock_bundle_cannot_be_paired(self):
        for capability, client in ((False, True), (True, False)):
            home = self.assembly(capability, client)
            with self.assertRaises((broker.Refused, KeyError)):
                broker.package_cohort(home)
            self.assertFalse((home / broker.COHORT).exists())
            # Only this owned synthetic build input is removed between cases.
            shutil.rmtree(home)

    def test_missing_or_linked_helper_never_creates_pairing_manifest(self):
        home = self.assembly(); path = home / broker.HELPERS[0]
        original = path.read_bytes(); path.unlink(); target = self.root / 'outside-code'; target.write_bytes(original)
        path.symlink_to(target)
        with self.assertRaises(broker.Refused):
            broker.package_cohort(home)
        self.assertFalse((home / broker.COHORT).exists())

    def test_actor_account_is_separate_from_key_control_and_has_only_clock_capability(self):
        raw = (SOURCE / 'unfiltered/pkg/install/kura-clock-broker.service').read_text()
        self.assertIn('\nUser=kura-clock\n', raw)
        self.assertIn('\nGroup=kura-clock\n', raw)
        self.assertNotIn('kura-key-control', raw)
        self.assertIn('\nCapabilityBoundingSet=CAP_SYS_TIME\n', raw)
        self.assertIn('\nAmbientCapabilities=CAP_SYS_TIME\n', raw)
        self.assertIn('\nNoNewPrivileges=true\n', raw)
        self.assertIn('\nPrivateDevices=true\n', raw)
        self.assertIn('\nDeviceAllow=char-rtc r\n', raw)
        self.assertIn('\nBindReadOnlyPaths=-/dev/.kura-clock-rtc:/dev/kura-clock-rtc\n', raw)
        self.assertIn('\nWants=' + broker.RTC_UNIT + '\n', raw)
        self.assertIn('-/opt/eclipse/kura', raw)
        projection = (SOURCE / 'unfiltered/pkg/install' / broker.RTC_UNIT).read_text()
        self.assertIn('\nCapabilityBoundingSet=CAP_MKNOD CAP_CHOWN\n', projection)
        self.assertIn('\nDevicePolicy=closed\n', projection)
        self.assertIn('\nDeviceAllow=char-rtc m\n', projection)

    def prefix(self, path):
        raw = (SOURCE / 'variants/linux/unfiltered/deb/control/postinst').read_text()
        start = raw.index('    # The credential workflow uses umask 077.')
        end = raw.index('    #install KURA files', start)
        script = 'umask 077\ncheck_prefix() {\n' + raw[start:end] + '\n}\ncheck_prefix\n'
        environment = os.environ.copy(); environment['INSTALL_DIR'] = str(path); environment['LOG'] = str(self.root / 'install.log')
        return subprocess.run(['/bin/bash', '-c', script], env=environment, capture_output=True, text=True)

    def test_new_code_prefix_is_traversable_even_under_private_umask(self):
        path = self.root / 'new-code-prefix'
        result = self.prefix(path)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(0o755, stat.S_IMODE(path.stat().st_mode))

    def test_existing_private_prefix_is_not_chmod_or_chowned(self):
        path = self.root / 'existing-prefix'; path.mkdir(mode=0o700)
        before = path.stat(); result = self.prefix(path); after = path.stat()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual((before.st_ino, before.st_uid, before.st_gid, before.st_mode, before.st_mtime_ns, before.st_ctime_ns),
                         (after.st_ino, after.st_uid, after.st_gid, after.st_mode, after.st_mtime_ns, after.st_ctime_ns))

    def test_prefix_links_and_files_are_rejected_without_following_or_replacing(self):
        for kind in ('broken-link', 'directory-link', 'file'):
            path = self.root / kind; target = self.root / (kind + '-target')
            if kind == 'directory-link':
                target.mkdir(mode=0o700); path.symlink_to(target, target_is_directory=True)
            elif kind == 'broken-link':
                path.symlink_to(target)
            else:
                path.write_bytes(b'keep-original')
            before = path.lstat()
            self.assertNotEqual(0, self.prefix(path).returncode)
            self.assertEqual(before.st_ino, path.lstat().st_ino)
            if kind == 'broken-link':
                self.assertFalse(target.exists())
            if kind == 'file':
                self.assertEqual(b'keep-original', path.read_bytes())


if __name__ == '__main__':
    unittest.main()
