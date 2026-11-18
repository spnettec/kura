#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Dedicated non-Root CAP_SYS_TIME actor for typed clock operations."""
import contextlib
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_journal import (Journal, Refused, command, create, decode, digest, directory, encode,
                                identifier, identity, read, require, sync, MAX_BYTES, OPERATIONS, RTC_ALIASES, RTC_NODE)

HOME = Path('/opt/eclipse/kura')
ACTOR_HOME = Path('/usr/libexec/kura-clock-broker')
STATE = Path('/var/lib/kura-clock-broker')
SOCKET = Path('/run/kura-clock-broker/control.sock')
RTC_PROJECTION = Path('/dev/kura-clock-rtc')
RTC_SOURCE = Path('/dev/.kura-clock-rtc')
RTC_CLASS = Path('/sys/class/rtc')
RTC_MANIFEST = 'devices.json'
COHORT = Path('libexec/clock-broker/cohort.json')
LEGACY_UNITS = ('kura-clock-broker.socket', 'kura-clock-broker.service')
RTC_UNIT = 'kura-clock-rtc-devices.service'
UNITS = (*LEGACY_UNITS, RTC_UNIT)
CHRONY_UNITS = ('chrony.service', 'chronyd.service')
CHRONY_ACTIVE_STATES = {'active', 'reloading', 'inactive', 'failed', 'activating', 'deactivating',
                        'maintenance', 'refreshing'}
HELPERS = ('bin/kura_clock_broker.py', 'bin/kura_clock_journal.py', 'bin/kura_clock_client.py', 'bin/kura_clock_setup.py')
SYS_TIME = 1 << 25
RTC_PROJECTOR_CAPS = (1 << 0) | (1 << 27)  # CHOWN and MKNOD
VENDOR_UNIT_ROOTS = (Path('/lib/systemd/system'), Path('/usr/lib/systemd/system'))
WRITE_ACTIONS = {phase + '-' + suffix: (phase, name)
                 for name, (suffix, _, _) in OPERATIONS.items() for phase in ('prepare', 'commit')}
# _IOW('p', 0x0a, struct rtc_time) on the release architectures.
RTC_SET_TIME = 0x4024700a


def canonical_alias(path):
    """Only the installer's Root-owned, one-hop versioned Core alias."""
    require(path == HOME, 'UNPAIRED_CODE')
    metadata = path.lstat()
    require(stat.S_ISLNK(metadata.st_mode) and metadata.st_uid == 0, 'UNPAIRED_CODE')
    raw = os.readlink(path)
    target = Path(raw) if raw.startswith('/') else path.parent / raw
    require(target.parent == HOME.parent and re.fullmatch(r'kura_[A-Za-z0-9.+~_-]+_linux', target.name) is not None
            and raw in (target.name, str(target)), 'UNPAIRED_CODE')
    value = target.lstat()
    require(stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and not value.st_mode & 0o022, 'UNPAIRED_CODE')
    return target


def protected(path):
    """Root code only. Fixed distro /lib and versioned Core aliases only."""
    path = Path(path)
    require(path.is_absolute(), 'UNPAIRED_CODE')
    for part in [*reversed(path.parents), path]:
        metadata = part.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            if part == HOME:
                canonical_alias(part)
            else:
                require(part == Path('/lib') and metadata.st_uid == 0
                        and part.resolve() == Path('/usr/lib'), 'UNPAIRED_CODE')
        elif part != path:
            require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0
                    and not metadata.st_mode & 0o022, 'UNPAIRED_CODE')
        else:
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0 and metadata.st_nlink == 1
                    and not metadata.st_mode & 0o022, 'UNPAIRED_CODE')
    return path


def public_file(path, maximum=MAX_BYTES):
    path = protected(path)
    metadata = path.lstat()
    return read(path, 0, stat.S_IMODE(metadata.st_mode), maximum)


