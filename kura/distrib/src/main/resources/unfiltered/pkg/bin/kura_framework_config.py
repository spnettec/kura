#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Publish the installed Equinox configuration before starting a JVM."""
import fcntl
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile


API = 'org.eclipse.kura.api'
API_PACKAGES = frozenset('org.eclipse.kura.' + name for name in ('channel', 'comm', 'driver', 'message'))
API_VERSION = '2.0.0'
BUNDLE_ENTRY = rb'reference\\:file\\:(.+)@[0-9](?:\\:start)?'
HEADER_SEPARATOR = re.compile(r'"(?:[^"\\]|\\.)*"|[,;]')


def manifest_clauses(header):
    """Return clauses with their quoted attribute values kept intact."""
    clause = []
    start = 0
    for match in HEADER_SEPARATOR.finditer(header):
        separator = match.group()
        if separator not in (',', ';'):
            continue
        clause.append(header[start:match.start()].strip())
        start = match.end()
        if separator == ',':
            yield clause
            clause = []
    clause.append(header[start:].strip())
    yield clause


def package_clauses(header):
    for clause in manifest_clauses(header):
        names, attributes = [], {}
        for entry in clause:
            name, sep, value = entry.partition('=')
            if sep:
                attributes[name.strip()] = value.strip().strip('"')
            elif not attributes:
                names.append(name)
        for name in API_PACKAGES.intersection(names):
            yield name, attributes


def version(value):
    match = re.fullmatch(r'(\d+)(?:\.(\d+)(?:\.(\d+)(?:\.([A-Za-z0-9_-]+))?)?)?', value)
    if match is None:
        raise ValueError(f'Invalid OSGi package version {value!r}')
    major, minor, micro, qualifier = match.groups()
    return int(major), int(minor or '0'), int(micro or '0'), qualifier or ''


def accepts(requirement, exported):
    current = version(exported)
    if requirement[0] not in '[(':
        return current >= version(requirement)
    match = re.fullmatch(r'([\[(])\s*([^,]+?)\s*,\s*([^,]+?)\s*([\])])', requirement)
    if match is None:
        raise ValueError(f'Invalid OSGi package range {requirement!r}')
    low_bound, low, high, high_bound = match.groups()
    low, high = version(low), version(high)
    return (low < current or low == current and low_bound == '[') and (
        current < high or current == high and high_bound == ']')


def check_api_bundles(home, configured):
    """Check the exact bundle list from the paired loader before publishing it."""
    sys.path.insert(0, str(home / 'bin'))
    from kura_key_cohort import Refused, headers

    lines = [line for line in configured.splitlines() if line.startswith(b'osgi.bundles=')]
    if len(lines) != 1:
        raise ValueError('Expected one Equinox bundle list')
    archives = []
    for entry in lines[0].removeprefix(b'osgi.bundles=').split(b','):
        match = re.fullmatch(BUNDLE_ENTRY, entry)
        if match is None:
            raise ValueError('Invalid generated Equinox bundle entry')
        path = Path(os.fsdecode(match[1]))
        try:
            with zipfile.ZipFile(path) as archive:
                try:
                    attributes = archive.getinfo('META-INF/MANIFEST.MF')
                except KeyError:
                    continue
                with archive.open(attributes) as stream:
                    manifest = headers(stream.read(65537))
        except (zipfile.BadZipFile, Refused) as error:
            raise ValueError(f'Cannot inspect bundle {path}: {error}') from error
        bundle = manifest.get('bundle-symbolicname', '').split(';', 1)[0].strip()
        archives.append((path, bundle, manifest))

    providers = [(path, manifest) for path, bundle, manifest in archives if bundle == API]
    if len(providers) != 1:
        raise ValueError(f'Expected one {API} exporter')
    api, manifest = providers[0]
    if not api.resolve().is_relative_to((home / 'plugins').resolve()):
        raise ValueError(f'{API} must come from Core plugins')
    exports = dict(package_clauses(manifest.get('export-package', '')))
    if set(exports) != API_PACKAGES or any(
        attributes.get('version') != API_VERSION for attributes in exports.values()
    ):
        raise ValueError(f'{API} must export the four Kura API packages at {API_VERSION}')

    for path, bundle, manifest in archives:
        if not bundle:
            continue
        for package, attributes in package_clauses(manifest.get('import-package', '')):
            if attributes.get('resolution:') == 'optional':
                continue
            requirement = attributes.get('version', attributes.get('specification-version', '0'))
            if not requirement or not accepts(requirement, API_VERSION):
                raise ValueError(f'{path.name} requires {package} {requirement}, '
                                 f'incompatible with Core {API_VERSION}')


def publish(home, directory):
    recovery = None
    if 'KURA_CONTROLLED_RECOVERY_ID' in os.environ or os.path.lexists('/var/lib/kura-recovery-launch'):
        sys.path.insert(0, str(home / 'bin'))
        import kura_recovery_launch as launch
        recovery = launch.selected(home)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # All three launchers share this directory. Only the lock holder may
        # discard a previous process's incomplete configuration.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pending = directory / '.config.ini.pending'
        pending.unlink(missing_ok=True)
        try:
            fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as output:
                with (home / 'framework/config.ini').open('rb') as template:
                    shutil.copyfileobj(template, output)
                output.flush()
                # The independently paired loader appends its normal bundle
                # list. Template read errors above must reach the launcher.
                command = [home / 'bin/gen_config_ini.sh', os.devnull, home / 'plugins', home / 'siblings']
                configured = subprocess.run(command, stdout=subprocess.PIPE, check=True).stdout
                check_api_bundles(home, configured)
                if recovery is not None:
                    marker = b'\nosgi.bundles='
                    launch.require(configured.count(marker) == 1)
                    entry = ('reference\\:file\\:' + str(home / launch.BOOTSTRAP) + '@1\\:start,').encode()
                    configured = configured.replace(marker, marker + entry, 1)
                output.write(configured)
                os.fsync(output.fileno())
            os.replace(pending, directory / 'config.ini')
            os.fsync(lock)
        finally:
            pending.unlink(missing_ok=True)
    finally:
        os.close(lock)


if __name__ == '__main__':
    try:
        if sys.argv[1] == '--check-api':
            check_api_bundles(Path(sys.argv[2]), sys.stdin.buffer.read())
        else:
            publish(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f'Cannot publish Equinox configuration: {error}')
