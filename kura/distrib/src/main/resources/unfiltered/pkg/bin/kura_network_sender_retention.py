#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Keep unpublished acknowledgments paired with the original network actor across Core purge."""
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_bind_outcomes import binding
from kura_clock_broker import HOME, public_file, publish_path, unit_directory_present
from kura_clock_journal import MAX_BYTES, create, decode, directory, encode, identifier, read, require, sync
from kura_clock_setup import inactive, sender_data_directory

ARCHIVE = Path('/etc/kura/network-sender-retention.json')
# The field indexes and byte bounds are the wire formats of the installed Java senders.
SENDERS = {
    'dhcp-control': (Path('/var/lib/kura-dhcp-service'), 16384, 2, 1, 5),
    'bind-control': (Path('/var/lib/kura-bind-service'), 32768, 2, 1, 8),
    'modem-control': (Path('/var/lib/kura-modem-reset'), 512, 4, 5, 7),
}
INVALID = 'UNPAIRED_NETWORK_SENDER'


def check_record(name, content):
    actor, limit, scope, operation, count = SENDERS[name]
    fields = content.split('\n')
    require(0 < len(content.encode('ascii')) <= limit and len(fields) == count and fields[0] == '1'
            and fields[-1] == '', INVALID)
    identifier(fields[operation])
    directory(actor, 0)
    meta = actor.lstat()
    machine = public_file(Path('/etc/machine-id'), 64).strip()
    require(meta.st_gid == 0 and re.fullmatch(rb'[0-9a-f]{32}', machine), INVALID)
    # A sender may have persisted before dispatch, when root.json does not exist yet.
    require(fields[scope] == binding(actor, [machine.decode('ascii'), meta.st_dev, meta.st_ino]), INVALID)


def archive(staged):
    require(staged.parent == Path('/var/lib') and re.fullmatch(r'\.kura-retained\.tmp\.[A-Za-z0-9]+', staged.name), INVALID)
    directory(staged, 0)
    data = staged / 'data'
    if os.path.lexists(data):
        require(stat.S_ISDIR(data.lstat().st_mode), INVALID)
    names = [name for name in SENDERS if os.path.lexists(data / name)]
    if not names and not os.path.lexists(ARCHIVE):
        return
    user = pwd.getpwnam('kurad')
    require(user.pw_uid > 0 and user.pw_gid > 0, INVALID)
    sender_data_directory(data, user.pw_uid)
    records = {}
    for name in names:
        folder = data / name
        directory(folder, user.pw_uid)
        pending = folder / 'pending'
        if os.path.lexists(pending):
            content = read(pending, user.pw_uid, maximum=SENDERS[name][1]).decode('ascii')
            check_record(name, content)
            records[name] = content
    value = dict(schema=1, uid=user.pw_uid, gid=user.pw_gid, records=records)
    require(len(encode(value)) <= MAX_BYTES, INVALID)
    if os.path.lexists(ARCHIVE):
        require(read(ARCHIVE, 0) == encode(value), INVALID)
    elif records:
        require(unit_directory_present(ARCHIVE.parent), INVALID)
        with tempfile.TemporaryDirectory(dir=ARCHIVE.parent) as staging:
            source = Path(staging) / 'pending.json'
            create(source, value)
            publish_path(source, ARCHIVE, False)
        sync(ARCHIVE.parent)


def restore_files(data, records, uid):
    sender_data_directory(data, uid)
    for name, content in records.items():
        folder = data / name
        folder.mkdir(mode=0o700, exist_ok=True)
        directory(folder, uid)
        pending = folder / 'pending'
        raw = content.encode('ascii')
        if not os.path.lexists(pending):
            # The same account as the Java sender publishes only a complete record.
            source = folder / ('.restore-' + secrets.token_hex(16))
            fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                publish_path(source, pending, False)
            finally:
                source.unlink(missing_ok=True)
        require(read(pending, uid, maximum=SENDERS[name][1]) == raw, INVALID)
        sync(folder)
    sync(data)


def restore():
    if not os.path.lexists(ARCHIVE):
        return
    require(unit_directory_present(ARCHIVE.parent), INVALID)
    value = decode(read(ARCHIVE, 0))
    user = pwd.getpwnam('kurad')
    require(set(value) == {'schema', 'uid', 'gid', 'records'} and value['schema'] == 1
            and value['uid'] == user.pw_uid > 0 and value['gid'] == user.pw_gid > 0, INVALID)
    records = value['records']
    require(type(records) is dict and records and records.keys() <= SENDERS.keys(), INVALID)
    for name, content in records.items():
        check_record(name, content)
    inactive('kura.service')
    child = os.fork()
    if not child:
        try:
            # The versioned install is searchable only by kura-key-control. Pin the
            # sender's directory before dropping privileges; writes need no group grant.
            fd = os.open(HOME / 'data', os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                os.fchdir(fd)
            finally:
                os.close(fd)
            os.setgroups([])
            os.setgid(user.pw_gid)
            os.setuid(user.pw_uid)
            restore_files(Path('.'), records, user.pw_uid)
        except Exception as error:
            print(error, file=sys.stderr, flush=True)
            os._exit(1)
        os._exit(0)
    _, status = os.waitpid(child, 0)
    require(os.waitstatus_to_exitcode(status) == 0, INVALID)
    ARCHIVE.unlink()
    sync(ARCHIVE.parent)


if __name__ == '__main__':
    if sys.argv[1:] == ['restore']:
        restore()
    elif len(sys.argv) == 3 and sys.argv[1] == 'archive':
        archive(Path(sys.argv[2]))
    else:
        sys.exit(2)
