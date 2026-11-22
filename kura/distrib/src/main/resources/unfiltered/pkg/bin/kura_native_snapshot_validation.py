#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Only the live, Root-attested native agent can invoke Core's read-only validator."""

import grp
import hashlib
import os
from pathlib import Path
import pwd
import re
import socket
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_key_service import Failure, Lifecycle, LifecycleRefused, Manager, Refused
from kura_key_service import decode, read_request_frame, require, send_frame
from kura_reboot_broker import proc_file, proc_status, socket_peer, verify_alive, verify_identity
from kura_reboot_broker import Refused as PeerRefused

SOCKET = '/run/kura-snapshot-validation/control.sock'
ACCOUNT = 'kura-management-agent'
AGENT = 'kura-management-agent-v2.service'
VENDOR_UNIT = '/usr/lib/systemd/system/' + AGENT
ATTESTATION = Path('/run/kura-native-snapshot-validation/agent.json')
AGENT_IDENTITY = Path('/etc/kura-management-runtime/agent.json')
PURPOSE = 'yofc.kura.native-snapshot-validation-peer.v1'
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
UNIT_FIELDS = ('Id', 'LoadState', 'FragmentPath', 'DropInPaths', 'NeedDaemonReload',
               'ActiveState', 'MainPID', 'InvocationID', 'ControlGroup', 'User', 'Group')
ATTESTATION_FIELDS = frozenset(('schema', 'purpose', 'invocationId', 'bootId', 'rootDevice',
                               'rootInode', 'identitySha256'))


def unit_state():
    command = ['/usr/bin/systemctl', '--system', '--no-ask-password', 'show', '--all',
               '--property=' + ','.join(UNIT_FIELDS), AGENT]
    result = subprocess.run(command, capture_output=True, timeout=4, check=False,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    require(result.returncode == 0 and len(result.stdout) < 16384, 'FORBIDDEN')
    pairs = [line.split('=', 1) for line in result.stdout.decode('ascii').splitlines()]
    require(all(len(row) == 2 for row in pairs), 'FORBIDDEN')
    properties = dict(pairs)
    require(len(pairs) == len(properties) and set(properties) == set(UNIT_FIELDS), 'FORBIDDEN')
    return properties


def live_agent(lifecycle, peer):
    pid, uid, gid, pidfd = peer
    verify_alive(pidfd, 'FORBIDDEN')
    account = pwd.getpwnam(ACCOUNT)
    control = grp.getgrnam('kura-management').gr_gid
    readers = grp.getgrnam(ACCOUNT).gr_gid
    require(uid == account.pw_uid > 0 and gid == control > 0 and account.pw_gid == readers > 0
            and control != readers and account.pw_dir == '/nonexistent'
            and account.pw_shell in ('/usr/sbin/nologin', '/sbin/nologin'), 'FORBIDDEN')
    runtime = unit_state()
    require(runtime == {'Id': AGENT, 'LoadState': 'loaded', 'FragmentPath': VENDOR_UNIT,
                        'DropInPaths': '', 'NeedDaemonReload': 'no', 'ActiveState': 'active',
                        'MainPID': str(pid), 'InvocationID': runtime['InvocationID'],
                        'ControlGroup': '/system.slice/' + AGENT, 'User': ACCOUNT,
                        'Group': 'kura-management'}, 'FORBIDDEN')
    require(re.fullmatch('[0-9a-f]{32}', runtime['InvocationID']) is not None
            and proc_file(pid, 'cgroup').splitlines() == [('0::/system.slice/' + AGENT).encode()],
            'FORBIDDEN')
    status = proc_status(pid)
    verify_identity(status, uid, gid)
    require(set(map(int, status['Groups'].split())) == {control, readers}
            and status['NoNewPrivs'].strip() == '1'
            and all(int(status[key], 16) == 0 for key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')),
            'FORBIDDEN')

    attestation = decode(lifecycle.read(ATTESTATION, limit=4096))
    identity_raw = lifecycle.read(AGENT_IDENTITY, limit=4096, private=False)
    root = os.stat('/')
    value = dict(schema=1, purpose=PURPOSE, invocationId=runtime['InvocationID'],
                 bootId=BOOT_ID.read_text().strip(), rootDevice=root.st_dev, rootInode=root.st_ino,
                 identitySha256=hashlib.sha256(identity_raw).hexdigest())
    require(set(attestation) == ATTESTATION_FIELDS and type(attestation.get('schema')) is int
            and attestation == value, 'FORBIDDEN')
    identity = decode(identity_raw)
    require(identity.get('profile') == 'native-nonroot-v1'
            and (identity.get('uid'), identity.get('gid'), identity.get('readerGid')) == (uid, gid, readers),
            'FORBIDDEN')
    verify_alive(pidfd, 'FORBIDDEN')
    return value


def validation_request(manager, request, descriptor, uid):
    action = request.get('action')
    require(action in ('core-validation-info', 'core-snapshot-validate', 'core-snapshot-inventory'), 'FORBIDDEN')
    validator = manager.validation_component()
    if action == 'core-validation-info':
        require(descriptor is None, 'PROTOCOL_MISMATCH')
        return validator.info(request)
    if action == 'core-snapshot-inventory':
        require(descriptor is None, 'PROTOCOL_MISMATCH')
        core = pwd.getpwnam('kurad')
        return validator.snapshot_inventory(request, core.pw_uid, core.pw_gid)
    require(descriptor is not None, 'PROTOCOL_MISMATCH')
    return validator.validate(request, descriptor, uid, core_uid=pwd.getpwnam('kurad').pw_uid)


def serve_one(connection, lifecycle, manager):
    connection.settimeout(3)
    descriptor = None
    try:
        with socket_peer(connection) as peer:
            binding = live_agent(lifecycle, peer)
            request, descriptor = read_request_frame(connection)
            result = validation_request(manager, request, descriptor, peer[1])
            require(live_agent(lifecycle, peer) == binding, 'FORBIDDEN')
    except Failure as error:
        result = dict(schema=1, error=error.reason)
    except (OSError, ValueError, KeyError, Refused, LifecycleRefused, PeerRefused, subprocess.SubprocessError):
        result = dict(schema=1, error='FORBIDDEN')
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
    manifest = lifecycle.assets()
    require('kura-snapshot-validation.socket' in manifest['units']
            and 'bin/kura_native_snapshot_validation.py' in manifest['files'], 'UNAVAILABLE')
    require(lifecycle.fence() is None, 'MAINTENANCE')
    manager = Manager()
    with socket.socket(fileno=3) as listener:
        require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM
                and listener.getsockname() == SOCKET
                and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1, 'UNAVAILABLE')
        while True:
            connection, _ = listener.accept()
            with connection:
                serve_one(connection, lifecycle, manager)


if __name__ == '__main__':
    try:
        serve()
    except (Failure, LifecycleRefused, Refused, OSError, KeyError):
        sys.stderr.write('Kura native snapshot validation unavailable\n')
        sys.exit(2)
