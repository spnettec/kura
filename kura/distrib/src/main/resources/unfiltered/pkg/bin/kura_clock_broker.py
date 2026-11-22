#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Dedicated non-Root CAP_SYS_TIME actor for typed clock operations."""
from array import array
import contextlib
import ctypes
import errno
import grp
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
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_journal import (Journal, Refused, command, decode, digest, directory, encode,
                                chrony_configuration, identifier, identity, read, require,
                                CHRONY_ACTIONS, CHRONY_UNITS,
                                MAX_BYTES, OPERATIONS, RTC_ALIASES, RTC_NODE)

HOME = Path('/opt/eclipse/kura')
ACTOR_HOME = Path('/usr/libexec/kura-clock-broker')
STATE = Path('/var/lib/kura-clock-broker')
SOCKET = Path('/run/kura-clock-broker/control.sock')
RTC_SOURCE = Path('/dev/.kura-clock-rtc')
RTC_CLASS = Path('/sys/class/rtc')
RTC_MANIFEST = 'devices.json'
COHORT = Path('libexec/clock-broker/cohort.json')
LEGACY_UNITS = ('kura-clock-broker.socket', 'kura-clock-broker.service')
RTC_UNIT = 'kura-clock-rtc-devices.service'
PREVIOUS_UNITS = (*LEGACY_UNITS, RTC_UNIT)
STEP_SOCKET_UNIT = 'kura-clock-chrony-step.socket'
STEP_SERVICE_UNIT = 'kura-clock-chrony-step.service'
STEP_UNITS = (*PREVIOUS_UNITS, STEP_SOCKET_UNIT, STEP_SERVICE_UNIT)
CONFIG_SOCKET_UNIT = 'kura-clock-chrony-config.socket'
CONFIG_SERVICE_UNIT = 'kura-clock-chrony-config.service'
CONFIG_UNITS = (*STEP_UNITS, CONFIG_SOCKET_UNIT, CONFIG_SERVICE_UNIT)
RTC_SOCKET_UNIT = 'kura-clock-rtc-devices.socket'
RTC_SOCKET = Path('/run/kura-clock-broker/rtc.sock')
RTC_TIMEOUT = 3
UNITS = (*CONFIG_UNITS, RTC_SOCKET_UNIT)
CONFIG_SOCKET = Path('/run/kura-clock-broker/chrony-config.sock')
CONFIG_TIMEOUT = 15
STEP_SOCKET = Path('/run/kura-clock-broker/chrony-step.sock')
STEP_RUNTIME = Path('/run/kura-chrony-step')
STEP_USER = '_chrony'
STEP_TIMEOUT = 12
CHRONY_ACTIVE_STATES = {'active', 'reloading', 'inactive', 'failed', 'activating', 'deactivating',
                        'maintenance', 'refreshing'}
CHRONY_EXECUTABLES = ('/usr/sbin/chronyd', '/usr/bin/chronyd')
CHRONY_STARTERS = (*CHRONY_EXECUTABLES, '/usr/lib/systemd/scripts/chronyd-starter.sh')
CHRONY_STEP_MESSAGE = r'^System clock was stepped by [-+]?[0-9]+[.,][0-9]{6} seconds$'
CHRONY_JOURNAL_GROUP = 'systemd-journal'
CHRONY_COMMAND = Path('/run/chrony/chronyd.sock')
CHRONY_PROTOCOL_VERSION = 6
CHRONY_PROBE = 0
CHRONY_MAKESTEP = 43
CHRONY_NULL_REPLY = 1
CHRONY_PACKET_BYTES = 28
CHRONY_COMMAND_TIMEOUT = 2
CHRONY_POLICY = Path('/usr/share/polkit-1/rules.d/10-kura-clock-chrony.rules')
PREVIOUS_CHRONY_RULE = b'''// Managed by the Kura clock broker installer.
polkit.addRule(function(action, subject) {
    if (subject.user !== "kura-clock" || action.id.indexOf("org.freedesktop.systemd1.") !== 0) {
        return;
    }
    var unit = action.lookup("unit");
    var verb = action.lookup("verb");
    if (action.id === "org.freedesktop.systemd1.manage-units" &&
        subject.system_unit === "kura-clock-broker.service" && subject.no_new_privileges === true &&
        (unit === "chrony.service" || unit === "chronyd.service") &&
        (verb === "start" || verb === "stop")) {
        return polkit.Result.YES;
    }
    return polkit.Result.NO;
});
'''
CHRONY_RULE = PREVIOUS_CHRONY_RULE.replace(b'verb === "stop")', b'verb === "stop" || verb === "restart")')
CHRONY_JOB_TIMEOUT = 15
STOP_CONTEXT = 'chrony-stop-context'
TEARDOWN_REQUESTS = (STOP_CONTEXT, 'prepare-chrony-stop', 'commit-chrony-stop')
LEGACY_HELPERS = ('bin/kura_clock_broker.py', 'bin/kura_clock_journal.py', 'bin/kura_clock_client.py', 'bin/kura_clock_setup.py')
HELPERS = (*LEGACY_HELPERS, 'bin/kura_chrony_config.py')
SYS_TIME = 1 << 25
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


