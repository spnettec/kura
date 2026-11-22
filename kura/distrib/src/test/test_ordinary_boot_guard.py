"""Exercise the guard shipped in both Core maintainer scripts before side effects."""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1] / 'main/resources/variants/linux/unfiltered/deb/control'


def guard(name):
    text = (BASE / name).read_text()
    return text.split("<<'PYGUARD'\n", 1)[1].split('\nPYGUARD', 1)[0]


class OrdinaryBootGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='core-ordinary-boot-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / 'ordinary-boot'
        self.policy.mkdir(mode=0o700)
        self.ident = 'boot-11111111-1111-1111-1111-111111111111'
        self.journal = self.policy / 'transaction.json'

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(value).encode())
        path.chmod(0o600)

    def committed(self, target='kura.service'):
        receipt = {'schema': 'yofc.agent.ordinary-boot.v1', 'id': self.ident, 'request': {},
            'targetBefore': {'unit': target}, 'retiredBefore': [], 'actionIntents': ['enable ' + target],
            'status': 'BOOT_POLICY_COMMITTED', 'bootVerified': False, 'kuraRecoveryVerified': False}
        p = self.policy / 'receipts' / (self.ident + '.json')
        self.put(p, receipt)
        journal = {'schema': 1, 'id': self.ident, 'token': '22222222-2222-2222-2222-222222222222',
            'state': 'BOOT_POLICY_COMMITTED', 'expiresAt': 123, 'previousConfirmedSha256': None, 'request': {},
            'target': receipt['targetBefore'], 'retired': [], 'actionIntents': receipt['actionIntents'],
            'receiptSha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        self.put(self.journal, journal)
        self.put(self.policy / 'confirmed.json', journal)
        return journal, p

    def run_guard(self, script='preinst'):
        source = guard(script).replace("Path('/etc/kura/ordinary-boot-policy.json')", 'Path(' + repr(str(self.root / 'core-policy.json')) + ')').replace("Path('/var/lib/kura-management-agent/ordinary-boot')", 'Path(' + repr(str(self.policy)) + ')')
        return subprocess.run([sys.executable, '-c', source], capture_output=True, text=True)

    def test_same_exact_guard_precedes_install_mutations_in_both_scripts(self):
        self.assertEqual(guard('preinst'), guard('postinst'))
        for name in ['preinst', 'postinst']:
            text = (BASE / name).read_text()
            self.assertLess(text.index('guardOrdinaryBootPolicy "$@" || exit 1'), text.index('INSTALL_DIR='))
            self.assertIn('abort-upgrade|abort-remove|failed-upgrade) ;;', text)

    def test_absent_agent_policy_keeps_core_independent(self):
        self.assertEqual(self.run_guard().returncode, 0)

    def system_control_cancelled(self):
        root = self.root / 'system-control'
        root.mkdir(mode=0o700)
        ident = 'system-11111111-1111-4111-8111-111111111111'
        config = {'schema': 1, 'unit': 'kura.service', 'unitDefinitionSha256': 'a' * 64}
        path = root / 'receipts' / (ident + '.config.json')
        self.put(path, config)
        path.parent.chmod(0o700)
        value = dict(schema=1, id=ident, token='22222222-2222-4222-8222-222222222222',
            state='CANCELLED', action='restart', configSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            definitionSha256='a' * 64, unit='kura.service', before={},
            beforeBootId='33333333-3333-4333-8333-333333333333', expiresAt=1,
            profile=None, snapshots=[], probe=None, issuedCommand=None, issued=False,
            issuedAt=None, requestAccepted=False, scheduledUnit=None, after=None,
            afterBootId=None, observation=None, outcome=None, receiptSha256=None,
            error=None, commandDecisions={})
        journal = root / 'transaction.json'
        self.put(journal, value)
        return journal, value, path

    def test_system_control_pending_blocks_both_scripts_and_preserves_every_record(self):
        p, j, _ = self.system_control_cancelled()
        for state in ['PREPARED', 'ISSUING', 'AWAITING_BOOT', 'VERIFYING_APPLICATION', 'RECOVERY_REQUIRED']:
            j['state'] = state
            self.put(p, j)
            before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            for script in ['preinst', 'postinst']:
                r = self.run_guard(script)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('unresolved transaction', r.stderr)
            self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_system_control_cancelled_needs_original_private_grant_and_no_issued_intent(self):
        p, j, config = self.system_control_cancelled()
        for script in ['preinst', 'postinst']:
            r = self.run_guard(script)
            self.assertEqual(r.returncode, 0, r.stderr)
        config.chmod(0o644)
        self.assertNotEqual(self.run_guard().returncode, 0)
        config.chmod(0o600)
        config.write_bytes(config.read_bytes() + b' ')
        self.assertNotEqual(self.run_guard().returncode, 0)
        j['issued'] = True
        self.put(p, j)
        self.assertNotEqual(self.run_guard().returncode, 0)

    def test_system_control_evidence_alone_blocks_without_any_agent_configuration(self):
        root = self.root / 'system-control/commands'
        root.mkdir(parents=True, mode=0o700)
        self.assertEqual(self.run_guard().returncode, 0)
        path = root / 'retained.json'
        self.put(path, {'preserve': True})
        before = path.read_bytes()
        for script in ['preinst', 'postinst']:
            r = self.run_guard(script)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('journal missing with retained records', r.stderr)
        self.assertEqual(before, path.read_bytes())

    def test_handoff_commands_without_recovery_journal_block_core_and_preserve_bytes(self):
        commands = self.root / 'recovery/commands'
        commands.mkdir(parents=True, mode=0o700)
        self.assertEqual(self.run_guard().returncode, 0)
        path = commands / 'retained.json'
        self.put(path, {'unlinked': True})
        before = path.read_bytes()
        for script in ['preinst', 'postinst']:
            result = self.run_guard(script)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('handoff command evidence', result.stderr)
        self.assertEqual(before, path.read_bytes())

    def test_native_core_committed_policy_retains_every_byte(self):
        self.committed()
        before = {str(p): p.read_bytes() for p in self.policy.rglob('*') if p.is_file()}
        for script in ['preinst', 'postinst']:
            r = self.run_guard(script)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.policy.rglob('*') if p.is_file()})

    def test_command_evidence_is_private_bound_and_does_not_change_the_confirmed_kernel_policy(self):
        j, _ = self.committed()
        command = '33333333-3333-4333-8333-333333333333'
        decision = {'schema': 1, 'transactionId': self.ident, 'binding': {'commandId': command, 'requestSha256': 'a' * 64, 'operation': 19}, 'result': {}}
        path = self.policy / 'commands' / (command + '.json')
        self.put(path, decision)
        j['commandDecisions'] = {command: hashlib.sha256(path.read_bytes()).hexdigest()}
        self.put(self.journal, j)
        for name in ['preinst', 'postinst']:
            result = self.run_guard(name)
            self.assertEqual(result.returncode, 0, result.stderr)
        raw = path.read_bytes()
        path.write_bytes(raw + b' ')
        self.assertNotEqual(self.run_guard().returncode, 0)
        path.write_bytes(raw)
        path.chmod(0o644)
        self.assertNotEqual(self.run_guard().returncode, 0)
        path.chmod(0o600)
        j['issuedCommand'] = dict(decision['binding'], operation=17)
        self.put(self.journal, j)
        self.assertNotEqual(self.run_guard().returncode, 0)

    def test_different_ordinary_unit_cannot_silently_reenable_core_entry(self):
        self.committed('reviewed-ordinary.service')
        r = self.run_guard()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('re-enable a different Kura startup entry', r.stderr)

    def test_prepared_partial_and_recovery_required_are_blocked(self):
        j, _ = self.committed()
        for state in ['BOOT_POLICY_PREPARED', 'APPLYING_BOOT_POLICY', 'RECOVERY_REQUIRED']:
            j['state'] = state
            self.put(self.journal, j)
            self.assertNotEqual(self.run_guard().returncode, 0, state)

    def test_receipt_corruption_missing_and_exposed_evidence_are_blocked(self):
        j, p = self.committed()
        original = p.read_bytes()
        p.write_bytes(original + b' ')
        self.assertNotEqual(self.run_guard().returncode, 0)
        p.write_bytes(original)
        p.chmod(0o644)
        self.assertNotEqual(self.run_guard().returncode, 0)
        p.chmod(0o600)
        p.rename(p.with_suffix('.retained'))
        self.assertNotEqual(self.run_guard().returncode, 0)

    def test_cancelled_requires_a_full_unissued_journal(self):
        j, _ = self.committed()
        j.update(state='CANCELLED', actionIntents=[], receiptSha256=None)
        self.put(self.journal, j)
        self.assertEqual(self.run_guard().returncode, 0)
        self.put(self.journal, {'state': 'CANCELLED'})
        self.assertNotEqual(self.run_guard().returncode, 0)

    def test_symlink_and_exposed_journal_are_rejected(self):
        self.committed()
        self.journal.chmod(0o644)
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.journal.chmod(0o600)
        retained = self.journal.with_suffix('.retained')
        self.journal.rename(retained)
        self.journal.symlink_to(retained)
        self.assertNotEqual(self.run_guard().returncode, 0)

    def test_cancelled_new_plan_keeps_previous_different_boot_entry_protected(self):
        j, _ = self.committed('reviewed-ordinary.service')
        j.update(id='boot-33333333-3333-3333-3333-333333333333', state='CANCELLED', actionIntents=[], receiptSha256=None)
        self.put(self.journal, j)
        self.assertNotEqual(self.run_guard().returncode, 0)

    def test_core_registration_routes_custom_state_and_missing_journal_is_blocked(self):
        self.committed()
        self.put(self.root / 'core-policy.json', {'schema': 1, 'stateRoot': str(self.root)})
        self.assertEqual(self.run_guard().returncode, 0)
        self.journal.rename(self.journal.with_suffix('.retained'))
        self.assertNotEqual(self.run_guard().returncode, 0)

    def test_maintainer_supervisor_holds_both_locks_and_children_cannot_extend_them(self):
        source = (BASE / 'preinst').read_text()
        start = source.index('# YOFC ORDINARY BOOT INSTALL GUARD V1')
        end = source.index('# END YOFC ORDINARY BOOT INSTALL GUARD V1') + len('# END YOFC ORDINARY BOOT INSTALL GUARD V1')
        header = source[start:end]
        header = header.replace("Path('/etc/kura/ordinary-boot-policy.json')", 'Path(' + repr(str(self.root / 'core-policy.json')) + ')')
        header = header.replace("Path('/var/lib/kura-management-agent/ordinary-boot')", 'Path(' + repr(str(self.policy)) + ')')
        lock = self.root / 'core.lock'
        header = header.replace("Path('/run/lock/kura-ordinary-boot.lock')", 'Path(' + repr(str(lock)) + ')')
        counter = self.root / 'counter'
        child_pid = self.root / 'child.pid'
        stub = r"""
python3 - <<'STUB'
from pathlib import Path
import fcntl, subprocess
root = Path(ROOT)
for name in ['core.lock', 'system-change.lock']:
    with (root / name).open('r+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise AssertionError('supervisor did not hold '+name)
with (root / 'counter').open('a') as f:f.write('once\n')
child = subprocess.Popen(['/bin/sleep','4'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=False)
(root / 'child.pid').write_text(str(child.pid))
STUB
""".replace('ROOT', repr(str(self.root)))
        script = self.root / 'phase.sh'
        script.write_text('#!/bin/bash\n' + header + '\n' + stub)
        env = dict(os.environ)
        env.pop('_YOFC_CORE_BOOT_GUARD_CHILD', None)
        result = subprocess.run(['/bin/bash', str(script), 'install'], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(counter.read_text(), 'once\n')
        pid = int(child_pid.read_text())
        os.kill(pid, 0)
        self.addCleanup(lambda: os.kill(pid, signal.SIGTERM) if subprocess.run(['kill', '-0', str(pid)], capture_output=True).returncode == 0 else None)
        for name in ['core.lock', 'system-change.lock']:
            with (self.root / name).open('r+') as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_other_managed_recovery_required_blocks_core_install(self):
        self.put(self.root / 'recovery/transaction.json', {'state': 'RECOVERY_REQUIRED'})
        self.assertNotEqual(self.run_guard().returncode, 0)


if __name__ == '__main__':
    unittest.main()
