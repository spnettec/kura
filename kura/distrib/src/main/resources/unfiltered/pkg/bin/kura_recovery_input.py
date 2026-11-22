#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Stage an exact administrative recovery input outside the live snapshot set."""

from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import pwd
import re
import shutil
import stat

from kura_key_service import Failure, decode, digest, encode, fields, rename_no_replace, require

SPOOL = '/var/lib/kura-recovery-input'
ARTIFACT = 'snapshot'
RECEIPT = 'receipt.json'
NATIVE_ADMISSIONS = '.native-admissions'
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
                return self.original_locked(identity)

    def original_locked(self, identity):
        target = self.spool / identity
        pending = self.spool / ('.pending-' + identity)
        if os.path.lexists(target):
            require(not os.path.lexists(pending), 'UNSAFE_FILESYSTEM')
            return self.receipt(target, identity)
        if os.path.lexists(pending):
            self.manager.directory(pending, private=True)
            if os.path.lexists(pending / RECEIPT):
                return self.receipt(pending, identity) | {'state': 'RECOVERY_INPUT_READY'}
            return self.observation(identity, 'RECOVERY_INPUT_PENDING')
        attempt = self.spool / NATIVE_ADMISSIONS / identity / 'attempt.json'
        if os.path.lexists(attempt):
            self.manager.read(attempt, 4096)
            return self.observation(identity, 'RECOVERY_INPUT_ATTEMPTED')
        return self.observation(identity, 'RECOVERY_INPUT_ABSENT')

    def ensure_spool(self):
        try:
            self.lifecycle.directory(self.spool, private=True, create=True)
        except FileExistsError:
            self.lifecycle.directory(self.spool, private=True)
        self.lifecycle.sync(self.spool.parent)

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
    def copy_input(descriptor, directory, owner, expected, remaining, expected_size=None):
        metadata = lambda value: (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode, value.st_nlink,
                                  value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode) == 0o600
                and before.st_uid == owner and before.st_nlink == 1
                and fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
                and 0 < before.st_size <= MAX_SNAPSHOT,
                'UNSAFE_RECOVERY_INPUT')
        require(expected_size is None or before.st_size == expected_size, 'RECOVERY_INPUT_CHANGED')
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
            self.ensure_spool()
            with self.spool_lock(True):
                require(not os.path.lexists(self.spool / NATIVE_ADMISSIONS / identity), 'RECOVERY_INPUT_EXISTS')
                return self.stage_locked(identity, descriptor, expected, mode, policy, binding_sha)

    def stage_locked(self, identity, descriptor, expected, mode, policy, binding_sha, *,
                     source_uid=None, expected_size=None, recheck=None):
        manager = self.manager
        pending = self.spool / ('.pending-' + identity)
        target = self.spool / identity
        require(not os.path.lexists(pending) and not os.path.lexists(target), 'RECOVERY_INPUT_EXISTS')
        size = 0
        count = 0
        for child in self.spool.iterdir():
            if child.name == NATIVE_ADMISSIONS:
                manager.directory(child, private=True)
                continue
            count += 1
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
            owner = manager.owner if source_uid is None else source_uid
            size = self.copy_input(descriptor, pending, owner, expected, MAX_TOTAL - size, expected_size)
            validation = manager.validation_component()
            request = dict(schema=1, action='core-snapshot-validate', snapshotSha256=expected,
                           mode=mode, passwordPolicy=policy, expectedBindingSha256=binding_sha)
            with (pending / ARTIFACT).open('rb') as input_file:
                validation.validate(request, input_file.fileno(), manager.owner)
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                _, current_binding = validation.binding()
                require(current_binding == binding_sha, 'COHORT_CHANGED')
                if recheck is not None:
                    recheck()
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

    def prepare_main(self, identity):
        import kura_recovery_launch as launch

        require(RESTORE_ID.fullmatch(identity) is not None)
        manager = self.manager
        core = pwd.getpwnam('kurad')
        require(core.pw_uid > 0 and core.pw_gid > 0, 'UNMANAGED_CORE')
        base = self.lifecycle.path(launch.ROOT)
        target = base / identity
        pending = base / ('.pending-' + identity)
        with manager.lock(manager.state / 'admission.lock', False):
            manager.maintenance()
            manager.settled()
            with self.spool_lock(True):
                staged = self.spool / identity
                source = self.receipt(staged, identity)
                contents = manager.read(staged / ARTIFACT, MAX_SNAPSHOT)
                require(launch.digest(contents) == source['snapshotSha256'], 'UNSAFE_FILESYSTEM')
                validation = manager.validation_component()
                with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                    binding, fingerprint = validation.binding()
                    require(fingerprint == source['bindingSha256'], 'COHORT_CHANGED')
                    home = self.lifecycle.path('/opt/eclipse/kura').resolve(strict=True)
                    raw = self.lifecycle.read(home / launch.BOOTSTRAP, limit=16 << 20, private=False)
                    plan = {name: source[name] for name in ('schema', 'root', 'restoreId', 'bindingSha256',
                                                            'snapshotSha256', 'size', 'mode', 'passwordPolicy')}
                    plan.update({name: binding[name] for name in ('activeKeySha256', 'ringSha256', 'cohortSha256')})
                    plan['bootstrapSha256'] = launch.digest(raw)
                    self.prepare_projection(launch, base, pending, target, plan, contents, core)
        return self.observation(identity, 'MAIN_LAUNCH_PREPARED') | {'planSha256': launch.digest(launch.canonical(plan))}

    def prepare_projection(self, launch, base, pending, target, plan, contents, core):
        self.lifecycle.directory(base.parent)
        if not os.path.lexists(base):
            base.mkdir(mode=0o700)
            os.chown(base, 0, core.pw_gid)
            base.chmod(0o750)
            self.lifecycle.sync(base.parent)
        launch.directory(base, 0, core.pw_gid, 0o750)
        require(not os.path.lexists(pending) and not os.path.lexists(target), 'MAIN_LAUNCH_EXISTS')
        pending.mkdir(mode=0o700)
        self.lifecycle.sync(base)
        entries = {launch.SNAPSHOT: contents, launch.PLAN: launch.canonical(plan),
                   launch.REQUEST: launch.properties(target, plan)}
        for name, value in entries.items():
            launch.write(pending / name, value, 0o440, core.pw_gid)
        output = pending / launch.OUT
        output.mkdir(mode=0o700)
        os.chown(output, core.pw_uid, core.pw_gid)
        os.chown(pending, 0, core.pw_gid)
        pending.chmod(0o750)
        self.lifecycle.sync(pending)
        try:
            rename_no_replace(pending, target)
            self.lifecycle.sync(base)
        except OSError:
            raise Failure('UNKNOWN') from None

    def inspect_main(self, identity):
        import kura_recovery_launch as launch

        require(RESTORE_ID.fullmatch(identity) is not None)
        core = pwd.getpwnam('kurad')
        base = self.lifecycle.path(launch.ROOT)
        with self.manager.lock(self.manager.state / 'admission.lock', False):
            with self.spool_lock(False):
                if not os.path.lexists(base):
                    return self.observation(identity, 'MAIN_LAUNCH_ABSENT')
                launch.directory(base, 0, core.pw_gid, 0o750)
                pending = base / ('.pending-' + identity)
                if os.path.lexists(pending):
                    require(not os.path.lexists(base / identity), 'UNSAFE_FILESYSTEM')
                    self.manager.directory(pending)
                    return self.observation(identity, 'MAIN_LAUNCH_PREPARING')
                if not os.path.lexists(base / identity):
                    return self.observation(identity, 'MAIN_LAUNCH_ABSENT')
                path, plan = launch.projection(base, identity, core.pw_uid, core.pw_gid, self.lifecycle.root)
                result = self.observation(identity, 'MAIN_LAUNCH_PREPARED')
                result['planSha256'] = launch.digest(launch.canonical(plan))
                output = path / launch.OUT
                if not os.path.lexists(output / launch.CLAIM):
                    require(not any(output.iterdir()), 'UNSAFE_FILESYSTEM')
                    return result
                raw = launch.read(output / launch.CLAIM, core.pw_uid, core.pw_gid, 0o600, 4096)
                claim = decode(raw)
                fields(claim, {'schema', 'state', 'restoreId', 'planSha256', 'pid', 'startTicks', 'invocationId', 'bootId'})
                require(type(claim['schema']) is int and claim['schema'] == 1
                        and claim['state'] == 'MAIN_LAUNCH_CLAIMED' and claim['restoreId'] == identity
                        and claim['planSha256'] == result['planSha256']
                        and type(claim['pid']) is int and claim['pid'] > 1
                        and isinstance(claim['startTicks'], str) and re.fullmatch('[0-9]{1,20}', claim['startTicks'])
                        and isinstance(claim['invocationId'], str) and re.fullmatch('[0-9a-f]{32}', claim['invocationId'])
                        and isinstance(claim['bootId'], str) and RESTORE_ID.fullmatch('rec-' + claim['bootId']),
                        'UNSAFE_FILESYSTEM')
                result.update(state=claim['state'], invocation=claim)
                if os.path.lexists(output / launch.RECEIPT):
                    raw = launch.read(output / launch.RECEIPT, core.pw_uid, core.pw_gid, 0o600, 65536)
                    lines = [line.split('=', 1) for line in raw.decode('utf-8').splitlines()]
                    receipt = dict(lines)
                    require(len(lines) == len(receipt) and receipt.get('schema') == '1'
                            and receipt.get('restore.id') == identity, 'UNSAFE_FILESYSTEM')
                    status = receipt.get('status')
                    require(status in ('CM_APPLIED', 'RECOVERY_REQUIRED'), 'UNSAFE_FILESYSTEM')
                    if status == 'CM_APPLIED':
                        require(receipt.get('snapshot.sha256') == plan['snapshotSha256'], 'UNSAFE_FILESYSTEM')
                        for name in ('backup', 'applied'):
                            item = output / (launch.RECEIPT + f'.cm-{name}.aes')
                            value = launch.read(item, core.pw_uid, core.pw_gid, 0o600, 64 << 20)
                            require(launch.digest(value) == receipt.get(name + '.sha256'), 'UNSAFE_FILESYSTEM')
                    result.update(state=status, receiptSha256=launch.digest(raw))
                return result


def private_file(path, flags):
    return os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)


def command(manager, lifecycle, arguments):
    require(os.geteuid() == 0 and arguments, 'FORBIDDEN')
    recovery = RecoveryInput(manager, lifecycle)
    if arguments[0] == 'delegate':
        from kura_native_recovery_input import administrative_grant
        return administrative_grant(recovery, arguments[1:])
    controls = {'original': recovery.original, 'continue': recovery.continue_ready,
                'prepare-main': recovery.prepare_main, 'inspect-main': recovery.inspect_main}
    if arguments[0] in controls:
        require(len(arguments) == 2)
        return controls[arguments[0]](arguments[1])
    require(arguments[0] == 'stage' and len(arguments) == 7)
    _, identity, path, expected, mode, policy, binding_sha = arguments
    require(Path(path).is_absolute())
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        return recovery.stage(identity, descriptor, expected, mode, policy, binding_sha)
    finally:
        os.close(descriptor)
