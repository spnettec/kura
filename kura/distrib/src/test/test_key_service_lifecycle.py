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
            self.write(self.physical / name, ("fixture asset " + name).encode(), 0o640)
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
            result = "LoadState=loaded\nActiveState=" + self.states[name] + "\nMainPID=0\nControlPID=0\n"
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
