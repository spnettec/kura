# SPDX-License-Identifier: EPL-2.0
"""Pair the installed Kura Main to one private, single-use Netfilter worker."""
import hashlib
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import struct
import stat
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import public_file
from kura_clock_journal import Refused, decode, encode, require
from kura_journal_export import package_cohort as build_cohort, paired_unit
from kura_ownership_markers import SOURCES as MARKER_SOURCES, verify_main
from kura_reboot_broker import ENVIRONMENT, proc_status, socket_peer, verify_identity

NAME = 'kura-firewall-publish'
HOME = Path('/usr/libexec') / NAME
SOCKET = NAME + '.socket'
ACTOR = NAME + '@.service'
WORKER = HOME / 'worker'
CORE_HOME = Path('/opt/eclipse/kura')
SOURCES = tuple(name for name in MARKER_SOURCES if name.startswith('bin/')) + (
    'bin/kura_firewall_publish.py', 'install/' + SOCKET, 'install/' + ACTOR)
MAX_REQUEST = 8 * 1024 * 1024
TOKEN = ('operationId', 'rootScope', 'requestSha256', 'wireSha256')


def package_cohort(home, worker, architecture):
    raw = worker.read_bytes()
    require(64 <= len(raw) <= MAX_REQUEST and raw[:7] == b'\x7fELF\x02\x01\x01'
            and int.from_bytes(raw[18:20], 'little') == {'arm64': 183, 'amd64': 62}[architecture],
            'WRONG_FIREWALL_WORKER_ARCHITECTURE')
    directory = Path('libexec/firewall-publish')
    build_cohort(home, pair_directory=directory, sources=SOURCES)
    manifest = home / directory / 'cohort.json'
    value = decode(manifest.read_bytes())
    value['files']['worker'] = hashlib.sha256(raw).hexdigest()
    manifest.write_bytes(encode(value) + b'\n')


def verify_actor(unit):
    require(re.fullmatch(r'kura-firewall-publish@[A-Za-z0-9_.:\\-]{1,128}\.service', unit),
            'UNPAIRED_FIREWALL_ACTOR')
    status = proc_status(os.getpid())
    verify_identity(status, 0, 0)
    require(status['NoNewPrivs'].strip() == '1' and all(int(status[field], 16) == 1 << 12
            for field in ('CapPrm', 'CapEff', 'CapBnd', 'CapAmb', 'CapInh')), 'UNPAIRED_FIREWALL_ACTOR')
    cohort = verify_sources()
    paired_unit(SOCKET, SOCKET, cohort['files'][SOCKET])
    paired_unit(unit, ACTOR, cohort['files'][ACTOR])
    return cohort['mainUnitSha256']


def verify_sources():
    cohort = decode(public_file(HOME / 'cohort.json'))
    require(set(cohort) == {'schema', 'files', 'mainUnitSha256'} and type(cohort['schema']) is int
            and cohort['schema'] == 1 and re.fullmatch(r'[0-9a-f]{64}', cohort['mainUnitSha256'])
            and set(cohort['files']) == {Path(path).name for path in SOURCES} | {'worker'}, 'UNPAIRED_FIREWALL_ACTOR')
    for name, digest in cohort['files'].items():
        raw = public_file(HOME / name, MAX_REQUEST if name == 'worker' else 1024 * 1024)
        require(hashlib.sha256(raw).hexdigest() == digest, 'UNPAIRED_FIREWALL_ACTOR')
    return cohort


@contextlib.contextmanager
def package_lock(manager):
    path = manager.store.path('/var/lib/dpkg/lock')
    manager.directory(path.parent)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == manager.owner and info.st_gid == 0
                and info.st_nlink == 1 and info.st_size == 0 and stat.S_IMODE(info.st_mode) in (0o600, 0o640)
                and os.path.samestat(info, path.lstat()), 'UNPAIRED_CORE_PACKAGE_LOCK')
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused('CORE_PACKAGE_MAINTENANCE_ACTIVE') from None
        yield
    finally:
        os.close(fd)