def jar_contract(path, *capabilities):
    require(path.is_file() and not path.is_symlink(), 'UNPAIRED_CODE')
    with zipfile.ZipFile(path) as archive:
        raw = archive.read('META-INF/MANIFEST.MF')
        require(len(raw) <= MAX_BYTES, 'UNPAIRED_CODE')
        joined = raw.replace(b'\r\n', b'\n').replace(b'\n ', b'').decode('ascii')
        headers = dict(line.split(': ', 1) for line in joined.split('\n\n', 1)[0].splitlines() if ': ' in line)
        require(headers.get('Bundle-SymbolicName', '').split(';', 1)[0] == 'org.eclipse.kura.linux.clock', 'UNPAIRED_CODE')
        capabilities = capabilities or ('1.2.1',)
        version = '(?:' + '|'.join(map(re.escape, capabilities)) + ')'
        require(re.search(r'(?:^|,)\s*kura\.clock\.privilege\s*;\s*version:Version="?' + version + r'"?(?:;|,|$)',
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


def effective_units(units=UNITS):
    properties = ('Id', 'Names', 'LoadState', 'FragmentPath', 'SourcePath', 'DropInPaths',
                  'NeedDaemonReload', 'Transient')
    for name in units:
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


def chrony_last_step():
    """Return only the timestamps of the last step from the local Chrony service."""
    try:
        result = subprocess.run(
            ['/usr/bin/journalctl', '--system', '--no-pager', '--boot', '--since=today',
             '--output=json', '--output-fields=_EXE,_SYSTEMD_UNIT', '--case-sensitive=true',
             '--grep=' + CHRONY_STEP_MESSAGE, '--lines=1',
             *['_SYSTEMD_UNIT=' + unit for unit in CHRONY_UNITS],
             *['_EXE=' + binary for binary in CHRONY_EXECUTABLES]],
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}, capture_output=True, timeout=3)
        reason = 'UNAVAILABLE_CHRONY_JOURNAL'
        require(not result.stderr and result.returncode in (0, 1), reason)
        if result.stdout.strip() in (b'', b'-- No entries --'):
            return dict(schema=1, realtimeMicros=0, monotonicMicros=0)
        require(result.returncode == 0 and len(result.stdout) <= 4096, reason)
        entry = decode(result.stdout)
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip().replace('-', '')
        require(entry.get('_BOOT_ID') == boot_id and entry.get('_SYSTEMD_UNIT') in CHRONY_UNITS
                and entry.get('_EXE') in CHRONY_EXECUTABLES, reason)
        timestamps = []
        for key in ('__REALTIME_TIMESTAMP', '__MONOTONIC_TIMESTAMP'):
            timestamp = entry.get(key)
            require(isinstance(timestamp, str) and re.fullmatch('[1-9][0-9]{0,18}', timestamp), reason)
            number = int(timestamp)
            require(number <= 9223372036854775807, reason)
            timestamps.append(number)
        return dict(schema=1, realtimeMicros=timestamps[0], monotonicMicros=timestamps[1])
    except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
        raise Refused('UNAVAILABLE_CHRONY_JOURNAL') from error


def chrony_target(unit):
    require(unit in CHRONY_UNITS)
    if public_file(CHRONY_POLICY) != CHRONY_RULE:
        raise OSError(errno.EPERM, 'Unpaired Chrony policy')
    fields = ('Id', 'LoadState', 'FragmentPath', 'SourcePath', 'DropInPaths', 'NeedDaemonReload', 'Transient',
              'ActiveState')
    value = systemd_properties(fields, unit)
    if (value['Id'] != unit or value['LoadState'] != 'loaded' or value['ActiveState'] not in CHRONY_ACTIVE_STATES
            or value['FragmentPath'] not in {str(root / unit) for root in VENDOR_UNIT_ROOTS}
            or value['SourcePath'] != '' or value['DropInPaths'] != ''
            or value['NeedDaemonReload'] != 'no' or value['Transient'] != 'no'):
        raise OSError(errno.ESTALE, 'Unpaired loaded Chrony unit')
    fragment = public_file(Path(value['FragmentPath']))
    state = value.pop('ActiveState')
    return digest(dict(unit=value, fragmentSha256=hashlib.sha256(fragment).hexdigest())), state


def require_chrony_bus_identity():
    # Polkit only reports the caller's unit for a PID file descriptor supplied
    # by the system bus. An older bus must fail before a service job is sent.
    try:
        reply = subprocess.check_output(
            ['/usr/bin/busctl', '--system', '--json=short', '--timeout=2s', 'call',
             'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
             'GetConnectionCredentials', 's', 'org.freedesktop.systemd1'],
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'},
            stderr=subprocess.DEVNULL, timeout=3)
        value = json.loads(reply)
        credentials, = value['data']
        if (value['type'] == 'a{sv}' and credentials['ProcessID'] == dict(type='u', data=1)
                and credentials['UnixUserID'] == dict(type='u', data=0)
                and credentials['ProcessFD']['type'] == 'h'):
            return
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        pass
    raise OSError(errno.EOPNOTSUPP, 'System D-Bus does not provide a verified process descriptor')


def chrony_binding(unit):
    binding, _ = chrony_target(unit)
    require_chrony_bus_identity()
    return binding


def change_chrony(action, unit, expected_binding):
    verb = CHRONY_ACTIONS[action]
    if chrony_binding(unit) != expected_binding:
        raise OSError(errno.ESTALE, 'Chrony target changed after prepare')
    try:
        result = subprocess.run(['/usr/bin/systemctl', '--system', '--no-ask-password', '--no-pager',
                                 '--job-mode=fail', verb, unit],
                                env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'},
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=CHRONY_JOB_TIMEOUT)
        require(result.returncode == 0, 'UNCERTAIN_CHRONY_RESULT')
        binding, state = chrony_target(unit)
        require(binding == expected_binding and state == ('active' if verb == 'start' else 'inactive'),
                'UNCERTAIN_CHRONY_RESULT')
    except (OSError, Refused, subprocess.SubprocessError) as error:
        # A job can be queued in PID1 even when its client fails or times out.
        raise Refused('UNCERTAIN_CHRONY_RESULT') from error


def chrony_datagram(stream, operation, daemon):
    """Chrony v6 null request/reply frames, with no compatibility retransmission."""
    sequence = os.urandom(4)
    request = struct.pack('!BBBBHH', CHRONY_PROTOCOL_VERSION, 1, 0, 0, operation, 0)
    require(stream.send(request + sequence + bytes(16)) == CHRONY_PACKET_BYTES, 'INVALID_CHRONY_DATAGRAM')
    credential_size = struct.calcsize('3i')
    reply, ancillary, flags, _ = stream.recvmsg(CHRONY_PACKET_BYTES, socket.CMSG_SPACE(credential_size))
    expected_reply = struct.pack('!BBBBHHHHHH', CHRONY_PROTOCOL_VERSION, 2, 0, 0, operation,
                                 CHRONY_NULL_REPLY, 0, 0, 0, 0) + sequence + bytes(8)
    require(not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) and reply == expected_reply
            and ancillary == [(socket.SOL_SOCKET, socket.SCM_CREDENTIALS, struct.pack('3i', *daemon))],
            'INVALID_CHRONY_ACK')


