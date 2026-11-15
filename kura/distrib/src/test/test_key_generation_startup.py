#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Temporary credentials only. Never start or alter an installed Kura or Root daemon."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main/resources/unfiltered/pkg/bin"))
import kura_key_store as policy
import kura_key_service as service


class GenerationStartupTest(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        temporary = tempfile.TemporaryDirectory(prefix="kura-generation-startup-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "etc/kura/credentials"
        self.state = self.root / "var/lib/kura-key-service"
        (self.state / "operations").mkdir(parents=True, mode=0o700)
        self.directory.mkdir(parents=True, mode=0o700)
        self.active = secrets.token_bytes(32)
        self.raw = policy.RING_MAGIC + bytes([2, 1, 0, 16]) + policy.CORE_DEFAULT + bytes([32]) + self.active
        self.metadata = dict(ringSha256=hashlib.sha256(self.raw).hexdigest(),
                             activeKeySha256=hashlib.sha256(self.active).hexdigest(),
                             legacyKeySha256=hashlib.sha256(policy.CORE_DEFAULT).hexdigest(),
                             keySha256s=[hashlib.sha256(policy.CORE_DEFAULT).hexdigest(), hashlib.sha256(self.active).hexdigest()])
        self.put(policy.CREDENTIAL, self.active)
        self.put(policy.RING_CREDENTIAL, self.raw)
        self.put("key-generations.json", json.dumps(dict(schema=1, purpose=policy.GENERATION_FORMAT,
                                                        **self.metadata)).encode())
        self.put("provisioned.json", service.encode(dict(schema=1, keySha256=self.metadata["activeKeySha256"],
                                                        origin="fresh", legacyKey=False, unitDigests=[])))
        self.put(".provision.lock", b"")
        for name, data in (("admission.lock", b""), ("journal.key", secrets.token_bytes(32))):
            p = self.state / name
            p.write_bytes(data)
            p.chmod(0o600)
        self.environment = patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": str(self.directory)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def put(self, name, data):
        p = self.directory / name
        p.write_bytes(data)
        p.chmod(0o600)

    def identity(self):
        return {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mode, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
                for p in self.directory.iterdir() if p.is_file()}

    def test_loaded_generation_requires_complete_binding_before_root_admission(self):
        before = self.identity()
        with patch.object(policy, "generation_start_admission") as admission:
            policy.check_loaded(require_generations=True)
        admission.assert_called_once_with(self.metadata)
        self.assertEqual(before, self.identity())

    def test_explicit_generation_mode_never_falls_back_when_both_extras_are_missing(self):
        (self.directory / policy.RING_CREDENTIAL).unlink()
        (self.directory / "key-generations.json").unlink()
        before = self.identity()
        with patch.object(policy, "generation_start_admission") as admission:
            with self.assertRaises((policy.Refused, OSError)):
                policy.check_loaded(require_generations=True)
            admission.assert_not_called()
        self.assertEqual(before, self.identity())

    def test_legacy_mode_does_not_silently_ignore_a_single_present_generation_file(self):
        for missing in (policy.RING_CREDENTIAL, "key-generations.json"):
            p = self.directory / missing
            original = p.read_bytes()
            p.unlink()
            with patch.object(policy, "generation_start_admission") as admission:
                with self.assertRaises((policy.Refused, OSError)):
                    policy.check_loaded()
                admission.assert_not_called()
            self.put(missing, original)

    def test_loaded_generation_mismatch_and_duplicate_receipt_fail_without_admission(self):
        binding = dict(schema=1, purpose=policy.GENERATION_FORMAT, **self.metadata)
        cases = [json.dumps(dict(binding, ringSha256="1" * 64)).encode(),
                 json.dumps(dict(binding, schema=True)).encode(),
                 json.dumps(dict(binding, unexpected="not-accepted")).encode(),
                 b'{"schema":1,' + json.dumps(binding).encode()[1:]]
        for raw in cases:
            self.put("key-generations.json", raw)
            before = self.identity()
            with patch.object(policy, "generation_start_admission") as admission:
                with self.assertRaises(policy.Refused):
                    policy.check_loaded(require_generations=True)
                admission.assert_not_called()
            self.assertEqual(before, self.identity())

    def test_loaded_generation_does_not_use_an_environment_key_to_repair_mismatch(self):
        self.put(policy.CREDENTIAL, secrets.token_bytes(32))
        before = self.identity()
        with patch.dict(os.environ, {policy.PROPERTY: self.active.hex()}), patch.object(policy, "generation_start_admission") as admission:
            with self.assertRaises(policy.Refused):
                policy.check_loaded(require_generations=True)
            admission.assert_not_called()
        self.assertEqual(before, self.identity())

    def test_loaded_generation_rejects_nonprivate_or_oversized_ring(self):
        ring = self.directory / policy.RING_CREDENTIAL
        ring.chmod(0o644)
        with self.assertRaises(policy.Refused):
            policy.check_loaded(require_generations=True)
        ring.chmod(0o600)
        self.put(policy.RING_CREDENTIAL, self.raw + b"x" * 512)
        with self.assertRaises(policy.Refused):
            policy.check_loaded(require_generations=True)

    def test_prepare_preserves_generations_instead_of_comparing_retired_single_key_sources(self):
        retained = self.root / "var/lib/kura-retained/encryption"
        retained.mkdir(parents=True, mode=0o700)
        (retained / policy.CREDENTIAL).write_bytes(policy.CORE_DEFAULT)
        (retained / policy.CREDENTIAL).chmod(0o400)
        before = self.identity()
        with patch.object(policy.secrets, "token_bytes", side_effect=AssertionError("No replacement key")):
            result = policy.Store(self.root).prepare("upgrade")
        self.assertTrue(result["keyReady"])
        self.assertEqual(before, self.identity())
        self.assertEqual(policy.CORE_DEFAULT, (retained / policy.CREDENTIAL).read_bytes())

    def test_isolated_interpreter_loads_only_the_packaged_sibling_policy(self):
        before = self.identity()
        script = "import runpy,sys; m=runpy.run_path(sys.argv[1],run_name='isolated_key_policy'); m['Store'](sys.argv[2]).prepare('upgrade')"
        result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(Path(policy.__file__).resolve()), str(self.root)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertEqual(before, self.identity())

    def test_prepare_never_creates_a_key_when_a_retained_generation_binding_is_incomplete(self):
        (self.directory / policy.CREDENTIAL).unlink()
        (self.directory / "provisioned.json").unlink()
        before = self.identity()
        with patch.object(policy.secrets, "token_bytes", side_effect=AssertionError("No new key on missing state")):
            with self.assertRaises(policy.Refused):
                policy.Store(self.root).prepare("install")
        self.assertEqual(before, self.identity())

    def test_prepare_never_settles_an_intent_from_present_restored_credentials(self):
        identity = str(uuid.uuid4())
        record = dict(schema=1, operationId=identity, action="generation-restore", requestTag="2" * 64,
                      state="INTENT", response=None)
        p = self.state / "operations" / (identity + ".json")
        p.write_bytes(service.encode(record)); p.chmod(0o600)
        before = self.identity()
        with self.assertRaises(policy.Refused):
            policy.Store(self.root).prepare("upgrade")
        self.assertEqual(before, self.identity())
        self.assertEqual(record, service.decode(p.read_bytes()))

    def single_key(self, value=None):
        for name in (policy.RING_CREDENTIAL, "key-generations.json"):
            (self.directory / name).unlink()
        self.active = value if value is not None else self.active
        self.put(policy.CREDENTIAL, self.active)
        self.put("provisioned.json", service.encode(dict(schema=1, keySha256=hashlib.sha256(self.active).hexdigest(),
                                                        origin="canonical", legacyKey=self.active == policy.CORE_DEFAULT,
                                                        unitDigests=[])))

    def credential_request(self, ring=True):
        return dict(schema=1, action="credential-start-admission", keySha256=hashlib.sha256(self.active).hexdigest(),
                    ringSha256=self.metadata["ringSha256"] if ring else None)

    def test_root_admission_accepts_only_the_original_single_key_without_modifying_state(self):
        self.single_key(policy.CORE_DEFAULT)
        before = self.identity()
        manager = service.Manager(self.root, owner=os.geteuid())
        result = manager.handle(self.credential_request(False))
        self.assertEqual(dict(schema=1, state="CREDENTIAL_READY", keySha256=hashlib.sha256(self.active).hexdigest(),
                              ringSha256=None), result)
        self.assertEqual(before, self.identity())
        self.assertEqual([], list((self.state / "operations").iterdir()))

    def test_root_admission_never_accepts_missing_loaded_generations_or_a_different_key(self):
        manager = service.Manager(self.root, owner=os.geteuid())
        self.assertEqual("CREDENTIAL_READY", manager.handle(self.credential_request())["state"])
        for request in (self.credential_request(False), dict(self.credential_request(), keySha256="a" * 64),
                        dict(self.credential_request(), ringSha256="b" * 64)):
            with self.assertRaises(service.Failure) as caught:
                manager.handle(request)
            self.assertEqual("CONFLICT", caught.exception.reason)

    def test_root_admission_refuses_an_unknown_key_or_start_operation_even_in_single_key_state(self):
        self.single_key()
        manager = service.Manager(self.root, owner=os.geteuid())
        identity = str(uuid.uuid4())
        operation = self.state / "operations" / (identity + ".json")
        pending = dict(schema=1, operationId=identity, action="generation-prepare", requestTag="1" * 64,
                       state="INTENT", response=None)
        operation.write_bytes(service.encode(pending)); operation.chmod(0o600)
        before = self.identity()
        with self.assertRaises(service.Failure) as caught:
            manager.handle(self.credential_request(False))
        self.assertEqual("UNRESOLVED_OPERATION", caught.exception.reason)
        operation.unlink()
        startups = self.state / "startups"
        startups.mkdir(mode=0o700)
        pending = dict(schema=1, operationId=identity, restoreOperationId=str(uuid.uuid4()),
                       keySha256=hashlib.sha256(self.active).hexdigest(), requestTag="2" * 64, state="INTENT", response=None)
        operation = startups / (identity + ".json")
        operation.write_bytes(service.encode(pending)); operation.chmod(0o600)
        with self.assertRaises(service.Failure) as caught:
            manager.handle(self.credential_request(False))
        self.assertEqual("UNRESOLVED_OPERATION", caught.exception.reason)
        self.assertEqual(before, self.identity())
        self.assertEqual(pending, service.decode(operation.read_bytes()))

    def test_root_admission_never_falls_back_from_incomplete_or_unbound_canonical_generation_files(self):
        manager = service.Manager(self.root, owner=os.geteuid())
        for name in (policy.RING_CREDENTIAL, "key-generations.json"):
            path = self.directory / name
            original = path.read_bytes()
            path.unlink()
            with self.assertRaises(service.Failure):
                manager.handle(self.credential_request(False))
            self.put(name, original)

    def test_managed_entrypoint_sends_single_and_generation_fingerprints_through_the_same_root_gate(self):
        before = self.identity()
        with patch.object(policy, "credential_start_admission") as managed, \
                patch.object(policy, "generation_start_admission", side_effect=AssertionError("No second legacy admission")):
            self.assertEqual(0, policy.main(["check-loaded-managed"]))
        managed.assert_called_once_with(hashlib.sha256(self.active).hexdigest(), self.metadata["ringSha256"])
        self.assertEqual(before, self.identity())
        self.single_key()
        with patch.object(policy, "credential_start_admission") as managed:
            self.assertEqual(0, policy.main(["check-loaded-managed"]))
        managed.assert_called_once_with(hashlib.sha256(self.active).hexdigest(), None)

    def test_managed_entrypoint_rejects_bad_loaded_material_before_root_and_never_uses_environment_replacement(self):
        self.put(policy.CREDENTIAL, secrets.token_bytes(32))
        before = self.identity()
        with patch.dict(os.environ, {policy.PROPERTY: self.active.hex()}), \
                patch.object(policy, "credential_start_admission") as managed:
            with self.assertRaises(policy.Refused):
                policy.check_loaded(require_root=True)
            managed.assert_not_called()
        self.assertEqual(before, self.identity())

    def test_cold_recovery_peer_cannot_request_the_managed_boot_gate(self):
        manager = service.Manager(self.root, owner=os.geteuid())
        with self.assertRaises(service.Failure) as caught:
            manager.handle(self.credential_request(), recovery_only=True)
        self.assertEqual("FORBIDDEN", caught.exception.reason)

    @unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0, "Isolated Linux Root socket only")
    def test_real_isolated_managed_entrypoint_blocks_original_unknown_before_any_core_start(self):
        self.single_key()
        path = Path("/run/kura-key-service/control.sock")
        if os.path.lexists(path) or not path.parent.is_dir():
            self.skipTest("Requires an empty private socket directory in the disposable test container")
        manager = service.Manager(self.root, owner=os.geteuid())
        calls, errors = [], []
        before = self.identity()
        def run_entry():
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(path)); listener.listen(1); listener.settimeout(3)
                inode = path.lstat().st_ino
                def serve_one():
                    try:
                        connection, _ = listener.accept()
                        with connection:
                            connection.settimeout(3)
                            request = service.decode(service.read_frame(connection))
                            self.assertEqual(b"", connection.recv(1))
                            self.assertEqual(self.credential_request(False), request)
                            calls.append(request)
                            try:
                                reply = manager.handle(request)
                            except service.Failure as failure:
                                reply = dict(schema=1, error=failure.reason)
                            service.send_frame(connection, reply)
                    except Exception as error:
                        errors.append(error)
                thread = threading.Thread(target=serve_one, daemon=True)
                thread.start()
                try:
                    result = subprocess.run([sys.executable, "-I", "-B", policy.__file__, "check-loaded-managed"],
                                            capture_output=True, text=True, timeout=5)
                finally:
                    thread.join(4)
                    if path.lstat().st_ino == inode:
                        path.unlink()
                self.assertFalse(thread.is_alive())
                self.assertEqual([], errors)
                return result
        result = run_entry()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        identity = str(uuid.uuid4())
        record = dict(schema=1, operationId=identity, action="generation-prepare", requestTag="3" * 64,
                      state="INTENT", response=None)
        journal = self.state / "operations" / (identity + ".json")
        journal.write_bytes(service.encode(record)); journal.chmod(0o600)
        # Negative control: the historical single-key entrypoint never asks Root.
        old = subprocess.run([sys.executable, "-I", "-B", policy.__file__, "check-loaded"],
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(0, old.returncode, old.stderr)
        result = run_entry()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("preserve original operation and keys", result.stderr)
        self.assertEqual("", result.stdout)
        self.assertNotIn(self.active.hex(), result.stderr)
        self.assertEqual(2, len(calls))
        self.assertEqual(before, self.identity())
        self.assertEqual(record, service.decode(journal.read_bytes()))

    @unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0, "Isolated Linux Root socket only")
    def test_real_root_peer_admits_only_the_loaded_original_generation(self):
        path = Path("/run/kura-key-service/control.sock")
        if os.path.lexists(path) or not path.parent.is_dir():
            self.skipTest("Requires an empty private socket directory in the disposable test container")
        manager = service.Manager(self.root, owner=os.geteuid())
        errors = []
        before = self.identity()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path)); listener.listen(1); listener.settimeout(3)
            created_inode = path.lstat().st_ino
            def serve_one():
                try:
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(3)
                        request = service.decode(service.read_frame(connection))
                        self.assertEqual(b"", connection.recv(1))
                        self.assertEqual({"schema", "action", "ringSha256", "activeKeySha256"}, set(request))
                        self.assertEqual("generation-start-admission", request["action"])
                        service.send_frame(connection, manager.handle(request))
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=serve_one, daemon=True)
            thread.start()
            try:
                policy.check_loaded(require_generations=True)
            finally:
                thread.join(4)
                if path.lstat().st_ino == created_inode:
                    path.unlink()
            self.assertFalse(thread.is_alive())
            self.assertEqual([], errors)
        self.assertEqual(before, self.identity())
        self.assertEqual([], list((self.state / "operations").iterdir()))


