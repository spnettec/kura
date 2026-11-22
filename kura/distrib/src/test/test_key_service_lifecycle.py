#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Package admission and retention contracts using new private fixture trees."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import types
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main/resources/unfiltered/pkg/bin"))
import kura_key_service as service
import kura_key_service_lifecycle as lifecycle


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        previous_umask = os.umask(0o077)
        self.addCleanup(os.umask, previous_umask)
        self.temporary = tempfile.TemporaryDirectory(prefix="kura-key-package-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.calls = []
        self.states = {name: "inactive" for name in (*lifecycle.UNITS, "kura.service")}
        self.fail_stop = False
        self.policy = lifecycle.Lifecycle(self.root, os.geteuid(), self.runner)
        self.physical = self.root / "opt/eclipse/kura_test"
        self.physical.mkdir(parents=True, mode=0o750)
        (self.physical.parent / "kura").symlink_to(self.physical, target_is_directory=True)
        for name in lifecycle.ASSETS:
            value=(Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg'/name).read_bytes() if name=='bin/kura_key_journal.py' else ("fixture asset " + name).encode()
            self.write(self.physical / name, value, 0o640)
        for name in lifecycle.UNITS:
            self.write(self.root / "lib/systemd/system" / name, ("fixture unit " + name).encode(), 0o644)
        (self.root / "run/systemd/system").mkdir(parents=True)
        self.manifest()
        directory = self.root / "etc/kura/credentials"
        directory.mkdir(parents=True, mode=0o700)
        self.key = secrets.token_bytes(32)
        self.write(directory / "kura_encryption_key", self.key, 0o400)
        proof = dict(schema=1, keySha256=hashlib.sha256(self.key).hexdigest(), origin="fresh",
                     legacyKey=False, unitDigests=[])
        self.write(directory / "provisioned.json", json.dumps(proof).encode(), 0o600)
        self.write(directory / ".provision.lock", b"", 0o600)

    def runner(self, args, **_kwargs):
        self.calls.append(args)
        command = args[1]
        result = ""
        code = 0
        if command == "show":
            name = args[2]
            loaded = "loaded" if name in self.states else "not-found"
            result = "LoadState=" + loaded + "\nActiveState=" + self.states.get(name, "inactive") + "\nMainPID=0\nControlPID=0\n"
        elif command == "stop":
            if self.fail_stop:
                code = 1
            else:
                self.states[args[2]] = "inactive"
        return types.SimpleNamespace(returncode=code, stdout=result, stderr="")

    @staticmethod
    def write(path, value, mode=0o600):
        path.parent.mkdir(parents=True, exist_ok=True)
        staged = path.parent / (".test-setup-" + secrets.token_hex(8))
        staged.write_bytes(value)
        staged.chmod(mode)
        staged.replace(path)

    def manifest(self):
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        value = dict(schema=1, protocol=1, files={name: digest(self.physical / name) for name in lifecycle.ASSETS},
                     units={name: digest(self.root / "lib/systemd/system" / name) for name in lifecycle.UNITS})
        self.write(self.physical / "libexec/key-backup/manifest.json", json.dumps(value).encode(), 0o640)

    def opened(self):
        marker = self.policy.enter("install")
        self.policy.leave()
        self.calls.clear()
        return marker

    def operation(self, pending=False):
        identity = str(uuid.uuid4())
        response = dict(schema=1, operationId=identity, state="SUCCEEDED", action="restore",
                        keySha256=hashlib.sha256(self.key).hexdigest(), keyChanged=False,
                        existingReceiptPreserved=True)
        record = dict(schema=1, operationId=identity, action="restore", requestTag="a" * 64,
                      state="INTENT" if pending else "SUCCEEDED", response=None if pending else response)
        path = self.policy.state / "operations" / (identity + ".json")
        self.write(path, lifecycle.encoded(record))
        return path

    def data_identity(self):
        result = {}
        for name in ["etc/kura/credentials/kura_encryption_key", "etc/kura/credentials/provisioned.json"]:
            path = self.root / name;m = path.lstat()
            result[name] = (m.st_ino,m.st_uid,m.st_gid,stat.S_IMODE(m.st_mode),m.st_mtime_ns,m.st_ctime_ns,path.read_bytes())
        return result

    def test_initial_admission_creates_private_independent_journal_and_fence(self):
        before = self.data_identity()
        marker = self.policy.enter("install")
        self.assertEqual("MAINTENANCE", marker["state"])
        self.assertEqual(32, len((self.policy.state / "journal.key").read_bytes()))
        self.assertEqual(0o700, stat.S_IMODE(self.policy.state.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE((self.policy.state / "journal.key").stat().st_mode))
        self.assertEqual(before, self.data_identity())
        stops = [args[2] for args in self.calls if args[1] == "stop"]
        self.assertEqual(list(lifecycle.UNITS), stops)

    def test_native_validation_manifest_pairs_the_two_units_and_maintainer_stops_listener_first(self):
        self.assertEqual(set(lifecycle.UNITS), set(self.policy.assets()['units']))
        path = self.physical / 'libexec/key-backup/manifest.json'
        updated = json.loads(path.read_bytes())
        asset = 'bin/kura_native_snapshot_validation.py'
        self.write(self.physical / asset, b'native validation asset', 0o644)
        updated['files'][asset] = hashlib.sha256(b'native validation asset').hexdigest()
        updated.update(schema=2, protocol=2, generation={})
        self.write(path, lifecycle.encoded(updated), 0o640)
        with self.assertRaisesRegex(lifecycle.Refused, 'Unrecognized key-service package profile'):
            self.policy.assets()
        for unit in lifecycle.VALIDATION_UNITS:
            raw = unit.encode()
            self.write(self.root / 'lib/systemd/system' / unit, raw, 0o644)
            updated['units'][unit] = hashlib.sha256(raw).hexdigest()
            self.states[unit] = 'active'
        self.write(path, lifecycle.encoded(updated), 0o640)
        self.assertEqual(updated, self.policy.assets())
        self.policy.stop_units()
        stopped = [args[2] for args in self.calls if args[1] == 'stop']
        self.assertEqual(list(lifecycle.NATIVE_VALIDATION_UNITS), stopped)

    def test_reentrant_install_preserves_fence_id_and_journal_key(self):
        original = self.policy.enter("upgrade")
        path = self.policy.state / "journal.key"
        before = (path.stat().st_ino,path.stat().st_mtime_ns,path.read_bytes())
        self.assertEqual(original, self.policy.enter("install"))
        self.assertEqual(before,(path.stat().st_ino,path.stat().st_mtime_ns,path.read_bytes()))

    def test_package_reentry_can_install_new_units_while_original_fence_is_held(self):
        original = self.policy.enter("upgrade")
        self.write(self.physical / "bin/kura_key_service.py", b"new unpacked fixture code",0o640)
        self.assertEqual(original,self.policy.enter("install"))
        with self.assertRaises(lifecycle.Refused):
            self.policy.leave()
        self.assertTrue((self.policy.state / "maintenance.json").exists())

    def test_pending_deployment_publication_refuses_upgrade_and_remove_before_stop(self):
        self.opened()
        registry = self.physical / 'packages/dpa.properties'
        target = self.physical / 'data/site-registry'
        self.write(target, b'previous entry')
        registry.parent.mkdir()
        registry.symlink_to(target)
        receipt = target.with_name('.site-registry.publication')
        self.write(receipt, b'original deployment receipt')
        inode = receipt.stat().st_ino

        for action in ('upgrade', 'remove'):
            with self.subTest(action=action), self.assertRaisesRegex(lifecycle.ActiveWriter, 'original deployment'):
                self.policy.enter(action)
        self.assertFalse(any(call[1] == 'stop' for call in self.calls))
        self.assertIsNone(self.policy.fence())
        self.assertEqual(inode, receipt.stat().st_ino)
        self.assertEqual(b'original deployment receipt', receipt.read_bytes())

    def test_deployment_receipt_appearing_during_main_stop_preserves_original_fence(self):
        fence = self.policy.enter('upgrade')
        receipt = self.physical / 'packages/.dpa.properties.publication'
        receipt.parent.mkdir()
        # An interrupted first install may have no published registry yet.
        receipt.symlink_to('missing')
        with self.assertRaisesRegex(lifecycle.ActiveWriter, 'original deployment'):
            self.policy.check_package_writers()
        self.assertTrue(receipt.is_symlink())
        self.assertEqual(fence, self.policy.fence())
        receipt.unlink()
        self.policy.check_package_writers()
        self.assertEqual(fence, self.policy.enter('upgrade'))

    def test_pending_pkcs12_change_blocks_package_entry_and_stopped_copy(self):
        directory = self.physical / "data" / "site" / (".kura-keystore-" + "a" * 64)
        directory.mkdir(parents=True)
        first = directory / ("password-change-" + "b" * 64)
        second = directory / ("password-change-" + "c" * 64)
        first.write_bytes(b"private provider record")
        os.link(first, second)
        before = first.stat()
        for action in ("upgrade", "remove"):
            with self.assertRaisesRegex(lifecycle.ActiveWriter, "PKCS12"):
                self.policy.enter(action)
            self.assertFalse((self.policy.state / "maintenance.json").exists())
        first.unlink()
        with self.assertRaisesRegex(lifecycle.ActiveWriter, "PKCS12"):
            self.policy.check_package_writers()
        self.assertEqual(second.stat().st_ino, before.st_ino)
        self.assertEqual(second.read_bytes(), b"private provider record")
        second.unlink()
        (directory / "password-change.tmp").touch()
        self.policy.check_package_writers()

    def test_password_scan_does_not_follow_links_or_match_unrelated_names(self):
        outside = self.root / "elsewhere" / (".kura-keystore-" + "d" * 64)
        outside.mkdir(parents=True)
        (outside / ("password-change-" + "e" * 64)).touch()
        (self.physical / "external").symlink_to(outside.parent, target_is_directory=True)
        (self.physical / ("password-change-" + "f" * 64)).touch()
        self.policy.check_package_writers()

    def test_direct_writer_refuses_maintenance_before_fencing_or_stopping_units(self):
        self.opened()
        path = self.root / 'run/kura-key-service/writers/lease.lock'
        self.write(path, b'')
        path.parent.chmod(0o700)
        with path.open('rb') as writer:
            fcntl.flock(writer, fcntl.LOCK_SH | fcntl.LOCK_NB)
            with self.assertRaises(lifecycle.Refused):
                self.policy.enter('upgrade')
            self.assertIsNone(self.policy.fence())
            self.assertFalse(any(call[1] == 'stop' for call in self.calls))
        self.assertEqual('upgrade', self.policy.enter('upgrade')['firstAction'])

    def test_managed_main_may_drain_but_no_writer_can_survive_the_stop(self):
        lease = self.root / 'run/kura-key-service/writers/lease.lock'
        self.write(lease, b'')
        lease.parent.chmod(0o700)
        process = self.root / 'proc/432'
        process.mkdir(parents=True)
        (process / 'stat').write_text('432 (java) ' + ' '.join(['0'] * 19 + ['123']))
        boot = str(uuid.uuid4())
        self.write(self.root / 'proc/sys/kernel/random/boot_id', boot.encode())
        info = lease.stat()
        record = lease.parent / '432-123.json'
        self.write(record, lifecycle.encoded(dict(schema=1, state='LEASE_GRANTED', pid=432, startTicks='123',
                                                 bootId=boot, uid=process.stat().st_uid,
                                                 lockDevice=info.st_dev, lockInode=info.st_ino)))
        self.policy.runner = lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout='MainPID=432\n')
        with lease.open('rb') as main, lease.open('rb') as direct:
            fcntl.flock(main, fcntl.LOCK_SH)
            fcntl.flock(direct, fcntl.LOCK_SH)
            self.policy.check_package_writers(allow_main=True)
            fcntl.flock(main, fcntl.LOCK_UN)
            record.unlink()
            with self.assertRaises(lifecycle.ActiveWriter):
                self.policy.check_package_writers()
            with self.assertRaises(lifecycle.ActiveWriter):
                self.policy.check_package_writers(allow_main=True)
        self.policy.check_package_writers()

    def test_active_operation_refuses_before_fencing_or_stopping(self):
        self.opened()
        with (self.policy.state / "admission.lock").open("rb") as stream:
            fcntl.flock(stream,fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(lifecycle.Refused):
                self.policy.enter("upgrade")
        self.assertFalse((self.policy.state / "maintenance.json").exists())
        self.assertFalse(any(args[1] == "stop" for args in self.calls))

    def test_unknown_operation_refuses_before_fencing_or_stopping(self):
        self.opened();path=self.operation(pending=True);before=path.read_bytes()
        with self.assertRaises(lifecycle.Refused):
            self.policy.enter("upgrade")
        self.assertEqual(before,path.read_bytes())
        self.assertFalse((self.policy.state / "maintenance.json").exists())
        self.assertFalse(any(args[1] == "stop" for args in self.calls))

    def test_retained_original_receipt_survives_enter_leave(self):
        self.opened();path=self.operation();before=(path.stat().st_ino,path.read_bytes())
        data=self.data_identity();secret=(self.policy.state / "journal.key").read_bytes()
        self.policy.enter("upgrade");self.policy.leave()
        self.assertEqual(before,(path.stat().st_ino,path.read_bytes()))
        self.assertEqual(data,self.data_identity())
        self.assertEqual(secret,(self.policy.state / "journal.key").read_bytes())

    def test_missing_journal_secret_with_saved_operation_is_never_replaced(self):
        self.opened();self.operation();secret=self.policy.state / "journal.key";secret.unlink()
        with self.assertRaises(lifecycle.Refused):
            self.policy.enter("upgrade")
        self.assertFalse(secret.exists())
        self.assertFalse(any(args[1] == "stop" for args in self.calls))

    def test_altered_original_response_is_not_a_terminal_receipt(self):
        self.opened();path=self.operation();record=json.loads(path.read_text())
        record["response"]["operationId"]=str(uuid.uuid4());self.write(path,lifecycle.encoded(record))
        with self.assertRaises(lifecycle.Refused):
            self.policy.enter("remove")
        self.assertFalse(any(args[1] == "stop" for args in self.calls))

    def test_manager_stop_failure_preserves_fence_and_data(self):
        self.opened();before=self.data_identity();self.fail_stop=True
        with self.assertRaises(lifecycle.Refused):
            self.policy.enter("upgrade")
        self.assertTrue((self.policy.state / "maintenance.json").exists())
        self.assertEqual(before,self.data_identity())

    def test_fenced_daemon_rejects_operations_before_worker_or_key_changes(self):
        self.policy.enter("upgrade")
        manager=service.Manager(self.root,os.geteuid(),cipher=["/missing-test-worker"])
        for request in [dict(schema=1,action="status"),dict(schema=1,action="operation-read",operationId=str(uuid.uuid4())),
                        dict(schema=1,action="backup-create",operationId=str(uuid.uuid4()),passphrase="test fixture password")]:
            with self.assertRaises(service.Failure) as caught:
                manager.handle(request)
            self.assertEqual("MAINTENANCE",caught.exception.reason)
        self.assertEqual([],list((self.policy.state / "operations").iterdir()))

    def test_successful_leave_removes_only_fence(self):
        self.policy.enter("install");before=self.data_identity()
        self.policy.leave()
        self.assertFalse((self.policy.state / "maintenance.json").exists())
        self.assertEqual(before,self.data_identity())
        self.assertTrue(service.Manager(self.root,os.geteuid()).handle(dict(schema=1,action="status"))["keyReady"])

    def test_changed_asset_keeps_installation_fenced(self):
        self.policy.enter("install")
        self.write(self.physical / "libexec/key-backup/kura-key-crypto.jar",b"different fixture artifact",0o640)
        with self.assertRaises(lifecycle.Refused):self.policy.leave()
        self.assertTrue((self.policy.state / "maintenance.json").exists())

    def test_archive_script_is_attested_before_package_can_leave_maintenance(self):
        self.policy.enter('install');before=self.data_identity()
        self.write(self.physical/'share/key-recovery/archive.js',b'changed archive browser asset',0o640)
        with self.assertRaises(lifecycle.Refused):self.policy.leave()
        self.assertIsNotNone(self.policy.fence());self.assertEqual(before,self.data_identity())

    def journal_v1_profile(self):
        path=self.physical/'libexec/key-backup/manifest.json';value=json.loads(path.read_bytes())
        value['files'].pop('share/key-recovery/archive.js');(self.physical/'share/key-recovery/archive.js').unlink()
        self.write(path,lifecycle.encoded(value),0o640)
        self.assertEqual(lifecycle.JOURNAL_V1_ASSETS,frozenset(self.policy.assets()['files']))

    def test_original_journal_package_profile_still_records_its_positive_package_handoff(self):
        self.journal_v1_profile();before=self.data_identity();marker=self.policy.enter('upgrade');self.policy.leave()
        record=json.loads((self.policy.state/'package-history'/(marker['id']+'.json')).read_bytes())
        self.assertEqual(marker['id'],record['maintenanceId']);self.assertEqual('upgrade',record['firstAction'])
        self.assertTrue((self.policy.state/'startups').is_dir());self.assertIsNone(self.policy.fence());self.assertEqual(before,self.data_identity())

    def test_original_journal_package_profile_does_not_bypass_unknown_admission(self):
        self.journal_v1_profile();self.policy.enter('install');self.policy.leave();self.calls.clear()
        self.operation(pending=True);before=self.data_identity()
        with self.assertRaises(lifecycle.Refused):self.policy.enter('upgrade')
        self.assertTrue(all(call[1]=='show' for call in self.calls));self.assertIsNone(self.policy.fence());self.assertEqual(before,self.data_identity())

    def test_missing_canonical_key_cannot_unfence_the_online_service(self):
        self.policy.enter("install")
        path=self.root / "etc/kura/credentials/kura_encryption_key"
        path.rename(path.parent / "test-retained-key")
        with self.assertRaises(service.Failure):self.policy.leave()
        self.assertTrue((self.policy.state / "maintenance.json").exists())
        self.assertFalse(path.exists())

    def test_unreviewed_override_refused_before_state_creation(self):
        self.write(self.root / "etc/systemd/system/kura-key-service.service",b"unknown fixture unit",0o644)
        with self.assertRaises(lifecycle.Refused):self.policy.enter("install")
        self.assertFalse(self.policy.state.exists())

    def test_hierarchical_or_generic_dropin_refused_before_state_creation(self):
        for name in ["kura-.service.d","kura-key-.socket.d","service.d"]:
            directory=self.root / "etc/systemd/system" / name
            self.write(directory / "override.conf",b"[Service]\nNoNewPrivileges=false\n",0o644)
            with self.assertRaises(lifecycle.Refused):self.policy.enter("install")
            self.assertFalse(self.policy.state.exists())
            (directory / "override.conf").unlink()

    def test_writable_empty_dropin_directory_is_not_trusted(self):
        directory=self.root / "etc/systemd/system/kura-key-service.service.d"
        directory.mkdir(parents=True);directory.chmod(0o777)
        with self.assertRaises(lifecycle.Refused):self.policy.enter("install")
        self.assertFalse(self.policy.state.exists())

    def test_unsafe_journal_key_permissions_preserve_state(self):
        self.opened();path=self.policy.state / "journal.key";path.chmod(0o644)
        with self.assertRaises(lifecycle.Refused):self.policy.enter("upgrade")
        self.assertFalse((self.policy.state / "maintenance.json").exists())

    def test_remove_units_retains_backup_journal_and_credentials(self):
        self.opened();path=self.operation();before=path.read_bytes();data=self.data_identity()
        self.policy.enter("remove");self.policy.remove_units()
        self.assertEqual(before,path.read_bytes());self.assertEqual(data,self.data_identity())
        self.assertTrue((self.policy.state / "maintenance.json").exists())
        self.assertTrue((self.policy.state / "journal.key").exists())
        self.assertTrue(all(not (self.root / "lib/systemd/system" / name).exists() for name in lifecycle.UNITS))

    def test_invalid_fence_is_not_replaced_or_cleared(self):
        self.policy.enter("upgrade");path=self.policy.state / "maintenance.json"
        self.write(path,b'{"schema":1,"state":"MAINTENANCE","extra":true}')
        before=path.read_bytes()
        with self.assertRaises(lifecycle.Refused):self.policy.enter("install")
        self.assertEqual(before,path.read_bytes())

    def test_missing_lock_with_old_operations_is_not_recreated(self):
        self.opened();self.operation();path=self.policy.state / "admission.lock";path.unlink()
        with self.assertRaises(lifecycle.Refused):self.policy.enter("upgrade")
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
