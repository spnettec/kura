#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh, empty systemd-container fixture; no socket start, account or clock IO."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, '/opt/eclipse/kura/bin')
import kura_clock_broker as broker

ROWS = []
PIN = 'clock-policy-fixture-pin.service'
PIN_RAW = (b'[Unit]\nAfter=kura-clock-broker.service\n[Service]\n'
           b'ExecStart=/usr/bin/sleep infinity\nUser=nobody\nGroup=nogroup\n'
           b'NoNewPrivileges=yes\nCapabilityBoundingSet=\nAmbientCapabilities=\nMemoryMax=8M\nTasksMax=2\n')
PROPERTIES = ('Id', 'Names', 'LoadState', 'FragmentPath', 'SourcePath', 'DropInPaths',
              'NeedDaemonReload', 'Transient', 'ActiveState')


def run(*arguments):
    return subprocess.check_output(['/usr/bin/systemctl', '--system', '--no-ask-password', *arguments],
                                   env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}, text=True, timeout=10)


def reload():
    run('daemon-reload')


def no_operations():
    assert not any(os.path.lexists(path) for path in [broker.STATE, broker.SOCKET, broker.ACTOR_HOME,
                   '/var/lib/kura-key-service', '/var/lib/kura-key-recovery', '/etc/kura', broker.HOME / 'data'])
    status = Path('/proc/self/status').read_text().splitlines()
    for line in status:
        if line.startswith(('CapInh:', 'CapPrm:', 'CapEff:', 'CapBnd:', 'CapAmb:')):
            assert not int(line.split(':', 1)[1].strip(), 16) & broker.SYS_TIME
    for name in broker.UNITS:
        value = broker.systemd_properties(PROPERTIES, name)
        assert value['ActiveState'] in ('inactive', 'failed'), value
        if name.endswith('.service'):
            processes = broker.systemd_properties(('MainPID', 'ControlPID'), name)
            assert processes == {'MainPID': '0', 'ControlPID': '0'}, processes


def accepted(label):
    policy = broker.Policy(); policy.check(); no_operations()
    ROWS.append(dict(case=label, state='ACCEPTED', cohortSha256=policy.cohort))


def refused(label, check=None):
    try:
        (check or broker.Policy().check)()
    except broker.Refused as error:
        assert error.reason == 'UNPAIRED_CODE', error.reason
        ROWS.append(dict(case=label, state='REFUSED', reason=error.reason))
    else:
        raise AssertionError('Unexpected admission: ' + label)
    no_operations()


def make(path, raw=None, target=None):
    missing = []
    for parent in path.parents:
        if parent.is_dir():
            break
        assert not os.path.lexists(parent), str(parent)
        missing.append(parent)
    for parent in reversed(missing):
        parent.mkdir(mode=0o755)
    assert not os.path.lexists(path), str(path)
    if target is not None:
        path.symlink_to(target)
    else:
        with path.open('xb') as f:
            os.fchmod(f.fileno(), 0o644); f.write(raw)
    return missing


def remove_own(path, parents, raw=None, target=None):
    if target is not None:
        assert path.is_symlink() and os.readlink(path) == target
    else:
        assert path.is_file() and not path.is_symlink() and path.read_bytes() == raw
    assert path.lstat().st_uid == 0
    path.unlink()
    for parent in parents:
        parent.rmdir()


def pin():
    # Keep the inactive clock fragment referenced. Otherwise PID1 may garbage
    # collect and freshly load it, which cannot exercise NeedDaemonReload.
    path = Path('/run/systemd/system') / PIN
    parents = make(path, raw=PIN_RAW)
    reload(); run('start', PIN)
    pid = run('show', PIN, '--property=MainPID', '--value').strip()
    status = dict(line.split(':', 1) for line in Path('/proc/' + pid + '/status').read_text().splitlines() if ':' in line)
    assert status['Uid'].split() == ['65534'] * 4 and status['NoNewPrivs'].strip() == '1'
    assert all(int(status[k], 16) == 0 for k in ['CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'])
    assert Path('/proc/' + pid + '/cmdline').read_bytes() == b'/usr/bin/sleep\0infinity\0'
    return path, parents, pid


def unpin(holder):
    path, parents, pid = holder
    assert run('show', PIN, '--property=MainPID', '--value').strip() == pid
    assert Path('/proc/' + pid + '/cmdline').read_bytes() == b'/usr/bin/sleep\0infinity\0'
    run('stop', PIN)
    assert run('show', PIN, '--property=MainPID', '--value').strip() == '0'
    remove_own(path, parents, raw=PIN_RAW); reload()


