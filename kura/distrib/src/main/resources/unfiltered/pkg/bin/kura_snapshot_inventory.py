#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""One metadata-only observation of the Core-owned snapshot directory."""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import sys

SOCKET = '/run/kura-snapshot-inventory.sock'
INPUT = Path('/run/kura-snapshot-inventory-input')
REQUEST = b'KURA_SNAPSHOT_INVENTORY_V1\n'
MAX_FILES = 128
MAX_FILE = 32 << 20
MAX_TOTAL = 64 << 20
NAMES = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}')


def require(condition):
    if not condition:
        raise ValueError('Snapshot inventory unavailable')


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid, info.st_gid,
            info.st_size, info.st_ctime_ns, info.st_mtime_ns)


def directory(info, uid, gid):
    require(stat.S_ISDIR(info.st_mode) and (info.st_uid, info.st_gid) == (uid, gid)
            and stat.S_IMODE(info.st_mode) == 0o700)


def entries(fd):
    result = {}
    scan_fd = os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, 'O_NOATIME', 0), dir_fd=fd)
    try:
        with os.scandir(scan_fd) as scan:
            for entry in scan:
                require(len(result) < MAX_FILES + 1)
                require(entry.name == '.recovery-retained' or NAMES.fullmatch(entry.name))
                result[entry.name] = identity(entry.stat(follow_symlinks=False))
    finally:
        os.close(scan_fd)
    return result


def inventory(path, uid, gid):
    read_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | getattr(os, 'O_NOATIME', 0)
    fd = os.open(path, read_flags | os.O_DIRECTORY)
    try:
        original = os.fstat(fd)
        directory(original, uid, gid)
        initial = entries(fd)
        files = []
        total = 0
        for name, expected in sorted(initial.items()):
            if name == '.recovery-retained':
                directory(os.stat(name, dir_fd=fd, follow_symlinks=False), uid, gid)
                continue
            _, _, mode, nlink, owner, group, size, _, _ = expected
            require(len(files) < MAX_FILES and stat.S_ISREG(mode) and nlink == 1
                    and owner == uid and stat.S_IMODE(mode) == 0o600
                    and 0 <= size <= MAX_FILE and total + size <= MAX_TOTAL)
            item = os.open(name, read_flags | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(item, 'rb') as source:
                require(identity(os.fstat(item)) == expected)
                remaining = size
                digest = hashlib.sha256()
                while remaining:
                    data = source.read(min(remaining, 65536))
                    require(bool(data))
                    remaining -= len(data)
                    digest.update(data)
                require(not source.read(1) and identity(os.fstat(item)) == expected)
            files.append(dict(name=name, size=size, sha256=digest.hexdigest(),
                              metadata=dict(mode=stat.S_IMODE(mode), uid=owner, gid=group)))
            total += size
        require(entries(fd) == initial and identity(os.fstat(fd)) == identity(original)
                and identity(path.lstat()) == identity(original))
        return dict(schema=1, directory=dict(device=str(original.st_dev), inode=str(original.st_ino), mode=448,
                                            uid=uid, gid=gid),
                    retainedDirectoryPresent='.recovery-retained' in initial, files=files)
    finally:
        os.close(fd)


def serve(connection):
    connection.settimeout(2)
    pid, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    require(pid > 0 and uid == 0)
    with connection.makefile('rb') as request:
        require(request.read(len(REQUEST)+1) == REQUEST)
    raw = json.dumps(inventory(INPUT, os.geteuid(), os.getegid()), separators=(',', ':')).encode()
    require(0 < len(raw) <= 65536)
    connection.sendall(struct.pack('!I', len(raw)) + raw)


def main():
    require(os.geteuid() != 0 and os.environ.get('LISTEN_PID') == str(os.getpid())
            and os.environ.get('LISTEN_FDS') == '1')
    with socket.socket(fileno=3) as listener:
        require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM
                and listener.getsockname() == SOCKET
                and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1)
        connection, _ = listener.accept()
        with connection:
            serve(connection)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError):
        sys.stderr.write('Kura snapshot inventory unavailable\n')
        sys.exit(2)
