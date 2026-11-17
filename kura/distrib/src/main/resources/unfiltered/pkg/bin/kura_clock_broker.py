#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Dedicated non-Root CAP_SYS_TIME actor; fixed typed wall-clock protocol only."""
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
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_journal import (Journal, Refused, command, create, decode, digest, directory, encode,
                                identifier, identity, read, require, sync, MAX_BYTES)

HOME = Path('/opt/eclipse/kura')
ACTOR_HOME = Path('/usr/libexec/kura-clock-broker')
STATE = Path('/var/lib/kura-clock-broker')
SOCKET = Path('/run/kura-clock-broker/control.sock')
COHORT = Path('libexec/clock-broker/cohort.json')
UNITS = ('kura-clock-broker.socket', 'kura-clock-broker.service')
HELPERS = ('bin/kura_clock_broker.py', 'bin/kura_clock_journal.py', 'bin/kura_clock_client.py', 'bin/kura_clock_setup.py')
SYS_TIME = 1 << 25


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
                 actor='kura-clock', caller='kurad', action='adjust-realtime')
    target = home / COHORT
    with target.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o644)
        stream.write(encode(value) + b'\n')
    return value


class Policy:
    def __init__(self, actor=False):
        self.home = ACTOR_HOME if actor else HOME
        self.actor_copy = actor

    def check(self, installed=True):
        raw = public_file(self.home / COHORT)
        value = decode(raw)
        require(set(value) == {'schema', 'protocol', 'files', 'clockBundle', 'actor', 'caller', 'action'}
                and type(value['schema']) is int and value['schema'] == 1
                and type(value['protocol']) is int and value['protocol'] == 1
                and value['actor'] == 'kura-clock' and value['caller'] == 'kurad'
                and value['action'] == 'adjust-realtime' and type(value['files']) is dict, 'UNPAIRED_CODE')
        bundle = value['clockBundle']
        require(isinstance(bundle, str) and re.fullmatch(r'plugins/(?:[A-Za-z0-9_.-]+/)?org\.eclipse\.kura\.linux\.clock[A-Za-z0-9_.-]*\.jar', bundle) is not None,
                'UNPAIRED_CODE')
        expected = {*HELPERS, *['libexec/clock-broker/' + name for name in UNITS], bundle}
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
            for name in UNITS:
                require(public_file(Path('/lib/systemd/system') / name)
                        == public_file(self.home / 'libexec/clock-broker' / name), 'UNPAIRED_CODE')
                for root in ('/etc/systemd/system', '/run/systemd/system'):
                    require(not os.path.lexists(Path(root) / name)
                            and not os.path.lexists(Path(root) / (name + '.d')), 'UNPAIRED_CODE')
            # Also reject vendor drop-ins: source pairing includes effective units.
            for name in UNITS:
                require(not os.path.lexists(Path('/lib/systemd/system') / (name + '.d')), 'UNPAIRED_CODE')
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
    def __init__(self, policy, journal, adjust_realtime=None):
        self.policy = policy
        self.journal = journal
        self.adjust_realtime = adjust_realtime or (lambda nanos: time.clock_settime_ns(time.CLOCK_REALTIME, nanos))

    def handle(self, value, peer):
        self.policy.check(); self.policy.peer(peer)
        require(type(value) is dict and type(value.get('schema')) is int and value.get('schema') == 1)
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
            require(action in ('prepare-adjust', 'commit-adjust'))
            value = command(dict(value, action='adjust-realtime'))
            require(value['cohortSha256'] == self.policy.cohort, 'UNPAIRED_CODE')
            # Check again under admission immediately before any durable intent.
            self.policy.check()
            require(value['cohortSha256'] == self.policy.cohort, 'UNPAIRED_CODE')
            self.policy.peer(peer)
            if action == 'prepare-adjust':
                return self.journal.prepare(value)
            return self.journal.commit(value, self.adjust_realtime)


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
        require(sys.argv == [str(ACTOR_HOME / 'bin/kura_clock_broker.py'), 'serve'], 'INVALID_ENTRYPOINT')
        serve()
    except (Refused, OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        reason = error.reason if isinstance(error, Refused) else 'UNRESOLVED_OR_UNAVAILABLE'
        print(reason, file=sys.stderr)
        raise SystemExit(1)
