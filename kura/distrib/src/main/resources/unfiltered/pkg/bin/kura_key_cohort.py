#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fixed generation-reader package contract. No keys, user paths or mutations."""
import hashlib
import os
from pathlib import Path
import re
import shlex
import stat
import zipfile
import zlib


class Refused(RuntimeError):
    pass


def require(ok):
    if not ok:
        raise Refused("Unpaired generation-reader package; preserve original keys and operation IDs")


ROLES = {
    "crypto": ("org.eclipse.kura.core.crypto", ("kura.crypto.key.generations",),
               ("org/eclipse/kura/core/crypto/CryptoServiceImpl.class", "org/eclipse/kura/core/crypto/EncryptionKeyRing.class")),
    "configuration": ("org.eclipse.kura.core.configuration", ("kura.configuration.password.sources", "kura.configuration.dispatch.release"),
                      ("org/eclipse/kura/core/configuration/ConfigurationServiceImpl.class",)),
    "snapshot": ("org.eclipse.kura.xml.marshaller.unmarshaller.provider", ("kura.configuration.snapshot.codec",),
                 ("org/eclipse/kura/internal/xml/marshaller/unmarshaller/XmlJavaComponentConfigurationsMapper.class",)),
    "offline": ("org.eclipse.kura.recovery.bootstrap", (),
                ("org/eclipse/kura/tools/recovery/SnapshotTool.class", "org/eclipse/kura/tools/recovery/RecoveryBootstrap.class",
                 "org/eclipse/kura/tools/recovery/RecoveryCrypto.class")),
}
LAUNCHERS = ("start_kura.sh", "start_kura_background.sh", "start_kura_debug.sh")
OFFLINE = "libexec/key-recovery/kura-offline-recovery.jar"
TEMPLATES = "libexec/key-backup/launchers/"
FIXED_FILES = frozenset(("bin/kura_key_cohort.py", "bin/kura_credential_env.sh", *[TEMPLATES + n for n in LAUNCHERS]))


def headers(raw):
    require(isinstance(raw, bytes))
    boundary = re.search(rb"\r?\n\r?\n", raw)
    if boundary:
        raw = raw[:boundary.start()]
    require(0 < len(raw) <= 65536 and b"\0" not in raw)
    try:
        # Byte-counted JAR folding may split a UTF-8 character between physical lines.
        lines = raw.replace(b"\r\n", b"\n").replace(b"\n ", b"").decode("utf-8").split("\n")
    except UnicodeError:
        raise Refused("Invalid generation-reader manifest") from None
    result = {}
    name = None
    for line in lines:
        if not line:
            break  # Main attributes only; named sections do not grant capabilities.
        if line.startswith(" "):
            require(name is not None)
            result[name] += line[1:]
        else:
            require(": " in line)
            name, value = line.split(": ", 1)
            name = name.lower()
            require(re.fullmatch(r"[a-z0-9-]+", name) is not None and name not in result)
            result[name] = value
    return result


def clauses(value):
    require(isinstance(value, str))
    result, part, quoted, escaped = [], [], False, False
    for char in value:
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        if char == "," and not quoted:
            result.append("".join(part).strip()); part = []
        else:
            part.append(char)
    require(not quoted and not escaped)
    result.append("".join(part).strip())
    entries = {}
    for entry in result:
        name = entry.split(";", 1)[0].strip()
        require(bool(name) and name not in entries)
        entries[name] = entry
    return entries


def identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid, value.st_size,
            value.st_nlink, value.st_mtime_ns, value.st_ctime_ns)


