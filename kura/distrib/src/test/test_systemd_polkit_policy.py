"""Exercise the emitted policy and its filesystem transition, without users/services."""
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/install/manage_kura_users.sh'
FUNCTIONS = SCRIPT.read_text().split('function create_users {', 1)[0]
sys.path.insert(0, str(SCRIPT.parent.parent / 'bin'))
from kura_clock_broker import CHRONY_RULE


class SystemdPolkitPolicyTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.rules = self.root / 'rules'
        self.legacy = self.root / 'legacy' / '51-org.freedesktop.systemd1.pkla'
        self.legacy.parent.mkdir()
        self.policy = self.rules / '51-kura-systemd.rules'
        self.old_policy = self.rules / 'kura.rules'

    def write(self, profile='NO'):
        return subprocess.run(
            ['bash', '-c', FUNCTIONS + '\nNN="$3"\nwrite_systemd_polkit_policy "$1" "$2"',
             'policy-test', str(self.rules), str(self.legacy), profile],
            capture_output=True, text=True, timeout=10)

    def seed(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def backup(self, path, data):
        return path.with_name(path.name + '.' + hashlib.sha256(data).hexdigest() + '.kurasave')

    def test_replaces_existing_policy_and_preserves_both_originals(self):
        old = b'old custom systemd policy\n'
        legacy = b'Action=org.freedesktop.systemd1.*\nResultAny=yes\n'
        self.seed(self.old_policy, old)
        self.seed(self.legacy, legacy)
        result = self.write()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.policy.read_bytes(), old)
        self.assertFalse(self.old_policy.exists())
        self.assertFalse(self.legacy.exists())
        for path, data in [(self.old_policy, old), (self.legacy, legacy)]:
            saved = self.backup(path, data)
            self.assertEqual(saved.read_bytes(), data)
            self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)
            self.assertNotIn(saved.suffix, ['.rules', '.pkla'])
        self.assertEqual(stat.S_IMODE(self.policy.stat().st_mode), 0o644)

    def test_idempotent_policy_keeps_inode_and_bytes(self):
        self.assertEqual(self.write().returncode, 0)
        before = self.policy.read_bytes(), self.policy.stat().st_ino
        self.assertEqual(self.write().returncode, 0)
        self.assertEqual((self.policy.read_bytes(), self.policy.stat().st_ino), before)
        self.assertEqual(sorted(p.name for p in self.rules.iterdir()), [self.policy.name])

    def test_retires_late_legacy_grants_even_when_modern_policy_unchanged(self):
        self.assertEqual(self.write().returncode, 0)
        inode = self.policy.stat().st_ino
        old = b'late legacy wildcard\n'
        self.seed(self.legacy, old)
        late = b'legacy package recreated the old rule\n'
        self.seed(self.old_policy, late)
        self.assertEqual(self.write().returncode, 0)
        self.assertFalse(self.legacy.exists())
        self.assertFalse(self.old_policy.exists())
        self.assertEqual(self.backup(self.legacy, old).read_bytes(), old)
        self.assertEqual(self.backup(self.old_policy, late).read_bytes(), late)
        self.assertEqual(self.policy.stat().st_ino, inode)

    def test_refuses_symlink_policy_without_touching_target(self):
        target = self.root / 'outside'
        self.seed(target, b'keep\n')
        self.rules.mkdir()
        self.policy.symlink_to(target)
        self.assertNotEqual(self.write().returncode, 0)
        self.assertTrue(self.policy.is_symlink())
        self.assertEqual(target.read_bytes(), b'keep\n')

    def test_refuses_symlink_legacy_without_touching_target(self):
        target = self.root / 'outside'
        self.seed(target, b'keep\n')
        self.legacy.symlink_to(target)
        self.assertNotEqual(self.write().returncode, 0)
        self.assertTrue(self.legacy.is_symlink())
        self.assertFalse(self.policy.exists())
        self.assertEqual(target.read_bytes(), b'keep\n')

    def test_refuses_conflicting_backup_without_replacing_active_rules(self):
        old = b'keep current rules\n'
        self.seed(self.policy, old)
        self.seed(self.backup(self.policy, old), b'conflict\n')
        self.assertNotEqual(self.write().returncode, 0)
        self.assertEqual(self.policy.read_bytes(), old)
        self.assertEqual(self.backup(self.policy, old).read_bytes(), b'conflict\n')
        self.assertFalse(any(p.name.startswith('.51-kura-systemd.rules.') for p in self.rules.iterdir()))

    def test_refuses_invalid_profile_before_writing_rules(self):
        self.assertNotEqual(self.write('unexpected').returncode, 0)
        self.assertFalse(self.rules.exists())

    def evaluate(self, profile, cases, *policies):
        if not shutil.which('node'):
            self.skipTest('Node is needed for the emitted JavaScript contract; native polkit is verified separately')
        result = self.write(profile)
        self.assertEqual(result.returncode, 0, result.stderr)
        program = '''
const fs = require('fs'), vm = require('vm'), basename = require('path').basename;
const paths = process.argv.slice(2).sort((left, right) => {
    const a = basename(left), b = basename(right);
    if (a === b) return 0;
    return a < b ? -1 : 1;
});
const rules = [];
for (const path of paths) {
    vm.runInNewContext(fs.readFileSync(path, 'utf8'), {
        polkit: {Result: {YES: 'yes', NO: 'no'}, addRule: f => rules.push(f)}
    });
}
process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map(c => {
    const action = {id: c.action || 'org.freedesktop.systemd1.manage-units', lookup: k => (c.details || {})[k]};
    const subject = {user: c.user || 'kurad', system_unit: c.systemUnit, no_new_privileges: c.nnp};
    for (const rule of rules) {
        const result = rule(action, subject);
        if (result != null) return result;
    }
})));
'''
        paths = [str(p) for p in (policies or (self.policy,))]
        result = subprocess.run(['node', '-e', program, json.dumps(cases), *paths],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_direct_service_control_is_denied_in_the_networking_profile(self):
        denied = [('cron.service', 'restart'), ('bluetooth.service', 'start'),
                  ('named.service', 'reload'), ('named.service', 'kill'),
                  ('chrony.service', 'start'), ('chronyd.service', 'stop'), ('named@other.service', 'start')]
        denied += [(unit, verb) for unit in ['named.service', 'bind9.service']
                   for verb in ['start', 'stop', 'restart']]
        cases = [dict(details=dict(unit=u, verb=v)) for u, v in denied]
        cases += [dict(details=dict(unit='named.service')), dict(details=dict(verb='start')), dict()]
        self.assertEqual(self.evaluate('NO', cases), ['no'] * len(cases))

    def test_no_network_profile_has_no_service_control_grants(self):
        cases = [dict(details=dict(unit=u, verb='start')) for u in
                 ['chrony.service', 'chronyd.service', 'named.service', 'bind9.service']]
        self.assertEqual(self.evaluate('YES', cases), ['no'] * 4)

    def test_unit_files_reload_and_other_systemd_writes_are_denied(self):
        actions = ['manage-unit-files', 'reload-daemon', 'set-environment', 'unknown-future-operation']
        cases = [dict(action='org.freedesktop.systemd1.' + a,
                      details=dict(unit='named.service', verb='enable')) for a in actions]
        self.assertEqual(self.evaluate('NO', cases), ['no'] * len(actions))

    def test_other_users_and_services_keep_their_own_authority(self):
        cases = [dict(user=u, details=dict(unit='named.service', verb='start')) for u in ['root', 'nobody']]
        cases += [dict(action='org.freedesktop.NetworkManager.enable-disable-network'),
                  dict(action='org.freedesktop.login1.inhibit-handle-lid-switch'),
                  dict(user='root', action='org.freedesktop.login1.reboot-multiple-sessions')]
        self.assertEqual(self.evaluate('NO', cases), [None] * len(cases))

    def test_core_precedes_installed_legacy_networking_rule(self):
        networking = self.rules / '52-kura-networking.rules'
        self.seed(networking, b'''polkit.addRule(function(action, subject) {
            if (subject.user !== 'kurad') return;
            if (action.id === 'org.freedesktop.NetworkManager.enable-disable-network') return polkit.Result.YES;
            if (action.id === 'org.freedesktop.systemd1.manage-units' &&
                ['chrony.service', 'chronyd.service', 'named.service'].indexOf(action.lookup('unit')) !== -1)
                return polkit.Result.YES;
        });\n''')
        cases = [dict(details=dict(unit='chrony.service', verb='start')),
                 dict(details=dict(unit='chronyd.service', verb='stop')),
                 dict(details=dict(unit='named.service', verb='kill')),
                 dict(details=dict(unit='named.service', verb='restart')),
                 dict(action='org.freedesktop.NetworkManager.enable-disable-network')]
        self.assertEqual(self.evaluate('NO', cases, networking, self.policy), ['no', 'no', 'no', 'no', 'yes'])
        self.assertEqual(self.evaluate('YES', cases, networking, self.policy), ['no', 'no', 'no', 'no', 'yes'])

    def test_daemon_cannot_use_logind_to_change_host_power_state(self):
        actions = ['reboot', 'reboot-multiple-sessions', 'reboot-ignore-inhibit', 'power-off-multiple-sessions',
                   'power-off', 'halt', 'kexec', 'soft-reboot', 'suspend-multiple-sessions',
                   'suspend-then-hibernate', 'hibernate-ignore-inhibit', 'hybrid-sleep',
                   'set-reboot-parameter', 'set-reboot-to-boot-loader-entry', 'set-reboot-to-firmware-setup']
        cases = [dict(action='org.freedesktop.login1.' + action) for action in actions]
        for profile in ('NO', 'YES'):
            self.assertEqual(self.evaluate(profile, cases), ['no'] * len(cases))

    def test_clock_rule_requires_exact_service_account_unit_verb_and_nnp(self):
        policy = self.root / 'clock.rules'
        policy.write_bytes(CHRONY_RULE)
        base = dict(user='kura-clock', systemUnit='kura-clock-broker.service', nnp=True,
                    details=dict(unit='chrony.service', verb='start'))
        restart = dict(base, details=dict(unit='chrony.service', verb='restart'))
        cases = [base, dict(base, details=dict(unit='chronyd.service', verb='stop')), restart,
                 dict(base, nnp=False), dict(base, nnp=None), dict(base, systemUnit='other.service'),
                 dict(restart, systemUnit='other.service'), dict(restart, nnp=False),
                 dict(base, details=dict(unit='networking.service', verb='start')),
                 dict(base, action='org.freedesktop.systemd1.manage-unit-files'), dict(base, user='kurad')]
        self.assertEqual(self.evaluate('NO', cases, policy), ['yes'] * 3 + ['no'] * 7 + [None])


if __name__ == '__main__':
    unittest.main()
