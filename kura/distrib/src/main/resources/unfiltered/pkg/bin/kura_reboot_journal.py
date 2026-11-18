#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Durable decisions for the standalone Core's fixed host reboot request."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import stat

from kura_clock_journal import Refused, create, decode, digest, directory, encode, identifier, read, require, sync

PURPOSE = 'kura-host-reboot-v1'
MAX_OPERATIONS = 4096
HASH = re.compile(r'[0-9a-f]{64}')
FIELDS = {'schema', 'action', 'namespace', 'requestId', 'cohortSha256', 'bootId'}
DECISIONS = {
    'ACCEPTED': {'MANAGER_ACCEPTED'},
    'FAILED': {'NOT_STARTED', 'STALE_BOOT'},
    'UNKNOWN': {'DISPATCH_UNCONFIRMED'},
}


def sha256(value):
    require(isinstance(value, str) and HASH.fullmatch(value) is not None)
    return value


def request(value):
    require(type(value) is dict and set(value) == FIELDS and type(value['schema']) is int
            and value['schema'] == 1 and value['action'] == 'reboot')
    for field in ('namespace', 'requestId', 'bootId'):
        identifier(value[field])
    sha256(value['cohortSha256'])
    return value


def reference(value):
    return dict(schema=1, namespace=value['namespace'], requestId=value['requestId'],
                requestSha256=digest(value))


def marker(namespace):
    return dict(schema=1, namespace=identifier(namespace), purpose=PURPOSE)


def linux_boot_id():
    return identifier(Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip())


@contextmanager
def admission_lock(lock, owner, create_if_missing=False):
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    if create_if_missing:
        flags |= os.O_CREAT
    fd = os.open(lock, flags, 0o600)
    try:
        metadata = os.fstat(fd)
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == owner and metadata.st_nlink == 1
                and stat.S_IMODE(metadata.st_mode) == 0o600 and metadata.st_size == 0, 'UNSAFE_STATE')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused('BUSY') from None
        actual = lock.lstat()
        require((actual.st_dev, actual.st_ino) == (metadata.st_dev, metadata.st_ino), 'UNSAFE_STATE')
        yield
    finally:
        os.close(fd)


