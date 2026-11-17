#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Root package lifecycle for the dedicated clock actor; keep all decisions."""
import grp
import hashlib
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import ACTOR_HOME, COHORT, HOME, STATE, UNITS, Policy, protected, public_file
from kura_clock_journal import (Journal, Refused, create, decode, digest, directory, encode,
                                identifier, read, require, sync)

ACCOUNT = Path('/etc/kura/clock-broker-account.json')
INTENT = Path('/etc/kura/clock-broker-account-intent.json')


def run(*arguments):
    return subprocess.check_output(list(arguments), env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'},
                                   text=True, timeout=20)


def properties(unit):
    result = subprocess.run(['/usr/bin/systemctl', 'show', unit, '--property=LoadState,ActiveState,MainPID,ControlPID'],
                            env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}, capture_output=True, text=True, timeout=5)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    require(values.get('LoadState') in ('loaded', 'not-found'), 'UNSAFE_UNIT')
    require(result.returncode == 0 or values['LoadState'] == 'not-found', 'UNSAFE_UNIT')
    return values


def inactive(unit):
    value = properties(unit)
    require(value.get('ActiveState') in ('inactive', 'failed')
            and value.get('MainPID', '0') == '0' and value.get('ControlPID', '0') == '0', 'UNIT_RUNNING')


def account(create_missing=False):
    if os.path.lexists(ACCOUNT):
        record = decode(public_file(ACCOUNT))
        require(set(record) == {'schema', 'purposeId', 'uid', 'gid', 'role'} and type(record['schema']) is int
                and record['schema'] == 1 and record['role'] == 'kura-clock' and type(record['uid']) is int
                and type(record['gid']) is int and record['uid'] > 0 and record['gid'] > 0, 'UNPAIRED_ACCOUNT')
        identifier(record['purposeId'])
    else:
        require(create_missing, 'UNPAIRED_ACCOUNT')
        if not os.path.lexists(INTENT):
            for lookup in (pwd.getpwnam, grp.getgrnam):
                try:
                    lookup('kura-clock')
                except KeyError:
                    continue
                raise Refused('UNPAIRED_ACCOUNT')
            require(not os.path.lexists(STATE) and not os.path.lexists(ACTOR_HOME)
                    and all(not os.path.lexists(Path('/lib/systemd/system') / n) for n in UNITS),
                    'UNPAIRED_ACCOUNT')
            require(ACCOUNT.parent.is_dir() and not ACCOUNT.parent.is_symlink(), 'UNPAIRED_ACCOUNT')
            create(INTENT, dict(schema=1, purposeId=str(uuid.uuid4()), role='kura-clock', originalAbsent=True), 0o644)
        intent = decode(public_file(INTENT))
        require(set(intent) == {'schema', 'purposeId', 'role', 'originalAbsent'} and type(intent['schema']) is int
                and intent['schema'] == 1 and intent['role'] == 'kura-clock' and intent['originalAbsent'] is True,
                'UNPAIRED_ACCOUNT')
        purpose = identifier(intent['purposeId'])
        group_result = INTENT.with_name('clock-broker-group-result.json')
        if not os.path.lexists(group_result):
            issued = INTENT.with_name('clock-broker-group-issued.json')
            require(not os.path.lexists(issued), 'UNRESOLVED_ACCOUNT_CREATION')
            create(issued, dict(schema=1, purposeId=purpose, action='group-create'), 0o644)
            run('/usr/sbin/groupadd', '--system', 'kura-clock')
            created = grp.getgrnam('kura-clock')
            create(group_result, dict(schema=1, purposeId=purpose, gid=created.gr_gid), 0o644)
        group = decode(public_file(group_result)); actual_group = grp.getgrnam('kura-clock')
        require(set(group) == {'schema', 'purposeId', 'gid'} and group['schema'] == 1 and group['purposeId'] == purpose
                and type(group['gid']) is int and group['gid'] > 0 and actual_group.gr_gid == group['gid']
                and actual_group.gr_mem == [], 'UNPAIRED_ACCOUNT')
        marker = 'yofc-kura-clock-' + purpose
        try:
            user = pwd.getpwnam('kura-clock')
        except KeyError:
            issued = INTENT.with_name('clock-broker-user-issued.json')
            require(not os.path.lexists(issued), 'UNRESOLVED_ACCOUNT_CREATION')
            create(issued, dict(schema=1, purposeId=purpose, action='user-create'), 0o644)
            run('/usr/sbin/useradd', '--system', '--gid', 'kura-clock', '--home-dir', '/nonexistent', '--no-create-home',
                '--shell', '/usr/sbin/nologin', '--comment', marker, 'kura-clock')
            user = pwd.getpwnam('kura-clock')
        require(user.pw_gecos == marker and user.pw_gid == group['gid'] and user.pw_uid > 0
                and user.pw_dir == '/nonexistent' and user.pw_shell == '/usr/sbin/nologin', 'UNPAIRED_ACCOUNT')
        record = dict(schema=1, purposeId=purpose, uid=user.pw_uid, gid=user.pw_gid, role='kura-clock')
        create(ACCOUNT, record, 0o644)
    user = pwd.getpwnam('kura-clock'); group = grp.getgrnam('kura-clock')
    require(user.pw_uid == record['uid'] and user.pw_gid == group.gr_gid == record['gid'] and group.gr_mem == []
            and user.pw_gecos == 'yofc-kura-clock-' + record['purposeId']
            and user.pw_dir == '/nonexistent' and user.pw_shell == '/usr/sbin/nologin'
            and set(os.getgrouplist('kura-clock', user.pw_gid)) == {user.pw_gid}, 'UNPAIRED_ACCOUNT')
    return record


