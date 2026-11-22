#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Private, append-only clock decisions. Never replay an admitted write."""
import base64
import binascii
import contextlib
import errno
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
MAX_CHRONY_CONFIGURATION_BYTES = 16384
MAX_OPERATIONS = 4096
MAX_SAMPLE_AGE_NS = 30 * 1000000000
COMMAND_FIELDS = {'schema', 'namespace', 'requestId', 'action', 'cohortSha256'}
RTC_NODE = re.compile(r'/dev/rtc(?:0|[1-9][0-9]{0,8})')
RTC_ALIASES = ('/dev/rtc', '/dev/misc/rtc')
CHRONY_UNITS = ('chrony.service', 'chronyd.service')
CHRONY_ACTIONS = {'start-chrony': 'start', 'stop-chrony': 'stop'}
OPERATIONS = {
    'adjust-realtime': ('adjust', 'correctionMillis', 'CLOCK_SET_RETURNED'),
    'sync-rtc': ('rtc', 'rtcDevice', 'RTC_SET_RETURNED'),
    'start-chrony': ('chrony-start', 'chronyStartUnit', 'CHRONY_STARTED'),
    'stop-chrony': ('chrony-stop', 'chronyStopUnit', 'CHRONY_STOPPED'),
    'step-chrony': ('chrony-step', 'chronyStepUnit', 'CHRONY_STEP_ACCEPTED'),
    'configure-chrony': ('chrony-config', 'chronyConfiguration', 'CHRONY_CONFIGURED'),
}
BINDING_FIELDS = {'sync-rtc': 'rtcBinding', **dict.fromkeys(CHRONY_ACTIONS, 'chronyBinding'),
                  'step-chrony': 'chronyStepBinding', 'configure-chrony': 'chronyConfigBinding'}


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