def chrony_command(runtime, target, expected_binding=None):
    """Probe the paired daemon, or issue exactly one step on the same connected socket."""
    sent = False
    try:
        binding, daemon = target()
        if expected_binding is not None and binding != expected_binding:
            raise OSError(errno.ESTALE, 'Chrony command endpoint changed after prepare')
        with tempfile.TemporaryDirectory(prefix='reply-', dir=runtime) as staged, \
                socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as stream:
            # Chrony v6 copies pathnames as C strings. An abstract socket cannot receive its replies.
            parent = Path(staged)
            reply = parent / 'chronyc.sock'
            stream.settimeout(CHRONY_COMMAND_TIMEOUT)
            stream.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            stream.bind(str(reply))
            reply.chmod(0o600)
            stream.connect(str(CHRONY_COMMAND))
            chrony_datagram(stream, CHRONY_PROBE, daemon)
            if target() != (binding, daemon):
                raise OSError(errno.ESTALE, 'Chrony command endpoint changed during admission')
            if expected_binding is not None:
                # Failures during submission or acknowledgement cannot prove that the daemon did not act.
                sent = True
                chrony_datagram(stream, CHRONY_MAKESTEP, daemon)
                require(target() == (binding, daemon), 'CHRONY_ENDPOINT_CHANGED')
        return binding
    except (OSError, Refused) as error:
        if sent:
            raise Refused('UNCERTAIN_CHRONY_STEP') from error
        if isinstance(error, Refused):
            raise OSError(errno.EPROTO, 'Chrony command endpoint could not be verified') from error
        raise


def process_status(pid):
    return dict(line.split(':', 1) for line in (Path('/proc') / str(pid) / 'status').read_text().splitlines()
                if ':' in line)


def chrony_step_target(unit):
    fragment, state = chrony_target(unit)
    fields = systemd_properties(('ExecStart', 'MainPID', 'ControlGroup', 'User', 'RuntimeDirectory', 'ActiveState'), unit)
    account = pwd.getpwnam(STEP_USER)
    executable = fields['ExecStart'].removeprefix('{ path=').partition(' ; ')[0]
    require(state == fields['ActiveState'] == 'active' and account.pw_uid > 0 and account.pw_gid > 0
            and fields['User'] == account.pw_name and fields['RuntimeDirectory'] == 'chrony'
            and executable in CHRONY_STARTERS and fields['ControlGroup'] == '/system.slice/' + unit
            and re.fullmatch('[1-9][0-9]{0,9}', fields['MainPID']), 'UNPAIRED_CHRONY_COMMAND')
    protected(Path(executable))
    pid = int(fields['MainPID'])
    uid, gid = account.pw_uid, account.pw_gid
    proc = Path('/proc') / str(pid)
    require((proc / 'cgroup').read_text().splitlines() == ['0::' + fields['ControlGroup']], 'UNPAIRED_CHRONY_COMMAND')
    status = process_status(pid)
    require(status['Uid'].split() == [str(uid)] * 4 and status['Gid'].split() == [str(gid)] * 4,
            'UNPAIRED_CHRONY_COMMAND')
    birth = (proc / 'stat').read_text().rpartition(') ')[2].split()[19]
    require(birth.isascii() and birth.isdigit(), 'UNPAIRED_CHRONY_COMMAND')
    require(unit_directory_present(CHRONY_COMMAND.parent.parent), 'UNPAIRED_CHRONY_COMMAND')
    parent, endpoint = CHRONY_COMMAND.parent.lstat(), CHRONY_COMMAND.lstat()
    require(stat.S_ISDIR(parent.st_mode) and stat.S_ISSOCK(endpoint.st_mode)
            and all(value.st_uid == uid and value.st_gid == gid and not value.st_mode & 0o022
                    for value in (parent, endpoint)), 'UNPAIRED_CHRONY_COMMAND')
    return digest(dict(fragment=fragment, pid=pid, birth=birth, uid=uid, gid=gid,
                       parent=identity(parent), endpoint=identity(endpoint))), (pid, uid, gid)