def initialize_domain(manager, policy):
    # The arguments exist only for isolated tests. The CLI always uses live /.
    with package_lock(manager), manager.lock(manager.state / 'admission.lock', True):
        manager.maintenance()
        policy.assets()
        cohort = verify_sources()
        require(hashlib.sha256(public_file(CORE_HOME / 'bin/kura_firewall_publish.py')).hexdigest()
                == cohort['files']['kura_firewall_publish.py'], 'UNPAIRED_FIREWALL_INITIALIZER')
        main = paired_unit('kura.service', 'kura.service', cohort['mainUnitSha256'],
                           ('MainPID', 'ControlPID', 'ActiveState'), main=True)
        require(main['MainPID'] == main['ControlPID'] == '0' and main['ActiveState'] == 'inactive',
                'CORE_MAIN_NOT_IDLE')
        writers = manager.writer_lock(create=True)
        try:
            try:
                fcntl.flock(writers, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused('CORE_WRITERS_ACTIVE') from None
            policy.directory(policy.path('/var/lib/kura-legacy-firewall/publication'), private=True, create=True)

            def inherit():
                os.dup2(writers, 3)
                if writers != 3:
                    os.close(writers)

            # FD3 is already open if the writer descriptor is above 3. Preserve
            # that slot through Python's close_fds pass, then replace it only in
            # the child. Parent package/admission/writer fences remain held.
            result = subprocess.run(['/usr/bin/setpriv', '--bounding-set=-all', '--inh-caps=-all',
                                     '--ambient-caps=-all', '--no-new-privs',
                                     str(WORKER), '--initialize-persistent-root'],
                                    pass_fds=tuple(sorted({3, writers})), preexec_fn=inherit,
                                    capture_output=True, timeout=20, env=ENVIRONMENT, cwd='/')
            if result.returncode != 0:
                reason = next((name for name in ('UNSUPPORTED_ROOT_IDENTITY', 'LEGACY_DOMAIN',
                                                'UNRESOLVED', 'UNPAIRED', 'BUSY')
                               if name.encode() in result.stderr), 'ROOT_DOMAIN_INITIALIZATION_FAILED')
                raise Refused(reason)
            require(0 < len(result.stdout) <= 1024, 'INVALID_ROOT_DOMAIN_RESULT')
            value = decode(result.stdout)
            require(set(value) == {'schema', 'state', 'rootScopeScheme', 'rootScope'}
                    and type(value['schema']) is int and value['schema'] == 2
                    and value['state'] in ('INITIALIZED', 'EXISTS') and value['rootScopeScheme'] == 'kernel-fh-v2'
                    and isinstance(value['rootScope'], str) and re.fullmatch('[0-9a-f]{64}', value['rootScope']),
                    'INVALID_ROOT_DOMAIN_RESULT')
            return value
        finally:
            os.close(writers)


def initialize_persistent_root():
    require(sys.platform == 'linux' and os.geteuid() == os.getegid() == 0
            and Path(__file__).resolve(strict=True) == (CORE_HOME / 'bin/kura_firewall_publish.py').resolve(strict=True),
            'UNPAIRED_FIREWALL_INITIALIZER')
    # Lazy imports keep the socket actor's flat, capability-restricted cohort
    # independent of the key service. Only this fixed Core CLI uses its lock API.
    from kura_key_service import Manager, Failure
    from kura_key_service_lifecycle import Lifecycle, Refused as CoreRefused
    try:
        return initialize_domain(Manager(), Lifecycle())
    except (Failure, CoreRefused):
        raise Refused('CORE_ROOT_DOMAIN_UNAVAILABLE') from None


def frame(stream, maximum):
    deadline = time.monotonic() + 10

    def read(size):
        data = bytearray()
        while len(data) < size:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'INVALID_FIREWALL_FRAME')
            stream.settimeout(remaining)
            part = stream.recv(size - len(data))
            require(part, 'INVALID_FIREWALL_FRAME')
            data.extend(part)
        return bytes(data)

    size, = struct.unpack('>I', read(4))
    require(0 < size <= maximum, 'INVALID_FIREWALL_FRAME')
    raw = read(size)
    require(b'\n' not in raw and b'\r' not in raw, 'INVALID_FIREWALL_FRAME')
    return raw


def send(stream, value):
    raw = encode(value)
    stream.settimeout(3)
    stream.sendall(struct.pack('>I', len(raw)) + raw)


def worker_reply(worker):
    raw = worker.stdout.readline(2 * 1024 * 1024 + 1)
    require(0 < len(raw) <= 2 * 1024 * 1024 and raw.endswith(b'\n'), 'NO_FIREWALL_RESULT')
    value = json.loads(raw)
    require(type(value) is dict, 'INVALID_FIREWALL_RESULT')
    # The original kernel ACK is kept in the Root journal.
    value.pop('ack', None)
    return value


def serve(stream, unit):
    require(stream.family == socket.AF_UNIX and stream.type == socket.SOCK_STREAM
            and stream.getsockname() == '/run/' + NAME + '.sock', 'UNPAIRED_FIREWALL_SOCKET')
    main = verify_actor(unit)
    with socket_peer(stream) as peer:
        verify_main(peer, main)
        request = frame(stream, MAX_REQUEST)
        with subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=ENVIRONMENT) as worker:
            try:
                worker.stdin.write(request + b'\n')
                worker.stdin.flush()
                value = worker_reply(worker)
                if value.get('state') == 'PREPARED':
                    require(value['requestSha256'] == hashlib.sha256(request).hexdigest(), 'UNPAIRED_FIREWALL_PLAN')
                    token = {key: value[key] for key in TOKEN}
                    send(stream, value)
                    require(decode(frame(stream, 1024)) == token, 'INVALID_FIREWALL_APPROVAL')
                    verify_main(peer, main)
                    worker.stdin.write(encode(token) + b'\n')
                    worker.stdin.flush()
                    value = worker_reply(worker)
                require(value.get('state') in {'SCOPE', 'UNKNOWN', 'NOT_FOUND', 'APPLIED', 'REJECTED', 'UNCHANGED'},
                        'INVALID_FIREWALL_RESULT')
                worker.stdin.close()
                require(worker.wait(timeout=3) == 0, 'NO_FIREWALL_RESULT')
                send(stream, value)
            finally:
                if worker.poll() is None:
                    worker.kill()


def main():
    try:
        if sys.argv[1:] == ['--initialize-persistent-root']:
            sys.stdout.buffer.write(encode(initialize_persistent_root()) + b'\n')
            return 0
        require(len(sys.argv) == 2, 'UNPAIRED_FIREWALL_ACTOR')
        with socket.socket(fileno=0) as stream:
            serve(stream, sys.argv[1])
    # An incomplete response still requires original-ID reconciliation. Close
    # the connection and keep routine refusals inside the service memory limit.
    except Refused as error:
        print(f'Kura firewall publication refused: {error.reason}', file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('Kura firewall publication failed: transport or invalid reply', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
