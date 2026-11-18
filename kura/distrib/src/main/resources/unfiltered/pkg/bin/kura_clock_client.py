#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Core's fixed clock sender; persist first and never resend a write."""
import fcntl
import os
from pathlib import Path
import pwd
import socket
import stat
import struct
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import HOME, SOCKET, Policy, receive, send
from kura_clock_journal import (Refused, command, create, decode, digest, directory, encode,
                                identifier, read, require, sync, terminal_receipt, validate_argument,
                                MAX_BYTES, OPERATIONS)

REQUEST_OPERATIONS = {field: action for action, (_, field, _) in OPERATIONS.items()}


def caller_uid():
    owner = os.geteuid()
    require(owner > 0 and os.getuid() == owner, 'UNSAFE_CALLER')
    return owner


def root_exchange(policy, value):
    caller_uid()
    policy.check()
    for path in (SOCKET.parent.parent, SOCKET.parent):
        metadata = path.lstat()
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0
                and not metadata.st_mode & 0o022, 'UNSAFE_LISTENER')
    metadata = SOCKET.lstat()
    require(stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == 0
            and metadata.st_gid == pwd.getpwnam('kurad').pw_gid
            and stat.S_IMODE(metadata.st_mode) == 0o660, 'UNSAFE_LISTENER')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(5)
        stream.connect(str(SOCKET))
        pid, uid, _ = struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        # The Root listener was bound by PID1 and inherited by the non-Root actor.
        require(pid == 1 and uid == 0, 'UNSAFE_LISTENER')
        send(stream, value); stream.shutdown(socket.SHUT_WR)
        reply = receive(stream)
    require(type(reply.get('ok')) is bool, 'INVALID_REPLY')
    if not reply['ok']:
        require(set(reply) == {'ok', 'reason'} and isinstance(reply['reason'], str), 'INVALID_REPLY')
        raise Refused(reply['reason'])
    require(set(reply) == {'ok', 'result'} and type(reply['result']) is dict, 'INVALID_REPLY')
    return reply['result']


