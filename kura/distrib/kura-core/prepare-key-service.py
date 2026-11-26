#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Assemble the fixed private worker and its manifest; never touch a gateway."""
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/main/resources/unfiltered/pkg/bin"))
import kura_key_cohort as cohort
import kura_clock_broker as clock_broker
import kura_command_executor as command_executor
import kura_reboot_broker as reboot_broker
import kura_journal_export as journal_export
import kura_ownership_markers as ownership_markers
import kura_firewall_tables as firewall_tables
import kura_firewall_publish as firewall_publish
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


def bind_published_predecessors(manifest, paths):
    if not paths:
        return
    field = 'publishedPredecessorManifestSha256s'
    administrative = {'bin/kura_key_service_lifecycle.py', 'bin/kura_key_store.py', 'bin/kura_key_generation.py'}

    def stable_assets(files):
        return dict.fromkeys(files) | {k: v for k, v in files.items() if k not in administrative}

    def boot_contract(value):
        generation = value['generation']
        require(value['schema'] == 2 and value['protocol'] == 2
                and set(value) == {'schema', 'protocol', 'files', 'units', 'generation'}
                and set(generation) - {field} == {'writerProtocol', 'unitSha256', 'files', 'readers'})
        return (value['units'], stable_assets(value['files']), generation['writerProtocol'],
                generation['unitSha256'], generation['readers'], stable_assets(generation['files']))

    contract = boot_contract(manifest)
    hashes = set()
    for path in paths:
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 65536)
        raw = path.read_bytes()
        require(boot_contract(json.loads(raw)) == contract)
        hashes.add(hashlib.sha256(raw).hexdigest())
    require(1 <= len(hashes) <= 8)
    manifest['generation'][field] = sorted(hashes)


def prepare(assembly, cipher_target, offline_target, predecessors=()):
    require(assembly.is_dir() and not assembly.is_symlink())
    verify_crypto_imports(assembly)
    helpers = ["bin/kura_key_store.py", "bin/kura_key_service.py", "bin/kura_key_service_lifecycle.py",
               'bin/kura_key_recovery.py', 'bin/kura_key_recovery_setup.py', 'bin/kura_key_recovery_start.py',
               'bin/kura_key_journal.py', 'bin/kura_native_snapshot_validation.py', 'bin/kura_snapshot_inventory.py',
               'bin/kura_recovery_input.py', 'bin/kura_recovery_launch.py', 'bin/kura_native_recovery_input.py',
               'bin/kura_recovery_main_command.py', 'bin/kura_native_recovery_main.py', 'bin/kura_snapshot_publication.py']
    static = ['share/key-recovery/' + name for name in ['index.html', 'recovery.js', 'recovery.css', 'archive.js']]
    units = ['kura-key-service.socket', 'kura-key-service.service', 'kura-key-recovery.service',
             'kura-snapshot-validation.socket', 'kura-snapshot-validation.service',
             'kura-snapshot-inventory.socket', 'kura-snapshot-inventory.service',
             'kura-recovery-input.socket', 'kura-recovery-input.service',
             'kura-recovery-main.socket', 'kura-recovery-main.service',
             'kura-recovery-main-reader.socket', 'kura-recovery-main-reader.service', 'kura.service']
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
    bind_published_predecessors(manifest, predecessors)
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


def upgrade_payload(assembly):
    directories, files = [], {}
    for path in sorted(assembly.rglob('*')):
        name = path.relative_to(assembly).as_posix()
        require(not path.is_symlink())
        if path.is_dir():
            directories.append(name)
        else:
            require(path.is_file())
            with path.open('rb') as stream:
                files[name] = (path.stat().st_size, hashlib.file_digest(stream, 'sha256').hexdigest())
    return dict(home=assembly.name, directories=directories, files=files)


def layout_repair_predecessor(assembly, archive):
    require(archive.is_file() and not archive.is_symlink())
    raw = subprocess.check_output(['dpkg-deb', '--ctrl-tarfile', str(archive)], timeout=20)
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as control:
        parts = {member.name.removeprefix('./'): control.extractfile(member).read()
                 for member in control if member.isfile()}
    metadata = parts['control']
    version = re.search(rb'(?m)^Version: ([0-9][0-9A-Za-z.+:~_-]{0,199})$', metadata)
    require(version and re.search(rb'(?m)^Package: kura-core$', metadata))
    previous = re.search(rb'(?m)^_KURA_EMBEDDED_UPGRADE_PAYLOAD = (.+)$', parts['preinst'])
    require(previous is not None)
    published = ast.literal_eval(previous[1].decode())
    require(set(published) == {'home', 'directories', 'files', 'controls'})
    payload = upgrade_payload(assembly)
    require(all(published[name] == value for name, value in payload.items()))
    postinst = hashlib.sha256(parts['postinst']).hexdigest()
    require(published['controls']['postinst'] == postinst)
    manifest = payload['files']['libexec/key-backup/manifest.json'][1]
    return dict(packageVersion=version[1].decode(), manifestSha256=manifest, postinstSha256=postinst)