def chrony_step_exchange(unit, binding=None):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(STEP_TIMEOUT)
        try:
            require(unit_directory_present(STEP_SOCKET.parent), 'UNSAFE_LISTENER')
            metadata = STEP_SOCKET.lstat()
            require(stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == 0
                    and metadata.st_gid == pwd.getpwnam('kura-clock').pw_gid
                    and stat.S_IMODE(metadata.st_mode) == 0o660, 'UNSAFE_LISTENER')
            stream.connect(str(STEP_SOCKET))
            require(socket_peer(stream) == (1, 0, 0), 'UNSAFE_LISTENER')
        except Refused as error:
            raise OSError(errno.EPERM, 'Unpaired Chrony step listener') from error
        try:
            send(stream, dict(schema=1, unit=unit, binding=binding))
            stream.shutdown(socket.SHUT_WR)
            reply = receive(stream)
            if set(reply) == {'errno'} and type(reply['errno']) is int and 0 < reply['errno'] <= 4095:
                error_number = reply['errno']
            else:
                value = reply.get('binding')
                require(set(reply) == {'binding'} and isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                        and (binding is None or binding == value), 'UNPAIRED_CHRONY_REPLY')
                return value
        except (OSError, Refused) as error:
            if binding is None:
                raise OSError(errno.EPROTO, 'Chrony step preflight did not complete') from error
            raise Refused('UNCERTAIN_CHRONY_STEP') from error
        raise OSError(error_number, 'Chrony step was refused before submission')


def chrony_config_exchange(value, request_id=None, binding=None):
    request = dict(schema=1, unit=value) if request_id is None else dict(
        schema=1, configuration=value, requestId=request_id, binding=binding)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(CONFIG_TIMEOUT)
        try:
            require(unit_directory_present(CONFIG_SOCKET.parent), 'UNSAFE_LISTENER')
            metadata = CONFIG_SOCKET.lstat()
            require(stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == 0
                    and metadata.st_gid == pwd.getpwnam('kura-clock').pw_gid
                    and stat.S_IMODE(metadata.st_mode) == 0o660, 'UNSAFE_LISTENER')
            stream.connect(str(CONFIG_SOCKET))
            require(socket_peer(stream) == (1, 0, 0), 'UNSAFE_LISTENER')
        except (OSError, Refused) as error:
            raise OSError(errno.EPERM, 'Unpaired Chrony configuration listener') from error
        try:
            send(stream, request)
            stream.shutdown(socket.SHUT_WR)
            reply = receive(stream)
            if set(reply) == {'errno'} and type(reply['errno']) is int and 0 < reply['errno'] <= 4095:
                error_number = reply['errno']
            else:
                require(set(reply) == {'sha256'} and isinstance(reply['sha256'], str)
                        and re.fullmatch('[0-9a-f]{64}', reply['sha256'])
                        and (binding is None or binding == reply['sha256']), 'UNPAIRED_CHRONY_CONFIG_REPLY')
                return reply['sha256']
        except (OSError, Refused) as error:
            if binding is not None:
                raise Refused('UNCERTAIN_CHRONY_CONFIG') from error
            raise OSError(errno.EIO, 'Chrony configuration inspection did not complete') from error
        raise OSError(error_number, 'Chrony configuration refused before publication')


def chrony_config_runtime(unit):
    fragment, state = chrony_target(unit)
    observed = systemd_properties(('ActiveState', 'MainPID', 'ExecMainStartTimestampMonotonic'), unit)
    pid = observed['MainPID']
    started = observed['ExecMainStartTimestampMonotonic']
    if (state != observed['ActiveState'] or state not in ('active', 'inactive')
            or re.fullmatch(r'0|[1-9][0-9]{0,9}', pid) is None
            or re.fullmatch(r'0|[1-9][0-9]{0,19}', started) is None
            or (state == 'active' and (pid in ('0', '1') or started == '0'))
            or (state == 'inactive' and pid != '0')):
        raise OSError(errno.ESTALE, 'Chrony runtime is not in a stable paired state')
    return dict(fragment=fragment, state=state, pid=int(pid), started=int(started))


def prepare_chrony_config(argument, request_id):
    if chrony_config_runtime(argument['unit'])['state'] == 'active':
        require_chrony_bus_identity()
    return chrony_config_exchange(argument, request_id)


