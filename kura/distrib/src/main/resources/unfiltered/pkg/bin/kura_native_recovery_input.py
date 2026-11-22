#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Core-owned one-shot stage admission for the paired native agent."""
import hashlib
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_key_service import Failure, Lifecycle, LifecycleRefused, Manager, Refused
from kura_key_service import decode, digest, encode, fields, read_request_frame, require, send_frame
from kura_native_snapshot_validation import ATTESTATION_FIELDS, administrator_peer, live_agent
from kura_reboot_broker import Refused as PeerRefused
from kura_reboot_broker import socket_peer
from kura_recovery_input import MAX_INPUTS, MAX_SNAPSHOT, NATIVE_ADMISSIONS, RESTORE_ID, RecoveryInput

SOCKET = '/run/kura-recovery-input.sock'
SOCKET_UNIT = 'kura-recovery-input.socket'
SERVICE_UNIT = 'kura-recovery-input.service'
ADMISSION_FIELDS = {'restoreId', 'snapshotSha256', 'size', 'mode', 'passwordPolicy', 'bindingSha256'}


def exact_input(value):
    require(isinstance(value['restoreId'], str) and RESTORE_ID.fullmatch(value['restoreId']))
    digest(value['snapshotSha256'])
    digest(value['bindingSha256'])
    RecoveryInput.check_format(value['mode'], value['passwordPolicy'])
    require(type(value['size']) is int and 0 < value['size'] <= MAX_SNAPSHOT)


def require_package(lifecycle):
    manifest = lifecycle.assets()
    require({SOCKET_UNIT, SERVICE_UNIT} <= set(manifest['units'])
            and 'bin/kura_native_recovery_input.py' in manifest['files'], 'UNAVAILABLE')


def administrative_grant(recovery, arguments):
    require(len(arguments) == 6 and os.geteuid() == 0, 'FORBIDDEN')
    identity, sha, size, mode, policy, binding = arguments
    require(re.fullmatch('[1-9][0-9]{0,7}', size) is not None)
    options = dict(restoreId=identity, snapshotSha256=sha, size=int(size), mode=mode,
                   passwordPolicy=policy, bindingSha256=binding)
    exact_input(options)
    lifecycle = recovery.lifecycle
    require_package(lifecycle)
    with administrator_peer(lifecycle) as authenticate:
        return grant(recovery, options, authenticate)


def grant(recovery, options, authenticate):
    manager = recovery.manager
    identity = options['restoreId']
    with manager.lock(manager.state / 'admission.lock', False):
        manager.maintenance()
        manager.settled()
        recovery.ensure_spool()
        with recovery.spool_lock(True):
            require(recovery.original_locked(identity)['state'] == 'RECOVERY_INPUT_ABSENT', 'RECOVERY_INPUT_EXISTS')
            table = recovery.spool / NATIVE_ADMISSIONS
            recovery.lifecycle.directory(table, private=True, create=True)
            recovery.lifecycle.sync(recovery.spool)
            entry = table / identity
            require(not os.path.lexists(entry), 'RECOVERY_INPUT_EXISTS')
            require(sum(1 for _ in table.iterdir()) < MAX_INPUTS, 'RESOURCE_EXHAUSTED')
            validation = manager.validation_component()
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                _, expected = validation.binding()
                require(expected == options['bindingSha256'], 'COHORT_CHANGED')
                record = dict(schema=1, state='RECOVERY_INPUT_GRANTED', peer=authenticate(), **options)
                entry.mkdir(mode=0o700)
                recovery.lifecycle.sync(table)
                manager.atomic(entry / 'grant.json', encode(record), no_replace=True)
    return {key: value for key, value in record.items() if key != 'peer'}


def read_grant(recovery, identity, current, *, writing):
    entry = recovery.spool / NATIVE_ADMISSIONS / identity
    require(os.path.lexists(entry / 'grant.json'), 'FORBIDDEN')
    raw = recovery.manager.read(entry / 'grant.json', 8192)
    value = decode(raw)
    fields(value, ADMISSION_FIELDS | {'schema', 'state', 'peer'})
    exact_input(value)
    owner = value['peer']
    require(type(value['schema']) is int and value['schema'] == 1 and value['restoreId'] == identity
            and value['state'] == 'RECOVERY_INPUT_GRANTED' and isinstance(owner, dict)
            and set(owner) == ATTESTATION_FIELDS, 'UNSAFE_FILESYSTEM')
    if writing:
        require(owner == current, 'FORBIDDEN')
    else:
        require(all(owner[name] == current[name] for name in ('rootDevice', 'rootInode', 'identitySha256')),
                'FORBIDDEN')
    return entry, value, raw


