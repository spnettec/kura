# SPDX-License-Identifier: EPL-2.0
"""Delegate the scheduled NetworkManager modem reset through a paired local actor."""
from contextlib import closing
import fcntl
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
import kura_bind_outcomes as outcomes
from kura_bind_service import checked_package_asset
from kura_clock_broker import HOME, VENDOR_UNIT_ROOTS, public_file, unit_directory_present
from kura_clock_journal import MAX_OPERATIONS, Refused, create, decode, directory, encode, identifier, require
from kura_journal_export import main_peer, paired_unit, unit_properties
from kura_modem_cohort import active_provider, check_modem_reset_provider
from kura_reboot_broker import ENVIRONMENT, UNIT_PROPERTIES, file_hash, proc_file, proc_status, receive, send, socket_peer

ACTOR_HOME = Path('/usr/libexec/kura-modem-reset')
STATE = Path('/var/lib/kura-modem-reset')
SOCKET = Path('/run/kura-modem-reset.sock')
SOCKET_UNIT = 'kura-modem-reset.socket'
ACTOR_UNIT = 'kura-modem-reset@.service'
HELPER = 'bin/kura_modem_reset.py'
CLIENT = ('/usr/bin/python3', '-I', '-B', str(HOME / HELPER), 'client')
SOURCES = (HELPER, 'bin/kura_bind_service.py', 'bin/kura_bind_config.py', 'bin/kura_bind_outcomes.py',
           'bin/kura_clock_broker.py', 'bin/kura_clock_journal.py', 'bin/kura_journal_export.py',
           'bin/kura_modem_cohort.py', 'bin/kura_reboot_broker.py', 'bin/kura_reboot_journal.py',
           'bin/kura_reboot_protocol.py', f'install/{SOCKET_UNIT}', f'install/{ACTOR_UNIT}')
NM = 'org.freedesktop.NetworkManager'
MM = 'org.freedesktop.ModemManager1'
BUS = 'org.freedesktop.DBus'
BUS_PATH = '/org/freedesktop/DBus'
NM_PATH = re.compile(r'/org/freedesktop/NetworkManager/Devices/[0-9]{1,10}')
MM_PATH = re.compile(r'/org/freedesktop/ModemManager1/Modem/[0-9]{1,10}')
RESULTS = ('APPLIED', 'REFUSED', 'UNKNOWN', 'NOT_FOUND')


def package_cohort(home):
    target = home / 'libexec/modem-reset'
    target.mkdir()
    files = {}
    for name in SOURCES:
        source = home / name
        require(source.is_file() and not source.is_symlink(), 'UNPAIRED_MODEM_RESET_RELEASE')
        shutil.copyfile(source, target / source.name)
        files[source.name] = file_hash(source.read_bytes())
    main = (home / 'install/kura.service').read_bytes()
    (target / 'cohort.json').write_bytes(encode(dict(schema=1, mainUnitSha256=file_hash(main), files=files)) + b'\n')