def jar_contract(path):
    require(path.is_file() and not path.is_symlink(), 'UNPAIRED_CODE')
    with zipfile.ZipFile(path) as archive:
        raw = archive.read('META-INF/MANIFEST.MF')
        require(len(raw) <= MAX_BYTES, 'UNPAIRED_CODE')
        joined = raw.replace(b'\r\n', b'\n').replace(b'\n ', b'').decode('ascii')
        headers = dict(line.split(': ', 1) for line in joined.split('\n\n', 1)[0].splitlines() if ': ' in line)
        require(headers.get('Bundle-SymbolicName', '').split(';', 1)[0] == 'org.eclipse.kura.linux.clock', 'UNPAIRED_CODE')
        require(re.search(r'(?:^|,)\s*kura\.clock\.privilege\s*;\s*version:Version="?1\.0\.0"?(?:;|,|$)',
                          headers.get('Provide-Capability', '')) is not None, 'UNPAIRED_CODE')
        prefix = archive.read('org/eclipse/kura/linux/clock/ClockPrivilegeClient.class')[:8]
        require(prefix == b'\xca\xfe\xba\xbe\0\0\0A', 'UNPAIRED_CODE')


def package_cohort(home):
    """Fresh package assembly only; no installed paths or runtime state."""
    home = Path(home)
    require(home.is_dir() and not home.is_symlink(), 'UNPAIRED_CODE')
    matches = list((home / 'plugins').rglob('org.eclipse.kura.linux.clock*.jar'))
    require(len(matches) == 1, 'UNPAIRED_CODE')
    jar_contract(matches[0])
    paths = [*HELPERS, *['libexec/clock-broker/' + name for name in UNITS], matches[0].relative_to(home).as_posix()]
    files = {}
    for name in paths:
        path = home / name
        require(path.is_file() and not path.is_symlink(), 'UNPAIRED_CODE')
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    value = dict(schema=1, protocol=1, files=files, clockBundle=paths[-1],
                 actor='kura-clock', caller='kurad', actions=list(OPERATIONS))
    target = home / COHORT
    with target.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o644)
        stream.write(encode(value) + b'\n')
    return value


def systemd_properties(properties, unit=None):
    """Read PID1's configuration, with no caller environment or fallback."""
    require(unit is None or unit in (*UNITS, *CHRONY_UNITS), 'UNPAIRED_CODE')
    arguments = ['/usr/bin/systemctl', '--system', '--no-ask-password', 'show', '--all',
                 '--property=' + ','.join(properties)]
    if unit is not None:
        arguments.append(unit)
    try:
        result = subprocess.run(arguments, env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'},
                                capture_output=True, text=True, timeout=5)
        require(result.returncode == 0 and len(result.stdout.encode()) <= MAX_BYTES, 'UNPAIRED_CODE')
        values = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition('=')
            require(separator == '=' and key in properties and key not in values, 'UNPAIRED_CODE')
            values[key] = value
        require(set(values) == set(properties), 'UNPAIRED_CODE')
        return values
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        raise Refused('UNPAIRED_CODE') from error


def unit_load_paths():
    raw = systemd_properties(('UnitPath',))['UnitPath']
    tokens = raw.split()
    require(tokens and all(re.fullmatch(r'/[A-Za-z0-9_./+-]+', token) is not None
                           and '..' not in Path(token).parts and Path(token).as_posix() == token
                           for token in tokens), 'UNPAIRED_CODE')
    roots = tuple(dict.fromkeys(Path(token) for token in tokens))
    require(any(root in VENDOR_UNIT_ROOTS for root in roots), 'UNPAIRED_CODE')
    return roots


def unit_directory_present(path):
    """A missing Root-controlled suffix is fine; denied lookup is not absence."""
    for part in [*reversed(path.parents), path]:
        try:
            metadata = part.lstat()
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(metadata.st_mode):
            require(part == Path('/lib') and metadata.st_uid == 0
                    and part.resolve() == Path('/usr/lib'), 'UNPAIRED_CODE')
        else:
            require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0
                    and not metadata.st_mode & 0o022, 'UNPAIRED_CODE')
    return True


def unit_input_names(name):
    stem, kind = name.rsplit('.', 1)
    names = [name + suffix for suffix in ('.d', '.wants', '.requires', '.upholds')]
    names.append(kind + '.d')
    while '-' in stem:
        stem = stem.rsplit('-', 1)[0]
        names.append(stem + '-.' + kind + '.d')
    return names