def configure_chrony(argument, request_id, binding):
    unit = argument['unit']
    before = chrony_config_runtime(unit)
    running = before['state'] == 'active'
    if running:
        require_chrony_bus_identity()
    wanted = hashlib.sha256(chrony_configuration(argument)).hexdigest()
    original = chrony_config_exchange(unit)
    if chrony_config_runtime(unit) != before:
        raise OSError(errno.ESTALE, 'Chrony runtime changed before publication')
    chrony_config_exchange(argument, request_id, binding)
    if not running or original == wanted:
        return

    # Publication already returned. Losing the observation or the systemd job
    # now leaves the original clock decision unresolved, never retryable.
    try:
        require(chrony_config_runtime(unit) == before and chrony_config_exchange(unit) == wanted,
                'UNCERTAIN_CHRONY_CONFIG_ACTIVATION')
        result = subprocess.run(['/usr/bin/systemctl', '--system', '--no-ask-password', 'restart', unit],
                                env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}, timeout=CHRONY_JOB_TIMEOUT,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        require(result.returncode == 0, 'UNCERTAIN_CHRONY_CONFIG_ACTIVATION')
        after = chrony_config_runtime(unit)
        require(after['state'] == 'active' and after['fragment'] == before['fragment']
                and after['pid'] != before['pid'] and after['started'] > before['started']
                and chrony_config_exchange(unit) == wanted,
                'UNCERTAIN_CHRONY_CONFIG_ACTIVATION')
    except (OSError, Refused, subprocess.SubprocessError) as error:
        raise Refused('UNCERTAIN_CHRONY_CONFIG_ACTIVATION') from error


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
        prior = (allow_legacy and self.actor_copy and not installed and set(value) == base | {'actions'}
                 and value['actions'] in (['adjust-realtime', 'sync-rtc'],
                                          ['adjust-realtime', 'sync-rtc', 'start-chrony', 'stop-chrony']))
        step = (allow_legacy and self.actor_copy and not installed and set(value) == base | {'actions'}
                and value['actions'] == list(OPERATIONS)[:-1])
        require((legacy or prior or step or (set(value) == base | {'actions'} and value['actions'] == list(OPERATIONS)))
                and type(value['schema']) is int and value['schema'] == 1
                and type(value['protocol']) is int and value['protocol'] == 1
                and value['actor'] == 'kura-clock' and value['caller'] == 'kurad'
                and type(value['files']) is dict, 'UNPAIRED_CODE')
        bundle = value['clockBundle']
        require(isinstance(bundle, str) and re.fullmatch(r'plugins/(?:[A-Za-z0-9_.-]+/)?org\.eclipse\.kura\.linux\.clock[A-Za-z0-9_.-]*\.jar', bundle) is not None,
                'UNPAIRED_CODE')
        old_rtc = (allow_legacy and self.actor_copy and not installed and type(value['files']) is dict
                   and 'libexec/clock-broker/' + RTC_SOCKET_UNIT not in value['files'])
        units = (LEGACY_UNITS if legacy else PREVIOUS_UNITS if prior else STEP_UNITS if step
                 else CONFIG_UNITS if old_rtc else UNITS)
        helpers = LEGACY_HELPERS if legacy or prior or step else HELPERS
        expected = {*helpers, *['libexec/clock-broker/' + name for name in units], bundle}
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
        if legacy or prior:
            capabilities = ('1.0.0',)
        elif step:
            capabilities = ('1.1.0',)
        elif allow_legacy and self.actor_copy and not installed:
            capabilities = ('1.2.1', '1.2.0')
        else:
            capabilities = ('1.2.1',)
        jar_contract(self.home / bundle, *capabilities)
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
        journal_gid = grp.getgrnam(CHRONY_JOURNAL_GROUP).gr_gid
        groups = set(os.getgroups())
        require(account.pw_uid > 0 and account.pw_gid > 0 and account.pw_shell == '/usr/sbin/nologin'
                and account.pw_dir == '/nonexistent', 'UNSAFE_ACTOR')
        require(os.getuid() == os.geteuid() == account.pw_uid and os.getgid() == os.getegid() == account.pw_gid
                and journal_gid > 0 and journal_gid != account.pw_gid and journal_gid in groups
                and groups <= {account.pw_gid, journal_gid}, 'UNSAFE_ACTOR')
        values = dict(line.split(':', 1) for line in Path('/proc/thread-self/status').read_text().splitlines() if ':' in line)
        require(values['Uid'].split() == [str(account.pw_uid)] * 4
                and values['Gid'].split() == [str(account.pw_gid)] * 4 and values['NoNewPrivs'].strip() == '1', 'UNSAFE_ACTOR')
        require(all(int(values[name].strip(), 16) == SYS_TIME for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')),
                'UNSAFE_ACTOR')
        directory(STATE, account.pw_uid)
        return account.pw_uid

    def peer(self, peer, stopping=False):
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
        require((fields['ActiveState'] == 'active' or (stopping and fields['ActiveState'] == 'deactivating'))
                and fields['MainPID'].isdigit() and int(fields['MainPID']) > 0
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
        require(type(value) is dict and type(value.get('schema')) is int and value.get('schema') == 1)
        action = value.get('action')
        require(isinstance(action, str))
        stopping = action in TEARDOWN_REQUESTS
        self.policy.check(); self.policy.peer(peer, stopping=stopping)
        if action == 'chrony-status':
            require(set(value) == {'schema', 'action'})
            return chrony_status()
        if action == 'chrony-last-step':
            require(set(value) == {'schema', 'action'})
            return chrony_last_step()
        if action == 'chrony-config-status':
            require(set(value) == {'schema', 'action', 'unit'} and value['unit'] in CHRONY_UNITS)
            return dict(schema=1, unit=value['unit'], sha256=chrony_config_exchange(value['unit']))
        with self.journal.lock():
            namespace = self.journal.namespace()
            if action in ('context', STOP_CONTEXT):
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
            self.policy.peer(peer, stopping=stopping)
            if operation in CHRONY_ACTIONS:
                if phase == 'prepare':
                    return self.journal.prepare(value, chrony_binding)
                return self.journal.commit(value, lambda unit, binding: change_chrony(operation, unit, binding))
            if operation == 'step-chrony':
                if phase == 'prepare':
                    return self.journal.prepare(value, chrony_step_exchange)
                return self.journal.commit(value, chrony_step_exchange)
            if operation == 'configure-chrony':
                request_id = value['requestId']
                if phase == 'prepare':
                    return self.journal.prepare(value, lambda config: prepare_chrony_config(config, request_id))
                return self.journal.commit(value, lambda config, binding: configure_chrony(config, request_id, binding))
            if phase == 'prepare':
                return self.journal.prepare(value, self.bind_rtc)
            actuate = self.adjust_realtime if operation == 'adjust-realtime' else self.sync_rtc
            return self.journal.commit(value, actuate)


def rtc_binding(device):
    binding, _ = rtc_relay_exchange(device, None)
    return binding


def rtc_set_time(device, expected_binding):
    if sys.platform != 'linux' or os.uname().machine not in ('aarch64', 'x86_64'):
        raise OSError(errno.ENOSYS, 'Unsupported RTC ioctl ABI')
    _, fd = rtc_relay_exchange(device, expected_binding)
    try:
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
    entry = RTC_CLASS / name
    kernel = entry.resolve(strict=True)
    if kernel.name != name or not kernel.is_relative_to('/sys/devices'):
        raise OSError(errno.ENODEV, 'RTC entry is outside the kernel device tree')
    before = kernel.stat()
    with (kernel / 'dev').open(encoding='ascii') as source:
        device_number = source.read(64).strip()
    if re.fullmatch(r'[0-9]{1,4}:[0-9]{1,7}', device_number) is None:
        raise OSError(errno.ENODEV, 'Unrecognized kernel RTC device number')
    major, minor = map(int, device_number.split(':'))
    if identity(kernel.stat()) != identity(before) or entry.resolve(strict=True) != kernel:
        raise OSError(errno.ESTALE, 'Kernel RTC changed during inspection')
    return dict(major=major, minor=minor, inode=before.st_ino, path=str(kernel))


def rtc_snapshot(device):
    path = Path(device)
    alias = None
    if device in RTC_ALIASES:
        require(unit_directory_present(path.parent), 'UNPAIRED_RTC_NODE')
        alias = path.lstat()
        if not stat.S_ISLNK(alias.st_mode) or alias.st_uid != 0:
            raise OSError(errno.ENODEV, 'RTC alias must be a Root-owned link')
        # Match the fixed kernel node name, including the historical misc alias.
        link = os.readlink(path)
        target = Path(link)
        if not target.is_absolute():
            if path == Path('/dev/misc/rtc') and link.startswith('../'):
                target = Path('/dev') / link[3:]
            else:
                target = path.parent / link
        if not RTC_NODE.fullmatch(str(target)):
            raise OSError(errno.ENODEV, 'RTC alias does not point directly to an RTC node')
        if identity(path.lstat()) != identity(alias):
            raise OSError(errno.ESTALE, 'RTC alias changed during inspection')
        path = Path(target)
    if not RTC_NODE.fullmatch(str(path)):
        raise OSError(errno.ENODEV, 'RTC target is outside the supported kernel nodes')
    require(unit_directory_present(path.parent), 'UNPAIRED_RTC_NODE')
    hardware = rtc_hardware(path.name)
    node = path.lstat()
    if (not stat.S_ISCHR(node.st_mode) or node.st_uid != 0 or node.st_nlink != 1
            or (os.major(node.st_rdev), os.minor(node.st_rdev)) != (hardware['major'], hardware['minor'])):
        raise OSError(errno.ENODEV, 'RTC node does not match the kernel device')
    binding = digest(dict(node=path.name, kernel=hardware, hostNode=identity(node),
                          alias=None if alias is None else identity(alias)))
    return path, node, binding


def rtc_relay_exchange(device, binding):
    # This relay can only inspect nodes and open read-only descriptions. Any
    # relay failure occurs before the caller can enter the RTC write ioctl.
    descriptors = array('i')
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as stream:
            stream.settimeout(RTC_TIMEOUT)
            require(unit_directory_present(RTC_SOCKET.parent), 'UNSAFE_LISTENER')
            metadata = RTC_SOCKET.lstat()
            require(stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == 0
                    and metadata.st_gid == pwd.getpwnam('kura-clock').pw_gid
                    and stat.S_IMODE(metadata.st_mode) == 0o660, 'UNSAFE_LISTENER')
            stream.connect(str(RTC_SOCKET))
            require(socket_peer(stream) == (1, 0, 0), 'UNSAFE_LISTENER')
            stream.sendall(encode(dict(schema=1, device=device, binding=binding)))
            raw, control, flags, _ = stream.recvmsg(MAX_BYTES, socket.CMSG_SPACE(descriptors.itemsize),
                                                   socket.MSG_CMSG_CLOEXEC)
        for level, kind, data in control:
            if (level, kind) == (socket.SOL_SOCKET, socket.SCM_RIGHTS):
                descriptors.frombytes(data[:len(data) - len(data) % descriptors.itemsize])
        require(not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC), 'INVALID_RTC_REPLY')
        reply = decode(raw)
        if set(reply) == {'errno'} and type(reply['errno']) is int and 0 < reply['errno'] <= 4095:
            require(not control, 'INVALID_RTC_REPLY')
            raise OSError(reply['errno'], 'RTC device admission failed')
        value = reply.get('binding')
        require(set(reply) == {'binding'} and isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value)
                and (not control if binding is None else
                     value == binding and len(control) == len(descriptors) == 1), 'INVALID_RTC_REPLY')
        return value, descriptors.pop() if binding is not None else None
    except OSError as error:
        if error.errno is None:
            raise OSError(errno.ETIMEDOUT, 'RTC device admission timed out') from error
        raise
    except (Refused, ValueError) as error:
        raise OSError(errno.EPROTO, 'RTC device relay could not be verified') from error
    finally:
        for fd in descriptors:
            with contextlib.suppress(OSError):
                os.close(fd)


