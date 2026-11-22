#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Provision and fence the standalone Core reboot broker during package changes."""
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import publish_path, unit_directory_present
from kura_clock_journal import Refused, create, decode, digest, directory, encode, identifier, read, require, sync
from kura_reboot_broker import (AUTHORITY, CALLER, COHORT, ENVIRONMENT, HOME, INSTALLATION, MAIN_UNIT,
                               SENDER, STATE, UNITS, Policy, account_binding, file_hash, public_file,
                               sender_binding, verify_unit_sources)
from kura_reboot_journal import RebootJournal, admission_lock, request, sha256

ACTOR, SOCKET = UNITS[:2]
VENDOR = Path('/lib/systemd/system')
LOCK = INSTALLATION.with_name('.reboot-broker-package.lock')
FENCE = 'maintenance.json'


def exists(path):
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def run(*arguments):
    return subprocess.check_output(['/usr/bin/systemctl', '--system', *arguments],
                                   env=ENVIRONMENT, text=True, timeout=20)


def activity(unit):
    require(unit in (MAIN_UNIT, ACTOR, SOCKET), 'UNPAIRED_UNIT')
    keys = ('LoadState', 'ActiveState', 'ControlPID', 'MainPID')
    result = subprocess.run(['/usr/bin/systemctl', '--system', 'show', '--all', '--property=' + ','.join(keys), unit],
                            env=ENVIRONMENT, capture_output=True, text=True, timeout=5)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    require((result.returncode == 0 and values.get('LoadState') in ('loaded', 'masked', 'not-found'))
            or (result.returncode == 1 and values.get('LoadState') == 'not-found'), 'UNPAIRED_UNIT')
    return values


def inactive(unit):
    value = activity(unit)
    require(value.get('ActiveState') in ('inactive', 'failed')
            and value.get('MainPID', '0') == value.get('ControlPID', '0') == '0', 'UNIT_RUNNING')


def current_units(manifest):
    return {unit: manifest['files'][(COHORT.parent / unit).as_posix()] for unit in (ACTOR, SOCKET)}


def durable_publish(path, value, mode):
    with tempfile.TemporaryDirectory(prefix='.kura-reboot-marker-', dir=path.parent) as temporary:
        staged = Path(temporary) / path.name
        create(staged, value, mode)
        publish_path(staged, path, False)
        sync(path.parent)


def bound_installation():
    binding = account_binding(INSTALLATION)
    require(read(INSTALLATION, 0, 0o600) == encode(binding)
            and read(AUTHORITY, 0, 0o644) == encode(binding), 'UNPAIRED_INSTALLATION')
    sender_binding(binding)
    return binding


def maintenance(binding):
    path = STATE / FENCE
    if not exists(path):
        return None
    raw = read(path, 0)
    value = decode(raw)
    require(raw == encode(value) and set(value) == {'schema', 'namespace', 'purposeId', 'oldCohortSha256', 'units'}
            and type(value['schema']) is int and value['schema'] == 1 and value['namespace'] == binding['namespace']
            and type(value['units']) is dict and set(value['units']) == {ACTOR, SOCKET}, 'UNPAIRED_MAINTENANCE')
    identifier(value['purposeId'])
    sha256(value['oldCohortSha256'])
    for item in value['units'].values():
        sha256(item)
    return value


def fence_value(binding, manifest):
    return dict(schema=1, namespace=binding['namespace'], purposeId=str(uuid.uuid4()),
                oldCohortSha256=digest(manifest), units=current_units(manifest))


def verify_known_units(manifest, fence):
    current = current_units(manifest)
    for name in (ACTOR, SOCKET):
        path = VENDOR / name
        if exists(path):
            actual = file_hash(public_file(path))
            require(actual in (fence['units'][name], current[name]), 'UNPAIRED_UNIT')


def provision(manifest):
    """Keep the same reservation across interruptions, and publish authority last."""
    if exists(AUTHORITY):
        return bound_installation()
    require(not any(exists(VENDOR / name) for name in (ACTOR, SOCKET)), 'UNPAIRED_INSTALLATION')
    if not exists(INSTALLATION):
        require(not exists(STATE) and not exists(SENDER), 'UNPAIRED_INSTALLATION')
        user = pwd.getpwnam(CALLER)
        require(user.pw_uid > 0 and user.pw_gid > 0, 'UNPAIRED_ACCOUNT')
        binding = dict(schema=1, namespace=str(uuid.uuid4()), callerUid=user.pw_uid, callerGid=user.pw_gid)
        durable_publish(INSTALLATION, binding, 0o600)
    binding = account_binding(INSTALLATION)
    require(read(INSTALLATION, 0, 0o600) == encode(binding), 'UNPAIRED_INSTALLATION')
    if not exists(STATE):
        with tempfile.TemporaryDirectory(prefix='.kura-reboot-state-', dir=STATE.parent) as temporary:
            staged = Path(temporary) / STATE.name
            staged.mkdir(mode=0o700)
            RebootJournal(staged, binding['namespace'], digest(manifest)).initialize()
            create(staged / FENCE, fence_value(binding, manifest))
            publish_path(staged, STATE, False)
            sync(STATE.parent)
    journal = RebootJournal(STATE, binding['namespace'], digest(manifest))
    with journal.locked():
        require(maintenance(binding) is not None and not any((STATE / 'operations').iterdir()), 'UNPAIRED_INSTALLATION')
        if not exists(SENDER):
            with tempfile.TemporaryDirectory(prefix='.kura-reboot-sender-', dir=SENDER.parent) as temporary:
                staged = Path(temporary) / SENDER.name
                staged.mkdir(mode=0o700)
                create(staged / 'binding.json', binding, 0o644)
                os.chown(staged, binding['callerUid'], binding['callerGid'])
                sync(staged)
                publish_path(staged, SENDER, False)
                sync(SENDER.parent)
        sender_binding(binding)
        require({entry.name for entry in SENDER.iterdir()} == {'binding.json'}, 'UNPAIRED_INSTALLATION')
        durable_publish(AUTHORITY, binding, 0o644)
    return bound_installation()


