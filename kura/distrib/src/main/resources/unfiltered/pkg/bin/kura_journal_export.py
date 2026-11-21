# SPDX-License-Identifier: EPL-2.0
"""Read only the local systemd journal for the authenticated Kura Main."""
import grp
import os
from pathlib import Path
import pwd
import re
import selectors
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import HOME, VENDOR_UNIT_ROOTS, protected, public_file
from kura_clock_journal import Refused, decode, encode, require
from kura_reboot_broker import (ENVIRONMENT, MAIN_CGROUP, MAIN_PROPERTIES, MAIN_UNIT,
                               UNIT_PROPERTIES, file_hash, proc_file, proc_status,
                               receive, send, socket_peer, verify_alive, verify_identity)

SOCKET = Path('/run/kura-journal-export.sock')
SOCKET_UNIT = 'kura-journal-export.socket'
ACTOR_UNIT = 'kura-journal-export@.service'
ACTOR = 'kura-journal-export'
CALLER = 'kurad'
HELPER = 'bin/kura_journal_export.py'
ACTOR_HOME = Path('/usr/libexec/kura-journal-export')
PAIR_DIRECTORY = Path('libexec/journal-export')
COHORT = 'cohort.json'
UNITS = (SOCKET_UNIT, ACTOR_UNIT)
SOURCES = (HELPER, 'bin/kura_clock_broker.py', 'bin/kura_clock_journal.py',
           'bin/kura_reboot_broker.py', 'bin/kura_reboot_journal.py', 'bin/kura_reboot_protocol.py',
           *(f'install/{name}' for name in UNITS))
FILES = tuple(Path(name).name for name in SOURCES)
CLIENT = ('/usr/bin/python3', '-I', '-B', str(HOME / HELPER), 'client')
NETWORKING_DROPIN = Path('/usr/lib/systemd/system/kura.service.d/kura-networking.conf')
NETWORKING_SHAS = frozenset((
    'eb1079ba9bc662b196ef873cfc860cc1b53ab3b50813c2ee4437352c4cd65b18',
    '06589b8dede5926f63d760ec0a94a51aa6ef6ce6ddffee1c78dfcf978ec30473',
))
MAX_DATA = 32 * 1024 * 1024
READ_TIME = 25


def package_cohort(home, *, pair_directory=PAIR_DIRECTORY, sources=SOURCES):
    destination = home / pair_directory
    destination.mkdir()
    main = home / 'install' / MAIN_UNIT
    require(main.is_file() and not main.is_symlink(), 'UNPAIRED_EXPORT')
    files = {}
    for name in sources:
        path = home / name
        require(path.is_file() and not path.is_symlink(), 'UNPAIRED_EXPORT')
        shutil.copyfile(path, destination / path.name)
        files[path.name] = file_hash(path.read_bytes())
    manifest = {'schema': 1, 'mainUnitSha256': file_hash(main.read_bytes()), 'files': files}
    (destination / COHORT).write_bytes(encode(manifest) + b'\n')


def request(scope, fields):
    require(scope in ('kura', 'system') and isinstance(fields, str) and len(fields) <= 1024,
            'INVALID_EXPORT')
    names = fields.split(',')
    require(0 < len(names) <= 32 and all(re.fullmatch(r'[A-Z_][A-Z0-9_]{0,63}', name) for name in names),
            'INVALID_EXPORT')
    return {'schema': 1, 'scope': scope, 'fields': fields}


def unit_properties(unit, names):
    output = subprocess.run(['/usr/bin/systemctl', '--system', '--no-ask-password', 'show', '--all',
                             '--property=' + ','.join(names), unit], capture_output=True,
                            check=True, timeout=4, env=ENVIRONMENT).stdout
    require(len(output) <= 8192, 'UNPAIRED_EXPORT')
    properties = {}
    for line in output.decode('ascii').splitlines():
        key, separator, value = line.partition('=')
        require(separator and key in names and key not in properties, 'UNPAIRED_EXPORT')
        properties[key] = value
    require(properties.keys() == set(names), 'UNPAIRED_EXPORT')
    return properties