class Connection:
    def __init__(self, response, uid=0, suffix=b""):
        self.wire = bytearray(struct.pack("!I", len(response)) + response + suffix)
        self.uid = uid
        self.sent = b""
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def settimeout(self, timeout): pass
    def connect(self, address):
        if address != "/run/kura-key-service/control.sock":
            raise AssertionError("Only the fixed Root socket is allowed")
    def getsockopt(self, *args): return struct.pack("3i", 1, self.uid, self.uid)
    def sendall(self, value): self.sent += value
    def shutdown(self, how): pass
    def recv(self, size):
        # Split frames deliberately; the client must consume an exact bounded message.
        size = min(size, 7)
        part = bytes(self.wire[:size]); del self.wire[:size]
        return part


class GenerationAdmissionClientTest(unittest.TestCase):
    def setUp(self):
        self.expected = dict(ringSha256="1" * 64, activeKeySha256="2" * 64)
        self.reply = dict(schema=1, state="GENERATION_READY", **self.expected)

    def run_client(self, connection):
        with patch.object(policy.sys, "platform", "linux"), patch.object(policy.socket, "socket", return_value=connection):
            policy.generation_start_admission(self.expected)

    def test_fixed_read_only_request_to_root_contains_only_public_fingerprints(self):
        connection = Connection(service.encode(self.reply))
        self.run_client(connection)
        size = struct.unpack("!I", connection.sent[:4])[0]
        self.assertEqual(size, len(connection.sent[4:]))
        self.assertEqual(dict(schema=1, action="generation-start-admission", **self.expected),
                         json.loads(connection.sent[4:]))

    def test_an_untrusted_peer_cannot_claim_root_admission(self):
        connection = Connection(service.encode(self.reply), uid=1000)
        with self.assertRaises(policy.Refused): self.run_client(connection)
        self.assertEqual(b"", connection.sent)

    def test_unknown_error_wrong_fingerprint_or_boolean_schema_never_admits(self):
        replies = [dict(schema=1, error="UNRESOLVED_OPERATION"), dict(self.reply, schema=True),
                   dict(self.reply, ringSha256="3" * 64), dict(self.reply, arbitrary=True)]
        for reply in replies:
            with self.assertRaises(policy.Refused): self.run_client(Connection(service.encode(reply)))

    def test_duplicate_fields_trailing_bytes_and_oversized_frames_never_admit(self):
        duplicate = b'{"schema":1,' + service.encode(self.reply)[1:]
        connections = [Connection(duplicate), Connection(service.encode(self.reply), suffix=b"x"),
                       Connection(b"x" * 2049)]
        for connection in connections:
            with self.assertRaises(policy.Refused): self.run_client(connection)


