#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Root package lifecycle for the dedicated clock actor; keep all decisions."""
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import (ACTOR_HOME, CHRONY_POLICY, CHRONY_RULE, PREVIOUS_CHRONY_RULE, COHORT, CONFIG_SOCKET_UNIT, CONFIG_UNITS, HOME,
                               LEGACY_UNITS, PREVIOUS_UNITS, RTC_SOCKET_UNIT, STATE, STEP_SOCKET_UNIT, STEP_UNITS, UNITS,
                               Policy, effective_units, public_file, publish_path,
                               retire_rtc_projection, unit_sources, unit_directory_present)
from kura_clock_journal import (Journal, Refused, create, decode, digest, directory, encode,
                                command, identifier, identity, pairs, read, require, sync, terminal_receipt,
                                MAX_OPERATIONS)

ACCOUNT = Path('/etc/kura/clock-broker-account.json')
INTENT = Path('/etc/kura/clock-broker-account-intent.json')
RETAINED = Path('/var/lib/kura-retained')
SENDER_ARCHIVE = Path('/etc/kura/clock-sender-retention.json')
MAX_SENDER_ARCHIVE = 16 * 1024 * 1024
SENDER_DIRECTORIES = ('issued', 'completed')


def run(*arguments):
    return subprocess.check_output(list(arguments), env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'},
                                   text=True, timeout=20)


def chrony_policy(action, previous_paired=False):
    path = CHRONY_POLICY
    require(unit_directory_present(path.parent), 'UNPAIRED_CHRONY_POLICY')
    existing = public_file(path) if os.path.lexists(path) else None
    if existing == CHRONY_RULE:
        if action == 'remove':
            path.unlink()
            sync(path.parent)
        return
    replace = existing is not None
    require(not replace or (previous_paired and existing == PREVIOUS_CHRONY_RULE and action in ('check', 'install')),
            'UNPAIRED_CHRONY_POLICY')
    if action == 'install':
        fd, staged = tempfile.mkstemp(prefix='.kura-clock-chrony-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                os.fchown(stream.fileno(), 0, 0)
                os.fchmod(stream.fileno(), 0o644)
                stream.write(CHRONY_RULE)
                stream.flush()
                os.fsync(stream.fileno())
            require((public_file(path) if os.path.lexists(path) else None) == existing, 'UNPAIRED_CHRONY_POLICY')
            publish_path(staged, path, replace)
        finally:
            if os.path.lexists(staged):
                os.unlink(staged)
            sync(path.parent)
    elif action == 'verify':
        raise Refused('UNPAIRED_CHRONY_POLICY')


def main_masked():
    """A fixed Root Main mask is an off state, never clock-unit authority."""
    found = False
    for prefix in ('/etc', '/run'):
        path = Path(prefix + '/systemd/system/kura.service')
        if not os.path.lexists(path):
            continue
        require(unit_directory_present(path.parent), 'UNSAFE_UNIT')
        before = path.lstat()
        require(stat.S_ISLNK(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1, 'UNSAFE_UNIT')
        target = os.readlink(path)
        identity = lambda m: (m.st_dev, m.st_ino, m.st_uid, m.st_gid, m.st_mode,
                              m.st_nlink, m.st_size, m.st_mtime_ns, m.st_ctime_ns)
        require(target == '/dev/null' and identity(before) == identity(path.lstat()), 'UNSAFE_UNIT')
        found = True
    require(found, 'UNSAFE_UNIT')


def properties(unit):
    result = subprocess.run(['/usr/bin/systemctl', 'show', unit, '--property=LoadState,ActiveState,MainPID,ControlPID'],
                            env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}, capture_output=True, text=True, timeout=5)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if unit == 'kura.service' and values.get('LoadState') == 'masked':
        main_masked()
        require(values.get('MainPID') == '0' and values.get('ControlPID') == '0'
                and values.get('ActiveState') == 'inactive', 'UNIT_RUNNING')
    else:
        require(values.get('LoadState') in ('loaded', 'not-found'), 'UNSAFE_UNIT')
    require(result.returncode == 0 or values['LoadState'] == 'not-found', 'UNSAFE_UNIT')
    return values


def unit_inactive(value):
    return (value.get('ActiveState') in ('inactive', 'failed')
            and value.get('MainPID', '0') == '0' and value.get('ControlPID', '0') == '0')


def inactive(unit):
    require(unit_inactive(properties(unit)), 'UNIT_RUNNING')


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
            and set(value['units']) in (set(LEGACY_UNITS), set(PREVIOUS_UNITS), set(STEP_UNITS), set(CONFIG_UNITS), set(UNITS)),
            'UNPAIRED_MAINTENANCE')
    identifier(value['purposeId'])
    require(isinstance(value['cohortSha256'], str) and re.fullmatch('[0-9a-f]{64}', value['cohortSha256']) is not None
            and all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) is not None for v in value['units'].values()),
            'UNPAIRED_MAINTENANCE')
    require(value['namespace'] == namespace_or_empty(Journal(STATE, record['uid'])), 'FOREIGN_NAMESPACE')
    return value