def private_state(record):
    if not os.path.lexists(STATE):
        STATE.mkdir(mode=0o700)
        os.chown(STATE, record['uid'], record['gid']); sync(STATE.parent)
    directory(STATE, record['uid'])
    path = STATE / 'admission.lock'
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except FileExistsError:
        return
    try:
        os.fchown(fd, record['uid'], record['gid']); os.fsync(fd)
    finally:
        os.close(fd)
    sync(STATE)


def namespace_or_empty(journal):
    if not os.path.lexists(STATE / 'namespace.json'):
        require(not os.path.lexists(STATE / 'operations'), 'UNRESOLVED_NAMESPACE')
        return None
    directory(STATE / 'operations', journal.owner)
    return journal.namespace()


def maintenance(record):
    flag = STATE / 'maintenance.json'
    if not os.path.lexists(flag):
        return None
    directory(STATE, record['uid'])
    value = decode(read(flag, 0, 0o644))
    require(set(value) == {'schema', 'purposeId', 'namespace', 'cohortSha256', 'units'}
            and type(value['schema']) is int and value['schema'] == 1 and type(value['units']) is dict
            and set(value['units']) == set(UNITS), 'UNPAIRED_MAINTENANCE')
    identifier(value['purposeId'])
    require(isinstance(value['cohortSha256'], str) and re.fullmatch('[0-9a-f]{64}', value['cohortSha256']) is not None
            and all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) is not None for v in value['units'].values()),
            'UNPAIRED_MAINTENANCE')
    require(value['namespace'] == namespace_or_empty(Journal(STATE, record['uid'])), 'FOREIGN_NAMESPACE')
    return value


def quiesce():
    policy = Policy(); policy.check()
    record = account(); private_state(record)
    journal = Journal(STATE, record['uid'])
    with journal.lock():
        namespace = namespace_or_empty(journal)
        if namespace is not None:
            for entry in (STATE / 'operations').iterdir():
                identifier(entry.name)
                intent = decode(read(entry / 'intent.json', record['uid']))
                require(journal.status(namespace, entry.name, digest(intent))['state'] in ('APPLIED', 'FAILED'),
                        'UNRESOLVED_CLOCK_OPERATION')
        current = maintenance(record)
        units = {name: hashlib.sha256(public_file(Path('/lib/systemd/system') / name)).hexdigest() for name in UNITS}
        if current is None:
            create(STATE / 'maintenance.json', dict(schema=1, purposeId=str(uuid.uuid4()), namespace=namespace,
                   cohortSha256=policy.cohort, units=units), 0o644)
        else:
            require(current['cohortSha256'] == policy.cohort and current['units'] == units, 'UNPAIRED_MAINTENANCE')
    for name in UNITS:
        run('/usr/bin/systemctl', 'stop', name); inactive(name)


def install():
    policy = Policy(); descriptor = policy.check(installed=False)
    inactive('kura.service')
    for name in UNITS:
        inactive(name)
    # Core already owns /etc/kura. No parent ownership or existing data is repaired.
    metadata = ACCOUNT.parent.lstat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0 and not metadata.st_mode & 0o022, 'UNSAFE_STATE')
    record = account(create_missing=True)
    private_state(record)
    current = maintenance(record) if os.path.lexists(STATE) else None
    install_actor_code(policy, descriptor, record, current)
    for name in UNITS:
        desired = public_file(HOME / 'libexec/clock-broker' / name)
        path = Path('/lib/systemd/system') / name
        if os.path.lexists(path):
            old = public_file(path)
            require(old == desired or (current is not None and hashlib.sha256(old).hexdigest() == current['units'][name]),
                    'UNPAIRED_CODE')
        for root in ('/etc/systemd/system', '/run/systemd/system'):
            require(not os.path.lexists(Path(root) / name) and not os.path.lexists(Path(root) / (name + '.d')), 'UNPAIRED_CODE')
        temporary = path.with_name(name + '.kura-clock-staged')
        if os.path.lexists(temporary):
            require(public_file(temporary) == desired, 'UNPAIRED_CODE')
        else:
            with temporary.open('xb') as output:
                os.fchmod(output.fileno(), 0o644); output.write(desired); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path); sync(path.parent)
    policy.check()


