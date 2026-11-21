# SPDX-License-Identifier: EPL-2.0
"""Carry the original Core directory across dpkg's removal of the public link."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid


PARENT = Path('/opt/eclipse')
HOME = PARENT / 'kura'


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
    record = dict(root=identity(Path('/')), parent=identity(PARENT), name=physical.name,
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
            and rec['root'] == identity(Path('/')) and rec['parent'] == identity(PARENT),
            'Different original Core removal or installation Root')
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
    {'capture': capture, 'remove': remove}[action](Path(directory))
