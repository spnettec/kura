#!/usr/bin/python3
"""Foreground launcher. No shell interpolation and no network ownership changes."""
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

HOME = Path('/opt/eclipse/kura')
STATE = Path('/var/lib/kura-netplan')
FORBIDDEN = {'org.eclipse.kura.nm', 'org.eclipse.kura.linux.net',
             'org.eclipse.kura.net.admin.firewall', 'org.eclipse.kura.network.threat.manager'}


def bundle_name(path):
    with zipfile.ZipFile(path) as archive:
        manifest = archive.read('META-INF/MANIFEST.MF').decode().replace('\r\n', '\n')
    manifest = re.sub(r'\n ', '', manifest)
    headers = dict(line.split(': ', 1) for line in manifest.split('\n\n', 1)[0].splitlines() if ': ' in line)
    return headers.get('Bundle-SymbolicName', '').split(';', 1)[0]


def check_bundles(home):
    names = set()
    for path in sorted(home.rglob('*.jar')):
        if not (path.is_relative_to(home / 'plugins') or path.is_relative_to(home / 'siblings')):
            continue
        name = bundle_name(path)
        if not name or name in names:
            raise ValueError(f'Missing or duplicate bundle identity: {path.name}')
        if name in FORBIDDEN:
            raise ValueError(f'Conflicting network writer: {name}')
        names.add(name)
    return names


def main():
    if not (STATE / '.initialized').is_file():
        raise ValueError('Package initialization is incomplete; do not reset retained data')
    settings = json.loads(Path('/etc/kura-netplan/runtime.json').read_text())
    endpoint = settings['socket']
    if not isinstance(endpoint, str) or not endpoint.startswith('/') or len(endpoint.encode()) > 100:
        raise ValueError('Invalid agent socket')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*', settings['agentUser']):
        raise ValueError('Invalid agent OS user')
    if not re.fullmatch(r'[1-9][0-9]{1,4}[mg]', settings['memory']):
        raise ValueError('Invalid JVM memory')
    key = Path('/etc/kura-netplan/crypto.key').read_text().rstrip('\n')
    if len(key.encode()) != 32:
        raise ValueError('A valid local 32-byte crypto key is required')
    check_bundles(HOME)
    config = Path('/run/kura-netplan/configuration')
    config.mkdir(mode=0o700, exist_ok=True)
    result = subprocess.run(['/bin/sh', str(HOME / 'bin/gen_config_ini.sh'),
                             str(HOME / 'framework/config.ini'), str(HOME / 'plugins'),
                             str(HOME / 'siblings')], check=True, capture_output=True, text=True)
    if result.stderr:
        print(result.stderr, end='', file=__import__('sys').stderr)
    (config / 'config.ini').write_text(result.stdout)
    args = ['/usr/bin/java', '-Xms128m', '-Xmx' + settings['memory'],
            '--add-opens=java.base/java.lang=ALL-UNNAMED', '--add-opens=java.base/java.util=ALL-UNNAMED',
            '--add-modules=ALL-SYSTEM', '-Dkura.os.version=debian', '-Dtarget.device=linux',
            '-Dkura.management.socket=' + endpoint, '-Dkura.management.agent.user=' + settings['agentUser'],
            '-Dkura.networking.provider=netplan',
            '-Dkura.configuration.external.pids=org.eclipse.kura.net.admin.NetworkConfigurationService',
            '-Dkura.home=' + str(HOME), '-Dkura.configuration=file:' + str(HOME / 'framework/kura.properties'),
            '-Dkura.custom.configuration=file:' + str(STATE / 'user/kura_custom.properties'),
            '-Ddpa.configuration=' + str(STATE / 'packages/dpa.properties'),
            '-Dlog4j.configurationFile=file:' + str(HOME / 'log4j/log4j.xml'),
            '-Dlog4j2.disable.jmx=true', '-Djdk.tls.trustNameService=true', '-Declipse.ignoreApp=true',
            '-jar', str(HOME / 'plugins/org.eclipse.equinox.launcher-1.7.100.jar'),
            '-configuration', str(config), '-consoleLog']
    # CryptoServiceImpl accepts the environment; keep the key out of argv and logs.
    os.environ['KURA_CRYPTO_SECRET_KEY'] = key
    os.chdir(HOME)
    os.execv(args[0], args)


if __name__ == '__main__':
    main()
