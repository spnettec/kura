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
import kura_bind_config as configuration
import kura_bind_outcomes as outcomes
from kura_clock_broker import HOME, VENDOR_UNIT_ROOTS, public_file, unit_directory_present
from kura_clock_journal import MAX_OPERATIONS, Refused, create, decode, digest, directory, encode, identifier, require
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
SOURCES = (HELPER, 'bin/kura_bind_config.py', 'bin/kura_bind_outcomes.py', 'bin/kura_clock_broker.py',
           'bin/kura_clock_journal.py', 'bin/kura_journal_export.py',
           'bin/kura_modem_cohort.py', 'bin/kura_reboot_broker.py', 'bin/kura_reboot_journal.py',
           'bin/kura_reboot_protocol.py', f'install/{SOCKET_UNIT}', f'install/{ACTOR_UNIT}')
LAN_CAPABILITY = 'lan-listener-v1'
FILES = {Path(name).name for name in SOURCES} | {LAN_CAPABILITY}
WRITES = ('start', 'stop', 'restart', 'configure')
ACTIONS = ('status', 'scope')
RESULTS = ('APPLIED', 'REFUSED', 'UNKNOWN', 'INACTIVE', 'NOT_FOUND')


def package_cohort(home):
    target = home / 'libexec/bind-service'
    target.mkdir()
    files = {}
    for name in SOURCES:
        source = home / name
        require(source.is_file() and not source.is_symlink(), 'UNPAIRED_BIND_RELEASE')
        shutil.copyfile(source, target / source.name)
        files[source.name] = file_hash(source.read_bytes())
    capability = b'1\n'
    (target / LAN_CAPABILITY).write_bytes(capability)
    files[LAN_CAPABILITY] = file_hash(capability)
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
    identifier(operation)
    fields = dict(schema=1, operationId=operation)
    if action.startswith('scoped:'):
        _, scope, action = action.split(':', 2)
        require(outcomes.PROOF.fullmatch(scope), 'INVALID_BIND_REQUEST')
        fields['rootScope'] = scope
        if action.startswith('configure:'):
            return dict(**fields, action='configure', configuration=configuration.decode_fields(action))
        require(action in WRITES and action != 'configure', 'INVALID_BIND_REQUEST')
        return dict(**fields, action=action)
    delivery = outcomes.request_fields(action)
    if delivery is not None:
        return dict(**fields, **delivery)
    require(action in ACTIONS, 'INVALID_BIND_REQUEST')
    return dict(**fields, action=action)


def checked_package_asset(path, manifest, *, maximum=1024 * 1024, package='bind9'):
    canonical = path.resolve(strict=True)
    require(canonical == path or (path.parent == Path('/lib/systemd/system')
                                  and canonical == Path('/usr/lib/systemd/system') / path.name),
            'UNPAIRED_BIND_UNIT')
    # Use the installed Debian record to check package ownership and the
    # original package checksum, then bind the observed content with SHA-256.
    owner = subprocess.check_output(['/usr/bin/dpkg-query', '-S', str(canonical)],
                                    env=ENVIRONMENT, timeout=3).rstrip()
    require(owner == os.fsencode(package + ': ' + str(canonical)), 'UNPAIRED_BIND_UNIT')
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


def validate_checker():
    manifest = public_file(Path('/var/lib/dpkg/info/bind9-utils.md5sums'))
    checked_package_asset(configuration.CHECKER, manifest, maximum=8 * 1024 * 1024, package='bind9-utils')


def apply_configuration(phase, payload, identity, staged, prepared, before):
    configuration.publish(identity, payload, staged, prepared)
    fingerprint, state, invocation = before
    enabling = phase in configuration.ENABLE_MODES
    if enabling:
        action = 'restart' if state == 'active' else 'start'
        write_job(action)
        wanted = 'active'
    elif phase == 'disable':
        if state != 'inactive':
            write_job('stop')
        wanted = 'inactive'
    else:
        wanted = state
    current, after, observed = target()
    require(current == fingerprint and after == wanted and (not enabling or observed != invocation)
            and configuration.read_current()[1] == payload, 'BIND_OUTCOME_UNKNOWN')


