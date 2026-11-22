#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Native delegation of the two fixed, journaled Main commands."""
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_key_service import Failure, Lifecycle, LifecycleRefused, Manager, Refused
from kura_key_service import decode, digest, encode, fields, read_frame, read_request_frame, require, send_frame
from kura_native_recovery_input import read_grant as input_grant
from kura_native_snapshot_validation import ATTESTATION_FIELDS, administrator_peer, live_agent
from kura_reboot_broker import Refused as PeerRefused, socket_peer
from kura_recovery_input import RecoveryInput
from kura_recovery_main_command import Controller
import kura_recovery_launch as launch

SOCKET = '/run/kura-recovery-main.sock'
COMMANDS = ('start', 'stop')
READER = 'kura-recovery-main-reader.service'
UNITS = {'kura-recovery-main.socket', 'kura-recovery-main.service', READER, 'kura-recovery-main-reader.socket'}


def require_package(lifecycle):
    manifest = lifecycle.assets()
    require(UNITS <= set(manifest['units']) and 'bin/kura_native_recovery_main.py' in manifest['files'],
            'UNAVAILABLE')


def grant_path(controller, identity, action):
    return controller.base / '.native-commands' / identity / (action + '.json')


def grant(controller, identity, action, expected, authenticate):
    manager = controller.manager
    with manager.lock(manager.state / 'admission.lock', True):
        manager.maintenance()
        manager.settled()
        peer = authenticate()
        input_grant(controller.recovery, identity, peer, writing=False)
        path, plan = controller.projection(identity)
        result = controller.inspect(path, plan)
        if action == 'start':
            require(result['state'] == 'MAIN_LAUNCH_PREPARED' and result['planSha256'] == expected
                    and controller.load(identity, 'start') is None, 'CONFLICT')
            os.close(manager.writer_lock(create=True))
        else:
            require(result['state'] == 'CM_APPLIED' and result['receiptSha256'] == expected
                    and controller.load(identity, 'start-receipt') is not None
                    and controller.load(identity, 'stop') is None, 'CONFLICT')
        record = dict(schema=1, state='MAIN_COMMAND_GRANTED', restoreId=identity, action=action,
                      expectedSha256=expected, peer=peer)
        target = grant_path(controller, identity, action)
        controller.lifecycle.directory(target.parent, private=True, create=True)
        controller.lifecycle.sync(target.parent.parent)
        controller.lifecycle.sync(controller.base)
        require(authenticate() == peer, 'FORBIDDEN')
        manager.atomic(target, encode(record), no_replace=True)
    return {key: value for key, value in record.items() if key != 'peer'}


def administrative_grant(recovery, arguments):
    require(os.geteuid() == 0 and len(arguments) == 3)
    identity, action, expected = arguments
    require(launch.IDENTITY.fullmatch(identity) and action in COMMANDS)
    digest(expected)
    require_package(recovery.lifecycle)
    with administrator_peer(recovery.lifecycle) as authenticate:
        return grant(Controller(recovery), identity, action, expected, authenticate)


def authorization(controller, identity, action, current, expected=None):
    path = grant_path(controller, identity, action)
    require(os.path.lexists(path), 'FORBIDDEN')
    value = decode(controller.manager.read(path, 8192))
    fields(value, {'schema', 'state', 'restoreId', 'action', 'expectedSha256', 'peer'})
    owner = value['peer']
    require(type(value['schema']) is int and value['schema'] == 1 and value['state'] == 'MAIN_COMMAND_GRANTED'
            and value['restoreId'] == identity and value['action'] == action and isinstance(owner, dict)
            and set(owner) == ATTESTATION_FIELDS, 'UNSAFE_FILESYSTEM')
    digest(value['expectedSha256'])
    if expected is not None:
        require(owner == current and value['expectedSha256'] == expected, 'FORBIDDEN')
    else:
        require(all(owner[key] == current[key] for key in ('rootDevice', 'rootInode', 'identitySha256')), 'FORBIDDEN')


def read_projection(identity):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(12)
        connection.connect(launch.READER_SOCKET)
        _, owner, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        require(owner == 0, 'FORBIDDEN')
        connection.sendall((identity + '\n').encode('ascii'))
        connection.shutdown(socket.SHUT_WR)
        raw = read_frame(connection)
        require(len(raw) <= 8192 and not connection.recv(1), 'PROTOCOL_MISMATCH')
        value = decode(raw)
    # kurad's reader belongs to a separate cgroup. Let that exact one-shot unit
    # exit before the unchanged Core fence scans for all other kurad processes.
    command = ['/usr/bin/systemctl', '--system', '--no-ask-password', 'show',
               '--property=ActiveState,MainPID,ControlPID', READER]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3,
                                check=False, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        if result.returncode == 0 and set(result.stdout.splitlines()) == {'ActiveState=inactive', 'MainPID=0', 'ControlPID=0'}:
            break
        time.sleep(0.025)
    else:
        raise Failure('READER_BUSY')
    return value


def handle(recovery, request, descriptor, authenticate):
    action = request.get('action')
    require(action in ('main-start', 'main-stop', 'main-original', 'main-application-original')
            and descriptor is None, 'FORBIDDEN')
    read_only = action in ('main-original', 'main-application-original')
    fields(request, {'schema', 'restoreId', 'action'} | (set() if read_only else {'expectedSha256'}))
    identity = request['restoreId']
    require(type(request['schema']) is int and request['schema'] == 1 and isinstance(identity, str)
            and launch.IDENTITY.fullmatch(identity), 'INVALID_ARGUMENT')
    original = authenticate()
    fixed = Controller(recovery, reader=read_projection)
    if action == 'main-application-original':
        authorization(fixed, identity, 'start', original)
        return fixed.application(identity)
    if action == 'main-original':
        direction = 'start' if os.path.lexists(grant_path(fixed, identity, 'start')) else 'stop'
        authorization(fixed, identity, direction, original)
        return fixed.observation(identity)
    direction = action.removeprefix('main-')
    expected = digest(request['expectedSha256'])

    def current_authority():
        current = authenticate()
        require(current == original, 'FORBIDDEN')
        authorization(fixed, identity, direction, current, expected)

    current_authority()
    fixed.authorize = current_authority
    return (fixed.start if direction == 'start' else fixed.stop)(identity, expected)


def serve_connection(connection, recovery):
    connection.settimeout(3)
    descriptor = None
    try:
        with socket_peer(connection) as peer:
            def authenticate():
                return live_agent(recovery.lifecycle, peer)
            original = authenticate()
            request, descriptor = read_request_frame(connection)
            result = handle(recovery, request, descriptor, authenticate)
            try:
                require(authenticate() == original, 'FORBIDDEN')
            except (Failure, OSError, ValueError, KeyError, Refused, LifecycleRefused, PeerRefused, subprocess.SubprocessError):
                raise Failure('UNKNOWN' if request['action'] in ('main-start', 'main-stop') else 'FORBIDDEN') from None
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
        sys.stderr.write('Kura native recovery Main actor is unavailable\n')
        sys.exit(2)
