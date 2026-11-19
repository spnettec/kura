# SPDX-License-Identifier: EPL-2.0
"""Local typed kernel module and USB serial registration operations."""
import errno
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
from kura_clock_broker import HOME, protected, public_file
from kura_clock_journal import Refused, create, decode, directory, encode, identifier, read, require
from kura_journal_export import main_peer, paired_unit
from kura_reboot_broker import ENVIRONMENT, file_hash, proc_status, receive, send, socket_peer

ACTOR_HOME = Path('/usr/libexec/kura-modem-driver')
SOCKET = Path('/run/kura-modem-driver.sock')
SOCKET_UNIT = 'kura-modem-driver.socket'
ACTOR_UNIT = 'kura-modem-driver@.service'
STATE = Path('/var/lib/kura-modem-driver')
USB = Path('/sys/bus/usb/devices')
MODULES = Path('/sys/module')
NEW_ID = Path('/sys/bus/usb-serial/drivers/option1/new_id')
KMOD = Path('/usr/bin/kmod')
HELPER = 'bin/kura_modem_driver.py'
PAIR = Path('libexec/modem-driver')
CAP_MODULE = 1 << 16
CLIENT = ('/usr/bin/python3', '-I', '-B', str(HOME / HELPER), 'client')
SOURCES = (HELPER, 'bin/kura_journal_export.py', 'bin/kura_clock_broker.py', 'bin/kura_clock_journal.py',
           'bin/kura_reboot_broker.py', 'bin/kura_reboot_journal.py', 'bin/kura_reboot_protocol.py',
           f'install/{SOCKET_UNIT}', f'install/{ACTOR_UNIT}')
FILES = {Path(value).name for value in SOURCES}
DYNAMIC_OPTION_IDS = {'1bc7:1010', '1bc7:1011', '1bc7:1201', '19d2:1476', '1e0e:9001'}
DRIVERS = {
    'cdc_acm': {'1bc7:0021', '1bc7:0022', '1bc7:0036', '1546:1102', '1546:110a', '2c7c:0125', '2c7c:0296'},
    'sierra': {'1199:6812', '1199:683c', '1199:0025'},
    'option': DYNAMIC_OPTION_IDS | {'12d1:1506', '1bbb:00b6'},
}


def package_cohort(home):
    target = home / PAIR
    target.mkdir()
    files = {}
    for name in SOURCES:
        source = home / name
        require(source.is_file() and not source.is_symlink(), 'UNPAIRED_MODEM_RELEASE')
        shutil.copyfile(source, target / source.name)
        files[source.name] = file_hash(source.read_bytes())
    main = (home / 'install/kura.service').read_bytes()
    (target / 'cohort.json').write_bytes(encode(dict(schema=1, mainUnitSha256=file_hash(main), files=files)) + b'\n')


def request(action, module, usb_id, operation):
    require(action in ('load', 'unload') and module in DRIVERS and usb_id in DRIVERS[module], 'INVALID_MODEM_REQUEST')
    identifier(operation)
    return dict(schema=1, action=action, module=module, usbId=usb_id, operationId=operation)


def verify_actor(unit):
    require(re.fullmatch(r'kura-modem-driver@[A-Za-z0-9_.:\\-]{1,128}\.service', unit), 'UNPAIRED_MODEM_RELEASE')
    status = proc_status(os.getpid())
    effective = int(status['CapEff'], 16)
    require(os.getuid() == os.geteuid() == 0 and os.getgid() == os.getegid() == 0
            and status['NoNewPrivs'].strip() == '1'
            and all(int(status[name], 16) & ~CAP_MODULE == 0 for name in ('CapPrm','CapEff','CapBnd'))
            and all(int(status[name], 16) == 0 for name in ('CapInh','CapAmb')), 'UNPAIRED_MODEM_RELEASE')
    cohort = decode(public_file(ACTOR_HOME / 'cohort.json'))
    require(set(cohort) == {'schema', 'files', 'mainUnitSha256'} and type(cohort['schema']) is int
            and cohort['schema'] == 1 and set(cohort['files']) == FILES, 'UNPAIRED_MODEM_RELEASE')
    for filename, expected in cohort['files'].items():
        require(file_hash(public_file(ACTOR_HOME / filename)) == expected, 'UNPAIRED_MODEM_RELEASE')
    paired_unit(SOCKET_UNIT, SOCKET_UNIT, cohort['files'][SOCKET_UNIT])
    paired_unit(unit, ACTOR_UNIT, cohort['files'][ACTOR_UNIT])
    return cohort['mainUnitSha256'], effective == CAP_MODULE