def issued_layout_plan(assembly, earlier, issued, path):
    observed = json.loads(path.read_bytes())
    require(set(observed) == {'maintenanceId', 'root', 'machineSha256', 'recovery', 'records', 'scripts', 'data'})
    digest = lambda value: isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None
    identity = lambda value: isinstance(value, list) and len(value) == 2 and all(type(x) is int and x > 0 for x in value)
    operation = observed['maintenanceId']
    require(isinstance(operation, str) and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', operation))
    require(identity(observed['root']) and identity(observed['data']) and digest(observed['machineSha256']))
    recovery = observed['recovery']
    require(set(recovery) == {'mode', 'device', 'inode'} and recovery['mode'] == 'reinstall'
            and identity([recovery['device'], recovery['inode']]))
    records = observed['records']
    require(set(records) == {'intent.json', 'layout-repair.json', 'setup-layout-intent.json'}
            and all(len(value) == 3 and identity(value[:2]) and digest(value[2]) for value in records.values()))
    scripts = {item.name: hashlib.sha256(item.read_bytes()).hexdigest()
               for item in sorted((assembly / 'bin').glob('*.sh')) if item.is_file() and not item.is_symlink()}
    require(scripts.keys() == observed['scripts'].keys() and all(map(digest, observed['scripts'].values())))
    templates = {name: value for name, value in scripts.items() if value != observed['scripts'][name]}
    require(templates.keys() == {'start_kura.sh', 'start_kura_background.sh', 'start_kura_debug.sh'})
    require(earlier['manifestSha256'] == issued['manifestSha256']
            and earlier['packageVersion'] != issued['packageVersion'])
    config = ast.parse((assembly / 'bin/kura_dhcp_configuration.py').read_bytes())
    default, = [ast.literal_eval(node.value) for node in config.body if isinstance(node, ast.Assign)
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'DEFAULT']
    return dict(schema=1, **observed, earlier=earlier, issued=issued, templates=templates,
                dhcpSha256=hashlib.sha256(default).hexdigest(),
                installPolicySha256=hashlib.sha256((assembly / 'install/manage_kura_users.sh').read_bytes()).hexdigest())


def layout_repair_source():
    return '\n'.join(Path(__file__).with_name(name).read_text()
                     for name in ('prelayout-repair.py', 'issued-layout-repair.py'))


def embed_layout_repair(preinst, postinst, assembly, predecessor, issued=None):
    token = 'raise RuntimeError("Kura retained layout repair was not embedded")'
    content = preinst.read_text()
    require(content.count(token) == 1)
    names = dict(_KURA_LAYOUT_REPAIR_PREDECESSOR=predecessor, _KURA_LAYOUT_REPAIR_HOME=assembly.name,
                 _KURA_LAYOUT_REPAIR_POSTINST_SHA256=hashlib.sha256(postinst.read_bytes()).hexdigest(),
                 _KURA_ISSUED_LAYOUT_PLAN=issued)
    source = layout_repair_source()
    helper = ''.join(f'{key} = {value!r}\n' for key, value in names.items()) + source
    compile(helper, 'prelayout-repair.py', 'exec', dont_inherit=True)
    preinst.write_text(content.replace(token, helper))


def embed_upgrade_copy(preinst, assembly):
    token = 'raise RuntimeError("Kura upgrade copy was not embedded")'
    source = Path(__file__).with_name('preinst-upgrade-copy.py').read_bytes()
    require(0 < len(source) <= 32768)
    compile(source, 'preinst-upgrade-copy.py', 'exec', dont_inherit=True)
    content = preinst.read_text()
    require(content.count(token) == 1)
    controls = {}
    for hook in ('postinst', 'prerm', 'postrm'):
        with preinst.with_name(hook).open('rb') as stream:
            controls[hook] = hashlib.file_digest(stream, 'sha256').hexdigest()
    data = dict(upgrade_payload(assembly), controls=controls)
    inputs = '_KURA_EMBEDDED_UPGRADE_PAYLOAD = ' + repr(data)
    helper = '_KURA_EMBEDDED_UPGRADE_COPY_SOURCE = ' + repr(source)
    preinst.write_text(content.replace(token, inputs + '\n' + helper))


def embed_policy_readers(preinst,lifecycle,journal,manifest):
    token='raise RuntimeError("Kura key-policy readers were not embedded")'
    require(preinst.is_file() and not preinst.is_symlink())
    require(manifest.is_file() and not manifest.is_symlink())
    raw = manifest.read_bytes()
    predecessors = json.loads(raw)['generation'].get('publishedPredecessorManifestSha256s', [])
    assignments = ['_KURA_INCOMING_KEY_MANIFEST_SHA256 = ' + repr(hashlib.sha256(raw).hexdigest()),
                   '_KURA_INCOMING_KEY_PREDECESSORS = ' + repr(tuple(predecessors))]
    readers = (('_KURA_EMBEDDED_LIFECYCLE_SOURCE', lifecycle, 160 * 1024),
               ('_KURA_EMBEDDED_JOURNAL_SOURCE', journal, 128 * 1024),
               ('_KURA_REMOVAL_HOME_SOURCE', Path(__file__).with_name('removal-home.py'), 32768))
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


def prepare_broker_packages(assembly, architecture):
    # These flat directories are generated exclusively by this build.
    # Each builder writes its manifest into a fresh directory.
    libexec = assembly / 'libexec'
    require(assembly.is_dir() and not assembly.is_symlink()
            and libexec.is_dir() and not libexec.is_symlink())
    builders = {
        'clock-broker': prepare_clock_service,
        'reboot-broker': reboot_broker.package_cohort,
        'journal-export': journal_export.package_cohort,
        'ownership-markers': ownership_markers.package_cohort,
        'firewall-tables': firewall_tables.package_cohort,
        'firewall-publish': lambda home: firewall_publish.package_cohort(
            home, home.parent / 'native' / ('worker-' + architecture), architecture),
        'command-executor': command_executor.package_cohort,
        'modem-driver': modem_driver.package_cohort,
        'bind-service': bind_service.package_cohort,
        'dhcp-service': dhcp_service.package_cohort,
        'modem-reset': modem_reset.package_cohort,
    }
    for name in builders:
        destination = libexec / name
        require(not destination.is_symlink())
        if destination.exists():
            require(destination.is_dir() and all(
                entry.is_file() and not entry.is_symlink() for entry in destination.iterdir()))
    for name, build in builders.items():
        destination = libexec / name
        if destination.exists():
            for entry in destination.iterdir():
                entry.unlink()
            destination.rmdir()
        build(assembly)


def embed_firewall_guard(directory, source):
    guard = source.read_text().rstrip()
    compile(guard, str(source), 'exec')
    for hook in ('preinst', 'prerm', 'postinst', 'postrm'):
        control = directory / hook
        first, _, body = control.read_text().partition('\n')
        require(first == '#!/bin/bash' and 'KURA_FIREWALL_MAINTENANCE' not in body)
        gate = f'''if kura_firewall_result=$(/usr/bin/python3 -I -B - {hook} "${{1:-}}" <<'KURA_FIREWALL_MAINTENANCE'
{guard}
KURA_FIREWALL_MAINTENANCE
); then
    case "$kura_firewall_result" in
        preserve) exit 0 ;;
        '') ;;
        *) exit 1 ;;
    esac
else
    exit "$?"
fi
'''
        control.write_text(f'{first}\n{gate}\n{body}')


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


def embed_configure_phases(control, assembly, repair_predecessor=None, issued=None):
    token = 'raise RuntimeError("Kura Core configure phases were not embedded")'
    manifest = json.loads((assembly/'libexec/key-backup/manifest.json').read_bytes())
    names = dict(CORE_CONFIGURE_HOME=assembly.name, CORE_CONFIGURE_REPAIR_PREDECESSOR=repair_predecessor,
                 CORE_CONFIGURE_VENDOR_UNITS=tuple(sorted(manifest['units'])), CORE_CONFIGURE_ISSUED_LAYOUT_PLAN=issued)
    packages = assembly / 'packages'
    factory = {}
    for path in sorted(packages.iterdir()):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                factory[path.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    names['CORE_CONFIGURE_FACTORY_PACKAGES'] = factory
    for name, filename in (('CORE_REMOVAL_HOME_SOURCE', 'removal-home.py'),
                           ('CORE_RETAINED_PREFLIGHT_SOURCE', 'retained-generation-preflight.py')):
        names[name] = Path(__file__).with_name(filename).read_bytes()
    for name, relative in (
            ('CORE_CONFIGURE_LIFECYCLE_SHA', 'bin/kura_key_service_lifecycle.py'),
            ('CORE_CONFIGURE_MANIFEST_SHA', 'libexec/key-backup/manifest.json'),
            ('CORE_CONFIGURE_INSTALLER_SHA', 'install/kura_install.sh'),
            ('CORE_CONFIGURE_OWNERSHIP_SHA', 'bin/kura_runtime_ownership.py'),
            ('CORE_CONFIGURE_CLOCK_SETUP_SHA', 'bin/kura_clock_setup.py'),
            ('CORE_CONFIGURE_REBOOT_SETUP_SHA', 'bin/kura_reboot_setup.py')):
        names[name] = hashlib.sha256((assembly / relative).read_bytes()).hexdigest()
    source = layout_repair_source() + '\n' + Path(__file__).with_name('postinst-configure.py').read_text()
    source = ''.join(f'{key} = {value!r}\n' for key, value in names.items()) + source
    compile(source, 'postinst-configure.py', 'exec', dont_inherit=True)
    content = control.read_text()
    require(content.count(token) == 1)
    control.write_text(content.replace(token, source))


if __name__ == "__main__":
    require(len(sys.argv) == 5)
    previous = os.environ.get('KURA_PUBLISHED_GENERATION_PREDECESSORS')
    predecessors = tuple(Path(path) for path in previous.split(os.pathsep)) if previous else ()
    prepare(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), predecessors)
    prepare_broker_packages(Path(sys.argv[1]), sys.argv[4])
    embed_journal_reader(Path(sys.argv[1]).parent/'filtered-control/preinst',Path(sys.argv[1])/'bin/kura_key_journal.py')
    embed_main_link_migration(Path(sys.argv[1]).parent/'filtered-control/preinst')
    embed_package_helper(Path(sys.argv[1]).parent/'filtered-control/preinst',
                         Path(sys.argv[1])/'bin/kura_modem_cohort.py', 'modem cohort')
    embed_package_helper(Path(sys.argv[1]).parent/'filtered-control/preinst',
                         Path(sys.argv[1])/'bin/kura_wpa_policy.py', 'WPA policy admission')
    embed_managed_nm_preflight(Path(sys.argv[1]).parent/'filtered-control/preinst',
                               Path(sys.argv[1])/'install/manage_kura_users.sh')
    embed_policy_readers(Path(sys.argv[1]).parent/'filtered-control/preinst',Path(sys.argv[1])/'bin/kura_key_service_lifecycle.py',
        Path(sys.argv[1])/'bin/kura_key_journal.py', Path(sys.argv[1])/'libexec/key-backup/manifest.json')
    embed_package_helper(Path(sys.argv[1]).parent/'filtered-control/preinst',
                         Path(__file__).with_name('retained-generation-preflight.py'), 'retained generation preflight')
    for hook in ('prerm', 'postrm'):
        control = Path(sys.argv[1]).parent / 'filtered-control' / hook
        embed_package_helper(control, Path(__file__).with_name('removal-home.py'), 'removal home')
    for hook in ('preinst', 'postinst', 'prerm'):
        control = Path(sys.argv[1]).parent / 'filtered-control' / hook
        embed_package_helper(control, Path(__file__).with_name('addon-code-policy.py'), 'addon-code policy')
        embed_package_helper(control, Path(sys.argv[1]) / 'bin/kura_watchdog_maintenance.py', 'watchdog maintenance')
    assembly = Path(sys.argv[1])
    repair = os.environ.get('KURA_RETAINED_LAYOUT_REPAIR_DEB')
    predecessor = layout_repair_predecessor(assembly, Path(repair)) if repair else None
    reviewed = os.environ.get('KURA_ISSUED_LAYOUT_REPAIR_PLAN')
    earlier = os.environ.get('KURA_ISSUED_LAYOUT_EARLIER_DEB')
    require(bool(reviewed) == bool(earlier) and (not reviewed or predecessor is not None))
    issued = (issued_layout_plan(assembly, layout_repair_predecessor(assembly, Path(earlier)),
                                 predecessor, Path(reviewed)) if reviewed else None)
    control = assembly.parent/'filtered-control'
    embed_configure_phases(control/'postinst', assembly, predecessor, issued)
    embed_layout_repair(control/'preinst', control/'postinst', assembly, predecessor, issued)
    for hook in ('preinst', 'prerm'):
        embed_clock_guard(Path(sys.argv[1]).parent/'filtered-control'/hook)
        embed_reboot_guard(Path(sys.argv[1]).parent/'filtered-control'/hook)
    target = Path(sys.argv[1]).parent
    embed_firewall_guard(target / 'filtered-control', target / 'native/package-maintenance.py')
    # Bind the finalized installed control files. The preinst itself is bound at runtime.
    embed_upgrade_copy(Path(sys.argv[1]).parent/'filtered-control/preinst', Path(sys.argv[1]))