def override(path, label, loaded=True, raw=b'[Service]\nMemoryMax=67108865\n', name=broker.UNITS[1]):
    parents = make(path, raw=raw)
    try:
        refused(label + '-before-reload')
        if loaded:
            reload()
            value = broker.systemd_properties(PROPERTIES, name)
            assert value['DropInPaths'], value
            refused(label + '-loaded-metadata', broker.effective_units)
            ROWS[-1]['loadedDropInPaths'] = value['DropInPaths']
    finally:
        remove_own(path, parents, raw=raw); reload()
    accepted(label + '-original-restored')


def main():
    assert os.getuid() == os.geteuid() == 0
    reload(); roots = broker.unit_load_paths(); accepted('original-loaded-vendor-unit')
    for index, root in enumerate(roots):
        # Includes control/attached/generator roots and both vendor layouts.
        # Do not daemon-reload generator-owned directories while the test input exists.
        path = root / (broker.UNITS[1] + '.d') / '91-kura-clock-fixture.conf'
        override(path, 'lookup-root-' + str(index), loaded='generator' not in str(root))
    override(Path('/run/systemd/system/service.d/91-kura-clock-fixture.conf'), 'all-services')
    override(Path('/run/systemd/system/kura-clock-.service.d/91-kura-clock-fixture.conf'), 'clock-prefix')
    override(Path('/run/systemd/system/kura-.socket.d/91-kura-clock-fixture.conf'), 'kura-socket-prefix',
             raw=b'[Socket]\nBacklog=17\n', name=broker.UNITS[0])
    for suffix in ('.wants', '.requires', '.upholds'):
        path = Path('/run/systemd/system') / (broker.UNITS[1] + suffix)
        parents = make(path / 'fixture.service', target='/dev/null')
        try:
            refused('dependency' + suffix)
        finally:
            remove_own(path / 'fixture.service', parents, target='/dev/null')
        accepted('dependency' + suffix + '-original-restored')
    # A second identical fragment in another priority directory is still unpaired.
    for root in [Path('/usr/local/lib/systemd/system'), Path('/run/systemd/system.attached')]:
        path = root / broker.UNITS[1]; raw = (broker.VENDOR_UNIT_ROOTS[0] / broker.UNITS[1]).read_bytes()
        parents = make(path, raw=raw)
        try:
            refused('shadow-fragment-' + root.as_posix())
            reload(); value = broker.systemd_properties(PROPERTIES, broker.UNITS[1])
            assert value['FragmentPath'] == str(path), value
            refused('loaded-shadow-fragment', broker.effective_units)
        finally:
            remove_own(path, parents, raw=raw); reload()
        accepted('shadow-fragment-original-restored')
    # Exercise the real SetUnitProperties path, which writes system.control.
    folder = Path('/run/systemd/system.control') / (broker.UNITS[1] + '.d')
    assert not os.path.lexists(folder)
    run('set-property', '--runtime', broker.UNITS[1], 'MemoryMax=67108865')
    files = list(folder.iterdir()); assert len(files) == 1 and files[0].name == '50-MemoryMax.conf'
    raw = files[0].read_bytes(); assert b'MemoryMax=67108865' in raw
    try:
        refused('real-runtime-set-property')
    finally:
        remove_own(files[0], [folder], raw=raw); reload()
    accepted('runtime-property-original-restored')
    # Restoring bytes alone cannot declare PID1 reloaded; retain the stale gate.
    path = broker.VENDOR_UNIT_ROOTS[0] / broker.UNITS[1]; raw = path.read_bytes()
    try:
        path.write_bytes(raw + b'\n# public fixture stale marker\n')
        value = broker.systemd_properties(PROPERTIES, broker.UNITS[1]); assert value['NeedDaemonReload'] == 'yes', value
        refused('stale-loaded-fragment', broker.effective_units)
        path.write_bytes(raw)
        value = broker.systemd_properties(PROPERTIES, broker.UNITS[1]); assert value['NeedDaemonReload'] == 'yes', value
        refused('original-bytes-restored-before-reload', broker.effective_units)
    finally:
        assert path.read_bytes() in (raw, raw + b'\n# public fixture stale marker\n')
        path.write_bytes(raw); reload()
    accepted('original-fragment-reloaded')
    no_operations()
    print(json.dumps(dict(cases=ROWS, passed=len(ROWS), unitLoadPaths=[str(p) for p in roots],
                         systemdVersion=run('--version').splitlines()[0], clockOperations=0,
                         clockNamespaceAbsent=True, actorAndSocketNeverStarted=True, realKeysRead=False)))


if __name__ == '__main__':
    holder = pin()
    try:
        main()
    except Exception:
        print(json.dumps(dict(completedCases=ROWS, incomplete=True)))
        raise
    finally:
        unpin(holder)
