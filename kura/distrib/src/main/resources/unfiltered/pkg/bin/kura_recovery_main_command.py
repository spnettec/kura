#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""One-shot local authority for the existing, paired kura.service."""
import os
from pathlib import Path
import pwd
import re
import subprocess
import time

from kura_key_service import Failure, LifecycleRefused, Refused, decode, digest, encode, fields, rename_no_replace, require
from kura_key_generation import START, SYSTEMCTL
import kura_recovery_launch as launch
from kura_snapshot_publication import SnapshotPublication

STOP = (*SYSTEMCTL, 'stop', 'kura.service')
JOB = re.compile(r'o "(/org/freedesktop/systemd1/job/[0-9]+)"\n?')
CHECK_GROUPS = {'componentPids': 'components.sha256', 'checkIds': 'checks.sha256',
                'additionalSelfPids': 'additional.grant.sha256'}


def approved_checks(value):
    fields(value, CHECK_GROUPS)
    result = {}
    for key, name in CHECK_GROUPS.items():
        items = value[key]
        require(isinstance(items, list) and len(items) <= 32 and (items or key == 'additionalSelfPids'))
        for item in items:
            require(isinstance(item, str) and item.strip() and len(item.encode('utf-8')) <= 512
                    and not any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in item))
        require(len(items) == len(set(items)))
        result[name] = launch.digest('\0'.join(items).encode('utf-8'))
    return result


