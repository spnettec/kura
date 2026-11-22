#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Socket-activated standalone Core reboot broker and its fixed Main helper."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import pwd
import select
import shutil
import socket
import stat
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import (HOME, VENDOR_UNIT_ROOTS, protected, public_file, unit_directory_present,
                              unit_input_names, unit_load_paths)
from kura_clock_journal import Refused, decode, digest, directory, encode, identifier, identity, read, require
from kura_reboot_journal import RebootJournal
from kura_reboot_protocol import RebootProtocol, RebootSender

STATE = Path('/var/lib/kura-reboot-broker')
SENDER = Path('/var/lib/kura-reboot-sender')
AUTHORITY = Path('/etc/kura/reboot-broker-authority.json')
MAIN_AUTHORITY = Path('/run/kura-reboot-main-authority.json')
INSTALLATION = Path('/etc/kura/reboot-broker-installation.json')
SOCKET = Path('/run/kura-reboot-broker/control.sock')
HELPER = HOME / 'bin/kura_reboot_broker.py'
COHORT = Path('libexec/reboot-broker/cohort.json')
MAIN_UNIT = 'kura.service'
EMPTY_KEY_DROPINS = Path('/etc/systemd/system/kura.service.d')
UNITS = ('kura-reboot-broker.service', 'kura-reboot-broker.socket', MAIN_UNIT)
UNIT_PROPERTIES = ('Id', 'Names', 'LoadState', 'FragmentPath', 'SourcePath', 'DropInPaths',
                   'NeedDaemonReload', 'Transient')
MAIN_PROPERTIES = ('MainPID', 'ControlGroup', 'ActiveState', 'InvocationID')
FILES = (
    'bin/kura_clock_journal.py', 'bin/kura_clock_broker.py',
    'bin/kura_reboot_journal.py', 'bin/kura_reboot_protocol.py', 'bin/kura_reboot_broker.py',
    'bin/kura_reboot_setup.py',
    *((COHORT.parent / name).as_posix() for name in UNITS),
)
PEER_PIDFD = getattr(socket, 'SO_PEERPIDFD', 77)  # Linux generic UAPI, ARM64 and amd64.
MAX_FRAME = 4096
REPLY_TIMEOUT = 12
CALLER = 'kurad'
MAIN_CGROUP = '0::/system.slice/' + MAIN_UNIT
MAX_UNIT_OUTPUT = 64 * 1024
ENVIRONMENT = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
CLIENT_ARGS = ('/usr/bin/python3', '-I', '-B', str(HELPER), 'client')
DISPATCH_ARGS = ('/usr/bin/systemctl', '--system', '--no-ask-password', '--no-wall', '--no-block', 'reboot')


def file_hash(raw):
    return hashlib.sha256(raw).hexdigest()


def package_cohort(home):
    target = home / COHORT
    target.parent.mkdir(mode=0o755)
    for unit in UNITS:
        source = home / 'install' / unit
        require(source.is_file() and not source.is_symlink(), 'UNPAIRED_CODE')
        shutil.copyfile(source, target.parent / unit)
    files = {}
    for name in FILES:
        path = home / name
        require(path.is_file() and not path.is_symlink(), 'UNPAIRED_CODE')
        files[name] = file_hash(path.read_bytes())
    manifest = dict(schema=1, action='reboot', caller=CALLER, files=files)
    with target.open('xb') as output:
        os.fchmod(output.fileno(), 0o644)
        output.write(encode(manifest) + b'\n')
    return manifest


def manager_properties(unit, names):
    require(unit in UNITS, 'UNPAIRED_UNIT')
    result = subprocess.run(['/usr/bin/systemctl', '--system', '--no-ask-password', 'show', '--all',
                             '--property=' + ','.join(names), unit], env=ENVIRONMENT, capture_output=True, timeout=4)
    require(result.returncode == 0 and len(result.stdout) <= MAX_UNIT_OUTPUT, 'UNPAIRED_UNIT')
    values = {}
    for line in result.stdout.decode('ascii').splitlines():
        name, separator, value = line.partition('=')
        require(separator == '=' and name in names and name not in values, 'UNPAIRED_UNIT')
        values[name] = value
    require(set(values) == set(names), 'UNPAIRED_UNIT')
    return values


