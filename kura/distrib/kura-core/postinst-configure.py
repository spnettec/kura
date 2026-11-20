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
import tempfile
import types


INSTALLER_STEPS = ('layout', 'brokers', 'runtime', 'https', 'ownership')
CONFIGURE_FILES = {'intent.json', 'prepared.json', 'ready.json'} | {
    f'setup-{step}-{phase}.json' for step in INSTALLER_STEPS for phase in ('intent', 'returned', 'complete')
}


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

    def paired_home(self):
        logical = self.policy.path('/opt/eclipse/kura')
        self.api.require(logical.is_symlink() and logical.lstat().st_uid == self.policy.owner
                         and logical.resolve(strict=True) == self.physical,
                         'Configure is not using the paired Core runtime link')

    def paired_setup(self):
        self.paired_home()
        self.policy.no_overrides()
        self.policy.generation_assets()

    def read_intent(self, directory, original):
        policy, require = self.policy, self.api.require
        policy.directory(directory, private=True)
        require({p.name for p in directory.iterdir()} <= CONFIGURE_FILES)
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
        return recovery, secret

    def publish(self, directory, original, phase, recovery, secret):
        destination = directory / f'{phase}.json'
        self.api.require(not os.path.lexists(destination), 'Configure record already exists')
        with tempfile.TemporaryDirectory(prefix=f'.{original}-', dir=self.state) as pending:
            staged = Path(pending) / destination.name
            self.policy.create(staged, self.body(original, phase, recovery, secret))
            os.rename(staged, destination)
            self.policy.sync(directory)

    def setup_state(self, directory, original, recovery, secret):
        completed = []
        issued = None
        returned = False
        gap = False
        for step in INSTALLER_STEPS:
            intent = directory / f'setup-{step}-intent.json'
            success = directory / f'setup-{step}-returned.json'
            receipt = directory / f'setup-{step}-complete.json'
            has_success = os.path.lexists(success)
            if not os.path.lexists(intent) and not os.path.lexists(receipt) and not has_success:
                gap = True
                continue
            self.api.require(not gap and os.path.lexists(intent), 'Out-of-order installer evidence')
            self.api.require(self.policy.read(intent, limit=4096) == self.body(original, f'setup-{step}-intent', recovery, secret),
                             'Invalid installer step intent')
            if has_success:
                self.api.require(self.policy.read(success, limit=4096) == self.body(original, f'setup-{step}-returned', recovery, secret),
                                 'Invalid installer success evidence')
            if not os.path.lexists(receipt):
                issued, returned = step, has_success
                gap = True
                continue
            self.api.require(self.policy.read(receipt, limit=4096) == self.body(original, f'setup-{step}-complete', recovery, secret),
                             'Invalid installer step receipt')
            completed.append(step)
        return completed, issued, returned

    def run_step(self, step, invoke):
        policy, require = self.policy, self.api.require
        require(step in INSTALLER_STEPS)
        with policy.locked():
            policy.check_records()
            fence = policy.fence()
            require(fence is not None, 'Installer step has no original fence')
            original = fence['id']
            directory = self.state / original
            recovery, secret = self.read_intent(directory, original)
            require(not os.path.lexists(directory / 'prepared.json') and not os.path.lexists(directory / 'ready.json'),
                    'Installer is already prepared')
            require(self.source() == recovery, 'Original configure recovery copy changed')
            completed, issued, _ = self.setup_state(directory, original, recovery, secret)
            require(issued is None, f'Installer step {issued} is unresolved; preserve the original intent')
            if step in completed:
                return
            require(step == INSTALLER_STEPS[len(completed)], 'Out-of-order installer step')
            policy.no_overrides()
            if step != 'layout':
                self.paired_home()
            self.publish(directory, original, f'setup-{step}-intent', recovery, secret)

        invoke()

        with policy.locked():
            require(policy.fence() == fence and self.read_intent(directory, original) == (recovery, secret)
                    and self.source() == recovery, 'Installer fence changed before receipt')
            policy.no_overrides()
            self.paired_home()
            require(self.setup_state(directory, original, recovery, secret) == (completed, step, False),
                    'Installer evidence changed before receipt')
            # Only the launcher observing the successful original invocation
            # can publish this witness. Resume never invokes an issued step.
            self.publish(directory, original, f'setup-{step}-returned', recovery, secret)

    def apply(self, action):
        policy, require = self.policy, self.api.require
        with policy.locked():
            policy.check_records()
            fence = policy.fence()
            original = fence['id'] if fence else self.head()
            directory = self.state / original
            if not os.path.lexists(directory):
                require(fence is not None and action in ('status', 'resume', 'begin'), 'Missing original configure intent')
                recovery = self.source()
                if action == 'begin':
                    policy.directory(self.state, private=True, create=True)
                    policy.sync(self.state.parent)
                    secret = policy.read(policy.state / 'journal.key', limit=32)
                    require(len(secret) == 32)
                    # Publish the original fence directory only after its intent
                    # is durable. An interruption during staging cannot look
                    # like an incomplete intent for the original fence.
                    with tempfile.TemporaryDirectory(prefix=f'.{original}-', dir=self.state) as pending:
                        pending = Path(pending)
                        policy.create(pending / 'intent.json', self.body(original, 'intent', recovery, secret))
                        os.rename(pending, directory)
                        policy.sync(self.state)
                return 'NEW', recovery['mode']
            recovery, secret = self.read_intent(directory, original)
            mode = recovery['mode']
            prepared = directory / 'prepared.json'
            ready = directory / 'ready.json'
            completed, issued, returned = self.setup_state(directory, original, recovery, secret)
            if issued is not None:
                require(action == 'resume' and returned and fence is not None,
                        f'Installer step {issued} is unresolved; preserve the original intent')
                require(not os.path.lexists(prepared) and not os.path.lexists(ready)
                        and self.source() == recovery, 'Installer evidence changed before completion')
                policy.no_overrides()
                self.paired_home()
                self.publish(directory, original, f'setup-{issued}-complete', recovery, secret)
                completed.append(issued)
            if action == 'resume':
                action = 'status'
            prepared_body = self.body(original, 'prepared', recovery, secret)
            ready_body = self.body(original, 'ready', recovery, secret)
            if not os.path.lexists(prepared):
                require(action in ('status', 'prepared') and fence is not None and not os.path.lexists(ready),
                        'Installer completion is unresolved; keep the original configure intent')
                require(self.source() == recovery, 'Original configure recovery copy changed')
                if action == 'status':
                    return 'INSTALLER', mode
                require(tuple(completed) == INSTALLER_STEPS, 'Missing completed installer steps')
                self.paired_setup()
                self.publish(directory, original, 'prepared', recovery, secret)
                return 'PREPARED', mode
            require(tuple(completed) == INSTALLER_STEPS, 'Missing completed installer steps')
            require(policy.read(prepared, limit=4096) == prepared_body, 'Invalid configure setup receipt')
            self.paired_setup()
            if not os.path.lexists(ready):
                require(fence is not None and action in ('status', 'ready'), 'Configure data readiness is unresolved')
                require(self.source() == recovery, 'Original configure recovery copy changed')
                if action == 'ready':
                    # The staged source may be retired as soon as READY is
                    # durable. Flush the restored runtime trees first.
                    os.sync()
                    self.publish(directory, original, 'ready', recovery, secret)
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
    actions = {'status', 'resume', 'begin', 'prepared', 'ready', 'retire-copy'} | {f'setup-{step}' for step in INSTALLER_STEPS}
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise ValueError('Invalid Core configure action')
    action = sys.argv[1]
    physical = Path('/opt/eclipse') / CORE_CONFIGURE_HOME
    lifecycle = load_lifecycle(physical, CORE_CONFIGURE_LIFECYCLE_SHA)
    policy = lifecycle.Lifecycle()
    manifest_sha = hashlib.sha256(policy.read(physical / 'libexec/key-backup/manifest.json', private=False)).hexdigest()
    lifecycle.require(manifest_sha == CORE_CONFIGURE_MANIFEST_SHA, 'Unpaired incoming Core configure manifest')
    installer = physical / 'install/kura_install.sh'
    if action == 'begin' or action.startswith('setup-'):
        installer_source = policy.read(installer, private=False)
        lifecycle.require(hashlib.sha256(installer_source).hexdigest() == CORE_CONFIGURE_INSTALLER_SHA,
                          'Unpaired incoming Core installer')
    control = policy.read(Path('/var/lib/dpkg/info/kura-core.postinst'), limit=512 * 1024, private=False)
    version = subprocess.check_output(['/usr/bin/dpkg-query', '-W', '-f=${Version}', 'kura-core'], text=True)
    lifecycle.require(re.fullmatch(r'[0-9][0-9A-Za-z.+:~_-]{0,199}', version))
    configure = Configure(lifecycle, policy, physical, version, manifest_sha, hashlib.sha256(control).hexdigest())
    if action.startswith('setup-'):
        step = action.removeprefix('setup-')

        def invoke():
            subprocess.run(['/bin/sh', str(installer), f'--configure-{step}'], check=True)
            os.sync()

        configure.run_step(step, invoke)
        return
    phase, mode = configure.apply(action)
    print(phase, mode, physical)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        sys.stderr.write(f'Core configure refused: {error}\n')
        sys.exit(1)
