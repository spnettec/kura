#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Assemble the fixed private worker and its manifest; never touch a gateway."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/main/resources/unfiltered/pkg/bin"))
import kura_key_cohort as cohort
import kura_clock_broker as clock_broker
import kura_command_executor as command_executor
import kura_reboot_broker as reboot_broker
import kura_journal_export as journal_export
import kura_modem_driver as modem_driver
import kura_bind_service as bind_service
import kura_dhcp_service as dhcp_service
import kura_modem_reset as modem_reset


def require(ok):
    if not ok:
        raise RuntimeError("Incomplete or unexpected gateway key-service build inputs")


def verify_crypto_imports(assembly, modules=None):
    """Reject cached Core bundles built against a different crypto API contract.

    Snapshot coordinates alone cannot distinguish the previous API major. The
    handwritten manifests are authoritative; compare the staged bundles' OSGi
    crypto version declarations before producing a new distribution manifest.
    This is a build-input check, not a general OSGi resolver or runtime bypass.
    """
    modules = modules or Path(__file__).resolve().parents[2]
    def headers(raw):
        joined = raw.decode('utf-8').replace('\r\n', '\n').replace('\n ', '')
        return dict(line.split(': ', 1) for line in joined.splitlines() if ': ' in line)
    def version(values, name):
        raw = values.get(name, '')
        match = re.search(r'(?:^|,)\s*org\.eclipse\.kura\.crypto\s*;\s*version\s*=\s*"([^"]+)"', raw)
        if 'org.eclipse.kura.crypto' in raw and match is None:
            raise RuntimeError('Unrecognized crypto package declaration in ' + name)
        return match.group(1) if match else None
    checked = {}
    for path in sorted((assembly / 'plugins').rglob('*.jar')):
        with zipfile.ZipFile(path) as archive:
            actual = headers(archive.read('META-INF/MANIFEST.MF'))
        declarations = {name: version(actual, name) for name in ('Import-Package', 'Export-Package')}
        bundle = actual.get('Bundle-SymbolicName', '').split(';', 1)[0].strip()
        if not re.fullmatch(r'org\.eclipse\.kura\.[A-Za-z0-9_.-]+', bundle):
            if not any(declarations.values()):
                continue
            raise RuntimeError('Unexpected crypto API bundle: ' + path.name)
        source = modules / bundle / 'META-INF/MANIFEST.MF'
        if not any(declarations.values()) and not source.is_file():
            continue
        if not source.is_file():
            raise RuntimeError('Missing handwritten crypto contract: ' + bundle)
        expected = headers(source.read_bytes())
        if not any(declarations.values()) and not any(version(expected, name) for name in declarations):
            continue
        for name, value in declarations.items():
            if value != version(expected, name):
                raise RuntimeError('Stale crypto API build input: ' + bundle + ' ' + name
                    + ' staged=' + str(value) + ' source=' + str(version(expected, name))
                    + '; rebuild and install current consumers into the same Maven cache')
        if bundle in checked:
            raise RuntimeError('Duplicate crypto API build input: ' + bundle)
        checked[bundle] = declarations
    if 'org.eclipse.kura.api' not in checked or len(checked) < 2:
        raise RuntimeError('Incomplete crypto API build inputs')
    return checked


def prepare(assembly, cipher_target, offline_target):
    require(assembly.is_dir() and not assembly.is_symlink())
    verify_crypto_imports(assembly)
    helpers = ["bin/kura_key_store.py", "bin/kura_key_service.py", "bin/kura_key_service_lifecycle.py",
               'bin/kura_key_recovery.py', 'bin/kura_key_recovery_setup.py', 'bin/kura_key_recovery_start.py', 'bin/kura_key_journal.py']
    static = ['share/key-recovery/' + name for name in ['index.html', 'recovery.js', 'recovery.css', 'archive.js']]
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
    stop_files = cohort.managed_unit(unit_bytes)
    require(all((assembly / name).is_file() and not (assembly / name).is_symlink() for name in stop_files))
    generation_files = set(cohort.FIXED_FILES) | set(readers.values()) | set(libraries) | stop_files
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

