# SPDX-License-Identifier: EPL-2.0
"""Delegate fixed Debian BIND service operations from the paired Kura Main."""
import fcntl
import hashlib
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import stat
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import HOME, VENDOR_UNIT_ROOTS, public_file, unit_directory_present
from kura_clock_journal import MAX_OPERATIONS, Refused, create, decode, digest, directory, encode, identifier, read, require
from kura_journal_export import main_peer, paired_unit, unit_properties
from kura_modem_cohort import active_provider
from kura_reboot_broker import ENVIRONMENT, UNIT_PROPERTIES, file_hash, proc_status, receive, send, socket_peer

ACTOR_HOME = Path('/usr/libexec/kura-bind-service')
STATE = Path('/var/lib/kura-bind-service')
SOCKET = Path('/run/kura-bind-service.sock')
SOCKET_UNIT = 'kura-bind-service.socket'
ACTOR_UNIT = 'kura-bind-service@.service'
UNIT = 'named.service'
ALIAS = 'bind9.service'
NAMED = Path('/usr/sbin/named')
HELPER = 'bin/kura_bind_service.py'
CLIENT = ('/usr/bin/python3', '-I', '-B', str(HOME / HELPER), 'client')
SYSTEMCTL = ('/usr/bin/systemctl', '--system', '--no-ask-password', '--no-pager')
SOURCES = (HELPER, 'bin/kura_clock_broker.py', 'bin/kura_clock_journal.py', 'bin/kura_journal_export.py',
           'bin/kura_modem_cohort.py', 'bin/kura_reboot_broker.py', 'bin/kura_reboot_journal.py',
           'bin/kura_reboot_protocol.py', f'install/{SOCKET_UNIT}', f'install/{ACTOR_UNIT}')
FILES = {Path(name).name for name in SOURCES}
ACTIONS = ('status', 'start', 'stop', 'restart')
RESULTS = ('APPLIED', 'REFUSED', 'UNKNOWN', 'INACTIVE')


def package_cohort(home):
    target = home / 'libexec/bind-service'
    target.mkdir()
    files = {}
    for name in SOURCES:
        source = home / name
        require(source.is_file() and not source.is_symlink(), 'UNPAIRED_BIND_RELEASE')
        shutil.copyfile(source, target / source.name)
        files[source.name] = file_hash(source.read_bytes())
    main = (home / 'install/kura.service').read_bytes()
    (target / 'cohort.json').write_bytes(encode(dict(schema=1, mainUnitSha256=file_hash(main), files=files)) + b'\n')