class Controller:
    def __init__(self, recovery, *, reader=None, authorize=None):
        self.recovery = recovery
        self.manager = recovery.manager
        self.lifecycle = recovery.lifecycle
        self.base = self.lifecycle.path(launch.ROOT)
        self.core = pwd.getpwnam('kurad')
        self.reader = reader
        self.authorize = authorize
        require(self.core.pw_uid > 0 and self.core.pw_gid > 0, 'UNMANAGED_CORE')

    def projection(self, identity):
        return launch.projection(self.base, identity, self.core.pw_uid, self.core.pw_gid, self.lifecycle.root)

    def inspect(self, path, plan, phase=None):
        if self.reader is None:
            return launch.inspect_projection(path, plan, self.core.pw_uid, self.core.pw_gid)
        result = self.reader(plan['restoreId'], phase) if phase else self.reader(plan['restoreId'])
        require(result.get('restoreId') == plan['restoreId'] and result.get('root') == plan['root']
                and result.get('planSha256') == launch.digest(launch.canonical(plan)), 'CONFLICT')
        return result

    def inspect_guarded(self, path, plan, fixed, *, draft=False, admit=False):
        validate = launch.guarded_projection if self.reader is None else launch.guarded_plan
        target, normal = validate(path, plan, fixed, self.core.pw_uid, self.core.pw_gid, draft=draft)
        phase = 'draft-admit' if admit else ('draft' if draft else 'guarded')
        result = self.inspect(target, normal, phase)
        return normal, result

    def authenticate(self):
        if self.authorize is not None:
            self.authorize()

    def journal(self, identity):
        return self.base / '.commands' / identity

    def load(self, identity, name):
        path = self.journal(identity) / (name + '.json')
        if not os.path.lexists(path):
            return None
        value = decode(self.manager.read(path, 8192))
        require(value.get('restoreId') == identity and value.get('root') == launch.root_identity(self.lifecycle.root)
                and type(value.get('schema')) is int and value['schema'] == 1, 'UNSAFE_FILESYSTEM')
        return value

    def observation(self, identity):
        value = self.recovery.observation(identity, 'MAIN_COMMAND_ABSENT')
        with self.manager.lock(self.manager.state / 'admission.lock', False):
            start, start_receipt, stop, stop_receipt = (
                self.load(identity, name) for name in ('start', 'start-receipt', 'stop', 'stop-receipt')
            )
            if start is None:
                require(start_receipt is stop is stop_receipt is None, 'UNSAFE_FILESYSTEM')
                return value
            fields(start, {'schema', 'restoreId', 'root', 'state', 'selectionSha256', 'planSha256', 'bootId'})
            require(start['state'] == 'MAIN_START_INTENT', 'UNSAFE_FILESYSTEM')
            digest(start['selectionSha256'])
            digest(start['planSha256'])
            if start_receipt is None:
                require(stop is stop_receipt is None, 'UNSAFE_FILESYSTEM')
                return start | {'state': 'MAIN_START_UNKNOWN'}
            fields(start_receipt, set(start) | {'jobPath'})
            require(start_receipt['state'] == 'MAIN_START_JOB_ACCEPTED'
                    and all(start_receipt[key] == start[key] for key in start if key != 'state')
                    and re.fullmatch('/org/freedesktop/systemd1/job/[0-9]+', start_receipt['jobPath']),
                    'UNSAFE_FILESYSTEM')
            if stop is None:
                require(stop_receipt is None, 'UNSAFE_FILESYSTEM')
                return start_receipt
            fields(stop, set(start_receipt) | {'pid', 'invocationId', 'startTicks', 'receiptSha256'})
            require(stop['state'] == 'MAIN_STOP_INTENT'
                    and all(stop[key] == start_receipt[key] for key in start_receipt if key != 'state'),
                    'UNSAFE_FILESYSTEM')
            if stop_receipt is None:
                return stop | {'state': 'MAIN_STOP_UNKNOWN'}
            require(stop_receipt == stop | {'state': 'MAIN_STOPPED'}, 'UNSAFE_FILESYSTEM')
            return stop_receipt

    def ensure_stopped(self, component, generation):
        component.dropin(generation_mode=generation)
        component.stopped(generation_mode=generation, uid=self.core.pw_uid)

    def start(self, identity, planned):
        digest(planned)
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', True):
            manager.maintenance()
            manager.settled()
            path, plan = self.projection(identity)
            require(launch.digest(launch.canonical(plan)) == planned, 'CONFLICT')
            require(self.inspect(path, plan)['state'] == 'MAIN_LAUNCH_PREPARED', 'MAIN_LAUNCH_USED')
            require(launch.selection(self.base, self.core.pw_gid, self.lifecycle.root) is None,
                    'MAIN_SELECTION_EXISTS')
            journal = self.journal(identity)
            require(not os.path.lexists(journal), 'MAIN_COMMAND_EXISTS')
            component, cohort = manager.generation_component()
            generation = plan['ringSha256'] is not None
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                _, _, _, _, _, source = manager.generation_source()
                require(source == dict(keySha256=plan['activeKeySha256'], ringSha256=plan['ringSha256'])
                        and cohort['cohortSha256'] == plan['cohortSha256'], 'COHORT_CHANGED')
                manager.generation_start_authorized(source, cohort)
                if self.reader is None:
                    os.close(manager.writer_lock(create=True))
                with manager.exclusive_writers():
                    self.ensure_stopped(component, generation)
                    self.authenticate()
                    selection = dict(schema=1, root=plan['root'], restoreId=identity,
                                     planSha256=planned, bootId=launch.boot_identity())
                    intent = selection | {'state': 'MAIN_START_INTENT',
                                          'selectionSha256': launch.digest(launch.canonical(selection))}
                    self.lifecycle.directory(journal, private=True, create=True)
                    self.lifecycle.sync(journal.parent)
                    self.lifecycle.sync(self.base)
                    try:
                        manager.atomic(journal / 'start.json', encode(intent), no_replace=True)
                        pending = self.base / ('.selection-' + identity)
                        launch.write(pending, launch.canonical(selection), 0o440, self.core.pw_gid)
                        rename_no_replace(pending, self.base / launch.SELECTION)
                        self.lifecycle.sync(self.base)
                    except (OSError, Failure) as error:
                        raise Failure('UNKNOWN') from error
        # Publish admission before asking PID 1 so its pre-start readers can
        # acquire the existing read/lease locks. The durable selection fences
        # maintenance and prohibits a fallback to an ordinary Main.
        try:
            self.ensure_stopped(component, generation)
            self.authenticate()
            raw = component.command(START, timeout=18)
            job = JOB.fullmatch(raw)
            require(job is not None, 'UNKNOWN')
            receipt = intent | {'state': 'MAIN_START_JOB_ACCEPTED', 'jobPath': job.group(1)}
            manager.atomic(journal / 'start-receipt.json', encode(receipt), no_replace=True)
            return receipt
        except (OSError, Failure, Refused, LifecycleRefused, subprocess.SubprocessError, ValueError, KeyError) as error:
            raise Failure('UNKNOWN') from error

    def active_projection(self, identity, prior):
        path, plan = self.projection(identity)
        selected = launch.selection(self.base, self.core.pw_gid, self.lifecycle.root)
        require(selected is not None and selected['restoreId'] == identity
                and launch.digest(launch.canonical(selected)) == prior['selectionSha256']
                and selected['bootId'] == launch.boot_identity(), 'CONFLICT')
        observed = self.inspect(path, plan)
        require(observed['state'] == 'CM_APPLIED', 'CONFLICT')
        component, generation = self.active_invocation(plan, selected, observed)
        return component, generation, path, plan, observed

    def active_invocation(self, plan, selected, observed):
        manager = self.manager
        component, cohort = manager.generation_component()
        generation = plan['ringSha256'] is not None
        unit = component.unit(generation_mode=generation)
        invocation = observed['invocation']
        require(unit['ActiveState'] == 'active' and unit['SubState'] == 'running'
                and unit['ControlGroup'] == '/system.slice/kura.service'
                and unit['ControlPID'] == '0' and unit['MainPID'] == str(invocation['pid'])
                and unit['InvocationID'] == invocation['invocationId']
                and selected['bootId'] == invocation['bootId'], 'CONFLICT')
        writer = manager.writer_registration(invocation['pid'])
        require(writer['startTicks'] == invocation['startTicks'] and writer['bootId'] == invocation['bootId']
                and writer['uid'] == self.core.pw_uid and writer['keySha256'] == plan['activeKeySha256']
                and writer['ringSha256'] == plan['ringSha256']
                and writer['cohortSha256'] == plan['cohortSha256'] == cohort['cohortSha256'], 'CONFLICT')
        return component, generation

    def application(self, identity):
        prior = self.observation(identity)
        require(prior['state'] == 'MAIN_START_JOB_ACCEPTED', 'CONFLICT')
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', False):
            manager.maintenance()
            require(not os.path.lexists(self.journal(identity) / 'stop.json'), 'CONFLICT')
            _, _, _, plan, observed = self.active_projection(identity, prior)
            return observed | {'snapshotSha256': plan['snapshotSha256']}

    def stop(self, identity, receipt_sha):
        digest(receipt_sha)
        prior = self.observation(identity)
        require(prior['state'] == 'MAIN_START_JOB_ACCEPTED', 'MAIN_COMMAND_EXISTS')
        manager = self.manager
        journal = self.journal(identity)
        with manager.lock(manager.state / 'admission.lock', True):
            manager.maintenance()
            manager.settled()
            require(not os.path.lexists(journal / 'stop.json'), 'MAIN_COMMAND_EXISTS')
            component, generation, path, plan, observed = self.active_projection(identity, prior)
            require(observed['receiptSha256'] == receipt_sha, 'CONFLICT')
            invocation = observed['invocation']
            intent = prior | {'state': 'MAIN_STOP_INTENT', 'pid': invocation['pid'],
                              'invocationId': invocation['invocationId'], 'startTicks': invocation['startTicks'],
                              'receiptSha256': receipt_sha}
            self.authenticate()
            try:
                manager.atomic(journal / 'stop.json', encode(intent), no_replace=True)
                component.command(STOP, timeout=55)
                self.ensure_stopped(component, generation)
                with manager.exclusive_writers():
                    self.ensure_stopped(component, generation)
                    require(self.inspect(path, plan) == observed, 'CONFLICT')
                    receipt = intent | {'state': 'MAIN_STOPPED'}
                    manager.atomic(journal / 'stop-receipt.json', encode(receipt), no_replace=True)
                    return receipt
            except (OSError, Failure, Refused, LifecycleRefused, subprocess.SubprocessError, ValueError, KeyError) as error:
                raise Failure('UNKNOWN') from error

    def guarded_source(self, identity, stopped):
        path, plan = self.projection(identity)
        fixed = launch.selection(self.base, self.core.pw_gid, self.lifecycle.root)
        require(stopped['state'] == 'MAIN_STOPPED' and fixed is not None
                and fixed['restoreId'] == identity and fixed['bootId'] == launch.boot_identity()
                and stopped['bootId'] == fixed['bootId']
                and launch.digest(launch.canonical(fixed)) == stopped['selectionSha256']
                and launch.digest(launch.canonical(plan)) == stopped['planSha256'], 'CONFLICT')
        applied = self.inspect(path, plan)
        require(applied['state'] == 'CM_APPLIED' and applied['receiptSha256'] == stopped['receiptSha256']
                and all(applied['invocation'][key] == stopped[key]
                        for key in ('pid', 'invocationId', 'startTicks', 'bootId')), 'CONFLICT')
        return path, plan, fixed

    def verify_guarded_credential(self, plan, cohort):
        manager = self.manager
        _, _, _, _, _, source = manager.generation_source()
        require(source == dict(keySha256=plan['activeKeySha256'], ringSha256=plan['ringSha256'])
                and cohort['cohortSha256'] == plan['cohortSha256'], 'COHORT_CHANGED')
        manager.generation_start_authorized(source, cohort)

    def prepare_guarded(self, path, plan, stopped, snapshot_id, *, draft=False):
        raw, applied = launch.decision(path / launch.OUT / launch.RECEIPT, plan['restoreId'],
                                       self.core.pw_uid, self.core.pw_gid)
        require(launch.digest(raw) == stopped['receiptSha256'], 'CONFLICT')
        guard = dict(snapshotId=snapshot_id, selectionSha256=stopped['selectionSha256'],
                     sourceReceiptSha256=stopped['receiptSha256'], sourceAppliedSha256=applied['applied.sha256'])
        published = SnapshotPublication(self).require_published(plan['restoreId'], snapshot_id, stopped['receiptSha256'])
        if published is not None:
            guard.update(snapshotFile=published['file'], snapshotDirectory=published['directory'],
                         publishedSha256=published['publishedSha256'], publishedSize=published['publishedSize'],
                         publishedMode=published['publishedMode'])
        normal = plan | {'guarded': guard}
        launch.normal_snapshot(self.lifecycle.root, normal, self.core.pw_uid, self.core.pw_gid)
        self.authenticate()
        try:
            pending = path / '.guarded-pending'
            pending.mkdir(mode=0o700)
            self.lifecycle.sync(path)
            target = path / (launch.GUARDED_DRAFT if draft else launch.GUARDED)
            self.recovery.prepare_guarded_projection(pending, target, normal, self.core)
        except (OSError, Failure, Refused, LifecycleRefused) as error:
            raise Failure('UNKNOWN') from error
        return normal

    def prepare_guarded_grant(self, identity, stopped, receipt_sha, snapshot_id):
        require(stopped['state'] == 'MAIN_STOPPED' and stopped['receiptSha256'] == receipt_sha
                and self.load(identity, 'stop-receipt') == stopped, 'CONFLICT')
        path, plan, _ = self.guarded_source(identity, stopped)
        require(not any(os.path.lexists(path / name) for name in
                        (launch.GUARDED, launch.GUARDED_DRAFT, '.guarded-pending')), 'MAIN_COMMAND_EXISTS')
        manager = self.manager
        component, cohort = manager.generation_component()
        with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
            self.verify_guarded_credential(plan, cohort)
            with manager.exclusive_writers():
                self.ensure_stopped(component, plan['ringSha256'] is not None)
                normal = self.prepare_guarded(path, plan, stopped, snapshot_id, draft=True)
        return launch.digest(launch.canonical(normal))

    def start_guarded(self, identity, receipt_sha, snapshot_id, *, prepared=None):
        digest(receipt_sha)
        launch.snapshot_number(snapshot_id)
        stopped = self.observation(identity)
        require(stopped['state'] == 'MAIN_STOPPED' and stopped['receiptSha256'] == receipt_sha, 'CONFLICT')
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', True):
            manager.maintenance()
            manager.settled()
            require(self.load(identity, 'stop-receipt') == stopped, 'CONFLICT')
            path, plan, fixed = self.guarded_source(identity, stopped)
            target, pending = path / launch.GUARDED, path / '.guarded-pending'
            require(not os.path.lexists(target) and not os.path.lexists(pending)
                    and self.load(identity, 'guarded-start-receipt') is None, 'MAIN_COMMAND_EXISTS')
            component, cohort = manager.generation_component()
            generation = plan['ringSha256'] is not None
            draft = path / launch.GUARDED_DRAFT
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                self.verify_guarded_credential(plan, cohort)
                with manager.exclusive_writers():
                    self.ensure_stopped(component, generation)
                    if prepared is None:
                        require(not os.path.lexists(draft), 'MAIN_COMMAND_EXISTS')
                        normal = self.prepare_guarded(path, plan, stopped, snapshot_id)
                    else:
                        SnapshotPublication(self).require_published(identity, snapshot_id, receipt_sha)
                        normal, result = self.inspect_guarded(path, plan, fixed, draft=True, admit=True)
                        require(result['state'] == 'MAIN_LAUNCH_PREPARED' and result['planSha256'] == prepared
                                and normal['guarded']['snapshotId'] == snapshot_id
                                and normal['guarded']['sourceReceiptSha256'] == receipt_sha, 'CONFLICT')
                        self.ensure_stopped(component, generation)
                        self.authenticate()
                        try:
                            rename_no_replace(draft, target)
                            self.lifecycle.sync(path)
                        except OSError as error:
                            raise Failure('UNKNOWN') from error
        try:
            self.ensure_stopped(component, generation)
            self.authenticate()
            job = JOB.fullmatch(component.command(START, timeout=18))
            require(job is not None, 'UNKNOWN')
            receipt = dict(schema=1, root=plan['root'], restoreId=identity, state='GUARDED_MAIN_START_JOB_ACCEPTED',
                           guardedSha256=launch.digest(launch.canonical(normal)), jobPath=job.group(1))
            manager.atomic(self.journal(identity) / 'guarded-start-receipt.json', encode(receipt), no_replace=True)
            return receipt
        except (OSError, Failure, Refused, LifecycleRefused, subprocess.SubprocessError, ValueError, KeyError) as error:
            raise Failure('UNKNOWN') from error

    def guarded_status(self, identity):
        stopped = self.observation(identity)
        result = self.recovery.observation(identity, 'GUARDED_MAIN_ABSENT')
        if stopped['state'] != 'MAIN_STOPPED':
            return result
        with self.manager.lock(self.manager.state / 'admission.lock', False):
            path, plan = self.projection(identity)
            pending = path / '.guarded-pending'
            admitted = os.path.lexists(path / launch.GUARDED)
            draft = os.path.lexists(path / launch.GUARDED_DRAFT)
            require(not (admitted and draft), 'UNSAFE_FILESYSTEM')
            if not admitted and not draft:
                require(self.load(identity, 'guarded-start-receipt') is None, 'UNSAFE_FILESYSTEM')
                if os.path.lexists(pending):
                    result['state'] = 'GUARDED_MAIN_START_UNKNOWN'
                return result
            fixed = launch.selection(self.base, self.core.pw_gid, self.lifecycle.root, archived=identity)
            require(not os.path.lexists(pending) and fixed is not None
                    and fixed['restoreId'] == identity
                    and launch.digest(launch.canonical(fixed)) == stopped['selectionSha256'], 'CONFLICT')
            normal, outcome = self.inspect_guarded(path, plan, fixed, draft=draft)
            fingerprint = launch.digest(launch.canonical(normal))
            receipt = self.load(identity, 'guarded-start-receipt')
            if draft:
                require(receipt is None and outcome['state'] == 'MAIN_LAUNCH_PREPARED', 'UNSAFE_FILESYSTEM')
                result.update(state='GUARDED_MAIN_PREPARED', guardedSha256=fingerprint)
            elif receipt is not None:
                fields(receipt, set(result) | {'guardedSha256', 'jobPath'})
                require(receipt['state'] == 'GUARDED_MAIN_START_JOB_ACCEPTED'
                        and receipt['guardedSha256'] == fingerprint
                        and re.fullmatch('/org/freedesktop/systemd1/job/[0-9]+', receipt['jobPath']), 'UNSAFE_FILESYSTEM')
                result = receipt
            else:
                result.update(state='GUARDED_MAIN_START_UNKNOWN', guardedSha256=fingerprint)
            result['originalStop'] = stopped
            result['outcome'] = outcome
            return result

    def guarded_application(self, identity):
        status = self.guarded_status(identity)
        require(status['state'] == 'GUARDED_MAIN_START_JOB_ACCEPTED'
                and status['outcome']['state'] == 'NORMAL_BOOT_ADMITTED', 'CONFLICT')
        with self.manager.lock(self.manager.state / 'admission.lock', False):
            self.manager.maintenance()
            path, plan = self.projection(identity)
            fixed = launch.selection(self.base, self.core.pw_gid, self.lifecycle.root)
            require(fixed is not None and fixed['restoreId'] == identity
                    and fixed['bootId'] == launch.boot_identity(), 'CONFLICT')
            _, normal = launch.guarded_plan(path, plan, fixed, self.core.pw_uid, self.core.pw_gid)
            require(launch.digest(launch.canonical(normal)) == status['guardedSha256'], 'CONFLICT')
            self.active_invocation(plan, fixed, status['outcome'])
            return status['outcome'] | {'snapshotSha256': plan['snapshotSha256'],
                                        'sourceReceiptSha256': status['originalStop']['receiptSha256']}

    def authorize_release(self, identity, receipt_sha, policy_path, authenticate):
        digest(receipt_sha)
        require(policy_path.is_absolute())
        policy = decode(self.manager.read(policy_path, 32768))
        valid = policy.pop('validForSeconds', None)
        require(type(valid) is int and 60 <= valid <= 600)
        checks = approved_checks(policy)
        proof = self.guarded_application(identity)
        require(proof['receiptSha256'] == receipt_sha, 'CONFLICT')
        peer = authenticate()
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', True):
            manager.maintenance()
            self.check_live_release(identity, proof)
            require(self.load(identity, 'release-approved') is None, 'MAIN_COMMAND_EXISTS')
            require(authenticate() == peer, 'FORBIDDEN')
            approved = self.recovery.observation(identity, 'GUARDED_RELEASE_APPROVED')
            approved.update(proof=proof, peer=peer, checks=checks,
                            notAfterUnixMillis=time.time_ns() // 1_000_000 + valid * 1000)
            try:
                manager.atomic(self.journal(identity) / 'release-approved.json', encode(approved), no_replace=True)
            except (OSError, Refused, LifecycleRefused) as error:
                raise Failure('UNKNOWN') from error
            return {key: value for key, value in approved.items() if key != 'peer'}

    def check_live_release(self, identity, proof):
        path, plan = self.projection(identity)
        fixed = launch.selection(self.base, self.core.pw_gid, self.lifecycle.root)
        require(fixed is not None and fixed['restoreId'] == identity
                and fixed['bootId'] == launch.boot_identity(), 'CONFLICT')
        target, normal = launch.guarded_plan(path, plan, fixed, self.core.pw_uid, self.core.pw_gid)
        require(launch.digest(launch.canonical(normal)) == proof['planSha256'], 'CONFLICT')
        self.active_invocation(plan, fixed, proof)
        return target

    def issue_release(self, identity, receipt_sha, checks, health_sha, nonce, authenticate):
        digest(receipt_sha)
        digest(health_sha)
        digest(nonce)
        approved_checks_value = approved_checks(checks)
        approved = self.load(identity, 'release-approved')
        require(approved is not None and approved['state'] == 'GUARDED_RELEASE_APPROVED'
                and approved['checks'] == approved_checks_value and approved['peer'] == authenticate()
                and approved['proof']['receiptSha256'] == receipt_sha, 'FORBIDDEN')
        proof = self.guarded_application(identity)
        require(approved['proof'] == proof, 'CONFLICT')
        manager = self.manager
        expires = approved['notAfterUnixMillis']
        with manager.lock(manager.state / 'admission.lock', True):
            manager.maintenance()
            target = self.check_live_release(identity, proof)
            pending = target / '.release-issued.pending'
            require(self.load(identity, 'release-intent') is None and not os.path.lexists(pending)
                    and not os.path.lexists(target / launch.RELEASE_DECISION), 'MAIN_COMMAND_EXISTS')
            require(expires > time.time_ns() // 1_000_000 and approved['peer'] == authenticate(), 'FORBIDDEN')
            completion = 'complete-' + identity[4:]
            issued = {'schema': 'yofc.kura.fixed-write-approval.v1', 'completion.id': completion, 'restore.id': identity,
                      'normal.receipt.sha256': receipt_sha, 'source.receipt.sha256': proof['sourceReceiptSha256'],
                      'snapshot.sha256': proof['snapshotSha256'], 'health.receipt.sha256': health_sha,
                      'nonce': nonce, 'process.id': str(proof['invocation']['pid']),
                      'invocation.id': proof['invocation']['invocationId'], 'not.after': str(expires)}
            raw = launch.property_bytes(issued | approved_checks_value)
            intent = self.recovery.observation(identity, 'GUARDED_RELEASE_ISSUED')
            intent.update(decisionSha256=launch.digest(raw), completionId=completion, notAfterUnixMillis=expires,
                          normalReceiptSha256=receipt_sha, healthReceiptSha256=health_sha, nonce=nonce)
            try:
                manager.atomic(self.journal(identity) / 'release-intent.json', encode(intent), no_replace=True)
                launch.write(pending, raw, 0o440, self.core.pw_gid)
                rename_no_replace(pending, target / launch.RELEASE_DECISION)
                self.lifecycle.sync(target)
            except (OSError, Failure, Refused, LifecycleRefused) as error:
                raise Failure('UNKNOWN') from error
            return intent

    def release_status(self, identity):
        with self.manager.lock(self.manager.state / 'admission.lock', False):
            approved = self.load(identity, 'release-approved')
            intent = self.load(identity, 'release-intent')
            if approved is None:
                require(intent is None, 'UNSAFE_FILESYSTEM')
                return self.recovery.observation(identity, 'GUARDED_RELEASE_ABSENT')
            require(approved['state'] == 'GUARDED_RELEASE_APPROVED', 'UNSAFE_FILESYSTEM')
            if intent is None:
                return self.recovery.observation(identity, 'GUARDED_RELEASE_APPROVED')
            path, plan = self.projection(identity)
            fixed = launch.selection(self.base, self.core.pw_gid, self.lifecycle.root, archived=identity)
            require(fixed is not None and fixed['restoreId'] == identity, 'CONFLICT')
            validate = launch.guarded_projection if self.reader is None else launch.guarded_plan
            target, normal = validate(path, plan, fixed, self.core.pw_uid, self.core.pw_gid)
            if self.reader is None:
                release = launch.release_observation(target, normal, self.core.pw_uid, self.core.pw_gid)
            else:
                release = self.inspect(target, normal, 'release')['release']
            require(intent['state'] == 'GUARDED_RELEASE_ISSUED'
                    and (not release or all(release.get(key) == intent[key]
                                            for key in ('completionId', 'decisionSha256'))), 'CONFLICT')
            if 'releaseReceiptSha256' not in release:
                return intent | {'state': 'GUARDED_RELEASE_UNKNOWN'}
            return intent | {'state': 'GUARDED_RELEASE_COMMITTED',
                             'releaseReceiptSha256': release['releaseReceiptSha256'],
                             'selectionRetired': os.path.lexists(path / launch.RETIRED_SELECTION)}

    def retire_guarded(self, identity, release_sha):
        digest(release_sha)
        status = self.release_status(identity)
        require(status['state'] == 'GUARDED_RELEASE_COMMITTED' and not status['selectionRetired']
                and status['releaseReceiptSha256'] == release_sha, 'CONFLICT')
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', True):
            manager.maintenance()
            manager.settled()
            path, plan = self.projection(identity)
            fixed = launch.selection(self.base, self.core.pw_gid, self.lifecycle.root)
            require(fixed is not None and fixed['restoreId'] == identity, 'CONFLICT')
            target, normal = launch.guarded_projection(path, plan, fixed, self.core.pw_uid, self.core.pw_gid)
            component, cohort = manager.generation_component()
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                self.verify_guarded_credential(plan, cohort)
                with manager.exclusive_writers():
                    self.ensure_stopped(component, plan['ringSha256'] is not None)
                    release = launch.release_observation(target, normal, self.core.pw_uid, self.core.pw_gid)
                    require(release.get('releaseReceiptSha256') == release_sha, 'CONFLICT')
                    try:
                        rename_no_replace(self.base / launch.SELECTION, path / launch.RETIRED_SELECTION)
                        self.lifecycle.sync(path)
                        self.lifecycle.sync(self.base)
                    except (OSError, Failure, Refused, LifecycleRefused) as error:
                        raise Failure('UNKNOWN') from error
        return status | {'selectionRetired': True}


def command(recovery, action, arguments):
    parameter_count = {'start-main': 2, 'stop-main': 2, 'main-command-status': 1,
                       'start-guarded-main': 3, 'guarded-main-status': 1,
                       'approve-guarded-release': 3, 'guarded-release-status': 1, 'retire-guarded-main': 2,
                       'publish-ordinary-snapshot': 2, 'continue-ordinary-snapshot': 2, 'ordinary-snapshot-status': 1}
    require(len(arguments) == parameter_count[action])
    identity, *expected = arguments
    require(launch.IDENTITY.fullmatch(identity) is not None)
    fixed = Controller(recovery)
    if action == 'ordinary-snapshot-status':
        return SnapshotPublication(fixed).status(identity)
    if action in ('publish-ordinary-snapshot', 'continue-ordinary-snapshot'):
        return SnapshotPublication(fixed).run(identity, expected[0], continuing=action == 'continue-ordinary-snapshot')
    if action == 'approve-guarded-release':
        from kura_native_snapshot_validation import administrator_peer

        receipt, policy = expected
        with administrator_peer(recovery.lifecycle) as authenticate:
            return fixed.authorize_release(identity, receipt, Path(policy), authenticate)
    route = {'start-main': fixed.start, 'stop-main': fixed.stop, 'main-command-status': fixed.observation,
             'start-guarded-main': fixed.start_guarded, 'guarded-main-status': fixed.guarded_status,
             'guarded-release-status': fixed.release_status, 'retire-guarded-main': fixed.retire_guarded}
    return route[action](identity, *expected)
