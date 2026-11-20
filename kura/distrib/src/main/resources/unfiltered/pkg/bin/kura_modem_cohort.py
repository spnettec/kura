# SPDX-License-Identifier: EPL-2.0
"""Require the installed Networking release to use the paired modem, DNS, DHCP and authorization contracts."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile

HOME = Path('/opt/eclipse/kura')
SHARE = Path('/usr/share')
NETWORKING_RULE = Path('/usr/share/polkit-1/rules.d/52-kura-networking.rules')
NETWORKING_LOCATION_POLICY_SHA256 = '52936e9d56c0f8d979d1531a9e6a837eaed527b0cd6d340c3f27d250d3e88652'
PROVIDERS = {'kura-networking': 'networking', 'kura-firewall-only': 'firewall'}
MODEM_NAME = re.compile(r'org\.eclipse\.kura\.linux\.net-[0-9A-Za-z.+~-]+\.jar')
BIND_NAME = re.compile(r'org\.eclipse\.kura\.linux\.systemd\.provider-[0-9A-Za-z.+~-]+\.jar')
NM_NAME = re.compile(r'org\.eclipse\.kura\.nm-[0-9A-Za-z.+~-]+\.jar')
ENVIRONMENT = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
DPKG = Path('/usr/bin/dpkg')
DPKG_DEB = '/usr/bin/dpkg-deb'
COHORT_HASHES = {
    'kura-networking': 'KURA_NETWORKING_COHORT_SHA256',
    'kura-firewall-only': 'KURA_FIREWALL_ONLY_COHORT_SHA256',
}


class MissingProviderProof(ValueError):
    def __init__(self, package, path, protocol):
        super().__init__(f'Missing paired Networking release proof for {protocol}')
        self.package = package
        self.path = path


def provider_contracts(package):
    modem = ('4', 'modem-provider.json', MODEM_NAME, 'modemProtocol', None)
    bind = (
        ('4', 'bind-provider.json', BIND_NAME, 'bindProtocol', None),
        ('4', 'bind-config-provider.json', BIND_NAME, 'bindConfigurationProtocol', None),
        ('4', 'bind-outcome-provider.json', BIND_NAME, 'bindOutcomeProtocol', None),
    )
    if package == 'kura-firewall-only':
        return (modem, *bind)
    return (
        modem, *bind,
        ('4', 'dhcp-provider.json', MODEM_NAME, 'dhcpProtocol', None),
        ('5s', 'dhcp-nm-provider.json', NM_NAME, 'dhcpNmProtocol', None),
        ('5s', 'wifi-nm-provider.json', NM_NAME, 'wifiNmProtocol', NETWORKING_RULE),
        ('5s', 'modem-reset-provider.json', NM_NAME, 'modemResetProtocol', None),
        ('5s', 'modem-location-provider.json', NM_NAME, 'modemLocationProtocol', None),
    )


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


def check(on_missing=None):
    installed = active_provider()
    for package, directory in PROVIDERS.items():
        proof_dir = SHARE / package
        folders = {}
        missing = False
        for tier, filename, name, protocol, policy in provider_contracts(package):
            if installed != package and protocol in {'modemResetProtocol', 'modemLocationProtocol'}:
                continue
            folder = HOME / 'siblings' / directory / tier
            if folder not in folders:
                folders[folder] = ()
                if os.path.lexists(folder):
                    protected(folder, directory=True)
                    folders[folder] = tuple(folder.iterdir())
            present = installed == package and (package == 'kura-networking' or protocol == 'modemProtocol')
            try:
                check_asset(package, folder, folders[folder], proof_dir / filename, name, protocol,
                            present, policy=policy)
            except MissingProviderProof as error:
                if on_missing is None:
                    raise
                on_missing(error)
                jars = {path for path in folders[folder] if name.fullmatch(path.name)}
                if len(jars) != 1:
                    raise ValueError('Expected one installed legacy Networking bundle')
                jar = next(iter(jars))
                require_ownership(jar, package)
                protected(jar)
                missing = True
        if installed == package == 'kura-networking' and not missing:
            rule = snapshot(NETWORKING_RULE, 16 * 1024, lambda stream: stream.read())
            if hashlib.sha256(rule).hexdigest() != NETWORKING_LOCATION_POLICY_SHA256:
                raise ValueError('Networking still needs the paired read-only ModemManager policy')


def check_modem_reset_provider(present):
    check_nm_bundle('modem-reset-provider.json', 'modemResetProtocol', present)


def check_modem_location_provider(present):
    check_nm_bundle('modem-location-provider.json', 'modemLocationProtocol', present)


def check_nm_bundle(proof, protocol, present):
    folder = HOME / 'siblings' / 'networking' / '5s'
    jars = ()
    if os.path.lexists(folder):
        protected(folder, directory=True)
        jars = tuple(folder.iterdir())
    check_asset('kura-networking', folder, jars, SHARE / 'kura-networking' / proof, NM_NAME, protocol, present)


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
        raise MissingProviderProof(package, proof_path, protocol)
    require_ownership(proof_path, package)
    proof = snapshot(proof_path, 4096, json.load)
    validate_proof(proof, name, protocol, policy=policy)
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


def validate_proof(proof, name, protocol, *, policy):
    keys = {'schema', protocol, 'provider', 'sha256'}
    if policy is not None:
        keys.add('policySha256')
    if (type(proof) is not dict or set(proof) != keys
            or type(proof['schema']) is not int or proof['schema'] != 1
            or type(proof[protocol]) is not int or proof[protocol] != 1
            or not isinstance(proof['provider'], str) or not name.fullmatch(proof['provider'])
            or not isinstance(proof['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', proof['sha256'])):
        raise ValueError(f'Networking provider contract is invalid for {protocol}')


def current_dpkg_archives():
    # The same system dpkg process must be consuming these exact paths. An
    # operator's digest alone cannot authorize a Core-only maintenance command.
    pid = os.getppid()
    executable = DPKG.stat()
    for _ in range(10):
        process = Path('/proc') / str(pid)
        if os.path.samestat((process / 'exe').stat(), executable):
            if (process.stat().st_uid != 0 or not Path('/').samefile(process / 'root')
                    or not Path('/proc/self/ns/mnt').samefile(process / 'ns/mnt')):
                raise ValueError('Debian cohort invocation belongs to another Root')
            arguments = (process / 'cmdline').read_bytes().split(b'\0')[:-1]
            if len(arguments) != 4 or arguments[:2] != [os.fsencode(DPKG), b'--install']:
                raise ValueError('Expected one dpkg --install with Core followed by its provider')
            paths = tuple(Path(os.fsdecode(arg)) for arg in arguments[2:])
            if any(not path.is_absolute() or path.resolve(strict=True) != path for path in paths):
                raise ValueError('Debian cohort archives must use canonical absolute paths')
            return paths
        pid = int((process / 'stat').read_text().rsplit(')', 1)[1].split()[1])
        if pid <= 1:
            break
    raise ValueError('Debian cohort requires the active dpkg installation process')


def package_field(archive, field, **kwargs):
    return subprocess.check_output(
        [DPKG_DEB, '--field', str(archive), field], env=ENVIRONMENT, timeout=5, **kwargs
    ).decode().strip()


def newer_version(new, old):
    subprocess.run([str(DPKG), '--compare-versions', new, 'gt', old],
                   env=ENVIRONMENT, timeout=5, check=True)


def read_provider_assets(stream, package):
    contracts = provider_contracts(package)
    prefix = HOME / 'siblings' / PROVIDERS[package]
    foreign = {path for name, folder in PROVIDERS.items() if name != package
               for path in (HOME / 'siblings' / folder, SHARE / name)}
    proofs = {SHARE / package / spec[1] for spec in contracts}
    assets = {}
    with tarfile.open(fileobj=stream, mode='r|') as archive:
        for entry in archive:
            path = Path('/') / entry.name.removeprefix('./')
            if path in foreign or any(parent in foreign for parent in path.parents):
                raise ValueError('Provider archive contains the other Networking variant')
            if package == 'kura-firewall-only' and (path == NETWORKING_RULE
                    or (path.parent == prefix / '5s' and NM_NAME.fullmatch(path.name))):
                raise ValueError('Firewall-only archive contains NetworkManager provider assets')
            if path in proofs:
                limit = 4096
            elif path == NETWORKING_RULE:
                limit = 16 * 1024
            elif any(path.parent == prefix / tier and name.fullmatch(path.name)
                     for tier, _, name, _, _ in contracts):
                limit = 64 * 1024 * 1024
            else:
                continue
            if (path in assets or not entry.isfile() or entry.uid != 0 or entry.gid != 0
                    or entry.mode & 0o022 or not 0 < entry.size <= limit):
                raise ValueError('Unsafe or duplicate Networking archive asset')
            with archive.extractfile(entry) as source:
                assets[path] = json.load(source) if path in proofs else hashlib.file_digest(source, 'sha256').hexdigest()
    for tier, filename, name, protocol, policy in contracts:
        proof = assets.get(SHARE / package / filename)
        jars = {candidate for candidate in assets if candidate.parent == prefix / tier
                and name.fullmatch(candidate.name)}
        if package == 'kura-firewall-only' and protocol != 'modemProtocol':
            if proof is not None or jars:
                raise ValueError(f'Unexpected firewall-only archive asset for {protocol}')
            continue
        validate_proof(proof, name, protocol, policy=policy)
        path = prefix / tier / proof['provider']
        if jars != {path} or assets[path] != proof['sha256']:
            raise ValueError(f'Incoming Networking archive has an unpaired {protocol} provider')
        if policy is not None and assets.get(policy) != proof['policySha256']:
            raise ValueError('Incoming Networking archive has an unpaired Wi-Fi policy')
    if package == 'kura-networking' and assets.get(NETWORKING_RULE) != NETWORKING_LOCATION_POLICY_SHA256:
        raise ValueError('Incoming Networking archive lacks the read-only ModemManager policy')


def check_provider_archive(path, package, expected_hash, old_version):
    def inspect(stream):
        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected_hash:
            raise ValueError('Incoming Networking archive differs from its approved SHA-256')
        stream.seek(0)
        inherited = dict(pass_fds=(stream.fileno(),))
        member = f'/proc/self/fd/{stream.fileno()}'
        if (package_field(member, 'Package', **inherited) != package
                or package_field(member, 'Architecture', **inherited) != 'all'):
            raise ValueError(f'Expected a {package} archive for the installed provider')
        newer_version(package_field(member, 'Version', **inherited), old_version)
        command = ['/usr/bin/timeout', '45', DPKG_DEB, '--fsys-tarfile', member]
        with subprocess.Popen(command, env=ENVIRONMENT, stdout=subprocess.PIPE, **inherited) as process:
            try:
                read_provider_assets(process.stdout, package)
                # Consume tar padding so dpkg-deb can finish and be checked.
                while process.stdout.read(64 * 1024):
                    pass
                if process.wait(timeout=5) != 0:
                    raise ValueError('Could not read exact Networking archive payload')
            finally:
                if process.poll() is None:
                    process.kill()

    snapshot(path, 256 * 1024 * 1024, inspect)


def check_package_upgrade(old_version, new_version):
    approvals = [(package, os.environ[variable]) for package, variable in COHORT_HASHES.items()
                 if variable in os.environ]
    if (len(approvals) != 1 or not re.fullmatch(r'[0-9a-f]{64}', approvals[0][1])
            or os.environ.get('DPKG_MAINTSCRIPT_PACKAGE') != 'kura-core'
            or os.environ.get('DPKG_MAINTSCRIPT_NAME') != 'preinst'
            or os.environ.get('DPKG_ROOT', '') not in ('', '/')
            or os.environ.get('DPKG_ADMINDIR') != '/var/lib/dpkg'):
        check()
        return

    package, expected = approvals[0]
    installed_paths = None

    def missing_from_package(error):
        nonlocal installed_paths
        if error.package != package:
            raise error
        # An installed package that claims this file has damaged payload, even
        # when the selected incoming archive has a compatible replacement.
        if installed_paths is None:
            listing = dpkg('-L', error.package)
            if listing.returncode != 0 or not listing.stdout:
                raise error
            installed_paths = set(listing.stdout.splitlines())
        if os.fsencode(error.path) in installed_paths:
            raise error

    check(on_missing=missing_from_package)
    if installed_paths is not None:
        core, provider = current_dpkg_archives()
        protected(core)
        if (package_field(core, 'Package') != 'kura-core'
                or package_field(core, 'Version') != new_version):
            raise ValueError('The active dpkg cohort does not match this Core preinst')
        newer_version(new_version, old_version)
        installed = dpkg('-W', '-f=${Version}\n', package)
        if installed.returncode != 0 or not installed.stdout.strip():
            raise ValueError('Cannot prove the installed Networking version')
        check_provider_archive(provider, package, expected, installed.stdout.decode().strip())


if __name__ == '__main__':
    try:
        if len(sys.argv) == 4 and sys.argv[1] == 'upgrade':
            check_package_upgrade(*sys.argv[2:])
        else:
            check()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, tarfile.TarError) as error:
        print('Cannot start or replace Kura Main: install the paired typed Networking providers. '
              + str(error), file=sys.stderr)
        sys.exit(1)