def paired_unit(unit, template, template_hash, names=(), main=False):
    loaded = unit_properties(unit, UNIT_PROPERTIES + tuple(names))
    allowed_dropins = ('', str(NETWORKING_DROPIN)) if main else ('',)
    require(loaded['Id'] == unit and loaded['Names'].split() == [unit] and loaded['LoadState'] == 'loaded'
            and loaded['FragmentPath'] in {str(path / template) for path in VENDOR_UNIT_ROOTS}
            and loaded['SourcePath'] == '' and loaded['DropInPaths'] in allowed_dropins
            and loaded['NeedDaemonReload'] == loaded['Transient'] == 'no', 'UNPAIRED_EXPORT')
    require(file_hash(public_file(Path(loaded['FragmentPath']))) == template_hash, 'UNPAIRED_EXPORT')
    if loaded['DropInPaths']:
        require(file_hash(public_file(NETWORKING_DROPIN)) in NETWORKING_SHAS, 'UNPAIRED_EXPORT')
    return loaded


def verify_actor(unit):
    require(re.fullmatch(r'kura-journal-export@[A-Za-z0-9_.:\\-]{1,128}\.service', unit) is not None,
            'UNPAIRED_EXPORT')
    actor = pwd.getpwnam(ACTOR)
    journal_gid = grp.getgrnam('systemd-journal').gr_gid
    status = proc_status(os.getpid())
    groups = set(os.getgroups())
    require(actor.pw_uid > 0 and actor.pw_gid > 0 and journal_gid > 0 and os.geteuid() == actor.pw_uid
            and actor.pw_shell == '/usr/sbin/nologin' and actor.pw_dir == '/nonexistent'
            and journal_gid in groups and groups <= {actor.pw_gid, journal_gid}
            and status['NoNewPrivs'].strip() == '1'
            and all(int(status[name], 16) == 0 for name in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb')),
            'UNPAIRED_EXPORT')
    verify_identity(status, actor.pw_uid, actor.pw_gid)
    manifest = decode(public_file(ACTOR_HOME / COHORT))
    require(set(manifest) == {'schema', 'files', 'mainUnitSha256'} and type(manifest['schema']) is int
            and manifest['schema'] == 1 and manifest['files'].keys() == set(FILES)
            and re.fullmatch(r'[0-9a-f]{64}', manifest['mainUnitSha256']), 'UNPAIRED_EXPORT')
    for name, expected in manifest['files'].items():
        require(file_hash(public_file(ACTOR_HOME / name)) == expected, 'UNPAIRED_EXPORT')
    paired_unit(SOCKET_UNIT, SOCKET_UNIT, manifest['files'][SOCKET_UNIT])
    paired_unit(unit, ACTOR_UNIT, manifest['files'][ACTOR_UNIT])
    return manifest['mainUnitSha256']


def main_peer(peer, unit_sha, client_args=CLIENT, argument_count=2, decode_args=request, *, networking=None,
              command_line=None):
    pid, uid, gid, pidfd = peer
    account = pwd.getpwnam(CALLER)
    require(uid == account.pw_uid > 0 and gid == account.pw_gid > 0, 'UNAUTHORIZED')
    verify_alive(pidfd)
    names = MAIN_PROPERTIES + ('User', 'Group')
    main = paired_unit(MAIN_UNIT, MAIN_UNIT, unit_sha, names, main=True)
    parent = int(main['MainPID'])
    require(main['ActiveState'] == 'active' and main['ControlGroup'] == '/system.slice/kura.service'
            and main['User'] == main['Group'] == CALLER and parent > 1 and pid != parent
            and re.fullmatch(r'[0-9a-f]{32}', main['InvocationID']), 'UNAUTHORIZED')
    if networking is not None:
        require(main['DropInPaths'] == (str(NETWORKING_DROPIN) if networking else ''), 'UNAUTHORIZED')
    status = proc_status(pid)
    verify_identity(status, uid, gid)
    require(status['PPid'].strip() == str(parent), 'UNAUTHORIZED')
    with_parent = os.pidfd_open(parent)
    try:
        verify_alive(with_parent)
        verify_identity(proc_status(parent), uid, gid)
        for process in (pid, parent):
            require(proc_file(process, 'cgroup').splitlines() == [MAIN_CGROUP.encode()], 'UNAUTHORIZED')
        raw = (proc_file(pid, 'cmdline') if command_line is None else command_line(pid)).split(b'\0')
        require((argument_count is None or len(raw) == len(client_args) + argument_count + 1) and raw[-1] == b''
                and raw[:len(client_args)] == list(map(os.fsencode, client_args)), 'UNAUTHORIZED')
        expected = decode_args(*(arg.decode('ascii') if command_line is None else os.fsdecode(arg)
                                 for arg in raw[len(client_args):-1]))
        require(paired_unit(MAIN_UNIT, MAIN_UNIT, unit_sha, names, main=True) == main, 'UNAUTHORIZED')
        verify_alive(with_parent)
        verify_alive(pidfd)
        return expected
    finally:
        os.close(with_parent)


def read_journal(selection, output):
    command = ['/usr/bin/journalctl', '--no-pager', '--quiet', '--output=verbose',
               '--output-fields=' + selection['fields']]
    if selection['scope'] == 'kura':
        command.append('--unit=kura.service')
    protected(Path(command[0]))
    size = 0
    deadline = time.monotonic() + READ_TIME
    with subprocess.Popen(command, env=ENVIRONMENT, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as child:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    require(remaining > 0 and selector.select(remaining), 'EXPORT_TIMEOUT')
                    block = os.read(child.stdout.fileno(), 65536)
                    if not block:
                        break
                    size += len(block)
                    require(size <= MAX_DATA, 'EXPORT_TOO_LARGE')
                    output.write(block)
            require(child.wait(timeout=max(0, deadline-time.monotonic())) == 0, 'JOURNAL_UNAVAILABLE')
        finally:
            if child.poll() is None:
                child.kill()
    output.seek(0)
    return size


def serve(stream, unit):
    unit_sha = verify_actor(unit)
    with socket_peer(stream) as peer:
        expected = main_peer(peer, unit_sha)
        actual = receive(stream)
        require(type(actual.get('schema')) is int and actual == expected, 'INVALID_EXPORT')
        require(main_peer(peer, unit_sha) == expected, 'UNAUTHORIZED')
        with tempfile.TemporaryFile() as contents:
            size = read_journal(expected, contents)
            require(main_peer(peer, unit_sha) == expected, 'UNAUTHORIZED')
            stream.settimeout(5)
            stream.sendall(struct.pack('>I', size))
            while block := contents.read(65536):
                stream.sendall(block)
            stream.shutdown(socket.SHUT_WR)


def client(selection, output):
    metadata = SOCKET.lstat()
    caller = pwd.getpwnam(CALLER)
    require(stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == 0 and metadata.st_gid == caller.pw_gid
            and stat.S_IMODE(metadata.st_mode) == 0o660, 'UNPAIRED_EXPORT')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(4)
        stream.connect(str(SOCKET))
        require(struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)) == (1, 0, 0),
                'UNPAIRED_EXPORT')
        send(stream, selection)
        stream.settimeout(45)
        with stream.makefile('rb') as incoming:
            header = incoming.read(4)
            require(len(header) == 4, 'EXPORT_UNAVAILABLE')
            size, = struct.unpack('>I', header)
            require(size <= MAX_DATA, 'EXPORT_TOO_LARGE')
            while size:
                block = incoming.read(min(size, 65536))
                require(block, 'EXPORT_INCOMPLETE')
                output.write(block)
                size -= len(block)
            require(incoming.read(1) == b'', 'INVALID_EXPORT')


if __name__ == '__main__':
    try:
        args = sys.argv[1:]
        if len(args) == 2 and args[0] == 'serve':
            with socket.socket(fileno=os.dup(0)) as connection:
                serve(connection, args[1])
        elif len(args) == 3 and args[0] == 'client':
            client(request(*args[1:]), sys.stdout.buffer)
        else:
            raise Refused('INVALID_EXPORT')
    except (Refused, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        print(error.args[0] if isinstance(error, Refused) else 'EXPORT_UNAVAILABLE', file=sys.stderr)
        sys.exit(1)
