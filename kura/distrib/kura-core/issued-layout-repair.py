# SPDX-License-Identifier: EPL-2.0
"""Control-only handoff for an individually reviewed issued retained layout."""
import ctypes
import hashlib
import hmac
import os
from pathlib import Path
import stat
import tempfile


ISSUED_LAYOUT_SOURCES = ('intent.json', 'layout-repair.json', 'setup-layout-intent.json')
ISSUED_LAYOUT_HANDOFF = 'issued-layout-handoff.json'
ISSUED_LAYOUT_VERIFIED = 'issued-layout-verified.json'


def checked_issued_layout(api, policy, directory, original, recovery, secret, plan):
    """Authenticate the preserved, unresolved history without using the log of the failed child."""
    require = api.require
    root = policy.root.lstat()
    require(original == plan['maintenanceId'] and [root.st_dev, root.st_ino] == plan['root']
            and hashlib.sha256(policy.read(policy.path('/etc/machine-id'), limit=64, private=False)).hexdigest()
            == plan['machineSha256'], 'Issued layout belongs to another Root or maintenance ID')
    require(recovery == plan['recovery'] and len(secret) == 32,
            'Issued layout requires its original retained directory and journal')
    require(not any(os.path.lexists(directory / name) for name in
                    ('setup-layout-returned.json', 'setup-layout-complete.json')),
            'Issued layout has original return or completion evidence')
    records = {}
    for name in ISSUED_LAYOUT_SOURCES:
        path = directory / name
        before = path.lstat()
        raw = policy.read(path, limit=4096)
        require(os.path.samestat(before, path.lstat()) and
                [before.st_dev, before.st_ino, hashlib.sha256(raw).hexdigest()] == plan['records'][name],
                'Issued layout source record changed: ' + name)
        records[name] = raw
    old_intent = records['intent.json']
    checked_repair_source(api, old_intent, original, plan['earlier'], recovery, secret)
    require(records['layout-repair.json'] == layout_repair_receipt(
        api, policy, original, old_intent, recovery, plan['earlier'], plan['issued'], secret),
        'Issued layout predecessor handoff is not authenticated')
    checked_repair_source(api, records['setup-layout-intent.json'], original, plan['issued'],
                          recovery, secret, phase='setup-layout-intent')


def issued_layout_record(api, plan, target, phase, secret, *, placeholders=None):
    purpose = 'kura-core-issued-layout-repair-v1'
    evidence = dict(schema=1, purpose=purpose, phase=phase, maintenanceId=plan['maintenanceId'],
                    originalOutcome='UNRESOLVED', planSha256=hashlib.sha256(api.encoded(plan)).hexdigest(),
                    successor=target)
    if placeholders is not None:
        evidence['placeholders'] = placeholders
    tag = hmac.new(secret, purpose.encode('ascii') + b'\0' + api.encoded(evidence), hashlib.sha256).hexdigest()
    return api.encoded(dict(evidence, tag=tag))


def publish_issued_layout_record(policy, directory, name, raw):
    with tempfile.TemporaryDirectory(prefix=f'.{directory.name}-issued-', dir=directory.parent) as pending:
        staged = Path(pending) / name
        policy.create(staged, raw)
        rename = ctypes.CDLL(None, use_errno=True).renameat2
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(staged), -100, os.fsencode(directory / name), 1):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(directory / name))
    policy.sync(directory)


def admit_issued_layout(api, policy, directory, original, physical, target, control_sha, dpkg, plan):
    require = api.require
    names = {path.name for path in directory.iterdir()}
    initial = set(ISSUED_LAYOUT_SOURCES)
    require(names in (initial, initial | {ISSUED_LAYOUT_HANDOFF}),
            'Issued layout has advanced beyond the reviewed package handoff')
    authorized = ISSUED_LAYOUT_HANDOFF in names
    old = plan['issued']
    require(old['manifestSha256'] == target['manifestSha256'], 'Issued layout requires the original package payload')
    half_installed = 'install reinstreq half-installed'
    old_half = ['install ok half-configured', old['packageVersion']]
    old_interrupted = [half_installed, old['packageVersion']]
    new_unpacked = ['install ok unpacked', target['packageVersion']]
    # dpkg marks the old version reinstreq/half-installed before it invokes
    # the incoming preinst, even on the first (uninterrupted) unpack.
    require(dpkg in (old_half, old_interrupted) or authorized and dpkg == new_unpacked,
            'Core is outside the reviewed issued layout unpack state')
    require((dpkg == new_unpacked and control_sha == target['postinstSha256'])
            or (dpkg != new_unpacked and control_sha == old['postinstSha256'])
            or (authorized and dpkg == old_interrupted and control_sha == target['postinstSha256']),
            'Unpaired issued layout postinst')
    retained = policy.path('/var/lib/kura-retained')
    policy.directory(retained, private=True)
    info = retained.lstat()
    recovery = dict(mode='reinstall', device=info.st_dev, inode=info.st_ino)
    require(not os.path.lexists(retained / '.partial-payload'), 'Original removal copy was partially unpacked')
    secret = policy.read(policy.state / 'journal.key', limit=32)
    checked_issued_layout(api, policy, directory, original, recovery, secret, plan)
    receipt = issued_layout_record(api, plan, target, 'AUTHORIZED_HANDOFF', secret)
    if authorized:
        require(policy.read(directory / ISSUED_LAYOUT_HANDOFF, limit=4096) == receipt,
                'Original issued layout handoff changed')
    issued_layout_stop(api, policy, physical, plan, retry=False)
    if not authorized:
        # The first admission is still at the old installed payload. A later
        # interrupted unpack may already have replaced some launchers.
        require(prepare_retained_generation(unpacked_layout=True) == 0,
                'Original issued layout credentials changed')
        cohort = policy.generation_assets()
        require(cohort['manifestSha256'] == old['manifestSha256'], 'Original issued layout cohort changed')
        check_issued_scripts(api, policy, physical, plan, templates=False, executable=False)
        publish_issued_layout_record(policy, directory, ISSUED_LAYOUT_HANDOFF, receipt)
    else:
        policy.sync(directory)