class ManagedAdmissionClientTest(unittest.TestCase):
    def run_client(self, connection, ring=None):
        with patch.object(policy.sys, "platform", "linux"), patch.object(policy.socket, "socket", return_value=connection):
            policy.credential_start_admission("1" * 64, ring)

    def test_single_or_generation_requests_contain_only_fixed_public_fingerprints(self):
        for ring in (None, "2" * 64):
            expected = dict(keySha256="1" * 64, ringSha256=ring)
            connection = Connection(service.encode(dict(schema=1, state="CREDENTIAL_READY", **expected)))
            self.run_client(connection, ring)
            self.assertEqual(dict(schema=1, action="credential-start-admission", **expected), json.loads(connection.sent[4:]))

    def test_wrong_peer_or_unavailable_root_never_admits_or_retries(self):
        connection = Connection(service.encode(dict(schema=1, state="CREDENTIAL_READY", keySha256="1" * 64, ringSha256=None)), uid=1000)
        with self.assertRaises(policy.Refused):
            self.run_client(connection)
        self.assertEqual(b"", connection.sent)
        with patch.object(policy.sys, "platform", "linux"), patch.object(policy.socket, "socket", side_effect=OSError("fixture unavailable")) as factory:
            with self.assertRaises(policy.Refused):
                policy.credential_start_admission("1" * 64, None)
        factory.assert_called_once()

    def test_unknown_wrong_mode_schema_key_or_extra_fields_are_refused(self):
        reply = dict(schema=1, state="CREDENTIAL_READY", keySha256="1" * 64, ringSha256=None)
        replies = [dict(schema=1, error="UNRESOLVED_OPERATION"), dict(reply, schema=True),
                   dict(reply, ringSha256="2" * 64), dict(reply, keySha256="3" * 64),
                   dict(reply, state="GENERATION_READY"), dict(reply, extra=True)]
        for value in replies:
            with self.assertRaises(policy.Refused):
                self.run_client(Connection(service.encode(value)))

    def test_duplicate_truncated_and_trailing_frames_cannot_claim_managed_admission(self):
        reply = service.encode(dict(schema=1, state="CREDENTIAL_READY", keySha256="1" * 64, ringSha256=None))
        connections = [Connection(b'{"schema":1,' + reply[1:]), Connection(reply, suffix=b"x"), Connection(b"x" * 2049)]
        truncated = Connection(reply)
        truncated.wire = truncated.wire[:-5]
        connections.append(truncated)
        for connection in connections:
            with self.assertRaises(policy.Refused):
                self.run_client(connection)


if __name__ == "__main__":
    unittest.main()