def verify_unit_sources(units=UNITS):
    for root in unit_load_paths():
        if not unit_directory_present(root):
            continue
        for unit in units:
            names = unit_input_names(unit)
            if root not in VENDOR_UNIT_ROOTS:
                names.append(unit)
            for name in names:
                path = root / name
                try:
                    metadata = path.lstat()
                except FileNotFoundError:
                    continue
                if path == EMPTY_KEY_DROPINS:
                    # The key service reserves this private directory even with no drop-in.
                    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == metadata.st_gid == 0
                            and stat.S_IMODE(metadata.st_mode) == 0o700 and not any(path.iterdir())
                            and identity(metadata) == identity(path.lstat()), 'UNPAIRED_UNIT')
                    continue
                raise Refused('UNPAIRED_UNIT')


def account_binding(path=None):
    value = decode(public_file(AUTHORITY if path is None else path))
    account = pwd.getpwnam(CALLER)
    require(set(value) == {'schema', 'namespace', 'callerUid', 'callerGid'} and type(value['schema']) is int
            and value['schema'] == 1 and type(value['callerUid']) is int and type(value['callerGid']) is int
            and account.pw_uid == value['callerUid'] > 0 and account.pw_gid == value['callerGid'] > 0,
            'UNPAIRED_ACCOUNT')
    identifier(value['namespace'])
    return value


def sender_binding(binding):
    directory(SENDER, binding['callerUid'])
    require(SENDER.lstat().st_gid == binding['callerGid']
            and read(SENDER / 'binding.json', 0, 0o644) == encode(binding), 'UNPAIRED_SENDER')


class Policy:
    def packaged(self):
        manifest = decode(public_file(HOME / COHORT))
        require(set(manifest) == {'schema', 'action', 'caller', 'files'} and type(manifest['schema']) is int
                and manifest['schema'] == 1 and manifest['action'] == 'reboot' and manifest['caller'] == CALLER
                and type(manifest['files']) is dict and set(manifest['files']) == set(FILES), 'UNPAIRED_CODE')
        for name in FILES:
            require(file_hash(public_file(HOME / name)) == manifest['files'][name], 'UNPAIRED_CODE')
        return manifest

    def check(self, *, actor, include_main=True):
        manifest = self.packaged()
        units = UNITS if include_main else UNITS[:2]
        if actor:
            verify_unit_sources(units)
        for unit in units:
            loaded = manager_properties(unit, UNIT_PROPERTIES)
            require(loaded['Id'] == unit and loaded['Names'].split() == [unit] and loaded['LoadState'] == 'loaded'
                    and loaded['FragmentPath'] in {str(root / unit) for root in VENDOR_UNIT_ROOTS}
                    and loaded['SourcePath'] == loaded['DropInPaths'] == ''
                    and loaded['NeedDaemonReload'] == loaded['Transient'] == 'no', 'UNPAIRED_UNIT')
            packaged_unit = (COHORT.parent / unit).as_posix()
            require(file_hash(public_file(Path(loaded['FragmentPath']))) == manifest['files'][packaged_unit],
                    'UNPAIRED_UNIT')
        if actor:
            return digest(manifest), account_binding()
        require(os.statvfs(MAIN_AUTHORITY).f_flag & os.ST_RDONLY, 'UNPAIRED_INSTALLATION')
        return digest(manifest), account_binding(MAIN_AUTHORITY)


def proc_file(pid, name):
    with (Path('/proc') / str(pid) / name).open('rb') as source:
        raw = source.read(MAX_UNIT_OUTPUT + 1)
    require(len(raw) <= MAX_UNIT_OUTPUT, 'UNAUTHORIZED')
    return raw


def proc_status(pid):
    return dict(line.split(':', 1) for line in proc_file(pid, 'status').decode('ascii').splitlines() if ':' in line)


def verify_identity(status, uid, gid):
    require(status['Uid'].split() == [str(uid)] * 4 and status['Gid'].split() == [str(gid)] * 4, 'UNAUTHORIZED')


