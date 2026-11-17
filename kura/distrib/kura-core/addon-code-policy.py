#!/usr/bin/env python3
# Copyright (c) 2026 YOFC IOT and others
# SPDX-License-Identifier: EPL-2.0
"""Preserve Root-owned sibling code separately from mutable runtime data.

Embedded in incoming package hooks: an old installation need not provide this
reader. No gateway credential, journal, configuration or network write is used.
"""
import ctypes
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
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
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, 'renameat2', None)
        if rename is None:
            raise RuntimeError('Atomic no-replace directory publication is required')
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(temporary), -100, os.fsencode(destination), 1):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(destination))
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


def main(arguments):
    if len(arguments) != 3:
        raise RuntimeError('Invalid sibling code arguments')
    action, left, right = arguments
    source, destination = Path(left), Path(right)
    installed = Path('/opt/eclipse/kura/libexec/addons')
    recovery = re.compile(r'(?:/opt/eclipse/\.kura-preserve|/var/lib/kura-retained|/var/lib/\.kura-retained\.tmp\.[A-Za-z0-9]+)/libexec/addons')
    if not ((action == 'preserve' and source == installed and recovery.fullmatch(right))
            or (action == 'restore' and destination == installed and recovery.fullmatch(left))):
        raise RuntimeError('Sibling code paths are outside package lifecycle scope')
    transfer(action, source, destination)


if __name__ == '__main__':
    main(sys.argv[1:])