def unit_sources():
    """Reject overrides in the manager's complete current system load path."""
    try:
        for root in unit_load_paths():
            if not unit_directory_present(root):
                continue
            for name in UNITS:
                inputs = unit_input_names(name)
                if root not in VENDOR_UNIT_ROOTS:
                    inputs.append(name)
                for entry in inputs:
                    try:
                        (root / entry).lstat()
                    except FileNotFoundError:
                        continue
                    raise Refused('UNPAIRED_CODE')
    except OSError as error:
        raise Refused('UNPAIRED_CODE') from error


def effective_units():
    properties = ('Id', 'Names', 'LoadState', 'FragmentPath', 'SourcePath', 'DropInPaths',
                  'NeedDaemonReload', 'Transient')
    for name in UNITS:
        value = systemd_properties(properties, name)
        require(value['Id'] == name and value['Names'].split() == [name] and value['LoadState'] == 'loaded'
                and value['FragmentPath'] in {str(root / name) for root in VENDOR_UNIT_ROOTS}
                and value['SourcePath'] == value['DropInPaths'] == ''
                and value['NeedDaemonReload'] == value['Transient'] == 'no', 'UNPAIRED_CODE')


def chrony_status():
    """Read the fixed distro names. A status observation grants no service control."""
    properties = ('Id', 'LoadState', 'ActiveState')
    for name in CHRONY_UNITS:
        value = systemd_properties(properties, name)
        if value['LoadState'] == 'not-found':
            require(value['Id'] == name and value['ActiveState'] == 'inactive', 'INVALID_CHRONY_STATUS')
            continue
        require(value['LoadState'] == 'loaded' and value['Id'] in CHRONY_UNITS
                and value['ActiveState'] in CHRONY_ACTIVE_STATES, 'INVALID_CHRONY_STATUS')
        return dict(schema=1, unit=value['Id'], active=value['ActiveState'] in ('active', 'reloading', 'refreshing'))
    return dict(schema=1, unit='', active=False)


