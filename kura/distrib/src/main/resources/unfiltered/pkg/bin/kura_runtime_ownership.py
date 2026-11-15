#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Separate installed root code from Kura's mutable data without replacing files."""
import fcntl
import grp
import os
from pathlib import Path
import pwd
import stat
import sys

MUTABLE = frozenset(('user', 'data', 'packages', 'log', '.data'))


class Refused(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise Refused(message)


def code_reader_group(account):
    try:
        control = grp.getgrnam('kura-key-control')
    except KeyError:
        return account.pw_gid  # Previous package, before recovery setup runs.
    recovery = pwd.getpwnam('kura-key-recovery')
    require(control.gr_gid not in (0, account.pw_gid, recovery.pw_gid)
            and recovery.pw_uid not in (0, account.pw_uid)
            and set(control.gr_mem) == {'kurad', 'kura-key-recovery'},
            'Unexpected runtime code-reader/control group')
    return control.gr_gid


class Ownership:
    def __init__(self, home, daemon_uid, daemon_gid, code_uid=0, code_gid=None):
        self.home = Path(home)
        self.daemon_uid, self.daemon_gid = daemon_uid, daemon_gid
        self.code_uid, self.code_gid = code_uid, daemon_gid if code_gid is None else code_gid

    @staticmethod
    def identity(metadata):
        return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_uid,
                metadata.st_gid, metadata.st_nlink, metadata.st_size,
                metadata.st_mtime_ns, metadata.st_ctime_ns)

    def plan(self, code_only=False):
        require(self.home.is_absolute() and '..' not in self.home.parts
                and not self.home.is_symlink() and self.home.is_dir(), 'Unsafe physical runtime directory')
        plan = []
        for path in [self.home, *sorted(self.home.rglob('*'))]:
            relative = path.relative_to(self.home)
            mutable = bool(relative.parts and relative.parts[0] in MUTABLE)
            if code_only and mutable and len(relative.parts) > 1:
                continue
            metadata = path.lstat()
            if len(relative.parts) == 1 and mutable:
                require(stat.S_ISDIR(metadata.st_mode), 'Mutable runtime root must be a real directory')
            if stat.S_ISLNK(metadata.st_mode):
                require(mutable and len(relative.parts) > 1, 'Unexpected code or mutable-root symlink')
                mode = None
            elif stat.S_ISDIR(metadata.st_mode):
                mode = 0o700 if mutable else 0o750
            else:
                require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
                        and not stat.S_IMODE(metadata.st_mode) & 0o7000,
                        'Unsafe runtime file type, hard link or special mode')
                mode = (0o600 if mutable else 0o640) | (0o100 if metadata.st_mode & 0o100 else 0)
                if not mutable and mode & 0o100:
                    mode |= 0o010
            uid, gid = ((self.daemon_uid, self.daemon_gid) if mutable else (self.code_uid, self.code_gid))
            plan.append((path, self.identity(metadata), uid, gid, mode))
        return plan

    def apply(self, code_only=False):
        # Validate the complete tree before the first ownership or mode change.
        plan = self.plan(code_only=True) if code_only else self.plan()
        framework = self.home / 'framework'
        require(framework.is_dir() and not framework.is_symlink(), 'Missing installed framework directory')
        registry = framework / 'sibling-install-order'
        if not registry.exists():
            fd = os.open(registry, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o640)
            try:
                os.fchown(fd, self.code_uid, self.code_gid)
                os.fchmod(fd, 0o640)
                os.fsync(fd)
            finally:
                os.close(fd)
        for name in MUTABLE:
            path = self.home / name
            if not path.exists():
                path.mkdir(mode=0o700)
                os.chown(path, self.daemon_uid, self.daemon_gid, follow_symlinks=False)
        plan = self.plan(code_only=True) if code_only else self.plan()
        changed = 0
        for path, identity, uid, gid, mode in plan:
            relative = path.relative_to(self.home)
            if code_only and relative.parts and relative.parts[0] in MUTABLE:
                continue
            metadata = path.lstat()
            require(self.identity(metadata) == identity, 'Runtime changed before ownership update')
            if stat.S_ISLNK(metadata.st_mode):
                if (metadata.st_uid, metadata.st_gid) != (uid, gid):
                    os.chown(path, uid, gid, follow_symlinks=False)
                    changed += 1
                continue
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if stat.S_ISDIR(metadata.st_mode):
                flags |= os.O_DIRECTORY
            fd = os.open(path, flags)
            try:
                require(self.identity(os.fstat(fd)) == identity, 'Runtime node changed before ownership update')
                update_owner = (metadata.st_uid, metadata.st_gid) != (uid, gid)
                update_mode = stat.S_IMODE(metadata.st_mode) != mode
                if update_owner:
                    os.fchown(fd, uid, gid)
                if update_mode:
                    os.fchmod(fd, mode)
                changed += update_owner or update_mode
            finally:
                os.close(fd)
        return changed


def main(arguments):
    try:
        require(os.geteuid() == 0 and arguments in ([], ['--code-only']), 'Require the root package installer')
        account = pwd.getpwnam('kurad')
        link = Path('/opt/eclipse/kura')
        require(link.is_symlink(), 'Require the installed canonical runtime link')
        home = link.resolve(strict=True)
        require(home.parent == Path('/opt/eclipse') and home.name.startswith('kura_'),
                'Unexpected installed runtime target')
        root = Path('/opt/eclipse')
        require(root.stat().st_uid == 0 and not root.stat().st_mode & 0o022,
                'Unsafe installation parent')
        # Keep the package lock outside all daemon-writable trees.
        lock = os.open(root / '.kura-ownership.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                       0o600)
        try:
            metadata = os.fstat(lock)
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and metadata.st_uid == 0
                    and not stat.S_IMODE(metadata.st_mode) & 0o7077, 'Unsafe ownership lock')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code_gid = code_reader_group(account)
            # Both roles can read public root-owned code. Mutable data remains
            # private to kurad; canonical credentials remain outside this tree.
            Ownership(home, account.pw_uid, account.pw_gid, code_gid=code_gid).apply(code_only=bool(arguments))
        finally:
            os.close(lock)
        print('Kura root code and private runtime data ownership accepted.')
        return 0
    except Exception:
        print('Kura ownership update refused; retain all runtime data and reconcile the layout.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