def chrony_configuration(value):
    require(type(value) is dict and set(value) == {'unit', 'content'}
            and value['unit'] in CHRONY_UNITS and isinstance(value['content'], str)
            and 0 < len(value['content']) <= 4 * ((MAX_CHRONY_CONFIGURATION_BYTES + 2) // 3))
    try:
        raw = base64.b64decode(value['content'], validate=True)
        raw.decode('utf-8', errors='strict')
    except (ValueError, binascii.Error):
        raise Refused('INVALID_ARGUMENT') from None
    require(0 < len(raw) <= MAX_CHRONY_CONFIGURATION_BYTES
            and base64.b64encode(raw).decode('ascii') == value['content'])
    return raw


def validate_argument(field, value):
    if field == 'correctionMillis':
        require(type(value) is int and -9223372036854 <= value <= 9223372036854)
    elif field == 'rtcDevice':
        require(isinstance(value, str) and (RTC_NODE.fullmatch(value) is not None or value in RTC_ALIASES))
    elif field == 'chronyConfiguration':
        chrony_configuration(value)
    else:
        require(isinstance(value, str) and value in CHRONY_UNITS)


def command(value):
    require(type(value) is dict and isinstance(value.get('action'), str) and value['action'] in OPERATIONS)
    _, argument, _ = OPERATIONS[value['action']]
    require(set(value) == COMMAND_FIELDS | {argument} and type(value['schema']) is int and value['schema'] == 1)
    identifier(value['namespace']); identifier(value['requestId'])
    validate_argument(argument, value[argument])
    require(isinstance(value['cohortSha256'], str) and re.fullmatch('[0-9a-f]{64}', value['cohortSha256']) is not None)
    return value


def terminal_receipt(result, reference, action):
    _, _, success = OPERATIONS[action]
    reasons = {'OS_ERROR', 'STALE_SAMPLE'}
    if action == 'adjust-realtime':
        reasons.add('CLOCK_RANGE')
    return (set(result) == set(reference) | {'state', 'reason', 'errno', 'observedRealtimeNs', 'observedMonotonicNs'}
            and all(result[key] == expected for key, expected in reference.items())
            and type(result['schema']) is int and type(result['errno']) is int and 0 <= result['errno'] <= 4095
            and type(result['observedRealtimeNs']) is int and type(result['observedMonotonicNs']) is int
            and ((result['state'] == 'APPLIED' and result['reason'] == success and result['errno'] == 0)
                 or (result['state'] == 'FAILED' and isinstance(result['reason'], str)
                     and result['reason'] in reasons and result['errno'] != 0)))


def valid_binding(binding):
    if type(binding) is not dict:
        return False
    if set(binding) == {'sha256'}:
        value = binding['sha256']
        return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None
    return set(binding) == {'errno'} and type(binding['errno']) is int and 0 < binding['errno'] <= 4095


def identity(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_uid, metadata.st_gid, metadata.st_mode,
            metadata.st_nlink, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def directory(path, owner, mode=0o700):
    metadata = path.lstat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == owner
            and stat.S_IMODE(metadata.st_mode) == mode, 'UNSAFE_STATE')


def read(path, owner, mode=0o600, maximum=MAX_BYTES, *, durable=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == mode and before.st_size <= maximum, 'UNSAFE_STATE')
        with os.fdopen(os.dup(fd), 'rb') as source:
            value = source.read(maximum + 1)
        if durable:
            os.fsync(fd)
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

    def read_prepared(self, path, reference, action):
        prepared = decode(read(path / 'prepared-context.json', self.owner))
        keys = set(reference) | {'bootId', 'preparedMonotonicNs'}
        field = BINDING_FIELDS.get(action)
        # Completed legacy RTC records may predate their device binding.
        if field and (action != 'sync-rtc' or field in prepared):
            keys.add(field)
            require(valid_binding(prepared.get(field)), 'UNRESOLVED_PREPARE')
        require(set(prepared) == keys and all(prepared[key] == value for key, value in reference.items())
                and type(prepared['schema']) is int
                and type(prepared['preparedMonotonicNs']) is int and prepared['preparedMonotonicNs'] >= 0,
                'UNRESOLVED_PREPARE')
        identifier(prepared['bootId'])
        return prepared

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
            prepared = self.read_prepared(path, result, intent['action'])
        except (OSError, Refused):
            return dict(result, state='UNKNOWN', reason='UNRESOLVED_PREPARE')
        if not os.path.lexists(path / 'commit-intent.json'):
            require(not os.path.lexists(path / 'result.json'), 'UNRESOLVED_JOURNAL')
            if intent['action'] == 'sync-rtc' and 'rtcBinding' not in prepared:
                return dict(result, state='UNKNOWN', reason='UNRESOLVED_PREPARE')
            return dict(result, state='PREPARED', reason='NOT_COMMITTED')
        try:
            require(decode(read(path / 'commit-intent.json', self.owner)) == result, 'UNRESOLVED_JOURNAL')
        except (OSError, Refused):
            return dict(result, state='UNKNOWN', reason='UNRESOLVED_COMMIT')
        if not os.path.lexists(path / 'result.json'):
            return dict(result, state='UNKNOWN', reason='NO_DURABLE_RESULT')
        try:
            receipt = decode(read(path / 'result.json', self.owner))
            require(terminal_receipt(receipt, result, intent['action']))
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

    def prepare(self, value, bind=None):
        value = command(value)
        require(value['namespace'] == self.namespace(), 'FOREIGN_NAMESPACE')
        request_id = value['requestId']; request_hash = digest(value)
        path = self.root / 'operations' / request_id
        if os.path.lexists(path):
            return self.status(value['namespace'], request_id, request_hash)
        require(self.accepting(), 'ADMISSION_CLOSED')
        reference = dict(schema=1, namespace=value['namespace'], requestId=request_id, requestSha256=request_hash)
        prepared = dict(reference, bootId=identifier(self.boot_id()), preparedMonotonicNs=time.monotonic_ns())
        field = BINDING_FIELDS.get(value['action'])
        if field:
            require(callable(bind), 'UNRESOLVED_PREPARE')
            try:
                binding = dict(sha256=bind(value[OPERATIONS[value['action']][1]]))
            except OSError as error:
                binding = dict(errno=error.errno)
            require(valid_binding(binding), 'UNRESOLVED_PREPARE')
            prepared[field] = binding
        path.mkdir(mode=0o700); sync(path.parent)
        create(path / 'intent.json', value)
        require(read(path / 'intent.json', self.owner) == encode(value), 'UNRESOLVED_JOURNAL')
        create(path / 'prepared-context.json', prepared)
        return self.status(value['namespace'], request_id, request_hash)

    def commit(self, value, actuate):
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
        prepared = self.read_prepared(path, receipt, value['action'])
        field = BINDING_FIELDS.get(value['action'])
        binding = prepared[field] if field else None
        create(path / 'commit-intent.json', receipt)
        age = time.monotonic_ns() - prepared['preparedMonotonicNs']
        _, field, success = OPERATIONS[value['action']]
        argument = value[field]
        if field == 'correctionMillis':
            argument = time.time_ns() + argument * 1000000
        if prepared['bootId'] != identifier(self.boot_id()) or not 0 <= age <= MAX_SAMPLE_AGE_NS:
            receipt.update(state='FAILED', reason='STALE_SAMPLE', errno=errno.ESTALE)
        elif field == 'correctionMillis' and not 0 <= argument <= 9223372036854775807:
            receipt.update(state='FAILED', reason='CLOCK_RANGE', errno=errno.EINVAL)
        elif binding is not None and 'errno' in binding:
            receipt.update(state='FAILED', reason='OS_ERROR', errno=binding['errno'])
        else:
            try:
                if binding is None:
                    actuate(argument)
                else:
                    actuate(argument, binding['sha256'])
                receipt.update(state='APPLIED', reason=success, errno=0)
            except OSError as error:
                require(type(error.errno) is int and 0 < error.errno <= 4095, 'UNRESOLVED_JOURNAL')
                receipt.update(state='FAILED', reason='OS_ERROR', errno=error.errno)
        receipt.update(observedRealtimeNs=time.time_ns(), observedMonotonicNs=time.monotonic_ns())
        create(path / 'result.json', receipt)
        return self.status(value['namespace'], request_id, request_hash)
