#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fixed Main projection and single invocation for a staged Core recovery input."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = '/var/lib/kura-recovery-launch'
SELECTOR = 'KURA_CONTROLLED_RECOVERY_ID'
BOOTSTRAP = 'libexec/key-recovery/kura-offline-recovery.jar'
SNAPSHOT = 'snapshot_0.xml'
REQUEST = 'request.properties'
PLAN = 'plan.json'
OUT = 'result'
CLAIM = 'launch.json'
SELECTION = 'selection.json'
CONDITION = 'condition.json'
RECEIPT = 'applied.properties'
MAX_SNAPSHOT = 32 << 20
IDENTITY = re.compile(r'rec-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
SHA = re.compile(r'[0-9a-f]{64}')


def require(condition):
    if not condition:
        raise ValueError('Invalid controlled recovery launch profile')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def root_identity(path):
    info = path.stat()
    return dict(device=str(info.st_dev), inode=str(info.st_ino))


def properties(path, plan):
    values = {
        'schema': '1',
        'restore.id': plan['restoreId'],
        'snapshot.path': str(path / SNAPSHOT),
        'snapshot.sha256': plan['snapshotSha256'],
        'snapshot.mode': plan['mode'],
        'password.policy': plan['passwordPolicy'],
        'receipt.path': str(path / OUT / RECEIPT),
        'crypto.systemd.credentials': 'true',
        'crypto.key.sha256': plan['activeKeySha256'],
        'crypto.ring.sha256': plan['ringSha256'] or 'none',
    }
    return ''.join(key + '=' + value + '\n' for key, value in sorted(values.items())).encode('ascii')


def directory(path, uid, gid, mode):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (uid, gid, mode))


def read(path, uid, gid, mode, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as file:
        before = os.fstat(file.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and (before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode)) == (uid, gid, mode)
                and 0 < before.st_size <= limit)
        value = file.read(limit + 1)
        after = path.lstat()
        require(len(value) == before.st_size and os.path.samestat(before, after)
                and (before.st_ctime_ns, before.st_mtime_ns) == (after.st_ctime_ns, after.st_mtime_ns))
        return value


def projection(base, identity, uid, gid, root):
    require(IDENTITY.fullmatch(identity) is not None)
    directory(base, 0, gid, 0o750)
    path = base / identity
    directory(path, 0, gid, 0o750)
    directory(path / OUT, uid, gid, 0o700)
    raw = read(path / PLAN, 0, gid, 0o440, 8192)
    plan = json.loads(raw)
    keys = {'schema', 'root', 'restoreId', 'bindingSha256', 'activeKeySha256', 'ringSha256', 'cohortSha256',
            'snapshotSha256', 'size', 'mode', 'passwordPolicy', 'bootstrapSha256'}
    require(isinstance(plan, dict) and set(plan) == keys and canonical(plan) == raw
            and type(plan['schema']) is int and plan['schema'] == 1
            and plan['root'] == root_identity(root) and plan['restoreId'] == identity
            and plan['mode'] in ('plain', 'aes-gcm')
            and plan['passwordPolicy'] in ('authenticated', 'legacy', 'logical-v1')
            and type(plan['size']) is int and 0 < plan['size'] <= MAX_SNAPSHOT)
    for key in ('bindingSha256', 'activeKeySha256', 'cohortSha256', 'snapshotSha256', 'bootstrapSha256'):
        require(isinstance(plan[key], str) and SHA.fullmatch(plan[key]))
    require(plan['ringSha256'] is None or isinstance(plan['ringSha256'], str) and SHA.fullmatch(plan['ringSha256']))
    request = read(path / REQUEST, 0, gid, 0o440, 4096)
    require(request == properties(path, plan))
    snapshot = read(path / SNAPSHOT, 0, gid, 0o440, MAX_SNAPSHOT)
    require(len(snapshot) == plan['size'] and digest(snapshot) == plan['snapshotSha256'])
    return path, plan