def serve_rtc_request(stream):
    raw, _, flags, _ = stream.recvmsg(MAX_BYTES)
    require(not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC), 'INVALID_FRAME')
    request = decode(raw)
    require(set(request) == {'schema', 'device', 'binding'} and type(request['schema']) is int
            and request['schema'] == 1 and isinstance(request['device'], str)
            and (request['device'] in RTC_ALIASES or RTC_NODE.fullmatch(request['device'])), 'INVALID_RTC_REQUEST')
    device, expected = request['device'], request['binding']
    require(expected is None or isinstance(expected, str) and re.fullmatch('[a-f0-9]{64}', expected),
            'INVALID_RTC_REQUEST')
    fd = None
    try:
        path, before, binding = rtc_snapshot(device)
        if expected is not None:
            if binding != expected:
                raise OSError(errno.ESTALE, 'RTC device changed since prepare')
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
            opened = os.fstat(fd)
            if (identity(opened) != identity(before) or opened.st_rdev != before.st_rdev
                    or rtc_snapshot(device)[2] != binding):
                raise OSError(errno.ESTALE, 'RTC device changed during open')
        response = encode(dict(binding=binding))
        if fd is not None:
            stream.sendmsg([response], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array('i', [fd]))])
            return
    except OSError as error:
        response = encode(dict(errno=error.errno or errno.EIO))
    finally:
        if fd is not None:
            os.close(fd)
    stream.sendall(response)


