#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Stage an exact administrative recovery input outside the live snapshot set."""

from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat

from kura_key_service import Failure, decode, digest, encode, fields, rename_no_replace, require

SPOOL = '/var/lib/kura-recovery-input'
ARTIFACT = 'snapshot'
RECEIPT = 'receipt.json'
MAX_SNAPSHOT = 32 << 20
MAX_INPUTS = 16
MAX_TOTAL = 64 << 20
RESTORE_ID = re.compile(r'rec-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')


class RecoveryInput:
    def __init__(self, manager, lifecycle):
        self.manager = manager
        self.lifecycle = lifecycle
        self.spool = lifecycle.path(SPOOL)

    def root_identity(self):
        root = self.lifecycle.root.stat()
        return dict(device=str(root.st_dev), inode=str(root.st_ino))

    def original(self, identity):
        require(RESTORE_ID.fullmatch(identity) is not None)
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', False):
            if not os.path.lexists(self.spool):
                return self.observation(identity, 'RECOVERY_INPUT_ABSENT')
            with self.spool_lock(False):
                target = self.spool / identity
                pending = self.spool / ('.pending-' + identity)
                if os.path.lexists(target):
                    require(not os.path.lexists(pending), 'UNSAFE_FILESYSTEM')
                    return self.receipt(target, identity)
                if os.path.lexists(pending):
                    manager.directory(pending, private=True)
                    if os.path.lexists(pending / RECEIPT):
                        return self.receipt(pending, identity) | {'state': 'RECOVERY_INPUT_READY'}
                    return self.observation(identity, 'RECOVERY_INPUT_PENDING')
                return self.observation(identity, 'RECOVERY_INPUT_ABSENT')

    @contextmanager
    def spool_lock(self, exclusive):
        self.manager.directory(self.spool, private=True)
        fd = os.open(self.spool, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_NB | (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH))
            except BlockingIOError:
                raise Failure('BUSY') from None
            yield
        finally:
            os.close(fd)

    def observation(self, identity, state):
        return dict(schema=1, restoreId=identity, root=self.root_identity(), state=state)

    def receipt(self, target, identity):
        self.manager.directory(target, private=True)
        require({path.name for path in target.iterdir()} == {RECEIPT, ARTIFACT}, 'UNSAFE_FILESYSTEM')
        recorded = decode(self.manager.read(target / RECEIPT, 8192))
        fields(recorded, {'schema', 'restoreId', 'root', 'state', 'bindingSha256',
                          'snapshotSha256', 'size', 'mode', 'passwordPolicy'})
        expected = self.observation(identity, 'RECOVERY_INPUT_STAGED')
        require(type(recorded['schema']) is int and all(recorded[key] == val for key, val in expected.items()),
                'UNSAFE_FILESYSTEM')
        digest(recorded['bindingSha256'])
        digest(recorded['snapshotSha256'])
        self.check_format(recorded['mode'], recorded['passwordPolicy'])
        require(type(recorded['size']) is int and 0 < recorded['size'] <= MAX_SNAPSHOT, 'UNSAFE_FILESYSTEM')
        contents = self.manager.read(target / ARTIFACT, MAX_SNAPSHOT)
        require(len(contents) == recorded['size']
                and hashlib.sha256(contents).hexdigest() == recorded['snapshotSha256'], 'UNSAFE_FILESYSTEM')
        return recorded

    @staticmethod
    def check_format(mode, policy):
        require(mode in ('plain', 'aes-gcm') and policy in ('authenticated', 'legacy', 'logical-v1'))

    @staticmethod
    def copy_input(descriptor, directory, owner, expected, remaining):
        metadata = lambda value: (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode, value.st_nlink,
                                  value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode) == 0o600
                and before.st_uid == owner and before.st_nlink == 1
                and fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
                and 0 < before.st_size <= MAX_SNAPSHOT,
                'UNSAFE_RECOVERY_INPUT')
        require(before.st_size <= remaining, 'RESOURCE_EXHAUSTED')
        fingerprint = hashlib.sha256()
        count = 0
        with open(directory / ARTIFACT, 'xb', opener=private_file) as output:
            while count < before.st_size:
                data = os.pread(descriptor, min(before.st_size - count, 65536), count)
                require(bool(data), 'RECOVERY_INPUT_CHANGED')
                output.write(data)
                fingerprint.update(data)
                count += len(data)
            require(metadata(before) == metadata(os.fstat(descriptor)) and fingerprint.hexdigest() == expected,
                    'RECOVERY_INPUT_CHANGED')
            output.flush()
            os.fsync(output.fileno())
        return count

    def stage(self, identity, descriptor, expected, mode, policy, binding_sha):
        require(RESTORE_ID.fullmatch(identity) is not None)
        digest(expected)
        digest(binding_sha)
        self.check_format(mode, policy)
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', False):
            manager.maintenance()
            manager.settled()
            try:
                self.lifecycle.directory(self.spool, private=True, create=True)
            except FileExistsError:
                self.lifecycle.directory(self.spool, private=True)
            self.lifecycle.sync(self.spool.parent)
            with self.spool_lock(True):
                return self.stage_locked(identity, descriptor, expected, mode, policy, binding_sha)

    def stage_locked(self, identity, descriptor, expected, mode, policy, binding_sha):
        manager = self.manager
        pending = self.spool / ('.pending-' + identity)
        target = self.spool / identity
        require(not os.path.lexists(pending) and not os.path.lexists(target), 'RECOVERY_INPUT_EXISTS')
        size = 0
        for count, child in enumerate(self.spool.iterdir(), start=1):
            require(count < MAX_INPUTS, 'RESOURCE_EXHAUSTED')
            name = child.name
            require(RESTORE_ID.fullmatch(name.removeprefix('.pending-')) is not None, 'UNSAFE_FILESYSTEM')
            manager.directory(child, private=True)
            if os.path.lexists(child / ARTIFACT):
                item = (child / ARTIFACT).lstat()
                require(stat.S_ISREG(item.st_mode) and item.st_nlink == 1 and item.st_uid == manager.owner
                        and stat.S_IMODE(item.st_mode) == 0o600 and item.st_size <= MAX_SNAPSHOT, 'UNSAFE_FILESYSTEM')
                size += item.st_size
        # The reservation survives an interruption before publication.
        pending.mkdir(mode=0o700)
        try:
            self.lifecycle.sync(self.spool)
            size = self.copy_input(descriptor, pending, manager.owner, expected, MAX_TOTAL - size)
            validation = manager.validation_component()
            request = dict(schema=1, action='core-snapshot-validate', snapshotSha256=expected,
                           mode=mode, passwordPolicy=policy, expectedBindingSha256=binding_sha)
            with (pending / ARTIFACT).open('rb') as input_file:
                validation.validate(request, input_file.fileno(), manager.owner)
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                _, current_binding = validation.binding()
                require(current_binding == binding_sha, 'COHORT_CHANGED')
                result = self.observation(identity, 'RECOVERY_INPUT_STAGED')
                result.update(bindingSha256=binding_sha, snapshotSha256=expected,
                              mode=mode, passwordPolicy=policy, size=size)
                manager.atomic(pending / RECEIPT, encode(result), no_replace=True)
                return self.publish(pending, target, result)
        except (OSError, Failure):
            if os.path.lexists(pending / RECEIPT) or os.path.lexists(target):
                raise Failure('UNKNOWN') from None
            shutil.rmtree(pending)
            self.lifecycle.sync(self.spool)
            raise

    def publish(self, pending, target, result):
        try:
            self.lifecycle.sync(pending)
            rename_no_replace(pending, target)
            self.lifecycle.sync(self.spool)
        except OSError:
            raise Failure('UNKNOWN') from None
        return result

    def continue_ready(self, identity):
        require(RESTORE_ID.fullmatch(identity) is not None)
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', False):
            manager.maintenance()
            manager.settled()
            with self.spool_lock(True):
                pending = self.spool / ('.pending-' + identity)
                target = self.spool / identity
                require(not os.path.lexists(target), 'RECOVERY_INPUT_EXISTS')
                result = self.receipt(pending, identity)
                validation = manager.validation_component()
                with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                    _, current_binding = validation.binding()
                    require(current_binding == result['bindingSha256'], 'COHORT_CHANGED')
                    return self.publish(pending, target, result)


def private_file(path, flags):
    return os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)


def command(manager, lifecycle, arguments):
    require(os.geteuid() == 0 and arguments and arguments[0] in ('stage', 'original', 'continue'), 'FORBIDDEN')
    recovery = RecoveryInput(manager, lifecycle)
    if arguments[0] == 'original':
        require(len(arguments) == 2)
        return recovery.original(arguments[1])
    if arguments[0] == 'continue':
        require(len(arguments) == 2)
        return recovery.continue_ready(arguments[1])
    require(len(arguments) == 7)
    _, identity, path, expected, mode, policy, binding_sha = arguments
    require(Path(path).is_absolute())
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        return recovery.stage(identity, descriptor, expected, mode, policy, binding_sha)
    finally:
        os.close(descriptor)
