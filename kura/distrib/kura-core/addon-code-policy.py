#!/usr/bin/env python3
# Copyright (c) 2026 YOFC IOT and others
# SPDX-License-Identifier: EPL-2.0
"""Preserve Root-owned sibling code separately from mutable runtime data.

Embedded in incoming package hooks: an old installation need not provide this
reader. No gateway credential, journal, configuration or network write is used.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile


def protected(value, directory=False):
    if value.st_uid != 0 or value.st_mode & 0o022:
        raise RuntimeError('Sibling code is not protected Root code')
    if directory:
        if not stat.S_ISDIR(value.st_mode):
            raise RuntimeError('Sibling code directory changed type')
    elif not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise RuntimeError('Sibling code must be a regular file with one link')


def ancestors(path):
    for entry in reversed((path, *path.parents)):
        if not os.path.lexists(entry):
            continue
        value = entry.lstat()
        if stat.S_ISLNK(value.st_mode) and entry == Path('/opt/eclipse/kura'):
            target = entry.resolve(strict=True)
            if value.st_uid != 0 or target.parent != entry.parent or not target.name.startswith('kura_'):
                raise RuntimeError('Unsafe Core home symlink')
            ancestors(target)
        else:
            protected(value, directory=True)


def fingerprint(root):
    protected(root.lstat(), directory=True)
    result = {}
    for path in [root, *sorted(root.rglob('*'))]:
        value = path.lstat()
        directory = stat.S_ISDIR(value.st_mode)
        protected(value, directory=directory)
        digest = None
        if not directory:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as source:
                opened = os.fstat(source.fileno())
                protected(opened)
                if (opened.st_dev, opened.st_ino) != (value.st_dev, value.st_ino):
                    raise RuntimeError('Sibling code changed while reading')
                hasher = hashlib.sha256()
                while chunk := source.read(65536):
                    hasher.update(chunk)
                digest = hasher.hexdigest()
        result[str(path.relative_to(root))] = (directory, value.st_uid, value.st_gid,
                                               stat.S_IMODE(value.st_mode), digest)
    return result


def rename_new(temporary, destination):
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise RuntimeError('Atomic no-replace publication is required')
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(temporary), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def publish(source, destination):
    ancestors(source)
    ancestors(destination.parent)
    before = fingerprint(source)
    if os.path.lexists(destination):
        raise RuntimeError('Preserve the existing sibling code destination')
    # Keep incomplete copies private and never expose a partially copied addon.
    temporary = Path(tempfile.mkdtemp(prefix='.addon-code-copy-', dir=destination.parent))
    try:
        shutil.copytree(source, temporary, dirs_exist_ok=True, symlinks=True)
        for relative, (directory, uid, gid, mode, _) in before.items():
            path = temporary / relative
            value = path.lstat()
            if stat.S_ISLNK(value.st_mode):
                raise RuntimeError('Sibling code changed to a symlink while copying')
            os.chown(path, uid, gid, follow_symlinks=False)
            path.chmod(mode)
            if not directory:
                with path.open('rb') as stream:
                    os.fsync(stream.fileno())
        if fingerprint(temporary) != before or fingerprint(source) != before:
            raise RuntimeError('Sibling code changed during preservation')
        for path in reversed([temporary, *sorted(p for p in temporary.rglob('*') if p.is_dir())]):
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        rename_new(temporary, destination)
        fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def transfer(action, source, destination):
    if os.geteuid() != 0 or action not in {'preserve', 'restore'}:
        raise RuntimeError('Invalid privileged sibling code action')
    ancestors(source.parent)
    if not os.path.lexists(source):
        return
    fingerprint(source)  # Validate the whole input before publishing any child.
    ancestors(destination.parent)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    ancestors(destination.parent)
    if action == 'preserve':
        publish(source, destination)
        return
    if not os.path.lexists(destination):
        destination.mkdir(mode=0o755)
    ancestors(destination)
    fingerprint(destination)
    for addon in sorted(source.iterdir()):
        if not addon.is_dir() or not re.fullmatch('[a-z0-9][a-z0-9-]{0,62}', addon.name):
            raise RuntimeError('Unexpected preserved addon code directory')
        target = destination / addon.name
        # dpkg may already have unpacked a newer version of this whole addon.
        # Never merge old files back into it, including deleted old callbacks.
        if os.path.lexists(target):
            fingerprint(target)
            continue
        publish(addon, target)


FIREWALL = Path('/opt/eclipse/kura/bin/firewall')


def registered_launcher_digest():
    def query(*args):
        return subprocess.check_output(['/usr/bin/dpkg-query', '--admindir=/var/lib/dpkg', *args],
                                       text=True, env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'})

    packages = query('-W', '-f=${Package} ${db:Status-Status}\n')
    owners = []
    for record in packages.splitlines():
        package, status = record.split()
        if package not in {'kura-networking', 'kura-firewall-only'} or status in {'config-files', 'not-installed'}:
            continue
        if str(FIREWALL) not in query('-L', package).splitlines():
            continue  # Older layouts may not own this path.
        checksums = query('--control-show', package, 'md5sums')
        matches = [line.split()[0] for line in checksums.splitlines()
                   if line.split(maxsplit=1)[1:] == [str(FIREWALL.relative_to('/'))]]
        if len(matches) != 1 or not re.fullmatch('[a-f0-9]{32}', matches[0]):
            raise RuntimeError('Firewall launcher has no unique registered checksum')
        owners.extend(matches)
    if len(owners) > 1:
        raise RuntimeError('Firewall launcher has multiple registered providers')
    return owners[0] if owners else None


def launcher_payload(path, digest):
    ancestors(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        value = os.fstat(fd)
        protected(value)
        raw = stream.read()
        if not value.st_mode & stat.S_IXUSR or hashlib.md5(raw, usedforsecurity=False).hexdigest() != digest:
            raise RuntimeError('Firewall launcher differs from the registered package')
        return raw, value


def transfer_launcher(action, source, destination, digest):
    if digest is None:
        return  # Do not restore code from a removed provider.
    if action == 'restore' and os.path.lexists(destination):
        launcher_payload(destination, digest)  # A jointly unpacked provider takes precedence.
        return
    raw, metadata = launcher_payload(source, digest)
    ancestors(destination.parent)
    destination.parent.mkdir(exist_ok=True, mode=0o700)
    ancestors(destination.parent)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.firewall-copy-', delete=False) as tmp:
        temporary = Path(tmp.name)
        try:
            tmp.write(raw)
            tmp.flush()
            os.fchown(tmp.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(tmp.fileno(), stat.S_IMODE(metadata.st_mode))
            os.fsync(tmp.fileno())
            rename_new(temporary, destination)
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)


SKIN = Path('/opt/eclipse/kura/console/skin')


def gwt_skin_registration():
    packages = subprocess.check_output(['/usr/bin/dpkg-query', '-W', '-f=${Package}\n'], text=True)
    if 'kura-management-ui' not in packages.splitlines():
        return dict(files={}, version=None, state=None, generation=None)
    raw = subprocess.check_output(['/usr/bin/dpkg-query', '-W', '-f=${Version}\n${db:Status-Status}\n${Conffiles}',
                                   'kura-management-ui'], text=True)
    version, state, conffiles = raw.split('\n', 2)
    files = {}
    for line in conffiles.splitlines():
        path, digest = line.strip().removesuffix(' obsolete').rsplit(' ', 1)
        if Path(path).is_relative_to(SKIN):
            name = Path(path).relative_to(SKIN)
            if '..' in name.parts or str(name) in files:
                raise RuntimeError('Invalid GWT conffile registration')
            files[str(name)] = digest
    listing = Path('/var/lib/dpkg/info/kura-management-ui.list')
    generation = None
    if os.path.lexists(listing):
        value = listing.lstat()
        protected(value)
        generation = [value.st_dev, value.st_ino, value.st_ctime_ns]
    return dict(files=files, version=version, state=state, generation=generation)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def merge_skin(staged, destination):
    # Both complete trees have been checked. Publish only missing nodes; a retry
    # compares already published files before continuing with the remainder.
    if not os.path.lexists(destination):
        rename_new(staged, destination)
        sync_directory(destination.parent)
        return
    for child in sorted(staged.iterdir()):
        target = destination / child.name
        if not os.path.lexists(target) or child.is_dir():
            merge_skin(child, target)


def transfer_skin(action, source, destination):
    ancestors(source.parent)
    if not os.path.lexists(source):
        return  # Includes retained directories made before skin capture existed.
    saved = fingerprint(source)
    if any(entry[3] & 0o7000 for entry in saved.values()):
        raise RuntimeError('Unexpected special permission in the console skin')
    registration = gwt_skin_registration()
    ancestors(destination.parent)
    destination.parent.mkdir(parents=True, mode=0o750, exist_ok=True)
    ancestors(destination.parent)
    record_name = 'gwt-conffiles.json'
    if action == 'preserve':
        publish(source, destination)
        with (destination.parent / record_name).open('x', encoding='utf-8') as record:
            os.fchmod(record.fileno(), 0o600)
            json.dump(registration, record, sort_keys=True)
            record.flush()
            os.fsync(record.fileno())
        sync_directory(destination.parent)
        return

    record = source.parent / record_name
    protected(record.lstat())
    captured = json.loads(record.read_bytes())
    incoming = fingerprint(destination) if os.path.lexists(destination) else {}
    changed = (captured['generation'], captured['version']) != (registration['generation'], registration['version'])
    omit = []
    for name, entry in saved.items():
        current = incoming.get(name)
        if current is not None and current[0] != entry[0]:
            raise RuntimeError('Console skin file type conflicts with the incoming installation')
        if entry[0]:
            continue
        old_digest = captured['files'].get(name)
        if old_digest is not None and name not in registration['files']:
            if registration['state'] in (None, 'not-installed'):
                omit.append(name)  # A purge explicitly removed GWT's conffiles.
                continue
            with (source / name).open('rb') as stream:
                retired_default = hashlib.file_digest(stream, lambda: hashlib.md5(usedforsecurity=False)).hexdigest()
            if retired_default == old_digest:
                omit.append(name)
                continue
            old_digest = None  # A retired, locally edited conffile is site data.
        if current is not None and current[-1] == entry[-1]:
            continue
        if old_digest is not None and changed:
            # dpkg retains conffiles on remove. During joint unpack its pending
            # .dpkg-new still needs the local bytes for the configure decision.
            pending = name + '.dpkg-new' in incoming and registration['state'] in ('unpacked', 'half-configured')
            if current is None and (pending or registration['state'] == 'config-files'):
                continue
            with (source / name).open('rb') as stream:
                vendor = hashlib.file_digest(stream, lambda: hashlib.md5(usedforsecurity=False)).hexdigest()
            native_backup = incoming.get(name + '.dpkg-old')
            if vendor == old_digest or (native_backup and native_backup[-1] == entry[-1]):
                omit.append(name)  # Honor dpkg's new bytes or deliberate absence.
                continue
            raise RuntimeError('GWT conffile changed during Core maintenance; retain both generations: ' + name)
        if current is not None:
            raise RuntimeError('Site skin conflicts with incoming content; retain the recovery copy: ' + name)

    if not incoming and len(omit) == len(saved) - 1 and (omit or (captured['files'] and not registration['files'])):
        return
    # Stage outside the public runtime so an interrupted copy cannot be served
    # as a skin file. The private recovery source remains until Core is ready.
    with tempfile.TemporaryDirectory(dir=destination.parents[2], prefix='.kura-skin-') as directory:
        staged = Path(directory) / 'skin'
        publish(source, staged)
        if fingerprint(staged) != saved or (fingerprint(destination) if os.path.lexists(destination) else {}) != incoming:
            raise RuntimeError('Console skin changed during restore')
        for name in omit:
            file = staged / name
            file.unlink()
            sync_directory(file.parent)
        merge_skin(staged, destination)
        restored = fingerprint(destination)
        for name, entry in saved.items():
            if name not in omit and (name not in restored or restored[name][-1] != entry[-1]):
                raise RuntimeError('Console skin restoration incomplete: ' + name)
        sync_directory(destination.parent)


def main(arguments):
    if len(arguments) != 3:
        raise RuntimeError('Invalid sibling code arguments')
    action, left, right = arguments
    source, destination = Path(left), Path(right)
    installed = Path('/opt/eclipse/kura/libexec/addons')
    recovery = re.compile(r'(?:/opt/eclipse/\.kura-preserve|/var/lib/kura-retained|/var/lib/\.kura-retained\.tmp\.[A-Za-z0-9]+)/libexec/addons')
    capture = re.compile(r'/opt/eclipse/\.kura-preserve\.tmp\.[0-9a-f-]{36}\.[a-z0-9_]{8}/libexec/addons')
    if not ((action == 'preserve' and source == installed and (recovery.fullmatch(right) or capture.fullmatch(right)))
            or (action == 'restore' and destination == installed and recovery.fullmatch(left))):
        raise RuntimeError('Sibling code paths are outside package lifecycle scope')
    transfer(action, source, destination)
    transfer_skin(action, source.parents[1] / 'console/skin', destination.parents[1] / 'console/skin')
    transfer_launcher(action, source.parents[1] / 'bin/firewall', destination.parents[1] / 'bin/firewall',
                      registered_launcher_digest())
    # preinst already stages sibling bundles during upgrades. prerm also needs
    # them for a retained reinstall, even if the site ships no maintenance hooks.
    staging = destination.parents[1]
    if action == 'preserve' and staging.name.startswith('.kura-retained.tmp.'):
        transfer(action, source.parents[1] / 'siblings', staging / 'siblings')


if __name__ == '__main__':
    main(sys.argv[1:])