class Policy:
    def __init__(self, actor=False):
        self.home = ACTOR_HOME if actor else HOME
        self.actor_copy = actor

    def check(self, installed=True, effective=True, allow_legacy=False):
        raw = public_file(self.home / COHORT)
        value = decode(raw)
        base = {'schema', 'protocol', 'files', 'clockBundle', 'actor', 'caller'}
        legacy = (allow_legacy and self.actor_copy and not installed and set(value) == base | {'action'}
                  and value['action'] == 'adjust-realtime')
        require((legacy or (set(value) == base | {'actions'} and value['actions'] == list(OPERATIONS)))
                and type(value['schema']) is int and value['schema'] == 1
                and type(value['protocol']) is int and value['protocol'] == 1
                and value['actor'] == 'kura-clock' and value['caller'] == 'kurad'
                and type(value['files']) is dict, 'UNPAIRED_CODE')
        bundle = value['clockBundle']
        require(isinstance(bundle, str) and re.fullmatch(r'plugins/(?:[A-Za-z0-9_.-]+/)?org\.eclipse\.kura\.linux\.clock[A-Za-z0-9_.-]*\.jar', bundle) is not None,
                'UNPAIRED_CODE')
        units = LEGACY_UNITS if legacy else UNITS
        expected = {*HELPERS, *['libexec/clock-broker/' + name for name in units], bundle}
        require(set(value['files']) == expected, 'UNPAIRED_CODE')
        if self.actor_copy:
            # This copy is a closed code cohort, unlike the complete Core tree.
            # Extra importable files or directories do not become actor code.
            expected_files = expected | {COHORT.as_posix()}
            expected_dirs = set()
            for name in expected_files:
                expected_dirs.update(p.as_posix() for p in Path(name).parents if p != Path('.'))
            group = pwd.getpwnam('kura-clock').pw_gid
            for path in [self.home, *self.home.rglob('*')]:
                metadata = path.lstat(); relative = path.relative_to(self.home).as_posix()
                require(metadata.st_uid == 0 and metadata.st_gid == group, 'UNPAIRED_CODE')
                if stat.S_ISDIR(metadata.st_mode):
                    require((path == self.home or relative in expected_dirs) and stat.S_IMODE(metadata.st_mode) == 0o750,
                            'UNPAIRED_CODE')
                else:
                    require(relative in expected_files and stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
                            and stat.S_IMODE(metadata.st_mode) == 0o640, 'UNPAIRED_CODE')
        for name, expected_hash in value['files'].items():
            require(isinstance(expected_hash, str) and re.fullmatch('[0-9a-f]{64}', expected_hash) is not None, 'UNPAIRED_CODE')
            actual = public_file(self.home / name, 256 * 1024 * 1024 if name == bundle else MAX_BYTES)
            require(hashlib.sha256(actual).hexdigest() == expected_hash, 'UNPAIRED_CODE')
        jar_contract(self.home / bundle)
        if installed:
            unit_sources()
            for name in UNITS:
                require(public_file(Path('/lib/systemd/system') / name)
                        == public_file(self.home / 'libexec/clock-broker' / name), 'UNPAIRED_CODE')
            if effective:
                effective_units()
        self.cohort = digest(value)
        return value

    def actor(self):
        account = pwd.getpwnam('kura-clock')
        require(account.pw_uid > 0 and account.pw_gid > 0 and account.pw_shell == '/usr/sbin/nologin'
                and account.pw_dir == '/nonexistent', 'UNSAFE_ACTOR')
        require(os.getuid() == os.geteuid() == account.pw_uid and os.getgid() == os.getegid() == account.pw_gid
                and set(os.getgroups()) <= {account.pw_gid}, 'UNSAFE_ACTOR')
        values = dict(line.split(':', 1) for line in Path('/proc/thread-self/status').read_text().splitlines() if ':' in line)
        require(values['Uid'].split() == [str(account.pw_uid)] * 4
                and values['Gid'].split() == [str(account.pw_gid)] * 4 and values['NoNewPrivs'].strip() == '1', 'UNSAFE_ACTOR')
        require(all(int(values[name].strip(), 16) == SYS_TIME for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')),
                'UNSAFE_ACTOR')
        directory(STATE, account.pw_uid)
        return account.pw_uid

    def peer(self, peer):
        pid, uid, gid = peer
        account = pwd.getpwnam('kurad')
        require(account.pw_uid > 0 and uid == account.pw_uid, 'UNAUTHORIZED')
        values = dict(line.split(':', 1) for line in Path('/proc/' + str(pid) + '/status').read_text().splitlines() if ':' in line)
        require(values['Uid'].split() == [str(uid)] * 4, 'UNAUTHORIZED')
        # The fixed isolated helper must be a direct child of the running Main.
        # MainPID comes from systemd, never a daemon-writable PID file.
        fields = dict(line.split('=', 1) for line in subprocess.check_output(
            ['/usr/bin/systemctl', 'show', 'kura.service', '--property=MainPID,ActiveState'],
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}, text=True, timeout=3).splitlines())
        require(fields['ActiveState'] == 'active' and fields['MainPID'].isdigit() and int(fields['MainPID']) > 0
                and values['PPid'].strip() == fields['MainPID'], 'UNAUTHORIZED')
        parent = Path('/proc/' + fields['MainPID'])
        parent_status = dict(line.split(':', 1) for line in (parent / 'status').read_text().splitlines() if ':' in line)
        require(parent_status['Uid'].split() == [str(uid)] * 4, 'UNAUTHORIZED')
        argv = Path('/proc/' + str(pid) + '/cmdline').read_bytes().split(b'\0')[:-1]
        require(argv[:5] == [b'/usr/bin/python3', b'-I', b'-B', str(HOME / 'bin/kura_clock_client.py').encode(), b'client']
                and len(argv) == 6, 'UNAUTHORIZED')
        return pid


