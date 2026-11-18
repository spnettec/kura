#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Main template publication must preserve an existing boot choice and fail closed."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'main/resources/variants/linux/unfiltered/pkg/install/kura_install.sh'


class MainUnitInstallTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.install = self.root / 'opt'; (self.install / 'kura/install').mkdir(parents=True)
        (self.install / 'kura/install/kura.service').write_text('[Service]\nExecStart=INSTALL_DIR/kura/bin/start_kura.sh\n')
        (self.install / 'kura/bin').mkdir(); (self.install / 'kura/bin/start_kura.sh').write_text('#!/bin/sh\n')
        self.paths = {}
        for key, name in [('lib', '/lib/systemd/system'), ('usr', '/usr/lib/systemd/system'),
                          ('etc', '/etc/systemd/system'), ('run', '/run/systemd/system')]:
            path = self.root / name.lstrip('/'); path.mkdir(parents=True); self.paths[key] = path
        self.calls = self.root / 'calls'
        self.systemctl = self.root / 'systemctl'
        self.systemctl.write_text('''#!/bin/sh
printf '%s\n' "$*" >> "$CALLS"
case "$1:$FAIL" in daemon-reload:reload|enable:enable) exit 47;; esac
exit 0
'''); self.systemctl.chmod(0o700)

    def invoke(self, fail=''):
        raw = SOURCE.read_text(); start = raw.index('# set up kura init\n'); end = raw.index('# setup snapshot_0 recovery folder', start)
        script = raw[start:end]
        for key, name in [('usr', '/usr/lib/systemd/system'), ('lib', '/lib/systemd/system'),
                          ('etc', '/etc/systemd/system'), ('run', '/run/systemd/system')]:
            # Replace complete directory tokens once, so /usr/lib is not
            # accidentally rewritten a second time through its /lib suffix.
            script = script.replace(name + '/', '__UNIT_' + key.upper() + '__/')
        for key, path in self.paths.items(): script = script.replace('__UNIT_' + key.upper() + '__', str(path))
        script = script.replace('/usr/bin/systemctl', str(self.systemctl))
        env = dict(os.environ, INSTALL_DIR=str(self.install), CALLS=str(self.calls), FAIL=fail)
        result = subprocess.run(['/bin/sh', '-c', script],env=env,capture_output=True,text=True)
        return result, self.calls.read_text().splitlines()

    def test_fresh_service_is_enabled_after_successful_reload(self):
        result, calls = self.invoke()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['daemon-reload', 'enable kura.service'], calls)
        self.assertIn(str(self.install) + '/kura/bin/start_kura.sh', (self.paths['lib'] / 'kura.service').read_text())

    def test_existing_unit_keeps_disabled_enabled_runtime_static_and_mask_choices(self):
        for kind in ['disabled', 'enabled', 'enabled-runtime', 'static', 'masked', 'masked-runtime']:
            with self.subTest(kind=kind):
                unit = self.paths['lib'] / 'kura.service'; unit.write_text('old managed template\n')
                links = []
                if kind in ['enabled', 'enabled-runtime']:
                    folder = self.paths['etc' if kind == 'enabled' else 'run'] / 'multi-user.target.wants'
                    folder.mkdir(exist_ok=True); link = folder / 'kura.service'; link.symlink_to(unit); links.append(link)
                elif kind in ['masked', 'masked-runtime']:
                    link = self.paths['etc' if kind == 'masked' else 'run'] / 'kura.service'
                    link.symlink_to('/dev/null'); links.append(link)
                before = {str(p): (p.lstat().st_ino, os.readlink(p)) for p in links}
                result, calls = self.invoke()
                self.assertEqual(0, result.returncode, result.stderr); self.assertEqual(['daemon-reload'], calls)
                self.assertEqual(before, {str(p): (p.lstat().st_ino, os.readlink(p)) for p in links})
                for link in links: link.unlink()
                self.calls.unlink()

    def test_existing_other_vendor_or_mask_is_not_treated_as_new_service(self):
        for key, broken in [('usr', False), ('etc', False), ('run', False), ('etc', True)]:
            with self.subTest(location=key, broken=broken):
                unit = self.paths[key] / 'kura.service'
                if broken: unit.symlink_to(self.root / 'missing-operator-target')
                else: unit.write_text('existing choice\n')
                result, calls = self.invoke(); self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(['daemon-reload'], calls)
                self.assertTrue(unit.is_symlink() if broken else unit.is_file())
                unit.unlink(); self.calls.unlink()
                (self.paths['lib'] / 'kura.service').unlink()

    def test_failed_reload_does_not_enable_or_report_success(self):
        result, calls = self.invoke('reload')
        self.assertNotEqual(0, result.returncode); self.assertEqual(['daemon-reload'], calls)

    def test_failed_first_enable_is_propagated(self):
        result, calls = self.invoke('enable')
        self.assertNotEqual(0, result.returncode); self.assertEqual(['daemon-reload', 'enable kura.service'], calls)


if __name__ == '__main__':
    unittest.main()
