#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Retained boot choices are bound to the original Root removal and identities."""
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import test_key_service_lifecycle as fixtures

lifecycle = fixtures.lifecycle
CONTROL = Path(__file__).resolve().parents[1] / 'main/resources/variants/linux/unfiltered/deb/control/prerm'


class RetainedMainStateTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LifecycleTest('runTest'); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.policy = self.fixture.policy; self.root = self.policy.root
        self.choice = 'disabled'; self.fail_enable = False
        original_runner = self.policy.runner
        def runner(args, **kwargs):
            if args[1:3] == ['show', 'kura.service'] and '--property=UnitFileState' in args:
                return fixtures.types.SimpleNamespace(returncode=0, stdout=self.choice + '\n', stderr='')
            if args[1] == 'enable':
                self.fixture.calls.append(args)
                if self.fail_enable:
                    return fixtures.types.SimpleNamespace(returncode=47, stdout='', stderr='')
                self.choice = 'enabled-runtime' if '--runtime' in args else 'enabled'
                return fixtures.types.SimpleNamespace(returncode=0, stdout='', stderr='')
            return original_runner(args, **kwargs)
        self.policy.runner = runner
        self.fence = self.policy.enter('remove')
        self.accounts = {'kura': {'uid': 1000, 'gid': 1000}, 'kurad': {'uid': 997, 'gid': 991}}
        mocked = patch.object(self.policy, 'main_accounts', return_value=self.accounts)
        mocked.start(); self.addCleanup(mocked.stop)
        self.stage = self.root / 'var/lib/.kura-retained.tmp.1234abcd'
        (self.stage / 'systemd').mkdir(parents=True, mode=0o700)
        self.stage.chmod(0o700)
        self.fixture.write(self.root / 'lib/systemd/system/kura.service', b'Root owned Main unit\n', 0o644)
        self.fixture.write(self.stage / 'systemd/kura.service', b'Root owned Main unit\n', 0o644)
        self.retained = self.root / 'var/lib/kura-retained'

    def retain(self, choice='disabled'):
        self.choice = choice; self.policy.retain_main_state(self.stage)
        self.stage.rename(self.retained)
        return self.retained / 'systemd/main-state.json'

    def test_disabled_reinstall_keeps_original_fence_and_makes_no_enable_call(self):
        self.retain(); before = (self.policy.state / 'maintenance.json').read_bytes()
        value = self.policy.retained_main_state(restore=True)
        self.assertEqual(self.fence['id'], value['maintenanceId'])
        self.assertEqual(before, (self.policy.state / 'maintenance.json').read_bytes())
        self.assertFalse(any(args[1] == 'enable' for args in self.fixture.calls))

    def test_enabled_and_runtime_enabled_are_restored_without_starting_main(self):
        for state in ('enabled', 'enabled-runtime'):
            with self.subTest(state=state):
                path = self.retain(state); self.choice = 'disabled'
                self.policy.retained_main_state(restore=True)
                self.assertEqual(state, self.choice)
                self.policy.retained_main_state(restore=True)
                calls = [args for args in self.fixture.calls if args[1] == 'enable']
                self.assertEqual(1, len(calls)); self.assertNotIn('--now', calls[0])
                self.assertEqual(state == 'enabled-runtime', '--runtime' in calls[0])
                self.fixture.calls.clear(); path.unlink()
                self.retained.rename(self.stage)

    def test_static_and_masks_are_verified_without_changing_links(self):
        for state in ('static', 'masked', 'masked-runtime'):
            with self.subTest(state=state):
                path = self.retain(state); self.policy.retained_main_state(restore=True)
                self.assertEqual(state, self.choice)
                self.assertFalse(any(args[1] == 'enable' for args in self.fixture.calls))
                path.unlink(); self.retained.rename(self.stage)

    def test_changed_record_fence_root_secret_account_or_unit_refuses_before_enable(self):
        path = self.retain('enabled'); original = path.read_bytes(); self.choice = 'disabled'
        for item in ('record', 'fence', 'root', 'account', 'unit'):
            with self.subTest(item=item):
                target = path
                if item == 'record':
                    changed = json.loads(original); changed['unitFileState'] = 'disabled'
                    self.fixture.write(path, lifecycle.encoded(changed))
                elif item == 'fence':
                    target = self.policy.state / 'maintenance.json'; old = target.read_bytes()
                    changed = json.loads(old); changed['id'] = str(fixtures.uuid.uuid4())
                    self.fixture.write(target, lifecycle.encoded(changed))
                elif item == 'root':
                    target = self.policy.state / 'journal.key'; old = target.read_bytes()
                    self.fixture.write(target, b'X' * 32)
                elif item == 'account':
                    self.accounts['kurad']['uid'] += 1
                else:
                    target = self.retained / 'systemd/kura.service'; old = target.read_bytes()
                    self.fixture.write(target, b'changed unit\n', 0o644)
                with self.assertRaises(lifecycle.Refused): self.policy.retained_main_state(restore=True)
                self.assertEqual('disabled', self.choice)
                if item == 'record': self.fixture.write(path, original)
                elif item == 'account': self.accounts['kurad']['uid'] -= 1
                else: self.fixture.write(target, old, 0o644 if item == 'unit' else 0o600)
        self.assertFalse(any(args[1] == 'enable' for args in self.fixture.calls))

    def test_missing_legacy_record_or_unsafe_link_is_not_adopted(self):
        self.retain(); path = self.retained / 'systemd/main-state.json'
        raw = path.read_bytes(); path.unlink()
        with self.assertRaises(FileNotFoundError): self.policy.retained_main_state()
        other = self.retained / 'systemd/other'; self.fixture.write(other, raw)
        path.symlink_to(other)
        with self.assertRaises(OSError): self.policy.retained_main_state()

    def test_failed_enable_keeps_retained_state_and_original_admission(self):
        path = self.retain('enabled'); raw = path.read_bytes()
        self.choice = 'disabled'; self.fail_enable = True
        with self.assertRaises(lifecycle.Refused): self.policy.retained_main_state(restore=True)
        self.assertEqual(raw, path.read_bytes()); self.assertEqual(self.fence, self.policy.fence())