def install_actor_code(policy, descriptor, record, maintenance_record):
    """Root-only copies, exactly paired to canonical Core; no key-control group."""
    parent = ACTOR_HOME.parent
    if not os.path.lexists(parent):
        metadata = parent.parent.lstat()
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0 and not metadata.st_mode & 0o022, 'UNPAIRED_CODE')
        parent.mkdir(mode=0o755); os.chmod(parent, 0o755); sync(parent.parent)
    metadata = parent.lstat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0 and not metadata.st_mode & 0o022, 'UNPAIRED_CODE')
    if os.path.lexists(ACTOR_HOME):
        installed = Policy(actor=True); installed.check(installed=False)
        if installed.cohort == policy.cohort:
            return
        require(maintenance_record is not None and installed.cohort == maintenance_record['cohortSha256'], 'UNPAIRED_CODE')
    staged = parent / ('.kura-clock-broker-staged-' + policy.cohort)
    if not os.path.lexists(staged):
        staged.mkdir(mode=0o750); os.chown(staged, 0, record['gid']); os.chmod(staged, 0o750)
        for name in [*descriptor['files'], COHORT.as_posix()]:
            destination = staged / name
            missing = []
            for folder in destination.parents:
                if folder == staged:
                    break
                if not os.path.lexists(folder):
                    missing.append(folder)
            for folder in reversed(missing):
                folder.mkdir(mode=0o750); os.chown(folder, 0, record['gid']); os.chmod(folder, 0o750)
            raw = public_file(HOME / name, 256 * 1024 * 1024)
            with destination.open('xb') as output:
                os.fchown(output.fileno(), 0, record['gid']); os.fchmod(output.fileno(), 0o640)
                output.write(raw); output.flush(); os.fsync(output.fileno())
            sync(destination.parent)
        sync(staged)
    staged_policy = Policy(actor=True); staged_policy.home = staged
    staged_policy.check(installed=False)
    require(staged_policy.cohort == policy.cohort, 'UNPAIRED_CODE')
    if os.path.lexists(ACTOR_HOME):
        old = Policy(actor=True); old.check(installed=False)
        require(maintenance_record is not None and old.cohort == maintenance_record['cohortSha256'], 'UNPAIRED_CODE')
        archive = parent / ('.kura-clock-broker-previous-' + old.cohort + '-' + maintenance_record['purposeId'])
        require(not os.path.lexists(archive), 'UNRESOLVED_CODE_PUBLICATION')
        os.rename(ACTOR_HOME, archive); sync(parent)
    os.rename(staged, ACTOR_HOME); sync(parent)
    installed = Policy(actor=True); installed.check(installed=False)
    require(installed.cohort == policy.cohort, 'UNPAIRED_CODE')


def resume():
    policy = Policy(); policy.check(); record = account()
    actor = Policy(actor=True); actor.check()
    require(actor.cohort == policy.cohort, 'UNPAIRED_CODE')
    if os.path.lexists(STATE):
        journal = Journal(STATE, record['uid'])
        with journal.lock():
            value = maintenance(record)
            if value is not None:
                (STATE / 'maintenance.json').unlink(); sync(STATE)
    run('/usr/bin/systemctl', 'daemon-reload')
    run('/usr/bin/systemctl', 'enable', '--now', 'kura-clock-broker.socket')


def remove():
    quiesce()
    for name in UNITS:
        run('/usr/bin/systemctl', 'disable', name)
        (Path('/lib/systemd/system') / name).unlink()
    sync(Path('/lib/systemd/system'))
    run('/usr/bin/systemctl', 'daemon-reload')
    # Keep the actor's account, namespace, original operations and maintenance
    # purpose, along with Core's retained sender decisions, across remove/purge.


if __name__ == '__main__':
    try:
        require(os.geteuid() == 0 and len(sys.argv) == 2 and sys.argv[0] == str(HOME / 'bin/kura_clock_setup.py'), 'INVALID_ENTRYPOINT')
        require(sys.argv[1] in ('install', 'quiesce', 'resume', 'remove'))
        globals()[sys.argv[1]]()
    except (Refused, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(error.reason if isinstance(error, Refused) else 'UNRESOLVED_OR_UNAVAILABLE', file=sys.stderr)
        raise SystemExit(1)