class Client:
    def __init__(self, data_directory, exchange=None, policy=None):
        self.policy = policy or Policy()
        self.exchange = exchange or (lambda value: root_exchange(self.policy, value))
        self.owner = caller_uid()
        data = Path(data_directory)
        require(data.is_absolute(), 'UNSAFE_STATE')
        metadata = data.lstat()
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == self.owner
                and not metadata.st_mode & 0o022, 'UNSAFE_STATE')
        self.root = data / 'clock-broker'
        if not os.path.lexists(self.root):
            self.root.mkdir(mode=0o700); sync(data)
        directory(self.root, self.owner)

    def finish(self, pending, result):
        completed = self.root / 'completed'
        if not os.path.lexists(completed):
            completed.mkdir(mode=0o700); sync(self.root)
        directory(completed, self.owner)
        value = dict(schema=1, command=pending, result=result)
        path = completed / (pending['requestId'] + '.json')
        if os.path.lexists(path):
            require(read(path, self.owner) == encode(value), 'UNRESOLVED_LOCAL_RECEIPT')
        else:
            create(path, value)
        require(read(self.root / 'pending.json', self.owner) == encode(pending), 'UNRESOLVED_LOCAL_INTENT')
        (self.root / 'pending.json').unlink(); sync(self.root)

    def update(self, correction_millis):
        return self.submit('adjust-realtime', correction_millis)

    def submit(self, action, argument):
        suffix, field, _ = OPERATIONS[action]
        validate_argument(field, argument)
        lock = self.root / 'sender.lock'
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            metadata = os.fstat(fd)
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == self.owner and metadata.st_nlink == 1
                    and stat.S_IMODE(metadata.st_mode) == 0o600 and metadata.st_size == 0, 'UNSAFE_STATE')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused('BUSY') from None
            self.policy.check()
            context = self.exchange(dict(schema=1, action='context'))
            require(set(context) == {'schema', 'state', 'namespace', 'cohortSha256', 'acceptingWrites'}
                    and type(context['schema']) is int and context['schema'] == 1 and context['state'] == 'READY'
                    and type(context['acceptingWrites']) is bool and context['cohortSha256'] == self.policy.cohort, 'UNPAIRED_CODE')
            namespace = identifier(context['namespace'])
            path = self.root / 'pending.json'
            current_sample = not os.path.lexists(path)
            if not current_sample:
                pending = command(decode(read(path, self.owner)))
                # Never query this old ID at another Root, or switch identities.
                require(pending['namespace'] == namespace, 'FOREIGN_NAMESPACE')
                result = self.exchange(dict(schema=1, action='status', namespace=namespace,
                                            requestId=pending['requestId'], requestSha256=digest(pending)))
            else:
                require(context['acceptingWrites'], 'ADMISSION_CLOSED')
                pending = command(dict(schema=1, namespace=namespace, requestId=str(uuid.uuid4()),
                                       action=action, cohortSha256=self.policy.cohort, **{field: argument}))
                create(path, pending)
                require(read(path, self.owner) == encode(pending), 'UNRESOLVED_LOCAL_INTENT')
                # Prepare has no clock syscall. Never resend it after loss;
                # subsequent invocations query the original namespace/ID.
                result = self.exchange(dict(pending, action='prepare-' + suffix))
            suffix, field, _ = OPERATIONS[pending['action']]
            issued = self.root / 'issued'
            if not os.path.lexists(issued):
                issued.mkdir(mode=0o700); sync(self.root)
            directory(issued, self.owner)
            issued_path = issued / (pending['requestId'] + '.json')
            issued_value = dict(schema=1, namespace=namespace, requestId=pending['requestId'], requestSha256=digest(pending))
            if os.path.lexists(issued_path):
                require(read(issued_path, self.owner) == encode(issued_value), 'UNRESOLVED_LOCAL_COMMIT')
            if result.get('state') == 'PREPARED' and not os.path.lexists(issued_path):
                # Only a known, original uncommitted prepare may issue its first
                # commit. Record before sending so a lost commit is never retried.
                require(set(result) == {'schema', 'namespace', 'requestId', 'requestSha256', 'state', 'reason'}
                        and type(result['schema']) is int and result['schema'] == 1 and result['namespace'] == namespace
                        and result['requestId'] == pending['requestId'] and result['requestSha256'] == digest(pending)
                        and result['reason'] == 'NOT_COMMITTED', 'INVALID_REPLY')
                require(pending['cohortSha256'] == self.policy.cohort, 'UNPAIRED_PREPARE')
                create(issued_path, issued_value)
                result = self.exchange(dict(pending, action='commit-' + suffix))
            require(result.get('schema') == 1 and type(result.get('schema')) is int
                    and result.get('namespace') == namespace and result.get('requestId') == pending['requestId']
                    and result.get('requestSha256') == digest(pending)
                    and result.get('state') in ('APPLIED', 'FAILED', 'UNKNOWN', 'UNSEEN', 'PREPARED'), 'INVALID_REPLY')
            if result['state'] in ('APPLIED', 'FAILED'):
                require(terminal_receipt(result, issued_value, pending['action']), 'INVALID_REPLY')
                self.finish(pending, result)
            else:
                require(set(result) == {'schema', 'namespace', 'requestId', 'requestSha256', 'state', 'reason'}
                        and result['reason'] in ('NO_LOCAL_INTENT', 'UNRESOLVED_INTENT', 'NO_DURABLE_RESULT', 'UNRESOLVED_RESULT',
                                                 'UNRESOLVED_COMMIT', 'UNRESOLVED_PREPARE', 'NOT_COMMITTED'),
                        'INVALID_REPLY')
            return dict(schema=1, namespace=namespace, requestId=pending['requestId'], **{field: pending[field]},
                        state='UNKNOWN' if result['state'] in ('UNSEEN', 'PREPARED') else result['state'],
                        reason=result['reason'], currentSample=current_sample)
        finally:
            os.close(fd)


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 3 and sys.argv[:2] == [str(HOME / 'bin/kura_clock_client.py'), 'client'], 'INVALID_ENTRYPOINT')
        value = decode(sys.stdin.buffer.read(MAX_BYTES + 1))
        require(len(value) == 1)
        field, argument = next(iter(value.items()))
        if field == 'inspectChrony':
            require(argument is True)
            result = root_exchange(Policy(), dict(schema=1, action='chrony-status'))
        else:
            require(field in REQUEST_OPERATIONS)
            result = Client(sys.argv[2]).submit(REQUEST_OPERATIONS[field], argument)
        print(encode(result).decode('ascii'), flush=True)
    except (Refused, OSError, ValueError, KeyError) as error:
        print(error.reason if isinstance(error, Refused) else 'UNRESOLVED_OR_UNAVAILABLE', file=sys.stderr)
        raise SystemExit(1)