def serve_rtc():
    status = process_status('thread-self')
    require(status['Uid'].split() == status['Gid'].split() == ['0'] * 4
            and status['NoNewPrivs'].strip() == '1'
            and all(int(status[name].strip(), 16) == 0 for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')),
            'UNSAFE_RTC_RELAY')
    policy = Policy(actor=True)
    policy.check()
    with activated_listener(RTC_SOCKET, 'rtc', socket.SOCK_SEQPACKET) as listener:
        stream, _ = listener.accept()
        with stream:
            stream.settimeout(RTC_TIMEOUT)
            clock_actor_peer(socket_peer(stream))
            serve_rtc_request(stream)


def check_rtc_projection_node(value, hardware):
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
        check_rtc_projection_node((path / name).lstat(), hardware)
    return catalog


def publish_path(staged, target, replace):
    # NOREPLACE for fresh publication. EXCHANGE retains a checked old entry.
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(staged), -100, os.fsencode(target), 2 if replace else 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def retire_rtc_projection(previous, maintenance):
    if not os.path.lexists(RTC_SOURCE):
        return
    require(previous is not None and maintenance is not None
            and digest(previous) == maintenance['cohortSha256']
            and RTC_UNIT in maintenance['units'] and RTC_SOCKET_UNIT not in maintenance['units']
            and previous['files'].get('libexec/clock-broker/' + RTC_UNIT) == maintenance['units'][RTC_UNIT]
            and 'libexec/clock-broker/' + RTC_SOCKET_UNIT not in previous['files'],
            'UNPAIRED_RTC_PROJECTION')
    require(unit_directory_present(RTC_SOURCE.parent), 'UNPAIRED_RTC_PROJECTION')
    rtc_catalog(RTC_SOURCE)
    # Preserve the checked projection, including old device identities. After
    # this single rename only Root can walk to it, even if dpkg is interrupted.
    archive = Path(tempfile.mkdtemp(prefix='.kura-clock-rtc-retired-', dir=RTC_SOURCE.parent))
    try:
        publish_path(RTC_SOURCE, archive / 'projection', False)
    except OSError:
        archive.rmdir()
        raise


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


def socket_peer(stream):
    format_string = '3i'
    return struct.unpack(format_string, stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                         struct.calcsize(format_string)))


def activated_listener(path, descriptor, kind=socket.SOCK_STREAM):
    require(os.environ.get('LISTEN_PID') == str(os.getpid()) and os.environ.get('LISTEN_FDS') == '1'
            and os.environ.get('LISTEN_FDNAMES') == descriptor, 'INVALID_LISTENER')
    listener = socket.socket(fileno=3)
    require(listener.family == socket.AF_UNIX and listener.type == kind
            and listener.getsockname() == str(path) and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1,
            'INVALID_LISTENER')
    return listener


def clock_actor_peer(peer):
    pid, uid, gid = peer
    account = pwd.getpwnam('kura-clock')
    require(pid > 1 and uid == account.pw_uid > 0 and gid == account.pw_gid > 0, 'UNAUTHORIZED')
    value = systemd_properties(('ActiveState', 'MainPID'), 'kura-clock-broker.service')
    require(value == dict(ActiveState='active', MainPID=str(pid)), 'UNAUTHORIZED')
    status = process_status(pid)
    require(status['Uid'].split() == [str(uid)] * 4 and status['Gid'].split() == [str(gid)] * 4
            and status['NoNewPrivs'].strip() == '1' and int(status['CapEff'].strip(), 16) == SYS_TIME,
            'UNAUTHORIZED')


