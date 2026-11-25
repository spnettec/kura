#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Exercise the snapshot maintenance guard against real Linux lock inodes."""

from contextlib import ExitStack, nullcontext
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_key_generation as generation


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Requires a disposable Linux root')
class SnapshotRewrapAgentTest(unittest.TestCase):
    uid = 2010
    gid = 2011

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.policy = generation.Lifecycle(self.root, owner=0)
        self.path = self.policy.path
        self.secret = b'x' * 32
        self.namespace = '0' * 64
        self.state = self.path(generation.NATIVE_AGENT_STATE)
        self.system_lock = self.state / 'system-change.lock'
        self.package_lock = self.path('/var/lib/dpkg/lock')
        self.write(self.package_lock, b'', mode=0o640)
        self.path('/run/lock').mkdir(parents=True)
        self.manager = Mock(root=self.root, owner=0, state=self.path('/service'))
        self.manager.store.path = self.path
        self.rewrap = generation.SnapshotRewrap(
            self.manager, '7838706f-fae2-4006-82c4-61d34fb75cd2', self.namespace, '5')
        self.core = Mock()
        self.unit = dict.fromkeys(generation.NATIVE_AGENT_PROPERTIES, '')
        self.unit.update(Id=generation.NATIVE_AGENT, LoadState='not-found', MainPID='0', ControlPID='0')
        self.core.command.side_effect = lambda _args: ''.join(f'{k}={v}\n' for k, v in self.unit.items())

    def write(self, path, data, mode=0o600, uid=0, gid=0):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        os.chown(path, uid, gid)

    def directory(self, path):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chown(path, self.uid, self.gid)

    def configure_agent(self):
        unit = b'paired vendor unit'
        binary = b'paired native program'
        unit_sha, binary_sha = (hashlib.sha256(raw).hexdigest() for raw in (unit, binary))
        for name, value in (
            ('NATIVE_AGENT_UNIT_SHA', unit_sha), ('NATIVE_AGENT_PROGRAM_SHA', binary_sha),
        ):
            self.enterContext(patch.object(generation, name, value))
        self.enterContext(patch.object(generation.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=self.uid)))
        self.enterContext(patch.object(generation.grp, 'getgrnam', return_value=SimpleNamespace(gr_gid=self.gid)))
        self.write(self.path(generation.NATIVE_AGENT_UNIT), unit, mode=0o644)
        program = self.path(generation.NATIVE_AGENT_PROGRAM)
        self.write(program, binary, mode=0o755)
        identity = dict(schemaVersion=1, profile='native-nonroot-v1', user=generation.NATIVE_AGENT_ACCOUNT,
                        uid=self.uid, gid=self.gid, stateDirectory=generation.NATIVE_AGENT_STATE,
                        unitSha256=unit_sha, binarySha256=binary_sha)
        self.write(self.path(generation.NATIVE_AGENT_IDENTITY), generation.encode(identity), mode=0o644)
        admin = self.path(generation.NATIVE_AGENT_ADMIN)
        self.write(admin / 'initialization.json', generation.encode(dict(identity=identity)))
        admin.chmod(0o700)
        self.directory(self.state)
        self.write(self.system_lock, b'', uid=self.uid, gid=self.gid)
        for name in ('recovery', 'recovery/staging', 'recovery/backups', 'recovery/receipts'):
            self.directory(self.state / name)
        group = '/system.slice/' + generation.NATIVE_AGENT
        self.unit.update(LoadState='loaded', ActiveState='active', MainPID='42', ControlGroup=group,
                         FragmentPath=generation.NATIVE_AGENT_UNIT, NeedDaemonReload='no', InvocationID='1' * 32,
                         User=generation.NATIVE_AGENT_ACCOUNT, Group=generation.NATIVE_AGENT_GROUP)
        self.proc = self.path('/proc/42')
        self.directory(self.proc)
        (self.proc / 'root').symlink_to(self.root)
        (self.proc / 'exe').symlink_to(program)
        environment = (
            f'AGENT_RUNTIME_IDENTITY={generation.NATIVE_AGENT_IDENTITY}\0'
            f'AGENT_STATE_DB={generation.NATIVE_AGENT_STATE}/results.sqlite\0'
        ).encode()
        self.write(self.proc / 'environ', environment)
        self.write(self.proc / 'cgroup', ('0::' + group + '\n').encode())

    def profile(self):
        with ExitStack() as locks:
            return self.rewrap.check_profile(self.policy, self.core, locks)

    def refused(self, reason, action):
        with self.assertRaisesRegex(generation.Failure, '^' + reason + '$'):
            action()

    def lock_status(self, path, api):
        return subprocess.run(
            [sys.executable, '-c',
             'import fcntl, os, sys\n'
             'fd = os.open(sys.argv[1], os.O_RDWR)\n'
             'try: getattr(fcntl, sys.argv[2])(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
             'except BlockingIOError: sys.exit(23)\n',
             path, api], check=False).returncode

    def test_standalone_still_works_and_fences_concurrent_installation(self):
        with ExitStack() as locks:
            self.assertEqual({}, self.rewrap.check_profile(self.policy, self.core, locks))
            self.assertEqual(23, self.lock_status(self.package_lock, 'lockf'))
        self.assertEqual(0, self.lock_status(self.package_lock, 'lockf'))

    def test_original_agent_writer_and_setup_are_fenced(self):
        self.configure_agent()
        with self.rewrap.agent_lock(self.system_lock, self.uid):
            self.refused('AGENT_WRITERS_ACTIVE', self.profile)
        with ExitStack() as locks:
            profile = self.rewrap.check_profile(self.policy, self.core, locks)
            self.assertEqual(self.rewrap.identity_of(self.state.stat()), profile['agentState']['directory'])
            self.assertEqual(self.rewrap.identity_of(self.system_lock.stat()), profile['agentState']['lock'])
            self.assertEqual(23, self.lock_status(self.system_lock, 'flock'))
            self.assertEqual(23, self.lock_status(self.path(generation.NATIVE_AGENT_LOCK), 'flock'))
            self.assertEqual(23, self.lock_status(self.package_lock, 'lockf'))
        self.assertEqual(0, self.lock_status(self.system_lock, 'flock'))

    def test_referenced_or_pending_history_is_preserved(self):
        self.configure_agent()
        for name in ('ordinary-boot', 'recovery/transaction.json', 'recovery/staging/old',
                     'recovery/backups/old', 'recovery/receipts/old'):
            with self.subTest(name=name):
                reference = self.state / name
                self.write(reference, b'original', uid=self.uid, gid=self.gid)
                self.refused('SNAPSHOT_HISTORY_REFERENCED', self.profile)
                self.assertEqual(b'original', reference.read_bytes())
                reference.unlink()
        self.write(self.path(generation.NATIVE_AGENT_ADMIN) / '.initialization-pending', b'original')
        self.refused('AGENT_GENERATION_UNAVAILABLE', self.profile)

    def test_unpaired_agent_runtime_is_refused(self):
        self.configure_agent()
        self.unit['DropInPaths'] = '/etc/systemd/system/unreviewed.conf'
        self.refused('AGENT_GENERATION_UNAVAILABLE', self.profile)
        self.unit['DropInPaths'] = ''
        program = self.path(generation.NATIVE_AGENT_PROGRAM)
        shadow = program.with_name('unpaired')
        self.write(shadow, program.read_bytes())
        (self.proc / 'exe').unlink()
        (self.proc / 'exe').symlink_to(shadow)
        self.refused('AGENT_GENERATION_UNAVAILABLE', self.profile)

    def continuation(self, profile):
        rewrap = self.rewrap
        manager = self.manager
        home = self.path('/opt/eclipse/kura')
        home.mkdir(parents=True)
        fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, fd)
        publication = {'generation': 2, 'operationId': 'publication'}
        cohort = {'cohortSha256': '1' * 64}
        source = {'keySha256': '2' * 64, 'ringSha256': '3' * 64}
        manager.generation_component.return_value = self.core, cohort
        manager.generation_source.return_value = (None, None, None, 2, None, source)
        self.core.current.return_value = publication
        self.core.unit.return_value = dict(ActiveState='inactive', MainPID='0', ControlPID='0')
        for owner, name, value in (
            (manager, 'lock', nullcontext()), (manager, 'exclusive_writers', nullcontext()),
            (rewrap, 'data_directory', nullcontext(fd)),
            (generation.Lifecycle, 'recovery_locked', nullcontext()),
        ):
            self.enterContext(patch.object(owner, name, return_value=value))
        self.enterContext(patch.object(generation.Lifecycle, 'no_overrides'))
        self.enterContext(patch.object(generation.Lifecycle, 'check_pending_keystore_passwords'))
        self.enterContext(patch.object(generation.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=self.uid)))
        manager.read.side_effect = lambda path, _limit: path.read_bytes()
        self.write(manager.state / 'journal.key', self.secret)
        intent = dict(schema=1, operationId=rewrap.identity, namespaceSha256=self.namespace,
                      publicationId=publication['operationId'], cohortSha256=cohort['cohortSha256'],
                      data=rewrap.identity_of(os.fstat(fd)), **source, **rewrap.selection(), **profile)
        self.write(rewrap.slot / 'intent.json', rewrap.signed(intent, self.secret, 'intent'))
        return self.enterContext(patch.object(rewrap, 'finish', return_value='continued'))

    def test_existing_standalone_intent_still_continues(self):
        finish = self.continuation({})
        self.assertEqual('continued', self.rewrap.run('continue'))
        finish.assert_called_once()

    def test_continuation_binds_both_original_agent_inodes(self):
        self.configure_agent()
        finish = self.continuation(self.profile())
        self.assertEqual('continued', self.rewrap.run('continue'))
        self.system_lock.rename(self.state / 'saved-lock')
        self.write(self.system_lock, b'', uid=self.uid, gid=self.gid)
        self.refused('PROVIDER_REWRAP_INPUT_CHANGED', lambda: self.rewrap.run('continue'))
        self.system_lock.unlink()
        (self.state / 'saved-lock').rename(self.system_lock)
        old = self.state.with_name('saved-state')
        self.state.rename(old)
        self.directory(self.state)
        (old / 'system-change.lock').rename(self.system_lock)
        self.refused('PROVIDER_REWRAP_INPUT_CHANGED', lambda: self.rewrap.run('continue'))
        finish.assert_called_once()