def boot_identity():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def selection(base, gid, root):
    if not os.path.lexists(base):
        return None
    directory(base, 0, gid, 0o750)
    path = base / SELECTION
    if not os.path.lexists(path):
        return None
    raw = read(path, 0, gid, 0o440, 4096)
    value = json.loads(raw)
    require(isinstance(value, dict) and set(value) == {'schema', 'root', 'restoreId', 'planSha256', 'bootId'}
            and canonical(value) == raw and type(value['schema']) is int and value['schema'] == 1
            and value['root'] == root_identity(root)
            and isinstance(value['restoreId'], str) and IDENTITY.fullmatch(value['restoreId'])
            and isinstance(value['planSha256'], str) and SHA.fullmatch(value['planSha256'])
            and isinstance(value['bootId'], str) and IDENTITY.fullmatch('rec-' + value['bootId']))
    return value


def unit_invocation():
    require(os.geteuid() != 0 and os.geteuid() == os.getuid() and os.getegid() == os.getgid())
    require(Path('/proc/self/cgroup').read_text().strip() == '0::/system.slice/kura.service')
    invocation = os.environ.get('INVOCATION_ID', '')
    require(re.fullmatch('[0-9a-f]{32}', invocation) is not None)
    return invocation


def select_projection(home, identity, fixed):
    require(not any(os.environ.get(name) for name in
                    ('KURA_JVM_ARGS_FILE', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'JAVA_TOOL_OPTIONS')))
    path, plan = projection(Path(ROOT), identity, os.getuid(), os.getgid(), Path('/'))
    jar = home / BOOTSTRAP
    require(digest(jar.read_bytes()) == plan['bootstrapSha256'])
    if fixed is not None:
        require(fixed['bootId'] == boot_identity() and fixed['planSha256'] == digest(canonical(plan)))
    return path, plan


def condition(home):
    fixed = selection(Path(ROOT), os.getgid(), Path('/'))
    if fixed is None:
        return
    require(SELECTOR not in os.environ)
    invocation = unit_invocation()
    path, _ = select_projection(home, fixed['restoreId'], fixed)
    output = path / OUT
    require(not any(output.iterdir()))
    marker = dict(schema=1, selectionSha256=digest(canonical(fixed)), invocationId=invocation)
    write(output / CONDITION, canonical(marker), 0o600)
    sync(output)


def selected(home):
    identity = os.environ.get(SELECTOR)
    fixed = selection(Path(ROOT), os.getgid(), Path('/'))
    if identity is None and fixed is None:
        return None
    invocation = unit_invocation()
    if fixed is not None:
        require(identity is None)
        identity = fixed['restoreId']
    path, plan = select_projection(home, identity, fixed)
    output = path / OUT
    expected = {CONDITION} if fixed is not None else set()
    require({item.name for item in output.iterdir()} == expected)
    if fixed is not None:
        marker = dict(schema=1, selectionSha256=digest(canonical(fixed)), invocationId=invocation)
        require(read(output / CONDITION, os.getuid(), os.getgid(), 0o600, 4096) == canonical(marker))
    return path, plan


def sync(directory_path):
    fd = os.open(directory_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write(path, contents, mode, group=None):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
    with os.fdopen(fd, 'wb') as file:
        if group is not None:
            os.fchown(file.fileno(), 0, group)
        os.fchmod(file.fileno(), mode)
        file.write(contents)
        file.flush()
        os.fsync(file.fileno())


def claim(path, plan, lease):
    require((lease['keySha256'], lease['ringSha256'], lease['cohortSha256'])
            == (plan['activeKeySha256'], plan['ringSha256'], plan['cohortSha256']))
    value = dict(schema=1, state='MAIN_LAUNCH_CLAIMED', restoreId=plan['restoreId'],
                 planSha256=digest(canonical(plan)), pid=os.getpid(),
                 startTicks=lease['startTicks'], invocationId=os.environ['INVOCATION_ID'],
                 bootId=boot_identity())
    write(path / OUT / CLAIM, canonical(value), 0o600)
    sync(path / OUT)


if __name__ == '__main__':
    try:
        require(sys.argv[1:] == ['condition'])
        condition(Path(__file__).resolve().parents[1])
    except (OSError, ValueError, TypeError, KeyError):
        print('Controlled recovery selection is already used, stale, or invalid', file=sys.stderr)
        sys.exit(1)