def serve_chrony_step():
    account = pwd.getpwnam(STEP_USER)
    broker_gid = pwd.getpwnam('kura-clock').pw_gid
    status = process_status('thread-self')
    groups = set(os.getgroups())
    require(os.getuid() == os.geteuid() == account.pw_uid > 0
            and os.getgid() == os.getegid() == account.pw_gid > 0 and account.pw_gid != broker_gid
            and broker_gid in groups and groups <= {account.pw_gid, broker_gid} and status['NoNewPrivs'].strip() == '1'
            and all(int(status[name].strip(), 16) == 0 for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')),
            'UNSAFE_CHRONY_STEP_SERVICE')
    directory(STEP_RUNTIME, account.pw_uid)
    policy = Policy(actor=True); policy.check()
    with activated_listener(STEP_SOCKET, 'chrony-step') as listener:
        while True:
            stream, _ = listener.accept()
            with stream:
                stream.settimeout(2)
                try:
                    policy.check()
                    clock_actor_peer(socket_peer(stream))
                    request = receive(stream)
                    require(set(request) == {'schema', 'unit', 'binding'} and type(request['schema']) is int
                            and request['schema'] == 1 and isinstance(request['unit'], str)
                            and request['unit'] in CHRONY_UNITS, 'INVALID_CHRONY_COMMAND')
                    binding = request['binding']
                    require(binding is None or (isinstance(binding, str) and re.fullmatch('[0-9a-f]{64}', binding)),
                            'INVALID_CHRONY_COMMAND')
                    try:
                        actual = chrony_command(STEP_RUNTIME, lambda: chrony_step_target(request['unit']), binding)
                        reply = dict(binding=actual)
                    except OSError as error:
                        reply = dict(errno=error.errno or errno.EIO)
                    send(stream, reply)
                except (OSError, Refused, ValueError, KeyError, IndexError, zipfile.BadZipFile):
                    # Close without claiming a result if a submitted command lost a paired acknowledgement.
                    continue


def chrony_config_target(unit):
    from kura_chrony_config import CHRONYD, CONFIG_FILE

    runtime = chrony_config_runtime(unit)
    fields = systemd_properties(('ExecStart', 'EnvironmentFiles', 'Environment'), unit)
    command_line = '{ path=/usr/sbin/chronyd ; argv[]=/usr/sbin/chronyd $DAEMON_OPTS ; ignore_errors=no ;'
    if (not fields['ExecStart'].startswith(command_line) or not fields['ExecStart'].endswith(' }')
            or fields['ExecStart'].count('{') != 1 or fields['Environment'] != ''
            or fields['EnvironmentFiles'] != '/etc/default/chrony (ignore_errors=yes)'
            or os.path.lexists('/etc/chrony.conf')):
        raise OSError(errno.EOPNOTSUPP, 'Unsupported effective Chrony configuration path')
    options_path = Path('/etc/default/chrony')
    options = public_file(options_path, 4096) if os.path.lexists(options_path) else b''
    directives = [line.strip() for line in options.split(b'\n') if line.strip() and not line.lstrip().startswith(b'#')]
    allowed_options = rb'DAEMON_OPTS="(?:-F [0-2](?: -x)?|-x)?"'
    if len(directives) > 1 or (directives and not re.fullmatch(allowed_options, directives[0])):
        raise OSError(errno.EOPNOTSUPP, 'Unsupported effective Chrony options')
    protected(CHRONYD)
    protected(CONFIG_FILE)
    return digest(dict(runtime=runtime, options=hashlib.sha256(options).hexdigest(), binary=identity(CHRONYD.lstat())))


def serve_chrony_config():
    from kura_chrony_config import CONFIG_FILE, Config, parse_configuration

    status = process_status('thread-self')
    require(os.getuid() == os.geteuid() == os.getgid() == os.getegid() == 0
            and set(os.getgroups()) <= {0} and status['NoNewPrivs'].strip() == '1'
            and all(int(status[name].strip(), 16) == 0 for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')),
            'UNSAFE_CHRONY_CONFIG_SERVICE')
    policy = Policy(actor=True); policy.check()
    config = Config(CONFIG_FILE, chrony_config_target)
    with activated_listener(CONFIG_SOCKET, 'chrony-config') as listener:
        while True:
            stream, _ = listener.accept()
            with stream:
                stream.settimeout(3)
                try:
                    policy.check()
                    clock_actor_peer(socket_peer(stream))
                    request = receive(stream)
                    require(type(request.get('schema')) is int and request['schema'] == 1)
                    try:
                        if set(request) == {'schema', 'unit'}:
                            unit = request['unit']
                            require(unit in CHRONY_UNITS)
                            _, raw, _, _ = config.observation(unit)
                            value = hashlib.sha256(raw).hexdigest()
                        else:
                            require(set(request) == {'schema', 'configuration', 'requestId', 'binding'})
                            argument = request['configuration']
                            candidate = chrony_configuration(argument)
                            request_id = identifier(request['requestId'])
                            binding = request['binding']
                            unit = argument['unit']
                            if binding is None:
                                value = config.prepare(unit, candidate)
                            else:
                                require(isinstance(binding, str) and re.fullmatch('[0-9a-f]{64}', binding))
                                value = config.commit(unit, candidate, binding, request_id, parse_configuration)
                        reply = dict(sha256=value)
                    except OSError as error:
                        reply = dict(errno=error.errno or errno.EIO)
                    send(stream, reply)
                except (OSError, Refused, ValueError, KeyError, IndexError, subprocess.SubprocessError, zipfile.BadZipFile):
                    # No success or deterministic failure can be inferred across a lost reply.
                    continue


def serve():
    policy = Policy(actor=True); policy.check(); owner = policy.actor()
    manager = Manager(policy, Journal(STATE, owner))
    with activated_listener(SOCKET, 'control') as listener:
        while True:
            stream, _ = listener.accept()
            with stream:
                stream.settimeout(5)
                try:
                    result = manager.handle(receive(stream), socket_peer(stream))
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
        elif sys.argv[1] == 'serve-chrony-step':
            serve_chrony_step()
        elif sys.argv[1] == 'serve-chrony-config':
            serve_chrony_config()
        else:
            require(sys.argv[1] == 'serve-rtc', 'INVALID_ENTRYPOINT')
            serve_rtc()
    except (Refused, OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        reason = error.reason if isinstance(error, Refused) else 'UNRESOLVED_OR_UNAVAILABLE'
        print(reason, file=sys.stderr)
        raise SystemExit(1)
