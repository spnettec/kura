# SPDX-License-Identifier: EPL-2.0
"""Verify Main's declared credential layout without releasing the declaration."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import pwd
import re
import socket
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import public_file
from kura_clock_journal import Refused, decode, require
from kura_journal_export import (ACTOR, ACTOR_HOME, ACTOR_UNIT, COHORT, FILES, GENERATION_DROPIN,
                                 PROOF_FILES, PROOF_SOCKET, paired_unit)
from kura_reboot_broker import (MAIN_CGROUP, MAIN_PROPERTIES, MAIN_UNIT, file_hash, proc_file,
                               proc_status, socket_peer, verify_alive, verify_identity)

WORKERS = {
    ACTOR_UNIT: (ACTOR, ACTOR_HOME, 0),
    'kura-command-executor@.service': ('kura', Path('/usr/libexec/kura-command-executor'), 0),
    'kura-icmp-probe@.service': ('kura-icmp-probe', Path('/usr/libexec/kura-command-executor'), 1 << 13),
}
MAX_CONNECTIONS = 16


def sandbox(status, capabilities):
    require(status['NoNewPrivs'].strip() == '1' and all(int(status[name], 16) == capabilities
            for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')), 'UNAUTHORIZED')


def verify_service():
    status = proc_status(os.getpid())
    verify_identity(status, 0, 0)
    sandbox(status, 0)
    manifest = decode(public_file(ACTOR_HOME / COHORT))
    require(manifest.keys() == {'schema', 'files', 'mainUnitSha256'} and type(manifest['schema']) is int
            and manifest['schema'] == 1 and manifest['files'].keys() == set(FILES)
            and re.fullmatch('[0-9a-f]{64}', manifest['mainUnitSha256']), 'UNPAIRED_EXPORT')
    for name, pin in manifest['files'].items():
        require(file_hash(public_file(ACTOR_HOME / name)) == pin, 'UNPAIRED_EXPORT')
    for unit in PROOF_FILES:
        paired_unit(unit, unit, manifest['files'][unit])
    return manifest['mainUnitSha256']


def verify_worker(peer, unit, main_hash):
    pid, uid, gid, pidfd = peer
    # systemd connects while still Root, then execs the worker in the same PID.
    require(pid > 1 and uid == gid == 0, 'UNAUTHORIZED')
    verify_alive(pidfd)
    prefix, separator, instance = unit.partition('@')
    template = prefix + '@.service'
    require(separator and template in WORKERS
            and re.fullmatch(r'[A-Za-z0-9_.:\\-]{1,128}\.service', instance), 'UNAUTHORIZED')
    account_name, home, capabilities = WORKERS[template]
    account = pwd.getpwnam(account_name)
    require(account.pw_uid > 0 and account.pw_gid > 0, 'UNAUTHORIZED')
    status = proc_status(pid)
    verify_identity(status, account.pw_uid, account.pw_gid)
    sandbox(status, capabilities)
    manifest = decode(public_file(home / COHORT))
    pin = manifest['files'][template]
    require(manifest['mainUnitSha256'] == main_hash and file_hash(public_file(home / template)) == pin,
            'UNPAIRED_EXPORT')
    actor = paired_unit(unit, template, pin, MAIN_PROPERTIES + ('User', 'Group'))
    group = actor['ControlGroup']
    require(actor['ActiveState'] == 'active' and actor['MainPID'] == str(pid)
            and actor['User'] == actor['Group'] == account_name
            and group.startswith('/system.slice/') and group.endswith('/' + unit)
            and proc_file(pid, 'cgroup').splitlines() == [('0::' + group).encode()], 'UNAUTHORIZED')
    verify_alive(pidfd)


def answer(peer, request, main_hash):
    invocation, separator, actor = request.decode('ascii').removesuffix('\n').partition(' ')
    require(request.endswith(b'\n') and separator and re.fullmatch('[0-9a-f]{32}', invocation),
            'INVALID_PROOF_REQUEST')
    verify_worker(peer, actor, main_hash)
    unit = paired_unit(MAIN_UNIT, MAIN_UNIT, main_hash, MAIN_PROPERTIES + ('User', 'Group'), main=True)
    require(unit['ActiveState'] == 'active' and unit['User'] == unit['Group'] == 'kurad'
            and int(unit['MainPID']) > 1 and '0::' + unit['ControlGroup'] == MAIN_CGROUP
            and unit['InvocationID'] == invocation
            and str(GENERATION_DROPIN) in unit['DropInPaths'].split(), 'UNPAIRED_EXPORT')
    verify_alive(peer[3])
    return invocation.encode('ascii') + b'\n'


def connection(stream, main_hash):
    with stream:
        try:
            stream.settimeout(50)
            with socket_peer(stream) as peer, stream.makefile('rb') as request:
                # Journal rechecks Main after collecting output. Keep the private
                # proof stream for that check and independently validate each request.
                for _ in range(6):
                    stream.sendall(answer(peer, request.readline(240), main_hash))
        except (Refused, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
            return


def serve():
    require(os.environ.get('LISTEN_PID') == str(os.getpid()) and os.environ.get('LISTEN_FDS') == '1',
            'UNPAIRED_EXPORT')
    with socket.socket(fileno=3) as listener, ThreadPoolExecutor(MAX_CONNECTIONS) as workers:
        require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM
                and listener.getsockname() == str(PROOF_SOCKET)
                and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN), 'UNPAIRED_EXPORT')
        main_hash = verify_service()
        active = set()
        while True:
            stream, _ = listener.accept()
            active = {job for job in active if not job.done()}
            if len(active) < MAX_CONNECTIONS:
                active.add(workers.submit(connection, stream, main_hash))
            else:
                stream.close()


if __name__ == '__main__':
    serve()
