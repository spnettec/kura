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
from unittest.mock import patch
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
        # Storage/crypto fixtures have no installed Core. Real package/boot pairing
        # (including refusal) is covered with actual built JARs in the cohort suite.
        pairing = patch.object(self.manager, 'require_generation_cohort')
        pairing.start(); self.addCleanup(pairing.stop)

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


    def generation_fixture(self):
        keys = [service.CORE_DEFAULT, secrets.token_bytes(24), self.key]
        raw = service.RING_MAGIC + bytes([3, 2, 0]) + b"".join(bytes([len(key)]) + key for key in keys)
        self.write(self.directory / "kura_encryption_keyring", raw, 0o400)
        _, metadata = service.key_generations(raw)
        self.write(self.directory / "key-generations.json",
                   service.encode(dict(schema=1, purpose=service.GENERATION_FORMAT, **metadata)), 0o600)
        return raw

    def generation_backup(self, identity=None):
        return self.manager.handle(self.request("generation-backup-create", operationId=identity or str(uuid.uuid4()),
                                                passphrase=PASSWORD))

    def generation_inspect(self, backup, password=PASSWORD):
        return self.manager.handle(self.request("generation-backup-inspect", backup=backup, passphrase=password))

    def generation_identity(self):
        return tuple(self.identity(self.directory / name) if (self.directory / name).exists() else None for name in
                     ("kura_encryption_key", "provisioned.json", "kura_encryption_keyring", "key-generations.json"))

    def test_generation_backup_keeps_every_key_and_does_not_modify_credentials(self):
        raw = self.generation_fixture()
        before = self.generation_identity()
        paths = [self.directory / name for name in ("kura_encryption_keyring", "key-generations.json")]
        original = [(p.read_bytes(), p.stat().st_ino, p.stat().st_mode, p.stat().st_mtime_ns) for p in paths]
        result = self.generation_backup()
        self.assertEqual(service.GENERATION_FORMAT, result["backup"]["format"])
        recovered, metadata, _ = self.manager.unpack_generations(result["backup"], PASSWORD.encode())
        self.assertEqual(raw, recovered)
        self.assertEqual(3, len(metadata["keySha256s"]))
        self.assertEqual(hashlib.sha256(service.CORE_DEFAULT).hexdigest(), metadata["legacyKeySha256"])
        self.assertEqual(before, self.generation_identity())
        self.assertEqual(original, [(p.read_bytes(), p.stat().st_ino, p.stat().st_mode, p.stat().st_mtime_ns) for p in paths])
        journal = (self.state / "operations" / (result["operationId"] + ".json")).read_bytes()
        self.assertNotIn(base64.b64encode(raw), journal)
        self.assertNotIn(self.key, journal)
        self.assertNotIn(service.CORE_DEFAULT, journal)
        inspected = self.generation_inspect(result["backup"])
        self.assertTrue(inspected["matchesRetainedReceipt"])
        self.assertEqual(self.manager.generation_restore_supported(), inspected["restoreSupported"])
        self.assertNotIn("keyring", inspected)
        self.assertNotIn("receipt", inspected)

    def test_generation_inspection_matches_retained_binding_when_keys_are_missing(self):
        self.generation_fixture()
        backup = self.generation_backup()["backup"]
        (self.directory / "kura_encryption_keyring").unlink()
        self.key_path.unlink()
        before = sorted(p.name for p in (self.state / "operations").iterdir())
        result = self.generation_inspect(backup)
        self.assertTrue(result["matchesRetainedReceipt"])
        self.assertFalse(result["activeKeyReady"])
        self.assertEqual(self.manager.generation_restore_supported(), result["restoreSupported"])
        self.assertFalse(self.key_path.exists())
        self.assertFalse((self.directory / "kura_encryption_keyring").exists())
        self.assertEqual(before, sorted(p.name for p in (self.state / "operations").iterdir()))
        self.refused("GENERATION_REQUIRED", self.backup)

    def test_generation_binding_is_required_before_backup_and_never_synthesized(self):
        self.generation_fixture()
        binding = self.directory / "key-generations.json"
        binding.unlink()
        before = self.generation_identity()
        self.refused("KEY_GENERATIONS_MISSING", self.generation_backup)
        self.assertFalse(binding.exists())
        self.assertEqual(before, self.generation_identity())
        self.assertEqual([], list((self.state / "operations").iterdir()))

    def test_generation_backup_rejects_an_unbound_key_or_generation_set(self):
        raw = self.generation_fixture()
        ring = self.directory / "kura_encryption_keyring"
        self.write(ring, raw[:-32] + secrets.token_bytes(32), 0o400)
        self.refused("UNSAFE_FILESYSTEM", self.generation_backup)
        # Keep the same active key; replacing an older generation is still a conflict.
        altered = bytearray(raw)
        altered[len(service.RING_MAGIC) + 3 + 1] ^= 1
        self.write(ring, bytes(altered), 0o400)
        self.refused("UNSAFE_FILESYSTEM", self.generation_backup)
        self.assertEqual([], list((self.state / "operations").iterdir()))

    def test_generation_inspect_distinguishes_same_active_key_from_same_complete_set(self):
        raw = self.generation_fixture()
        backup = self.generation_backup()["backup"]
        altered = bytearray(raw)
        altered[len(service.RING_MAGIC) + 3 + 1] ^= 1
        _, metadata = service.key_generations(bytes(altered))
        self.write(self.directory / "key-generations.json",
                   service.encode(dict(schema=1, purpose=service.GENERATION_FORMAT, **metadata)), 0o600)
        result = self.generation_inspect(backup)
        self.assertFalse(result["matchesRetainedReceipt"])
        self.assertEqual(self.proof["keySha256"], result["activeKeySha256"])
        self.assertEqual(self.manager.generation_restore_supported(), result["restoreSupported"])

    def test_generation_backup_rejects_wrong_password_tampering_and_external_id(self):
        self.generation_fixture()
        backup = self.generation_backup()["backup"]
        self.refused("BACKUP_REJECTED", lambda: self.generation_inspect(backup, PASSWORD + "wrong"))
        altered = dict(backup)
        ciphertext = bytearray(base64.b64decode(backup["encrypted"]))
        ciphertext[-1] ^= 1
        altered["encrypted"] = base64.b64encode(ciphertext).decode()
        self.refused("BACKUP_REJECTED", lambda: self.generation_inspect(altered))
        altered = dict(backup, operationId=str(uuid.uuid4()))
        self.refused("BACKUP_REJECTED", lambda: self.generation_inspect(altered))
        self.assertEqual(1, len(list((self.state / "operations").iterdir())))

    def test_generation_backup_purpose_cannot_be_relabelled_as_a_single_key_backup(self):
        single = self.backup()[1]["backup"]
        self.generation_fixture()
        multiple = self.generation_backup()["backup"]
        with self.assertRaises(service.Failure):
            self.generation_inspect(dict(single, format=service.GENERATION_FORMAT))
        with self.assertRaises(service.Failure):
            self.manager.unpack(dict(multiple, format=service.FORMAT), PASSWORD.encode())
        self.assertEqual(2, len(list((self.state / "operations").iterdir())))

    def test_generation_backup_original_result_reads_do_not_reencrypt(self):
        self.generation_fixture()
        identity = str(uuid.uuid4())
        original = self.generation_backup(identity)
        with patch.object(self.manager, "crypt", side_effect=AssertionError("No cipher on original-result reads")):
            self.assertEqual(original, self.manager.handle(self.request("operation-read", operationId=identity)))
            self.assertEqual(original, self.generation_backup(identity))
        self.refused("CONFLICT", lambda: self.manager.handle(self.request("generation-backup-create", operationId=identity,
                                                                        passphrase=PASSWORD + "different")))

    def test_generation_backup_ambiguous_result_remains_unknown_and_fences_new_ids(self):
        self.generation_fixture()
        identity = str(uuid.uuid4())
        before = self.generation_identity()
        original_atomic = self.manager.atomic
        def lose_result(path, value, **options):
            if service.decode(value).get("state") == "SUCCEEDED":
                raise OSError("Fixture simulates a lost result before final journal publication")
            return original_atomic(path, value, **options)
        with patch.object(self.manager, "atomic", side_effect=lose_result):
            self.refused("UNKNOWN", lambda: self.generation_backup(identity))
        with patch.object(self.manager, "crypt", side_effect=AssertionError("UNKNOWN must not dispatch")):
            result = self.manager.handle(self.request("operation-read", operationId=identity))
            self.assertEqual("UNKNOWN", result["state"])
            self.assertEqual(result, self.generation_backup(identity))
            self.refused("UNRESOLVED_OPERATION", self.generation_backup)
        self.assertEqual(before, self.generation_identity())
        self.assertEqual([identity + ".json"], [p.name for p in (self.state / "operations").iterdir()])

    def test_generation_journal_cannot_be_downgraded_to_single_key_format(self):
        self.generation_fixture()
        original = self.generation_backup()
        path = self.state / "operations" / (original["operationId"] + ".json")
        record = service.decode(path.read_bytes())
        record["response"]["backup"]["format"] = service.FORMAT
        self.write(path, service.encode(record), 0o600)
        self.refused("UNSAFE_JOURNAL", lambda: self.manager.handle(self.request("operation-read", operationId=original["operationId"])))
        self.refused("UNSAFE_JOURNAL", self.generation_backup)

    def test_single_key_backup_and_restore_are_fenced_even_when_ring_is_missing(self):
        backup = self.backup()[1]["backup"]
        self.generation_fixture()
        (self.directory / "kura_encryption_keyring").unlink()
        before = self.generation_identity()
        self.refused("GENERATION_REQUIRED", self.backup)
        self.refused("GENERATION_REQUIRED", lambda: self.restore(backup))
        self.assertEqual(before, self.generation_identity())
        self.assertEqual(1, len(list((self.state / "operations").iterdir())))

    def test_generation_ring_symlinks_and_dangling_entries_never_allow_single_key_fallback(self):
        self.generation_fixture()
        ring = self.directory / "kura_encryption_keyring"
        ring.unlink()
        ring.symlink_to(self.directory / "does-not-exist")
        self.refused("GENERATION_REQUIRED", self.backup)
        self.refused("UNSAFE_FILESYSTEM", self.generation_backup)
        self.assertEqual([], list((self.state / "operations").iterdir()))

    def test_recovery_peer_cannot_export_a_generation_set(self):
        self.generation_fixture()
        for action in ("generation-backup-create", "generation-start-admission"):
            self.refused("FORBIDDEN", lambda: self.manager.handle(dict(schema=1, action=action), recovery_only=True))
        self.assertEqual([], list((self.state / "operations").iterdir()))

    def test_generation_ring_codec_rejects_ambiguous_or_incomplete_generations(self):
        raw = self.generation_fixture()
        prefix = service.RING_MAGIC
        duplicate = prefix + bytes([2, 0, 1, 32]) + self.key + bytes([32]) + self.key
        legacy_active = prefix + bytes([2, 0, 1, 16]) + service.CORE_DEFAULT + bytes([32]) + self.key
        for value in (b"", raw[:len(prefix) + 2], raw[:-1], raw + b"x", raw + b"x" * 512,
                      b"x" + raw[1:], prefix + bytes([1, 0, 0]) + raw[len(prefix) + 3:],
                      prefix + bytes([9, 0, 1]) + raw[len(prefix) + 3:],
                      prefix + bytes([3, 2, 2]) + raw[len(prefix) + 3:], duplicate, legacy_active):
            with self.subTest(size=len(value)):
                with self.assertRaises(service.Failure):
                    service.key_generations(value)


    def generation_restore(self, backup, *, recovery_only=False, identity=None, expected=None):
        request = self.request("generation-restore", operationId=identity or str(uuid.uuid4()),
                               backup=backup, passphrase=PASSWORD,
                               expectedRingSha256=expected or self.manager.generation_receipt()["ringSha256"])
        return self.manager.handle(request, recovery_only=recovery_only)

    def send_as(self, request, uid=None):
        user = os.geteuid() if uid is None else uid
        result, descriptor = service.serve_request(self.manager, request, os.getpid(), user, 20001, 20002, None)
        self.assertIsNone(descriptor)
        return result

    def restore_sender(self, request):
        return dict(source='local-admin', namespaceSha256=self.manager.gwt_namespace()['namespaceSha256'],
                    admissionId=str(uuid.uuid4()), request=request)

    def generation_boot_admission(self):
        metadata = self.manager.generation_receipt()
        return self.manager.handle(self.request("generation-start-admission", ringSha256=metadata["ringSha256"],
                                               activeKeySha256=metadata["activeKeySha256"]))

    def test_generation_restore_of_existing_identical_set_preserves_all_inodes(self):
        self.generation_fixture()
        backup = self.generation_backup()["backup"]
        before = self.generation_identity()
        result = self.generation_restore(backup)
        self.assertFalse(result["activeKeyRestored"])
        self.assertFalse(result["keyringRestored"])
        self.assertTrue(result["existingReceiptPreserved"])
        self.assertEqual(before, self.generation_identity())
        with patch.object(self.manager, "crypt", side_effect=AssertionError("Original result is read-only")):
            read = self.manager.handle(self.request("operation-read", operationId=result["operationId"]), recovery_only=True)
        self.assertEqual(result, read)
        self.assertEqual("GENERATION_READY", self.generation_boot_admission()["state"])

    @unittest.skipUnless(sys.platform == "linux", "Linux atomic original-credential publication")
    def test_generation_restore_publishes_only_missing_original_pair(self):
        raw = self.generation_fixture()
        backup = self.generation_backup()["backup"]
        receipts = [self.receipt_path, self.directory / "key-generations.json"]
        originals = [self.identity(p) for p in receipts]
        self.key_path.unlink()
        ring = self.directory / "kura_encryption_keyring"
        ring.unlink()
        request = self.request("generation-backup-inspect", backup=backup, passphrase=PASSWORD)
        inspected = self.manager.handle(request, recovery_only=True)
        self.assertTrue(inspected["restoreAllowed"])
        self.assertFalse(inspected["activeKeyReady"])
        self.assertFalse(inspected["keyringReady"])
        result = self.generation_restore(backup, recovery_only=True)
        self.assertTrue(result["activeKeyRestored"])
        self.assertTrue(result["keyringRestored"])
        self.assertEqual(self.key, self.key_path.read_bytes())
        self.assertEqual(raw, ring.read_bytes())
        self.assertEqual(0o400, stat.S_IMODE(ring.stat().st_mode))
        self.assertEqual(0o400, stat.S_IMODE(self.key_path.stat().st_mode))
        self.assertEqual(1, ring.stat().st_nlink)
        self.assertEqual(originals, [self.identity(p) for p in receipts])
        self.assertEqual("GENERATION_READY", self.generation_boot_admission()["state"])
        self.refused("CONFLICT", lambda: self.generation_restore(backup, recovery_only=True))

    @unittest.skipUnless(sys.platform == "linux", "Linux atomic original-credential publication")
    def test_generation_restore_keeps_the_existing_half_byte_and_metadata_exact(self):
        self.generation_fixture()
        backup = self.generation_backup()["backup"]
        ring = self.directory / "kura_encryption_keyring"
        for missing, retained in ((ring, self.key_path), (self.key_path, ring)):
            with self.subTest(missing=missing.name):
                missing.unlink()
                original = self.identity(retained)
                result = self.generation_restore(backup)
                self.assertEqual(missing == ring, result["keyringRestored"])
                self.assertEqual(missing == self.key_path, result["activeKeyRestored"])
                self.assertEqual(original, self.identity(retained))

    def test_generation_restore_refuses_a_different_complete_set_before_intent(self):
        raw = self.generation_fixture()
        backup = self.generation_backup()["backup"]
        altered = bytearray(raw)
        altered[len(service.RING_MAGIC) + 4] ^= 1
        _, metadata = service.key_generations(bytes(altered))
        self.write(self.directory / "key-generations.json",
                   service.encode(dict(schema=1, purpose=service.GENERATION_FORMAT, **metadata)), 0o600)
        before = self.generation_identity()
        self.refused("CONFLICT", lambda: self.generation_restore(backup))
        self.assertEqual(before, self.generation_identity())
        self.assertEqual(1, len(list((self.state / "operations").iterdir())))

    def test_generation_restore_never_replaces_an_existing_wrong_keyring(self):
        raw = self.generation_fixture()
        backup = self.generation_backup()["backup"]
        ring = self.directory / "kura_encryption_keyring"
        self.write(ring, raw[:-1] + bytes([raw[-1] ^ 1]), 0o400)
        before = self.generation_identity()
        self.refused("CONFLICT", lambda: self.generation_restore(backup))
        self.assertEqual(before, self.generation_identity())
        self.assertEqual(1, len(list((self.state / "operations").iterdir())))

    @unittest.skipUnless(sys.platform == "linux", "Linux atomic original-credential publication")
    def test_partial_generation_restore_is_unknown_and_fences_startup_and_new_ids(self):
        self.generation_fixture()
        backup = self.generation_backup()["backup"]
        self.key_path.unlink()
        ring = self.directory / "kura_encryption_keyring"
        ring.unlink()
        identity = str(uuid.uuid4())
        rename = service.rename_no_replace
        def lose_key(staged, destination):
            if destination == self.key_path:
                raise OSError("Fixture loses publication of the second original credential")
            return rename(staged, destination)
        with patch.object(service, 'rename_no_replace', side_effect=lose_key):
            self.refused("UNKNOWN", lambda: self.generation_restore(backup, identity=identity))
        self.assertTrue(ring.is_file())
        self.assertFalse(self.key_path.exists())
        with patch.object(self.manager, "crypt", side_effect=AssertionError("UNKNOWN must not dispatch")):
            self.assertEqual("UNKNOWN", self.generation_restore(backup, identity=identity)["state"])
            self.refused("UNRESOLVED_OPERATION", lambda: self.generation_restore(backup))
        self.refused("UNRESOLVED_OPERATION", self.generation_boot_admission)
        inspected = self.generation_inspect(backup)
        self.assertTrue(inspected["matchesRetainedReceipt"])
        self.assertFalse(inspected["restoreAllowed"])
        self.assertTrue(inspected["restoreBlockedByUnresolvedOperation"])

    @unittest.skipUnless(sys.platform == "linux", "Linux atomic original-credential publication")
    def test_present_keys_do_not_settle_a_generation_restore_with_a_lost_result(self):
        self.generation_fixture()
        backup = self.generation_backup()["backup"]
        self.key_path.unlink()
        (self.directory / "kura_encryption_keyring").unlink()
        identity = str(uuid.uuid4())
        atomic = self.manager.atomic
        def lose_result(path, value, **options):
            if path.parent == self.state / "operations" and service.decode(value)["state"] == "SUCCEEDED":
                raise OSError("Fixture loses the final restore result")
            return atomic(path, value, **options)
        with patch.object(self.manager, "atomic", side_effect=lose_result):
            self.refused("UNKNOWN", lambda: self.generation_restore(backup, identity=identity))
        before = self.generation_identity()
        inspected = self.generation_inspect(backup)
        self.assertTrue(inspected["activeKeyReady"])
        self.assertTrue(inspected["keyringReady"])
        self.assertFalse(inspected["restoreAllowed"])
        self.refused("UNRESOLVED_OPERATION", self.generation_boot_admission)
        self.assertEqual("UNKNOWN", self.manager.handle(self.request("operation-read", operationId=identity))["state"])
        self.assertEqual(before, self.generation_identity())

    @unittest.skipUnless(sys.platform == "linux", "Linux atomic original-credential publication")
    def test_generation_restore_no_replace_survives_a_concurrent_foreign_key(self):
        self.generation_fixture()
        backup = self.generation_backup()["backup"]
        self.key_path.unlink()
        (self.directory / "kura_encryption_keyring").unlink()
        foreign = secrets.token_bytes(32)
        rename = service.rename_no_replace
        def race(staged, destination):
            if destination == self.key_path:
                self.write(destination, foreign, 0o400)
            return rename(staged, destination)
        with patch.object(service, 'rename_no_replace', side_effect=race):
            self.refused("UNKNOWN", lambda: self.generation_restore(backup))
        self.assertEqual(foreign, self.key_path.read_bytes())
        self.refused("UNRESOLVED_OPERATION", self.generation_boot_admission)

    @unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Linux Root sender and no-replace rename')
    def test_generation_restore_continues_through_sender_only_from_original_staged_inodes(self):
        raw = self.generation_fixture()
        backup = self.generation_backup()['backup']
        ring = self.directory / 'kura_encryption_keyring'
        ring.unlink()
        self.key_path.unlink()
        self.write(self.state / 'sender-admission.lock', b'', 0o600)
        identity = str(uuid.uuid4())
        original = self.restore_sender(self.request('generation-restore', operationId=identity, backup=backup,
            passphrase=PASSWORD, expectedRingSha256=self.manager.generation_receipt()['ringSha256']))
        receipt = self.identity(self.receipt_path)
        generation = self.identity(self.directory / 'key-generations.json')
        rename = service.rename_no_replace

        def lose_key(staged, destination):
            if destination == self.key_path:
                raise OSError('Fixture interrupts the active key rename')
            return rename(staged, destination)

        self.assertEqual('RESERVED', self.send_as(self.request('sender-reserve', **original))['state'])
        with patch.object(service, 'rename_no_replace', side_effect=lose_key):
            self.refused('UNKNOWN', lambda: self.send_as(self.request('sender-command', **original)))
        ring_identity = self.identity(ring)
        staged_key = self.manager.generation_restore_stage(self.key_path, identity, 'activeKey')
        staged_inode = staged_key.stat().st_ino
        read = self.request('generation-restore-read', operationId=identity)
        view = self.send_as(read)
        self.assertEqual('UNKNOWN', view['state'])
        self.assertFalse(view['startupAuthorized'])
        self.refused('FORBIDDEN', lambda: self.send_as(read, uid=20001))
        self.refused('FORBIDDEN', lambda: self.send_as(read, uid=20002))
        self.refused('UNRESOLVED_OPERATION', self.generation_boot_admission)
        namespace = self.manager.gwt_namespace()
        with patch.object(self.manager, 'gwt_namespace', return_value=dict(namespace, namespaceSha256='9' * 64)):
            self.refused('CONFLICT', lambda: self.send_as(read))
        original_path = self.state / 'operations' / (identity + '.json')
        original_bytes = original_path.read_bytes()
        altered = service.decode(original_bytes)
        altered['intent']['receiptTag'] = '0' * 64
        self.write(original_path, service.encode(altered), 0o600)
        self.refused('UNSAFE_JOURNAL', lambda: self.send_as(read))
        self.write(original_path, original_bytes, 0o600)
        recover = self.request('generation-restore-recover', operationId=identity,
                               expectedRestoreIntentSha256=view['restoreIntentSha256'])
        self.refused('FORBIDDEN', lambda: self.send_as(recover))
        incorrect = self.restore_sender(dict(recover, expectedRestoreIntentSha256='0' * 64))
        self.refused('CONFLICT', lambda: self.send_as(self.request('sender-reserve', **incorrect)))
        continuation = self.restore_sender(recover)

        # A copy of the correct key is not proof that the staged inode reached
        # the canonical name. Refuse before spending the continuation.
        self.write(self.key_path, self.key, 0o400)
        self.refused('CONFLICT', lambda: self.send_as(self.request('sender-reserve', **continuation)))
        self.key_path.unlink()
        with patch.object(self.manager, 'crypt', side_effect=AssertionError('No backup redispatch')):
            reserved = self.send_as(self.request('sender-reserve', **continuation))
            self.assertEqual(identity, reserved['nativeOperationId'])
            result = self.send_as(self.request('sender-command', **continuation))
        self.assertTrue(result['keyringRestored'] and result['activeKeyRestored'])
        self.assertEqual(result, self.send_as(read)['originalResult'])
        self.assertEqual(raw, ring.read_bytes())
        self.assertEqual(ring_identity, self.identity(ring))
        self.assertEqual(staged_inode, self.key_path.stat().st_ino)
        self.assertFalse(staged_key.exists())
        self.assertEqual(receipt, self.identity(self.receipt_path))
        self.assertEqual(generation, self.identity(self.directory / 'key-generations.json'))
        self.assertEqual('GENERATION_READY', self.generation_boot_admission()['state'])
        original_row = self.manager.sender_admissions.load(original['admissionId'])
        next_row = self.manager.sender_admissions.load(continuation['admissionId'])
        self.assertEqual(('TERMINAL', 'TERMINAL'), (original_row['state'], next_row['state']))
        self.assertEqual(original_row['admissionId'], next_row['parentAdmissionId'])

    def test_generation_restore_does_not_recover_an_unsigned_original_intent(self):
        self.generation_fixture()
        identity = str(uuid.uuid4())
        record = dict(schema=1, operationId=identity, action='generation-restore',
                      requestTag='1' * 64, state='INTENT', response=None)
        self.write(self.state / 'operations' / (identity + '.json'), service.encode(record), 0o600)
        view = self.manager.handle(self.request('generation-restore-read', operationId=identity))
        self.assertIsNone(view['restoreIntentSha256'])
        self.assertEqual('UNKNOWN', view['state'])
        request = self.request('generation-restore-recover', operationId=identity,
                               expectedRestoreIntentSha256='1' * 64)
        self.refused('UNRESOLVED_OPERATION', lambda: self.manager.handle(request))
        self.refused('UNRESOLVED_OPERATION', self.generation_boot_admission)

    def test_generation_startup_and_restore_are_fenced_by_an_original_unknown_start(self):
        self.generation_fixture()
        backup = self.generation_backup()["backup"]
        starts = self.state / "startups"
        starts.mkdir(mode=0o700)
        identity = str(uuid.uuid4())
        record = dict(schema=1, operationId=identity, restoreOperationId=str(uuid.uuid4()),
                      keySha256=self.proof["keySha256"], requestTag="1" * 64, state="INTENT", response=None)
        self.write(starts / (identity + ".json"), service.encode(record), 0o600)
        before = self.generation_identity()
        self.refused("UNRESOLVED_OPERATION", self.generation_boot_admission)
        self.refused("UNRESOLVED_OPERATION", self.generation_backup)
        self.refused("UNRESOLVED_OPERATION", lambda: self.generation_restore(backup))
        inspected = self.generation_inspect(backup)
        self.assertFalse(inspected["restoreAllowed"])
        self.assertTrue(inspected["restoreBlockedByUnresolvedOperation"])
        self.assertEqual(before, self.generation_identity())

    def prepare_request(self, identity=None):
        ring = self.directory / "kura_encryption_keyring"
        source = dict(keySha256=self.proof["keySha256"], ringSha256=None)
        if os.path.lexists(ring):
            source["ringSha256"] = hashlib.sha256(ring.read_bytes()).hexdigest()
        return self.request("generation-prepare", operationId=identity or str(uuid.uuid4()),
                            expectedSource=source, passphrase=PASSWORD)

    def verification_request(self, prepared, identity=None):
        return self.request("generation-backup-verify", operationId=identity or str(uuid.uuid4()),
                            preparationId=prepared["operationId"], passphrase=PASSWORD,
                            expectedRingSha256=prepared["generation"]["ringSha256"], backup=prepared["backup"])

    def test_generation_encoder_keeps_order_and_rejects_invalid_indices_lengths_and_duplicates(self):
        keys = [service.CORE_DEFAULT, secrets.token_bytes(24), self.key]
        raw = service.encode_key_generations(keys, 2, 0)
        self.assertEqual((keys, 2, 0), service.key_generation_entries(raw))
        for entries, active, legacy in ((keys, True, 0), (keys, 2, 2), ([self.key, self.key], 1, 0),
                                        ([b"short", self.key], 1, 0), (keys, 0, 2)):
            with self.subTest(active=active, legacy=legacy), self.assertRaises(service.Refused):
                service.encode_key_generations(entries, active, legacy)

    def test_generation_preparation_rejects_unbound_source_and_recovery_peer_before_any_intent(self):
        request = self.prepare_request()
        request["expectedSource"]["keySha256"] = "a" * 64
        self.refused("CONFLICT", lambda: self.manager.handle(request))
        request = self.prepare_request()
        request["expectedSource"]["ringSha256"] = "b" * 64
        self.refused("CONFLICT", lambda: self.manager.handle(request))
        for action in ("generation-prepare", "generation-backup-verify"):
            self.refused("FORBIDDEN", lambda: self.manager.handle(self.request(action), recovery_only=True))
        self.assertEqual([], list((self.state / "operations").iterdir()))
        self.assertFalse((self.state / "generations").exists())

    def test_generation_preparation_refuses_capacity_without_retiring_any_old_key(self):
        keys = [service.CORE_DEFAULT, *[secrets.token_bytes(32) for _ in range(6)], self.key]
        raw = service.encode_key_generations(keys, 7, 0)
        self.write(self.directory / "kura_encryption_keyring", raw, 0o400)
        _, metadata = service.key_generations(raw)
        self.write(self.directory / "key-generations.json", service.encode(dict(schema=1, purpose=service.GENERATION_FORMAT, **metadata)), 0o600)
        before = self.generation_identity()
        self.refused("CAPACITY", lambda: self.manager.handle(self.prepare_request()))
        self.assertEqual(before, self.generation_identity())
        self.assertEqual([], list((self.state / "operations").iterdir()))

    @unittest.skipUnless(sys.platform == "linux", "Immutable preparation requires Linux renameat2")
    def test_prepare_and_verify_legacy_key_retains_all_material_without_changing_canonical_state(self):
        self.key = service.CORE_DEFAULT
        self.proof.update(keySha256=hashlib.sha256(self.key).hexdigest(), legacyKey=True, origin="legacy")
        self.write(self.key_path, self.key, 0o400)
        self.write(self.receipt_path, service.encode(self.proof), 0o600)
        before = self.generation_identity()
        prepared = self.manager.handle(self.prepare_request())
        raw, history, _ = self.manager.prepared_generation(prepared["operationId"])
        keys, active, legacy = service.key_generation_entries(raw)
        self.assertEqual([16, 32], [len(key) for key in keys])
        self.assertEqual(self.key, keys[legacy])
        self.assertEqual(1, active)
        self.assertNotEqual(self.key, keys[active])
        self.assertFalse(prepared["published"])
        self.assertTrue(prepared["requiresExplicitCommit"])
        self.assertEqual(self.proof, history["sourceReceipt"])
        self.assertFalse(history["provisioned"]["legacyKey"])
        directory = self.state / "generations" / prepared["operationId"]
        for path in directory.iterdir():
            self.assertEqual(0o400, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(1, path.stat().st_nlink)
        saved = (self.state / "operations" / (prepared["operationId"] + ".json")).read_bytes()
        for secret in [PASSWORD.encode(), *[base64.b64encode(key) for key in keys]]:
            self.assertNotIn(secret, saved)
            self.assertNotIn(secret, (directory / "history.json").read_bytes())
        verified = self.manager.handle(self.verification_request(prepared))
        self.assertEqual(hashlib.sha256(service.encode(prepared["backup"])).hexdigest(), verified["backupSha256"])
        self.assertFalse(verified["published"])
        self.assertEqual(before, self.generation_identity())
        self.manager.settled()

    @unittest.skipUnless(sys.platform == "linux", "Immutable preparation requires Linux renameat2")
    def test_prepare_existing_generations_preserves_exact_original_ring_order_and_legacy_selector(self):
        original = self.generation_fixture()
        before = self.generation_identity()
        prepared = self.manager.handle(self.prepare_request())
        raw, _, _ = self.manager.prepared_generation(prepared["operationId"])
        old_keys, _, old_legacy = service.key_generation_entries(original)
        keys, active, legacy = service.key_generation_entries(raw)
        self.assertEqual(old_keys, keys[:-1])
        self.assertEqual(old_legacy, legacy)
        self.assertEqual(len(old_keys), active)
        self.assertEqual(original, (self.state / "generations" / prepared["operationId"] / "source-keyring").read_bytes())
        self.manager.handle(self.verification_request(prepared))
        self.assertEqual(before, self.generation_identity())
        self.assertEqual(self.proof["keySha256"], self.generation_boot_admission()["activeKeySha256"])

    @unittest.skipUnless(sys.platform == "linux", "Immutable preparation requires Linux renameat2")
    def test_preparation_result_read_never_generates_again_or_replaces_immutable_history(self):
        request = self.prepare_request()
        prepared = self.manager.handle(request)
        directory = self.state / "generations" / prepared["operationId"]
        before = {p.name: self.identity(p) for p in directory.iterdir()}
        with patch.object(self.manager, "crypt", side_effect=AssertionError("Result read must not encrypt")), \
                patch.object(service.secrets, "token_bytes", side_effect=AssertionError("Result read must not generate")):
            self.assertEqual(prepared, self.manager.handle(request))
            self.assertEqual(prepared, self.manager.handle(self.request("operation-read", operationId=prepared["operationId"])))
            self.refused("PREPARATION_PENDING", lambda: self.manager.handle(self.prepare_request()))
        self.assertEqual(before, {p.name: self.identity(p) for p in directory.iterdir()})
        changed = dict(request, passphrase="a different fixture passphrase")
        self.refused("CONFLICT", lambda: self.manager.handle(changed))

    @unittest.skipUnless(sys.platform == "linux", "Immutable preparation requires Linux renameat2")
    def test_preparation_partial_write_stays_unknown_and_blocks_new_ids_startup_and_package(self):
        self.generation_fixture()
        request = self.prepare_request()
        before = self.generation_identity()
        original = self.manager.atomic
        def lose_history(path, value, **options):
            if path.name == "history.json":
                raise OSError("fixture interrupted history publication")
            return original(path, value, **options)
        with patch.object(self.manager, "atomic", side_effect=lose_history):
            self.refused("UNKNOWN", lambda: self.manager.handle(request))
        with patch.object(self.manager, "crypt", side_effect=AssertionError("Unknown must not dispatch")), \
                patch.object(service.secrets, "token_bytes", side_effect=AssertionError("Unknown must not generate")):
            self.assertEqual("UNKNOWN", self.manager.handle(request)["state"])
            self.refused("UNRESOLVED_OPERATION", lambda: self.manager.handle(self.prepare_request()))
            self.refused("UNRESOLVED_OPERATION", self.generation_boot_admission)
        self.assertEqual(before, self.generation_identity())
        self.assertTrue((self.state / "generations" / request["operationId"] / "keyring").is_file())
        with self.assertRaises(service.LifecycleUnresolved):
            service.Lifecycle(self.root, os.geteuid()).check_records()

    @unittest.skipUnless(sys.platform == "linux", "Immutable preparation requires Linux renameat2")
    def test_preparation_lost_final_result_does_not_infer_success_from_present_keys(self):
        request = self.prepare_request()
        original = self.manager.atomic
        def lose_result(path, value, **options):
            if path.parent == self.state / "operations" and service.decode(value)["state"] == "SUCCEEDED":
                raise OSError("fixture lost final receipt")
            return original(path, value, **options)
        with patch.object(self.manager, "atomic", side_effect=lose_result):
            self.refused("UNKNOWN", lambda: self.manager.handle(request))
        directory = self.state / "generations" / request["operationId"]
        self.assertEqual({"keyring", "history.json"}, {p.name for p in directory.iterdir()})
        with patch.object(self.manager, "crypt", side_effect=AssertionError("Unknown must not dispatch")):
            self.assertEqual("UNKNOWN", self.manager.handle(request)["state"])
            self.refused("UNRESOLVED_OPERATION", lambda: self.manager.handle(self.prepare_request()))

    @unittest.skipUnless(sys.platform == "linux", "Immutable preparation requires Linux renameat2")
    def test_prepare_worker_failure_is_unknown_and_does_not_change_active_credentials(self):
        before = self.generation_identity()
        request = self.prepare_request()
        with patch.object(self.manager, "crypt", side_effect=service.Failure("BACKUP_REJECTED")):
            self.refused("UNKNOWN", lambda: self.manager.handle(request))
        self.assertEqual(before, self.generation_identity())
        self.assertEqual("UNKNOWN", self.manager.handle(self.request("operation-read", operationId=request["operationId"]))["state"])

    @unittest.skipUnless(sys.platform == "linux", "Immutable preparation requires Linux renameat2")
    def test_verification_refuses_wrong_password_tampering_and_relabelled_or_wrong_backup_before_intent(self):
        self.generation_fixture()
        prepared = self.manager.handle(self.prepare_request())
        request = self.verification_request(prepared)
        attempts = [dict(request, passphrase="wrong fixture passphrase"), dict(request, expectedRingSha256="b" * 64)]
        changed = bytearray(base64.b64decode(prepared["backup"]["encrypted"]))
        changed[-1] ^= 1
        attempts += [dict(request, backup=dict(prepared["backup"], encrypted=base64.b64encode(changed).decode())),
                     dict(request, backup=dict(prepared["backup"], operationId=str(uuid.uuid4())))]
        original_backup = self.generation_backup()["backup"]
        attempts.append(dict(request, backup=original_backup))
        before = {p.name: p.read_bytes() for p in (self.state / "operations").iterdir()}
        for candidate in attempts:
            self.refused("BACKUP_REJECTED", lambda: self.manager.handle(candidate))
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.state / "operations").iterdir()})

    @unittest.skipUnless(sys.platform == "linux", "Immutable preparation requires Linux renameat2")
    def test_verification_is_durable_original_result_only_and_does_not_reopen_a_preparation(self):
        prepared = self.manager.handle(self.prepare_request())
        request = self.verification_request(prepared)
        result = self.manager.handle(request)
        with patch.object(self.manager, "crypt", side_effect=AssertionError("Verification read must not decrypt")):
            self.assertEqual(result, self.manager.handle(request))
            self.assertEqual(result, self.manager.handle(self.request("operation-read", operationId=request["operationId"])))
        self.refused("ALREADY_VERIFIED", lambda: self.manager.handle(self.verification_request(prepared)))
        self.refused("PREPARATION_PENDING", lambda: self.manager.handle(self.prepare_request()))

    @unittest.skipUnless(sys.platform == "linux", "Immutable preparation requires Linux renameat2")
    def test_verification_rejects_stale_source_receipt_and_linked_or_changed_prepared_material(self):
        prepared = self.manager.handle(self.prepare_request())
        request = self.verification_request(prepared)
        proof = dict(self.proof, unitDigests=["a" * 64])
        self.write(self.receipt_path, service.encode(proof), 0o600)
        self.refused("CONFLICT", lambda: self.manager.handle(request))
        self.write(self.receipt_path, service.encode(self.proof), 0o600)
        directory = self.state / "generations" / prepared["operationId"]
        ring = directory / "keyring"
        raw = ring.read_bytes()
        other = directory / "other"
        self.write(other, raw, 0o400)
        ring.unlink()
        ring.symlink_to(other.name)
        self.refused("UNSAFE_FILESYSTEM", lambda: self.manager.handle(request))
        ring.unlink()
        self.write(ring, raw[:-1] + bytes([raw[-1] ^ 1]), 0o400)
        self.refused("UNSAFE_JOURNAL", lambda: self.manager.handle(request))
        self.assertEqual(1, len(list((self.state / "operations").iterdir())))

    @unittest.skipUnless(sys.platform == "linux", "Immutable preparation requires Linux renameat2")
    def test_verification_lost_final_result_fences_all_new_ids(self):
        prepared = self.manager.handle(self.prepare_request())
        request = self.verification_request(prepared)
        original = self.manager.atomic
        def lose_result(path, value, **options):
            if path.parent == self.state / "operations" and service.decode(value)["state"] == "SUCCEEDED":
                raise OSError("fixture lost verified receipt")
            return original(path, value, **options)
        with patch.object(self.manager, "atomic", side_effect=lose_result):
            self.refused("UNKNOWN", lambda: self.manager.handle(request))
        with patch.object(self.manager, "crypt", side_effect=AssertionError("Unknown must not dispatch")):
            self.assertEqual("UNKNOWN", self.manager.handle(request)["state"])
            self.refused("UNRESOLVED_OPERATION", lambda: self.manager.handle(self.verification_request(prepared)))
            self.refused("UNRESOLVED_OPERATION", lambda: self.manager.handle(self.prepare_request()))

    def preparation_read_request(self, identity):
        return self.request('generation-preparation-read', preparationId=identity)

    def preparation_read_snapshot(self):
        result = {}
        for path in self.root.rglob('*'):
            if path.is_file():
                info = path.lstat()
                result[str(path.relative_to(self.root))] = (
                    info.st_ino, info.st_uid, info.st_gid, info.st_mode, info.st_nlink,
                    info.st_mtime_ns, info.st_ctime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        return result

    @unittest.skipUnless(sys.platform == 'linux', 'Immutable preparation requires Linux renameat2')
    def test_preparation_read_returns_only_historical_metadata_without_secrets_or_mutation(self):
        prepared = self.manager.handle(self.prepare_request())
        identity = prepared['operationId']
        raw, history, _ = self.manager.prepared_generation(identity)
        before = self.preparation_read_snapshot()
        with patch.object(self.manager, 'atomic', side_effect=AssertionError('Read must not persist')):
            with patch.object(self.manager, 'crypt', side_effect=AssertionError('Read must not encrypt')):
                first = self.manager.handle(self.preparation_read_request(identity))
                self.assertEqual(first, self.manager.handle(self.preparation_read_request(identity)))
        self.assertEqual({'schema', 'action', 'preparationId', 'scope', 'state', 'createdAt', 'source',
                          'generation', 'historySha256', 'backupSha256'}, set(first))
        self.assertEqual('RECORDED', first['state'])
        self.assertEqual('IMMUTABLE_PREPARATION_ONLY', first['scope'])
        self.assertEqual(prepared['historySha256'], first['historySha256'])
        self.assertEqual(history['backupSha256'], first['backupSha256'])
        self.assertEqual(history['generation'], first['generation'])
        encoded = service.encode(first)
        for secret in [PASSWORD.encode(), base64.b64encode(raw), base64.b64encode(self.key),
                       prepared['backup']['encrypted'].encode()]:
            self.assertNotIn(secret, encoded)
        self.assertEqual(before, self.preparation_read_snapshot())

    def test_preparation_read_unknown_never_loads_or_completes_candidate_material(self):
        identity = str(uuid.uuid4())
        self.write(self.state / 'operations' / (identity + '.json'), service.encode(dict(
            schema=1, operationId=identity, action='generation-prepare', requestTag='a'*64,
            state='INTENT', response=None)), 0o600)
        before = self.preparation_read_snapshot()
        with patch.object(self.manager, 'prepared_generation', side_effect=AssertionError('Original UNKNOWN')):
            result = self.manager.handle(self.preparation_read_request(identity))
        self.assertEqual('UNKNOWN', result['state'])
        self.assertEqual({'schema', 'action', 'preparationId', 'scope', 'state'}, set(result))
        self.assertEqual(before, self.preparation_read_snapshot())

    @unittest.skipUnless(sys.platform == 'linux', 'Immutable preparation requires Linux renameat2')
    def test_preparation_read_remains_historical_when_canonical_keys_are_missing_or_another_intent_is_unknown(self):
        prepared = self.manager.handle(self.prepare_request());identity = prepared['operationId']
        self.key_path.unlink()
        unresolved = str(uuid.uuid4())
        self.write(self.state / 'operations' / (unresolved + '.json'), service.encode(dict(
            schema=1, operationId=unresolved, action='backup-create', requestTag='b'*64,
            state='INTENT', response=None)), 0o600)
        before = self.preparation_read_snapshot()
        result = self.manager.handle(self.preparation_read_request(identity))
        self.assertEqual('RECORDED', result['state'])
        self.assertNotIn('published', result);self.assertNotIn('startAllowed', result)
        self.refused('UNRESOLVED_OPERATION', self.manager.settled)
        self.assertFalse(self.key_path.exists())
        self.assertEqual(before, self.preparation_read_snapshot())

    @unittest.skipUnless(sys.platform == 'linux', 'Immutable preparation requires Linux renameat2')
    def test_preparation_read_rejects_missing_changed_or_linked_immutable_material(self):
        prepared = self.manager.handle(self.prepare_request());identity = prepared['operationId']
        history = self.state / 'generations' / identity / 'history.json'
        saved = history.read_bytes()
        for kind in ('changed', 'missing', 'linked'):
            if history.exists() or history.is_symlink():history.unlink()
            if kind == 'changed':self.write(history, saved + b' ', 0o400)
            if kind == 'linked':
                target = self.root / 'same-history';self.write(target, saved, 0o400)
                history.symlink_to(target)
            with self.subTest(kind=kind), self.assertRaises((service.Failure, service.Refused)):
                self.manager.handle(self.preparation_read_request(identity))
        history.unlink();self.write(history, saved, 0o400)

    def test_preparation_read_missing_invalid_fields_and_wrong_action_never_create_records(self):
        identity = str(uuid.uuid4());request = self.preparation_read_request(identity)
        before = self.preparation_read_snapshot()
        self.assertEqual('NOT_FOUND', self.manager.handle(request)['state'])
        for extra in ('passphrase', 'backup', 'keyFile'):
            self.refused('INVALID_ARGUMENT', lambda: self.manager.handle(dict(request, **{extra: 'forbidden'})))
        self.refused('INVALID_ARGUMENT', lambda: self.manager.handle(self.preparation_read_request('../outside')))
        self.assertEqual(before, self.preparation_read_snapshot())
        other = str(uuid.uuid4())
        self.write(self.state / 'operations' / (other + '.json'), service.encode(dict(
            schema=1, operationId=other, action='backup-create', requestTag='c'*64,
            state='INTENT', response=None)), 0o600)
        before = self.preparation_read_snapshot()
        self.refused('CONFLICT', lambda: self.manager.handle(self.preparation_read_request(other)))
        self.assertEqual(before, self.preparation_read_snapshot())

    def test_preparation_read_recovery_and_agent_peers_cannot_open_the_history(self):
        request = self.preparation_read_request(str(uuid.uuid4()))
        with patch.object(self.manager, 'read_preparation', side_effect=AssertionError('Forbidden peer')):
            self.refused('FORBIDDEN', lambda: self.manager.handle(request, recovery_only=True))
            with patch.object(service, 'agent_peer', return_value=True):
                self.refused('FORBIDDEN', lambda: service.serve_request(
                    self.manager, request, 123, 0, 999, None, None))

    @unittest.skipUnless(sys.platform == "linux", "Immutable preparation requires Linux renameat2")
    def test_preparation_receipt_cannot_claim_publication_or_weaken_required_confirmation(self):
        prepared = self.manager.handle(self.prepare_request())
        path = self.state / "operations" / (prepared["operationId"] + ".json")
        original = path.read_bytes()
        for field, value in (("published", True), ("published", 0), ("requiresExplicitCommit", False),
                             ("requiresExplicitCommit", 1)):
            record = service.decode(original)
            record["response"][field] = value
            self.write(path, service.encode(record), 0o600)
            self.refused("UNSAFE_JOURNAL", lambda: self.manager.record(prepared["operationId"]))
        self.write(path, original, 0o600)
        self.manager.settled()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cipher-jar", required=True)
    parser.add_argument("--java", default="/usr/bin/java")
    CONFIG, remaining = parser.parse_known_args()
    unittest.main(argv=[sys.argv[0], *remaining])
