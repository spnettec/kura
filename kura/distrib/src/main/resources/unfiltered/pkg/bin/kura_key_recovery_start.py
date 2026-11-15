#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fixed Core start handoff. A systemd job receipt never proves Core health."""
import hashlib
import hmac
import re
import subprocess

from kura_key_service import Failure, digest, encode, operation_id, fields, require, decode
from kura_key_service_lifecycle import Refused, validate_start, validate_maintenance, Lifecycle

COMMAND = ('/usr/bin/busctl', '--system', '--timeout=15s', 'call',
           'org.freedesktop.systemd1', '/org/freedesktop/systemd1',
           'org.freedesktop.systemd1.Manager', 'StartUnit', 'ss', 'kura.service', 'fail')


class Starter:
    def __init__(self, manager, runner=None):
        self.manager = manager
        self.directory = manager.state / 'startups'
        self.runner = subprocess.run if runner is None else runner

    def records(self):
        self.manager.directory(self.directory, private=True)
        paths = list(self.directory.iterdir())
        require(len(paths) <= 32, 'UNSAFE_JOURNAL')
        return [self.record(operation_id(p.name[:-5])) if p.name.endswith('.json')
                else self.invalid() for p in paths]

    @staticmethod
    def invalid():
        raise Failure('UNSAFE_JOURNAL')

    def record(self, identity):
        try:
            return validate_start(decode(self.manager.read(self.directory / (identity + '.json'))), identity)
        except FileNotFoundError:
            return None
        except Refused:
            return self.invalid()

    @staticmethod
    def public(record):
        if record is None:
            return dict(schema=1, state='NOT_FOUND')
        if record['state'] == 'INTENT':
            return dict(schema=1, operationId=record['operationId'], state='UNKNOWN')
        return record['response']

    def manifest_digest(self):
        policy = Lifecycle(self.manager.root, self.manager.owner)
        policy.assets()
        home = policy.path('/opt/eclipse/kura').resolve(strict=True)
        return hashlib.sha256(policy.read(home / 'libexec/key-backup/manifest.json', private=False)).hexdigest()

    def package_head(self):
        directory = self.manager.state / 'package-history'
        self.manager.directory(directory, private=True)
        paths = list(directory.iterdir())
        require(len(paths) <= 128, 'UNSAFE_JOURNAL')
        records = {}
        try:
            for path in paths:
                require(path.name.endswith('.json'), 'UNSAFE_JOURNAL')
                identity = operation_id(path.name[:-5])
                records[identity] = validate_maintenance(decode(self.manager.read(path)), identity)
        except Refused:
            return self.invalid()
        parents = {r['previousMaintenanceId'] for r in records.values()}
        heads = [r for r in records.values() if r['maintenanceId'] not in parents]
        require(len(heads) == (1 if records else 0), 'UNSAFE_JOURNAL')
        if not heads:
            return None
        visited = set()
        current = heads[0]
        while current is not None:
            require(current['maintenanceId'] not in visited, 'UNSAFE_JOURNAL')
            visited.add(current['maintenanceId'])
            parent = current['previousMaintenanceId']
            require(parent is None or parent in records, 'UNSAFE_JOURNAL')
            current = records.get(parent)
        require(len(visited) == len(records), 'UNSAFE_JOURNAL')
        return heads[0]

    def original_restore(self, restore_id, expected):
        record = self.manager.record(restore_id)
        require(record is not None and record['state'] == 'SUCCEEDED'
                and record['action'] == 'restore', 'UNRESOLVED_OPERATION')
        response = record['response']
        require(response['keyChanged'] is True and response['existingReceiptPreserved'] is True
                and response['keySha256'] == expected, 'CONFLICT')

    def plan(self, restore_id, expected):
        # Caller holds admission.lock. Every decision is from protected receipts.
        self.original_restore(restore_id, expected)
        records = self.records()
        unknown = [r for r in records if r['state'] == 'INTENT']
        result = dict(schema=1, state='START_PLAN', startAllowed=False, maintenanceId=None,
                      predecessorStartOperationId=None, manifestSha256=None,
                      blockingOperationId=unknown[0]['operationId'] if len(unknown) == 1 else None)
        require(len(unknown) <= 1, 'UNSAFE_JOURNAL')
        if unknown:
            return result
        group = {r['operationId']: r for r in records if r['restoreOperationId'] == restore_id}
        if not group:
            return result
        parents = {r['predecessorStartOperationId'] for r in group.values() if r['schema'] == 2}
        leaves = [r for r in group.values() if r['operationId'] not in parents]
        require(len(leaves) == 1, 'UNSAFE_JOURNAL')
        visited = set()
        current = leaves[0]
        while True:
            require(current['operationId'] not in visited and current['keySha256'] == expected, 'UNSAFE_JOURNAL')
            visited.add(current['operationId'])
            if current['schema'] == 1:
                break
            parent = current['predecessorStartOperationId']
            require(parent in group, 'UNSAFE_JOURNAL')
            current = group[parent]
        require(len(visited) == len(group), 'UNSAFE_JOURNAL')
        head = self.package_head()
        if head is None or head['firstAction'] != 'upgrade':
            return result
        if head['keySha256'] != expected or head['manifestSha256'] != self.manifest_digest():
            return result
        if leaves[0]['operationId'] not in head['precedingStartupIds']:
            return result
        if any(r.get('maintenanceId') == head['maintenanceId'] for r in records):
            return result
        return dict(result, startAllowed=True, maintenanceId=head['maintenanceId'],
                    predecessorStartOperationId=leaves[0]['operationId'], manifestSha256=head['manifestSha256'])

    def handle(self, request):
        manager = self.manager
        if request['action'] == 'core-start-plan':
            fields(request, {'schema', 'action', 'restoreOperationId', 'expectedKeySha256'})
            restore_id = operation_id(request['restoreOperationId'])
            expected = digest(request['expectedKeySha256'])
            with manager.lock(manager.state / 'admission.lock', False):
                manager.maintenance()
                return self.plan(restore_id, expected)
        identity = operation_id(request['operationId'])
        if request['action'] == 'core-start-read':
            fields(request, {'schema', 'action', 'operationId'})
            with manager.lock(manager.state / 'admission.lock', False):
                manager.maintenance()
                return self.public(self.record(identity))
        modern = request['action'] == 'core-start-after-maintenance'
        extra = {'predecessorStartOperationId', 'maintenanceId', 'manifestSha256'} if modern else set()
        fields(request, {'schema', 'action', 'operationId', 'restoreOperationId', 'expectedKeySha256'} | extra)
        if modern:
            operation_id(request['predecessorStartOperationId']); operation_id(request['maintenanceId'])
            digest(request['manifestSha256'])
        restore_id = operation_id(request['restoreOperationId'])
        expected = digest(request['expectedKeySha256'])
        with manager.lock(manager.state / 'admission.lock', True):
            manager.maintenance()
            secret = manager.read(manager.state / 'journal.key', 32)
            require(len(secret) == 32, 'UNSAFE_JOURNAL')
            tag = hmac.new(secret, encode(request), hashlib.sha256).hexdigest()
            prior = self.record(identity)
            if prior is not None:
                require(hmac.compare_digest(prior['requestTag'], tag), 'CONFLICT')
                return self.public(prior)  # Never repeat StartUnit, including INTENT.
            records = self.records()
            require(len(records) < 32, 'CAPACITY')
            require(all(r['state'] == 'SUCCEEDED' for r in records), 'UNRESOLVED_OPERATION')
            if modern:
                plan = self.plan(restore_id, expected)
                require(plan['startAllowed'] and all(plan[k] == request[k] for k in extra), 'CONFLICT')
            else:
                require(all(r['restoreOperationId'] != restore_id for r in records), 'CONFLICT')
            manager.journal_admission()
            self.original_restore(restore_id, expected)
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                _, proof = manager.canonical()
                require(proof['keySha256'] == expected, 'CONFLICT')
                record = dict(schema=2 if modern else 1, operationId=identity, restoreOperationId=restore_id,
                              keySha256=expected, requestTag=tag, state='INTENT', response=None)
                record.update({k: request[k] for k in extra})
                try:
                    manager.atomic(self.directory / (identity + '.json'), encode(record))
                    # Only this fixed unit/verb is reachable. No operator-supplied argv.
                    result = self.runner(list(COMMAND), capture_output=True, text=True, timeout=18,
                                         check=False, close_fds=True, cwd='/',
                                         env={'PATH': '/usr/bin:/bin', 'LANG': 'C'})
                    require(result.returncode == 0 and len(result.stdout) <= 256, 'UNKNOWN')
                    match = re.fullmatch(r'o "(/org/freedesktop/systemd1/job/[0-9]+)"\n?', result.stdout)
                    require(match is not None, 'UNKNOWN')
                    response = dict(schema=1, operationId=identity, restoreOperationId=restore_id,
                                    keySha256=expected, action=request['action'], state='SUCCEEDED',
                                    scope='SYSTEMD_JOB_ACCEPTED', jobPath=match[1])
                    response.update({k: request[k] for k in extra})
                    record.update(state='SUCCEEDED', response=response)
                    manager.atomic(self.directory / (identity + '.json'), encode(record))
                    return response
                except (Failure, OSError, Refused, subprocess.TimeoutExpired):
                    raise Failure('UNKNOWN') from None
