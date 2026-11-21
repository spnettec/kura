# SPDX-License-Identifier: EPL-2.0
"""Observe the two system ownership markers for the installed Kura Main."""
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import public_file
from kura_clock_journal import Refused, decode, require
from kura_journal_export import package_cohort as build_cohort, paired_unit
from kura_reboot_broker import (MAIN_CGROUP, MAIN_PROPERTIES, MAIN_UNIT, file_hash, proc_file,
                               proc_status, socket_peer, verify_alive, verify_identity)

SOCKET = '/run/kura-ownership-markers.sock'
SOCKET_UNIT = 'kura-ownership-markers.socket'
SERVICE = 'kura-ownership-markers.service'
HOME = Path('/usr/libexec/kura-ownership-markers')
DIRECTORY = Path('/etc/kura')
MARKERS = {b'F': 'firewall-owner-agent', b'N': 'network-owner-agent'}
SOURCES = ('bin/kura_ownership_markers.py', 'bin/kura_journal_export.py', 'bin/kura_clock_broker.py',
           'bin/kura_clock_journal.py', 'bin/kura_reboot_broker.py', 'bin/kura_reboot_journal.py',
           'bin/kura_reboot_protocol.py', f'install/{SOCKET_UNIT}', f'install/{SERVICE}')


def package_cohort(home):
    build_cohort(home, pair_directory=Path('libexec/ownership-markers'), sources=SOURCES)


def verify_actor():
    status = proc_status(os.getpid())
    verify_identity(status, 0, 0)
    require(status['NoNewPrivs'].strip() == '1' and all(int(status[name], 16) == 0
            for name in ('CapPrm', 'CapEff', 'CapBnd', 'CapAmb', 'CapInh')), 'UNPAIRED_READER')
    manifest = decode(public_file(HOME / 'cohort.json'))
    require(set(manifest) == {'schema', 'mainUnitSha256', 'files'} and type(manifest['schema']) is int
            and manifest['schema'] == 1 and re.fullmatch('[0-9a-f]{64}', manifest['mainUnitSha256'])
            and set(manifest['files']) == {Path(name).name for name in SOURCES}, 'UNPAIRED_READER')
    for name, expected in manifest['files'].items():
        require(file_hash(public_file(HOME / name)) == expected, 'UNPAIRED_READER')
    for unit in (SOCKET_UNIT, SERVICE):
        paired_unit(unit, unit, manifest['files'][unit])
    return manifest['mainUnitSha256']


def verify_main(peer, main_sha):
    pid, uid, gid, pidfd = peer
    caller = pwd.getpwnam('kurad')
    require(uid == caller.pw_uid > 0 and gid == caller.pw_gid > 0, 'UNAUTHORIZED')
    verify_alive(pidfd)
    main = paired_unit(MAIN_UNIT, MAIN_UNIT, main_sha, MAIN_PROPERTIES + ('User', 'Group'), main=True)
    require(main['MainPID'] == str(pid) and main['ActiveState'] == 'active'
            and main['User'] == main['Group'] == 'kurad' and main['ControlGroup'] == '/system.slice/kura.service'
            and re.fullmatch('[0-9a-f]{32}', main['InvocationID']), 'UNAUTHORIZED')
    verify_identity(proc_status(pid), uid, gid)
    require(proc_file(pid, 'cgroup').splitlines() == [MAIN_CGROUP.encode()], 'UNAUTHORIZED')
    verify_alive(pidfd)


def observe(kind, directory=DIRECTORY):
    require(kind in MARKERS, 'INVALID_REQUEST')
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        original = os.fstat(fd)
        require(original.st_uid == 0 and not original.st_mode & 0o022, 'UNSAFE_DIRECTORY')
        try:
            os.stat(MARKERS[kind], dir_fd=fd, follow_symlinks=False)
            result = b'1'
        except FileNotFoundError:
            result = b'0'
        current = directory.lstat()
        require(os.path.samestat(original, current) and stat.S_ISDIR(current.st_mode)
                and current.st_uid == 0 and not current.st_mode & 0o022, 'UNSAFE_DIRECTORY')
        return result
    finally:
        os.close(fd)


def serve():
    require(os.environ.get('LISTEN_PID') == str(os.getpid()) and os.environ.get('LISTEN_FDS') == '1',
            'UNPAIRED_READER')
    with socket.socket(fileno=3) as listener:
        require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM
                and listener.getsockname() == SOCKET and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN),
                'UNPAIRED_READER')
        main_sha = verify_actor()
        while True:
            stream, _ = listener.accept()
            with stream:
                try:
                    stream.settimeout(2)
                    with socket_peer(stream) as peer:
                        kind = stream.recv(1)
                        require(kind in MARKERS and stream.recv(1) == b'', 'INVALID_REQUEST')
                        verify_main(peer, main_sha)
                        result = observe(kind)
                        verify_alive(peer[3])
                        stream.sendall(result)
                except (OSError, KeyError, ValueError, Refused, subprocess.SubprocessError):
                    continue  # Empty response is indeterminate, including for a missing parent.


if __name__ == '__main__':
    serve()
