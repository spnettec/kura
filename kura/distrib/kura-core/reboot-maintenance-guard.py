# SPDX-License-Identifier: EPL-2.0
"""Embedded dpkg guard. Run only the paired installed broker's lifecycle helper."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import uuid

home = Path('/opt/eclipse/kura')
etc = Path('/etc/kura')
seal = etc / 'reboot-broker-installation.json'
authority = etc / 'reboot-broker-authority.json'
state = Path('/var/lib/kura-reboot-broker')
sender = Path('/var/lib/kura-reboot-sender')
units = ('kura-reboot-broker.service', 'kura-reboot-broker.socket')
vendor = Path('/usr/lib/systemd/system')
setup = home / 'bin/kura_reboot_setup.py'


def require(condition):
    if not condition:
        raise RuntimeError('Unpaired reboot broker state; preserve the original authority and requests')


def identity(value):
    return (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def secure_parents(path):
    for parent in path.parents:
        info = parent.lstat()
        if parent == home and stat.S_ISLNK(info.st_mode):
            alias = os.readlink(parent)
            target = parent.parent / alias
            require(info.st_uid == 0 and target.parent == home.parent
                    and re.fullmatch(r'kura_[A-Za-z0-9.+~_-]+_linux', target.name)
                    and alias in (str(target), target.name))
            info = target.lstat()
        if parent == sender:
            require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700)
            continue  # The still Root-owned binding file sits in the Main-owned leaf.
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022)


def read(path, mode=None):
    secure_parents(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and not info.st_mode & 0o022 and 0 < info.st_size <= 65536
                and (mode is None or stat.S_IMODE(info.st_mode) == mode))
        with os.fdopen(os.dup(fd), 'rb') as stream:
            data = stream.read(65537)
        require(len(data) == info.st_size and identity(info) == identity(os.fstat(fd)) == identity(path.lstat()))
        return data
    finally:
        os.close(fd)


manager = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
if os.path.lexists(setup):
    manifest = json.loads(read(home / 'libexec/reboot-broker/cohort.json'))
    require(manifest.get('schema') == 1 and manifest.get('action') == 'reboot' and manifest.get('caller') == 'kurad')
    for stem in ('clock_broker', 'clock_journal', 'reboot_broker', 'reboot_journal', 'reboot_protocol', 'reboot_setup'):
        name = 'bin/kura_' + stem + '.py'
        require(hashlib.sha256(read(home / name)).hexdigest() == manifest['files'][name])
    subprocess.run(['/usr/bin/python3', '-I', '-B', str(setup), 'quiesce'], env=manager, timeout=40, check=True)
elif any(os.path.lexists(path) for path in (seal, authority, state, sender, *(vendor / unit for unit in units))):
    raw = read(seal, 0o600)
    binding = json.loads(raw)
    user = pwd.getpwnam('kurad')
    require(set(binding) == {'schema', 'namespace', 'callerUid', 'callerGid'}
            and type(binding['schema']) is int and binding['schema'] == 1
            and user.pw_uid == binding['callerUid'] > 0 and user.pw_gid == binding['callerGid'] > 0)
    namespace = binding['namespace']
    require(str(uuid.UUID(namespace)) == namespace)
    require(raw == read(authority, 0o644) == read(sender / 'binding.json', 0o644))
    owner = sender.lstat()
    require(stat.S_ISDIR(owner.st_mode) and stat.S_IMODE(owner.st_mode) == 0o700
            and owner.st_uid == user.pw_uid and owner.st_gid == user.pw_gid)
    marker = json.loads(read(state / 'namespace.json', 0o600))
    require(marker == dict(schema=1, namespace=namespace, purpose='kura-host-reboot-v1'))
    fence = json.loads(read(state / 'maintenance.json', 0o600))
    require(fence.get('schema') == 1 and fence.get('namespace') == namespace and set(fence.get('units', ())) == set(units))
    for name in units:
        require(not os.path.lexists(vendor / name))
        result = subprocess.run(['/usr/bin/systemctl', '--system', 'show',
                                 '--property=ActiveState,ControlPID,MainPID,LoadState', name],
                                env=manager, capture_output=True, text=True, timeout=5)
        props = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        require(props.get('LoadState') == 'not-found' and props.get('ActiveState') == 'inactive'
                and props.get('ControlPID', '0') == props.get('MainPID', '0') == '0')
