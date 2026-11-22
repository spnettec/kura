#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fixed Core reboot requests and the standalone Core sender's one-shot state."""
import os
from pathlib import Path
import uuid

from kura_clock_journal import create, decode, directory, encode, identifier, read, require, sync
from kura_reboot_journal import DECISIONS, admission_lock, linux_boot_id, reference, request, sha256

BASE_FIELDS = {'schema', 'action'}
STATUS_FIELDS = {'namespace', 'requestId', 'requestSha256'}


class RebootProtocol:
    """Request handling shared by the authenticated transport and its contract tests."""

    def __init__(self, journal, authorize, dispatch):
        self.journal = journal
        self.authorize = authorize
        self.dispatch = dispatch

    def handle(self, value, peer):
        require(self.authorize(peer), 'UNAUTHORIZED')
        require(type(value) is dict and type(value.get('schema')) is int and value['schema'] == 1)
        action = value.get('action')
        if action == 'context':
            require(set(value) == BASE_FIELDS)
            return self.journal.context()
        if action == 'status':
            require(set(value) == BASE_FIELDS | STATUS_FIELDS)
            return self.journal.status(value['namespace'], value['requestId'], value['requestSha256'])
        return self.journal.submit(value, self.dispatch)


def verify_result(result, pending, observed_boot):
    anchor = reference(pending)
    fields = set(anchor) | {'state', 'reason'}
    require(type(result) is dict and fields <= set(result) and type(result['schema']) is int
            and all(result[key] == value for key, value in anchor.items())
            and isinstance(result['state'], str) and isinstance(result['reason'], str), 'INVALID_REPLY')
    state, reason = result['state'], result['reason']
    if state == 'UNSEEN' or (state, reason) == ('UNKNOWN', 'UNRESOLVED_INTENT'):
        require(set(result) == fields and (state != 'UNSEEN' or reason == 'NO_LOCAL_INTENT'), 'INVALID_REPLY')
        return dict(anchor, state='UNKNOWN', reason=reason)
    require(set(result) == fields | {'bootId', 'observedBootId'}
            and result['bootId'] == pending['bootId'] and result['observedBootId'] == observed_boot
            and (reason in DECISIONS.get(state, set()) or
                 (state == 'UNKNOWN' and reason in ('NO_DURABLE_RESULT', 'UNRESOLVED_RESULT'))), 'INVALID_REPLY')
    return result


class RebootSender:
    """Record the original request before sending it. Recreated senders only query it."""

    def __init__(self, root, namespace, cohort, exchange, boot_id=linux_boot_id):
        self.root = Path(root)
        self.namespace = identifier(namespace)
        self.cohort = sha256(cohort)
        self.exchange = exchange
        self.boot_id = boot_id
        self.owner = os.geteuid()
        directory(self.root, self.owner)

    def _context(self):
        value = self.exchange(dict(schema=1, action='context'))
        require(type(value) is dict and set(value) == {'schema', 'namespace', 'cohortSha256', 'bootId',
                                                       'acceptingWrites'}
                and type(value['schema']) is int and value['schema'] == 1
                and type(value['acceptingWrites']) is bool, 'INVALID_REPLY')
        require(value['namespace'] == self.namespace, 'FOREIGN_NAMESPACE')
        require(value['cohortSha256'] == self.cohort, 'UNPAIRED_CODE')
        require(value['bootId'] == identifier(self.boot_id()), 'STALE_BOOT')
        return value

    def _finish(self, path, pending, result):
        completed = self.root / 'completed'
        if not os.path.lexists(completed):
            completed.mkdir(mode=0o700)
        directory(completed, self.owner)
        sync(self.root)
        record = dict(schema=1, request=pending, result=result)
        target = completed / (pending['requestId'] + '.json')
        if not os.path.lexists(target):
            create(target, record)
        else:
            old = decode(read(target, self.owner, durable=True))
            require(set(old) == set(record) and type(old['schema']) is int and old['schema'] == 1
                    and old['request'] == pending and type(old['result']) is dict, 'UNRESOLVED_LOCAL_RECEIPT')
            recorded_boot = identifier(old['result'].get('observedBootId'))
            verify_result(old['result'], pending, recorded_boot)
            # Preserve the first observation if local completion was interrupted.
            require(all(old['result'].get(key) == value for key, value in result.items() if key != 'observedBootId')
                    and (result['state'] == 'FAILED' or recorded_boot != pending['bootId']),
                    'UNRESOLVED_LOCAL_RECEIPT')
            sync(completed)
        require(read(path, self.owner) == encode(pending), 'UNRESOLVED_LOCAL_INTENT')
        path.unlink()
        sync(self.root)

    def submit(self):
        """Issue once for a fresh intent. A later invocation only reconciles pending."""
        directory(self.root, self.owner)
        with admission_lock(self.root / 'sender.lock', self.owner, create_if_missing=True):
            path = self.root / 'pending.json'
            context = self._context()
            boot = context['bootId']
            fresh = not os.path.lexists(path)
            if fresh:
                require(context['acceptingWrites'], 'ADMISSION_CLOSED')
                pending = request(dict(schema=1, action='reboot', namespace=self.namespace, bootId=boot,
                                       requestId=str(uuid.uuid4()), cohortSha256=self.cohort))
                create(path, pending)
                require(read(path, self.owner) == encode(pending), 'UNRESOLVED_LOCAL_INTENT')
                result = self.exchange(pending)
            else:
                raw = read(path, self.owner)
                pending = request(decode(raw))
                require(raw == encode(pending), 'UNRESOLVED_LOCAL_INTENT')
                # Context exchange contains no operation ID. Never disclose the ID to a different Root.
                require(pending['namespace'] == self.namespace, 'FOREIGN_NAMESPACE')
                result = self.exchange(dict(reference(pending), action='status'))
            result = verify_result(result, pending, boot)
            if result['state'] == 'FAILED' or (result['state'] == 'ACCEPTED' and pending['bootId'] != boot):
                self._finish(path, pending, result)
            return dict(result, currentRequest=fresh)