class Manager:
    def __init__(self, policy, journal, adjust_realtime=None, sync_rtc=None, bind_rtc=None):
        self.policy = policy
        self.journal = journal
        self.adjust_realtime = adjust_realtime or (lambda nanos: time.clock_settime_ns(time.CLOCK_REALTIME, nanos))
        self.sync_rtc = sync_rtc or rtc_set_time
        self.bind_rtc = bind_rtc or rtc_binding

    def handle(self, value, peer):
        self.policy.check(); self.policy.peer(peer)
        require(type(value) is dict and type(value.get('schema')) is int and value.get('schema') == 1)
        if value.get('action') == 'chrony-status':
            require(set(value) == {'schema', 'action'})
            return chrony_status()
        with self.journal.lock():
            namespace = self.journal.namespace()
            action = value.get('action')
            if action == 'context':
                require(set(value) == {'schema', 'action'})
                return dict(schema=1, state='READY', namespace=namespace, cohortSha256=self.policy.cohort,
                            acceptingWrites=self.journal.accepting())
            # Admit this Root's namespace before inspecting any caller-provided old ID.
            require(value.get('namespace') == namespace, 'FOREIGN_NAMESPACE')
            if action == 'status':
                require(set(value) == {'schema', 'action', 'namespace', 'requestId', 'requestSha256'})
                return self.journal.status(namespace, value['requestId'], value['requestSha256'])
            require(isinstance(action, str) and action in WRITE_ACTIONS)
            phase, operation = WRITE_ACTIONS[action]
            value = command(dict(value, action=operation))
            require(value['cohortSha256'] == self.policy.cohort, 'UNPAIRED_CODE')
            # Check again under admission immediately before any durable intent.
            self.policy.check()
            require(value['cohortSha256'] == self.policy.cohort, 'UNPAIRED_CODE')
            self.policy.peer(peer)
            if phase == 'prepare':
                return self.journal.prepare(value, self.bind_rtc)
            actuate = self.adjust_realtime if operation == 'adjust-realtime' else self.sync_rtc
            return self.journal.commit(value, actuate)


def rtc_candidate(device):
    if sys.platform != 'linux' or os.uname().machine not in ('aarch64', 'x86_64'):
        raise OSError(errno.ENOSYS, 'Unsupported RTC ioctl ABI')
    path, hardware = projected_rtc(device)
    before = path.lstat()
    check_rtc_node(before, hardware)
    return path, hardware, before


def rtc_identity(path, hardware, metadata):
    return digest(dict(node=path.name, kernel=hardware, projection=identity(metadata)))


def rtc_binding(device):
    return rtc_identity(*rtc_candidate(device))


def rtc_set_time(device, expected_binding):
    path, hardware, before = rtc_candidate(device)
    if rtc_identity(path, hardware, before) != expected_binding:
        raise OSError(errno.ESTALE, 'RTC device does not match the prepared binding')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        if (identity(opened) != identity(before) or opened.st_rdev != before.st_rdev
                or identity(path.lstat()) != identity(before) or rtc_hardware(path.name) != hardware):
            raise OSError(errno.ENODEV, 'RTC device changed during admission')
        utc = time.gmtime()
        fields = (ctypes.c_int * 9)(utc.tm_sec, utc.tm_min, utc.tm_hour, utc.tm_mday, utc.tm_mon - 1,
                                     utc.tm_year - 1900, (utc.tm_wday + 1) % 7, utc.tm_yday - 1, 0)
        ioctl = ctypes.CDLL(None, use_errno=True).ioctl
        ioctl.restype = ctypes.c_int
        # An RTC driver may fail after starting a hardware write. No terminal
        # result and no second ioctl, including after EINTR.
        if ioctl(ctypes.c_int(fd), ctypes.c_ulong(RTC_SET_TIME), ctypes.byref(fields)) != 0:
            raise Refused('UNCERTAIN_RTC_RESULT')
    finally:
        # Linux releases the descriptor even on EINTR. A close failure must
        # not turn an admitted ioctl with an ambiguous result into FAILED.
        with contextlib.suppress(OSError):
            os.close(fd)


def rtc_hardware(name):
    kernel = (RTC_CLASS / name).resolve(strict=True)
    if kernel.name != name or not kernel.is_relative_to('/sys/devices'):
        raise OSError(errno.ENODEV, 'RTC entry is outside the kernel device tree')
    with (kernel / 'dev').open(encoding='ascii') as source:
        device_number = source.read(64).strip()
    if re.fullmatch(r'[0-9]{1,4}:[0-9]{1,7}', device_number) is None:
        raise OSError(errno.ENODEV, 'Unrecognized kernel RTC device number')
    major, minor = map(int, device_number.split(':'))
    metadata = kernel.stat()
    return dict(major=major, minor=minor, inode=metadata.st_ino, path=str(kernel))