def boot_identity():
    return identifier(Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip())


def admit_intent(intent_path, intent, before, authorize):
    require(authorize() and target() == before, 'BIND_TARGET_CHANGED')
    anchor = STATE / 'root.json'
    if not os.path.lexists(anchor):
        create(anchor, dict(schema=1, root=intent['root']))
    create(intent_path, intent)
    require(authorize() and target() == before, 'BIND_TARGET_CHANGED')


def configure_operation(expected, intent_path, receipt, intent, history, target_before, authorize):
    typed = expected['configuration']
    identity, payload, publication = configuration.prepare(typed, history, ENVIRONMENT)
    with configuration.stage(identity, payload, validate_checker, ENVIRONMENT) as (staged, prepared):
        require(configuration.prepare(typed, history, ENVIRONMENT) == (identity, payload, publication),
                'BIND_CONFIGURATION_CHANGED')
        intent['publication'] = publication
        intent['stagedPublication'] = dict(boot=boot_identity(), file=prepared)
        admit_intent(intent_path, intent, target_before, authorize)
        apply_configuration(typed['mode'], payload, identity, staged, prepared, target_before)
        return ('APPLIED', outcomes.commit(receipt, intent))


def settle_publication(expected, root, authorize):
    scope = outcomes.binding(STATE, root, required=True)
    require(scope == expected['proof'] and authorize(), 'UNPAIRED_BIND_QUERY')
    operation = expected['operationId']
    original = outcomes.intent_at(STATE, root, operation)
    if original is None:
        return ('NOT_FOUND', None)
    receipt = outcomes.result_at(STATE, operation, original)
    if receipt is not None:
        return ('APPLIED', receipt.get('deliveryToken'))
    # A service start/stop/restart cannot be inferred from a changed process
    # alone. Only a file-only publication with its recorded inode is eligible.
    proof = original.get('stagedPublication')
    request = original['request']
    if (not proof or request['action'] != 'configure' or request['configuration']['mode'] != 'keep'
            or proof['boot'] != boot_identity()):
        return ('UNKNOWN', None)

    before = (original['target'], original['state'], original['invocation'])
    desired = original['publication']['published']
    if target() != before or not configuration.published(proof['file'], desired):
        return ('UNKNOWN', None)
    configuration.sync_publication()
    require(authorize() and target() == before and configuration.published(proof['file'], desired),
            'BIND_PUBLICATION_UNVERIFIED')
    record = STATE / (operation + '.result')
    return ('APPLIED', outcomes.commit(record, original, recovered=True))


def locked_operation(expected, authorize):
    root = state_binding()
    if expected['action'] == 'settle-publication':
        return settle_publication(expected, root, authorize)
    if expected['action'] == 'acknowledge':
        require(authorize(), 'UNAUTHORIZED')
        return outcomes.acknowledge(STATE, root, expected)
    require(outcomes.binding(STATE, root) == expected.get('rootScope'), 'UNPAIRED_BIND_REQUEST')
    operation = expected['operationId']
    intent_path = STATE / (operation + '.intent')
    receipt = STATE / (operation + '.result')
    if os.path.lexists(intent_path):
        outcomes.binding(STATE, root, required=True)
        intent = outcomes.intent_at(STATE, root, operation)
        require(intent['request'] == expected, 'BIND_OPERATION_ID_CONFLICT')
        # An observed outcome has a distinct read-only request. A repeated
        # mutation never acts as a query and never dispatches another job.
        return ('UNKNOWN', None)

    intents = list(STATE.glob('*.intent'))
    require(len(intents) < MAX_OPERATIONS, 'BIND_HISTORY_FULL')
    history = []
    if intents:
        outcomes.binding(STATE, root, required=True)
    for previous in intents:
        original_id = identifier(previous.stem)
        intent = outcomes.intent_at(STATE, root, original_id)
        require(intent is not None, 'UNPAIRED_BIND_STATE')
        result = outcomes.result_at(STATE, original_id, intent)
        if result is None or not outcomes.delivered_at(STATE, original_id, intent, result):
            return ('UNKNOWN', None)
        history.append(intent)
    target_before = target()
    fingerprint, state, invocation = target_before
    action = expected['action']
    intent = dict(root=root, request=expected, target=fingerprint, state=state, invocation=invocation,
                  deliveryProtocol=outcomes.PROTOCOL)
    if action == 'configure':
        return configure_operation(expected, intent_path, receipt, intent, history, target_before, authorize)
    admit_intent(intent_path, intent, target_before, authorize)
    desired = 'inactive' if action == 'stop' else 'active'
    if action == 'restart' or state != desired:
        write_job(action)
    current, after, next_invocation = target()
    require(current == fingerprint and after == desired
            and (action != 'restart' or next_invocation != invocation), 'BIND_OUTCOME_UNKNOWN')
    return ('APPLIED', outcomes.commit(receipt, intent))


