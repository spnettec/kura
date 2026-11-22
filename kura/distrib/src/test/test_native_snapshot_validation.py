"""Peer and dispatch contracts for the dedicated native snapshot socket."""

from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_native_snapshot_validation as broker


class NativeSnapshotValidationTest(unittest.TestCase):
    def setUp(self):
        self.peer = (459, 991, 992, 5)
        self.raw = b'{"profile":"native-nonroot-v1","uid":991,"gid":992,"readerGid":993}'
        self.unit = dict(Id=broker.AGENT, LoadState='loaded', FragmentPath=broker.VENDOR_UNIT,
                         DropInPaths='', NeedDaemonReload='no', ActiveState='active', MainPID='459',
                         InvocationID='1' * 32, ControlGroup='/system.slice/' + broker.AGENT,
                         User=broker.ACCOUNT, Group='kura-management')
        self.attestation = dict(schema=1, purpose=broker.PURPOSE, invocationId=self.unit['InvocationID'],
                                bootId='current-boot', rootDevice=201, rootInode=18,
                                identitySha256=hashlib.sha256(self.raw).hexdigest())
        self.lifecycle = Mock()
        self.lifecycle.read.side_effect = lambda path, **kwargs: (
            json.dumps(self.attestation).encode() if path == broker.ATTESTATION else self.raw)
        status = dict(Uid='991 991 991 991', Gid='992 992 992 992', Groups='992 993', NoNewPrivs='1')
        status.update({name: '0' for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')})
        self.status = status
        for target in (
            patch.object(broker.pwd, 'getpwnam', return_value=SimpleNamespace(
                pw_uid=991, pw_gid=993, pw_dir='/nonexistent', pw_shell='/usr/sbin/nologin')),
            patch.object(broker.grp, 'getgrnam', side_effect=lambda name: SimpleNamespace(
                gr_gid=992 if name == 'kura-management' else 993)),
            patch.object(broker, 'unit_state', side_effect=lambda: self.unit.copy()),
            patch.object(broker, 'verify_alive'),
            patch.object(broker, 'proc_status', return_value=self.status),
            patch.object(broker, 'proc_file', return_value=('0::/system.slice/' + broker.AGENT + '\n').encode()),
            patch.object(broker, 'BOOT_ID', SimpleNamespace(read_text=lambda: 'current-boot\n')),
            patch.object(broker.os, 'stat', return_value=SimpleNamespace(st_dev=201, st_ino=18)),
        ):
            target.start()
            self.addCleanup(target.stop)

    def test_live_main_and_current_root_attestation_admit_the_peer(self):
        self.assertEqual(self.attestation, broker.live_agent(self.lifecycle, self.peer))

    def test_same_account_outside_main_is_refused(self):
        with self.assertRaisesRegex(broker.Failure, 'FORBIDDEN'):
            broker.live_agent(self.lifecycle, (460, *self.peer[1:]))

    def test_attestation_cannot_cross_boot_root_or_invocation(self):
        for key, value in [('bootId', 'prior-boot'), ('rootInode', 19), ('invocationId', '2' * 32),
                           ('identitySha256', 'a' * 64)]:
            with self.subTest(key=key), patch.dict(self.attestation, {key: value}):
                with self.assertRaisesRegex(broker.Failure, 'FORBIDDEN'):
                    broker.live_agent(self.lifecycle, self.peer)

    def test_stale_unit_and_extra_group_are_refused(self):
        with patch.dict(self.unit, {'NeedDaemonReload': 'yes'}):
            with self.assertRaisesRegex(broker.Failure, 'FORBIDDEN'):
                broker.live_agent(self.lifecycle, self.peer)
        with patch.dict(self.status, {'Groups': '991 992 993'}):
            with self.assertRaisesRegex(broker.Failure, 'FORBIDDEN'):
                broker.live_agent(self.lifecycle, self.peer)

    def test_route_only_dispatches_read_operations_with_expected_fd_shape(self):
        manager = Mock()
        with self.assertRaisesRegex(broker.Failure, 'FORBIDDEN'):
            broker.validation_request(manager, {'action': 'backup-create'}, None, 991)
        manager.validation_component.assert_not_called()
        info = {'schema': 1, 'action': 'core-validation-info'}
        validate = {'schema': 1, 'action': 'core-snapshot-validate'}
        inventory = {'schema': 1, 'action': 'core-snapshot-inventory'}
        for request, descriptor in [(info, 8), (validate, None), (inventory, 8)]:
            with self.assertRaisesRegex(broker.Failure, 'PROTOCOL_MISMATCH'):
                broker.validation_request(manager, request, descriptor, 991)
        broker.validation_request(manager, info, None, 991)
        broker.validation_request(manager, validate, 8, 991)
        broker.validation_request(manager, inventory, None, 991)
        validator = manager.validation_component.return_value
        validator.info.assert_called_once_with(info)
        validator.validate.assert_called_once_with(validate, 8, 991, core_uid=991)
        core = broker.pwd.getpwnam('kurad')
        validator.snapshot_inventory.assert_called_once_with(inventory, core.pw_uid, core.pw_gid)

    def test_peer_change_after_worker_prevents_release_and_closes_the_fd(self):
        stream = Mock()
        request = ({'action': 'core-snapshot-validate'}, 8)
        with patch.object(broker, 'socket_peer', return_value=nullcontext(self.peer)), \
                patch.object(broker, 'live_agent', side_effect=[{'current': 1}, {'current': 2}]), \
                patch.object(broker, 'read_request_frame', return_value=request), \
                patch.object(broker, 'validation_request'), patch.object(broker, 'send_frame') as send, \
                patch.object(broker.os, 'close') as close:
            broker.serve_one(stream, self.lifecycle, Mock())
            send.assert_called_once_with(stream, {'schema': 1, 'error': 'FORBIDDEN'})
            close.assert_called_once_with(8)