def sender_inventory(sender, uid):
    """Read only the sender's fixed private files, with their exact canonical bytes."""
    folders, entries = {}, {}
    size = 0
    for path in (sender, *(sender / name for name in SENDER_DIRECTORIES if os.path.lexists(sender / name))):
        name = '' if path == sender else path.name
        directory(path, uid)
        metadata = path.lstat()
        folders[name] = [metadata.st_gid, metadata.st_mtime_ns]
        children = list(path.iterdir())
        require(len(children) <= MAX_OPERATIONS, 'UNPAIRED_SENDER_RETENTION')
        for child in children:
            if not name and child.name in SENDER_DIRECTORIES:
                continue
            require(name or child.name in ('sender.lock', 'pending.json'), 'UNPAIRED_SENDER_RETENTION')
            metadata = child.lstat()
            raw = read(child, uid)
            size += len(raw)
            require(size <= MAX_SENDER_ARCHIVE, 'UNPAIRED_SENDER_RETENTION')
            require(identity(metadata) == identity(child.lstat()), 'UNPAIRED_SENDER_RETENTION')
            value = None if child.name == 'sender.lock' and not name else decode(raw)
            require(raw == (b'' if value is None else encode(value)), 'UNPAIRED_SENDER_RETENTION')
            entries[child.relative_to(sender).as_posix()] = [metadata.st_gid, metadata.st_mtime_ns, value]
    return dict(directories=folders, entries=entries)


def check_sender(inventory, journal, namespace):
    def metadata(entry):
        require(type(entry[0]) is int and entry[0] >= 0 and type(entry[1]) is int, 'UNPAIRED_SENDER_RETENTION')

    require(type(inventory) is dict and set(inventory) == {'directories', 'entries'}, 'UNPAIRED_SENDER_RETENTION')
    folders, entries = inventory['directories'], inventory['entries']
    require(type(folders) is dict and type(entries) is dict and '' in folders and set(folders) <= {'', *SENDER_DIRECTORIES}
            and len(entries) <= 2 * MAX_OPERATIONS + 2, 'UNPAIRED_SENDER_RETENTION')
    for entry in folders.values():
        require(type(entry) is list and len(entry) == 2, 'UNPAIRED_SENDER_RETENTION')
        metadata(entry)
    for path, entry in entries.items():
        require(type(entry) is list and len(entry) == 3, 'UNPAIRED_SENDER_RETENTION')
        metadata(entry)
        if path in ('sender.lock', 'pending.json'):
            continue
        folder, separator, filename = path.partition('/')
        require(separator and folder in SENDER_DIRECTORIES and folder in folders
                and filename.endswith('.json'), 'UNPAIRED_SENDER_RETENTION')
        identifier(filename[:-5])
    if 'sender.lock' in entries:
        require(entries['sender.lock'][2] is None, 'UNPAIRED_SENDER_RETENTION')

    references = {}
    if 'pending.json' in entries:
        pending = command(entries['pending.json'][2])
        require(pending['namespace'] == namespace, 'FOREIGN_NAMESPACE')
        references[pending['requestId']] = digest(pending)
    for path, (_, _, saved) in entries.items():
        if not path.startswith('completed/'):
            continue
        request_id = path[len('completed/'):-5]
        require(type(saved) is dict and set(saved) == {'schema', 'command', 'result'}
                and type(saved['schema']) is int and saved['schema'] == 1, 'UNPAIRED_SENDER_RETENTION')
        intent = command(saved['command'])
        require(intent['namespace'] == namespace and intent['requestId'] == request_id, 'FOREIGN_NAMESPACE')
        request_hash = digest(intent)
        require(references.setdefault(request_id, request_hash) == request_hash, 'UNPAIRED_SENDER_RETENTION')
        reference = dict(schema=1, namespace=namespace, requestId=request_id, requestSha256=request_hash)
        issue = entries.get('issued/' + request_id + '.json')
        require(issue is not None and encode(issue[2]) == encode(reference)
                and type(saved['result']) is dict and terminal_receipt(saved['result'], reference, intent['action'])
                and journal.status(namespace, request_id, request_hash) == saved['result'], 'UNPAIRED_SENDER_RETENTION')
    for path, (_, _, issue) in entries.items():
        if path.startswith('issued/'):
            request_id = path[len('issued/'):-5]
            require(request_id in references and encode(issue) == encode(dict(schema=1, namespace=namespace,
                    requestId=request_id, requestSha256=references[request_id])), 'UNPAIRED_SENDER_RETENTION')


