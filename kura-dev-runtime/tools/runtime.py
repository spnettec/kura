#!/usr/bin/env python3
"""Assemble and run the same real Equinox JAR runtime from Maven, IDEA and CLI."""
import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape
from xml.dom import minidom
from xml.parsers.expat import ExpatError
from generate_pom import filename

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'target/runtime'


def profile_name(value):
    if value == 'auto':
        value = {'Darwin': 'macos', 'Linux': 'linux'}.get(platform.system())
    if value not in ('macos', 'linux'):
        raise ValueError('Supported development profiles: macos, linux')
    return value


def data_home(profile):
    path = Path(os.environ.get('KURA_DEV_HOME', str(Path.home() / '.kura-dev' / profile))).expanduser().resolve()
    if path.is_relative_to(ROOT / 'target'):
        raise ValueError('KURA_DEV_HOME must be outside target: Maven clean must not remove development data')
    return path


PORT_PROPERTIES = {'KURA_HTTP_PORT': 'http.ports', 'KURA_HTTPS_PORT': 'https.ports',
                   'KURA_CLIENT_AUTH_PORT': 'https.client.auth.ports'}


def snapshot(home):
    candidates = sorted((p for p in (home / 'user/snapshots').glob('snapshot_*.xml')
                         if re.fullmatch(r'snapshot_\d+\.xml', p.name)),
                        key=lambda p: int(p.stem.split('_')[1]), reverse=True)
    for path in candidates:
        try:
            return path, minidom.parse(str(path))
        except (ExpatError, UnicodeError):
            continue  # Kura retains malformed snapshots as .bad and falls back itself.
    if candidates:
        raise ValueError('No readable plaintext development snapshot; export/decrypt it before importing')
    return None, None


def http_properties(document):
    if document is None:
        return {}
    for node in document.getElementsByTagName('*'):
        if node.localName == 'configuration' and node.getAttribute('pid') == 'org.eclipse.kura.http.server.manager.HttpService':
            return {prop.getAttribute('name'): prop for prop in node.getElementsByTagName('*')
                    if prop.localName == 'property'}
    return {}


def ports(home=None):
    result = {key: int(default) for key, default in
              [('KURA_HTTP_PORT', '8080'), ('KURA_HTTPS_PORT', '8443'), ('KURA_CLIENT_AUTH_PORT', '8444')]}
    if home:
        _, document = snapshot(home)
        properties = http_properties(document)
        for key, name in PORT_PROPERTIES.items():
            if name in properties:
                nodes = [n for n in properties[name].getElementsByTagName('*') if n.localName == 'value']
                if len(nodes) != 1:
                    raise ValueError(f'Development runtime requires one {name} entry; found {len(nodes)}')
                result[key] = int(nodes[0].firstChild.nodeValue)
    result.update({key: int(os.environ[key]) for key in result if key in os.environ})
    if any(port < 1 or port > 65535 for port in result.values()) or len(set(result.values())) != 3:
        raise ValueError('HTTP, HTTPS and client-auth ports must be distinct integers in 1..65535')
    return result


def apply_port_overrides(home, values):
    if not any(key in os.environ for key in PORT_PROPERTIES):
        return
    path, document = snapshot(home)
    properties = http_properties(document)
    changed = False
    for key, name in PORT_PROPERTIES.items():
        if key not in os.environ:
            continue
        if name not in properties:
            raise ValueError(f'Cannot override {key}: snapshot has no HttpService {name}')
        node = next(n for n in properties[name].getElementsByTagName('*') if n.localName == 'value')
        if node.firstChild.nodeValue != str(values[key]):
            node.firstChild.nodeValue = str(values[key])
            changed = True
    if changed:
        # Preserve the original snapshot and CDATA; Kura selects the highest ID.
        ids = [int(m.group(1)) for p in path.parent.iterdir()
               if (m := re.fullmatch(r'snapshot_(\d+)\.xml(?:\.bad)?', p.name))]
        destination = path.parent / f'snapshot_{max(ids) + 1}.xml'
        with os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(document.toxml(encoding='utf-8'))


def check_ports(values):
    for key, port in values.items():
        with socket.socket() as sock:
            try:
                sock.bind(('0.0.0.0', port))
            except OSError as exc:
                raise ValueError(f'{key}={port} is unavailable: {exc}') from exc


def read_manifest(path):
    with zipfile.ZipFile(path) as jar:
        value = jar.read('META-INF/MANIFEST.MF').decode().replace('\r\n', '\n')
        value = re.sub(r'\n ', '', value).split('\n\n', 1)[0]
        headers = dict(line.split(': ', 1) for line in value.splitlines() if ': ' in line)
        for entry in headers.get('Bundle-ClassPath', '.').split(','):
            entry = entry.strip().strip('"')
            if entry != '.' and entry not in jar.namelist() and not any(n.startswith(entry.rstrip('/') + '/') for n in jar.namelist()):
                raise ValueError(f'{path.name}: missing Bundle-ClassPath {entry}')
    return headers


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def guard(profile=None):
    # Port checks alone miss a JVM suspended before Jetty starts (IDEA Debug).
    processes = subprocess.run(['ps', '-axo', 'pid=,command='], check=True, capture_output=True, text=True)
    for line in processes.stdout.splitlines():
        if ' -jar ' in line and str(RUNTIME / 'launcher.jar') in line:
            pid = line.strip().split(None, 1)[0]
            raise ValueError(f'Runtime is in use by JVM {pid}; stop Run/Debug before building or cleaning')



