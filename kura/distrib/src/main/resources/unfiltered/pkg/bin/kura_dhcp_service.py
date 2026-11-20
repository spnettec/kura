# SPDX-License-Identifier: EPL-2.0
"""Root-paired control of the dedicated Kura dnsmasq DHCP instance."""
import fcntl
from ipaddress import IPv4Address
import json
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
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kura_bind_outcomes as outcomes
import kura_dhcp_configuration as configuration
import kura_dhcp_listeners as listeners
import kura_bind_service as bind
from kura_clock_broker import HOME, public_file, unit_directory_present
from kura_clock_journal import MAX_OPERATIONS, Refused, create, decode, digest, directory, encode, identifier, require, sync
from kura_journal_export import main_peer, paired_unit
from kura_modem_cohort import active_provider, check_dhcp_provider, protected, snapshot, stamp
from kura_reboot_broker import ENVIRONMENT, file_hash, proc_status, receive, send, socket_peer

ACTOR = Path('/usr/libexec/kura-dhcp-service')
STATE = Path('/var/lib/kura-dhcp-service')
CONFIG = Path('/etc/kura/dhcp-service/dnsmasq.conf')
SOCKET = Path('/run/kura-dhcp-service.sock')
SOCKET_UNIT = 'kura-dhcp-service.socket'
WORKER_UNIT = 'kura-dhcp-service@.service'
DAEMON_UNIT = 'kura-dhcp.service'
DAEMON = Path('/usr/sbin/dnsmasq')
DAEMON_CGROUP = '/system.slice/' + DAEMON_UNIT
CGROUP_ROOT = Path('/sys/fs/cgroup')
HELPER = 'bin/kura_dhcp_service.py'
CLIENT = ('/usr/bin/python3', '-I', '-B', str(HOME / HELPER), 'client')
SOURCES = (HELPER, 'bin/kura_dhcp_configuration.py', 'bin/kura_dhcp_listeners.py',
           'bin/kura_bind_service.py', 'bin/kura_bind_config.py',
           'bin/kura_bind_outcomes.py', 'bin/kura_clock_broker.py', 'bin/kura_clock_journal.py',
           'bin/kura_journal_export.py', 'bin/kura_modem_cohort.py', 'bin/kura_reboot_broker.py',
           'bin/kura_reboot_journal.py', 'bin/kura_reboot_protocol.py',
           *(f'install/{unit}' for unit in (SOCKET_UNIT, WORKER_UNIT, DAEMON_UNIT)))
FILES = {Path(name).name for name in SOURCES}
REQUEST_LIMIT = 16384
RESULTS = ('APPLIED', 'REFUSED', 'UNKNOWN', 'DIFFERENT', 'NOT_FOUND')


def package_cohort(home):
    target = home / 'libexec/dhcp-service'
    target.mkdir()
    files = {}
    for name in SOURCES:
        source = home / name
        require(source.is_file() and not source.is_symlink(), 'UNPAIRED_DHCP_RELEASE')
        shutil.copyfile(source, target / source.name)
        files[source.name] = file_hash(source.read_bytes())
    main = (home / 'install/kura.service').read_bytes()
    (target / 'cohort.json').write_bytes(encode(dict(schema=1, mainUnitSha256=file_hash(main), files=files)) + b'\n')


