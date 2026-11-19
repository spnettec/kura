# SPDX-License-Identifier: EPL-2.0
"""Require the installed Networking release to use the typed modem, DNS and DHCP protocols."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

HOME = Path('/opt/eclipse/kura')
SHARE = Path('/usr/share')
NETWORKING_RULE = Path('/usr/share/polkit-1/rules.d/52-kura-networking.rules')
PROVIDERS = {'kura-networking': 'networking', 'kura-firewall-only': 'firewall'}
MODEM_NAME = re.compile(r'org\.eclipse\.kura\.linux\.net-[0-9A-Za-z.+~-]+\.jar')
BIND_NAME = re.compile(r'org\.eclipse\.kura\.linux\.systemd\.provider-[0-9A-Za-z.+~-]+\.jar')
NM_NAME = re.compile(r'org\.eclipse\.kura\.nm-[0-9A-Za-z.+~-]+\.jar')
ENVIRONMENT = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}


def protected(path, directory=False):
    for entry in (*reversed(path.parents), path):
        metadata = entry.lstat()
        if entry == HOME and stat.S_ISLNK(metadata.st_mode):
            link = Path(os.readlink(entry))
            target = entry.parent / link if not link.is_absolute() else link
            if (metadata.st_uid != 0 or target.parent != entry.parent
                    or not re.fullmatch(r'kura_[0-9A-Za-z.+~-]+_linux', target.name)):
                raise ValueError('Unpaired Core installation path')
            protected(target, directory=True)
            continue
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError('Unprotected Networking release asset')
        if entry != path or directory:
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError('Invalid Networking release directory')
        elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError('Invalid Networking release file')
    return metadata


def stamp(value):
    return (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
            value.st_nlink, value.st_size, value.st_ctime_ns, value.st_mtime_ns)


def snapshot(path, limit, read):
    recorded = protected(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if stamp(recorded) != stamp(before) or not 0 < before.st_size <= limit:
            raise ValueError('Invalid bounds or identity for Networking release input')
        result = read(stream)
        if stamp(before) != stamp(os.fstat(stream.fileno())) or stamp(before) != stamp(path.lstat()):
            raise ValueError('Networking release input changed while reading')
        return result


def dpkg(*args):
    return subprocess.run(['/usr/bin/dpkg-query', *args], env=ENVIRONMENT, capture_output=True, timeout=5)


def provider_installed(package):
    result = dpkg('-W', '-f=${db:Status-Status}\n', package)
    if (result.returncode == 1 and result.stdout == b''
            and result.stderr.strip() == os.fsencode('dpkg-query: no packages found matching ' + package)):
        return False
    if result.returncode == 0:
        if result.stdout in (b'config-files\n', b'not-installed\n'):
            return False
        if result.stdout == b'installed\n':
            return True
    raise ValueError('Networking package is not in a settled state')


def active_provider():
    configured = [package for package in PROVIDERS if provider_installed(package)]
    if len(configured) > 1:
        raise ValueError('Multiple configured Networking providers')
    return configured[0] if configured else None


def require_ownership(path, package):
    result = dpkg('-S', str(path))
    if result.returncode != 0 or result.stdout.strip() != os.fsencode(package + ': ' + str(path)):
        raise ValueError('Provider is not the installed Networking payload')


def check():
    installed = active_provider()
    for package, directory in PROVIDERS.items():
        provider_dir = HOME / 'siblings' / directory / '4'
        proof_dir = SHARE / package
        files = ()
        if os.path.lexists(provider_dir):
            protected(provider_dir, directory=True)
            files = tuple(provider_dir.iterdir())
        check_asset(package, provider_dir, files, proof_dir / 'modem-provider.json',
                    MODEM_NAME, 'modemProtocol', installed == package)
        check_asset(package, provider_dir, files, proof_dir / 'bind-provider.json',
                    BIND_NAME, 'bindProtocol', installed == package == 'kura-networking')
        check_asset(package, provider_dir, files, proof_dir / 'bind-config-provider.json',
                    BIND_NAME, 'bindConfigurationProtocol', installed == package == 'kura-networking')
        check_asset(package, provider_dir, files, proof_dir / 'bind-outcome-provider.json',
                    BIND_NAME, 'bindOutcomeProtocol', installed == package == 'kura-networking')

        if package == 'kura-networking':
            check_dhcp_provider(installed == package)
            folder = HOME / 'siblings' / 'networking' / '5s'
            jars = ()
            if os.path.lexists(folder):
                protected(folder, directory=True)
                jars = tuple(folder.iterdir())
            check_asset(package, folder, jars, proof_dir / 'wifi-nm-provider.json',
                        NM_NAME, 'wifiNmProtocol', installed == package, policy=NETWORKING_RULE)


def check_dhcp_provider(present):
    package = 'kura-networking'
    root = HOME / 'siblings' / 'networking'
    for tier, filename, pattern, protocol in (
        ('4', 'dhcp-provider.json', MODEM_NAME, 'dhcpProtocol'),
        ('5s', 'dhcp-nm-provider.json', NM_NAME, 'dhcpNmProtocol'),
    ):
        provider_dir = root / tier
        files = ()
        if os.path.lexists(provider_dir):
            protected(provider_dir, directory=True)
            files = tuple(provider_dir.iterdir())
        check_asset(package, provider_dir, files, SHARE / package / filename, pattern, protocol, present)


def check_asset(package, provider_dir, files, proof_path, name, protocol, present, *, policy=None):
    jars = {path for path in files if name.fullmatch(path.name)}
    if present:
        check_provider(package, provider_dir, proof_path, jars, name, protocol, policy=policy)
    elif jars or os.path.lexists(proof_path):
        raise ValueError(f'Detached Networking provider files for {protocol}')


def check_provider(package, provider_dir, proof_path, jars, name, protocol, *, policy=None):
    if not os.path.lexists(proof_path):
        raise ValueError(f'Missing paired Networking release proof for {protocol}')
    require_ownership(proof_path, package)
    proof = snapshot(proof_path, 4096, json.load)
    keys = {'schema', protocol, 'provider', 'sha256'}
    if policy is not None:
        keys.add('policySha256')
    if (type(proof) is not dict or set(proof) != keys
            or type(proof['schema']) is not int or proof['schema'] != 1
            or type(proof[protocol]) is not int or proof[protocol] != 1
            or not isinstance(proof['provider'], str) or not name.fullmatch(proof['provider'])
            or not isinstance(proof['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', proof['sha256'])):
        raise ValueError(f'Networking provider contract is invalid for {protocol}')
    provider = provider_dir / proof['provider']
    if jars != {provider}:
        raise ValueError(f'Expected one paired Networking provider for {protocol}')
    require_ownership(provider, package)
    if snapshot(provider, 64 * 1024 * 1024,
                lambda stream: hashlib.file_digest(stream, 'sha256').hexdigest()) != proof['sha256']:
        raise ValueError(f'Networking provider fingerprint changed for {protocol}')
    if policy is not None:
        require_ownership(policy, package)
        if snapshot(policy, 16 * 1024,
                    lambda stream: hashlib.file_digest(stream, 'sha256').hexdigest()) != proof['policySha256']:
            raise ValueError('Unpaired Networking Wi-Fi policy')


if __name__ == '__main__':
    try:
        check()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print('Cannot start or replace Kura Main: install the paired typed Networking providers. '
              + str(error), file=sys.stderr)
        sys.exit(1)