def verify_actor(unit):
    require(re.fullmatch(r'kura-modem-reset@[A-Za-z0-9_.:\-]{1,128}\.service', unit),
            'UNPAIRED_MODEM_RESET_RELEASE')
    status = proc_status(os.getpid())
    require(os.getuid() == os.geteuid() == os.getgid() == os.getegid() == 0
            and status['NoNewPrivs'].strip() == '1'
            and all(int(status[name], 16) == 0 for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')),
            'UNPAIRED_MODEM_RESET_RELEASE')
    cohort = decode(public_file(ACTOR_HOME / 'cohort.json'))
    require(set(cohort) == {'schema', 'files', 'mainUnitSha256'} and type(cohort['schema']) is int
            and cohort['schema'] == 1 and set(cohort['files']) == {Path(name).name for name in SOURCES},
            'UNPAIRED_MODEM_RESET_RELEASE')
    for name, expected in cohort['files'].items():
        require(file_hash(public_file(ACTOR_HOME / name)) == expected, 'UNPAIRED_MODEM_RESET_RELEASE')
    paired_unit(SOCKET_UNIT, SOCKET_UNIT, cohort['files'][SOCKET_UNIT])
    paired_unit(unit, ACTOR_UNIT, cohort['files'][ACTOR_UNIT])
    return cohort['mainUnitSha256']


def request(action, operation):
    identifier(operation)
    fields = dict(schema=1, operationId=operation)
    if action in ('scope', 'ready'):
        return dict(**fields, action=action)
    if action.startswith(('outcome:', 'acknowledge:')):
        return dict(**fields, **outcomes.request_fields(action))
    verb, _, params = action.partition(':')
    scope, _, device = params.partition(':')
    require(verb == 'reset' and outcomes.PROOF.fullmatch(scope) and NM_PATH.fullmatch(device),
            'INVALID_MODEM_RESET_REQUEST')
    return dict(**fields, action='reset', rootScope=scope, device=device)


def provision():
    require(os.getuid() == os.geteuid() == 0 and unit_directory_present(STATE.parent),
            'UNPAIRED_MODEM_RESET_STATE')
    STATE.mkdir(mode=0o700, exist_ok=True)
    directory(STATE, 0)
    require(STATE.lstat().st_gid == 0, 'UNPAIRED_MODEM_RESET_STATE')


def state_binding():
    directory(STATE, 0)
    metadata = STATE.lstat()
    machine = public_file(Path('/etc/machine-id'), 64).strip()
    require(metadata.st_gid == 0 and re.fullmatch(rb'[0-9a-f]{32}', machine), 'UNPAIRED_MODEM_RESET_STATE')
    return [machine.decode('ascii'), metadata.st_dev, metadata.st_ino]


def bus_call(bus, destination, path, interface, method, signature='', args=(), timeout=3):
    return bus.call_blocking(destination, path, interface, method, signature, args, timeout=timeout)


def service(bus, name, unit, package, binary):
    fields = UNIT_PROPERTIES + ('ActiveState', 'MainPID', 'InvocationID', 'ControlGroup', 'ExecStart')
    props = unit_properties(unit, fields)
    group = '/system.slice/' + unit
    allowed_names = ({unit}, {unit, 'dbus-' + name + '.service'})
    require(props['Id'] == unit and set(props['Names'].split()) in allowed_names and props['LoadState'] == 'loaded'
            and props['ExecStart'].startswith('{ path=' + str(binary) + ' ; argv[]=' + str(binary))
            and props['ActiveState'] == 'active' and props['ControlGroup'] == group
            and props['FragmentPath'] in {str(root / unit) for root in VENDOR_UNIT_ROOTS}
            and props['SourcePath'] == props['DropInPaths'] == ''
            and props['Transient'] == props['NeedDaemonReload'] == 'no'
            and re.fullmatch('[0-9a-f]{32}', props['InvocationID']) and int(props['MainPID']) > 1,
            'UNPAIRED_MODEM_DAEMON')
    version = subprocess.check_output(['/usr/bin/dpkg-query', '-W', '-f=${db:Status-Status} ${Version}', package],
                                      env=ENVIRONMENT, timeout=3).decode('ascii')
    require(re.fullmatch(r'installed [0-9A-Za-z:.+~\-]+', version), 'UNPAIRED_MODEM_DAEMON')
    manifest = public_file(Path('/var/lib/dpkg/info') / (package + '.md5sums'))
    fragment = checked_package_asset(Path(props['FragmentPath']), manifest, package=package)
    executable = checked_package_asset(binary, manifest, maximum=16 * 1024 * 1024, package=package)
    owner = str(bus_call(bus, BUS, BUS_PATH, BUS, 'GetNameOwner', 's', (name,)))
    require(re.fullmatch(r':[0-9]{1,10}\.[0-9]{1,10}', owner), 'UNPAIRED_MODEM_DAEMON')
    pid = int(bus_call(bus, BUS, BUS_PATH, BUS, 'GetConnectionUnixProcessID', 's', (owner,)))
    uid = int(bus_call(bus, BUS, BUS_PATH, BUS, 'GetConnectionUnixUser', 's', (owner,)))
    require(pid == int(props['MainPID']) and uid == 0
            and proc_file(pid, 'cmdline').split(b'\0', 1)[0] == os.fsencode(binary)
            and proc_file(pid, 'cgroup') == f'0::{group}\n'.encode()
            and unit_properties(unit, fields) == props, 'UNPAIRED_MODEM_DAEMON')
    return owner, version, fragment, executable, props['InvocationID'], pid


def property_value(bus, owner, path, interface, prop, expected):
    value = bus_call(bus, owner, path, 'org.freedesktop.DBus.Properties', 'Get', 'ss', (interface, prop))
    require(type(value) is expected, 'INVALID_MODEM_PROPERTY')
    return value


def target(bus, requested, dbus):
    device = requested['device']
    nm = service(bus, NM, 'NetworkManager.service', 'network-manager', Path('/usr/sbin/NetworkManager'))
    require(property_value(bus, nm[0], device, NM + '.Device', 'DeviceType', dbus.UInt32) == 8,
            'NOT_A_MODEM_DEVICE')
    modem = str(property_value(bus, nm[0], device, NM + '.Device', 'Udi', dbus.String))
    require(MM_PATH.fullmatch(modem), 'UNPAIRED_MODEM_DEVICE')
    mm = service(bus, MM, 'ModemManager.service', 'modemmanager', Path('/usr/sbin/ModemManager'))
    hardware = str(property_value(bus, mm[0], modem, MM + '.Modem', 'Physdev', dbus.String))
    require(re.fullmatch(r'/sys/devices/(?:[a-zA-Z0-9_.:@-]+/)*[a-zA-Z0-9_.:@-]+', hardware)
            and Path(hardware).resolve(strict=True) == Path(hardware), 'UNPAIRED_MODEM_DEVICE')
    identity = Path(hardware).lstat()
    require(stat.S_ISDIR(identity.st_mode) and identity.st_uid == 0 and identity.st_mode & 0o022 == 0,
            'UNPAIRED_MODEM_DEVICE')
    nm_state = property_value(bus, nm[0], device, NM + '.Device', 'State', dbus.UInt32)
    mm_state = property_value(bus, mm[0], modem, MM + '.Modem', 'State', dbus.Int32)
    # NM's activated state and MM's connected state are independently authoritative.
    require(nm_state in range(10, 130, 10) and mm_state in (-1, *range(1, 12)), 'UNKNOWN_MODEM_STATE')
    require((nm_state, mm_state) != (100, 11), 'MODEM_ALREADY_CONNECTED')
    return nm, mm, modem, hardware, identity.st_dev, identity.st_ino


def legacy_owner():
    require(not any(os.path.lexists(path) for path in (
        Path('/etc/kura/network-owner-agent'), HOME / 'framework/network-owner-agent')), 'MODEM_OWNED_BY_AGENT')


def require_ready(root):
    intents = sorted(STATE.glob('*.intent'))
    require(len(intents) < MAX_OPERATIONS, 'MODEM_RESET_JOURNAL_FULL')
    for entry in intents:
        previous = entry.stem
        identifier(previous)
        intent = outcomes.intent_at(STATE, root, previous)
        result = outcomes.result_at(STATE, previous, intent)
        # Physical paths and bus object numbers can change when a reset
        # reenumerates a device. Preserve one unresolved reset per Root.
        require(result is not None and outcomes.delivered_at(STATE, previous, intent, result),
                'PENDING_MODEM_RESET_OUTCOME')

def reset(expected, root, authorize):
    # A private, fixed-system-bus connection binds unique names to this bus
    # lifetime. Losing the bus can never reconnect and dispatch to reused names.
    import dbus

    operation = expected['operationId']
    scope = outcomes.binding(STATE, root)
    require(expected['rootScope'] == scope, 'UNPAIRED_MODEM_RESET_SCOPE')
    if outcomes.intent_at(STATE, root, operation) is not None:
        return outcomes.query(STATE, root, dict(action='outcome', proof=scope, operationId=operation))
    require_ready(root)
    legacy_owner()
    with closing(dbus.bus.BusConnection('unix:path=/run/dbus/system_bus_socket')) as bus:
        observed = target(bus, expected, dbus)
        require(authorize(), 'UNAUTHORIZED')
        anchor = STATE / 'root.json'
        if not os.path.lexists(anchor):
            create(anchor, dict(schema=1, root=root))
        intent = dict(root=root, request=expected, deliveryProtocol=outcomes.PROTOCOL)
        create(STATE / (operation + '.intent'), intent)
        require(observed == target(bus, expected, dbus) and authorize(), 'MODEM_RESET_TARGET_CHANGED')
        legacy_owner()
        _, mm, modem, *_ = observed
        bus_call(bus, mm[0], modem, MM + '.Modem', 'Reset', timeout=20)
        return 'APPLIED', outcomes.commit(STATE / (operation + '.result'), intent)


def operate(expected, authorize):
    require(authorize(), 'UNAUTHORIZED')
    root = state_binding()
    if expected['action'] == 'ready':
        require_ready(root)
        return 'APPLIED', outcomes.binding(STATE, root)
    if expected['action'] in outcomes.READ_ONLY:
        return outcomes.query(STATE, root, expected)
    fd = os.open(STATE / 'lock', os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_RDWR, 0o600)
    try:
        value = os.fstat(fd)
        require(stat.S_ISREG(value.st_mode) and value.st_uid == value.st_gid == 0
                and stat.S_IMODE(value.st_mode) == 0o600 and value.st_nlink == 1, 'UNPAIRED_MODEM_RESET_STATE')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 'UNKNOWN', None
        require(state_binding() == root, 'UNPAIRED_MODEM_RESET_STATE')
        if expected['action'] == 'acknowledge':
            return outcomes.acknowledge(STATE, root, expected)
        return reset(expected, root, authorize)
    finally:
        os.close(fd)


def serve(stream, unit):
    import dbus

    paired_main = verify_actor(unit)
    with socket_peer(stream) as peer:
        def paired_request():
            identity = main_peer(peer, paired_main, CLIENT, 2, request, networking=True)
            require(active_provider() == 'kura-networking', 'UNPAIRED_MODEM_RESET_PROVIDER')
            check_modem_reset_provider(True)
            return identity

        expected = paired_request()
        actual = receive(stream)
        require(type(actual.get('schema')) is int and actual == expected, 'INVALID_MODEM_RESET_REQUEST')
        proof = None
        try:
            state, proof = operate(expected, lambda: paired_request() == expected)
        except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
                dbus.DBusException) as error:
            state = 'REFUSED'
            if expected['action'] == 'reset':
                # If checking the original intent fails, preserve UNKNOWN.
                state = 'UNKNOWN'
                try:
                    root = state_binding()
                    if (outcomes.binding(STATE, root) == expected['rootScope']
                            and outcomes.intent_at(STATE, root, expected['operationId']) is None):
                        state = 'REFUSED'
                except (Refused, OSError, ValueError, KeyError, TypeError):
                    pass
            print(error.reason if isinstance(error, Refused) else 'MODEM_RESET_JOB_FAILED', file=sys.stderr)
        reply = dict(schema=1, operationId=expected['operationId'], state=state)
        if proof is not None:
            reply['proof'] = proof
        send(stream, reply)