class RebootJournal:
    def __init__(self, root, namespace, cohort, boot_id=linux_boot_id):
        self.root = Path(root)
        self.namespace = identifier(namespace)
        self.cohort = sha256(cohort)
        self.owner = os.geteuid()
        self.boot_id = boot_id

    def initialize(self):
        """Provision a brand-new, already reserved state directory."""
        directory(self.root, self.owner)
        require(not any(self.root.iterdir()), 'STATE_ALREADY_PRESENT')
        # Reserve the namespace before publishing any writable admission path.
        create(self.root / 'namespace.json', marker(self.namespace))
        (self.root / 'operations').mkdir(mode=0o700)
        sync(self.root)
        fd = os.open(self.root / 'admission.lock', os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.fsync(fd)
        finally:
            os.close(fd)
        sync(self.root)

    @contextmanager
    def _locked(self):
        directory(self.root, self.owner)
        # Runtime never recreates an absent lock, marker, or operations directory.
        with admission_lock(self.root / 'admission.lock', self.owner):
            require(read(self.root / 'namespace.json', self.owner) == encode(marker(self.namespace)), 'FOREIGN_NAMESPACE')
            directory(self.root / 'operations', self.owner)
            yield

    def _intent(self, operation):
        directory(operation, self.owner)
        raw = read(operation / 'intent.json', self.owner)
        value = request(decode(raw))
        require(raw == encode(value) and value['namespace'] == self.namespace
                and value['requestId'] == operation.name, 'UNRESOLVED_INTENT')
        return value

    def _receipt(self, operation, value):
        receipt = dict(reference(value), bootId=value['bootId'])
        result = operation / 'result.json'
        try:
            raw = read(result, self.owner)
        except FileNotFoundError:
            return dict(receipt, state='UNKNOWN', reason='NO_DURABLE_RESULT')
        try:
            stored = decode(raw)
            require(raw == encode(stored) and set(stored) == set(receipt) | {'state', 'reason'}
                    and all(stored[key] == field for key, field in receipt.items())
                    and type(stored['schema']) is int and isinstance(stored['state'], str)
                    and isinstance(stored['reason'], str)
                    and stored['reason'] in DECISIONS.get(stored['state'], set()), 'UNRESOLVED_RESULT')
            return stored
        except Refused:
            return dict(receipt, state='UNKNOWN', reason='UNRESOLVED_RESULT')

    def _status(self, request_id, request_hash, boot_id):
        expected = dict(schema=1, namespace=self.namespace, requestId=request_id, requestSha256=request_hash)
        operation = self.root / 'operations' / request_id
        if not os.path.lexists(operation):
            return dict(expected, state='UNSEEN', reason='NO_LOCAL_INTENT')
        try:
            original = self._intent(operation)
        except (OSError, Refused):
            return dict(expected, state='UNKNOWN', reason='UNRESOLVED_INTENT')
        require(reference(original) == expected, 'CONFLICT')
        try:
            result = self._receipt(operation, original)
        except (OSError, Refused):
            result = dict(expected, bootId=original['bootId'], state='UNKNOWN', reason='UNRESOLVED_RESULT')
        return dict(result, observedBootId=boot_id)

    def status(self, namespace, request_id, request_hash):
        """Observe the original decision, without dispatch or journal mutation."""
        require(identifier(namespace) == self.namespace, 'FOREIGN_NAMESPACE')
        with self._locked():
            return self._status(identifier(request_id), sha256(request_hash), identifier(self.boot_id()))

    def _require_open(self, boot_id):
        require(not os.path.lexists(self.root / 'maintenance.json'), 'ADMISSION_CLOSED')
        entries = tuple((self.root / 'operations').iterdir())
        require(len(entries) < MAX_OPERATIONS, 'ADMISSION_CLOSED')
        for operation in entries:
            try:
                intent = self._intent(operation)
                receipt = self._receipt(operation, intent)
            except (OSError, Refused):
                raise Refused('ADMISSION_CLOSED') from None
            require(receipt['state'] != 'UNKNOWN', 'ADMISSION_CLOSED')
            require(receipt['state'] != 'ACCEPTED' or intent['bootId'] != boot_id, 'REBOOT_ALREADY_ACCEPTED')

    def context(self):
        with self._locked():
            boot_id = identifier(self.boot_id())
            try:
                self._require_open(boot_id)
                accepting = True
            except Refused:
                accepting = False
            return dict(schema=1, namespace=self.namespace, cohortSha256=self.cohort,
                        bootId=boot_id, acceptingWrites=accepting)

    def submit(self, value, dispatch):
        """Persist the original intent before the only possible dispatch."""
        value = request(value)
        require(value['namespace'] == self.namespace, 'FOREIGN_NAMESPACE')
        require(value['cohortSha256'] == self.cohort, 'UNPAIRED_CODE')
        with self._locked():
            boot_id = identifier(self.boot_id())
            request_id, request_hash = value['requestId'], digest(value)
            previous = self._status(request_id, request_hash, boot_id)
            if previous['state'] != 'UNSEEN':
                return previous
            require(value['bootId'] == boot_id, 'STALE_BOOT')
            self._require_open(boot_id)
            operation = self.root / 'operations' / request_id
            operation.mkdir(mode=0o700)
            sync(operation.parent)
            create(operation / 'intent.json', value)
            require(self._intent(operation) == value, 'UNRESOLVED_INTENT')
            if identifier(self.boot_id()) != boot_id:
                state, reason = 'FAILED', 'STALE_BOOT'
            else:
                # An exception leaves the durable intent unresolved. The dispatcher
                # must prove that a command did not start before returning NOT_STARTED.
                state, reason = dispatch()
                require((state, reason) in {('ACCEPTED', 'MANAGER_ACCEPTED'),
                                           ('FAILED', 'NOT_STARTED'), ('UNKNOWN', 'DISPATCH_UNCONFIRMED')},
                        'UNRESOLVED_RESULT')
            create(operation / 'result.json', dict(reference(value), bootId=boot_id, state=state, reason=reason))
            return self._status(request_id, request_hash, identifier(self.boot_id()))
