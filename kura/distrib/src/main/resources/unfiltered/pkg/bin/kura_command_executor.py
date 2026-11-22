# SPDX-License-Identifier: EPL-2.0
"""Execute ordinary commands and fixed ICMP checks in their own workers."""
import array
from contextlib import contextmanager
import fcntl
import ipaddress
import os
from pathlib import Path
import pwd
import re
import select
import shutil
import socket
import stat
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import HOME, canonical_alias, protected, public_file
from kura_clock_journal import Refused, decode, encode, require
from kura_journal_export import main_peer, paired_unit
from kura_reboot_broker import (ENVIRONMENT, MAIN_UNIT, file_hash, proc_status, socket_peer, verify_alive,
                               verify_identity)

SOCKET = Path('/run/kura-command-executor.sock')
SOCKET_UNIT = 'kura-command-executor.socket'
SERVICE = 'kura-command-executor@.service'
ACTOR_HOME = Path('/usr/libexec/kura-command-executor')
CLIENT_FILE = ACTOR_HOME / 'kura_command_executor.py'
CLIENT = ('/usr/bin/python3', '-I', '-B', str(CLIENT_FILE), 'client')
ACCOUNT = 'kura'
CALLER = 'kurad'
ICMP_ACCOUNT = 'kura-icmp-probe'
ICMP_SOCKET = Path('/run/kura-icmp-probe.sock')
ICMP_SOCKET_UNIT = 'kura-icmp-probe.socket'
ICMP_SERVICE = 'kura-icmp-probe@.service'
ICMP_CLIENT = (*CLIENT[:-1], 'icmp-client')
ICMP_BINARY = Path('/usr/bin/ping')
CAP_NET_RAW = 1 << 13
READY = b'\x01'
MUTABLE_DIRECTORIES = ('user', 'data', 'packages', 'log', '.data')
SOURCES = ('bin/kura_command_executor.py', 'bin/kura_journal_export.py',
           'bin/kura_clock_broker.py', 'bin/kura_clock_journal.py', 'bin/kura_reboot_broker.py',
           'bin/kura_reboot_journal.py', 'bin/kura_reboot_protocol.py',
           f'install/{SOCKET_UNIT}', f'install/{SERVICE}',
           f'install/{ICMP_SOCKET_UNIT}', f'install/{ICMP_SERVICE}')


def package_cohort(home):
    destination = home / 'libexec/command-executor'
    destination.mkdir()
    main = home / 'install' / MAIN_UNIT
    require(main.is_file() and not main.is_symlink(), 'UNPAIRED_EXECUTOR')
    files = {}
    for source in SOURCES:
        path = home / source
        require(path.is_file() and not path.is_symlink(), 'UNPAIRED_EXECUTOR')
        shutil.copyfile(path, destination / path.name)
        files[path.name] = file_hash(path.read_bytes())
    (destination / 'cohort.json').write_bytes(encode(
        {'schema': 1, 'mainUnitSha256': file_hash(main.read_bytes()), 'files': files}) + b'\n')