def client(expected):
    metadata = SOCKET.lstat()
    require(stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == 0 and metadata.st_gid == pwd.getpwnam('kurad').pw_gid
            and stat.S_IMODE(metadata.st_mode) == 0o660, 'UNPAIRED_MODEM_RESET_RELEASE')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(4)
        stream.connect(str(SOCKET))
        require(struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)) == (1, 0, 0),
                'UNPAIRED_MODEM_RESET_RELEASE')
        send(stream, expected)
        response = receive(stream, timeout=65)
    state, proof = response.get('state'), response.get('proof')
    reply = dict(schema=1, operationId=expected['operationId'], state=state)
    if state == 'APPLIED' and expected['action'] != 'acknowledge':
        require(isinstance(proof, str) and outcomes.PROOF.fullmatch(proof), 'INVALID_MODEM_RESET_RESPONSE')
        reply['proof'] = proof
        print(proof)
    require(type(response.get('schema')) is int and response == reply and state in RESULTS,
            'INVALID_MODEM_RESET_RESPONSE')
    return RESULTS.index(state)


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
            raise Refused('INVALID_MODEM_RESET_REQUEST')
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(error.reason if isinstance(error, Refused) else 'MODEM_RESET_OUTCOME_UNKNOWN', file=sys.stderr)
        sys.exit(2)
