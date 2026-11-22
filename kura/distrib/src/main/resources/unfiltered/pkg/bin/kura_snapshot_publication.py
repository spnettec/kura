#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Publish the stopped Main's exact staged input as an ordinary snapshot."""

import os
import re
import subprocess
import time

from kura_key_service import Failure, LifecycleRefused, Refused, digest, encode, fields, rename_no_replace, require
from kura_key_store import KEY_PATH, RING_PATH
import kura_recovery_launch as launch


class SnapshotPublication:
    INTENT = 'snapshot-publication-intent'
    READY = 'snapshot-publication-ready'
    RECEIPT = 'snapshot-publication-receipt'

    def __init__(self, controller):
        self.controller = controller
        self.manager = controller.manager
        self.lifecycle = controller.lifecycle
        self.core = controller.core
        self.directory = self.lifecycle.path(launch.NORMAL_SNAPSHOTS)

    def policy(self, plan):
        home = self.lifecycle.path('/opt/eclipse/kura').resolve(strict=True)
        jar = home / launch.BOOTSTRAP
        require(launch.digest(self.lifecycle.read(jar, limit=16 << 20, private=False)) == plan['bootstrapSha256'],
                'COHORT_CHANGED')
        command = ['/usr/bin/java', '-Xmx64m', '-cp', str(jar),
                   'org.eclipse.kura.tools.recovery.SnapshotStorePolicy', str(home / 'framework/kura.properties'),
                   str(home / 'user/kura_custom.properties')]
        result = subprocess.run(command, cwd='/', env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
                                capture_output=True, text=True, timeout=10, check=False)
        match = re.fullmatch(r'(plain|aes-gcm) ([0-9a-f]{64}) ([0-9a-f]{64})\n', result.stdout)
        require(result.returncode == 0 and match is not None, 'SNAPSHOT_POLICY_MISMATCH')
        return match[1], launch.digest(result.stdout.encode('ascii'))

    def convert(self, source, plan, target_mode):
        """Rewrap the staged artifact into the ordinary directory's exact current format.

        Runs before any journal record exists, so a refused conversion leaves no intent.
        The XML payload itself is never rewritten: legacy representations are converted
        by the real Main on load, not here.
        """
        require(plan['mode'] != target_mode and plan['mode'] in ('plain', 'aes-gcm')
                and target_mode in ('plain', 'aes-gcm'), 'SNAPSHOT_CONVERSION_REFUSED')
        home = self.lifecycle.path('/opt/eclipse/kura').resolve(strict=True)
        command = ['/usr/bin/java', '-Xms16m', '-Xmx256m', '-XX:MaxMetaspaceSize=64m',
                   '-XX:ActiveProcessorCount=1', '-XX:+UseSerialGC', '-XX:+DisableAttachMechanism',
                   '-XX:+PerfDisableSharedMem', '-jar', str(home / launch.BOOTSTRAP), 'convert',
                   '--input', str(source), '--from-mode', plan['mode'], '--to-mode', target_mode,
                   '--password-policy', plan['passwordPolicy'], '--expected-input-sha256', plan['snapshotSha256']]
        if plan['ringSha256'] is None:
            command += ['--key-file', KEY_PATH]
        else:
            command += ['--keyring-file', RING_PATH, '--keyring-sha256', plan['ringSha256']]
        try:
            result = subprocess.run(command, cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C'},
                                    capture_output=True, timeout=90, check=False, close_fds=True)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise Failure('SNAPSHOT_CONVERSION_REFUSED') from None
        require(result.returncode == 0 and not result.stderr
                and 0 < len(result.stdout) <= launch.MAX_SNAPSHOT, 'SNAPSHOT_CONVERSION_REFUSED')
        return result.stdout

    def paths(self, identity, number):
        launch.snapshot_number(number)
        return self.directory / ('recovery-import-' + identity + '.pending'), self.directory / f'snapshot_{number}.xml'

    def directory_identity(self):
        launch.directory(self.directory, self.core.pw_uid, self.core.pw_gid, 0o700)
        return launch.root_identity(self.directory)

    def latest(self):
        return max((launch.snapshot_number(path.name[9:-4]) for path in self.directory.glob('snapshot_*.xml')),
                   default=-1)

    def fingerprint(self, path, expected):
        before = path.lstat()
        raw = launch.read(path, self.core.pw_uid, self.core.pw_gid, 0o600, launch.MAX_SNAPSHOT)
        after = path.lstat()
        require(os.path.samestat(before, after) and before.st_ctime_ns == after.st_ctime_ns
                and len(raw) == expected['publishedSize'] and launch.digest(raw) == expected['publishedSha256'],
                'CONFLICT')
        return dict(device=str(after.st_dev), inode=str(after.st_ino))

    def journal(self, identity):
        return self.controller.journal(identity)

    def records(self, identity):
        intent, ready, receipt = (self.controller.load(identity, name) for name in
                                  (self.INTENT, self.READY, self.RECEIPT))
        if intent is None:
            require(ready is receipt is None, 'UNSAFE_FILESYSTEM')
            return None, None, None
        fields(intent, {'schema', 'root', 'restoreId', 'state', 'selectionSha256', 'planSha256', 'sourceReceiptSha256',
                        'snapshotId', 'snapshotSha256', 'size', 'publishedSha256', 'publishedSize', 'publishedMode',
                        'directory', 'policySha256'})
        require(intent['state'] == 'ORDINARY_SNAPSHOT_INTENT', 'UNSAFE_FILESYSTEM')
        self.paths(identity, intent['snapshotId'])
        for name in ('selectionSha256', 'planSha256', 'sourceReceiptSha256', 'policySha256', 'snapshotSha256',
                     'publishedSha256'):
            digest(intent[name])
        require(type(intent['size']) is int and 0 < intent['size'] <= launch.MAX_SNAPSHOT
                and type(intent['publishedSize']) is int and 0 < intent['publishedSize'] <= launch.MAX_SNAPSHOT
                and intent['publishedMode'] in ('plain', 'aes-gcm'),
                'UNSAFE_FILESYSTEM')
        if ready is None:
            require(receipt is None, 'UNSAFE_FILESYSTEM')
        else:
            fields(ready, intent.keys() | {'file'})
            require(ready == intent | {'state': 'ORDINARY_SNAPSHOT_READY', 'file': ready['file']}, 'UNSAFE_FILESYSTEM')
            if receipt is not None:
                require(receipt == ready | {'state': 'ORDINARY_SNAPSHOT_PUBLISHED'}, 'UNSAFE_FILESYSTEM')
        return intent, ready, receipt

    def observed(self, identity, intent, ready):
        pending, target = self.paths(identity, intent['snapshotId'])
        uncertain = intent | {'state': 'ORDINARY_SNAPSHOT_UNKNOWN'}
        if ready is None:
            return uncertain
        try:
            require(self.directory_identity() == intent['directory'], 'CONFLICT')
            exists_pending, exists_target = os.path.lexists(pending), os.path.lexists(target)
            require(exists_pending != exists_target, 'CONFLICT')
            evidence = self.fingerprint(pending if exists_pending else target, ready)
            require(evidence == ready['file'], 'CONFLICT')
        except (OSError, Failure, ValueError):
            return uncertain
        return ready if exists_pending else ready | {'state': 'ORDINARY_SNAPSHOT_PUBLISHED_UNCONFIRMED'}

    def status(self, identity):
        with self.manager.lock(self.manager.state / 'admission.lock', False):
            intent, ready, receipt = self.records(identity)
            if receipt is not None:
                return receipt
            if intent is None:
                return self.controller.recovery.observation(identity, 'ORDINARY_SNAPSHOT_ABSENT')
            return self.observed(identity, intent, ready)

    def write_pending(self, directory_fd, name, source, payload=None):
        raw = launch.read(source, 0, self.core.pw_gid, 0o440, launch.MAX_SNAPSHOT) if payload is None else payload
        fd = os.open(name, os.O_WRONLY | os.O_NOFOLLOW | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600,
                     dir_fd=directory_fd)
        with os.fdopen(fd, 'wb') as output:
            os.fchown(output.fileno(), self.core.pw_uid, self.core.pw_gid)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(directory_fd)

    def publish_ready(self, identity, status, directory_fd):
        pending, target = self.paths(identity, status['snapshotId'])
        if status['state'] == 'ORDINARY_SNAPSHOT_READY':
            require(self.latest() < launch.snapshot_number(status['snapshotId']), 'CONFLICT')
            rename_no_replace(pending.name, target.name, directory_fd=directory_fd)
        else:
            require(status['state'] == 'ORDINARY_SNAPSHOT_PUBLISHED_UNCONFIRMED', 'UNKNOWN')
        os.fsync(directory_fd)
        require(self.directory_identity() == status['directory']
                and self.fingerprint(target, status) == status['file'], 'CONFLICT')
        receipt = status | {'state': 'ORDINARY_SNAPSHOT_PUBLISHED'}
        self.manager.atomic(self.journal(identity) / (self.RECEIPT + '.json'), encode(receipt), no_replace=True)
        return receipt

    def run(self, identity, source_receipt, *, continuing=False):
        digest(source_receipt)
        controller = self.controller
        stopped = controller.observation(identity)
        require(stopped['state'] == 'MAIN_STOPPED' and stopped['receiptSha256'] == source_receipt, 'CONFLICT')
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', True):
            manager.maintenance()
            manager.settled()
            require(controller.load(identity, 'stop-receipt') == stopped, 'CONFLICT')
            path, plan, _ = controller.guarded_source(identity, stopped)
            require(not any(os.path.lexists(path / name) for name in
                            (launch.GUARDED, launch.GUARDED_DRAFT, '.guarded-pending')), 'MAIN_COMMAND_EXISTS')
            intent, ready, receipt = self.records(identity)
            require(receipt is None and (intent is not None) == continuing, 'MAIN_COMMAND_EXISTS')
            component, cohort = manager.generation_component()
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                controller.verify_guarded_credential(plan, cohort)
                with manager.exclusive_writers():
                    controller.ensure_stopped(component, plan['ringSha256'] is not None)
                    policy_mode, policy = self.policy(plan)
                    directory = self.directory_identity()
                    fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                    try:
                        inode = os.fstat(fd)
                        require(directory == dict(device=str(inode.st_dev), inode=str(inode.st_ino)), 'CONFLICT')
                        if continuing:
                            require(intent['sourceReceiptSha256'] == source_receipt
                                    and intent['planSha256'] == stopped['planSha256']
                                    and intent['selectionSha256'] == stopped['selectionSha256']
                                    and intent['snapshotSha256'] == plan['snapshotSha256'] and intent['size'] == plan['size']
                                    and intent['policySha256'] == policy, 'CONFLICT')
                            durable = self.observed(identity, intent, ready)
                            require(durable['state'] != 'ORDINARY_SNAPSHOT_UNKNOWN', 'UNKNOWN')
                        else:
                            number = str(time.time_ns() // 1_000_000)
                            require(launch.snapshot_number(number) > self.latest(), 'SNAPSHOT_CLOCK_BEHIND')
                            pending, target = self.paths(identity, number)
                            require(not os.path.lexists(pending) and not os.path.lexists(target), 'MAIN_COMMAND_EXISTS')
                            payload = None
                            published_sha, published_size = plan['snapshotSha256'], plan['size']
                            if policy_mode != plan['mode']:
                                payload = self.convert(path / launch.SNAPSHOT, plan, policy_mode)
                                published_sha, published_size = launch.digest(payload), len(payload)
                            intent = controller.recovery.observation(identity, 'ORDINARY_SNAPSHOT_INTENT') | dict(
                                selectionSha256=stopped['selectionSha256'], planSha256=stopped['planSha256'],
                                sourceReceiptSha256=source_receipt, snapshotId=number, snapshotSha256=plan['snapshotSha256'],
                                size=plan['size'], publishedSha256=published_sha, publishedSize=published_size,
                                publishedMode=policy_mode, directory=directory, policySha256=policy)
                            try:
                                manager.atomic(self.journal(identity) / (self.INTENT + '.json'), encode(intent), no_replace=True)
                                self.write_pending(fd, pending.name, path / launch.SNAPSHOT, payload)
                                durable = intent | {'state': 'ORDINARY_SNAPSHOT_READY',
                                                    'file': self.fingerprint(pending, intent)}
                                manager.atomic(self.journal(identity) / (self.READY + '.json'), encode(durable), no_replace=True)
                            except (OSError, Failure, Refused, LifecycleRefused, ValueError) as error:
                                raise Failure('UNKNOWN') from error
                        try:
                            return self.publish_ready(identity, durable, fd)
                        except (OSError, Failure, Refused, LifecycleRefused, ValueError) as error:
                            raise Failure('UNKNOWN') from error
                    finally:
                        os.close(fd)

    def require_published(self, identity, number, source_receipt):
        intent, _, receipt = self.records(identity)
        if intent is not None:
            require(receipt is not None and receipt['snapshotId'] == number
                    and receipt['sourceReceiptSha256'] == source_receipt, 'CONFLICT')
        return receipt
