#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Maintain the paired kurad -> kura su rule without leaving a target-free grant."""
import fcntl
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import sys

BEGIN = '# BEGIN KURA MANAGED SU POLICY'
END = '# END KURA MANAGED SU POLICY'
TARGET = 'auth [success=ignore default=1] pam_succeed_if.so user = kura'
CALLER = 'auth sufficient pam_succeed_if.so use_uid user = kurad'
ANCHOR = 'auth sufficient pam_rootok.so'
SESSION_INCLUDE = '@include common-session'
SESSION_BEGIN = '# BEGIN KURA MANAGED SU SESSION'
SESSION_END = '# END KURA MANAGED SU SESSION'
SESSION_ORIGINAL = '# KURA ORIGINAL COMMON-SESSION '
SESSION_RULES = (
    'session [success=1 default=ignore] pam_succeed_if.so use_uid user = kurad',
    'session substack common-session',
    'session [success=1 default=ignore] pam_succeed_if.so use_uid user != kurad',
    'session substack common-session-noninteractive',
)
LIMIT = 256 * 1024


class Refused(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def normalized(line):
    return re.sub(r'[ \t\r\n]+', ' ', line).strip(' \t\r\n')


def lines_of(raw):
    return [line.decode('latin-1') for line in raw.splitlines(keepends=True)]


def restore_session_block(lines):
    retained, block = [], None
    for line in lines:
        token = normalized(line)
        if token == SESSION_BEGIN:
            require(block is None, 'Nested managed su session marker')
            block = []
        elif token == SESSION_END:
            require(block is not None and len(block) == 5
                    and block[0].startswith(SESSION_ORIGINAL) and tuple(block[1:]) == SESSION_RULES,
                    'Unrecognized managed su session block')
            original = bytes.fromhex(block[0][len(SESSION_ORIGINAL):])
            require(len(original) <= 1024 and len(original.splitlines()) == 1
                    and normalized(original.decode('latin-1')) == SESSION_INCLUDE,
                    'Invalid original su session include')
            retained.append(original.decode('latin-1'))
            block = None
        elif block is not None:
            block.append(token)
        else:
            retained.append(line)
    require(block is None, 'Unterminated managed su session block')
    return retained


def render(original, operation):
    require(b'\0' not in original, 'Unsupported NUL in su policy')
    lines = restore_session_block(lines_of(original))
    require(len(lines) <= 8192, 'Too many su policy lines')
    retained = []
    block = None
    for line in lines:
        token = normalized(line)
        if token == BEGIN:
            require(block is None, 'Nested Kura su policy marker')
            block = []
        elif token == END:
            require(block is not None and block == [TARGET, CALLER], 'Unrecognized managed su policy block')
            block = None
        elif block is not None:
            block.append(token)
        elif token not in (TARGET, CALLER):
            retained.append(line)
    require(block is None, 'Unterminated Kura su policy block')
    if operation == 'install':
        anchors = [index for index, line in enumerate(retained) if normalized(line) == ANCHOR]
        require(len(anchors) == 1, 'Require one standard pam_rootok anchor')
        index = anchors[0]
        newline = '\r\n' if retained[index].endswith('\r\n') else '\n'
        if not retained[index].endswith('\n'):
            retained[index] += newline
        retained[index + 1:index + 1] = [line + newline for line in (BEGIN, TARGET, CALLER, END)]
        sessions = [index for index, line in enumerate(retained) if normalized(line) == SESSION_INCLUDE]
        require(len(sessions) == 1, 'Require one standard common-session include')
        index = sessions[0]
        raw = retained[index].encode('latin-1')
        require(len(raw) <= 1024, 'Su session include is too long')
        newline = '\r\n' if raw.endswith(b'\r\n') else '\n'
        retained[index:index + 1] = [line + newline for line in
            (SESSION_BEGIN, SESSION_ORIGINAL + raw.hex(), *SESSION_RULES, SESSION_END)]
    return ''.join(retained).encode('latin-1')


class Policy:
    def __init__(self, path=Path('/etc/pam.d/su'), owner=None):
        self.path = Path(path)
        require(self.path.is_absolute() and '..' not in self.path.parts, 'Require an absolute su policy path')
        self.owner = os.geteuid() if owner is None else owner

    @staticmethod
    def identity(metadata):
        return (metadata.st_dev, metadata.st_ino, metadata.st_uid, metadata.st_gid,
                metadata.st_mode, metadata.st_nlink, metadata.st_size,
                metadata.st_mtime_ns, metadata.st_ctime_ns)

    def read(self, directory, name, private=False):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and before.st_uid == self.owner
                    and not stat.S_IMODE(before.st_mode) & (0o7077 if private else 0o7022),
                    'Unsafe su policy file ownership, mode or link count')
            require(before.st_size <= LIMIT, 'Su policy file exceeds its limit')
            data = bytearray()
            while len(data) <= LIMIT:
                chunk = os.read(fd, LIMIT + 1 - len(data))
                if not chunk:
                    break
                data.extend(chunk)
            after = os.fstat(fd)
            current = os.stat(name, dir_fd=directory, follow_symlinks=False)
            require(len(data) == before.st_size and len(data) <= LIMIT
                    and self.identity(before) == self.identity(after) == self.identity(current),
                    'Su policy changed while reading')
            return bytes(data), before
        finally:
            os.close(fd)

    def create(self, directory, name, data, mode, group):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=directory)
        try:
            offset = 0
            while offset < len(data):
                written = os.write(fd, data[offset:])
                require(written > 0, 'Su policy publication stopped')
                offset += written
            os.fchown(fd, self.owner, group)
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)

    def session_sources(self, directory, original):
        """Refuse a noninteractive or uncontrolled include that still creates a login scope."""
        sources, active, scanned = {}, set(), set()
        def source(name):
            require(re.fullmatch(r'[A-Za-z0-9_.-]+', name) and '..' not in name,
                    'Unsupported su session include path')
            if name not in sources:
                require(len(sources) < 16, 'Too many su session sources')
                data, metadata = self.read(directory, name)
                sources[name] = (data, self.identity(metadata))
            return sources[name][0]
        def scan_file(name):
            require(name not in active, 'Cyclic su session include')
            if name in scanned:
                return
            require(len(active) < 8, 'Su session includes are too deep')
            active.add(name)
            scan_lines(lines_of(source(name)))
            active.remove(name)
            scanned.add(name)
        def scan_lines(lines, service=False):
            require(len(lines) <= 8192, 'Too many su session source lines')
            for line in lines:
                token = normalized(line)
                if not token or token.startswith('#'):
                    continue
                if token.startswith('@include'):
                    parts = token.split()
                    require(len(parts) == 2, 'Unsupported PAM include')
                    if service and token == SESSION_INCLUDE:
                        continue
                    scan_file(parts[1])
                elif re.match(r'^-?session[ \t]', token):
                    require(not token.endswith('\\'), 'Continued su session directives require review')
                    match = re.fullmatch(r'-?session\s+(\[[^\]]+\]|\S+)\s+(\S+)(?:\s+(.*))?', token)
                    require(match is not None, 'Unsupported su session directive')
                    control, module, arguments = match.groups()
                    if control in ('include', 'substack'):
                        require(not arguments, 'Unsupported PAM include arguments')
                        scan_file(module)
                    else:
                        require(Path(module).name != 'pam_systemd.so',
                                'Noninteractive su path would escape the service cgroup')
        source('common-session')  # Preserve the complete normal-caller stack.
        scan_file('common-session-noninteractive')
        scan_lines(restore_session_block(lines_of(original)), service=True)
        return sources

    def apply(self, operation):
        require(operation in ('check', 'check-installed', 'install', 'remove'), 'Unsupported su policy action')
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        lock = None
        try:
            parent = os.fstat(directory)
            require(parent.st_uid == self.owner and not stat.S_IMODE(parent.st_mode) & 0o022,
                    'Unsafe su policy directory')
            if operation not in ('check', 'check-installed'):
                lock = os.open('.kura-su-policy.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                               0o600, dir_fd=directory)
                metadata = os.fstat(lock)
                require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
                        and metadata.st_uid == self.owner and not stat.S_IMODE(metadata.st_mode) & 0o7077,
                        'Unsafe su policy lock')
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            original, metadata = self.read(directory, self.path.name)
            sources = self.session_sources(directory, original) if operation != 'remove' else {}
            replacement = render(original, 'remove' if operation == 'remove' else 'install')
            if operation == 'check-installed':
                require(replacement == original, 'Installed su session policy is missing or changed')
            if operation in ('check', 'check-installed') or replacement == original:
                return False
            digest = hashlib.sha256(original).hexdigest()
            backup = self.path.name + '.' + digest + '.kurasave'
            try:
                self.create(directory, backup, original, 0o600, metadata.st_gid)
            except FileExistsError:
                saved, _ = self.read(directory, backup, private=True)
                require(saved == original, 'Conflicting su policy backup')
            os.fsync(directory)
            temporary = '.kura-su-policy-' + secrets.token_hex(12)
            try:
                self.create(directory, temporary, replacement, stat.S_IMODE(metadata.st_mode), metadata.st_gid)
                current, identity = self.read(directory, self.path.name)
                require(current == original and self.identity(identity) == self.identity(metadata),
                        'Su policy changed before publication')
                for name, (data, identity) in sources.items():
                    current, metadata = self.read(directory, name)
                    require(current == data and self.identity(metadata) == identity,
                            'Su session dependency changed before publication')
                os.replace(temporary, self.path.name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
            return True
        finally:
            if lock is not None:
                os.close(lock)
            os.close(directory)


def main(arguments):
    try:
        require(len(arguments) == 1 and (os.geteuid() == 0 or arguments == ['check-installed']),
                'Require root for su policy updates')
        Policy(owner=0).apply(arguments[0])
        print('Kura su PAM policy ' + arguments[0] + ' accepted.')
        return 0
    except Exception:
        print('Kura su PAM policy refused; retain the policy and backups for reconciliation.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
