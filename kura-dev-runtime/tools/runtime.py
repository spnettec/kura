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


def ports():
    result = {key: int(os.environ.get(key, default)) for key, default in
              [('KURA_HTTP_PORT', '8080'), ('KURA_HTTPS_PORT', '8443'), ('KURA_CLIENT_AUTH_PORT', '8444')]}
    if any(port < 1 or port > 65535 for port in result.values()) or len(set(result.values())) != 3:
        raise ValueError('HTTP, HTTPS and client-auth ports must be distinct integers in 1..65535')
    return result


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


def properties_escape(value):
    return str(value).replace('\\', '\\\\').replace(':', '\\:')


def prepare(profile):
    guard(profile)
    home = data_home(profile)
    values = ports()
    check_ports(values)
    initialize(home, values)
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
    check_ports(ports())
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
    parser.add_argument('command', choices=['assemble', 'prepare', 'run', 'guard'])
    parser.add_argument('--profile', default='auto')
    parser.add_argument('--debug-port', type=int)
    args = parser.parse_args()
    try:
        profile = profile_name(args.profile)
        if args.command == 'run':
            run(profile, args.debug_port)
        else:
            globals()[args.command](profile)
    except (ValueError, OSError, KeyError) as exc:
        print(f'Kura runtime: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == '__main__':
    main()