def check_rtc_node(value, hardware):
    if (not stat.S_ISCHR(value.st_mode) or value.st_uid != 0 or value.st_nlink != 1
            or value.st_gid != pwd.getpwnam('kura-clock').pw_gid or stat.S_IMODE(value.st_mode) != 0o640
            or (os.major(value.st_rdev), os.minor(value.st_rdev)) != (hardware['major'], hardware['minor'])):
        raise OSError(errno.ENODEV, 'RTC node does not match the projected kernel device')


def rtc_catalog(path):
    metadata = path.lstat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0 and stat.S_IMODE(metadata.st_mode) == 0o750
            and metadata.st_gid == pwd.getpwnam('kura-clock').pw_gid, 'UNPAIRED_RTC_PROJECTION')
    catalog = decode(read(path / RTC_MANIFEST, 0, 0o644))
    require(set(catalog) == {'schema', 'nodes', 'aliases'}
            and type(catalog['schema']) is int and catalog['schema'] == 1
            and type(catalog['nodes']) is dict and type(catalog['aliases']) is dict, 'UNPAIRED_RTC_PROJECTION')
    nodes, aliases = catalog['nodes'], catalog['aliases']
    require(set(aliases) <= set(RTC_ALIASES) and all(isinstance(v, str) and v in nodes for v in aliases.values())
            and all(RTC_NODE.fullmatch('/dev/' + name) is not None for name in nodes)
            and {entry.name for entry in path.iterdir()} == {RTC_MANIFEST, *nodes}, 'UNPAIRED_RTC_PROJECTION')
    for name, hardware in nodes.items():
        require(type(hardware) is dict and set(hardware) == {'major', 'minor', 'inode', 'path'}
                and all(type(hardware[field]) is int and hardware[field] >= 0 for field in ('major', 'minor', 'inode'))
                and isinstance(hardware['path'], str) and hardware['path'].startswith('/sys/devices/'),
                'UNPAIRED_RTC_PROJECTION')
        check_rtc_node((path / name).lstat(), hardware)
    return catalog


def projected_rtc(device):
    catalog = rtc_catalog(RTC_PROJECTION)
    if RTC_NODE.fullmatch(device) is not None:
        name = Path(device).name
    else:
        name = catalog['aliases'].get(device)
    hardware = catalog['nodes'].get(name)
    if hardware is None or rtc_hardware(name) != hardware:
        raise OSError(errno.ENODEV, 'Requested RTC has no current paired projection')
    return RTC_PROJECTION / name, hardware


def publish_rtc(staged, target, replace):
    # Both names are in the Root devtmpfs. NOREPLACE for fresh publication,
    # EXCHANGE retains a fully checked old projection until the new one is ready.
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(staged), -100, os.fsencode(target), 2 if replace else 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def project_rtc():
    require(os.getuid() == os.geteuid() == 0 and os.getgid() == os.getegid() == 0, 'UNSAFE_RTC_PROJECTOR')
    values = dict(line.split(':', 1) for line in Path('/proc/thread-self/status').read_text().splitlines() if ':' in line)
    require(values['NoNewPrivs'].strip() == '1' and all(
        int(values[name].strip(), 16) == RTC_PROJECTOR_CAPS for name in ('CapPrm', 'CapEff', 'CapBnd')),
        'UNSAFE_RTC_PROJECTOR')
    policy = Policy(actor=True)
    policy.check()
    require(unit_directory_present(RTC_SOURCE.parent), 'UNPAIRED_RTC_PROJECTION')
    group = pwd.getpwnam('kura-clock').pw_gid
    with_projection = os.path.lexists(RTC_SOURCE)
    previous = rtc_catalog(RTC_SOURCE) if with_projection else None
    try:
        entries = sorted(RTC_CLASS.iterdir())
    except FileNotFoundError:
        entries = []
    nodes = {entry.name: rtc_hardware(entry.name) for entry in entries
             if RTC_NODE.fullmatch('/dev/' + entry.name) is not None}
    aliases = {}
    for alias in RTC_ALIASES:
        try:
            origin = Path(alias).resolve(strict=True)
        except FileNotFoundError:
            continue
        if RTC_NODE.fullmatch(str(origin)) is not None and origin.name in nodes:
            aliases[alias] = origin.name
    catalog = dict(schema=1, nodes=nodes, aliases=aliases)
    if catalog == previous:
        return
    require(len(encode(catalog)) <= MAX_BYTES, 'UNPAIRED_RTC_PROJECTION')
    staged = Path(tempfile.mkdtemp(prefix='.kura-clock-rtc-staged-', dir=RTC_SOURCE.parent))
    try:
        for name, hardware in nodes.items():
            path = staged / name
            os.mknod(path, stat.S_IFCHR | 0o600, os.makedev(hardware['major'], hardware['minor']))
            os.chown(path, 0, group, follow_symlinks=False)
            path.chmod(0o640)
        create(staged / RTC_MANIFEST, catalog, 0o644)
        os.chown(staged, 0, group, follow_symlinks=False)
        staged.chmod(0o750)
        require(rtc_catalog(staged) == catalog, 'UNPAIRED_RTC_PROJECTION')
        policy.check()
        if with_projection:
            require(rtc_catalog(RTC_SOURCE) == previous, 'UNPAIRED_RTC_PROJECTION')
        publish_rtc(staged, RTC_SOURCE, with_projection)
    finally:
        if staged.exists():
            for entry in staged.iterdir():
                entry.unlink()
            staged.rmdir()


