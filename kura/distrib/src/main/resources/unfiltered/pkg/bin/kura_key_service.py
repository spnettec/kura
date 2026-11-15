#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Core-owned gateway AES key backup/recovery. No shell, user paths or key rotation."""
import base64
import contextlib
import ctypes
import datetime
import errno
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import socket
import ssl
import stat
import struct
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_key_store import Store, KEY_PATH, RECEIPT_PATH, CORE_DEFAULT, OLD_DEVELOPMENT, Refused
from kura_key_service_lifecycle import Lifecycle, validate_record, Refused as LifecycleRefused

SOCKET = "/run/kura-key-service/control.sock"
STATE = "/var/lib/kura-key-service"
FORMAT = "yofc-kura-gateway-master-key-v1"
MAX_FRAME = 65536
MAX_OPERATIONS = 256
CIPHER = ["/usr/bin/java", "-Xms16m", "-Xmx96m", "-XX:MaxMetaspaceSize=64m",
          "-XX:ActiveProcessorCount=1", "-XX:+DisableAttachMechanism", "-XX:+PerfDisableSharedMem",
          "-jar", "/opt/eclipse/kura/libexec/key-backup/kura-key-crypto.jar"]


class Failure(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def require(ok, reason="INVALID_ARGUMENT"):
    if not ok:
        raise Failure(reason)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def decode(data):
    require(len(data) <= MAX_FRAME)
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(Failure("INVALID_ARGUMENT")))
    except (ValueError, UnicodeError, RecursionError):
        raise Failure("INVALID_ARGUMENT") from None
    require(isinstance(value, dict))
    return value


def fields(value, names):
    require(isinstance(value, dict) and set(value) == set(names))


def operation_id(value):
    require(isinstance(value, str))
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise Failure("INVALID_ARGUMENT") from None
    require(parsed.version == 4 and str(parsed) == value)
    return value


def digest(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None)
    return value


def passphrase(value):
    require(isinstance(value, str) and 12 <= len(value) <= 256 and "\0" not in value)
    try:
        raw = value.encode("utf-8")
    except UnicodeError:
        raise Failure("INVALID_ARGUMENT") from None
    require(len(raw) <= 1024)
    return raw


def receipt(value, key=None):
    fields(value, {"schema", "keySha256", "origin", "legacyKey", "unitDigests"})
    require(type(value["schema"]) is int and value["schema"] == 1)
    digest(value["keySha256"])
    require(value["origin"] in ("fresh", "legacy", "canonical"))
    require(type(value["legacyKey"]) is bool)
    require(isinstance(value["unitDigests"], list) and len(value["unitDigests"]) <= 3)
    for item in value["unitDigests"]:
        digest(item)
    if key is not None:
        require(len(key) in (16, 24, 32) and hashlib.sha256(key).hexdigest() == value["keySha256"])
        require(value["legacyKey"] == (key in (CORE_DEFAULT, OLD_DEVELOPMENT)))
    return value


