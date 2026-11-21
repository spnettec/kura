#!/usr/bin/python3
# SPDX-License-Identifier: EPL-2.0
"""Prepare the historical PID file for the packaged, unprivileged Main."""
import os
import pwd
import re
import stat
import sys


def prepare_pid(run, account):
    parent = os.fstat(run)
    if parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError("Untrusted runtime directory")
    name = "kura.pid"
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=run)
    except FileExistsError:
        info = os.stat(name, dir_fd=run, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Expected a regular, single-link PID file")
        owner = (info.st_uid, info.st_gid)
        if owner == (account.pw_uid, account.pw_gid):
            return
        if owner != (0, 0) or stat.S_IMODE(info.st_mode) not in (0o600, 0o640, 0o644):
            raise ValueError("Unrecognized legacy PID file")
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=run)
        try:
            if os.fstat(fd) != info:
                raise ValueError("Legacy PID file changed")
            check_stale(fd, info)
            os.fchmod(fd, 0o600)
            os.fchown(fd, account.pw_uid, account.pw_gid)
        finally:
            os.close(fd)
    else:
        try:
            os.fchown(fd, account.pw_uid, account.pw_gid)
        finally:
            os.close(fd)


def check_stale(fd, info):
    # An interruption between creation and chown leaves this private file empty.
    if info.st_size == 0 and stat.S_IMODE(info.st_mode) == 0o600:
        return
    raw = os.read(fd, 32)
    if not re.fullmatch(rb"[1-9][0-9]{0,9}\n", raw) or len(raw) != info.st_size:
        raise ValueError("Unrecognized legacy PID record")
    pid = int(raw)
    if not 1 < pid <= 2**31 - 1:
        raise ValueError("Invalid legacy PID")
    try:
        process = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    os.close(process)
    raise ValueError("Recorded process is still alive")


if __name__ == "__main__":
    try:
        account = pwd.getpwnam("kurad")
        if len(sys.argv) != 1 or os.geteuid() != 0 or not account.pw_uid or not account.pw_gid:
            raise ValueError("Invalid PID preparation identity")
        run = os.open("/run", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            prepare_pid(run, account)
        finally:
            os.close(run)
    except (OSError, KeyError, ValueError) as error:
        sys.exit("Cannot prepare Kura PID file: " + str(error))
