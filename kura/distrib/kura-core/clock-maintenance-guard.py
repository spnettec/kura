# SPDX-License-Identifier: EPL-2.0
"""Embedded package guard; invoke only paired installed clock code before unpack."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys

home = Path('/opt/eclipse/kura')
setup = home / 'bin/kura_clock_setup.py'
state = Path('/var/lib/kura-clock-broker')
account = Path('/etc/kura/clock-broker-account.json')


def require(value):
    if not value:
        raise RuntimeError('Unpaired or unresolved clock broker; preserve the original namespace and IDs')


def read(path, owner=0, mode=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner and before.st_nlink == 1
                and not before.st_mode & 0o022 and before.st_size <= 65536
                and (mode is None or stat.S_IMODE(before.st_mode) == mode))
        raw = os.read(fd, 65537)
        key = lambda m: (m.st_dev, m.st_ino, m.st_uid, m.st_gid, m.st_mode, m.st_nlink, m.st_size, m.st_mtime_ns, m.st_ctime_ns)
        require(len(raw) == before.st_size and key(before) == key(os.fstat(fd)) == key(path.lstat()))
        return raw
    finally:
        os.close(fd)


def check_existing_operations(journal_source):
    """Inspect the paired installed namespace without creating state or stopping units."""
    if not os.path.lexists(state):
        return
    user = pwd.getpwnam('kura-clock')
    record = json.loads(read(account, mode=0o644))
    require(record.get('schema') == 1 and type(record.get('uid')) is int
            and user.pw_uid == record['uid'] > 0 and user.pw_gid == record.get('gid'))
    namespace = {'__name__': 'kura_clock_journal'}
    exec(compile(journal_source, str(home / 'bin/kura_clock_journal.py'), 'exec'), namespace)
    journal = namespace['Journal'](state, owner=user.pw_uid)
    path = state / 'admission.lock'
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        metadata = os.fstat(fd)
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == user.pw_uid and metadata.st_nlink == 1
                and stat.S_IMODE(metadata.st_mode) == 0o600 and metadata.st_size == 0)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(os.path.samestat(metadata, path.lstat()))
        marker, operations = state / 'namespace.json', state / 'operations'
        if not os.path.lexists(marker):
            require(not os.path.lexists(operations))
            return
        namespace['directory'](operations, user.pw_uid)
        original = journal.namespace()
        for entry in operations.iterdir():
            namespace['identifier'](entry.name)
            namespace['directory'](entry, user.pw_uid)
            intent = namespace['decode'](namespace['read'](entry / 'intent.json', user.pw_uid))
            require(journal.status(original, entry.name, namespace['digest'](intent))['state'] in ('APPLIED', 'FAILED'))
    finally:
        os.close(fd)


require(sys.argv[1:] in ([], ['check']))
if os.path.lexists(setup):
    manifest = home / 'libexec/clock-broker/cohort.json'
    for path in [setup, manifest]:
        for parent in path.parents:
            value = parent.lstat()
            if parent == home and stat.S_ISLNK(value.st_mode):
                require(value.st_uid == 0)
                raw = os.readlink(parent)
                target = Path(raw) if raw.startswith('/') else parent.parent / raw
                require(target.parent == home.parent and re.fullmatch(r'kura_[A-Za-z0-9.+~_-]+_linux', target.name) is not None
                        and raw in (target.name, str(target)))
                target_metadata = target.lstat()
                require(stat.S_ISDIR(target_metadata.st_mode) and target_metadata.st_uid == 0 and not target_metadata.st_mode & 0o022)
            else:
                require(stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and not value.st_mode & 0o022)
    descriptor = json.loads(read(manifest))
    require(descriptor.get('schema') == 1 and descriptor.get('protocol') == 1)
    helpers = ('kura_clock_setup.py', 'kura_clock_broker.py', 'kura_clock_client.py', 'kura_clock_journal.py')
    if 'configure-chrony' in descriptor.get('actions', []):
        helpers += ('kura_chrony_config.py',)
    journal_source = None
    for name in helpers:
        raw = read(home / 'bin' / name)
        require(hashlib.sha256(raw).hexdigest() == descriptor['files']['bin/' + name])
        if name == 'kura_clock_journal.py':
            journal_source = raw
    if sys.argv[1:] == ['check']:
        check_existing_operations(journal_source)
    else:
        subprocess.run(['/usr/bin/python3', '-I', '-B', str(setup), 'quiesce'], check=True, timeout=30)
elif os.path.lexists(state):
    # Managed remove/purge retains its namespace and Root maintenance purpose.
    # Do not import absent code, recreate an identity or query any old operation.
    record = json.loads(read(account, mode=0o644))
    user = pwd.getpwnam('kura-clock')
    require(record.get('schema') == 1 and type(record.get('uid')) is int and record['uid'] > 0
            and user.pw_uid == record['uid'] and user.pw_gid == record.get('gid'))
    metadata = state.lstat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == user.pw_uid and stat.S_IMODE(metadata.st_mode) == 0o700)
    flag = json.loads(read(state / 'maintenance.json', mode=0o644))
    require(flag.get('schema') == 1)
    if os.path.lexists(state / 'namespace.json'):
        namespace = json.loads(read(state / 'namespace.json', user.pw_uid, 0o600))
        require(flag.get('namespace') == namespace.get('namespace'))
    else:
        require(flag.get('namespace') is None and not os.path.lexists(state / 'operations'))
    for name in ('kura-clock-broker.socket', 'kura-clock-broker.service', 'kura-clock-rtc-devices.service',
                 'kura-clock-chrony-step.socket', 'kura-clock-chrony-step.service',
                 'kura-clock-chrony-config.socket', 'kura-clock-chrony-config.service', 'kura-clock-rtc-devices.socket'):
        result = subprocess.run(['/usr/bin/systemctl', 'show', name, '--property=MainPID,ControlPID,ActiveState'],
                                capture_output=True, text=True, timeout=5)
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        require(values.get('ActiveState') in ('inactive', 'failed') and values.get('MainPID', '0') == '0'
                and values.get('ControlPID', '0') == '0')
