#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Isolated fresh fixtures. Never read, provision, restore or restart an installed Kura."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main/resources/unfiltered/pkg/bin"))
import kura_key_service as service

CONFIG = None
PASSWORD = "fixture-only backup passphrase 42!"


class KeyServiceTest(unittest.TestCase):
    def setUp(self):
        previous_umask = os.umask(0o077)
        self.addCleanup(os.umask, previous_umask)
        self.temporary = tempfile.TemporaryDirectory(prefix="kura-key-service-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "etc/kura/credentials"
        self.state = self.root / "var/lib/kura-key-service"
        for path in [self.directory, self.state, self.state / "operations"]:
            path.mkdir(parents=True, mode=0o700)
        self.key = secrets.token_bytes(32)
        self.proof = dict(schema=1, keySha256=hashlib.sha256(self.key).hexdigest(),
                          origin="fresh", legacyKey=False, unitDigests=[])
        self.key_path = self.directory / "kura_encryption_key"
        self.receipt_path = self.directory / "provisioned.json"
        self.write(self.key_path, self.key, 0o400)
        self.write(self.receipt_path, service.encode(self.proof), 0o600)
        self.write(self.directory / ".provision.lock", b"", 0o600)
        self.write(self.state / "admission.lock", b"", 0o600)
        self.write(self.state / "journal.key", secrets.token_bytes(32), 0o600)
        self.command = [CONFIG.java, "-Xms16m", "-Xmx96m", "-XX:ActiveProcessorCount=1",
                        "-XX:+DisableAttachMechanism", "-jar", CONFIG.cipher_jar]
        self.manager = service.Manager(self.root, owner=os.geteuid(), cipher=self.command)

    @staticmethod
    def write(path, value, mode):
        # Fixture setup replaces its own old 0400 inode; it never weakens production permissions.
        staged = path.parent / (".test-setup-" + secrets.token_hex(8))
        staged.write_bytes(value)
        staged.chmod(mode)
        staged.replace(path)

    def request(self, action, **values):
        return dict(schema=1, action=action, **values)

    def backup(self, identity=None):
        identity = identity or str(uuid.uuid4())
        request = self.request("backup-create", operationId=identity, passphrase=PASSWORD)
        return request, self.manager.handle(request)

    def inspect(self, backup, password=PASSWORD):
        return self.manager.handle(self.request("backup-inspect", backup=backup, passphrase=password))

    def restore(self, backup):
        return self.manager.handle(self.request("restore", operationId=str(uuid.uuid4()),
                                               backup=backup, passphrase=PASSWORD,
                                               expectedKeySha256=self.proof["keySha256"]))

    @staticmethod
    def identity(path):
        m = path.lstat()
        return (m.st_ino, m.st_uid, m.st_gid, stat.S_IMODE(m.st_mode), m.st_nlink,
                m.st_mtime_ns, m.st_ctime_ns, path.read_bytes())

    def refused(self, reason, operation):
        with self.assertRaises(service.Failure) as caught:
            operation()
        self.assertEqual(reason, caught.exception.reason)

    def test_status_uses_receipt_and_never_changes_existing_files(self):
        before = (self.identity(self.key_path), self.identity(self.receipt_path))
        result = self.manager.handle(self.request("status"))
        self.assertTrue(result["keyReady"])
        self.assertFalse(result["agentRequired"])
        self.assertEqual(self.proof["keySha256"], result["keySha256"])
        self.assertEqual(before, (self.identity(self.key_path), self.identity(self.receipt_path)))
        self.assertEqual([], list((self.state / "operations").iterdir()))

    def test_backup_round_trip_and_private_journal_contains_no_plaintext(self):
        before = (self.identity(self.key_path), self.identity(self.receipt_path))
        request, result = self.backup()
        checked = self.inspect(result["backup"])
        self.assertTrue(checked["restoreAllowed"])
        self.assertTrue(checked["sameDeviceKey"])
        record_path = self.state / "operations" / (request["operationId"] + ".json")
        saved = record_path.read_bytes()
        self.assertNotIn(PASSWORD.encode(), saved)
        self.assertNotIn(base64.b64encode(self.key), saved)
        self.assertNotIn(self.key, base64.b64decode(result["backup"]["encrypted"]))
        self.assertEqual(0o600, stat.S_IMODE(record_path.stat().st_mode))
        self.assertEqual(before, (self.identity(self.key_path), self.identity(self.receipt_path)))

    def test_cipher_random_salt_nonce_for_same_plaintext(self):
        first = self.manager.crypt(True, PASSWORD.encode(), b"isolated fixture plaintext")
        second = self.manager.crypt(True, PASSWORD.encode(), b"isolated fixture plaintext")
        self.assertNotEqual(first, second)
        self.assertEqual(b"isolated fixture plaintext", self.manager.crypt(False, PASSWORD.encode(), first))

    def test_wrong_passphrase_refused_without_a_mutation_record(self):
        _, result = self.backup()
        count = len(list((self.state / "operations").iterdir()))
        self.refused("BACKUP_REJECTED", lambda: self.inspect(result["backup"], "wrong fixture password"))
        self.assertEqual(count, len(list((self.state / "operations").iterdir())))

    def test_tampered_ciphertext_refused(self):
        _, result = self.backup()
        envelope = dict(result["backup"])
        data = bytearray(base64.b64decode(envelope["encrypted"]))
        data[-1] ^= 1
        envelope["encrypted"] = base64.b64encode(data).decode()
        self.refused("BACKUP_REJECTED", lambda: self.inspect(envelope))

    def test_external_operation_id_cannot_be_substituted(self):
        _, result = self.backup()
        envelope = dict(result["backup"], operationId=str(uuid.uuid4()))
        self.refused("BACKUP_REJECTED", lambda: self.inspect(envelope))

    def test_same_key_restore_is_noop_preserving_inode_bytes_modes_and_receipt(self):
        _, result = self.backup()
        before = (self.identity(self.key_path), self.identity(self.receipt_path))
        restored = self.restore(result["backup"])
        self.assertFalse(restored["keyChanged"])
        self.assertTrue(restored["existingReceiptPreserved"])
        self.assertEqual(before, (self.identity(self.key_path), self.identity(self.receipt_path)))

    def test_foreign_key_restore_refused_and_current_data_unchanged(self):
        _, result = self.backup()
        foreign = secrets.token_bytes(32)
        self.write(self.key_path, foreign, 0o400)
        self.proof["keySha256"] = hashlib.sha256(foreign).hexdigest()
        self.write(self.receipt_path, service.encode(self.proof), 0o600)
        before = (self.identity(self.key_path), self.identity(self.receipt_path))
        self.assertFalse(self.inspect(result["backup"])["restoreAllowed"])
        self.refused("CONFLICT", lambda: self.restore(result["backup"]))
        self.assertEqual(before, (self.identity(self.key_path), self.identity(self.receipt_path)))

    def test_receipt_missing_never_generates_new_key_or_receipt(self):
        self.receipt_path.unlink()
        before = self.identity(self.key_path)
        with self.assertRaises(FileNotFoundError):
            self.manager.handle(self.request("status"))
        self.assertEqual(before, self.identity(self.key_path))
        self.assertFalse(self.receipt_path.exists())

    def test_missing_key_status_and_backup_do_not_provision(self):
        self.key_path.unlink()
        proof = self.identity(self.receipt_path)
        self.assertFalse(self.manager.handle(self.request("status"))["keyReady"])
        self.refused("KEY_MISSING", self.backup)
        self.assertFalse(self.key_path.exists())
        self.assertEqual(proof, self.identity(self.receipt_path))

    def test_unsafe_key_mode_refused(self):
        self.key_path.chmod(0o644)
        self.refused("UNSAFE_FILESYSTEM", lambda: self.manager.handle(self.request("status")))

    def test_symlinked_key_refused(self):
        moved = self.directory / "retained-key"
        self.key_path.rename(moved)
        self.key_path.symlink_to(moved)
        with self.assertRaises(OSError):
            self.manager.handle(self.request("status"))
        self.assertEqual(self.key, moved.read_bytes())

    def test_symlinked_parent_refused(self):
        moved = self.directory.parent / "retained-credentials"
        self.directory.rename(moved)
        self.directory.symlink_to(moved, target_is_directory=True)
        self.refused("UNSAFE_FILESYSTEM", lambda: self.manager.handle(self.request("status")))

    def test_lost_response_queries_exact_original_artifact_without_cipher(self):
        request, result = self.backup()
        self.manager.crypt = lambda *_: self.fail("read-only recovery invoked cipher")
        query = self.request("operation-read", operationId=request["operationId"])
        self.assertEqual(result, self.manager.handle(query))
        self.assertEqual(result, self.manager.handle(request))

    def test_duplicate_id_with_another_password_refused(self):
        request, _ = self.backup()
        request["passphrase"] = "different fixture password"
        self.refused("CONFLICT", lambda: self.manager.handle(request))

    def test_cached_response_with_another_original_id_is_not_a_receipt(self):
        request, result = self.backup()
        query = self.request("operation-read", operationId=request["operationId"])
        self.assertEqual(result, self.manager.handle(query))
        path = self.state / "operations" / (request["operationId"] + ".json")
        record = service.decode(path.read_bytes())
        record["response"]["operationId"] = str(uuid.uuid4())
        self.write(path, service.encode(record), 0o600)
        self.refused("UNSAFE_JOURNAL", lambda: self.manager.handle(query))

    def test_cached_backup_envelope_with_another_original_id_is_refused(self):
        request, _ = self.backup()
        path = self.state / "operations" / (request["operationId"] + ".json")
        record = service.decode(path.read_bytes())
        record["response"]["backup"]["operationId"] = str(uuid.uuid4())
        self.write(path, service.encode(record), 0o600)
        query = self.request("operation-read", operationId=request["operationId"])
        self.refused("UNSAFE_JOURNAL", lambda: self.manager.handle(query))

    def test_intent_without_result_stays_unknown_and_fences_new_writes(self):
        original = str(uuid.uuid4())
        self.manager.cipher = ["/missing-key-test-only-java"]
        self.refused("UNKNOWN", lambda: self.backup(original))
        query = self.request("operation-read", operationId=original)
        self.assertEqual("UNKNOWN", self.manager.handle(query)["state"])
        self.refused("UNRESOLVED_OPERATION", self.backup)
        self.assertEqual(self.key, self.key_path.read_bytes())

    def test_not_found_query_never_creates_an_operation(self):
        before = list((self.state / "operations").iterdir())
        result = self.manager.handle(self.request("operation-read", operationId=str(uuid.uuid4())))
        self.assertEqual("NOT_FOUND", result["state"])
        self.assertEqual(before, list((self.state / "operations").iterdir()))

    def test_schema_does_not_accept_user_paths_or_unknown_actions(self):
        self.refused("INVALID_ARGUMENT", lambda: self.manager.handle(self.request("status", path="/tmp/key")))
        self.refused("INVALID_ARGUMENT", lambda: self.manager.handle(self.request("rotate")))
        self.refused("INVALID_ARGUMENT", lambda: self.manager.handle(dict(schema=True, action="status")))

    def test_invalid_original_ids_rejected_before_filesystem_access(self):
        for identity in ("../../key", str(uuid.uuid1()), "", str(uuid.uuid4()).upper()):
            self.refused("INVALID_ARGUMENT", lambda: self.manager.handle(
                self.request("operation-read", operationId=identity)))

    def test_duplicate_json_fields_nonfinite_and_wrong_root_refused(self):
        for raw in (b'{"schema":1,"schema":1}', b'{"value":NaN}', b'[]', b'{'):
            self.refused("INVALID_ARGUMENT", lambda: service.decode(raw))

    def test_busy_installer_admission_lock_prevents_new_work(self):
        with (self.state / "admission.lock").open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.refused("BUSY", self.backup)
        self.assertEqual([], list((self.state / "operations").iterdir()))

    def test_capacity_refusal_preserves_existing_backup(self):
        request, result = self.backup()
        previous = service.MAX_OPERATIONS
        try:
            service.MAX_OPERATIONS = 1
            self.refused("CAPACITY", self.backup)
            self.assertEqual(result, self.manager.handle(self.request("operation-read", operationId=request["operationId"])))
        finally:
            service.MAX_OPERATIONS = previous

    def test_known_legacy_key_is_reported_and_preserved_without_rotation(self):
        self.key = service.CORE_DEFAULT
        self.proof.update(keySha256=hashlib.sha256(self.key).hexdigest(), legacyKey=True, origin="legacy")
        self.write(self.key_path, self.key, 0o400)
        self.write(self.receipt_path, service.encode(self.proof), 0o600)
        before = self.identity(self.key_path)
        self.assertTrue(self.manager.handle(self.request("status"))["legacyKey"])
        _, result = self.backup()
        self.assertTrue(self.inspect(result["backup"])["restoreAllowed"])
        self.assertEqual(before, self.identity(self.key_path))

    def test_cipher_worker_rejects_trailing_bytes_and_keeps_stderr_redacted(self):
        secret = b"fixture-only secret hidden value"
        frame = b"KKB1\1" + struct.pack("!I", len(secret)) + secret + struct.pack("!I", 1) + b"x" + b"trailing"
        result = subprocess.run(self.command, input=frame, capture_output=True, timeout=20,
                                env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(2, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertNotIn(secret, result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "Atomic missing-key recovery requires Linux renameat2")
    def test_missing_key_recovery_uses_matching_original_receipt(self):
        _, result = self.backup()
        retained = self.directory / "test-retained-original-key"
        self.key_path.rename(retained)
        proof = self.identity(self.receipt_path)
        restored = self.restore(result["backup"])
        self.assertTrue(restored["keyChanged"])
        self.assertEqual(self.key, self.key_path.read_bytes())
        self.assertEqual(0o400, stat.S_IMODE(self.key_path.stat().st_mode))
        self.assertEqual(1, self.key_path.stat().st_nlink)
        self.assertEqual(self.key, retained.read_bytes())
        self.assertEqual(proof, self.identity(self.receipt_path))

    @unittest.skipUnless(sys.platform == "linux", "Atomic missing-key recovery requires Linux renameat2")
    def test_restore_publication_response_loss_stays_unknown_despite_present_key(self):
        _, result = self.backup()
        self.key_path.rename(self.directory / "test-retained-original-key")
        actual = self.manager.atomic
        def publish_then_lose_response(path, *args, **kwargs):
            actual(path, *args, **kwargs)
            if path == self.key_path:
                raise OSError("fixture-only response loss")
        self.manager.atomic = publish_then_lose_response
        self.refused("UNKNOWN", lambda: self.restore(result["backup"]))
        self.assertEqual(self.key, self.key_path.read_bytes())
        intent = [service.decode(p.read_bytes()) for p in (self.state / "operations").iterdir()
                  if service.decode(p.read_bytes())["state"] == "INTENT"]
        self.assertEqual(1, len(intent))
        query = self.request("operation-read", operationId=intent[0]["operationId"])
        self.assertEqual("UNKNOWN", self.manager.handle(query)["state"])
        self.refused("UNRESOLVED_OPERATION", self.backup)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cipher-jar", required=True)
    parser.add_argument("--java", default="/usr/bin/java")
    CONFIG, remaining = parser.parse_known_args()
    unittest.main(argv=[sys.argv[0], *remaining])