def verify_actor(unit, *, account_name=ACCOUNT, socket_unit=SOCKET_UNIT, template=SERVICE, capabilities=0):
    instance = re.escape(template.removesuffix('.service'))
    require(re.fullmatch(instance + r'[A-Za-z0-9_.:\\-]{1,128}\.service', unit),
            'UNPAIRED_EXECUTOR')
    account = pwd.getpwnam(account_name)
    groups = set(os.getgroups())
    require(account.pw_uid > 0 and account.pw_gid > 0 and 0 not in groups, 'UNPAIRED_EXECUTOR')
    if account_name == ICMP_ACCOUNT:
        require(account.pw_shell == '/usr/sbin/nologin' and account.pw_dir == '/nonexistent'
                and groups <= {account.pw_gid}, 'UNPAIRED_EXECUTOR')
    status = proc_status(os.getpid())
    verify_identity(status, account.pw_uid, account.pw_gid)
    require(status['NoNewPrivs'].strip() == '1'
            and all(int(status[name], 16) == capabilities
                    for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')),
            'UNPAIRED_EXECUTOR')
    manifest = decode(public_file(ACTOR_HOME / 'cohort.json'))
    require(set(manifest) == {'schema', 'mainUnitSha256', 'files'}
            and type(manifest['schema']) is int and manifest['schema'] == 1
            and manifest['files'].keys() == {Path(source).name for source in SOURCES}
            and re.fullmatch(r'[0-9a-f]{64}', manifest['mainUnitSha256']), 'UNPAIRED_EXECUTOR')
    for name, expected in manifest['files'].items():
        require(file_hash(public_file(ACTOR_HOME / name)) == expected, 'UNPAIRED_EXECUTOR')
    paired_unit(socket_unit, socket_unit, manifest['files'][socket_unit])
    paired_unit(unit, template, manifest['files'][template])
    return manifest['mainUnitSha256']


def command_from_args(directory, *command):
    require(os.path.isabs(directory) and directory == os.path.normpath(directory)
            and len(command) > 2 and command[:2] == ('/usr/bin/env', '--'),
            'INVALID_EXECUTION')
    return directory, command


def read_command_line(pid):
    maximum = os.sysconf('SC_ARG_MAX')
    with (Path('/proc') / str(pid) / 'cmdline').open('rb') as source:
        raw = source.read(maximum + 1)
    require(0 < len(raw) <= maximum, 'INVALID_EXECUTION')
    return raw


def receive_stdio(stream, files):
    stream.settimeout(5)
    integer_size = array.array('i').itemsize
    marker, controls, flags, _ = stream.recvmsg(1, socket.CMSG_SPACE(4 * integer_size), socket.MSG_CMSG_CLOEXEC)
    for level, kind, data in controls:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            values = array.array('i')
            values.frombytes(data[:len(data) - len(data) % integer_size])
            files.extend(values)
    require(marker == READY and len(controls) == 1 and len(files) == 4
            and not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC), 'INVALID_EXECUTION_STREAMS')
    for index, file in enumerate(files[:3]):
        actual = os.fstat(file)
        mode = fcntl.fcntl(file, fcntl.F_GETFL)
        require((stat.S_ISFIFO(actual.st_mode)
                 or (stat.S_ISCHR(actual.st_mode) and (os.major(actual.st_rdev), os.minor(actual.st_rdev)) == (1, 3)))
                and not mode & os.O_PATH
                and mode & os.O_ACCMODE in ((os.O_RDONLY, os.O_RDWR) if index == 0
                                         else (os.O_WRONLY, os.O_RDWR)), 'INVALID_EXECUTION_STREAMS')
    require(stat.S_ISDIR(os.fstat(files[3]).st_mode) and fcntl.fcntl(files[3], fcntl.F_GETFL) & os.O_PATH,
            'INVALID_EXECUTION_DIRECTORY')


def enter_directory(directory, inherited):
    try:
        local = os.open(directory, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    except PermissionError:
        # Inherit private application data, never a directory outside the worker's policy.
        home = canonical_alias(HOME)
        require(any(Path(directory).is_relative_to(home / name) for name in MUTABLE_DIRECTORIES),
                'INVALID_EXECUTION_DIRECTORY')
        os.fchdir(inherited)
        return
    try:
        require(os.path.samestat(os.fstat(local), os.fstat(inherited)), 'INVALID_EXECUTION_DIRECTORY')
        os.fchdir(local)
    finally:
        os.close(local)


def execute(stream, peer, directory, command, files):
    # Prefer the local mount so getcwd() works across systemd's mount namespaces.
    enter_directory(directory, files[3])
    child = subprocess.Popen(command, stdin=files[0], stdout=files[1], stderr=files[2])
    for file in files:
        os.close(file)
    files.clear()
    wait = select.poll()
    wait.register(stream, select.POLLIN | select.POLLHUP | select.POLLERR)
    wait.register(peer[3], select.POLLIN)
    try:
        while (code := child.poll()) is None:
            require(not wait.poll(100), 'EXECUTOR_CLIENT_LOST')
        verify_alive(peer[3])
        stream.sendall(bytes([code if code >= 0 else 128 - code]))
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def serve(stream, unit):
    unit_hash = verify_actor(unit)
    files = []
    try:
        with socket_peer(stream) as peer:
            directory, command = main_peer(peer, unit_hash, CLIENT, None, command_from_args,
                                           command_line=read_command_line)
            receive_stdio(stream, files)
            require(main_peer(peer, unit_hash, CLIENT, None, command_from_args,
                              command_line=read_command_line) == (directory, command), 'UNAUTHORIZED')
            execute(stream, peer, directory, command, files)
    finally:
        for file in files:
            os.close(file)


@contextmanager
def managed_socket(path):
    metadata = path.lstat()
    caller = pwd.getpwnam(CALLER)
    require(stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == 0 and metadata.st_gid == caller.pw_gid
            and stat.S_IMODE(metadata.st_mode) == 0o660, 'UNPAIRED_EXECUTOR')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(5)
        stream.connect(str(path))
        require(struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)) == (1, 0, 0),
                'UNPAIRED_EXECUTOR')
        yield stream


