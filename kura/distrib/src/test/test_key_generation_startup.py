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


if __name__ == "__main__":
    unittest.main()