def verify_actor(unit):
    require(re.fullmatch(r'kura-dhcp-service@[A-Za-z0-9_.:\-]{1,128}\.service', unit), 'UNPAIRED_DHCP_RELEASE')
    status = proc_status(os.getpid())
    require(os.getuid() == os.geteuid() == os.getgid() == os.getegid() == 0
            and status['NoNewPrivs'].strip() == '1'
            and all(int(status[name], 16) == 0 for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')),
            'UNPAIRED_DHCP_RELEASE')
    cohort = decode(public_file(ACTOR / 'cohort.json'))
    require(set(cohort) == {'schema', 'files', 'mainUnitSha256'} and type(cohort['schema']) is int
            and cohort['schema'] == 1 and set(cohort['files']) == FILES, 'UNPAIRED_DHCP_RELEASE')
    for name, expected in cohort['files'].items():
        require(file_hash(public_file(ACTOR / name)) == expected, 'UNPAIRED_DHCP_RELEASE')
    paired_unit(SOCKET_UNIT, SOCKET_UNIT, cohort['files'][SOCKET_UNIT])
    paired_unit(unit, WORKER_UNIT, cohort['files'][WORKER_UNIT])
    return cohort


def request(action, operation):
    identifier(operation)
    values = dict(schema=1, operationId=operation)
    if action == 'scope':
        return dict(**values, action=action)
    if action.startswith('compare:'):
        return dict(**values, action='compare', interfaces=configuration.parse(action[len('compare:'):]))
    if action.startswith('paired-outcome:'):
        original = action.removeprefix('paired-outcome:')
        require(original.startswith('apply:'), 'INVALID_DHCP_REQUEST')
        return dict(**values, action='paired-outcome', request=request(original, operation))
    if action.startswith('apply:'):
        _, scope, model = action.split(':', 2)
        require(outcomes.PROOF.fullmatch(scope), 'INVALID_DHCP_REQUEST')
        return dict(**values, action='apply', rootScope=scope, interfaces=configuration.parse(model))
    fields = outcomes.request_fields(action)
    require(fields is not None and fields['action'] in ('outcome', 'acknowledge'), 'INVALID_DHCP_REQUEST')
    return dict(**values, **fields)


def provision():
    require(os.getuid() == os.geteuid() == 0 and unit_directory_present(STATE.parent)
            and unit_directory_present(CONFIG.parent.parent), 'UNPAIRED_DHCP_STATE')
    for path, mode in ((STATE, 0o700), (CONFIG.parent, 0o755)):
        try:
            path.mkdir(mode=mode)
        except FileExistsError:
            pass
        directory(path, 0, mode)
        require(path.lstat().st_gid == 0, 'UNPAIRED_DHCP_STATE')
    # Creation is exclusive and an existing configuration is never replaced here.
    if not os.path.lexists(CONFIG):
        require(not any(STATE.glob('*.intent')) and not os.path.lexists(STATE/'root.json'), 'UNPAIRED_DHCP_STATE')
        fd = os.open(CONFIG, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY | os.O_CLOEXEC, 0o644)
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(configuration.DEFAULT)
            stream.flush()
            os.fsync(stream.fileno())
        sync(CONFIG.parent)
    current_config()


def state_binding():
    metadata = STATE.stat()
    machine = public_file(Path('/etc/machine-id'), 64).strip()
    require(re.fullmatch(rb'[0-9a-f]{32}', machine), 'UNPAIRED_DHCP_STATE')
    return [machine.decode('ascii'), metadata.st_dev, metadata.st_ino]


def current_config():
    metadata = protected(CONFIG)
    require(metadata.st_gid == 0 and stat.S_IMODE(metadata.st_mode) == 0o644
            and not os.listxattr(CONFIG, follow_symlinks=False), 'UNPAIRED_DHCP_CONFIGURATION')
    data = snapshot(CONFIG, configuration.LIMIT, lambda stream: stream.read())
    require(stamp(metadata) == stamp(CONFIG.lstat()), 'DHCP_CONFIGURATION_CHANGED')
    return stamp(metadata), data


def target(cohort):
    loaded = paired_unit(DAEMON_UNIT, DAEMON_UNIT, cohort['files'][DAEMON_UNIT],
                         ('ActiveState', 'MainPID', 'InvocationID', 'ControlGroup'))
    package = subprocess.check_output(['/usr/bin/dpkg-query', '-W', '-f=${db:Status-Status} ${Version}', 'dnsmasq-base'],
                                      env=ENVIRONMENT, timeout=3).decode('ascii')
    require(re.fullmatch(r'installed [0-9A-Za-z:.+~\-]+', package), 'UNPAIRED_DHCP_DAEMON')
    manifest = public_file(Path('/var/lib/dpkg/info/dnsmasq-base.md5sums'))
    executable = bind.checked_package_asset(DAEMON, manifest, maximum=8 * 1024 * 1024, package='dnsmasq-base')
    state = loaded.pop('ActiveState')
    invocation = loaded.pop('InvocationID')
    pid = int(loaded.pop('MainPID'))
    control_group = loaded.pop('ControlGroup')
    require(state in ('active', 'inactive', 'failed') and (pid > 1 if state == 'active' else pid == 0)
            and (re.fullmatch('[0-9a-f]{32}', invocation) if state == 'active' else True), 'DHCP_SERVICE_BUSY')
    cgroup = None
    if state == 'active':
        require(control_group == DAEMON_CGROUP and (CGROUP_ROOT / 'cgroup.controllers').is_file()
                and Path(f'/proc/{pid}/cgroup').read_bytes() == ('0::' + DAEMON_CGROUP + '\n').encode(),
                'UNPAIRED_DHCP_DAEMON')
        metadata = (CGROUP_ROOT / DAEMON_CGROUP.lstrip('/')).lstat()
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0 and metadata.st_ino > 0,
                'UNPAIRED_DHCP_DAEMON')
        cgroup = metadata.st_ino
    return digest(dict(loaded=loaded, package=package, executable=executable)), state, invocation, cgroup


