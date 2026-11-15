#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Private Core encryption-key provisioning; never rotate existing encrypted data."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import shlex
import socket
import stat
import struct
import sys

CREDENTIAL = "kura_encryption_key"
PROPERTY = "org.eclipse.kura.core.crypto.secretKey"
CORE_DEFAULT = b"rv;ipse329183!@#"
OLD_DEVELOPMENT = b"kura-dev-key-005"
KEY_PATH = "/etc/kura/credentials/" + CREDENTIAL
RECEIPT_PATH = "/etc/kura/credentials/provisioned.json"
RING_CREDENTIAL = "kura_encryption_keyring"
RING_PATH = "/etc/kura/credentials/" + RING_CREDENTIAL
GENERATION_RECEIPT_PATH = "/etc/kura/credentials/key-generations.json"
GENERATION_FORMAT = "yofc-kura-gateway-key-generations-v1"
RING_MAGIC = b"YOFC-KURA-KEYRING-v1\n"

class Refused(RuntimeError):
    pass

def require(ok, message):
    if not ok:
        raise Refused(message + "; existing Kura data and keys must be preserved")

def effective_key(value):
    return value if len(value) in (16, 24, 32) else CORE_DEFAULT

def generation_require(ok):
    require(ok, "Invalid key-generation credential or retained receipt")

def key_generations(raw):
    """The exact Java reader credential, shared by Root backup and startup policy."""
    generation_require(isinstance(raw, bytes) and len(RING_MAGIC) + 3 <= len(raw) <= 512)
    generation_require(raw.startswith(RING_MAGIC))
    count, active, legacy = raw[len(RING_MAGIC):len(RING_MAGIC) + 3]
    generation_require(2 <= count <= 8 and active < count and legacy < count and active != legacy)
    offset = len(RING_MAGIC) + 3
    keys, ids = [], []
    for number in range(count):
        generation_require(offset < len(raw))
        size = raw[offset]
        offset += 1
        generation_require(size in (16, 24, 32) and offset + size <= len(raw))
        generation_require(number != active or size == 32)
        key = raw[offset:offset + size]
        offset += size
        identity = hashlib.sha256(key).hexdigest()
        generation_require(identity not in ids)
        keys.append(key)
        ids.append(identity)
    generation_require(offset == len(raw))
    return keys[active], dict(ringSha256=hashlib.sha256(raw).hexdigest(), activeKeySha256=ids[active],
                             legacyKeySha256=ids[legacy], keySha256s=ids)

def generation_pairs(items):
    value = {}
    for key, item in items:
        generation_require(key not in value)
        value[key] = item
    return value

def generation_receipt(raw):
    generation_require(isinstance(raw, bytes) and 0 < len(raw) <= 2048)
    try:
        proof = json.loads(raw.decode("utf-8"), object_pairs_hook=generation_pairs,
                           parse_constant=lambda _: generation_require(False))
    except (ValueError, UnicodeError, RecursionError):
        raise Refused("Invalid retained generation receipt; preserve keys and data") from None
    generation_require(isinstance(proof, dict) and set(proof) ==
                       {"schema", "purpose", "ringSha256", "activeKeySha256", "legacyKeySha256", "keySha256s"})
    generation_require(type(proof["schema"]) is int and proof["schema"] == 1 and proof["purpose"] == GENERATION_FORMAT)
    def digest(value):
        generation_require(isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value))
    for name in ("ringSha256", "activeKeySha256", "legacyKeySha256"):
        digest(proof[name])
    ids = proof["keySha256s"]
    generation_require(isinstance(ids, list) and 2 <= len(ids) <= 8)
    for identity in ids:
        digest(identity)
    generation_require(len(set(ids)) == len(ids) and proof["activeKeySha256"] in ids
                       and proof["legacyKeySha256"] in ids and proof["activeKeySha256"] != proof["legacyKeySha256"])
    return {k: v for k, v in proof.items() if k not in ("schema", "purpose")}