def current_usb(usb_id):
    vendor, product = usb_id.split(':')
    if not USB.is_dir():
        return False
    for candidate in USB.iterdir():
        try:
            device = candidate.resolve(strict=True)
            require(device.is_relative_to('/sys/devices'), 'INVALID_USB_DEVICE')
            fd = os.open(device, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                if usb_attribute(fd, 'idVendor') == vendor and usb_attribute(fd, 'idProduct') == product:
                    return True
            finally:
                os.close(fd)
        except FileNotFoundError:
            # Bus interfaces have no device IDs; hotplug can also remove a path.
            continue
    return False


def usb_attribute(device, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=device)
    try:
        value = os.fstat(fd)
        require(stat.S_ISREG(value.st_mode) and value.st_uid == 0 and value.st_mode & 0o022 == 0,
                'INVALID_USB_DEVICE')
        identifier_bytes = os.read(fd, 8)
        require(re.fullmatch(rb'[0-9a-f]{4}\n', identifier_bytes), 'INVALID_USB_DEVICE')
        return identifier_bytes.rstrip().decode('ascii')
    finally:
        os.close(fd)


def module_stamp(module):
    path = MODULES / module
    try:
        identity = path.lstat()
    except FileNotFoundError:
        return None
    require(stat.S_ISDIR(identity.st_mode) and identity.st_uid == 0
            and identity.st_mode & 0o022 == 0, 'INVALID_MODULE_STATE')
    return [identity.st_dev, identity.st_ino, identity.st_ctime_ns]


def registration(usb_id):
    if not current_usb(usb_id):
        raise Refused('USB_NO_LONGER_ATTACHED')
    # sysfs owns the parent; canonicalize only that fixed kernel bus path.
    target = NEW_ID.parent.resolve(strict=True) / NEW_ID.name
    require(target.is_relative_to('/sys/bus/usb-serial/drivers'), 'INVALID_OPTION_STATE')
    fd = os.open(target, os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(fd)
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0
                and metadata.st_mode & 0o022 == 0, 'INVALID_OPTION_STATE')
        wire = usb_id.replace(':',' ').encode('ascii') + b'\n'
        try:
            require(os.write(fd, wire) == len(wire), 'OPTION_REGISTRATION_INCOMPLETE')
        except OSError as error:
            if error.errno != errno.EEXIST:
                raise
    finally:
        os.close(fd)


def run_kmod(action, module):
    protected(KMOD)
    # Module paths and options come from the platform and the fixed driver list.
    # Empty additional configuration prevents user-defined install shell commands.
    if action == 'load':
        args = ['modprobe','--config','/dev/null','--ignore-install','--first-time','--',module]
    else:
        args = ['rmmod','--',module]
    subprocess.run([str(KMOD),*args], env=ENVIRONMENT, timeout=15, check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def state_binding():
    metadata = STATE.stat()
    machine = public_file(Path('/etc/machine-id'), 64).strip()
    boot = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
    require(re.fullmatch(rb'[0-9a-f]{32}', machine), 'UNPAIRED_MODEM_STATE')
    identifier(boot)
    return dict(root=[machine.decode('ascii'),metadata.st_dev,metadata.st_ino],boot=boot)


def operate(requested, authorized, capability):
    module = requested['module']
    operation = requested['operationId']
    directory(STATE, 0)
    fd = os.open(STATE / 'lock', os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_RDWR, 0o600)
    try:
        meta = os.fstat(fd)
        require(stat.S_ISREG(meta.st_mode) and meta.st_uid == meta.st_gid == 0
                and stat.S_IMODE(meta.st_mode) == 0o600 and meta.st_nlink == 1, 'UNPAIRED_MODEM_STATE')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return locked_operation(requested, authorized, capability)
    finally:
        os.close(fd)


def locked_operation(requested, authorized, capability):
    context = state_binding()
    anchor = STATE / 'root.json'
    root_binding = dict(schema=1, root=context['root'])
    if os.path.lexists(anchor):
        require(decode(read(anchor, 0)) == root_binding, 'UNPAIRED_MODEM_STATE')
    module = requested['module']
    operation = requested['operationId']
    saved = STATE / (operation + '.intent')
    own = STATE / (operation + '.result')
    if os.path.lexists(saved):
        intent = decode(read(saved, 0))
        require(os.path.lexists(anchor) and intent['root'] == context['root'], 'UNPAIRED_MODEM_STATE')
        require(intent['request'] == requested, 'MODEM_OPERATION_ID_CONFLICT')
        if not os.path.lexists(own):
            return 'UNKNOWN'
        verified_decision(own, intent)
        return 'APPLIED'
    receipts = []
    # Intents and decisions are immutable. Affected modules cannot get a new
    # write while any admitted operation lacks its terminal decision.
    for entry in STATE.glob('*.intent'):
        intent = decode(read(entry, 0))
        require(os.path.lexists(anchor) and intent['root'] == context['root'], 'UNPAIRED_MODEM_STATE')
        result = entry.with_suffix('.result')
        if intent['request']['module'] == module:
            if not os.path.lexists(result):
                return 'UNKNOWN'
            decision = verified_decision(result, intent)
            if intent['boot'] == context['boot']:
                receipts.append(decision)

    before = module_stamp(module)
    load = requested['action'] == 'load'
    usb_id = requested['usbId']
    register = load and module == 'option' and usb_id in DYNAMIC_OPTION_IDS
    if load:
        require(current_usb(usb_id), 'USB_NOT_ATTACHED')
        change_module = before is None
    else:
        change_module = before is not None
        if change_module:
            require(any(row['ownedModule'] == before for row in receipts), 'MODULE_NOT_OWNED')
    if change_module or register:
        require(capability, 'MODEM_CAPABILITY_UNAVAILABLE')
    require(authorized(), 'UNAUTHORIZED')
    if change_module:
        protected(KMOD)
    if load:
        require(current_usb(usb_id), 'USB_NOT_ATTACHED')
    if not os.path.lexists(anchor):
        create(anchor, root_binding)
    intent = dict(**context, request=requested, originalModule=before)
    create(saved, intent)
    if change_module:
        run_kmod(requested['action'], module)
    if register:
        registration(usb_id)
    after = module_stamp(module)
    require((after is not None) if load else (after is None), 'MODULE_OUTCOME_UNVERIFIED')
    create(own, dict(intentSha256=file_hash(encode(intent)), ownedModule=after if load and before is None else None))
    return 'APPLIED'


def verified_decision(path, intent):
    decision = decode(read(path, 0))
    require(set(decision) == {'intentSha256','ownedModule'}
            and decision['intentSha256'] == file_hash(encode(intent)), 'UNPAIRED_MODEM_STATE')
    return decision


def serve(stream, unit):
    main_sha, capability = verify_actor(unit)
    with socket_peer(stream) as peer:
        def peer_request():
            return main_peer(peer, main_sha, CLIENT, 4, request, networking=True)
        expected = peer_request()
        actual = receive(stream)
        require(type(actual.get('schema')) is int and actual == expected, 'INVALID_MODEM_REQUEST')
        result = 'UNKNOWN'
        try:
            result = operate(expected, lambda: peer_request() == expected, capability)
        except Refused as error:
            # Once a write was admitted, do not turn an uncertain outcome into
            # a definite negative response.
            if not os.path.lexists(STATE / (expected['operationId'] + '.intent')):
                result = 'REFUSED'
            print(error.args[0], file=sys.stderr)
        send(stream, dict(schema=1, operationId=expected['operationId'], state=result))


def client(expected):
    meta = SOCKET.lstat()
    require(stat.S_ISSOCK(meta.st_mode) and meta.st_uid == 0 and meta.st_gid == pwd.getpwnam('kurad').pw_gid
            and stat.S_IMODE(meta.st_mode) == 0o660, 'UNPAIRED_MODEM_RELEASE')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(4)
        stream.connect(str(SOCKET))
        require(struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))==(1,0,0),
                'UNPAIRED_MODEM_RELEASE')
        send(stream, expected)
        result = receive(stream)
        require(result == dict(schema=1, operationId=expected['operationId'], state=result.get('state'))
                and type(result['schema']) is int and result['state'] in ('APPLIED','REFUSED','UNKNOWN'),
                'INVALID_MODEM_RESPONSE')
        # Expose only the typed decision to the original Java call.
        return ('APPLIED','REFUSED','UNKNOWN').index(result['state'])


if __name__ == '__main__':
    try:
        argv = sys.argv[1:]
        if len(argv) == 2 and argv[0] == 'serve':
            with socket.socket(fileno=os.dup(0)) as connection:
                serve(connection, argv[1])
        elif len(argv) == 5 and argv[0] == 'client':
            sys.exit(client(request(*argv[1:])))
        else:
            raise Refused('INVALID_MODEM_REQUEST')
    except (Refused, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        print(error.args[0] if isinstance(error, Refused) else 'MODEM_OUTCOME_UNKNOWN', file=sys.stderr)
        sys.exit(2)