def validate_pending(binding):
    path = SENDER / 'pending.json'
    if exists(path):
        raw = read(path, binding['callerUid'])
        value = request(decode(raw))
        require(raw == encode(value) and value['namespace'] == binding['namespace'], 'UNPAIRED_SENDER')


def quiesce(*, require_original=False):
    manifest = Policy().packaged()
    verify_unit_sources((ACTOR, SOCKET))
    if not exists(AUTHORITY):
        # An interrupted first configuration never published an active actor.
        require(exists(INSTALLATION) or not (exists(STATE) or exists(SENDER)), 'UNPAIRED_INSTALLATION')
        require(not any(exists(VENDOR / name) for name in (ACTOR, SOCKET)), 'UNPAIRED_UNIT')
        inactive(SOCKET)
        inactive(ACTOR)
        return
    binding = bound_installation()
    with RebootJournal(STATE, binding['namespace'], digest(manifest)).locked():
        current = maintenance(binding)
        if current is None:
            require(not require_original, 'UNPAIRED_MAINTENANCE')
            Policy().check(actor=True, include_main=False)
            current = fence_value(binding, manifest)
            durable_publish(STATE / FENCE, current, 0o600)
        verify_known_units(manifest, current)
    if any(activity(unit).get('ActiveState') not in ('inactive', 'failed') for unit in (ACTOR, SOCKET)):
        run('stop', SOCKET, ACTOR)
    inactive(SOCKET)
    inactive(ACTOR)


def reassert_quiescence():
    inactive(MAIN_UNIT)
    if any(activity(unit).get('ActiveState') not in ('inactive', 'failed')
           for unit in (SOCKET, ACTOR)):
        quiesce(require_original=True)
    inactive(SOCKET)
    inactive(ACTOR)


def resume():
    manifest = Policy().packaged()
    verify_unit_sources((ACTOR, SOCKET))
    inactive(MAIN_UNIT)
    binding = provision(manifest)
    validate_pending(binding)
    journal = RebootJournal(STATE, binding['namespace'], digest(manifest))
    with journal.locked():
        current = maintenance(binding)
        if current is None:
            Policy().check(actor=True, include_main=False)
            require(activity(SOCKET).get('ActiveState') == 'active', 'SOCKET_INACTIVE')
            return
        verify_known_units(manifest, current)
        # A previous configure may have reached socket activation before exit.
        if activity(SOCKET).get('ActiveState') != 'active':
            inactive(SOCKET)
            inactive(ACTOR)
            require(unit_directory_present(VENDOR), 'UNPAIRED_UNIT')
            for name in (ACTOR, SOCKET):
                source = public_file(HOME / COHORT.parent / name)
                path = VENDOR / name
                if exists(path) and public_file(path) == source:
                    continue
                with tempfile.TemporaryDirectory(prefix='.kura-reboot-unit-', dir=VENDOR) as temporary:
                    staged = Path(temporary) / name
                    with staged.open('xb') as output:
                        os.fchmod(output.fileno(), 0o644)
                        output.write(source)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(staged, path)
                    sync(VENDOR)
            run('daemon-reload')
            Policy().check(actor=True, include_main=False)
            run('enable', '--now', SOCKET)
        Policy().check(actor=True, include_main=False)
        require(activity(SOCKET).get('ActiveState') == 'active'
                and run('is-enabled', SOCKET).strip() == 'enabled'
                and maintenance(binding) == current, 'UNPAIRED_UNIT')
        (STATE / FENCE).unlink()
        sync(STATE)


def remove():
    inactive(MAIN_UNIT)
    inactive(SOCKET)
    inactive(ACTOR)
    if not exists(AUTHORITY):
        return
    binding = bound_installation()
    validate_pending(binding)
    manifest = Policy().packaged()
    with RebootJournal(STATE, binding['namespace'], digest(manifest)).locked():
        current = maintenance(binding)
        require(current is not None, 'UNPAIRED_MAINTENANCE')
        verify_known_units(manifest, current)
        if exists(VENDOR / SOCKET):
            run('disable', SOCKET)
        for unit in (ACTOR, SOCKET):
            if exists(VENDOR / unit):
                (VENDOR / unit).unlink()
                sync(VENDOR)
        run('daemon-reload')
        inactive(SOCKET)
        inactive(ACTOR)
    # Root, sender and the reservation are outside the ordinary purge tree.


if __name__ == '__main__':
    try:
        commands = {'quiesce': quiesce, 'reassert_quiescence': reassert_quiescence,
                    'resume': resume, 'remove': remove}
        require(os.geteuid() == 0 and len(sys.argv) == 2 and sys.argv[0] == str(HOME / 'bin/kura_reboot_setup.py')
                and sys.argv[1] in commands, 'INVALID_ENTRYPOINT')
        require(unit_directory_present(INSTALLATION.parent), 'UNPAIRED_INSTALLATION')
        with admission_lock(LOCK, 0, create_if_missing=True):
            commands[sys.argv[1]]()
    except (Refused, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(error.reason if isinstance(error, Refused) else 'UNRESOLVED_OR_UNAVAILABLE', file=sys.stderr)
        raise SystemExit(1)