def verify_actor(unit):
    require(re.fullmatch(r'kura-bind-service@[A-Za-z0-9_.:\-]{1,128}\.service', unit), 'UNPAIRED_BIND_RELEASE')
    status = proc_status(os.getpid())
    require(os.getuid() == os.geteuid() == 0 and os.getgid() == os.getegid() == 0
            and status['NoNewPrivs'].strip() == '1'
            and all(int(status[name], 16) == 0 for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')),
            'UNPAIRED_BIND_RELEASE')
    cohort = decode(public_file(ACTOR_HOME / 'cohort.json'))
    require(set(cohort) == {'schema', 'files', 'mainUnitSha256'} and type(cohort['schema']) is int
            and cohort['schema'] == 1 and set(cohort['files']) == FILES, 'UNPAIRED_BIND_RELEASE')
    for name, expected in cohort['files'].items():
        require(file_hash(public_file(ACTOR_HOME / name)) == expected, 'UNPAIRED_BIND_RELEASE')
    paired_unit(SOCKET_UNIT, SOCKET_UNIT, cohort['files'][SOCKET_UNIT])
    paired_unit(unit, ACTOR_UNIT, cohort['files'][ACTOR_UNIT])
    return cohort['mainUnitSha256']


def request(action, operation):
    require(action in ACTIONS, 'INVALID_BIND_REQUEST')
    identifier(operation)
    return dict(schema=1, action=action, operationId=operation)


def checked_package_asset(path, manifest, *, maximum=1024 * 1024):
    canonical = path.resolve(strict=True)
    require(canonical == path or (path.parent == Path('/lib/systemd/system')
                                  and canonical == Path('/usr/lib/systemd/system') / path.name),
            'UNPAIRED_BIND_UNIT')
    # Use the installed Debian record to check package ownership and the
    # original package checksum, then bind the observed content with SHA-256.
    owner = subprocess.check_output(['/usr/bin/dpkg-query', '-S', str(canonical)],
                                    env=ENVIRONMENT, timeout=3).rstrip()
    require(owner == os.fsencode('bind9: ' + str(canonical)), 'UNPAIRED_BIND_UNIT')
    records = [line.split(b'  ', 1)[0] for line in manifest.splitlines()
               if line.endswith(b'  ' + os.fsencode(str(canonical)[1:]))]
    require(len(records) == 1 and re.fullmatch(rb'[0-9a-f]{32}', records[0]), 'UNPAIRED_BIND_UNIT')
    payload = public_file(path, maximum)
    require(hashlib.md5(payload, usedforsecurity=False).hexdigest().encode('ascii') == records[0],
            'UNPAIRED_BIND_UNIT')
    return file_hash(payload)


def target():
    fields = UNIT_PROPERTIES + ('ActiveState', 'MainPID', 'InvocationID')
    observed = unit_properties(UNIT, fields)
    require(observed['Id'] == UNIT and set(observed['Names'].split()) in ({UNIT}, {UNIT, ALIAS})
            and observed['LoadState'] == 'loaded'
            and observed['FragmentPath'] in {str(root / UNIT) for root in VENDOR_UNIT_ROOTS}
            and observed['SourcePath'] == observed['DropInPaths'] == ''
            and observed['Transient'] == observed['NeedDaemonReload'] == 'no', 'UNPAIRED_BIND_UNIT')
    # An installation interrupted mid-unpack cannot authorize a service job.
    package = subprocess.check_output(['/usr/bin/dpkg-query', '-W', '-f=${db:Status-Status} ${Version}', 'bind9'],
                                      env=ENVIRONMENT, timeout=3).decode('ascii')
    require(re.fullmatch(r'installed [0-9A-Za-z:.+~\-]+', package), 'UNPAIRED_BIND_UNIT')
    manifest = public_file(Path('/var/lib/dpkg/info/bind9.md5sums'))
    fragment = checked_package_asset(Path(observed['FragmentPath']), manifest)
    binary = checked_package_asset(NAMED, manifest, maximum=8 * 1024 * 1024)
    observed.pop('Names')
    state = observed.pop('ActiveState')
    pid = observed.pop('MainPID')
    invocation = observed.pop('InvocationID')
    require(state in ('active', 'inactive', 'failed') and re.fullmatch('[0-9]+', pid)
            and re.fullmatch('(?:[0-9a-f]{32})?', invocation), 'BIND_NOT_SETTLED')
    if state == 'active':
        require(int(pid) > 1 and invocation not in ('', '0' * 32), 'BIND_NOT_SETTLED')
    else:
        require(pid == '0', 'BIND_NOT_SETTLED')
    return digest(dict(manager=observed, package=package, fragment=fragment, binary=binary)), state, invocation


def provision():
    require(os.getuid() == os.geteuid() == 0 and unit_directory_present(STATE.parent), 'UNPAIRED_BIND_STATE')
    try:
        STATE.mkdir(mode=0o700)
    except FileExistsError:
        pass
    directory(STATE, 0)
    require(STATE.lstat().st_gid == 0, 'UNPAIRED_BIND_STATE')


def state_binding():
    metadata = STATE.stat()
    machine = public_file(Path('/etc/machine-id'), 64).strip()
    require(re.fullmatch(rb'[0-9a-f]{32}', machine), 'UNPAIRED_BIND_STATE')
    return [machine.decode('ascii'), metadata.st_dev, metadata.st_ino]


def write_job(action):
    subprocess.run([*SYSTEMCTL, '--job-mode=fail', action, UNIT], env=ENVIRONMENT, timeout=28, check=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def resolve_result(path, intent):
    receipt = decode(read(path, 0))
    require(receipt == dict(intentSha256=digest(intent), state='APPLIED'), 'UNPAIRED_BIND_STATE')
    return receipt['state']


def locked_operation(expected, authorize):
    root = state_binding()
    anchor = STATE / 'root.json'
    binding = dict(schema=1, root=root)
    if os.path.lexists(anchor):
        require(decode(read(anchor, 0)) == binding, 'UNPAIRED_BIND_STATE')
    operation = expected['operationId']
    intent_path = STATE / (operation + '.intent')
    receipt = STATE / (operation + '.result')
    if os.path.lexists(intent_path):
        intent = decode(read(intent_path, 0))
        require(os.path.lexists(anchor) and intent['root'] == root, 'UNPAIRED_BIND_STATE')
        require(intent['request'] == expected, 'BIND_OPERATION_ID_CONFLICT')
        return resolve_result(receipt, intent) if os.path.lexists(receipt) else 'UNKNOWN'

    intents = list(STATE.glob('*.intent'))
    require(len(intents) < MAX_OPERATIONS, 'BIND_HISTORY_FULL')
    for previous in intents:
        intent = decode(read(previous, 0))
        require(os.path.lexists(anchor) and intent['root'] == root, 'UNPAIRED_BIND_STATE')
        terminal = previous.with_suffix('.result')
        if not os.path.lexists(terminal):
            return 'UNKNOWN'
        resolve_result(terminal, intent)
    target_before = target()
    require(authorize() and target() == target_before, 'BIND_TARGET_CHANGED')
    fingerprint, state, invocation = target_before
    action = expected['action']
    desired = 'inactive' if action == 'stop' else 'active'
    if not os.path.lexists(anchor):
        create(anchor, binding)
    intent = dict(root=root, request=expected, target=fingerprint, state=state, invocation=invocation)
    create(intent_path, intent)
    require(authorize() and target() == target_before, 'BIND_TARGET_CHANGED')
    if action == 'restart' or state != desired:
        write_job(action)
    current, after, next_invocation = target()
    require(current == fingerprint and after == desired
            and (action != 'restart' or next_invocation != invocation), 'BIND_OUTCOME_UNKNOWN')
    create(receipt, dict(intentSha256=digest(intent), state='APPLIED'))
    return 'APPLIED'


def operate(expected, authorize):
    if expected['action'] == 'status':
        require(authorize(), 'UNAUTHORIZED')
        return 'APPLIED' if target()[1] == 'active' else 'INACTIVE'
    directory(STATE, 0)
    require(STATE.lstat().st_gid == 0, 'UNPAIRED_BIND_STATE')
    fd = os.open(STATE / 'lock', os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_RDWR, 0o600)
    try:
        value = os.fstat(fd)
        require(stat.S_ISREG(value.st_mode) and value.st_uid == value.st_gid == 0
                and stat.S_IMODE(value.st_mode) == 0o600 and value.st_nlink == 1, 'UNPAIRED_BIND_STATE')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return locked_operation(expected, authorize)
    finally:
        os.close(fd)


def serve(stream, unit):
    main_sha = verify_actor(unit)
    with socket_peer(stream) as peer:
        def peer_request():
            require(active_provider() == 'kura-networking', 'UNPAIRED_BIND_PROVIDER')
            return main_peer(peer, main_sha, CLIENT, 2, request, networking=True)
        expected = peer_request()
        actual = receive(stream)
        require(type(actual.get('schema')) is int and actual == expected, 'INVALID_BIND_REQUEST')
        try:
            result = operate(expected, lambda: peer_request() == expected)
        except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            intent = STATE / (expected['operationId'] + '.intent')
            result = 'UNKNOWN' if os.path.lexists(intent) else 'REFUSED'
            print(error.reason if isinstance(error, Refused) else 'BIND_JOB_FAILED', file=sys.stderr)
        send(stream, dict(schema=1, operationId=expected['operationId'], state=result))


def client(expected):
    value = SOCKET.lstat()
    require(stat.S_ISSOCK(value.st_mode) and value.st_uid == 0 and value.st_gid == pwd.getpwnam('kurad').pw_gid
            and stat.S_IMODE(value.st_mode) == 0o660, 'UNPAIRED_BIND_RELEASE')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(4)
        stream.connect(str(SOCKET))
        credentials = stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        require(struct.unpack('3i', credentials) == (1, 0, 0), 'UNPAIRED_BIND_RELEASE')
        send(stream, expected)
        reply = receive(stream, timeout=38)
        require(type(reply.get('schema')) is int
                and reply == dict(schema=1, operationId=expected['operationId'], state=reply.get('state'))
                and reply['state'] in RESULTS, 'INVALID_BIND_RESPONSE')
        return RESULTS.index(reply['state'])


if __name__ == '__main__':
    try:
        args = sys.argv[1:]
        if args == ['provision']:
            provision()
        elif len(args) == 2 and args[0] == 'serve':
            with socket.socket(fileno=os.dup(0)) as worker:
                serve(worker, args[1])
        elif len(args) == 3 and args[0] == 'client':
            sys.exit(client(request(*args[1:])))
        else:
            raise Refused('INVALID_BIND_REQUEST')
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(error.reason if isinstance(error, Refused) else 'BIND_OUTCOME_UNKNOWN', file=sys.stderr)
        sys.exit(2)