def client(directory):
    require(os.getcwd() == directory, 'INVALID_EXECUTION_DIRECTORY')
    with managed_socket(SOCKET) as stream:
        working = os.open('.', os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            rights = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [0, 1, 2, working]))]
            require(stream.sendmsg([READY], rights) == 1, 'EXECUTOR_UNAVAILABLE')
        finally:
            os.close(working)
        stream.settimeout(None)
        result = stream.recv(1)
        require(len(result) == 1, 'EXECUTOR_RESULT_UNAVAILABLE')
        return result[0]


def icmp_request(family, address):
    require(family in ('-4', '-6') and 0 < len(address) <= 253, 'INVALID_ICMP_TARGET')
    if ':' in address:
        literal, zone, interface = address.partition('%')
        try:
            ipaddress.IPv6Address(literal)
        except ValueError as error:
            raise Refused('INVALID_ICMP_TARGET') from error
        require(family == '-6' and (not zone or re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', interface)),
                'INVALID_ICMP_TARGET')
    else:
        require(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', address), 'INVALID_ICMP_TARGET')
    return family, address


def serve_icmp(stream, unit):
    unit_hash = verify_actor(unit, account_name=ICMP_ACCOUNT, socket_unit=ICMP_SOCKET_UNIT,
                             template=ICMP_SERVICE, capabilities=CAP_NET_RAW)
    with socket_peer(stream) as peer:
        args = main_peer(peer, unit_hash, ICMP_CLIENT, 2, icmp_request)
        family, address = args
        protected(ICMP_BINARY)
        # Keep hostname resolution for the destination and skip reverse lookups when rendering replies.
        result = subprocess.run([str(ICMP_BINARY), family, '-n', '-c', '5', '-W', '1', '--', address],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=ENVIRONMENT, timeout=12)
        require(main_peer(peer, unit_hash, ICMP_CLIENT, 2, icmp_request) == args, 'UNAUTHORIZED')
        stream.settimeout(4)
        stream.sendall(b'\x00' if result.returncode == 0 else b'\x01')


def client_icmp(family, address):
    icmp_request(family, address)
    with managed_socket(ICMP_SOCKET) as stream:
        stream.settimeout(18)
        result = stream.recv(1)
        require(result in (b'\x00', b'\x01'), 'ICMP_RESULT_UNAVAILABLE')
        return result[0]


if __name__ == '__main__':
    try:
        args = sys.argv[1:]
        if len(args) == 2 and args[0] == 'serve':
            with socket.socket(fileno=os.dup(0)) as connection:
                serve(connection, args[1])
        elif len(args) == 2 and args[0] == 'icmp-serve':
            with socket.socket(fileno=os.dup(0)) as connection:
                serve_icmp(connection, args[1])
        elif len(args) == 3 and args[0] == 'icmp-client':
            sys.exit(client_icmp(*args[1:]))
        elif len(args) > 4 and args[0] == 'client':
            directory, _ = command_from_args(*args[1:])
            sys.exit(client(directory))
        else:
            raise Refused('INVALID_EXECUTION')
    except (Refused, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        print(error.args[0] if isinstance(error, Refused) else 'EXECUTOR_UNAVAILABLE', file=sys.stderr)
        sys.exit(1)
