#!/usr/bin/env python3
"""Stage only the explicit Netplan payload; never package the legacy installer."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ET.register_namespace('esf', 'http://eurotech.com/esf/2.0')
ET.register_namespace('ocd', 'http://www.osgi.org/xmlns/metatype/v1.2.0')

MODULE = Path(__file__).resolve().parent.parent


def deduplicate_plugins(home, launcher):
    seen = {}
    for path in sorted((home / 'plugins').rglob('*.jar')):
        name = launcher.bundle_name(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if name in seen:
            if seen[name] != digest:
                raise ValueError('Different payloads for bundle identity: ' + name)
            path.unlink()
            print('Removed byte-identical duplicate: ' + path.name)
        else:
            seen[name] = digest


def stage(build, version, arch):
    if arch not in ('arm64', 'amd64') or '${' in version:
        raise ValueError('Explicit Debian architecture and package version required')
    root = build / 'netplan-root'
    control = build / 'netplan-control'
    # These are this module's generated payloads, never runtime or user data.
    for path in [root, control]:
        if path.is_symlink():
            raise ValueError('Refusing symlink build output')
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
    source = build / 'netplan-input'
    home = root / 'opt/eclipse/kura'
    home.mkdir(parents=True)
    for name in ['plugins', 'framework']:
        shutil.copytree(source / name, home / name)
    (home / 'bin').mkdir()
    shutil.copy2(source / 'bin/gen_config_ini.sh', home / 'bin/gen_config_ini.sh')
    shutil.copy2(MODULE / 'resources/launch-netplan.py', home / 'bin/launch-netplan.py')
    spec = importlib.util.spec_from_file_location('launcher', home / 'bin/launch-netplan.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    deduplicate_plugins(home, launcher)
    names = launcher.check_bundles(home)
    if 'org.eclipse.kura.linux.clock' in names:
        raise ValueError('Unexpected JVM clock writer')
    native = 'aarch64' if arch == 'arm64' else 'x86_64'
    properties = (home / 'framework/kura.properties').read_text()
    replacements = {'kura.user.config': '/var/lib/kura-netplan/user', 'kura.data': '/var/lib/kura-netplan/data',
                    'kura.packages': '/var/lib/kura-netplan/packages', 'kura.snapshots': '/var/lib/kura-netplan/user/snapshots',
                    'kura.tmp': '/var/lib/kura-netplan/tmp', 'kura.log.download.sources': '/var/log/kura-netplan',
                    'kura.have.net.admin': 'true', 'kura.project': 'generic-' + native}
    for key, value in replacements.items():
        import re
        properties = re.sub(r'^' + re.escape(key) + r'=.*$', key + '=' + value, properties, flags=re.M)
    if '${' in properties or '{kura.' in properties:
        raise ValueError('Unresolved template in Kura properties')
    (home / 'framework/kura.properties').write_text(properties)
    (home / 'framework/netplan-profile.json').write_text(json.dumps({'profile': 'netplan', 'schema': 1, 'arch': arch}) + '\n')
    config = (home / 'framework/config.ini').read_text().replace('/tmp/.kura/data', '/var/lib/kura-netplan/data/osgi').replace('org.osgi.service.http.port=80', 'org.osgi.service.http.port=8080')
    config += '\nkura.networking.provider=netplan\nkura.configuration.external.pids=org.eclipse.kura.net.admin.NetworkConfigurationService\n'
    (home / 'framework/config.ini').write_text(config)
    (home / 'framework/sibling-install-order').write_text('networking-netplan\n')
    generator = home / 'bin/gen_config_ini.sh'
    generator.write_text(generator.read_text().replace('CONFLICT_LOG_DIR="/var/log/kura"', 'CONFLICT_LOG_DIR="/var/log/kura-netplan"'))
    logs = home / 'log4j'
    logs.mkdir()
    log_config = (source / 'log4j/log4j.xml').read_text().replace('>/var/log<', '>/var/log/kura-netplan<')
    (logs / 'log4j.xml').write_text(log_config.replace('${log_dir}/kura/archives', '${log_dir}'))
    defaults = root / 'usr/share/kura-netplan/defaults/user'
    shutil.copytree(source / 'user', defaults)
    (defaults / 'kura_custom.properties').write_text('kura.snapshots.encrypt=true\n')
    seed = defaults / 'snapshots/snapshot_0.xml'
    document = ET.parse(seed)
    for config in list(document.getroot()):
        if config.get('pid') in ('org.eclipse.kura.clock.ClockService', 'org.eclipse.kura.watchdog.WatchdogService'):
            document.getroot().remove(config)
            continue
        if config.get('pid') == 'org.eclipse.kura.http.server.manager.HttpService':
            props = config.find('{*}properties')
            values = {'https.ports': '8443', 'https.client.auth.ports': '8444', 'http.ports': '8080'}
            for name, value in values.items():
                prop = next((p for p in props if p.get('name') == name), None)
                if prop is None:
                    prop = ET.SubElement(props, '{http://eurotech.com/esf/2.0}property', {'name': name, 'array': 'true', 'encrypted': 'false', 'type': 'Integer'})
                    ET.SubElement(prop, '{http://eurotech.com/esf/2.0}value')
                prop.find('{*}value').text = value
    document.write(seed, encoding='utf-8', xml_declaration=True)
    unit = root / 'usr/lib/systemd/system/kura-netplan.service'
    unit.parent.mkdir(parents=True)
    shutil.copy2(MODULE / 'resources/kura-netplan.service', unit)
    settings = root / 'etc/kura-netplan/runtime.json'
    settings.parent.mkdir(parents=True)
    shutil.copy2(MODULE / 'resources/runtime.json', settings)
    (control / 'conffiles').write_text('/etc/kura-netplan/runtime.json\n')
    (control / 'control').write_text(f'''Package: kura-core-netplan
Version: {version}
Section: misc
Priority: optional
Architecture: {arch}
Maintainer: YOFC Kura maintainers
Pre-Depends: python3
Depends: openjdk-21-jre-headless | openjdk-25-jre-headless, systemd, passwd
Provides: kura-core (= {version})
Conflicts: kura-core, kura-networking, kura-firewall-only
Replaces: kura-core
Description: Kura core with a low privilege Netplan agent profile
 Explicit installation profile. Does not install NetworkManager or take over networking.
''')
    lifecycle = (MODULE / 'tools/lifecycle.py').read_text()
    for script in ['preinst', 'postinst', 'prerm', 'postrm']:
        path = control / script
        path.write_text('#!/usr/bin/python3\nSCRIPT_NAME = ' + repr(script) + '\n' + lifecycle)
        path.chmod(0o755)
    print(json.dumps({'profile': 'netplan', 'architecture': arch, 'bundles': len(names), 'output': str(root)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--arch', required=True)
    args = parser.parse_args()
    stage(args.build_dir, args.version, args.arch)