class RemoveCallbackTest(unittest.TestCase):
    def test_uninstall_uses_installed_bin_helper_after_install_tree_cleanup(self):
        raw = CONTROL.read_text()
        callback = 'bash "${INSTALL_DIR}/kura/bin/manage_kura_users.sh" -u || exit 1'
        self.assertIn(callback, raw)
        self.assertNotIn('bash "${INSTALL_DIR}/kura/install/manage_kura_users.sh" -u', raw)
        postinst = (CONTROL.parent / 'postinst').read_text()
        self.assertIn('rm -rf ${INSTALL_DIR}/kura/install', postinst)
        # Exercise the shipped callback after the entire install tree is gone.
        with fixtures.tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); helper = root / 'kura/bin/manage_kura_users.sh'
            helper.parent.mkdir(parents=True)
            helper.write_text('#!/bin/bash\n[ "$1" = -u ] || exit 47\n')
            result = subprocess.run(['bash', '-c', callback], env=dict(os.environ, INSTALL_DIR=str(root)))
            self.assertEqual(0, result.returncode)

    def test_preserve_data_copies_history_with_numeric_owners_and_never_executes_it(self):
        raw = CONTROL.read_text(); start = raw.index('function preserveUserData {')
        end = raw.index('##############################################\n# UTILITY FUNCTIONS', start)
        for fail in (False, True):
            with self.subTest(copy_failure=fail), fixtures.tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); home = root / 'opt/kura'
                (home / '.data').mkdir(parents=True); (root / 'var/lib').mkdir(parents=True)
                (root / 'lib/systemd/system').mkdir(parents=True)
                (root / 'lib/systemd/system/kura.service').write_text('Root managed unit\n')
                historical = home / '.data/manage_kura_users.sh'
                historical.write_bytes(b'#!/bin/sh\nexit 47 # historical data, not installed code\n')
                historical.chmod(0o600)
                snapshot = home / '.data/snapshot_0.xml'; snapshot.write_bytes(b'original historical XML\n')
                old = [(p.read_bytes(), p.stat().st_uid, p.stat().st_gid, p.stat().st_mode, p.stat().st_mtime_ns)
                       for p in (historical, snapshot)]
                function = raw[start:end].replace('/var/lib/', str(root / 'var/lib') + '/')
                function = function.replace('/lib/systemd/system/', str(root / 'lib/systemd/system') + '/')
                function = function.replace('/etc/kura/', str(root / 'etc/kura') + '/')
                prelude = '''python3() { return 0; }
manageAddonCode() { return 0; }
cp() {
    case "$2" in */.data) [ "$FAIL_COPY" = 0 ] || return 47;; esac
    command cp "$@"
}
'''
                env = dict(os.environ, INSTALL_DIR=str(root / 'opt'), RETAINED_DIR=str(root / 'var/lib/kura-retained'),
                           FAIL_COPY='1' if fail else '0')
                result = subprocess.run(['bash', '-c', prelude + function + '\npreserveUserData\n'],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(fail, result.returncode != 0, result.stderr)
                for index, path in enumerate((historical, snapshot)):
                    target = path if fail else root / 'var/lib/kura-retained/addon-data' / path.name
                    m = target.stat()
                    self.assertEqual(old[index], (target.read_bytes(), m.st_uid, m.st_gid, m.st_mode, m.st_mtime_ns))
                if fail: self.assertFalse((root / 'var/lib/kura-retained').exists())

    def test_disable_failure_keeps_main_unit_and_reaches_callback_caller(self):
        raw = CONTROL.read_text(); start = raw.index('function preRemove {')
        end = raw.index('##############################################\n# END UTILITY', start)
        with fixtures.tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); unit = root / 'lib/systemd/system/kura.service'
            unit.parent.mkdir(parents=True); unit.write_text('keep managed unit\n')
            function = raw[start:end].replace('/etc/init.d/kura', str(root / 'absent-init'))
            function = function.replace('/lib/systemd/system/kura.service', str(unit))
            script = 'systemctl() { return 47; }\n' + function + '\npreRemove\n'
            result = subprocess.run(['bash', '-c', script], capture_output=True)
            self.assertNotEqual(0, result.returncode); self.assertEqual('keep managed unit\n', unit.read_text())

    def test_real_callback_exit_status_is_propagated_in_both_watchdog_paths(self):
        raw = CONTROL.read_text(); start = raw.index('function runPreRemove {')
        end = raw.index('# Pre-remove script', start); definitions = raw[start:end]
        for status in (0, 47):
            for watchdog in (False, True):
                with self.subTest(status=status, watchdog=watchdog), fixtures.tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp); device = root / 'device'; marker = root / 'watchdog'
                    if watchdog: marker.write_text(str(device))
                    env = dict(os.environ, WD_TMP_FILE=str(marker), REFRESH_TIME='0.01',
                               TIMEOUT_TIME='10', TEST_STATUS=str(status))
                    script = definitions + '\npreRemove() { return "$TEST_STATUS"; }\nrunPreRemove\n'
                    result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, timeout=5)
                    self.assertEqual(status != 0, result.returncode != 0)


if __name__ == '__main__':
    unittest.main()