def operate(expected, authorize):
    action = expected['action']
    if action == 'status':
        require(authorize(), 'UNAUTHORIZED')
        return ('APPLIED' if target()[1] == 'active' else 'INACTIVE', None)
    directory(STATE, 0)
    require(STATE.lstat().st_gid == 0, 'UNPAIRED_BIND_STATE')
    if action in outcomes.READ_ONLY:
        require(authorize(), 'UNAUTHORIZED')
        return outcomes.query(STATE, state_binding(), expected)
    if action == 'acknowledge':
        require(outcomes.binding(STATE, state_binding(), required=True) == expected['rootScope'],
                'UNPAIRED_BIND_DELIVERY')
    if action == 'settle-publication':
        require(outcomes.binding(STATE, state_binding(), required=True) == expected['proof'],
                'UNPAIRED_BIND_QUERY')
    fd = os.open(STATE / 'lock', os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_RDWR, 0o600)
    try:
        value = os.fstat(fd)
        require(stat.S_ISREG(value.st_mode) and value.st_uid == value.st_gid == 0
                and stat.S_IMODE(value.st_mode) == 0o600 and value.st_nlink == 1, 'UNPAIRED_BIND_STATE')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return locked_operation(expected, authorize)
    finally:
        os.close(fd)


def admitted_operation(expected):
    try:
        root = state_binding()
        scope = outcomes.binding(STATE, root, required=True)
        if scope != expected.get('rootScope'):
            return False
        return outcomes.intent_at(STATE, root, expected['operationId']) is not None
    except (Refused, OSError, TypeError, KeyError, ValueError):
        return False


def serve(stream, unit):
    main_sha = verify_actor(unit)
    with socket_peer(stream) as peer:
        def peer_request():
            require(active_provider() == 'kura-networking', 'UNPAIRED_BIND_PROVIDER')
            return main_peer(peer, main_sha, CLIENT, 2, request, networking=True)
        expected = peer_request()
        actual = receive(stream)
        require(type(actual.get('schema')) is int and actual == expected, 'INVALID_BIND_REQUEST')
        proof = None
        try:
            result, proof = operate(expected, lambda: peer_request() == expected)
        except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            result = 'UNKNOWN' if expected['action'] in WRITES and admitted_operation(expected) else 'REFUSED'
            print(error.reason if isinstance(error, Refused) else 'BIND_JOB_FAILED', file=sys.stderr)
        reply = dict(schema=1, operationId=expected['operationId'], state=result)
        if proof is not None:
            reply['proof'] = proof
        send(stream, reply)


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
        reply = receive(stream, timeout=55 if expected['action'] == 'configure' else 38)
        wire = dict(schema=1, operationId=expected['operationId'], state=reply.get('state'))
        proof = reply.get('proof')
        action = expected['action']
        if proof is not None:
            require(isinstance(proof, str) and outcomes.PROOF.fullmatch(proof) and reply.get('state') == 'APPLIED'
                    and action in (*WRITES, *outcomes.READ_ONLY, 'settle-publication'), 'INVALID_BIND_RESPONSE')
            wire['proof'] = proof
        require(type(reply.get('schema')) is int and reply == wire and reply['state'] in RESULTS
                and (reply['state'] != 'APPLIED' or action not in (*WRITES, 'scope') or proof is not None),
                'INVALID_BIND_RESPONSE')
        if proof is not None:
            print(proof)
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