def sender_retention_binding(record, current):
    require(current is not None, 'UNPAIRED_SENDER_RETENTION')
    sender = pwd.getpwnam('kurad')
    require(sender.pw_uid > 0 and sender.pw_gid > 0, 'UNPAIRED_SENDER_RETENTION')
    return dict(schema=1, purposeId=current['purposeId'], namespace=current['namespace'],
                clockUid=record['uid'], clockGid=record['gid'], senderUid=sender.pw_uid, senderGid=sender.pw_gid)


def retained_sender(record, journal, current, restoring=False):
    live = HOME / 'data/clock-broker'
    source = RETAINED / 'data/clock-broker'
    exists = os.path.lexists(SENDER_ARCHIVE)
    if not exists and (restoring or not (os.path.lexists(source) or os.path.lexists(live))):
        return
    binding = sender_retention_binding(record, current)
    uid = binding['senderUid']
    namespace = binding['namespace']
    require(unit_directory_present(SENDER_ARCHIVE.parent), 'UNPAIRED_SENDER_RETENTION')
    if not restoring:
        require(unit_directory_present(RETAINED.parent), 'UNPAIRED_SENDER_RETENTION')
        directory(RETAINED, 0)
        sender_data_directory(source.parent, uid)
        inventory = sender_inventory(source, uid)
        check_sender(inventory, journal, namespace)
        value = dict(binding=binding, sender=inventory)
        if exists:
            require(read(SENDER_ARCHIVE, 0, maximum=MAX_SENDER_ARCHIVE) == encode(value), 'UNPAIRED_SENDER_RETENTION')
            return
        require(len(encode(value)) <= MAX_SENDER_ARCHIVE, 'UNPAIRED_SENDER_RETENTION')
        with tempfile.TemporaryDirectory(prefix='.kura-clock-sender-', dir=SENDER_ARCHIVE.parent) as folder:
            staged = Path(folder) / 'retention.json'
            create(staged, value)
            publish_path(staged, SENDER_ARCHIVE, False)
        sync(SENDER_ARCHIVE.parent)
        return

    raw = read(SENDER_ARCHIVE, 0, maximum=MAX_SENDER_ARCHIVE)
    value = json.loads(raw, object_pairs_hook=pairs)
    require(set(value) == {'binding', 'sender'} and value['binding'] == binding, 'UNPAIRED_SENDER_RETENTION')
    inventory = value['sender']
    check_sender(inventory, journal, namespace)
    inactive('kura.service')
    sender_data_directory(live.parent, uid)
    if not os.path.lexists(live):
        restore_sender(live, inventory, uid)
    require(sender_inventory(live, uid) == inventory, 'UNPAIRED_SENDER_RETENTION')
    # The exact live copy is durable before admitting new clock transactions.
    SENDER_ARCHIVE.unlink()
    sync(SENDER_ARCHIVE.parent)


def sender_data_directory(path, uid):
    parent = path.lstat()
    require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == uid
            and not parent.st_mode & 0o022, 'UNPAIRED_SENDER_RETENTION')