class Manager:
    """The root and cipher arguments exist for isolated tests, never on the wire or command line."""
    def __init__(self, root=Path("/"), owner=0, cipher=None):
        self.store = Store(root, owner)
        self.root = self.store.root
        self.owner = owner
        self.state = self.store.path(STATE)
        self.operations = self.state / "operations"
        self.cipher = list(CIPHER if cipher is None else cipher)

    def directory(self, path, private=False):
        # Do not create or repair directories as a side effect of status or backup.
        path = Path(path)
        current = self.root
        for part in ("", *path.relative_to(self.root).parts):
            current = current / part
            m = current.lstat()
            require(stat.S_ISDIR(m.st_mode) and m.st_uid == self.owner and not m.st_mode & 0o022,
                    "UNSAFE_FILESYSTEM")
        if private:
            require(not m.st_mode & 0o077, "UNSAFE_FILESYSTEM")

    @contextlib.contextmanager
    def lock(self, path, exclusive):
        self.directory(path.parent, private=True)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            m = os.fstat(fd)
            require(stat.S_ISREG(m.st_mode) and m.st_nlink == 1 and m.st_uid == self.owner
                    and not m.st_mode & 0o077, "UNSAFE_FILESYSTEM")
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Failure("BUSY") from None
            yield
        finally:
            os.close(fd)

    def read(self, path, limit=MAX_FRAME):
        try:
            return self.store.read(path, private=True, limit=limit)
        except Refused:
            raise Failure("UNSAFE_FILESYSTEM") from None

    def atomic(self, path, data, mode=0o600, no_replace=False):
        self.directory(path.parent, private=True)
        temporary = path.parent / (".key-service-" + secrets.token_hex(16))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if no_replace:
                # Unlike link/unlink, renameat2 never exposes a two-link canonical secret.
                library = ctypes.CDLL(None, use_errno=True)
                rename = getattr(library, "renameat2", None)
                require(rename is not None and sys.platform == "linux", "UNSUPPORTED")
                rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
                rename.restype = ctypes.c_int
                if rename(-100, os.fsencode(temporary), -100, os.fsencode(path), 1) != 0:
                    code = ctypes.get_errno()
                    if code == errno.EEXIST:
                        raise Failure("CONFLICT")
                    raise OSError(code, "Atomic key publication refused")
            else:
                if os.path.lexists(path):
                    self.read(path)
                os.replace(temporary, path)
            self.sync(path.parent)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def sync(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def canonical(self, allow_missing=False):
        directory = self.store.path("/etc/kura/credentials")
        self.directory(directory, private=True)
        proof = receipt(decode(self.read(self.store.path(RECEIPT_PATH), 8192)))
        try:
            key = self.read(self.store.path(KEY_PATH), 32)
        except FileNotFoundError:
            require(allow_missing, "KEY_MISSING")
            key = None
        if key is not None:
            receipt(proof, key)
        return key, proof

    def crypt(self, encrypt, password, value):
        require(len(value) <= 32768)
        frame = b"KKB1" + bytes([1 if encrypt else 2]) + struct.pack("!I", len(password)) + password
        frame += struct.pack("!I", len(value)) + value
        try:
            result = subprocess.run(self.cipher, input=frame, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                                    timeout=20, check=False, close_fds=True, cwd="/")
        except subprocess.TimeoutExpired:
            raise Failure("CIPHER_UNAVAILABLE") from None
        require(result.returncode == 0 and 0 < len(result.stdout) <= 32768,
                "CIPHER_UNAVAILABLE" if encrypt else "BACKUP_REJECTED")
        return result.stdout

    def unpack(self, envelope, password):
        fields(envelope, {"format", "operationId", "encrypted"})
        require(envelope["format"] == FORMAT, "BACKUP_REJECTED")
        original = operation_id(envelope["operationId"])
        require(isinstance(envelope["encrypted"], str) and len(envelope["encrypted"]) <= 32768)
        try:
            encrypted = base64.b64decode(envelope["encrypted"], validate=True)
        except ValueError:
            raise Failure("BACKUP_REJECTED") from None
        data = decode(self.crypt(False, password, encrypted))
        fields(data, {"schema", "purpose", "operationId", "createdAt", "key", "receipt"})
        require(type(data["schema"]) is int and data["schema"] == 1 and data["purpose"] == FORMAT,
                "BACKUP_REJECTED")
        require(data["operationId"] == original and isinstance(data["createdAt"], str), "BACKUP_REJECTED")
        require(isinstance(data["key"], str), "BACKUP_REJECTED")
        try:
            key = base64.b64decode(data["key"], validate=True)
        except ValueError:
            raise Failure("BACKUP_REJECTED") from None
        receipt(data["receipt"], key)
        return key, data

    def record(self, identity):
        path = self.operations / (identity + ".json")
        try:
            record = decode(self.read(path))
        except FileNotFoundError:
            return None
        try:
            return validate_record(record, identity)
        except LifecycleRefused:
            raise Failure("UNSAFE_JOURNAL") from None

    def public_record(self, record):
        if record is None:
            return {"schema": 1, "state": "NOT_FOUND"}
        if record["state"] == "INTENT":
            return {"schema": 1, "operationId": record["operationId"], "state": "UNKNOWN"}
        require(isinstance(record["response"], dict), "UNSAFE_JOURNAL")
        return record["response"]

    def journal_admission(self):
        self.directory(self.operations, private=True)
        names = list(self.operations.iterdir())
        require(len(names) < MAX_OPERATIONS, "CAPACITY")
        for path in names:
            require(path.name.endswith(".json"), "UNSAFE_JOURNAL")
            identity = operation_id(path.name[:-5])
            record = self.record(identity)
            require(record is not None and record["state"] != "INTENT", "UNRESOLVED_OPERATION")

    def maintenance(self):
        try:
            require(Lifecycle(self.root, self.owner).fence() is None, "MAINTENANCE")
        except LifecycleRefused:
            raise Failure("UNSAFE_JOURNAL") from None

    def handle(self, request, *, recovery_only=False):
        require(isinstance(request, dict) and type(request.get("schema")) is int and request["schema"] == 1)
        action = request.get("action")
        if recovery_only:
            require(action in ('status', 'backup-inspect', 'operation-read', 'restore', 'core-start', 'core-start-read', 'core-start-plan', 'core-start-after-maintenance', 'recovery-info'), 'FORBIDDEN')
        if action in ("core-start", "core-start-read", "core-start-plan", "core-start-after-maintenance"):
            from kura_key_recovery_start import Starter
            return Starter(self).handle(request)
        if action == 'recovery-info':
            fields(request, {'schema','action'})
            with self.lock(self.state/'admission.lock', False):
                self.maintenance()
                directory=self.store.path('/etc/kura/recovery-tls')
                self.directory(directory,private=True)
                data=self.read(directory/'server.crt',16384)
                try:pem=data.decode('ascii')
                except UnicodeError:raise Failure('UNAVAILABLE') from None
                require(re.fullmatch(r'-----BEGIN CERTIFICATE-----\n[A-Za-z0-9+/=\n]+-----END CERTIFICATE-----\n?',pem) is not None,'UNAVAILABLE')
                try:
                    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    context.load_verify_locations(cadata=pem)
                    der=ssl.PEM_cert_to_DER_cert(pem)
                except (ssl.SSLError,ValueError):raise Failure('UNAVAILABLE') from None
                return dict(schema=1,recoveryPort=9443,certificatePem=pem,
                            certificateSha256=hashlib.sha256(der).hexdigest(),agentRequired=False)
        if action == "status":
            fields(request, {"schema", "action"})
            with self.lock(self.state / "admission.lock", False):
                self.maintenance()
                with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), False):
                    key, proof = self.canonical(True)
                    return {"schema": 1, "keyReady": key is not None, "keySha256": proof["keySha256"],
                            "legacyKey": proof["legacyKey"], "agentRequired": False}
        if action == "operation-read":
            fields(request, {"schema", "action", "operationId"})
            identity = operation_id(request["operationId"])
            with self.lock(self.state / "admission.lock", False):
                self.maintenance()
                record = self.record(identity)
                require(not recovery_only or record is None or record['action'] == 'restore', 'FORBIDDEN')
                return self.public_record(record)
        if action == "backup-inspect":
            fields(request, {"schema", "action", "backup", "passphrase"})
            password = passphrase(request["passphrase"])
            with self.lock(self.state / "admission.lock", False):
                self.maintenance()
                key, data = self.unpack(request["backup"], password)
                with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), False):
                    current, proof = self.canonical(True)
                    compatible = proof["keySha256"] == data["receipt"]["keySha256"]
                    return {"schema": 1, "backupOperationId": data["operationId"],
                            "keySha256": data["receipt"]["keySha256"], "createdAt": data["createdAt"],
                            "sameDeviceKey": compatible, "keyReady": current is not None,
                            "restoreAllowed": compatible and (current is None if recovery_only else (current is None or current == key))}
        require(action in ("backup-create", "restore"))
        expected = {"schema", "action", "operationId", "passphrase"}
        if action == "restore":
            expected |= {"backup", "expectedKeySha256"}
        fields(request, expected)
        identity = operation_id(request["operationId"])
        password = passphrase(request["passphrase"])
        with self.lock(self.state / "admission.lock", True):
            self.maintenance()
            # Installer creates this independent journal key; status never provisions a data key.
            journal_key = self.read(self.state / "journal.key", 32)
            require(len(journal_key) == 32, "UNSAFE_JOURNAL")
            tag = hmac.new(journal_key, encode(request), hashlib.sha256).hexdigest()
            existing = self.record(identity)
            if existing is not None:
                require(hmac.compare_digest(existing["requestTag"], tag), "CONFLICT")
                return self.public_record(existing)
            self.journal_admission()
            with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), action == "restore"):
                current, proof = self.canonical(action == "restore")
                require(not recovery_only or current is None, 'CONFLICT')
                key = None
                if action == "restore":
                    digest(request["expectedKeySha256"])
                    key, data = self.unpack(request["backup"], password)
                    require(request["expectedKeySha256"] == proof["keySha256"]
                            == data["receipt"]["keySha256"], "CONFLICT")
                    require(current is None or current == key, "CONFLICT")
                    if current is None:
                        require(sys.platform == "linux" and hasattr(ctypes.CDLL(None), "renameat2"), "UNSUPPORTED")
                record = dict(schema=1, operationId=identity, action=action, requestTag=tag,
                              state="INTENT", response=None)
                # From this point every ambiguous failure is UNKNOWN. Never redispatch on read.
                try:
                    self.atomic(self.operations / (identity + ".json"), encode(record))
                    if action == "backup-create":
                        created = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        payload = dict(schema=1, purpose=FORMAT, operationId=identity, createdAt=created,
                                       key=base64.b64encode(current).decode("ascii"), receipt=proof)
                        encrypted = self.crypt(True, password, encode(payload))
                        response = dict(schema=1, operationId=identity, state="SUCCEEDED", action=action,
                                        backup=dict(format=FORMAT, operationId=identity,
                                                    encrypted=base64.b64encode(encrypted).decode("ascii")))
                    else:
                        if current is None:
                            self.atomic(self.store.path(KEY_PATH), key, mode=0o400, no_replace=True)
                        response = dict(schema=1, operationId=identity, state="SUCCEEDED", action=action,
                                        keySha256=proof["keySha256"], keyChanged=current is None,
                                        existingReceiptPreserved=True)
                    record.update(state="SUCCEEDED", response=response)
                    self.atomic(self.operations / (identity + ".json"), encode(record))
                    return response
                except (OSError, Failure, Refused):
                    raise Failure("UNKNOWN") from None