def embed_main_link_migration(preinst):
    token = 'raise RuntimeError("Kura Main link migration was not embedded")'
    source = Path(__file__).with_name('main-link-migration.py').read_bytes()
    require(0 < len(source) <= 32768)
    compile(source, 'main-link-migration.py', 'exec', dont_inherit=True)
    content = preinst.read_text()
    require(content.count(token) == 1)
    preinst.write_text(content.replace(token, '_KURA_EMBEDDED_MAIN_LINK_MIGRATION_SOURCE = ' + repr(source)))


def embed_upgrade_copy(preinst):
    token = 'raise RuntimeError("Kura upgrade copy was not embedded")'
    source = Path(__file__).with_name('preinst-upgrade-copy.py').read_bytes()
    require(0 < len(source) <= 32768)
    compile(source, 'preinst-upgrade-copy.py', 'exec', dont_inherit=True)
    content = preinst.read_text()
    require(content.count(token) == 1)
    preinst.write_text(content.replace(token, '_KURA_EMBEDDED_UPGRADE_COPY_SOURCE = ' + repr(source)))


def embed_policy_readers(preinst,lifecycle,journal):
    token='raise RuntimeError("Kura key-policy readers were not embedded")'
    require(preinst.is_file() and not preinst.is_symlink())
    assignments=[]
    readers = (('_KURA_EMBEDDED_LIFECYCLE_SOURCE', lifecycle, 160 * 1024),
               ('_KURA_EMBEDDED_JOURNAL_SOURCE', journal, 128 * 1024))
    for name, path, limit in readers:
        require(path.is_file() and not path.is_symlink())
        source = path.read_bytes()
        require(0 < len(source) <= limit)
        compile(source, str(path), 'exec', dont_inherit=True)
        assignments.append(name+' = '+repr(source))
    content=preinst.read_text();require(content.count(token)==1)
    preinst.write_text(content.replace(token,'\n'.join(assignments)))


def embed_package_helper(control, policy, label):
    token = f'raise RuntimeError("Kura {label} was not embedded")'
    require(control.is_file() and not control.is_symlink())
    require(policy.is_file() and not policy.is_symlink())
    source = policy.read_text()
    require(0 < len(source.encode()) <= 32768)
    compile(source, str(policy), 'exec', dont_inherit=True)
    content = control.read_text()
    require(content.count(token) == 1)
    control.write_text(content.replace(token, source))


def embed_managed_nm_preflight(control, installer):
    token = 'raise RuntimeError("Kura managed NM policy admission was not embedded")'
    marker = "<<'KURA_MANAGED_NETWORK_POLICY'\n"
    script = installer.read_text()
    require(script.count(marker) == 1)
    body = script.split(marker, 1)[1].split('\nKURA_MANAGED_NETWORK_POLICY', 1)[0]
    compile(body, str(installer), 'exec', dont_inherit=True)
    content = control.read_text()
    require(content.count(token) == 1)
    control.write_text(content.replace(token, body))


def prepare_clock_service(assembly):
    destination = assembly / 'libexec/clock-broker'
    destination.mkdir(parents=True, exist_ok=True)
    for name in clock_broker.UNITS:
        source = assembly / 'install' / name
        require(source.is_file() and not source.is_symlink())
        shutil.copyfile(source, destination / name)
    return clock_broker.package_cohort(assembly)


def embed_clock_guard(control):
    token = 'raise RuntimeError("Kura clock maintenance guard was not embedded")'
    source = Path(__file__).with_name('clock-maintenance-guard.py').read_text()
    compile(source, 'clock-maintenance-guard.py', 'exec', dont_inherit=True)
    content = control.read_text(); require(content.count(token) == 1)
    control.write_text(content.replace(token, source))