def restore_sender(live, inventory, uid):
    with tempfile.TemporaryDirectory(prefix='.kura-clock-sender-', dir=live.parent) as folder:
        staged = Path(folder) / live.name
        staged.mkdir(mode=0o700)
        folders = inventory['directories']
        for name in folders:
            if name:
                (staged / name).mkdir(mode=0o700)
        for name, (gid, modified, value) in inventory['entries'].items():
            path = staged / name
            with path.open('xb') as output:
                os.fchmod(output.fileno(), 0o600)
                os.fchown(output.fileno(), uid, gid)
                output.write(b'' if value is None else encode(value))
                output.flush()
                os.utime(output.fileno(), ns=(modified, modified))
                os.fsync(output.fileno())
        for name in sorted(folders, reverse=True):
            gid, modified = folders[name]
            path = staged / name
            os.chown(path, uid, gid)
            os.utime(path, ns=(modified, modified))
            sync(path)
        require(sender_inventory(staged, uid) == inventory, 'UNPAIRED_SENDER_RETENTION')
        publish_path(staged, live, False)
        sync(live.parent)


def terminal_operations(journal):
    namespace = namespace_or_empty(journal)
    if namespace is not None:
        for entry in (STATE / 'operations').iterdir():
            identifier(entry.name)
            intent = decode(read(entry / 'intent.json', journal.owner))
            require(journal.status(namespace, entry.name, digest(intent))['state'] in ('APPLIED', 'FAILED'),
                    'UNRESOLVED_CLOCK_OPERATION')
    return namespace


def quiesce():
    policy = Policy(); policy.check()
    record = account(); private_state(record)
    journal = Journal(STATE, record['uid'])
    with journal.lock():
        namespace = terminal_operations(journal)
        current = maintenance(record)
        units = {name: hashlib.sha256(public_file(Path('/lib/systemd/system') / name)).hexdigest() for name in UNITS}
        if current is None:
            create(STATE / 'maintenance.json', dict(schema=1, purposeId=str(uuid.uuid4()), namespace=namespace,
                   cohortSha256=policy.cohort, units=units), 0o644)
        else:
            require(current['cohortSha256'] == policy.cohort and current['units'] == units, 'UNPAIRED_MAINTENANCE')
    # Include the listening sockets in the same stop transaction as their services.
    run('/usr/bin/systemctl', 'stop', *UNITS)
    for name in UNITS:
        inactive(name)


def reassert_quiescence():
    inactive('kura.service')
    running = {name for name in UNITS if not unit_inactive(properties(name))}
    if not running:
        return
    unit_sources()
    record = account()
    original = maintenance(record)
    require(original is not None and running <= original['units'].keys(), 'UNPAIRED_MAINTENANCE')
    actor = Policy(actor=True)
    descriptor = actor.check(installed=False, effective=False, allow_legacy=True)
    require(actor.cohort == original['cohortSha256'], 'UNPAIRED_MAINTENANCE')
    for name, expected in original['units'].items():
        actual = hashlib.sha256(public_file(Path('/lib/systemd/system') / name)).hexdigest()
        require(actual == expected == descriptor['files']['libexec/clock-broker/' + name], 'UNPAIRED_CODE')
    effective_units(original['units'])
    journal = Journal(STATE, record['uid'])
    with journal.lock():
        require(maintenance(record) == original and terminal_operations(journal) == original['namespace'],
                'UNPAIRED_MAINTENANCE')
    run('/usr/bin/systemctl', 'stop', *sorted(original['units']))
    for name in UNITS:
        inactive(name)
    require(maintenance(record) == original, 'UNPAIRED_MAINTENANCE')


def archived_actor(record):
    return ACTOR_HOME.parent / ('.kura-clock-broker-previous-' + record['cohortSha256'] + '-' + record['purposeId'])


def previous_actor(record, candidate):
    if record is None:
        return None
    actor = Policy(actor=True)
    if os.path.lexists(ACTOR_HOME):
        descriptor = actor.check(installed=False, allow_legacy=True)
        if actor.cohort == record['cohortSha256']:
            return descriptor
        require(actor.cohort == candidate, 'UNPAIRED_CODE')
    # After the first rename the previous release lives at the exact archive
    # selected by the still-active maintenance purpose, including on a retry.
    actor.home = archived_actor(record)
    require(os.path.lexists(actor.home), 'UNRESOLVED_CODE_PUBLICATION')
    descriptor = actor.check(installed=False, allow_legacy=True)
    require(actor.cohort == record['cohortSha256'], 'UNPAIRED_CODE')
    return descriptor


