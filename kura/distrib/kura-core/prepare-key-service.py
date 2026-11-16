#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Assemble the fixed private worker and its manifest; never touch a gateway."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/main/resources/unfiltered/pkg/bin"))
import kura_key_cohort as cohort


def require(ok):
    if not ok:
        raise RuntimeError("Incomplete or unexpected gateway key-service build inputs")


def prepare(assembly, cipher_target, offline_target):
    require(assembly.is_dir() and not assembly.is_symlink())
    helpers = ["bin/kura_key_store.py", "bin/kura_key_service.py", "bin/kura_key_service_lifecycle.py",
               'bin/kura_key_recovery.py', 'bin/kura_key_recovery_setup.py', 'bin/kura_key_recovery_start.py', 'bin/kura_key_journal.py']
    static = ['share/key-recovery/' + name for name in ['index.html', 'recovery.js', 'recovery.css']]
    units = ["kura-key-service.socket", "kura-key-service.service", 'kura-key-recovery.service', 'kura.service']
    for name in helpers + static + ['bin/kura_key_cohort.py', 'bin/kura_credential_env.sh'] + ["install/" + unit for unit in units]:
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
    # Canonical install path is fixed by the existing native service contract.
    main_unit = assembly / "install/kura.service"
    unit_bytes = main_unit.read_bytes().replace(b"INSTALL_DIR", b"/opt/eclipse")
    require(b"kura_key_store.py check-loaded-managed\n" in unit_bytes
            and b"Requires=kura-key-service.socket\n" in unit_bytes)
    main_unit.write_bytes(unit_bytes)
    templates = assembly / cohort.TEMPLATES
    templates.mkdir(parents=True, exist_ok=True)
    for name in cohort.LAUNCHERS:
        source = assembly / "bin" / name
        require(source.is_file() and not source.is_symlink())
        cohort.heap_template(source.read_bytes())
        shutil.copyfile(source, templates / name)
    recovery = assembly / "libexec/key-recovery"
    recovery.mkdir(parents=True, exist_ok=True)
    (recovery / "lib").mkdir(exist_ok=True)
    standalone = offline_target / "kura-offline-recovery-1.0.0-SNAPSHOT.jar"
    require(standalone.is_file() and not standalone.is_symlink())
    shutil.copyfile(standalone, assembly / cohort.OFFLINE)
    for library in (offline_target / "lib").glob("*.jar"):
        require(library.is_file() and not library.is_symlink())
        shutil.copyfile(library, recovery / "lib" / library.name)
    readers, libraries = cohort.reader_files(assembly, os.geteuid())
    base_files = set(helpers + static + ["libexec/key-backup/kura-key-crypto.jar",
                                      "libexec/key-backup/lib/bcprov-jdk18on-1.86.jar"])
    generation_files = set(cohort.FIXED_FILES) | set(readers.values()) | set(libraries)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    generation = dict(files={name: digest(assembly / name) for name in sorted(generation_files)}, readers=readers,
                      unitSha256=digest(main_unit), writerProtocol=1)
    manifest = dict(schema=2, protocol=2, files={name: digest(assembly / name) for name in sorted(base_files)},
                    units={name: digest(assembly / "install" / name) for name in units if name != 'kura.service'}, generation=generation)
    cohort.validate(assembly, generation, Path.read_bytes, os.geteuid(), unit=unit_bytes)
    (destination / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


def embed_journal_reader(preinst, reader):
    token='raise RuntimeError("Kura key-journal reader was not embedded")'
    require(preinst.is_file() and not preinst.is_symlink())
    source=reader.read_bytes();require(0<len(source)<=131072);compile(source,str(reader),'exec',dont_inherit=True)
    content=preinst.read_text();require(content.count(token)==1)
    # A new preinst validates old state with its own reader before unpack.
    # Store bytes only; execute after Lifecycle and its exception types exist.
    content=content.replace(token,'_KURA_EMBEDDED_JOURNAL_SOURCE = '+repr(source))
    preinst.write_text(content)


if __name__ == "__main__":
    require(len(sys.argv) == 4)
    prepare(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    embed_journal_reader(Path(sys.argv[1]).parent/'filtered-control/preinst',Path(sys.argv[1])/'bin/kura_key_journal.py')