def check_issued_scripts(api, policy, physical, plan, *, templates, executable):
    require = api.require
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    expected = plan['scripts']
    require({path.name for path in (physical / 'bin').glob('*.sh')} == set(expected),
            'Issued layout shell entries differ')
    changed = {}
    for name, digest in expected.items():
        path = physical / 'bin' / name
        raw = policy.read(path, private=False)
        with os.fdopen(os.open(path, flags), 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(os.path.samestat(info, path.lstat()) and info.st_gid == 0 and
                    stat.S_IMODE(info.st_mode) in ((0o644, 0o755) if executable else (0o644,))
                    and not os.listxattr(stream.fileno()) and stream.read(65537) == raw,
                    'Issued layout shell file changed: ' + name)
        observed = hashlib.sha256(raw).hexdigest()
        if observed == digest:
            changed[path] = (raw, info, None)
            continue
        require(templates and plan['templates'].get(name) == observed,
                'Issued layout shell contents differ: ' + name)
        retained = policy.path('/var/lib/kura-retained/published-generation') / name
        published = policy.read(retained, limit=65536)
        require(hashlib.sha256(published).hexdigest() == digest,
                'Issued layout retained launcher differs: ' + name)
        changed[path] = (raw, info, published)
    return changed


def issued_layout_stop(api, policy, physical, plan, *, retry):
    require = api.require
    logical = policy.path('/opt/eclipse/kura')
    require(logical.is_symlink() and logical.lstat().st_uid == policy.owner
            and logical.resolve(strict=True) == physical, 'Original issued Main link changed')
    fields = policy.main_unit_properties('MainPID', 'ControlPID', 'ActiveState')
    require(fields['LoadState'] == 'loaded' and fields['UnitFileState'] == 'disabled'
            and fields['MainPID'] == fields['ControlPID'] == '0' and fields['ActiveState'] == 'inactive'
            and fields['NeedDaemonReload'] == 'no', 'Issued layout requires the original stopped disabled Main')
    manifest = policy.assets()
    main = policy.read(policy.main_vendor_path(), private=False)
    require(hashlib.sha256(main).hexdigest() == manifest['generation']['unitSha256'],
            'Issued layout requires the original vendor Main')
    names = set(manifest['units']) | {'kura.service'}
    for name in sorted(names - {'kura.service'}):
        status = policy.command(['show', name, '--property=LoadState,ActiveState,MainPID,ControlPID'])
        fields = dict(line.split('=', 1) for line in status.splitlines() if '=' in line)
        require(fields.get('LoadState') == 'loaded' and fields.get('ActiveState') in ('inactive', 'failed')
                and fields.get('MainPID', '0') == fields.get('ControlPID', '0') == '0',
                'Issued layout requires the original stopped unit: ' + name)
    jobs = policy.command(['list-jobs', '--no-legend', '--plain'])
    require(all(len(row.split()) >= 2 and row.split()[1] not in names for row in jobs.splitlines() if row.strip()),
            'Issued layout has a pending Main or key-service job')

    for name in ('kura-bind-service', 'kura-dhcp-service', 'kura-modem-reset'):
        path = policy.path('/var/lib/' + name)
        policy.directory(path, private=True)
        info = path.lstat()
        require(info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o700 and not any(path.iterdir()),
                'Issued layout requires the original empty broker journal: ' + name)
    dhcp = policy.path('/etc/kura/dhcp-service/dnsmasq.conf')
    raw = policy.read(dhcp, private=False)
    info = dhcp.lstat()
    require(info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o644 and not os.listxattr(dhcp)
            and hashlib.sha256(raw).hexdigest() == plan['dhcpSha256'], 'Issued layout DHCP configuration differs')

    for name in ('.data', 'data'):
        path = physical / name
        if os.path.lexists(path):
            require(retry, 'Unexpected placeholder before issued layout handoff: ' + name)
            policy.directory(path)
            info = path.lstat()
            require(info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o755
                    and not any(path.iterdir()) and not os.path.ismount(path),
                    'Unsafe issued layout placeholder: ' + name)