def initialize(home, values):
    for name in ['data', 'data/packages', 'user/security', 'user/snapshots', 'framework', 'load', 'tmp', 'logs']:
        (home / name).mkdir(parents=True, exist_ok=True)
    seed = home / 'user/snapshots/snapshot_0.xml'
    # Any snapshot (including .bad) or explicit import counts as existing user data.
    if not any((home / 'user/snapshots').glob('snapshot_*')):
        text = (ROOT / 'src/main/resources/snapshot_0.xml').read_text()
        replacements = {'@KURA_DEV_HOME@': escape(str(home)), '@KEYSTORE_PASSWORD@': secrets.token_urlsafe(24),
                        '@HTTP_PORT@': str(values['KURA_HTTP_PORT']), '@HTTPS_PORT@': str(values['KURA_HTTPS_PORT']),
                        '@CLIENT_AUTH_PORT@': str(values['KURA_CLIENT_AUTH_PORT'])}
        for key, value in replacements.items():
            text = text.replace(key, value)
        # Restrictive permissions before writing the initial development keystore password.
        with os.fdopen(os.open(seed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            stream.write(text)


def import_data(profile, source, old_home=None):
    guard(profile)
    home = data_home(profile)
    source_argument = Path(source).expanduser().absolute()
    source = source_argument.resolve()
    if home.exists() and any(home.iterdir()):
        raise ValueError(f'Import requires an empty KURA_DEV_HOME: {home}')
    if source == home or source in home.parents or home in source.parents:
        raise ValueError('Import source and destination must be separate directories')
    if not (source / 'user/snapshots').is_dir():
        raise ValueError('Import source must be a Kura data home containing user/snapshots')
    _, document = snapshot(source)
    if document is None:
        raise ValueError('Import source has no readable development snapshot')
    home.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.kura-import-', dir=home.parent))
    try:
        # Do not import the old framework cache, PDE workspace or executable bundles.
        for name in ('user', 'data'):
            directory = source / name
            if directory.exists():
                if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob('*')):
                    raise ValueError(f'Import source contains symlinks: {directory}')
                shutil.copytree(directory, staging / name)
        replacements = {str(source): str(home), str(source_argument): str(home)}
        if old_home:
            replacements[str(Path(old_home).expanduser())] = str(home)
        for path in (staging / 'user/snapshots').glob('snapshot_*.xml'):
            try:
                text = path.read_text()
                minidom.parseString(text)
            except (ExpatError, UnicodeError):
                continue  # Preserve malformed historical snapshots verbatim.
            for old, new in sorted(replacements.items(), key=lambda item: -len(item[0])):
                text = text.replace(escape(old), escape(new))
            path.write_text(text)
            path.chmod(0o600)
        (staging / 'import.json').write_text(json.dumps({'source': str(source), 'oldHome': old_home}, indent=2) + '\n')
        if home.exists():
            home.rmdir()  # Already checked empty; fail if it changed during import.
        staging.rename(home)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(f'Imported data into {home}; the original data was not modified')


def properties_escape(value):
    return str(value).replace('\\', '\\\\').replace(':', '\\:')


def prepare(profile):
    guard(profile)
    home = data_home(profile)
    values = ports(home)
    check_ports(values)
    initialize(home, values)
    apply_port_overrides(home, values)
    configuration = RUNTIME / 'configuration'
    configuration.mkdir(exist_ok=True)
    template = (ROOT / 'src/main/resources/kura.properties').read_text()
    (configuration / 'kura.properties').write_text(template.replace('@KURA_DEV_HOME@', properties_escape(home)))
    shutil.copy2(ROOT / 'src/main/resources/log4j.xml', configuration / 'log4j.xml')
    mode = 'macosx' if profile == 'macos' else 'emulator'
    options = ['-Xms256m', '-Xmx2g', '-Dosgi.noShutdown=true', '-Declipse.ignoreApp=true',
               '-Dkura.have.net.admin=false', '-Dlog4j2.disable.jmx=true',
               '-Dio.netty.tryReflectionSetAccessible=true', '-Dpolyglot.engine.WarnInterpreterOnly=false',
               '-Dorg.eclipse.equinox.http.jetty.customizer.class=org.eclipse.kura.jetty.customizer.KuraJettyCustomizer',
               f'-Dorg.eclipse.kura.mode={mode}', f'-Dkura.configuration={(configuration / "kura.properties").as_uri()}',
               f'-Dlog4j.configurationFile={(configuration / "log4j.xml").as_uri()}',
               f'-Ddpa.configuration={home / "framework/dpa.properties"}', f'-Dkura.home={home}',
               f'-Dkura.data={home / "data"}', f'-Dkura.snapshots={home / "user/snapshots"}',
               f'-Dfelix.fileinstall.dir={home / "load"}',
               f'-Dorg.osgi.service.http.port={values["KURA_HTTP_PORT"]}',
               '--add-modules=ALL-SYSTEM']
    options += ['--add-opens=java.base/' + package + '=ALL-UNNAMED' for package in
                ['jdk.internal.misc', 'java.lang', 'javax.net.ssl', 'java.nio', 'java.security', 'java.io']]
    (RUNTIME / 'jvm.args').write_text('\n'.join('"' + option.replace('\\', '\\\\').replace('"', '\\"') + '"' for option in options) + '\n')
    (RUNTIME / 'launch.json').write_text(json.dumps({'profile': profile, 'dataHome': str(home), 'ports': values}, indent=2) + '\n')


def assemble(profile):
    guard(profile)
    check_ports(ports(data_home(profile)))
    spec = json.loads((ROOT / 'runtime.json').read_text())
    sources = {coordinate: ROOT / 'target/bundle-cache' / filename(coordinate) for coordinate in
               {x['coordinates'] for x in spec['bundles']} | {spec['framework'], spec['launcher']}}
    missing = [coordinate for coordinate, path in sources.items() if not path.is_file()]
    if missing:
        raise ValueError('Missing runtime artifacts:\n' + '\n'.join(missing))
    staging = Path(tempfile.mkdtemp(prefix='runtime-', dir=ROOT / 'target'))
    inventory = []
    try:
        (staging / 'plugins').mkdir()
        locations = []
        names = set()
        for bundle in spec['bundles']:
            source = sources[bundle['coordinates']]
            headers = read_manifest(source)
            name = headers['Bundle-SymbolicName'].split(';')[0]
            if name != bundle['symbolicName'] or name in names:
                raise ValueError(f'Unexpected or duplicate symbolic name {name}: {bundle["coordinates"]}')
            names.add(name)
            jar = filename(bundle['coordinates'])
            shutil.copy2(source, staging / 'plugins' / jar)
            suffix = f'@{bundle["startLevel"]}' + (':start' if bundle['start'] and 'Fragment-Host' not in headers else '')
            locations.append('reference:file:plugins/' + jar + suffix)
            inventory.append({**bundle, 'bundleVersion': headers['Bundle-Version'], 'sha256': digest(source),
                              'source': 'maven:' + bundle['coordinates'], 'path': 'plugins/' + jar})
        for role in ('launcher', 'framework'):
            source = sources[spec[role]]
            shutil.copy2(source, staging / (role + '.jar'))
            headers = read_manifest(source)
            inventory.append({'role': role, 'coordinates': spec[role],
                              'symbolicName': headers['Bundle-SymbolicName'].split(';')[0],
                              'bundleVersion': headers['Bundle-Version'], 'sha256': digest(source),
                              'source': 'maven:' + spec[role], 'path': role + '.jar'})
        (staging / 'configuration').mkdir()
        # Equinox resolves relative reference URLs against osgi.install.area.
        lines = ['osgi.bundles=' + ','.join(locations), 'osgi.framework=file:framework.jar',
                 'osgi.bundles.defaultStartLevel=' + str(spec['defaultStartLevel']),
                 'osgi.startLevel=' + str(spec['frameworkStartLevel']), 'osgi.configuration.cascaded=false',
                 'eclipse.ignoreApp=true', 'osgi.noShutdown=true']
        (staging / 'configuration/config.ini').write_text('\n'.join(lines) + '\n')
        (staging / 'inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
        if RUNTIME.exists():
            shutil.rmtree(RUNTIME)
        staging.rename(RUNTIME)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    prepare(profile)
    print(f'Assembled {len(spec["bundles"])} bundles: {RUNTIME}; data: {data_home(profile)}')


def run(profile, debug_port):
    prepare(profile)
    java = Path(os.environ['JAVA_HOME']) / 'bin/java' if os.environ.get('JAVA_HOME') else Path(shutil.which('java') or 'java')
    command = [str(java), '@' + str(RUNTIME / 'jvm.args')]
    if debug_port:
        command.append(f'-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=127.0.0.1:{debug_port}')
    command += ['-jar', str(RUNTIME / 'launcher.jar'), '-configuration', str(RUNTIME / 'configuration'),
                '-data', str(data_home(profile) / 'data'), '-consoleLog', '-console']
    os.chdir(RUNTIME)
    os.execvpe(str(java), command, os.environ)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['assemble', 'prepare', 'run', 'guard', 'import-data'])
    parser.add_argument('--profile', default='auto')
    parser.add_argument('--debug-port', type=int)
    parser.add_argument('--source', help='Explicit old Kura data home, used only by import-data')
    parser.add_argument('--old-home', help='Previous absolute data-home prefix to relocate during import')
    args = parser.parse_args()
    try:
        profile = profile_name(args.profile)
        if args.command == 'import-data':
            if not args.source:
                raise ValueError('import-data requires --source')
            import_data(profile, args.source, args.old_home)
        elif args.command == 'run':
            run(profile, args.debug_port)
        else:
            globals()[args.command](profile)
    except (ValueError, OSError, KeyError) as exc:
        print(f'Kura runtime: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == '__main__':
    main()