def remove_rtc_projection():
    if os.path.lexists(RTC_SOURCE):
        require(unit_directory_present(RTC_SOURCE.parent), 'UNPAIRED_RTC_PROJECTION')
        catalog = rtc_catalog(RTC_SOURCE)
        retired = RTC_SOURCE.with_name('.kura-clock-rtc-retired-' + uuid.uuid4().hex)
        publish_rtc(RTC_SOURCE, retired, False)
        for name in (*catalog['nodes'], RTC_MANIFEST):
            (retired / name).unlink()
        retired.rmdir()


def exact(stream, count):
    value = bytearray()
    while len(value) < count:
        part = stream.recv(count - len(value))
        require(bool(part), 'TRUNCATED_FRAME')
        value.extend(part)
    return bytes(value)


def receive(stream):
    size = struct.unpack('>I', exact(stream, 4))[0]
    require(0 < size <= MAX_BYTES, 'INVALID_FRAME')
    value = decode(exact(stream, size))
    require(stream.recv(1) == b'', 'EXTRA_FRAME')
    return value


def send(stream, value):
    raw = encode(value); require(len(raw) <= MAX_BYTES)
    stream.sendall(struct.pack('>I', len(raw)) + raw)


def serve():
    policy = Policy(actor=True); policy.check(); owner = policy.actor()
    require(os.environ.get('LISTEN_PID') == str(os.getpid()) and os.environ.get('LISTEN_FDS') == '1'
            and os.environ.get('LISTEN_FDNAMES') == 'control', 'INVALID_LISTENER')
    listener = socket.socket(fileno=3)
    require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM
            and listener.getsockname() == str(SOCKET) and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1,
            'INVALID_LISTENER')
    manager = Manager(policy, Journal(STATE, owner))
    with listener:
        while True:
            stream, _ = listener.accept()
            with stream:
                stream.settimeout(5)
                try:
                    peer = struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    result = manager.handle(receive(stream), peer)
                    send(stream, dict(ok=True, result=result))
                except Refused as error:
                    try:
                        send(stream, dict(ok=False, reason=error.reason))
                    except OSError:
                        pass
                except (OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile):
                    # A missing acknowledgement cannot turn a durable intent into FAILED.
                    try:
                        send(stream, dict(ok=False, reason='UNRESOLVED_OR_UNAVAILABLE'))
                    except OSError:
                        pass


if __name__ == '__main__':
    try:
        entrypoint = str(ACTOR_HOME / 'bin/kura_clock_broker.py')
        require(len(sys.argv) == 2 and sys.argv[0] == entrypoint, 'INVALID_ENTRYPOINT')
        if sys.argv[1] == 'serve':
            serve()
        else:
            require(sys.argv[1] == 'project-rtc', 'INVALID_ENTRYPOINT')
            project_rtc()
    except (Refused, OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        reason = error.reason if isinstance(error, Refused) else 'UNRESOLVED_OR_UNAVAILABLE'
        print(reason, file=sys.stderr)
        raise SystemExit(1)