class Store:
    def __init__(self, root=Path("/"), owner=None):
        self.root = Path(root).absolute()
        self.owner = os.geteuid() if owner is None else owner
        self.observed = {}

    def path(self, absolute):
        p = Path(absolute)
        require(p.is_absolute() and ".." not in p.parts, "Invalid key-policy path")
        return self.root / p.relative_to("/")

    def read(self, path, private=False, limit=65536, owners=None, loaded_for_uid=None):
        path = Path(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            m = os.fstat(fd)
            require(stat.S_ISREG(m.st_mode) and m.st_nlink == 1,
                    "Unsafe key-policy file type or link count")
            private_mode = (loaded_permissions_private(fd,m,loaded_for_uid)
                            if private and loaded_for_uid is not None
                            else not m.st_mode & (0o077 if private else 0o022))
            require(m.st_uid in ({self.owner} if owners is None else owners) and private_mode,
                    "Unsafe key-policy file ownership or mode")
            require(m.st_size <= limit, "Key-policy file exceeds its limit")
            chunks = []
            total = 0
            while total <= limit:
                chunk = os.read(fd,limit+1-total)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            data = b"".join(chunks)
            require(len(data) <= limit and len(data) == m.st_size,
                    "Key-policy read is incomplete or exceeds its limit")
            after = os.fstat(fd)
            current = path.lstat()
            require((m.st_dev,m.st_ino,m.st_size,m.st_mtime_ns,m.st_ctime_ns)
                    == (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
                    and (m.st_dev,m.st_ino) == (current.st_dev,current.st_ino),
                    "Key-policy source changed while being read")
            identity = (m.st_dev,m.st_ino,m.st_uid,m.st_gid,stat.S_IMODE(m.st_mode),
                        m.st_size,m.st_mtime_ns,m.st_ctime_ns,m.st_nlink)
            self.observed[path] = (identity,hashlib.sha256(data).digest(),private,owners,loaded_for_uid)
            return data
        finally:
            os.close(fd)

    def private_dir(self, path):
        path = Path(path)
        if not path.exists() and not path.is_symlink():
            self.private_dir(path.parent)
            path.mkdir(mode=0o700)
        m = path.lstat()
        require(stat.S_ISDIR(m.st_mode) and m.st_uid == self.owner
                and not m.st_mode & 0o022, "Unsafe key-policy directory")
        if path == self.path("/etc/kura/credentials"):
            require(not m.st_mode & 0o077, "Credential directory is not private")

    @contextlib.contextmanager
    def locked(self):
        directory = self.path("/etc/kura/credentials")
        self.private_dir(self.root)
        self.private_dir(self.path("/etc"))
        self.private_dir(self.path("/etc/kura"))
        self.private_dir(directory)
        fd = os.open(directory / ".provision.lock",
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            m = os.fstat(fd)
            require(stat.S_ISREG(m.st_mode) and m.st_nlink == 1
                    and m.st_uid == self.owner and not m.st_mode & 0o077,
                    "Unsafe key-policy lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def stable(self):
        for path,(identity,digest,private,owners,loaded_for_uid) in list(self.observed.items()):
            data = self.read(path,private=private,owners=owners,loaded_for_uid=loaded_for_uid)
            now = self.observed[path]
            require(now[:2] == (identity,digest) and hashlib.sha256(data).digest() == digest,
                    "Key-policy source changed before publication")

    def publish(self, path, value, mode=0o400):
        path = Path(path)
        self.private_dir(path.parent)
        if os.path.lexists(path):
            require(self.read(path, private=True, limit=max(64,len(value))) == value,
                    "Existing private key-policy value conflicts")
            return
        temporary = path.parent / (".key-publish-" + secrets.token_hex(12))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        try:
            offset = 0
            while offset < len(value):
                written = os.write(fd,value[offset:])
                require(written > 0, "Private key publication stopped before completion")
                offset += written
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(temporary, path, follow_symlinks=False)
        finally:
            temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def key(self, path):
        value = self.read(path, private=True, limit=32)
        require(len(value) in (16,24,32), "Invalid persisted encryption-key length")
        return value

    def dropins_safe(self):
        dangerous = ("EnvironmentFile","LoadCredential","LoadCredentialEncrypted",
                     "SetCredential","SetCredentialEncrypted","ImportCredential","ExecStart","ExecStartPre")
        sensitive = ("KURA_CRYPTO_SECRET_KEY","CREDENTIALS_DIRECTORY","KURA_JVM_ARGS_FILE",
                     "JAVA_TOOL_OPTIONS","JDK_JAVA_OPTIONS","_JAVA_OPTIONS")
        for prefix in ("/etc","/run","/usr/lib","/lib"):
            for folder in ("service.d","kura.service.d"):
                directory = self.path(prefix + "/systemd/system/" + folder)
                if not directory.exists():
                    continue
                require(not directory.is_symlink(), "Symlinked systemd drop-in directory")
                for source in sorted(directory.glob("*.conf")):
                    text = self.read(source).decode("utf-8")
                    for line in text.splitlines():
                        line = line.strip()
                        if not line or line.startswith(("#",";")) or "=" not in line:
                            continue
                        name,value = line.split("=",1)
                        relevant = name.strip() in dangerous or (
                            name.strip() == "Environment" and any(x in value for x in sensitive))
                        require(not relevant, "Custom key/startup drop-in requires a reviewed migration")

    def unit_key(self, source):
        environment = {}
        credential = None
        executable = None
        section = ""
        for raw in self.read(source).decode("utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith(("#",";")):
                continue
            if line.startswith("["):
                section = line
                continue
            if section != "[Service]" or "=" not in line:
                continue
            name,value = line.split("=",1)
            name = name.strip()
            if name in ("Environment","EnvironmentFile","LoadCredential","LoadCredentialEncrypted",
                        "SetCredential","SetCredentialEncrypted","ImportCredential","ExecStart"):
                require("\\" not in value and "%" not in value,
                        "Escaped or dynamic legacy key configuration requires review")
            if name == "Environment":
                if not value.strip():
                    environment.clear()
                else:
                    for item in shlex.split(value):
                        require("=" in item, "Invalid legacy environment assignment")
                        k,v = item.split("=",1)
                        environment[k] = v
            elif name == "EnvironmentFile" and value.strip():
                raise Refused("Legacy EnvironmentFile requires a reviewed key migration; existing Kura data and keys must be preserved")
            elif name == "LoadCredential":
                if not value.strip():
                    credential = None
                else:
                    words = shlex.split(value)
                    require(len(words) == 1, "Ambiguous legacy credential")
                    ident,separator,location = words[0].partition(":")
                    if ident == CREDENTIAL:
                        require(separator and location.startswith("/"), "Unresolved legacy credential source")
                        credential = self.key(self.path(location))
            elif name in ("LoadCredentialEncrypted","SetCredential","SetCredentialEncrypted","ImportCredential"):
                require(not value.strip(), "Custom credential provisioning requires review")
            elif name == "ExecStart":
                executable = shlex.split(value)
        if credential is not None:
            return credential
        require(executable in [
            ["/bin/sh","/opt/eclipse/kura/bin/start_kura_background.sh"],
            ["/bin/bash","/opt/eclipse/kura/bin/start_kura_background.sh"]],
            "Unknown legacy Kura launcher")
        require(not any(environment.get(k) for k in
                        ("KURA_JVM_ARGS_FILE","JAVA_TOOL_OPTIONS","JDK_JAVA_OPTIONS","_JAVA_OPTIONS","CREDENTIALS_DIRECTORY")),
                "Custom legacy JVM/credential settings require review")
        return effective_key(environment.get("KURA_CRYPTO_SECRET_KEY","").encode("utf-8"))

    def running_key(self):
        if self.root != Path("/") or not sys.platform.startswith("linux"):
            return None
        pidfile = self.path("/var/run/kura.pid")
        if not os.path.lexists(pidfile):
            return None
        allowed = {self.owner}
        try:
            allowed.add(pwd.getpwnam("kurad").pw_uid)
        except KeyError:
            pass
        raw = self.read(pidfile, owners=allowed, limit=64).decode("ascii").strip()
        require(raw.isdigit() and str(int(raw)) == raw and int(raw) > 1, "Invalid existing Kura PID")
        proc = Path("/proc")/raw
        if not proc.exists():
            return None
        process_state = (proc/"stat").read_text().rsplit(")",1)[1].split()
        if process_state[0] in ("Z","X"):
            return None
        before = process_state[19]
        argv = (proc/"cmdline").read_bytes().split(b"\0")
        envbytes = (proc/"environ").read_bytes()
        require(len(envbytes) <= 1024*1024 and sum(map(len,argv)) <= 1024*1024,
                "Existing Kura process metadata exceeds its limit")
        jars = [argv[i+1] for i,item in enumerate(argv[:-1]) if item == b"-jar"]
        require(Path(os.readlink(proc/"exe")).name == "java" and len(jars)==1
                and jars[0].startswith(b"/opt/eclipse/kura/plugins/org.eclipse.equinox.launcher-")
                and jars[0].endswith(b".jar"),
                "Existing PID does not identify the installed Kura JVM")
        environment = dict(item.split(b"=",1) for item in envbytes.split(b"\0") if b"=" in item)
        value = None
        directory = environment.get(b"CREDENTIALS_DIRECTORY")
        if directory:
            location = directory.decode("utf-8")
            require(location.startswith("/") and ".." not in Path(location).parts,
                    "Unsafe running credential location")
            path = proc/"root"/location.lstrip("/")/CREDENTIAL
            if os.path.lexists(path):
                process_uid = int((proc/"status").read_text().split("Uid:")[1].split()[0])
                value = effective_key(self.read(path,private=True,limit=4096,
                    owners={self.owner,process_uid},loaded_for_uid=process_uid))
        if value is None:
            require(not any(item.startswith(b"@") for item in argv)
                    and not any(environment.get(k.encode()) for k in
                                ("JAVA_TOOL_OPTIONS","JDK_JAVA_OPTIONS","_JAVA_OPTIONS")),
                    "Running JVM argument files/options require reviewed key migration")
            marker = ("-D"+PROPERTY+"=").encode()
            property_values = [item[len(marker):] for item in argv if item.startswith(marker)]
            supplied = property_values[-1] if property_values and property_values[-1] else environment.get(b"KURA_CRYPTO_SECRET_KEY",b"")
            value = effective_key(supplied)
        after = (proc/"stat").read_text().rsplit(")",1)[1].split()[19]
        require(before == after, "Existing JVM identity changed during key capture")
        return value

    def prepare(self, action):
        require(action in ("install","upgrade","auto"), "Unsupported key provisioning action")
        self.observed.clear()
        with self.locked():
            self.dropins_safe()
            for prefix in ("/etc","/run"):
                require(not os.path.lexists(self.path(prefix+"/systemd/system/kura.service")),
                        "An overriding Kura unit requires reviewed key migration")
            canonical = self.path(KEY_PATH)
            current = self.key(canonical) if os.path.lexists(canonical) else None
            record_path = self.path(RECEIPT_PATH)
            receipt = json.loads(self.read(record_path,private=True)) if os.path.lexists(record_path) else None
            if receipt is not None:
                require(isinstance(receipt,dict) and current is not None
                        and set(receipt)=={"schema","keySha256","origin","legacyKey","unitDigests"}
                        and receipt["schema"]==1
                        and receipt["keySha256"]==hashlib.sha256(current).hexdigest()
                        and receipt["origin"] in ("fresh","legacy","canonical")
                        and receipt["legacyKey"] == (current in (CORE_DEFAULT,OLD_DEVELOPMENT))
                        and isinstance(receipt["unitDigests"],list)
                        and len(receipt["unitDigests"]) <= 3
                        and all(isinstance(x,str) and len(x)==64
                                and all(c in "0123456789abcdef" for c in x)
                                for x in receipt["unitDigests"]),
                        "Encryption-key receipt is inconsistent")
            if any(os.path.lexists(self.path(p)) for p in (RING_PATH, GENERATION_RECEIPT_PATH)):
                # Never generate a replacement or resolve retired legacy sources in a generation-aware store.
                require(current is not None and receipt is not None and type(receipt["schema"]) is int,
                        "Generation credentials are incomplete; restore the original set")
                active, metadata = key_generations(self.read(self.path(RING_PATH), private=True, limit=512))
                trusted = generation_receipt(self.read(self.path(GENERATION_RECEIPT_PATH), private=True, limit=2048))
                generation_require(active == current and metadata == trusted)
                # The installed entrypoint uses -I; its sibling directory is not on sys.path.
                # Embedded legacy capture has no __file__ and uses the fixed installed helper path.
                helper = Path(globals().get("__file__", self.path("/opt/eclipse/kura/bin/kura_key_store.py"))).resolve().parent
                if str(helper) not in sys.path:
                    sys.path.insert(0, str(helper))
                from kura_key_service_lifecycle import Lifecycle, Refused as LifecycleRefused
                lifecycle = Lifecycle(self.root, self.owner)
                try:
                    lifecycle.check_records()
                    require(action != "auto" or lifecycle.fence() is None, "Generation maintenance is not complete")
                except LifecycleRefused:
                    raise Refused("Unresolved or unsafe generation operation; preserve original UUID and credentials") from None
                self.stable()
                return dict(keyReady=True, source=receipt["origin"], legacyKey=receipt["legacyKey"])
            units = [self.path(x) for x in ("/usr/lib/systemd/system/kura.service",
                                          "/lib/systemd/system/kura.service")]
            units = list(dict.fromkeys(p.resolve() for p in units if os.path.lexists(p)))
            require(len(units) <= 1, "Ambiguous installed Kura unit")
            retained = self.path("/var/lib/kura-retained")
            if retained.exists():
                unit = retained/"systemd/kura.service"
                if unit.exists():
                    units.append(unit)
            candidates = [self.unit_key(unit) for unit in units]
            archive = retained/"encryption"/CREDENTIAL
            if os.path.lexists(archive):
                candidates.append(self.key(archive))
            live = self.running_key()
            if live is not None:
                candidates.append(live)
            require(not candidates or all(x == candidates[0] for x in candidates),
                    "Existing key sources disagree")
            selected = candidates[0] if candidates else None
            if selected is not None and current is not None:
                require(selected == current, "Existing canonical and legacy keys disagree")
            existing = action == "upgrade" or retained.exists()
            home = self.path("/opt/eclipse/kura")
            if home.exists():
                if action != "auto":
                    existing = True
                else:
                    factory = home/"install/snapshot_0.xml"
                    snapshot = home/"user/snapshots/snapshot_0.xml"
                    pristine = factory.is_file() and snapshot.is_file() and factory.read_bytes()==snapshot.read_bytes()
                    pristine = pristine and not any((home/"data").glob("*")) and not any((home/"user/snapshots").glob("snapshot_[1-9]*"))
                    existing = existing or not pristine
            require(selected is not None or current is not None and receipt is not None or not existing,
                    "Existing encrypted state has no verified key source")
            value = current if current is not None else selected
            origin = "canonical" if current is not None else "legacy"
            if value is None:
                value = secrets.token_bytes(32)
                origin = "fresh"
            self.stable()
            if current is None:
                self.publish(canonical,value)
            if receipt is None:
                receipt = dict(schema=1,keySha256=hashlib.sha256(value).hexdigest(),
                               origin=origin,legacyKey=value in (CORE_DEFAULT,OLD_DEVELOPMENT),
                               unitDigests=sorted({hashlib.sha256(self.read(unit)).hexdigest() for unit in units}))
                self.publish(record_path,(json.dumps(receipt,sort_keys=True)+"\n").encode(),0o600)
            return dict(keyReady=True,source=receipt["origin"],legacyKey=receipt["legacyKey"])

    def archive(self, destination):
        self.observed.clear()
        with self.locked():
            value = self.key(self.path(KEY_PATH))
            destination = Path(destination)
            self.private_dir(destination)
            require(not destination.stat().st_mode & 0o077, "Key archive is not private")
            self.publish(destination/CREDENTIAL,value)
            receipt = self.read(self.path(RECEIPT_PATH),private=True)
            self.publish(destination/"provisioned.json",receipt,0o600)

    def verify_migration(self, saved, target):
        self.observed.clear()
        with self.locked():
            receipt = json.loads(self.read(self.path(RECEIPT_PATH),private=True))
            require(isinstance(receipt,dict), "Invalid encryption-key receipt")
            saved_digest = hashlib.sha256(self.read(Path(saved))).hexdigest()
            require(saved_digest in receipt.get("unitDigests",[])
                    or self.unit_key(Path(saved)) == self.key(self.path(KEY_PATH)),
                    "Restored data key differs from the provisioned key")
            require(self.unit_key(Path(target)) == self.key(self.path(KEY_PATH)),
                    "Installed service does not use the provisioned key")

def loaded_permissions_private(fd, metadata, reader_uid=None):
    mode = stat.S_IMODE(metadata.st_mode)
    if not mode & 0o077:
        return True
    # systemd may retain root ownership and grant only this service UID read
    # access through a POSIX ACL. The group mode bits then describe the ACL
    # mask, while the owning group itself has no access. Never accept a plain
    # group-readable file or additional users/groups on that account.
    if mode != 0o440 or metadata.st_uid != 0:
        return False
    try:
        acl = os.getxattr(fd,"system.posix_acl_access")
    except (AttributeError,OSError):
        return False
    if len(acl) != 44 or struct.unpack_from("<I",acl)[0] != 2:
        return False
    entries = [struct.unpack_from("<HHI",acl,offset) for offset in range(4,44,8)]
    undefined = 0xffffffff
    reader_uid = os.geteuid() if reader_uid is None else reader_uid
    return entries == [(1,4,undefined),(2,4,reader_uid),(4,0,undefined),
                       (16,4,undefined),(32,0,undefined)]

def read_loaded(directory, name, limit):
    source = directory / name
    fd = os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    try:
        m = os.fstat(fd)
        require(stat.S_ISREG(m.st_mode) and m.st_nlink==1 and loaded_permissions_private(fd,m)
                and m.st_uid in (0,os.geteuid()),
                "Unsafe loaded Kura encryption credential")
        value = os.read(fd, limit + 1)
        current = os.fstat(fd)
        path_state = source.lstat()
        require(0 < len(value) <= limit and m.st_size==len(value),
                "Invalid loaded Kura encryption credential")
        require((m.st_dev,m.st_ino,m.st_size,m.st_mtime_ns,m.st_ctime_ns)
                == (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns,current.st_ctime_ns)
                and (m.st_dev,m.st_ino)==(path_state.st_dev,path_state.st_ino),
                "Loaded Kura encryption credential changed")
        return value
    finally:
        os.close(fd)

def generation_start_admission(metadata):
    # Fixed local read-only RPC. No keys, commands, paths or retry are transmitted.
    require(sys.platform == "linux", "Generation startup admission requires the supported local Root service")
    expected = {name: metadata[name] for name in ("ringSha256", "activeKeySha256")}
    request = dict(schema=1, action="generation-start-admission", **expected)
    def read_exact(connection, size):
        value = bytearray()
        while len(value) < size:
            chunk = connection.recv(size - len(value))
            require(bool(chunk), "Incomplete Root generation admission response")
            value.extend(chunk)
        return bytes(value)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect("/run/kura-key-service/control.sock")
            peer = connection.getsockopt(socket.SOL_SOCKET, getattr(socket, "SO_PEERCRED", 17), struct.calcsize("3i"))
            require(struct.unpack("3i", peer)[1] == 0, "Root generation admission peer is not trusted")
            raw = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("ascii")
            connection.sendall(struct.pack("!I", len(raw)) + raw)
            connection.shutdown(socket.SHUT_WR)
            size = struct.unpack("!I", read_exact(connection, 4))[0]
            require(0 < size <= 2048, "Invalid Root generation admission response")
            response = json.loads(read_exact(connection, size).decode("utf-8"), object_pairs_hook=generation_pairs,
                                  parse_constant=lambda _: generation_require(False))
            require(connection.recv(1) == b"", "Trailing Root generation admission response")
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise Refused("Root generation startup admission unavailable; preserve original operation and keys") from None
    require(isinstance(response, dict) and type(response.get("schema")) is int
            and response == dict(schema=1, state="GENERATION_READY", **expected),
            "Root generation startup admission refused; preserve original operation and keys")

def check_loaded(require_generations=False):
    directory = os.environ.get("CREDENTIALS_DIRECTORY", "")
    require(directory and Path(directory).is_absolute(), "Kura encryption credential is unavailable")
    directory = Path(directory)
    value = read_loaded(directory, CREDENTIAL, 32)
    require(len(value) in (16, 24, 32), "Invalid loaded Kura encryption credential")
    names = (RING_CREDENTIAL, "key-generations.json")
    present = any(os.path.lexists(directory / name) for name in names)
    if require_generations or present:
        raw = read_loaded(directory, RING_CREDENTIAL, 512)
        active, metadata = key_generations(raw)
        proof = generation_receipt(read_loaded(directory, "key-generations.json", 2048))
        generation_require(active == value and metadata == proof)
        generation_start_admission(metadata)

def main(argv):
    try:
        require(bool(argv), "Missing key-policy command")
        if argv in (["check-loaded"], ["check-loaded-generations"]):
            check_loaded(require_generations=argv == ["check-loaded-generations"])
            return 0
        require(os.geteuid()==0, "Key provisioning requires the package administrator")
        store = Store()
        if len(argv)==2 and argv[0]=="prepare":
            result = store.prepare(argv[1])
            print("Kura encryption key is ready; legacy data was not reencrypted."
                  if result["legacyKey"] else "Kura private encryption key is ready.")
        elif len(argv)==2 and argv[0]=="archive":
            store.archive(argv[1])
        elif len(argv)==3 and argv[0]=="verify-migration":
            store.verify_migration(argv[1],argv[2])
        else:
            raise Refused("Unsupported key-policy command")
        return 0
    except (Refused,OSError,ValueError,UnicodeError) as error:
        # Paths, unit contents, environment values and key material are not logged.
        print("Kura encryption-key policy refused: "+(str(error) if isinstance(error,Refused) else "invalid or unavailable private state; preserve existing data"),file=sys.stderr)
        return 1

if __name__=="__main__":
    sys.exit(main(sys.argv[1:]))

