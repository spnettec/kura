# SPDX-License-Identifier: EPL-2.0
"""Carry the original Core directory across dpkg's removal of the public link."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid


PARENT = Path('/opt/eclipse')
HOME = PARENT / 'kura'
ROOT = Path('/')
JOURNAL_KEY = Path('/var/lib/kura-key-service/journal.key')
GENERATION_DROPIN = Path('/etc/systemd/system/kura.service.d/40-kura-key-generations.conf')
GENERATION_LAUNCHERS = ('start_kura.sh', 'start_kura_background.sh', 'start_kura_debug.sh')
GENERATION_TAG = b'kura-core-retained-generation-v1\0'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def identity(path):
    st = path.lstat()
    return [st.st_dev, st.st_ino]


def protected(path, directory):
    for entry in (*reversed(path.parents), path):
        st = entry.lstat()
        check_type = stat.S_ISREG if entry == path and not directory else stat.S_ISDIR
        require(check_type(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022,
                f'Unsafe removal record or installation path: {entry}')
        if entry == path and not directory:
            require(st.st_nlink == 1, f'Unexpected link count: {entry}')


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new(path, data):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as dst:
        dst.write(data)
        dst.flush()
        os.fsync(dst.fileno())
    sync_dir(path.parent)


def no_mounts_below(path):
    for line in Path('/proc/self/mountinfo').read_bytes().splitlines():
        name = re.sub(rb'\\([0-7]{3})', lambda m: bytes([int(m[1], 8)]), line.split()[4])
        mount = Path(os.fsdecode(name))
        require(mount != path and path not in mount.parents, f'Installation still contains a mount: {mount}')


def removal_tag(record, context=b'kura-core-removal-packages-v1\0'):
    protected(JOURNAL_KEY, False)
    require(JOURNAL_KEY.stat().st_mode & 0o077 == 0, 'Unsafe removal journal key')
    key = JOURNAL_KEY.read_bytes()
    require(len(key) == 32, 'Invalid removal journal key')
    payload = json.dumps(record, sort_keys=True, separators=(',', ':')).encode('ascii')
    return hmac.new(key, context + payload, hashlib.sha256).hexdigest()


def generation_input(path, limit=65536):
    protected(path, False)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == 0
                and not before.st_mode & 0o7022 and 0 < before.st_size <= limit,
                'Unsafe published-generation file')
        raw = stream.read(limit + 1)
        after = path.lstat()
        require(len(raw) == before.st_size and (before.st_dev, before.st_ino, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_ctime_ns), 'Published-generation file changed')
        return raw


def retained_generation(retained, operation):
    current = JOURNAL_KEY.parent / 'generation-current.json'
    saved = retained / 'published-generation'
    if not os.path.lexists(current):
        require(not os.path.lexists(saved) and not os.path.lexists(GENERATION_DROPIN),
                'Retained generation requires its original publication')
        return
    protected(saved, True)
    require(stat.S_IMODE(saved.lstat().st_mode) == 0o700 and {p.name for p in saved.iterdir()} ==
            {*GENERATION_LAUNCHERS, 'receipt.json'}, 'Incomplete retained generation')
    require(all(stat.S_IMODE(p.lstat().st_mode) == 0o600 for p in saved.iterdir())
            and stat.S_IMODE(GENERATION_DROPIN.lstat().st_mode) == 0o400,
            'Unsafe retained generation permissions')
    receipt = json.loads(generation_input(saved / 'receipt.json', 4096))
    tag = receipt.pop('tag')
    require(hmac.compare_digest(tag, removal_tag(receipt, GENERATION_TAG))
            and receipt['operation'] == operation and receipt['root'] == identity(ROOT)
            and receipt['retained'] == identity(retained), 'Retained generation belongs to another removal')
    raw = generation_input(current, 8192)
    publication = json.loads(raw)
    digest = lambda data: hashlib.sha256(data).hexdigest()
    hashes = {name: digest(generation_input(saved / name)) for name in GENERATION_LAUNCHERS}
    binding = dict(schema=1, purpose='yofc-kura-key-generation-package-v1',
                   manifestSha256=receipt['manifestSha256'], launcherSha256s=hashes)
    require(receipt['publicationSha256'] == digest(raw) and receipt['publicationId'] == publication['operationId']
            and receipt['dropinSha256'] == digest(generation_input(GENERATION_DROPIN))
            and receipt['cohortSha256'] == publication['cohortSha256']
            and receipt['cohortSha256'] == digest(json.dumps(binding, sort_keys=True, separators=(',', ':')).encode('ascii')),
            'Retained launchers or credentials differ from the original publication')
    return receipt


def capture_generation(physical, retained, operation):
    current = JOURNAL_KEY.parent / 'generation-current.json'
    if not os.path.lexists(current):
        retained_generation(retained, operation)
        return
    # prerm has verified the complete installed reader cohort and original keys
    # under this removal fence. Persist only the three site-adjusted launchers.
    raw = generation_input(current, 8192)
    publication = json.loads(raw)
    saved = retained / 'published-generation'
    saved.mkdir(mode=0o700)
    for name in GENERATION_LAUNCHERS:
        write_new(saved / name, generation_input(physical / 'bin' / name))
    digest = lambda data: hashlib.sha256(data).hexdigest()
    receipt = dict(schema=1, operation=operation, root=identity(ROOT), retained=identity(retained),
                   publicationId=publication['operationId'], publicationSha256=digest(raw),
                   cohortSha256=publication['cohortSha256'],
                   manifestSha256=digest(generation_input(physical / 'libexec/key-backup/manifest.json')),
                   dropinSha256=digest(generation_input(GENERATION_DROPIN)))
    receipt['tag'] = removal_tag(receipt, GENERATION_TAG)
    write_new(saved / 'receipt.json', json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode('ascii'))
    retained_generation(retained, operation)
    sync_dir(retained)


def capture_history(physical, retained, record):
    packages = physical / 'packages'
    if not packages.is_dir() or packages.is_symlink():
        return
    registry = (packages / 'dpa.properties').resolve()
    pattern = re.compile(re.escape('.' + registry.name) + r'\.(install|uninstall)-[0-9a-f]{64}\.done')
    if not registry.parent.is_dir() or not any(pattern.fullmatch(p.name) for p in registry.parent.iterdir()):
        return
    # Park on the installation filesystem, even when /var/lib is a different mount.
    holder = Path(tempfile.mkdtemp(prefix='.kura-removed-packages-', dir=PARENT))
    sync_dir(PARENT)
    record.update(packages=identity(packages), holder=holder.name, holderIdentity=identity(holder),
                  retained=identity(retained))
    record['packageTag'] = removal_tag(record)


def package_record(retained):
    path = retained / 'removal-home.json'
    protected(path, False)
    record = json.loads(path.read_bytes())
    tag = record.pop('packageTag', None)
    require(tag is not None and hmac.compare_digest(tag, removal_tag(record))
            and record['root'] == identity(ROOT) and record['parent'] == identity(PARENT)
            and record['retained'] == identity(retained)
            and record['operation'] == json.loads((retained / 'systemd/main-state.json').read_bytes())['maintenanceId'],
            'Different retained deployment history or removal Root')
    return record


def paired_removal(retained):
    record = package_record(retained)
    physical = PARENT / record['name']
    protected(physical, True)
    witness = physical / ('.kura-remove-' + record['operation'])
    protected(witness, False)
    require(identity(physical) == record['target'] and identity(HOME) == record['alias']
            and HOME.resolve(strict=True) == physical
            and witness.read_bytes() == (retained / 'removal-home.json').read_bytes(),
            'Original deployment removal home changed')
    holder = PARENT / record['holder']
    protected(holder, True)
    require(identity(holder) == record['holderIdentity'], 'Original deployment holding directory changed')
    return record, physical, holder


def locate_retention(destination):
    """Find the fully captured directory for the active removal before copying again."""
    protected(destination.parent, True)
    fence_path = JOURNAL_KEY.parent / 'maintenance.json'
    protected(fence_path, False)
    fence = json.loads(fence_path.read_bytes())
    operation = str(uuid.UUID(fence['id']))
    require(fence['state'] == 'MAINTENANCE' and fence['firstAction'] == 'remove' and fence['id'] == operation,
            'Retention publication requires the active removal')
    physical = HOME.resolve(strict=True)
    require(physical.parent == PARENT, 'Different Core installation parent')
    protected(physical, True)
    witness = physical / ('.kura-remove-' + operation)
    published = os.path.lexists(destination)
    if not os.path.lexists(witness):
        require(not published and not any(physical.glob('.kura-remove-*')),
                'Existing removal has no paired installation witness for the active fence')
        return 'NEW'
    protected(witness, False)
    raw = witness.read_bytes()
    record = json.loads(raw)
    require(record['operation'] == operation and record['root'] == identity(ROOT)
            and record['parent'] == identity(PARENT) and record['name'] == physical.name
            and record['target'] == identity(physical) and record['alias'] == identity(HOME),
            'Original Core installation differs from its removal witness')
    if published:
        stage = destination
    elif 'stagingName' in record:
        require(re.fullmatch(r'\.kura-retained\.tmp\.[A-Za-z0-9]{8}', record['stagingName']),
                'Invalid original retention staging name')
        stage = destination.parent / record['stagingName']
    else:
        # Older package-history witnesses recorded the directory identity only.
        matches = [p for p in destination.parent.glob('.kura-retained.tmp.????????')
                   if identity(p) == record.get('retained')]
        require(len(matches) == 1, 'Cannot identify the original retention staging directory')
        stage = matches[0]
    protected(stage, True)
    require(stage.lstat().st_mode & 0o077 == 0 and identity(stage) == record.get('retained'),
            'Original retention staging directory changed')
    saved = stage / 'removal-home.json'
    protected(saved, False)
    require(saved.read_bytes() == raw, 'Staged removal record differs from its installation witness')
    main = stage / 'systemd/main-state.json'
    protected(main, False)
    require(json.loads(main.read_bytes())['maintenanceId'] == operation, 'Different retained Main maintenance')
    retained_generation(stage, operation)
    if 'packageTag' in record:
        paired_removal(stage)
    if published:
        sync_dir(destination.parent)
        return 'PUBLISHED'
    return str(stage)


def park(retained):
    record, physical, holder = paired_removal(retained)
    source, saved = physical / 'packages', holder / 'packages'
    if os.path.lexists(source):
        require(identity(source) == record['packages'] and not os.path.lexists(saved),
                'Original deployment directory changed before removal')
        no_mounts_below(source)
        source.rename(saved)
    require(identity(saved) == record['packages'], 'Retained deployment directory changed')
    sync_dir(holder)
    sync_dir(physical)


def purge_packages(retained):
    record = package_record(retained)
    holder = PARENT / record['holder']
    if not os.path.lexists(holder):
        return
    protected(holder, True)
    require(identity(holder) == record['holderIdentity'], 'Original purge holding directory changed')
    saved = holder / 'packages'
    if os.path.lexists(saved):
        require(identity(saved) == record['packages'], 'Different deployment directory at purge')
        no_mounts_below(saved)
        shutil.rmtree(saved)
    holder.rmdir()
    sync_dir(PARENT)


def capture(retained):
    protected(retained, True)
    protected(PARENT, True)
    require(not HOME.is_symlink() or HOME.lstat().st_uid == 0, 'Public Core link is not Root owned')
    physical = HOME.resolve(strict=True)
    require(physical.parent == PARENT and (physical == HOME or physical.name.startswith('kura_')),
            'Unrecognized Core installation directory')
    protected(physical, True)
    no_mounts_below(physical)
    operation = str(uuid.UUID(json.loads((retained / 'systemd/main-state.json').read_bytes())['maintenanceId']))
    record = dict(root=identity(ROOT), parent=identity(PARENT), name=physical.name,
                  target=identity(physical), alias=identity(HOME), operation=operation,
                  retained=identity(retained), stagingName=retained.name)
    # postinst restores this file from the same relative path for upgrades and
    # retained reinstalls. The lock belongs to the current framework directory.
    framework = physical / 'framework'
    registry = framework / 'sibling-install-order'
    if os.path.lexists(framework):
        protected(framework, True)
        if os.path.lexists(registry):
            protected(registry, False)
            require(not registry.lstat().st_mode & 0o7000, 'Invalid sibling registry mode')
            saved = retained / 'framework'
            saved.mkdir(mode=0o700)
            destination = saved / registry.name
            subprocess.run(['/bin/cp', '--preserve=mode,ownership,timestamps,xattr',
                            '--no-dereference', '--', registry, destination], check=True)
            with destination.open('rb') as stream:
                os.fsync(stream.fileno())
            sync_dir(saved)
    capture_generation(physical, retained, operation)
    capture_history(physical, retained, record)
    raw = json.dumps(record, sort_keys=True).encode()
    write_new(retained / 'removal-home.json', raw)
    # An inode number can be reused after a directory is removed.
    witness = physical / ('.kura-remove-' + operation)
    if os.path.lexists(witness):
        protected(witness, False)
        require(witness.read_bytes() == raw, 'Existing removal witness belongs to different inputs')
    else:
        write_new(witness, raw)


def remove(retained):
    record_path = retained / 'removal-home.json'
    protected(record_path, False)
    protected(PARENT, True)
    raw = record_path.read_bytes()
    rec = json.loads(raw)
    operation = str(uuid.UUID(rec['operation']))
    require(operation == json.loads((retained / 'systemd/main-state.json').read_bytes())['maintenanceId']
            and rec['root'] == identity(ROOT) and rec['parent'] == identity(PARENT),
            'Different original Core removal or installation Root')
    if 'packageTag' in rec:
        bound = package_record(retained)
        holder = PARENT / bound['holder']
        if os.path.lexists(PARENT / rec['name']) or os.path.lexists(PARENT / ('.kura-removing-' + operation)):
            protected(holder, True)
            require(identity(holder) == bound['holderIdentity'] and identity(holder / 'packages') == bound['packages'],
                    'Original deployment directory was not parked before removal')
    name = rec['name']
    require(Path(name).name == name and (name == 'kura' or name.startswith('kura_')),
            'Invalid original installation name')
    target = PARENT / name
    retired = PARENT / ('.kura-removing-' + operation)
    if os.path.lexists(retired):
        require(not os.path.lexists(target) and not os.path.lexists(HOME),
                'New Core installation appeared during removal')
        protected(retired, True)
        require(identity(retired) == rec['target'], 'Retired directory changed')
    elif os.path.lexists(target):
        protected(target, True)
        require(identity(target) == rec['target'], 'Original Core directory was replaced')
        witness = target / ('.kura-remove-' + operation)
        protected(witness, False)
        require(witness.read_bytes() == raw, 'Original Core removal witness changed')
        no_mounts_below(target)
        if target != HOME and os.path.lexists(HOME):
            require(HOME.is_symlink() and identity(HOME) == rec['alias'] and HOME.resolve(strict=True) == target,
                    'Public Core link was replaced')
            HOME.unlink()
        target.rename(retired)
        sync_dir(PARENT)
    else:
        require(not os.path.lexists(HOME), 'Unexpected public Core installation')
        return
    # The private name keeps a retry away from a newly installed public directory.
    no_mounts_below(retired)
    shutil.rmtree(retired)
    sync_dir(PARENT)


if __name__ == '__main__':
    action, directory = sys.argv[1:]
    retained = Path(directory)
    if action == 'purge':
        remove(retained)
    if action in ('park-if-recorded', 'purge'):
        path = retained / 'removal-home.json'
        protected(path, False)
        if 'packageTag' in json.loads(path.read_bytes()):
            (park if action == 'park-if-recorded' else purge_packages)(retained)
    elif action == 'locate':
        print(locate_retention(retained))
    else:
        {'capture': capture, 'remove': remove}[action](retained)