def install():
    policy = Policy(); descriptor = policy.check(installed=False)
    inactive('kura.service')
    for name in UNITS:
        inactive(name)
    # Reject every effective lookup location before accounts, state or code change.
    unit_sources()
    # Core already owns /etc/kura. No parent ownership or existing data is repaired.
    metadata = ACCOUNT.parent.lstat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0 and not metadata.st_mode & 0o022, 'UNSAFE_STATE')
    record = account(create_missing=True)
    private_state(record)
    current = maintenance(record) if os.path.lexists(STATE) else None
    # Check every installed fragment and the rule before publishing replacement code.
    previous = previous_actor(current, policy.cohort)
    previous_paired = previous is not None
    chrony_policy('check', previous_paired)
    desired_units = {}
    for name in UNITS:
        desired = public_file(HOME / 'libexec/clock-broker' / name)
        path = Path('/lib/systemd/system') / name
        if os.path.lexists(path):
            old = public_file(path)
            require(old == desired or (current is not None and hashlib.sha256(old).hexdigest() == current['units'].get(name)),
                    'UNPAIRED_CODE')
        desired_units[path] = desired
    retire_rtc_projection(previous, current)
    install_actor_code(policy, descriptor, record, current)
    for path, desired in desired_units.items():
        temporary = path.with_name(path.name + '.kura-clock-staged')
        if os.path.lexists(temporary):
            require(public_file(temporary) == desired, 'UNPAIRED_CODE')
        else:
            with temporary.open('xb') as output:
                os.fchmod(output.fileno(), 0o644); output.write(desired); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path); sync(path.parent)
    chrony_policy('install', previous_paired)
    policy.check(effective=False)


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
        installed = Policy(actor=True); installed.check(installed=False, allow_legacy=True)
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
        old = Policy(actor=True); old.check(installed=False, allow_legacy=True)
        require(maintenance_record is not None and old.cohort == maintenance_record['cohortSha256'], 'UNPAIRED_CODE')
        archive = archived_actor(maintenance_record)
        require(not os.path.lexists(archive), 'UNRESOLVED_CODE_PUBLICATION')
        os.rename(ACTOR_HOME, archive); sync(parent)
    os.rename(staged, ACTOR_HOME); sync(parent)
    installed = Policy(actor=True); installed.check(installed=False)
    require(installed.cohort == policy.cohort, 'UNPAIRED_CODE')


def resume():
    policy = Policy(); policy.check(effective=False); record = account()
    chrony_policy('verify')
    actor = Policy(actor=True); actor.check(effective=False)
    require(actor.cohort == policy.cohort, 'UNPAIRED_CODE')
    require(not os.path.lexists(SENDER_ARCHIVE), 'UNPAIRED_SENDER_RETENTION')
    # A newly published fragment is not yet PID1's loaded configuration. Keep
    # the original maintenance gate through reload, validation and socket start.
    run('/usr/bin/systemctl', 'daemon-reload')
    policy.check(); actor.check()
    run('/usr/bin/systemctl', 'enable', '--now', 'kura-clock-broker.socket')
    run('/usr/bin/systemctl', 'enable', '--now', STEP_SOCKET_UNIT)
    run('/usr/bin/systemctl', 'enable', '--now', CONFIG_SOCKET_UNIT)
    run('/usr/bin/systemctl', 'enable', '--now', RTC_SOCKET_UNIT)
    policy.check(); actor.check()
    if os.path.lexists(STATE):
        journal = Journal(STATE, record['uid'])
        with journal.lock():
            value = maintenance(record)
            if value is not None:
                (STATE / 'maintenance.json').unlink(); sync(STATE)


def restore_retained_sender():
    if not os.path.lexists(SENDER_ARCHIVE):
        return
    core, actor = Policy(), Policy(actor=True)
    core.check(effective=False); actor.check(effective=False)
    require(core.cohort == actor.cohort, 'UNPAIRED_CODE')
    record = account()
    journal = Journal(STATE, record['uid'])
    with journal.lock():
        retained_sender(record, journal, maintenance(record), restoring=True)


def remove():
    quiesce()
    record = account()
    journal = Journal(STATE, record['uid'])
    with journal.lock():
        retained_sender(record, journal, maintenance(record))
    chrony_policy('remove')
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
        require(sys.argv[1] in ('install', 'quiesce', 'reassert_quiescence', 'resume', 'remove', 'restore_retained_sender'))
        globals()[sys.argv[1]]()
    except (Refused, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(error.reason if isinstance(error, Refused) else 'UNRESOLVED_OR_UNAVAILABLE', file=sys.stderr)
        raise SystemExit(1)
