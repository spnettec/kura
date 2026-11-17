#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Private, append-only wall-clock decisions. Never replay an admitted write."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

MAX_BYTES = 65536
MAX_OPERATIONS = 4096
MAX_SAMPLE_AGE_NS = 30 * 1000000000
COMMAND_FIELDS = {'schema', 'namespace', 'requestId', 'action', 'correctionMillis', 'cohortSha256'}


class Refused(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def require(value, reason='INVALID_ARGUMENT'):
    if not value:
        raise Refused(reason)


def identifier(value):
    try:
        require(isinstance(value, str) and str(uuid.UUID(value)) == value)
    except (ValueError, AttributeError):
        raise Refused('INVALID_ARGUMENT') from None
    return value


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def decode(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES)
    try:
        value = json.loads(raw.decode('ascii'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(Refused('INVALID_ARGUMENT')))
    except (ValueError, UnicodeError, RecursionError):
        raise Refused('INVALID_ARGUMENT') from None
    require(type(value) is dict)
    return value


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('ascii')


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def command(value):
    require(type(value) is dict and set(value) == COMMAND_FIELDS and type(value['schema']) is int and value['schema'] == 1)
    identifier(value['namespace']); identifier(value['requestId'])
    require(value['action'] == 'adjust-realtime' and type(value['correctionMillis']) is int
            and -9223372036854 <= value['correctionMillis'] <= 9223372036854)
    require(isinstance(value['cohortSha256'], str) and re.fullmatch('[0-9a-f]{64}', value['cohortSha256']) is not None)
    return value


def identity(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_uid, metadata.st_gid, metadata.st_mode,
            metadata.st_nlink, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def directory(path, owner, mode=0o700):
    metadata = path.lstat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == owner
            and stat.S_IMODE(metadata.st_mode) == mode, 'UNSAFE_STATE')


def read(path, owner, mode=0o600, maximum=MAX_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == mode and before.st_size <= maximum, 'UNSAFE_STATE')
        with os.fdopen(os.dup(fd), 'rb') as source:
            value = source.read(maximum + 1)
        require(len(value) == before.st_size and identity(before) == identity(os.fstat(fd))
                == identity(path.lstat()), 'UNSAFE_STATE')
        return value
    finally:
        os.close(fd)


def sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create(path, value, mode=0o600):
    """An interrupted write stays present and unresolved; never replace it."""
    raw = encode(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
    try:
        os.fchmod(fd, mode)
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            require(count > 0, 'IO_ERROR')
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    sync(path.parent)


class Journal:
    def __init__(self, root, owner=None, boot_id=None):
        self.root = Path(root)
        self.owner = os.geteuid() if owner is None else owner
        self.boot_id = boot_id or (lambda: Path('/proc/sys/kernel/random/boot_id').read_text().strip())
        directory(self.root, self.owner)

    @contextlib.contextmanager
    def lock(self):
        path = self.root / 'admission.lock'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            metadata = os.fstat(fd)
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == self.owner and metadata.st_nlink == 1
                    and stat.S_IMODE(metadata.st_mode) == 0o600 and metadata.st_size == 0, 'UNSAFE_STATE')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused('BUSY') from None
            yield
        finally:
            os.close(fd)

    def namespace(self):
        marker = self.root / 'namespace.json'
        operations = self.root / 'operations'
        if not os.path.lexists(marker):
            # No identity replacement when anything other than the empty lock
            # already exists, including an interrupted namespace publication.
            require(set(p.name for p in self.root.iterdir()) <= {'admission.lock'}, 'UNRESOLVED_NAMESPACE')
            create(marker, dict(schema=1, namespace=str(uuid.uuid4()), purpose='kura-wall-clock-v1'))
        value = decode(read(marker, self.owner))
        require(set(value) == {'schema', 'namespace', 'purpose'} and type(value['schema']) is int
                and value['schema'] == 1 and value['purpose'] == 'kura-wall-clock-v1', 'UNRESOLVED_NAMESPACE')
        identifier(value['namespace'])
        if not os.path.lexists(operations):
            operations.mkdir(mode=0o700); sync(self.root)
        directory(operations, self.owner)
        return value['namespace']

    def status(self, namespace, request_id, request_hash):
        # Namespace admission always precedes looking up a caller's old ID.
        require(identifier(namespace) == self.namespace(), 'FOREIGN_NAMESPACE')
        identifier(request_id)
        require(isinstance(request_hash, str) and re.fullmatch('[0-9a-f]{64}', request_hash) is not None)
        path = self.root / 'operations' / request_id
        result = dict(schema=1, namespace=namespace, requestId=request_id, requestSha256=request_hash)
        if not os.path.lexists(path):
            return dict(result, state='UNSEEN', reason='NO_LOCAL_INTENT')
        directory(path, self.owner)
        try:
            intent = command(decode(read(path / 'intent.json', self.owner)))
            require(intent['namespace'] == namespace and intent['requestId'] == request_id, 'UNRESOLVED_JOURNAL')
        except (OSError, Refused):
            return dict(result, state='UNKNOWN', reason='UNRESOLVED_INTENT')
        require(digest(intent) == request_hash, 'CONFLICT')
        try:
            prepared = decode(read(path / 'prepared-context.json', self.owner))
            require(set(prepared) == set(result) | {'bootId', 'preparedMonotonicNs'}
                    and all(prepared[key] == value for key, value in result.items())
                    and type(prepared['preparedMonotonicNs']) is int and prepared['preparedMonotonicNs'] >= 0)
            identifier(prepared['bootId'])
        except (OSError, Refused):
            return dict(result, state='UNKNOWN', reason='UNRESOLVED_PREPARE')
        if not os.path.lexists(path / 'commit-intent.json'):
            require(not os.path.lexists(path / 'result.json'), 'UNRESOLVED_JOURNAL')
            return dict(result, state='PREPARED', reason='NOT_COMMITTED')
        try:
            require(decode(read(path / 'commit-intent.json', self.owner)) == result, 'UNRESOLVED_JOURNAL')
        except (OSError, Refused):
            return dict(result, state='UNKNOWN', reason='UNRESOLVED_COMMIT')
        if not os.path.lexists(path / 'result.json'):
            return dict(result, state='UNKNOWN', reason='NO_DURABLE_RESULT')
        try:
            receipt = decode(read(path / 'result.json', self.owner))
            require(set(receipt) == set(result) | {'state', 'reason', 'errno', 'observedRealtimeNs', 'observedMonotonicNs'})
            require(all(receipt[key] == value for key, value in result.items())
                    and receipt['state'] in ('APPLIED', 'FAILED')
                    and receipt['reason'] in ('CLOCK_SET_RETURNED', 'OS_ERROR', 'STALE_SAMPLE', 'CLOCK_RANGE')
                    and type(receipt['errno']) is int and 0 <= receipt['errno'] <= 4095
                    and type(receipt['observedRealtimeNs']) is int and type(receipt['observedMonotonicNs']) is int)
            require((receipt['state'], receipt['reason'], receipt['errno'] == 0) in
                    (('APPLIED', 'CLOCK_SET_RETURNED', True), ('FAILED', 'OS_ERROR', False),
                     ('FAILED', 'STALE_SAMPLE', False), ('FAILED', 'CLOCK_RANGE', False)))
            return receipt
        except (OSError, Refused):
            return dict(result, state='UNKNOWN', reason='UNRESOLVED_RESULT')

    def accepting(self):
        namespace = self.namespace()
        if os.path.lexists(self.root / 'maintenance.json'):
            return False
        entries = list((self.root / 'operations').iterdir())
        if len(entries) >= MAX_OPERATIONS:
            return False
        try:
            for entry in entries:
                identifier(entry.name); directory(entry, self.owner)
                prior = command(decode(read(entry / 'intent.json', self.owner)))
                if self.status(namespace, entry.name, digest(prior))['state'] not in ('APPLIED', 'FAILED'):
                    return False
        except (OSError, Refused):
            return False
        return True

    def prepare(self, value):
        value = command(value)
        require(value['namespace'] == self.namespace(), 'FOREIGN_NAMESPACE')
        request_id = value['requestId']; request_hash = digest(value)
        path = self.root / 'operations' / request_id
        if os.path.lexists(path):
            return self.status(value['namespace'], request_id, request_hash)
        require(self.accepting(), 'ADMISSION_CLOSED')
        path.mkdir(mode=0o700); sync(path.parent)
        create(path / 'intent.json', value)
        require(read(path / 'intent.json', self.owner) == encode(value), 'UNRESOLVED_JOURNAL')
        create(path / 'prepared-context.json', dict(schema=1, namespace=value['namespace'], requestId=request_id,
               requestSha256=request_hash, bootId=identifier(self.boot_id()),
               preparedMonotonicNs=time.monotonic_ns()))
        return self.status(value['namespace'], request_id, request_hash)

    def commit(self, value, adjust_realtime):
        value = command(value)
        require(value['namespace'] == self.namespace(), 'FOREIGN_NAMESPACE')
        request_id = value['requestId']; request_hash = digest(value)
        previous = self.status(value['namespace'], request_id, request_hash)
        require(previous['state'] != 'UNSEEN', 'NOT_PREPARED')
        if previous['state'] != 'PREPARED':
            return previous
        # The original immutable prepare must match every input, including its
        # source cohort, before the first and only clock syscall admission.
        path = self.root / 'operations' / request_id
        require(read(path / 'intent.json', self.owner) == encode(value), 'CONFLICT')
        receipt = dict(schema=1, namespace=value['namespace'], requestId=request_id, requestSha256=request_hash)
        create(path / 'commit-intent.json', receipt)
        prepared = decode(read(path / 'prepared-context.json', self.owner))
        age = time.monotonic_ns() - prepared['preparedMonotonicNs']
        target = time.time_ns() + value['correctionMillis'] * 1000000
        if prepared['bootId'] != identifier(self.boot_id()) or not 0 <= age <= MAX_SAMPLE_AGE_NS:
            receipt.update(state='FAILED', reason='STALE_SAMPLE', errno=116)
        elif not 0 <= target <= 9223372036854775807:
            receipt.update(state='FAILED', reason='CLOCK_RANGE', errno=22)
        else:
            try:
                adjust_realtime(target)
                receipt.update(state='APPLIED', reason='CLOCK_SET_RETURNED', errno=0)
            except OSError as error:
                require(type(error.errno) is int and 0 < error.errno <= 4095, 'UNRESOLVED_JOURNAL')
                receipt.update(state='FAILED', reason='OS_ERROR', errno=error.errno)
        receipt.update(observedRealtimeNs=time.time_ns(), observedMonotonicNs=time.monotonic_ns())
        create(path / 'result.json', receipt)
        return self.status(value['namespace'], request_id, request_hash)
