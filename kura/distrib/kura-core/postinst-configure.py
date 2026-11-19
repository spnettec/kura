# SPDX-License-Identifier: EPL-2.0
"""Embedded dpkg configure phases, bound to the original key-service fence."""
import hashlib
import hmac
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import types


def load_lifecycle(physical, expected):
    path = physical / 'bin/kura_key_service_lifecycle.py'
    for parent in reversed(path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Unsafe Core configure source directory')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o7022:
            raise ValueError('Unsafe Core configure source')
        source = stream.read(256 * 1024)
    if hashlib.sha256(source).hexdigest() != expected:
        raise ValueError('Unpaired Core configure source')
    module = types.ModuleType('kura_key_service_lifecycle')
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


class Configure:
    def __init__(self, api, policy, physical, version, manifest_sha, control_sha):
        self.api = api
        self.policy = policy
        self.physical = physical
        self.binding = dict(schema=1, packageVersion=version, manifestSha256=manifest_sha, postinstSha256=control_sha)
        self.state = policy.path('/var/lib/kura-package-configure')
        self.copies = {'upgrade': policy.path('/opt/eclipse/.kura-preserve'),
                       'reinstall': policy.path('/var/lib/kura-retained')}

    def head(self):
        history = self.policy.state / 'package-history'
        self.policy.directory(history, private=True)
        receipts = [self.api.validate_maintenance(self.api.decode(self.policy.read(p)), p.stem)
                    for p in history.iterdir()]
        parents = {p['previousMaintenanceId'] for p in receipts}
        heads = [p for p in receipts if p['maintenanceId'] not in parents]
        self.api.require(len(heads) == 1, 'Configure has no unique original package history')
        head = heads[0]
        by_id = {item['maintenanceId']: item for item in receipts}
        cursor = head['maintenanceId']
        seen = set()
        while cursor is not None:
            self.api.require(cursor in by_id and cursor not in seen, 'Invalid original package history')
            seen.add(cursor)
            cursor = by_id[cursor]['previousMaintenanceId']
        self.api.require(seen == by_id.keys(), 'Invalid original package history')
        self.api.require(head['manifestSha256'] == self.binding['manifestSha256'], 'Configure package history differs')
        return head['maintenanceId']

    def source(self):
        present = [(mode, path) for mode, path in self.copies.items() if os.path.lexists(path)]
        self.api.require(len(present) <= 1, 'Ambiguous Core configure recovery copies')
        if not present:
            return dict(mode='install', device=None, inode=None)
        (mode, path), = present
        self.policy.directory(path, private=True)
        info = path.lstat()
        return dict(mode=mode, device=info.st_dev, inode=info.st_ino)

    def body(self, original, kind, data, secret):
        result = dict(self.binding, maintenanceId=original, phase=kind, recovery=data)
        result['tag'] = hmac.new(secret, b'kura-core-postinst-v1\0' + self.api.encoded(result), hashlib.sha256).hexdigest()
        return self.api.encoded(result)

    def paired_setup(self):
        logical = self.policy.path('/opt/eclipse/kura')
        self.api.require(logical.is_symlink() and logical.resolve(strict=True) == self.physical,
                         'Configure is not using the paired Core runtime link')
        self.policy.no_overrides()
        self.policy.generation_assets()

    def apply(self, action):
        policy, require = self.policy, self.api.require
        with policy.locked():
            policy.check_records()
            fence = policy.fence()
            original = fence['id'] if fence else self.head()
            directory = self.state / original
            if not os.path.lexists(directory):
                require(fence is not None and action in ('status', 'begin'), 'Missing original configure intent')
                recovery = self.source()
                if action == 'begin':
                    policy.directory(self.state, private=True, create=True)
                    policy.directory(directory, private=True, create=True)
                    policy.sync(self.state)
                    policy.sync(self.state.parent)
                    secret = policy.read(policy.state / 'journal.key', limit=32)
                    require(len(secret) == 32)
                    policy.create(directory / 'intent.json', self.body(original, 'intent', recovery, secret))
                return 'NEW', recovery['mode']
            policy.directory(directory, private=True)
            require({p.name for p in directory.iterdir()} <= {'intent.json', 'prepared.json', 'ready.json'})
            secret = policy.read(policy.state / 'journal.key', limit=32)
            require(len(secret) == 32)
            raw = policy.read(directory / 'intent.json', limit=4096)
            recovery = self.api.decode(raw)['recovery']
            require(type(recovery) is dict and set(recovery) == {'mode', 'device', 'inode'})
            mode = recovery['mode']
            require((mode == 'install' and recovery['device'] is None and recovery['inode'] is None)
                    or (mode in self.copies and all(type(recovery[k]) is int and recovery[k] > 0
                                                   for k in ('device', 'inode'))))
            require(raw == self.body(original, 'intent', recovery, secret), 'Configure intent belongs to another package or Root')
            prepared = directory / 'prepared.json'
            ready = directory / 'ready.json'
            prepared_body = self.body(original, 'prepared', recovery, secret)
            ready_body = self.body(original, 'ready', recovery, secret)
            if not os.path.lexists(prepared):
                require(action == 'prepared' and fence is not None and not os.path.lexists(ready),
                        'Installer completion is unresolved; keep the original configure intent')
                self.paired_setup()
                require(self.source() == recovery, 'Original configure recovery copy changed')
                policy.create(prepared, prepared_body)
                return 'PREPARED', mode
            require(policy.read(prepared, limit=4096) == prepared_body, 'Invalid configure setup receipt')
            self.paired_setup()
            if not os.path.lexists(ready):
                require(fence is not None and action in ('status', 'ready'), 'Configure data readiness is unresolved')
                require(self.source() == recovery, 'Original configure recovery copy changed')
                if action == 'ready':
                    policy.create(ready, ready_body)
                    return 'READY', mode
                return 'PREPARED', mode
            require(policy.read(ready, limit=4096) == ready_body and action in ('status', 'retire-copy'),
                    'Invalid configure data receipt')
            existing = self.source()
            require(existing == recovery or existing['mode'] == 'install', 'Refusing a different configure recovery copy')
            if action == 'retire-copy' and existing['mode'] != 'install':
                path = self.copies[mode]
                shutil.rmtree(path)
                policy.sync(path.parent)
            return 'READY', mode


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in ('status', 'begin', 'prepared', 'ready', 'retire-copy'):
        raise ValueError('Invalid Core configure action')
    physical = Path('/opt/eclipse') / CORE_CONFIGURE_HOME
    lifecycle = load_lifecycle(physical, CORE_CONFIGURE_LIFECYCLE_SHA)
    policy = lifecycle.Lifecycle()
    manifest_sha = hashlib.sha256(policy.read(physical / 'libexec/key-backup/manifest.json', private=False)).hexdigest()
    lifecycle.require(manifest_sha == CORE_CONFIGURE_MANIFEST_SHA, 'Unpaired incoming Core configure manifest')
    if sys.argv[1] == 'begin':
        installer = policy.read(physical / 'install/kura_install.sh', private=False)
        lifecycle.require(hashlib.sha256(installer).hexdigest() == CORE_CONFIGURE_INSTALLER_SHA,
                          'Unpaired incoming Core installer')
    control = policy.read(Path('/var/lib/dpkg/info/kura-core.postinst'), limit=512 * 1024, private=False)
    version = subprocess.check_output(['/usr/bin/dpkg-query', '-W', '-f=${Version}', 'kura-core'], text=True)
    lifecycle.require(re.fullmatch(r'[0-9][0-9A-Za-z.+:~_-]{0,199}', version))
    phase, mode = Configure(lifecycle, policy, physical, version, manifest_sha, hashlib.sha256(control).hexdigest()).apply(sys.argv[1])
    print(phase, mode, physical)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        sys.stderr.write(f'Core configure refused: {error}\n')
        sys.exit(1)