def observe_interfaces(interfaces):
    if not interfaces:
        return ()
    raw = subprocess.check_output(['/usr/sbin/ip', '-j', '-4', 'address', 'show'],
                                  env=ENVIRONMENT, timeout=3)
    require(len(raw) <= 256 * 1024, 'DHCP_INTERFACE_UNAVAILABLE')
    links = {link['ifname']: link for link in json.loads(raw)}
    result = []
    for entry in interfaces:
        link = links.get(entry['interface'])
        require(link is not None and 'UP' in link['flags'] and link['ifindex'] > 0
                and any(ip.get('local') == entry['address'] and ip.get('prefixlen') == entry['prefix']
                        for ip in link['addr_info']), 'DHCP_INTERFACE_UNAVAILABLE')
        addresses = frozenset(IPv4Address(address[key]) for address in link['addr_info']
                              for key in ('local', 'broadcast') if key in address)
        master = links[link['master']]['ifindex'] if 'master' in link else None
        result.append(listeners.Link(link['ifindex'], addresses, master))
    return tuple(result)


def check_active_target(cohort, unit, interfaces, published):
    if not interfaces:
        return
    listeners.check(interfaces, unit[3], ready=True)
    require(target(cohort) == unit and current_config() == published, 'DHCP_TARGET_CHANGED')


def checked_history(root):
    entries = list(STATE.glob('*.intent'))
    require(len(entries) < MAX_OPERATIONS, 'DHCP_HISTORY_FULL')
    if entries:
        outcomes.binding(STATE, root, required=True)
    prior = []
    for path in entries:
        operation = identifier(path.stem)
        intent = outcomes.intent_at(STATE, root, operation)
        receipt = outcomes.result_at(STATE, operation, intent)
        if receipt is None or not outcomes.delivered_at(STATE, operation, intent, receipt):
            raise Refused('DHCP_PENDING_OUTCOME')
        prior.append(intent['publication'])
    records = sorted(prior, key=lambda entry: entry['revision'])
    current = file_hash(configuration.DEFAULT)
    for revision, record in enumerate(records, 1):
        require(record['revision'] == revision and record['oldSha256'] == current, 'UNPAIRED_DHCP_HISTORY')
        current = record['newSha256']
    return len(records), current


