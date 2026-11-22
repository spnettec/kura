# SPDX-License-Identifier: EPL-2.0
"""Retire the exact direct network grants installed by historical Kura packages."""
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import NamedTuple

XML_FILES = (
    Path('/etc/dbus-1/system.d/wpa_supplicant.conf'),
    Path('/usr/share/dbus-1/system.d/wpa_supplicant.conf'),
)
PKLA = Path('/etc/polkit-1/localauthority/50-local.d/54-fi.w1.wpa_supplicant1.pkla')
PKLA_GRANT = b'''[No password prompt for kurad user when using Wpa Supplicant]
Identity=unix-user:kurad
Action=fi.w1.wpa_supplicant1.*
ResultInactive=no
ResultActive=no
ResultAny=yes
'''
MODEM_PKLA = Path('/etc/polkit-1/localauthority/50-local.d/53-org.freedesktop.modemmanager.pkla')
MODEM_PKLA_GRANT = b'''[No password prompt for kurad user when using ModemManager]
Identity=unix-user:kurad
Action=org.freedesktop.ModemManager1.*
ResultInactive=no
ResultActive=no
ResultAny=yes
'''
XML_GRANT = b'''    <policy user="kurad">
        <allow own="fi.w1.wpa_supplicant1"/>
        <allow send_destination="fi.w1.wpa_supplicant1"/>
        <allow send_interface="fi.w1.wpa_supplicant1"/>
        <allow receive_sender="fi.w1.wpa_supplicant1" receive_type="signal"/>
    </policy>

'''
SYSTEM_BUS = Path('/run/dbus/system_bus_socket')
LIMIT = 128 * 1024


class Policy(NamedTuple):
    data: bytes
    identity: tuple
    mode: int
    xattrs: tuple


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(value):
    return (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
            value.st_nlink, value.st_size, value.st_ctime_ns, value.st_mtime_ns)


def read(path):
    for parent in reversed(path.parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            return None
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                f'Unsafe parent of network policy {path}')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOATIME | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == before.st_gid == 0
                and before.st_nlink == 1 and not before.st_mode & 0o7022 and before.st_size <= LIMIT,
                f'Unsafe network policy file {path}')
        data = stream.read(LIMIT + 1)
        attrs = tuple((key, os.getxattr(fd, key)) for key in sorted(os.listxattr(fd)))
        original = identity(before)
        require(len(data) == before.st_size and original == identity(os.fstat(fd)) == identity(path.lstat()),
                f'Network policy changed while reading {path}')
        return Policy(data, original, stat.S_IMODE(before.st_mode), attrs)


def historical_xml(data):
    # Both old scripts required no kurad match and used the same awk insertion.
    if b'kurad' in data:
        return None
    lines = data.removesuffix(b'\n').split(b'\n')
    for i, line in enumerate(lines):
        if line.startswith(b'</busconfig>'):
            return b''.join(row + b'\n' for row in lines[:i]) + XML_GRANT + b'\n'.join(lines[i:]) + b'\n'
    return None


def plan_xml(path):
    current = read(path)
    if current is None:
        return None, False
    needs_pairing = XML_GRANT in current.data
    paired = []
    settled = False
    for suffix in ('.save', '.kurasave'):
        backup_path = path.with_name(path.name + suffix)
        try:
            backup = read(backup_path)
        except (OSError, ValueError):
            if needs_pairing:
                raise
            continue
        if backup is None:
            continue
        original_patched = historical_xml(backup.data)
        if original_patched is None:
            continue
        if current.data == backup.data:
            settled = True
        if current.data == original_patched:
            paired.append((backup_path, backup))
    if not needs_pairing:
        return None, settled
    require(paired and all((backup.data, backup.mode, backup.xattrs) ==
                           (paired[0][1].data, paired[0][1].mode, paired[0][1].xattrs)
                           for _, backup in paired), f'WPA grant lacks an exact original backup: {path}')
    return (path, current, tuple(paired)), True


def sync_parent(path):
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def restore_xml(path, current, paired):
    source = paired[0][1]
    fd, temporary = tempfile.mkstemp(prefix='.kura-wpa-policy-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), 0, 0)
            os.fchmod(stream.fileno(), source.mode)
            stream.write(source.data)
            stream.flush()
            for key, value in source.xattrs:
                os.setxattr(stream.fileno(), key, value)
            os.fsync(stream.fileno())
        require(read(path) == current and all(read(name) == value for name, value in paired),
                f'WPA policy or original backup changed: {path}')
        os.replace(temporary, path)
        sync_parent(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def plan_pkla(path, historical, namespace):
    policy = read(path)
    if policy is None:
        return None
    if policy.data == historical:
        return path, policy
    require(b'unix-user:kurad' not in policy.data or namespace not in policy.data,
            f'{path.name} is not the historical Kura grant')
    return None


def settle(action):
    work = [plan_xml(path) for path in XML_FILES]
    pkla = [plan_pkla(PKLA, PKLA_GRANT, b'fi.w1.wpa_supplicant1.'),
            plan_pkla(MODEM_PKLA, MODEM_PKLA_GRANT, b'org.freedesktop.ModemManager1.')]
    if action == 'check':
        return
    for change, _ in work:
        if change:
            restore_xml(*change)
    for path, policy in filter(None, pkla):
        require(read(path) == policy, f'{path.name} changed before retirement')
        path.unlink()
        sync_parent(path)
    # Reload even if publication was completed by an interrupted installer.
    if any(reload_needed for _, reload_needed in work) and os.path.lexists(SYSTEM_BUS):
        require(stat.S_ISSOCK(SYSTEM_BUS.lstat().st_mode), 'Unpaired system D-Bus socket')
        subprocess.run(['/usr/bin/busctl', '--system', '--timeout=5s', 'call', 'org.freedesktop.DBus',
                        '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ReloadConfig'],
                       env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, check=True, timeout=8,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    try:
        require(os.getuid() == os.geteuid() == 0 and sys.argv[1:] in (['check'], ['apply'])
                and os.environ.get('DPKG_ROOT', '') in ('', '/')
                and os.environ.get('DPKG_ADMINDIR', '/var/lib/dpkg') == '/var/lib/dpkg',
                'Network policy maintenance requires the canonical package Root')
        settle(sys.argv[1])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        sys.exit('Cannot retire the historical network policy: ' + str(exc))
