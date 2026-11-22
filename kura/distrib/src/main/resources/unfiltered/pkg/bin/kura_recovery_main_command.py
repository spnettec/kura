#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""One-shot local authority for the existing, paired kura.service."""
import os
import pwd
import re
import subprocess

from kura_key_service import Failure, LifecycleRefused, Refused, decode, digest, encode, fields, rename_no_replace, require
from kura_key_generation import START, SYSTEMCTL
import kura_recovery_launch as launch

STOP = (*SYSTEMCTL, 'stop', 'kura.service')
JOB = re.compile(r'o "(/org/freedesktop/systemd1/job/[0-9]+)"\n?')


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

    def inspect(self, path, plan):
        if self.reader is None:
            return launch.inspect_projection(path, plan, self.core.pw_uid, self.core.pw_gid)
        result = self.reader(plan['restoreId'])
        require(result.get('restoreId') == plan['restoreId'] and result.get('root') == plan['root']
                and result.get('planSha256') == launch.digest(launch.canonical(plan)), 'CONFLICT')
        return result

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
            path, plan = self.projection(identity)
            selected = launch.selection(self.base, self.core.pw_gid, self.lifecycle.root)
            require(selected is not None and selected['restoreId'] == identity
                    and launch.digest(launch.canonical(selected)) == prior['selectionSha256']
                    and selected['bootId'] == launch.boot_identity(), 'CONFLICT')
            observed = self.inspect(path, plan)
            require(observed['state'] == 'CM_APPLIED' and observed['receiptSha256'] == receipt_sha, 'CONFLICT')
            component, cohort = manager.generation_component()
            generation = plan['ringSha256'] is not None
            unit = component.unit(generation_mode=generation)
            invocation = observed['invocation']
            require(unit['ActiveState'] == 'active' and unit['SubState'] == 'running'
                    and unit['ControlPID'] == '0' and unit['MainPID'] == str(invocation['pid'])
                    and unit['InvocationID'] == invocation['invocationId']
                    and selected['bootId'] == invocation['bootId'], 'CONFLICT')
            writer = manager.writer_registration(invocation['pid'])
            require(writer['startTicks'] == invocation['startTicks'] and writer['bootId'] == invocation['bootId']
                    and writer['uid'] == self.core.pw_uid and writer['keySha256'] == plan['activeKeySha256']
                    and writer['ringSha256'] == plan['ringSha256']
                    and writer['cohortSha256'] == plan['cohortSha256'] == cohort['cohortSha256'], 'CONFLICT')
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


def command(recovery, action, arguments):
    require(len(arguments) == (1 if action == 'main-command-status' else 2))
    identity, *expected = arguments
    require(launch.IDENTITY.fullmatch(identity) is not None)
    fixed = Controller(recovery)
    route = {'start-main': fixed.start, 'stop-main': fixed.stop, 'main-command-status': fixed.observation}
    return route[action](identity, *expected)