def handle(recovery, request, descriptor, uid, authenticate):
    action = request.get('action')
    require(action in ('recovery-input-stage', 'recovery-input-original'), 'FORBIDDEN')
    writing = action == 'recovery-input-stage'
    fields(request, {'schema', 'action'} | (ADMISSION_FIELDS if writing else {'restoreId'}))
    require(type(request['schema']) is int and request['schema'] == 1 and (descriptor is not None) == writing)
    identity = request['restoreId']
    require(isinstance(identity, str) and RESTORE_ID.fullmatch(identity))
    if writing:
        exact_input(request)
    manager = recovery.manager
    with manager.lock(manager.state / 'admission.lock', False):
        manager.maintenance()
        with recovery.spool_lock(writing):
            current = authenticate()
            entry, allowed, raw = read_grant(recovery, identity, current, writing=writing)
            if not writing:
                observed = recovery.original_locked(identity)
                if observed['state'] == 'RECOVERY_INPUT_ABSENT':
                    observed['state'] = 'RECOVERY_INPUT_GRANTED'
                return observed
            manager.settled()
            require(all(allowed[name] == request[name] for name in ADMISSION_FIELDS), 'FORBIDDEN')
            require(recovery.original_locked(identity)['state'] == 'RECOVERY_INPUT_ABSENT', 'RECOVERY_INPUT_EXISTS')
            require(not os.path.lexists(entry / 'attempt.json'), 'RECOVERY_INPUT_EXISTS')
            # The grant is consumed before a descriptor is copied or a validator runs.
            attempt = dict(schema=1, restoreId=identity, grantSha256=hashlib.sha256(raw).hexdigest())
            manager.atomic(entry / 'attempt.json', encode(attempt), no_replace=True)

            def recheck():
                require(authenticate() == current, 'FORBIDDEN')

            return recovery.stage_locked(identity, descriptor, request['snapshotSha256'], request['mode'],
                                         request['passwordPolicy'], request['bindingSha256'],
                                         source_uid=uid, expected_size=request['size'], recheck=recheck)


def serve_connection(connection, recovery):
    connection.settimeout(3)
    descriptor = None
    try:
        with socket_peer(connection) as peer:
            def authenticate():
                return live_agent(recovery.lifecycle, peer)
            original = authenticate()
            request, descriptor = read_request_frame(connection)
            result = handle(recovery, request, descriptor, peer[1], authenticate)
            try:
                require(authenticate() == original, 'FORBIDDEN')
            except (Failure, OSError, ValueError, KeyError, Refused, LifecycleRefused, PeerRefused, subprocess.SubprocessError):
                raise Failure('UNKNOWN' if request['action'] == 'recovery-input-stage' else 'FORBIDDEN')
    except Failure as error:
        result = dict(schema=1, error=error.reason)
    except (OSError, ValueError, KeyError, Refused, LifecycleRefused, PeerRefused, subprocess.SubprocessError):
        result = dict(schema=1, error='UNAVAILABLE')
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        send_frame(connection, result)
    except (OSError, Failure):
        pass


def serve():
    require(os.geteuid() == 0 and os.environ.get('LISTEN_PID') == str(os.getpid())
            and os.environ.get('LISTEN_FDS') == '1', 'UNAVAILABLE')
    lifecycle = Lifecycle()
    lifecycle.no_overrides()
    require_package(lifecycle)
    require(lifecycle.fence() is None, 'MAINTENANCE')
    recovery = RecoveryInput(Manager(), lifecycle)
    with socket.socket(fileno=3) as listener:
        require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM
                and listener.getsockname() == SOCKET
                and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN), 'UNAVAILABLE')
        while True:
            connection, _ = listener.accept()
            with connection:
                serve_connection(connection, recovery)


if __name__ == '__main__':
    try:
        serve()
    except (Failure, LifecycleRefused, Refused, OSError, KeyError):
        sys.stderr.write('Kura native recovery input actor is unavailable\n')
        sys.exit(2)
