#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fixed Main projection and single invocation for a staged Core recovery input."""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
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
GUARDED = 'guarded'
NORMAL_RECEIPT = 'normal.properties'
NORMAL_SNAPSHOTS = '/opt/eclipse/kura/user/snapshots'
SNAPSHOT_ID = re.compile(r'0|[1-9][0-9]{0,18}')
MAX_SNAPSHOT = 32 << 20
READER_SOCKET = '/run/kura-recovery-main-reader.sock'
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


def guarded_properties(path, plan):
    source = path.parent / OUT / RECEIPT
    guard = plan['guarded']
    values = dict(line.split('=', 1) for line in properties(path, plan).decode('ascii').splitlines())
    values.update({
        'snapshot.path': str(Path(NORMAL_SNAPSHOTS) / ('snapshot_' + guard['snapshotId'] + '.xml')),
        'receipt.path': str(path / OUT / NORMAL_RECEIPT),
        'verification.mode': 'normal-read-only',
        'verification.source.receipt': str(source),
        'verification.source.receipt.sha256': guard['sourceReceiptSha256'],
        'verification.source.applied.sha256': guard['sourceAppliedSha256'],
    })
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


def inspect_projection(path, plan, uid, gid):
    identity = plan['restoreId']
    plan_sha = digest(canonical(plan))
    output = path / OUT
    result = dict(schema=1, restoreId=identity, root=plan['root'], planSha256=plan_sha,
                  state='MAIN_LAUNCH_PREPARED')
    if not os.path.lexists(output / CLAIM):
        entries = {entry.name for entry in output.iterdir()}
        require(entries in (set(), {CONDITION}))
        if entries:
            result['state'] = 'MAIN_LAUNCH_CONDITIONED'
        return result
    claim = json.loads(read(output / CLAIM, uid, gid, 0o600, 4096))
    require(isinstance(claim, dict)
            and set(claim) == {'schema', 'state', 'restoreId', 'planSha256', 'pid', 'startTicks', 'invocationId', 'bootId'}
            and type(claim['schema']) is int and claim['schema'] == 1
            and claim['state'] == 'MAIN_LAUNCH_CLAIMED' and claim['restoreId'] == identity
            and claim['planSha256'] == plan_sha and type(claim['pid']) is int and claim['pid'] > 1
            and isinstance(claim['startTicks'], str) and re.fullmatch('[0-9]{1,20}', claim['startTicks'])
            and isinstance(claim['invocationId'], str) and re.fullmatch('[0-9a-f]{32}', claim['invocationId'])
            and isinstance(claim['bootId'], str) and IDENTITY.fullmatch('rec-' + claim['bootId']))
    result.update(state=claim['state'], invocation=claim)
    filename = NORMAL_RECEIPT if 'guarded' in plan else RECEIPT
    if os.path.lexists(output / filename):
        raw, receipt = decision(output / filename, identity, uid, gid)
        status = receipt.get('status')
        success = 'NORMAL_BOOT_ADMITTED' if 'guarded' in plan else 'CM_APPLIED'
        require(status in (success, 'RECOVERY_REQUIRED'))
        if status == 'CM_APPLIED':
            require(receipt.get('snapshot.sha256') == plan['snapshotSha256'])
            for name in ('backup', 'applied'):
                artifact = output / (RECEIPT + f'.cm-{name}.aes')
                require(digest(read(artifact, uid, gid, 0o600, 64 << 20)) == receipt.get(name + '.sha256'))
        elif status == 'NORMAL_BOOT_ADMITTED':
            guard = plan['guarded']
            observed = output / (NORMAL_RECEIPT + '.cm-observed.aes')
            require(receipt.get('snapshot.sha256') == plan['snapshotSha256']
                    and receipt.get('source.receipt.sha256') == guard['sourceReceiptSha256']
                    and receipt.get('source.applied.sha256') == guard['sourceAppliedSha256']
                    and digest(read(observed, uid, gid, 0o600, MAX_SNAPSHOT)) == receipt.get('observed.sha256'))
        result.update(state=status, receiptSha256=digest(raw))
    return result


def decision(path, identity, uid, gid):
    raw = read(path, uid, gid, 0o600, 65536)
    lines = [line.split('=', 1) for line in raw.decode('utf-8').splitlines()]
    record = dict(lines)
    require(len(lines) == len(record) and record.get('schema') == '1'
            and record.get('restore.id') == identity)
    return raw, record