def apply(expected, root, cohort, authorize):
    scope = outcomes.binding(STATE, root)
    require(scope == expected['rootScope'], 'UNPAIRED_DHCP_STATE')
    operation = expected['operationId']
    prepared = STATE / (operation + '.intent')
    if os.path.lexists(prepared):
        return ('UNKNOWN', None)
    try:
        versions, expected_sha = checked_history(root)
    except Refused as error:
        if error.reason == 'DHCP_PENDING_OUTCOME':
            return ('UNKNOWN', None)
        raise
    before = current_config()
    require(file_hash(before[1]) == expected_sha, 'UNOWNED_DHCP_CONFIGURATION')
    records = expected['interfaces']
    model = configuration.render(records)
    interfaces = observe_interfaces(records)
    unit = target(cohort)
    desired = 'active' if records else 'inactive'
    listeners.check(interfaces, unit[3])
    with tempfile.NamedTemporaryFile(dir=CONFIG.parent, prefix='.dnsmasq-', delete=False) as stream:
        staged = Path(stream.name)
        try:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(model)
            stream.flush()
            os.fsync(stream.fileno())
            subprocess.run([str(DAEMON), '--test', '--conf-file=' + str(staged)], env=ENVIRONMENT,
                           check=True, timeout=5, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            require(authorize() and current_config() == before and target(cohort) == unit, 'DHCP_TARGET_CHANGED')
            require(observe_interfaces(records) == interfaces, 'DHCP_INTERFACE_CHANGED')
            listeners.check(interfaces, unit[3])
            if not os.path.lexists(STATE / 'root.json'):
                create(STATE / 'root.json', dict(schema=1, root=root))
            intent = dict(root=root, request=expected, target=unit[0], deliveryProtocol=outcomes.PROTOCOL,
                          publication=dict(revision=versions + 1, oldSha256=expected_sha, newSha256=file_hash(model)))
            create(prepared, intent)
            require(authorize() and current_config() == before and target(cohort) == unit, 'DHCP_TARGET_CHANGED')
            require(observe_interfaces(records) == interfaces, 'DHCP_INTERFACE_CHANGED')
            listeners.check(interfaces, unit[3])
            if model != before[1]:
                os.replace(staged, CONFIG)
                sync(CONFIG.parent)
            published = current_config()
            require(published[1] == model, 'DHCP_CONFIGURATION_CHANGED')
            verb = 'restart' if records and unit[1] == 'active' else 'start' if records else 'stop'
            if unit[1] != desired or (records and model != before[1]):
                subprocess.run([*bind.SYSTEMCTL, '--job-mode=fail', verb, DAEMON_UNIT], env=ENVIRONMENT,
                               timeout=28, check=True, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            current = target(cohort)
            require(current[0] == unit[0] and current[1] == desired and current_config() == published
                    and observe_interfaces(records) == interfaces
                    and (verb != 'restart' or model == before[1] or current[2] != unit[2]), 'DHCP_OUTCOME_UNKNOWN')
            check_active_target(cohort, current, interfaces, published)
            return ('APPLIED', outcomes.commit(STATE / (operation + '.result'), intent))
        finally:
            staged.unlink(missing_ok=True)


def operate(expected, cohort, authorize):
    require(authorize(), 'UNAUTHORIZED')
    directory(STATE, 0)
    require(STATE.lstat().st_gid == 0, 'UNPAIRED_DHCP_STATE')
    root = state_binding()
    action = expected['action']
    if action == 'paired-outcome':
        return outcomes.paired_query(STATE, root, expected)
    if action in outcomes.READ_ONLY:
        return outcomes.query(STATE, root, expected)
    if action == 'compare':
        records = expected['interfaces']
        current = current_config()
        try:
            _, expected_sha = checked_history(root)
        except Refused as error:
            if error.reason == 'DHCP_PENDING_OUTCOME':
                return ('UNKNOWN', None)
            raise
        require(file_hash(current[1]) == expected_sha and current_config() == current, 'UNOWNED_DHCP_CONFIGURATION')
        matched = current[1] == configuration.render(records)
        if matched:
            interfaces = observe_interfaces(records)
            unit = target(cohort)
            if unit[1] == ('active' if records else 'inactive'):
                check_active_target(cohort, unit, interfaces, current)
                return ('APPLIED', None)
        return ('DIFFERENT', None)
    fd = os.open(STATE / 'lock', os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_RDWR, 0o600)
    try:
        value = os.fstat(fd)
        require(stat.S_ISREG(value.st_mode) and value.st_uid == value.st_gid == 0
                and stat.S_IMODE(value.st_mode) == 0o600 and value.st_nlink == 1, 'UNPAIRED_DHCP_STATE')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if action == 'acknowledge':
            return outcomes.acknowledge(STATE, root, expected)
        return apply(expected, root, cohort, authorize)
    finally:
        os.close(fd)


def serve(stream, unit):
    cohort = verify_actor(unit)
    with socket_peer(stream) as peer:
        def paired_request():
            identity = main_peer(peer, cohort['mainUnitSha256'], CLIENT, 2, request, networking=True)
            require(active_provider() == 'kura-networking', 'UNPAIRED_DHCP_PROVIDER')
            check_dhcp_provider(True)
            return identity
        expected = paired_request()
        actual = receive(stream, maximum=outcomes.request_limit(expected, REQUEST_LIMIT))
        require(type(actual.get('schema')) is int and actual == expected, 'INVALID_DHCP_REQUEST')
        proof = None
        try:
            result, proof = operate(expected, cohort, lambda: paired_request() == expected)
        except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            result = 'REFUSED'
            if expected['action'] == 'apply':
                result = outcomes.failed_write_state(STATE, expected, state_binding)
            print(error.reason if isinstance(error, Refused) else 'DHCP_JOB_FAILED', file=sys.stderr)
        reply = dict(schema=1, operationId=expected['operationId'], state=result)
        if proof is not None:
            reply['proof'] = proof
        send(stream, reply)


def client(expected):
    metadata = SOCKET.lstat()
    require(stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == 0 and metadata.st_gid == pwd.getpwnam('kurad').pw_gid
            and stat.S_IMODE(metadata.st_mode) == 0o660, 'UNPAIRED_DHCP_RELEASE')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(4)
        stream.connect(str(SOCKET))
        peer = stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        require(struct.unpack('3i', peer) == (1, 0, 0), 'UNPAIRED_DHCP_RELEASE')
        send(stream, expected, maximum=outcomes.request_limit(expected, REQUEST_LIMIT))
        response = receive(stream, timeout=50)
        proof = response.get('proof')
        reply = dict(schema=1, operationId=expected['operationId'], state=response.get('state'))
        action = expected['action']
        if proof is not None:
            require(isinstance(proof, str) and outcomes.PROOF.fullmatch(proof) and response['state'] == 'APPLIED'
                    and action in ('scope', 'apply', 'outcome', 'paired-outcome'), 'INVALID_DHCP_RESPONSE')
            reply['proof'] = proof
        require(type(response.get('schema')) is int and response == reply and response['state'] in RESULTS
                and (response['state'] != 'APPLIED' or action not in ('scope', 'apply', 'paired-outcome') or proof is not None),
                'INVALID_DHCP_RESPONSE')
        if proof is not None:
            print(proof)
        return RESULTS.index(response['state'])


if __name__ == '__main__':
    try:
        argv = sys.argv[1:]
        if argv == ['provision']:
            provision()
        elif len(argv) == 2 and argv[0] == 'serve':
            with socket.socket(fileno=os.dup(0)) as stream:
                serve(stream, argv[1])
        elif len(argv) == 3 and argv[0] == 'client':
            sys.exit(client(request(*argv[1:])))
        else:
            raise Refused('INVALID_DHCP_REQUEST')
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(error.reason if isinstance(error, Refused) else 'DHCP_OUTCOME_UNKNOWN', file=sys.stderr)
        sys.exit(2)