def jar(path, owner=None, role=None):
    """Read bounded manifest/class headers through a stable, no-follow file handle."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 256 * 1024 * 1024
                and not before.st_mode & 0o022 and (owner is None or before.st_uid == owner))
        try:
            with zipfile.ZipFile(stream) as archive:
                require(len(archive.infolist()) <= 65536)
                manifest = archive.getinfo("META-INF/MANIFEST.MF")
                require(0 < manifest.file_size <= 256 * 1024 * 1024)
                with archive.open(manifest) as attributes:
                    raw = attributes.read(65537)
                boundary = re.search(rb"\r?\n\r?\n", raw)
                # Signed JARs can have large named digest sections. Only main attributes
                # declare a reader; never decompress the remaining sections for this check.
                if boundary:
                    raw = raw[:boundary.start()]
                values = headers(raw)
                if role is not None:
                    expected, capabilities, classes = ROLES[role]
                    require(values.get("bundle-symbolicname", "").split(";", 1)[0] == expected)
                    provided = clauses(values.get("provide-capability", "")) if capabilities else {}
                    for capability in capabilities:
                        require(capability in provided and re.search(r';\s*version:Version=(?:"1\.0\.0"|1\.0\.0)(?:\s*;|\s*$)', provided[capability]) is not None)
                    for name in classes:
                        with archive.open(name) as bytecode:
                            prefix = bytecode.read(8)
                        require(len(prefix) == 8 and prefix[:6] == b"\xca\xfe\xba\xbe\0\0"
                                and int.from_bytes(prefix[6:8], "big") == 65)
                    if role == "offline":
                        require(values.get("main-class") == "org.eclipse.kura.tools.recovery.SnapshotTool")
                        required = clauses(values.get("require-capability", ""))
                        for capability in ("kura.crypto.key.generations", "kura.configuration.dispatch.release", "kura.configuration.snapshot.codec"):
                            require(capability in required and 'filter:="(&(version>=1.0.0)(!(version>=2.0.0)))"' in required[capability])
        except (KeyError, ValueError, zipfile.BadZipFile, RuntimeError, EOFError, zlib.error):
            raise Refused("Invalid generation-reader JAR") from None
        require(identity(before) == identity(os.fstat(stream.fileno())) == identity(Path(path).lstat()))
    return values


def heap_template(raw):
    # Installer changes these two numeric options for available RAM. Bind everything else.
    matches = list(re.finditer(rb"-Xms([0-9]+)m -Xmx([0-9]+)m", raw))
    require(len(matches) == 1)
    first, last = (int(value) for value in matches[0].groups())
    require(16 <= first <= last <= 65536)
    return re.sub(rb"-Xms[0-9]+m -Xmx[0-9]+m", b"-XmsHEAPm -XmxHEAPm", raw)


def managed_unit(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= 65536)
    section, values = "", {}
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            section = line
            continue
        require("=" in line)
        name, value = line.split("=", 1)
        key = (section, name)
        if not value:
            values[key] = []
        else:
            values.setdefault(key, []).append(value)
    for name in ("Requires", "After"):
        require("kura-key-service.socket" in " ".join(values.get(("[Unit]", name), [])).split())
    for name, expected in (("User", "kurad"), ("Group", "kurad"), ("KillMode", "control-group")):
        require(values.get(("[Service]", name)) == [expected])
    starts = values.get(("[Service]", "ExecStartPre"), [])
    require(starts and shlex.split(starts[0]) == ["/usr/bin/python3", "-I", "/opt/eclipse/kura/bin/kura_key_store.py", "check-loaded-managed"])
    require(values.get(("[Service]", "ExecStart")) == ["/bin/sh /opt/eclipse/kura/bin/start_kura_background.sh"])
    require("kura_encryption_key:/etc/kura/credentials/kura_encryption_key" in values.get(("[Service]", "LoadCredential"), []))


def catalog(home, owner=None):
    found = {role: [] for role in ROLES if role != "offline"}
    for folder in ("plugins", "siblings"):
        base = home / folder
        if not base.exists():
            continue
        require(base.is_dir() and not base.is_symlink())
        paths = list(base.rglob("*.jar"))
        require(len(paths) <= 4096)
        for path in paths:
            values = jar(path, owner)
            name = values.get("bundle-symbolicname", "").split(";", 1)[0]
            for role in found:
                if name == ROLES[role][0]:
                    found[role].append(path.relative_to(home).as_posix())
    require(all(len(paths) == 1 for paths in found.values()))
    return {role: paths[0] for role, paths in found.items()}


def reader_files(home, owner=None):
    roles = catalog(home, owner)
    roles["offline"] = OFFLINE
    for role, path in roles.items():
        jar(home / path, owner, role)
    offline = jar(home / OFFLINE, owner, "offline")
    entries = offline.get("class-path", "").split()
    require(entries and len(entries) <= 256 and len(set(entries)) == len(entries))
    libraries = []
    matched = {role: [] for role in ROLES if role != "offline"}
    for entry in entries:
        require(re.fullmatch(r"lib/[A-Za-z0-9_.-]+\.jar", entry) is not None)
        location = "libexec/key-recovery/" + entry
        libraries.append(location)
        values = jar(home / location, owner)
        name = values.get("bundle-symbolicname", "").split(";", 1)[0]
        for role in matched:
            if name == ROLES[role][0]:
                matched[role].append(location)
    # Identical bytecode/manifests in the standalone classpath and actual Core plugin set.
    digest = lambda path: hashlib.sha256((home / path).read_bytes()).hexdigest()
    for role, paths in matched.items():
        require(len(paths) == 1 and digest(paths[0]) == digest(roles[role]))
    return roles, libraries


def validate(home, manifest, read, owner=None, base_files=frozenset(), unit=None):
    """Attest actual readers and installer-normalized launchers; return exact runtime hashes."""
    require(isinstance(manifest.get("readers"), dict) and set(manifest["readers"]) == set(ROLES))
    managed_unit(unit)
    roles, libraries = reader_files(home, owner)
    require(roles == manifest["readers"])
    expected = set(FIXED_FILES) | set(roles.values()) | set(libraries)
    require(set(manifest["files"]) == set(base_files) | expected)
    observed = {}
    for name in LAUNCHERS:
        path = "bin/" + name
        raw = read(home / path)
        require(heap_template(raw) == heap_template(read(home / (TEMPLATES + name))))
        observed[path] = hashlib.sha256(raw).hexdigest()
    return observed