def snapshot_number(value):
    require(isinstance(value, str) and SNAPSHOT_ID.fullmatch(value) and int(value) <= (1 << 63) - 1)
    return int(value)


def normal_snapshot(root, plan, uid, gid):
    parent = root / NORMAL_SNAPSHOTS.lstrip('/')
    directory(parent, uid, gid, 0o700)
    snapshot_id = plan['guarded']['snapshotId']
    expected = snapshot_number(snapshot_id)
    for item in parent.glob('snapshot_*.xml'):
        require(snapshot_number(item.name[9:-4]) <= expected)
    contents = read(parent / ('snapshot_' + snapshot_id + '.xml'), uid, gid, 0o600, MAX_SNAPSHOT)
    require(len(contents) == plan['size'] and digest(contents) == plan['snapshotSha256'])


def guarded_projection(path, plan, fixed, uid, gid):
    target = path / GUARDED
    directory(target, 0, gid, 0o750)
    directory(target / OUT, uid, gid, 0o700)
    raw = read(target / PLAN, 0, gid, 0o440, 8192)
    normal = json.loads(raw)
    require(isinstance(normal, dict) and canonical(normal) == raw
            and set(normal) == set(plan) | {'guarded'} and all(normal[key] == plan[key] for key in plan))
    guard = normal['guarded']
    require(isinstance(guard, dict)
            and set(guard) == {'snapshotId', 'selectionSha256', 'sourceReceiptSha256', 'sourceAppliedSha256'}
            and guard['selectionSha256'] == digest(canonical(fixed)))
    snapshot_number(guard['snapshotId'])
    applied = inspect_projection(path, plan, uid, gid)
    source_raw, source = decision(path / OUT / RECEIPT, plan['restoreId'], uid, gid)
    require(applied['state'] == 'CM_APPLIED' and source.get('status') == 'CM_APPLIED'
            and applied['receiptSha256'] == guard['sourceReceiptSha256'] == digest(source_raw)
            and source.get('applied.sha256') == guard['sourceAppliedSha256'])
    require(read(target / REQUEST, 0, gid, 0o440, 4096) == guarded_properties(target, normal))
    return target, normal


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
        if os.path.lexists(path / GUARDED):
            path, plan = guarded_projection(path, plan, fixed, os.getuid(), os.getgid())
            normal_snapshot(Path('/'), plan, os.getuid(), os.getgid())
    return path, plan


def condition_marker(fixed, plan, invocation):
    result = dict(schema=1, selectionSha256=digest(canonical(fixed)), invocationId=invocation)
    if 'guarded' in plan:
        result['guardedSha256'] = digest(canonical(plan))
    return result


def condition(home):
    fixed = selection(Path(ROOT), os.getgid(), Path('/'))
    if fixed is None:
        return
    require(SELECTOR not in os.environ)
    invocation = unit_invocation()
    path, plan = select_projection(home, fixed['restoreId'], fixed)
    output = path / OUT
    require(not any(output.iterdir()))
    marker = condition_marker(fixed, plan, invocation)
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
        marker = condition_marker(fixed, plan, invocation)
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


def read_once():
    require(os.geteuid() != 0 and os.environ.get('LISTEN_PID') == str(os.getpid())
            and os.environ.get('LISTEN_FDS') == '1')
    with socket.socket(fileno=3) as listener:
        require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM
                and listener.getsockname() == READER_SOCKET
                and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1)
        connection, _ = listener.accept()
        with connection, connection.makefile('rb') as input_file:
            connection.settimeout(3)
            pid, owner, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            require(owner == 0 and pid > 0)
            raw = input_file.read(128).decode('ascii')
            require(raw.endswith('\n') and IDENTITY.fullmatch(raw[:-1]))
            uid, gid = os.geteuid(), os.getegid()
            path, plan = projection(Path(ROOT), raw[:-1], uid, gid, Path('/'))
            result = canonical(inspect_projection(path, plan, uid, gid))
            require(0 < len(result) <= 8192)
            connection.sendall(struct.pack('!I', len(result)) + result)


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['read-once']:
            read_once()
        else:
            require(sys.argv[1:] == ['condition'])
            condition(Path(__file__).resolve().parents[1])
    except (OSError, ValueError, TypeError, KeyError):
        print('Controlled recovery selection is already used, stale, or invalid', file=sys.stderr)
        sys.exit(1)
