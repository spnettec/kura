#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Use only a registered watchdog device for the legacy maintenance handoff."""

import errno
import os
from pathlib import Path
import pwd
import re
import stat
import sys


MARKER = Path("/tmp/watchdog")
DEVICES = Path("/dev")
SYSTEM_DEVICES = Path("/sys/dev/char")
MAX_PATH_BYTES = 512
WRITES = {"pulse": b"w", "disarm": b"V"}


def identity(info):
    return info.st_dev, info.st_ino, info.st_ctime_ns, info.st_mode, info.st_rdev


def request_path(marker, owners):
    try:
        fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in owners or info.st_nlink != 1
                or info.st_mode & 0o022 or not 0 < info.st_size <= MAX_PATH_BYTES):
            raise ValueError("Unsafe watchdog handoff marker")
        raw = stream.read(MAX_PATH_BYTES + 1)
        if (len(raw) != info.st_size or identity(info) != identity(os.fstat(stream.fileno()))
                or identity(info) != identity(marker.lstat())):
            raise ValueError("Watchdog handoff marker changed")
    path = raw.decode("ascii")
    parts = path.split("/")
    if parts[:2] != ["", "dev"] or len(parts) < 3 or any(
            part in (".", "..") or re.fullmatch(r"[A-Za-z0-9_.-]+", part) is None for part in parts[2:]):
        raise ValueError("Invalid watchdog device name")
    return Path(path)


def registered_watchdog(number, system_devices):
    major, minor = os.major(number), os.minor(number)
    row = system_devices / f"{major}:{minor}"
    if (row / "dev").read_text(encoding="ascii").strip() != f"{major}:{minor}":
        return False
    target = row.resolve(strict=True)
    subsystem = (target / "subsystem").resolve(strict=True)
    if subsystem == Path("/sys/class/watchdog"):
        return re.fullmatch(r"watchdog[0-9]+", target.name) is not None
    return (major, minor) == (10, 130) and target.name == "watchdog" and subsystem == Path("/sys/class/misc")


def verified_device(request, devices, system_devices):
    device = request.resolve(strict=True)
    if not device.is_relative_to(devices):
        raise ValueError("Watchdog device escaped /dev")
    for parent in device.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Unsafe watchdog device directory")
    info = device.lstat()
    if (not stat.S_ISCHR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o002
            or not registered_watchdog(info.st_rdev, system_devices)):
        raise ValueError("Unregistered watchdog device")
    return device, info


def maintain(action, *, marker=MARKER, devices=DEVICES, system_devices=SYSTEM_DEVICES):
    if action != "check" and action not in WRITES:
        raise ValueError("Unsupported watchdog action")
    owners = {0}
    try:
        owners.add(pwd.getpwnam("kurad").pw_uid)
    except KeyError:
        pass
    request = request_path(marker, owners)
    if request is None:
        return
    path, info = verified_device(request, devices, system_devices)
    if action == "check":
        return
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as error:
        if error.errno != errno.EBUSY:
            raise
        # A driver that is already held has its original supervisor.
        return
    try:
        if identity(info) != identity(os.fstat(fd)):
            raise ValueError("Watchdog device changed before maintenance")
        if os.write(fd, WRITES[action]) != 1:
            raise OSError("Incomplete watchdog maintenance write")
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("Expected one watchdog maintenance action")
        maintain(sys.argv[1])
    except (OSError, ValueError):
        # The legacy marker is data from an unprivileged service.
        print("Kura watchdog maintenance refused; check the installed watchdog device.", file=sys.stderr)
        sys.exit(1)
