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


def removal_tag(record):
    protected(JOURNAL_KEY, False)
    require(JOURNAL_KEY.stat().st_mode & 0o077 == 0, 'Unsafe removal journal key')
    key = JOURNAL_KEY.read_bytes()
    require(len(key) == 32, 'Invalid removal journal key')
    payload = json.dumps(record, sort_keys=True, separators=(',', ':')).encode('ascii')
    return hmac.new(key, b'kura-core-removal-packages-v1\0' + payload, hashlib.sha256).hexdigest()


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
                  target=identity(physical), alias=identity(HOME), operation=operation)
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
    else:
        {'capture': capture, 'remove': remove, 'check-resume': paired_removal}[action](retained)