@contextmanager
def socket_peer(stream):
    pid, uid, gid = struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    require(pid > 0 and uid >= 0 and gid >= 0, 'UNAUTHORIZED')
    # This fd pins the process that created the socket; a numeric PID alone does not.
    pidfd = stream.getsockopt(socket.SOL_SOCKET, PEER_PIDFD)
    try:
        require(pidfd >= 0, 'UNAUTHORIZED')
        yield pid, uid, gid, pidfd
    finally:
        if pidfd >= 0:
            os.close(pidfd)


def verify_alive(pidfd, reason='UNAUTHORIZED'):
    poll = select.poll()
    poll.register(pidfd, select.POLLIN)
    require(not poll.poll(0), reason)


def main_peer(peer, binding):
    pid, uid, gid, pidfd = peer
    require(uid == binding['callerUid'] and gid == binding['callerGid'], 'UNAUTHORIZED')
    verify_alive(pidfd)
    main = manager_properties(MAIN_UNIT, MAIN_PROPERTIES)
    main_pid = int(main['MainPID'])
    require(main['ActiveState'] == 'active' and main['ControlGroup'] == '/system.slice/' + MAIN_UNIT
            and main_pid > 1 and pid != main_pid and len(main['InvocationID']) == 32, 'UNAUTHORIZED')
    status = proc_status(pid)
    verify_identity(status, uid, gid)
    require(status['PPid'].strip() == str(main_pid), 'UNAUTHORIZED')
    verify_identity(proc_status(main_pid), uid, gid)
    for process in (pid, main_pid):
        require(proc_file(process, 'cgroup').splitlines() == [MAIN_CGROUP.encode()], 'UNAUTHORIZED')
    expected = b'\0'.join(os.fsencode(arg) for arg in CLIENT_ARGS) + b'\0'
    require(proc_file(pid, 'cmdline') == expected, 'UNAUTHORIZED')
    require(manager_properties(MAIN_UNIT, MAIN_PROPERTIES) == main, 'UNAUTHORIZED')
    verify_alive(pidfd)
    return True


def dispatch_reboot():
    # The action has no caller-supplied argv, environment, unit, or shell.
    protected(Path(DISPATCH_ARGS[0]))
    environment = dict(ENVIRONMENT, SYSTEMCTL_SKIP_AUTO_KEXEC='1', SYSTEMCTL_SKIP_AUTO_SOFT_REBOOT='1')
    try:
        process = subprocess.Popen(DISPATCH_ARGS, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return 'FAILED', 'NOT_STARTED'
    try:
        code = process.wait(timeout=REPLY_TIMEOUT)
    except subprocess.TimeoutExpired:
        # Ending the local wait cannot revoke a systemd request already sent.
        process.kill()
        process.wait(timeout=1)
        return 'UNKNOWN', 'DISPATCH_UNCONFIRMED'
    return ('ACCEPTED', 'MANAGER_ACCEPTED') if code == 0 else ('UNKNOWN', 'DISPATCH_UNCONFIRMED')


def receive(stream, *, timeout=REPLY_TIMEOUT, maximum=MAX_FRAME):
    deadline = time.monotonic() + timeout

    def get(count):
        value = bytearray()
        while len(value) < count:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'INVALID_FRAME')
            stream.settimeout(remaining)
            chunk = stream.recv(count - len(value))
            require(chunk, 'INVALID_FRAME')
            value.extend(chunk)
        return bytes(value)

    size, = struct.unpack('>I', get(4))
    require(0 < size <= maximum, 'INVALID_FRAME')
    value = decode(get(size))
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'INVALID_FRAME')
    stream.settimeout(remaining)
    require(stream.recv(1) == b'', 'INVALID_FRAME')
    return value


def send(stream, value, *, maximum=MAX_FRAME):
    raw = encode(value)
    require(len(raw) <= maximum, 'INVALID_FRAME')
    stream.settimeout(REPLY_TIMEOUT)
    stream.sendall(struct.pack('>I', len(raw)) + raw)
    stream.shutdown(socket.SHUT_WR)


