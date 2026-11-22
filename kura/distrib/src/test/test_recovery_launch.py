#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_recovery_launch as launch
import kura_recovery_main_command as commands
from kura_key_service import Failure, Lifecycle, Manager


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Linux Root fixture required')
class LaunchProjectionTest(unittest.TestCase):
    identity = 'rec-11111111-1111-4111-8111-111111111111'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base = self.root / 'launch'
        self.base.mkdir(mode=0o750)
        self.target = self.base / self.identity
        self.target.mkdir(mode=0o750)
        self.output = self.target / launch.OUT
        self.output.mkdir(mode=0o700)
        self.contents = b'exact staged snapshot'
        self.plan = dict(schema=1, restoreId=self.identity, root=launch.root_identity(self.root),
                         bindingSha256='a' * 64, activeKeySha256='b' * 64, ringSha256=None,
                         cohortSha256='c' * 64, bootstrapSha256='d' * 64, size=len(self.contents),
                         snapshotSha256=launch.digest(self.contents), mode='aes-gcm', passwordPolicy='authenticated')
        launch.write(self.target / launch.PLAN, launch.canonical(self.plan), 0o440)
        launch.write(self.target / launch.SNAPSHOT, self.contents, 0o440)
        launch.write(self.target / launch.REQUEST, launch.properties(self.target, self.plan), 0o440)

    def read(self, root=None):
        return launch.projection(self.base, self.identity, 0, 0, root or self.root)

    def test_projection_binds_snapshot_request_and_root(self):
        self.assertEqual((self.target, self.plan), self.read())
        with self.assertRaises(ValueError):
            self.read(self.base)
        snapshot = self.target / launch.SNAPSHOT
        snapshot.unlink()
        snapshot.symlink_to(self.target / launch.PLAN)
        with self.assertRaises(OSError):
            self.read()

    def test_request_replacement_and_non_private_result_directory_refused(self):
        request = self.target / launch.REQUEST
        request.unlink()
        changed = launch.properties(self.target, self.plan).replace(b'snapshot_0.xml', b'snapshot_1.xml')
        launch.write(request, changed, 0o440)
        with self.assertRaises(ValueError):
            self.read()
        request.unlink()
        launch.write(request, launch.properties(self.target, self.plan), 0o440)
        self.output.chmod(0o750)
        with self.assertRaises(ValueError):
            self.read()

    def test_claim_requires_exact_lease_and_cannot_be_replaced(self):
        lease = dict(keySha256=self.plan['activeKeySha256'], ringSha256=None,
                     cohortSha256=self.plan['cohortSha256'], startTicks='5')
        with patch.dict(os.environ, INVOCATION_ID='a' * 32):
            with self.assertRaises(ValueError):
                launch.claim(self.target, self.plan, lease | {'cohortSha256': 'e' * 64})
            self.assertFalse((self.output / launch.CLAIM).exists())
            launch.claim(self.target, self.plan, lease)
            with self.assertRaises(FileExistsError):
                launch.claim(self.target, self.plan, lease)
        saved = json.loads((self.output / launch.CLAIM).read_bytes())
        self.assertEqual(self.identity, saved['restoreId'])
        self.assertEqual(launch.digest(launch.canonical(self.plan)), saved['planSha256'])
        self.assertEqual(os.getpid(), saved['pid'])

    def test_fixed_condition_issues_only_one_systemd_invocation(self):
        fixed = dict(restoreId=self.identity)
        with patch.dict(os.environ, {}, clear=True), patch.object(launch, 'selection', return_value=fixed), \
                patch.object(launch, 'unit_invocation', return_value='a' * 32), \
                patch.object(launch, 'select_projection', return_value=(self.target, self.plan)):
            launch.condition(self.root)
            marker = (self.output / launch.CONDITION).read_bytes()
            with self.assertRaises(ValueError):
                launch.condition(self.root)
            self.assertEqual(marker, (self.output / launch.CONDITION).read_bytes())

    def test_guarded_snapshot_must_be_latest_exact_and_regular(self):
        parent = self.root / launch.NORMAL_SNAPSHOTS.lstrip('/')
        parent.mkdir(parents=True, mode=0o700)
        snapshot = parent / 'snapshot_7.xml'
        launch.write(snapshot, self.contents, 0o600)
        plan = self.plan | {'guarded': {'snapshotId': '7'}}
        launch.normal_snapshot(self.root, plan, 0, 0)
        newer = parent / 'snapshot_8.xml'
        launch.write(newer, self.contents, 0o600)
        with self.assertRaises(ValueError):
            launch.normal_snapshot(self.root, plan, 0, 0)
        newer.unlink()
        snapshot.unlink()
        launch.write(snapshot, b'other contents', 0o600)
        with self.assertRaises(ValueError):
            launch.normal_snapshot(self.root, plan, 0, 0)
        snapshot.unlink()
        snapshot.symlink_to(self.target / launch.SNAPSHOT)
        with self.assertRaises(OSError):
            launch.normal_snapshot(self.root, plan, 0, 0)

    def test_guarded_marker_keeps_original_selection_and_pins_new_plan(self):
        fixed = dict(restoreId=self.identity)
        normal = self.plan | {'guarded': {'snapshotId': '7'}}
        marker = launch.condition_marker(fixed, normal, 'a' * 32)
        self.assertEqual(launch.digest(launch.canonical(fixed)), marker['selectionSha256'])
        self.assertEqual(launch.digest(launch.canonical(normal)), marker['guardedSha256'])
        self.assertEqual('a' * 32, marker['invocationId'])
        self.assertNotEqual(marker, launch.condition_marker(fixed, self.plan, 'a' * 32))

    def test_guarded_status_preserves_uncertain_publication_on_original_number(self):
        manager = Mock()
        manager.state = self.root
        manager.lock.return_value = nullcontext()
        lifecycle = SimpleNamespace(path=lambda _: self.base, root=self.root)
        recovery = SimpleNamespace(manager=manager, lifecycle=lifecycle,
                                   observation=lambda identity, state: dict(schema=1, restoreId=identity, state=state,
                                                                            root=self.plan['root']))
        with patch.object(commands.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1001, pw_gid=1001)):
            controller = commands.Controller(recovery)
        controller.observation = Mock(return_value={'state': 'MAIN_STOPPED', 'receiptSha256': 'e' * 64})
        controller.load = Mock(return_value=None)
        controller.projection = Mock(return_value=(self.target, self.plan))
        self.assertEqual('GUARDED_MAIN_ABSENT', controller.guarded_status(self.identity)['state'])
        (self.target / '.guarded-pending').mkdir(mode=0o700)
        status = controller.guarded_status(self.identity)
        self.assertEqual('GUARDED_MAIN_START_UNKNOWN', status['state'])
        self.assertEqual(self.identity, status['restoreId'])
        controller.load.return_value = controller.observation.return_value
        controller.guarded_source = Mock(return_value=(self.target, self.plan, {}))
        with self.assertRaisesRegex(Failure, 'MAIN_COMMAND_EXISTS'):
            controller.start_guarded(self.identity, 'e' * 64, '7')
        manager.generation_component.assert_not_called()

    def test_lost_start_reply_keeps_original_intent_and_never_dispatches_again(self):
        manager = Manager(self.root, 0)
        policy = Lifecycle(self.root, 0)
        for name in ('/var/lib/kura-key-service/admission.lock', '/etc/kura/credentials/.provision.lock'):
            path = policy.path(name)
            policy.directory(path.parent, private=True, create=True)
            policy.create(path, b'')
        manager.maintenance = Mock()
        manager.settled = Mock()
        manager.generation_start_authorized = Mock()
        manager.generation_source = Mock(return_value=(None, None, None, None, None,
            dict(keySha256=self.plan['activeKeySha256'], ringSha256=None)))
        component = Mock()
        component.command.side_effect = Failure('SYSTEMD_UNAVAILABLE')
        manager.generation_component = Mock(return_value=(component, {'cohortSha256': self.plan['cohortSha256']}))
        manager.writer_lock = lambda **kwargs: os.open('/dev/null', os.O_RDONLY)
        manager.exclusive_writers = nullcontext
        with patch.object(commands.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1001, pw_gid=1001)):
            controller = commands.Controller(SimpleNamespace(manager=manager, lifecycle=policy,
                observation=lambda identity, state: dict(schema=1, restoreId=identity, state=state,
                                                       root=self.plan['root'])))
        controller.base = self.base
        controller.projection = Mock(return_value=(self.target, self.plan))
        os.chown(self.base, 0, 1001)
        fingerprint = launch.digest(launch.canonical(self.plan))
        with self.assertRaisesRegex(Failure, 'UNKNOWN'):
            controller.start(self.identity, fingerprint)
        original = controller.observation(self.identity)
        self.assertEqual('MAIN_START_UNKNOWN', original['state'])
        self.assertEqual(self.identity, original['restoreId'])
        with self.assertRaisesRegex(Failure, 'MAIN_SELECTION_EXISTS'):
            controller.start(self.identity, fingerprint)
        self.assertEqual(original, controller.observation(self.identity))
        component.command.assert_called_once_with(commands.START, timeout=18)


if __name__ == '__main__':
    unittest.main()
