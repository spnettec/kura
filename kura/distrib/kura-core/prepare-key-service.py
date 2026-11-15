#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Assemble the fixed private worker and its manifest; never touch a gateway."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile


def require(ok):
    if not ok:
        raise RuntimeError("Incomplete or unexpected gateway key-service build inputs")


def prepare(assembly, cipher_target):
    require(assembly.is_dir() and not assembly.is_symlink())
    helpers = ["bin/kura_key_store.py", "bin/kura_key_service.py", "bin/kura_key_service_lifecycle.py",
               'bin/kura_key_recovery.py', 'bin/kura_key_recovery_setup.py', 'bin/kura_key_recovery_start.py']
    static = ['share/key-recovery/' + name for name in ['index.html', 'recovery.js', 'recovery.css']]
    units = ["kura-key-service.socket", "kura-key-service.service", 'kura-key-recovery.service']
    for name in helpers + static + ["install/" + unit for unit in units]:
        require((assembly / name).is_file() and not (assembly / name).is_symlink())
    # prerm runs account/policy teardown while tracked root code still exists.
    # postrm must never execute the daemon-writable historical .data copy.
    users = assembly / "install/manage_kura_users.sh"
    require(users.is_file() and not users.is_symlink())
    shutil.copyfile(users, assembly / "bin/manage_kura_users.sh")
    jar = cipher_target / "kura-key-crypto-6.0.0-SNAPSHOT.jar"
    bc = cipher_target / "lib/bcprov-jdk18on-1.86.jar"
    require(jar.is_file() and bc.is_file() and not jar.is_symlink() and not bc.is_symlink())
    with zipfile.ZipFile(jar) as archive:
        raw = archive.read("META-INF/MANIFEST.MF").decode("utf-8").replace("\r\n", "\n")
        joined = raw.replace("\n ", "")
        attributes = dict(line.split(": ", 1) for line in joined.splitlines() if ": " in line)
        require(attributes.get("Main-Class") == "org.eclipse.kura.keybackup.KeyBackupCipher")
        require(attributes.get("Class-Path") == "lib/bcprov-jdk18on-1.86.jar")
    destination = assembly / "libexec/key-backup"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "lib").mkdir(exist_ok=True)
    shutil.copyfile(jar, destination / "kura-key-crypto.jar")
    shutil.copyfile(bc, destination / "lib/bcprov-jdk18on-1.86.jar")
    assets = helpers + static + ["libexec/key-backup/kura-key-crypto.jar",
                        "libexec/key-backup/lib/bcprov-jdk18on-1.86.jar"]
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = dict(schema=1, protocol=1, files={name: digest(assembly / name) for name in assets},
                    units={name: digest(assembly / "install" / name) for name in units})
    (destination / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    require(len(sys.argv) == 3)
    prepare(Path(sys.argv[1]), Path(sys.argv[2]))