def serve_socket(stream, protocol):
    try:
        with socket_peer(stream) as peer:
            # Reject unauthorized peers before accepting any application frame.
            require(protocol.authorize(peer), 'UNAUTHORIZED')
            result = protocol.handle(receive(stream), peer)
            response = dict(ok=True, result=result)
    except Refused as error:
        response = dict(ok=False, reason=error.reason)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        response = dict(ok=False, reason='UNRESOLVED_OR_UNAVAILABLE')
    try:
        send(stream, response)
    except OSError:
        pass


def serve():
    require(os.getuid() == os.geteuid() == os.getgid() == os.getegid() == 0, 'UNSAFE_ACTOR')
    status = proc_status(os.getpid())
    require(status['NoNewPrivs'].strip() == '1'
            and all(int(status[name].strip(), 16) == 0 for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')),
            'UNSAFE_ACTOR')
    directory(STATE, 0)
    require(os.environ.get('LISTEN_PID') == str(os.getpid()) and os.environ.get('LISTEN_FDS') == '1'
            and os.environ.get('LISTEN_FDNAMES') == 'control', 'INVALID_LISTENER')
    policy = Policy()
    cohort, binding = policy.check(actor=True, include_main=False)
    require(read(INSTALLATION, 0) == encode(binding), 'UNPAIRED_INSTALLATION')

    def authorize(peer):
        # Authenticate the actual process before repeating the live unit and cohort check.
        require(main_peer(peer, binding), 'UNAUTHORIZED')
        require(policy.check(actor=True) == (cohort, binding), 'UNPAIRED_CODE')
        require(read(INSTALLATION, 0) == encode(binding), 'UNPAIRED_INSTALLATION')
        return True

    protocol = RebootProtocol(RebootJournal(STATE, binding['namespace'], cohort), authorize, dispatch_reboot)
    with socket.socket(fileno=3) as listener:
        require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM
                and listener.getsockname() == str(SOCKET)
                and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN), 'INVALID_LISTENER')
        while True:
            connection, _ = listener.accept()
            with connection:
                serve_socket(connection, protocol)


def verify_socket(gid):
    for parent in SOCKET.parents:
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022, 'INVALID_LISTENER')
    info = SOCKET.lstat()
    require(stat.S_ISSOCK(info.st_mode) and info.st_uid == 0 and info.st_gid == gid and info.st_nlink == 1
            and stat.S_IMODE(info.st_mode) == 0o660, 'INVALID_LISTENER')


def exchange(value, gid):
    verify_socket(gid)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(REPLY_TIMEOUT)
        stream.connect(str(SOCKET))
        with socket_peer(stream) as (pid, uid, _, pidfd):
            require(pid == 1 and uid == 0, 'INVALID_LISTENER')
            verify_alive(pidfd, 'INVALID_LISTENER')
            send(stream, value)
            response = receive(stream)
            verify_alive(pidfd, 'INVALID_LISTENER')
    require(type(response.get('ok')) is bool, 'INVALID_REPLY')
    if not response['ok']:
        require(set(response) == {'ok', 'reason'} and isinstance(response['reason'], str), 'INVALID_REPLY')
        raise Refused(response['reason'])
    require(set(response) == {'ok', 'result'} and type(response['result']) is dict, 'INVALID_REPLY')
    return response['result']


def client():
    cohort, binding = Policy().check(actor=False)
    uid, gid = binding['callerUid'], binding['callerGid']
    verify_identity(proc_status(os.getpid()), uid, gid)
    sender_binding(binding)
    sender = RebootSender(SENDER, binding['namespace'], cohort, lambda value: exchange(value, gid))
    print(encode(sender.submit()).decode('ascii'), flush=True)


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 2 and sys.argv[0] == str(HELPER), 'INVALID_ENTRYPOINT')
        require(sys.argv[1] in ('serve', 'client'), 'INVALID_ENTRYPOINT')
        (serve if sys.argv[1] == 'serve' else client)()
    except (Refused, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(error.reason if isinstance(error, Refused) else 'UNRESOLVED_OR_UNAVAILABLE', file=sys.stderr)
        raise SystemExit(1)