def embed_reboot_guard(control):
    token = 'raise RuntimeError("Kura reboot maintenance guard was not embedded")'
    source = Path(__file__).with_name('reboot-maintenance-guard.py').read_text()
    compile(source, 'reboot-maintenance-guard.py', 'exec', dont_inherit=True)
    content = control.read_text()
    require(content.count(token) == 1)
    control.write_text(content.replace(token, source))


def embed_configure_phases(control, assembly):
    token = 'raise RuntimeError("Kura Core configure phases were not embedded")'
    names = dict(CORE_CONFIGURE_HOME=assembly.name)
    for name, relative in (
            ('CORE_CONFIGURE_LIFECYCLE_SHA', 'bin/kura_key_service_lifecycle.py'),
            ('CORE_CONFIGURE_MANIFEST_SHA', 'libexec/key-backup/manifest.json'),
            ('CORE_CONFIGURE_INSTALLER_SHA', 'install/kura_install.sh')):
        names[name] = hashlib.sha256((assembly / relative).read_bytes()).hexdigest()
    source = Path(__file__).with_name('postinst-configure.py').read_text()
    source = ''.join(f'{key} = {value!r}\n' for key, value in names.items()) + source
    compile(source, 'postinst-configure.py', 'exec', dont_inherit=True)
    content = control.read_text()
    require(content.count(token) == 1)
    control.write_text(content.replace(token, source))


if __name__ == "__main__":
    require(len(sys.argv) == 4)
    prepare(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    prepare_clock_service(Path(sys.argv[1]))
    reboot_broker.package_cohort(Path(sys.argv[1]))
    journal_export.package_cohort(Path(sys.argv[1]))
    command_executor.package_cohort(Path(sys.argv[1]))
    modem_driver.package_cohort(Path(sys.argv[1]))
    bind_service.package_cohort(Path(sys.argv[1]))
    dhcp_service.package_cohort(Path(sys.argv[1]))
    modem_reset.package_cohort(Path(sys.argv[1]))
    embed_journal_reader(Path(sys.argv[1]).parent/'filtered-control/preinst',Path(sys.argv[1])/'bin/kura_key_journal.py')
    embed_main_link_migration(Path(sys.argv[1]).parent/'filtered-control/preinst')
    embed_upgrade_copy(Path(sys.argv[1]).parent/'filtered-control/preinst')
    embed_package_helper(Path(sys.argv[1]).parent/'filtered-control/preinst',
                         Path(sys.argv[1])/'bin/kura_modem_cohort.py', 'modem cohort')
    embed_package_helper(Path(sys.argv[1]).parent/'filtered-control/preinst',
                         Path(sys.argv[1])/'bin/kura_wpa_policy.py', 'WPA policy admission')
    embed_managed_nm_preflight(Path(sys.argv[1]).parent/'filtered-control/preinst',
                               Path(sys.argv[1])/'install/manage_kura_users.sh')
    embed_policy_readers(Path(sys.argv[1]).parent/'filtered-control/preinst',Path(sys.argv[1])/'bin/kura_key_service_lifecycle.py',
        Path(sys.argv[1])/'bin/kura_key_journal.py')
    for hook in ('preinst', 'postinst', 'prerm'):
        control = Path(sys.argv[1]).parent / 'filtered-control' / hook
        embed_package_helper(control, Path(__file__).with_name('addon-code-policy.py'), 'addon-code policy')
        embed_package_helper(control, Path(sys.argv[1]) / 'bin/kura_watchdog_maintenance.py', 'watchdog maintenance')
    embed_configure_phases(Path(sys.argv[1]).parent/'filtered-control/postinst', Path(sys.argv[1]))
    for hook in ('preinst', 'prerm'):
        embed_clock_guard(Path(sys.argv[1]).parent/'filtered-control'/hook)
        embed_reboot_guard(Path(sys.argv[1]).parent/'filtered-control'/hook)