def read_exact(stream, size):
    output = bytearray()
    while len(output) < size:
        part = stream.recv(size - len(output))
        require(bool(part), "PROTOCOL_MISMATCH")
        output.extend(part)
    return bytes(output)


def read_frame(stream):
    length = struct.unpack("!I", read_exact(stream, 4))[0]
    require(0 < length <= MAX_FRAME, "PROTOCOL_MISMATCH")
    return read_exact(stream, length)


def send_frame(stream, value):
    data = encode(value)
    require(len(data) <= MAX_FRAME, "PROTOCOL_MISMATCH")
    stream.sendall(struct.pack("!I", len(data)) + data)


def peer(stream):
    require(sys.platform == "linux" and hasattr(socket, "SO_PEERCRED"), "UNSUPPORTED")
    return struct.unpack("3i", stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))


def recovery_identity(daemon):
    try:
        account = pwd.getpwnam('kura-key-recovery')
    except KeyError:
        return None  # The previous package generation has no recovery account.
    require(account.pw_uid not in (0, daemon) and account.pw_shell in ('/usr/sbin/nologin', '/sbin/nologin'), 'FORBIDDEN')
    return account.pw_uid


def serve():
    require(os.geteuid() == 0, "FORBIDDEN")
    require(os.environ.get("LISTEN_PID") == str(os.getpid()) and os.environ.get("LISTEN_FDS") == "1",
            "UNAVAILABLE")
    listener = socket.socket(fileno=3)
    require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM
            and listener.getsockname() == SOCKET
            and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1, "UNAVAILABLE")
    daemon = pwd.getpwnam("kurad").pw_uid
    require(daemon != 0, "FORBIDDEN")
    recovery = recovery_identity(daemon)
    lifecycle = Lifecycle()
    lifecycle.no_overrides()
    lifecycle.assets()
    require(lifecycle.fence() is None, "MAINTENANCE")
    manager = Manager()
    while True:
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(3)
            try:
                _, uid, _ = peer(connection)
                require(uid in (0, daemon) or recovery is not None and uid == recovery, "FORBIDDEN")
                request = decode(read_frame(connection))
                require(connection.recv(1) == b"", "PROTOCOL_MISMATCH")
                require(uid != daemon or request.get("action") not in ("core-start", "core-start-after-maintenance"), "FORBIDDEN")
                response = manager.handle(request, recovery_only=recovery is not None and uid == recovery)
            except Failure as failure:
                response = {"schema": 1, "error": failure.reason}
            except (OSError, Refused, KeyError):
                response = {"schema": 1, "error": "UNAVAILABLE"}
            try:
                send_frame(connection, response)
            except (OSError, Failure):
                pass  # Original durable UUID can be read; never repeat a mutation here.


def client():
    data = sys.stdin.buffer.read(MAX_FRAME + 1)
    request = decode(data)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(25)
        connection.connect(SOCKET)
        require(peer(connection)[1] == 0, "FORBIDDEN")
        send_frame(connection, request)
        connection.shutdown(socket.SHUT_WR)
        result = read_frame(connection)
        require(connection.recv(1) == b"", "PROTOCOL_MISMATCH")
        sys.stdout.buffer.write(encode(decode(result)) + b"\n")


if __name__ == "__main__":
    try:
        require(len(sys.argv) == 2 and sys.argv[1] in ("--serve", "--client"))
        serve() if sys.argv[1] == "--serve" else client()
    except (Failure, OSError, Refused, LifecycleRefused, KeyError):
        # The GWT adapter maps a lost mutating response to UNKNOWN with the original UUID.
        sys.stderr.write("Kura gateway key service unavailable; preserve the original operation ID\n")
        sys.exit(2)
