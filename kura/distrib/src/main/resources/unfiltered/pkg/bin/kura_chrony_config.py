#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Typed changes to the paired Debian Chrony configuration file."""
import errno
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from kura_clock_journal import MAX_CHRONY_CONFIGURATION_BYTES, Refused, digest, identity, read, sync

CONFIG_FILE = Path('/etc/chrony/chrony.conf')
CHRONYD = Path('/usr/sbin/chronyd')
SOURCE_FLAGS = frozenset(('iburst', 'burst', 'nts', 'prefer', 'noselect', 'offline', 'xleave', 'ipv4', 'ipv6'))
SOURCE_VALUES = {'minpoll': (-7, 24), 'maxpoll': (-7, 24), 'maxsources': (1, 64), 'port': (1, 65535)}
TUNING = frozenset(('maxupdateskew', 'maxdistance', 'maxjitter', 'corrtimeratio', 'maxslewrate'))
NUMBER = re.compile(rb'[0-9]{1,8}(?:\.[0-9]{1,8})?')
HOSTNAME = re.compile(rb'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?')


def host(value):
    try:
        ipaddress.ip_address(value.decode('ascii'))
        return b'%' not in value
    except (ValueError, UnicodeError):
        name = value.removesuffix(b'.')
        return len(name) <= 253 and all(HOSTNAME.fullmatch(label) for label in name.split(b'.'))


def integer(value, minimum, maximum):
    return re.fullmatch(rb'-?[0-9]{1,6}', value) is not None and minimum <= int(value) <= maximum


def editable_source(tokens):
    name, address, *options = tokens
    if not host(address):
        return False
    remaining = iter(options)
    seen = set()
    for token in remaining:
        if token in seen:
            return False
        seen.add(token)
        key = token.decode('ascii', errors='replace')
        if key in SOURCE_FLAGS:
            continue
        if key not in SOURCE_VALUES or (key == 'maxsources' and name != b'pool'):
            return False
        if not integer(next(remaining, b''), *SOURCE_VALUES[key]):
            return False
    return True


def editable(tokens):
    name, *args = tokens
    if name in (b'server', b'pool', b'peer'):
        return bool(args) and editable_source(tokens)
    if name == b'makestep':
        return len(args) == 2 and NUMBER.fullmatch(args[0]) is not None and integer(args[1], -1, 65535)
    if name == b'rtcsync':
        return not args
    if name == b'minsources':
        return len(args) == 1 and integer(args[0], 1, 64)
    return (name.decode('ascii', errors='replace') in TUNING and len(args) == 1
            and NUMBER.fullmatch(args[0]) is not None)


def protected_directives(content):
    # Chrony reads physical lines. Disallow control bytes that might change
    # tokenization between this comparison and the actual daemon parser.
    content = content.replace(b'\r\n', b'\n')
    if re.search(rb'[\x00-\x08\x0b-\x1f\x7f]', content):
        raise OSError(errno.EINVAL, 'Invalid Chrony configuration characters')
    if any(len(line) > 512 for line in content.split(b'\n')):
        raise OSError(errno.EINVAL, 'Chrony configuration line is too long')
    result = []
    for line in content.split(b'\n'):
        line = line.strip(b' \t')
        if not line or line.startswith(b'#'):
            continue
        if not editable(line.split()):
            result.append(line)
    return result


class Config:
    def __init__(self, path, unit_binding):
        self.path = path
        self.unit_binding = unit_binding

    def observation(self, unit):
        # The production caller separately checks every physical parent,
        # the package's canonical Chrony unit and its effective inputs.
        unit_state = self.unit_binding(unit)
        before = self.path.lstat()
        if before.st_uid != 0 or before.st_gid != 0 or before.st_mode & 0o7022:
            raise OSError(errno.EPERM, 'Unsafe Chrony configuration owner or mode')
        if os.listxattr(self.path, follow_symlinks=False):
            raise OSError(errno.EOPNOTSUPP, 'Chrony configuration has additional file metadata')
        raw = read(self.path, 0, stat.S_IMODE(before.st_mode), MAX_CHRONY_CONFIGURATION_BYTES)
        if identity(before) != identity(self.path.lstat()):
            raise OSError(errno.ESTALE, 'Chrony configuration changed while reading')
        binding = digest(dict(unit=unit_state, file=identity(before), sha256=hashlib.sha256(raw).hexdigest()))
        return binding, raw, stat.S_IMODE(before.st_mode), unit_state

    def prepare(self, unit, candidate):
        binding, original, _, _ = self.observation(unit)
        if original != candidate and protected_directives(original) != protected_directives(candidate):
            raise OSError(errno.EPERM, 'Chrony system directives are unchanged by managed configuration')
        return binding

    def commit(self, unit, candidate, expected_binding, request_id, parse):
        before, original, mode, unit_state = self.observation(unit)
        if before != expected_binding:
            raise OSError(errno.ESTALE, 'Prepared Chrony configuration changed')
        if original == candidate:
            return before
        if protected_directives(original) != protected_directives(candidate):
            raise OSError(errno.EPERM, 'Chrony system directives are unchanged by managed configuration')

        def staged(contents, mode):
            fd, name = tempfile.mkstemp(prefix='.kura-chrony-', dir=self.path.parent)
            path = Path(name)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    os.fchmod(stream.fileno(), mode)
                    stream.write(contents)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                path.unlink()
                raise
            return path

        replacement = staged(candidate, mode)
        saved = None
        publishing = False
        try:
            parse(replacement)
            saved = staged(original, 0o600)
            if self.observation(unit)[0] != before:
                raise OSError(errno.ESTALE, 'Prepared Chrony configuration changed')
            # Before publishing, retain the exact preimage under the original
            # request ID. Never replace a previously retained preimage.
            backup = self.path.with_name(f'.kura-chrony-original-{request_id}')
            try:
                publishing = True
                os.link(saved, backup, follow_symlinks=False)
                saved.unlink()
                sync(self.path.parent)
                os.replace(replacement, self.path)
                sync(self.path.parent)
                _, applied, applied_mode, applied_unit = self.observation(unit)
                if (applied, applied_mode, applied_unit) != (candidate, mode, unit_state):
                    raise Refused('UNCERTAIN_CHRONY_CONFIG')
            except OSError as error:
                raise Refused('UNCERTAIN_CHRONY_CONFIG') from error
        finally:
            try:
                replacement.unlink(missing_ok=True)
                if saved is not None:
                    saved.unlink(missing_ok=True)
            except OSError as error:
                if publishing:
                    raise Refused('UNCERTAIN_CHRONY_CONFIG') from error
                raise
        return before


def parse_configuration(path):
    try:
        result = subprocess.run([str(CHRONYD), '-p', '-f', str(path)], timeout=3,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
    except subprocess.SubprocessError as error:
        raise OSError(errno.EINVAL, 'Unable to verify Chrony configuration') from error
    if result.returncode != 0:
        raise OSError(errno.EINVAL, 'Invalid Chrony configuration')
