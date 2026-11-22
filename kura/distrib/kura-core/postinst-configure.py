# SPDX-License-Identifier: EPL-2.0
"""Embedded dpkg configure phases, bound to the original key-service fence."""
import ctypes
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
import types


INSTALLER_STEPS = ('layout', 'brokers', 'runtime', 'https', 'ownership')
CONFIGURE_FILES = {'intent.json', 'prepared.json', 'ready.json', 'configured.json'} | {
    f'setup-{step}-{phase}.json' for step in INSTALLER_STEPS for phase in ('intent', 'returned', 'complete')
}


def sync_staged_filesystem(directory_fd):
    syncfs = ctypes.CDLL(None, use_errno=True).syncfs
    syncfs.argtypes = (ctypes.c_int,)
    syncfs.restype = ctypes.c_int
    if syncfs(directory_fd) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def rename_package_entry(staged, target, flags):
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    at_fdcwd = -100
    if rename(at_fdcwd, os.fsencode(staged), at_fdcwd, os.fsencode(target), flags):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


def publish_sibling(staged, target):
    rename_package_entry(staged, target, 1)  # RENAME_NOREPLACE


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
        self.api.require(not os.path.lexists(path / '.partial-payload'),
                         'Interrupted dpkg payload still needs its original unpack')
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

    def run_step(self, step, invoke, *, prepare_brokers=None):
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
            if step == 'layout' and recovery['mode'] == 'upgrade':
                self.restore_published_launchers(original, secret)
            if step == 'layout' and recovery['mode'] in ('reinstall', 'install') and os.path.lexists(policy.state / 'generation-current.json'):
                self.restore_removed_generation(original, purged=recovery['mode'] == 'install')
            if step != 'layout':
                self.paired_home()
            if step == 'brokers' and prepare_brokers is not None:
                prepare_brokers(recovery['mode'])
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

    @staticmethod
    def package_identity(path):
        info = path.lstat()
        return dict(device=info.st_dev, inode=info.st_ino)

    def removal_history(self, original, copy, secret):
        require = self.api.require
        path = copy / 'removal-home.json'
        capture = self.api.decode(self.policy.read(path, limit=4096)) if os.path.lexists(path) else {}
        if 'packageTag' not in capture:
            registry = copy / 'packages/dpa.properties'
            pattern = re.compile(r'\.dpa\.properties\.(install|uninstall)-[0-9a-f]{64}\.done')
            require(not registry.parent.is_dir() or not any(pattern.fullmatch(p.name) for p in registry.parent.iterdir()),
                    'Completed deployment history requires its original removed directory')
            return None
        tag = capture.pop('packageTag')
        expected = hmac.new(secret, b'kura-core-removal-packages-v1\0' + self.api.encoded(capture),
                            hashlib.sha256).hexdigest()
        def pair(path):
            info = path.lstat()
            return [info.st_dev, info.st_ino]
        require(hmac.compare_digest(tag, expected) and capture['operation'] == original
                and capture['root'] == pair(self.policy.root) and capture['parent'] == pair(self.physical.parent)
                and capture['retained'] == pair(copy) and capture['name'] == self.physical.name,
                'Deployment history requires its original removal Root and home')
        parked = self.physical.parent / capture['holder']
        recorded = dict(zip(('device', 'inode'), capture['packages'], strict=True))
        return parked, capture['holderIdentity'], recorded, tag

    def upgrade_capture(self, original, copy, secret):
        require = self.api.require
        identity = self.package_identity
        capture = self.api.decode(self.policy.read(copy / '.capture.json', limit=4096))
        tag = capture.pop('tag')
        expected = hmac.new(secret, b'kura-core-preinst-capture-v1\0' + self.api.encoded(capture),
                            hashlib.sha256).hexdigest()
        require(hmac.compare_digest(tag, expected) and capture['maintenanceId'] == original
                and capture['root'] == identity(self.policy.root) and capture['stage'] == identity(copy),
                'Deployment history requires the original upgrade capture')
        return capture, tag

    def unpacked_main_directory(self, logical):
        if not os.path.lexists(logical):
            return None
        if logical.is_symlink():
            self.paired_home()
            return None
        self.policy.directory(logical)
        info = logical.lstat()
        self.api.require(info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o755
                         and not any(logical.iterdir()), 'Retained reinstall found an occupied Main directory')
        label = '/opt/eclipse/kura'
        owners = subprocess.check_output(['/usr/bin/dpkg-query', '-S', label], text=True)
        self.api.require(owners.splitlines() == ['kura-core: ' + label],
                         'Retained reinstall requires a Core-owned unpack directory')
        return info

    def restore_removed_generation(self, original, *, purged=False):
        """Reconstruct the genuine vendor layout from the paired unpacked release."""
        policy, require = self.policy, self.api.require
        digest = lambda raw: hashlib.sha256(raw).hexdigest()
        retained = self.copies['reinstall']
        removal = {'__name__': 'packaged_removal'}
        exec(compile(CORE_REMOVAL_HOME_SOURCE, '<removal-home>', 'exec'), removal)
        saved = (removal['purged_generation'](original) if purged else
                 removal['retained_generation'](retained, original))
        require(saved and saved['manifestSha256'] == self.binding['manifestSha256'],
                'Retained generation requires the original reader release')
        manifest_raw = policy.read(self.physical / 'libexec/key-backup/manifest.json', private=False)
        require(digest(manifest_raw) == saved['manifestSha256'])
        manifest = self.api.decode(manifest_raw)
        generation = manifest['generation']
        def incoming(name, limit=65536):
            return policy.read(self.physical / name, limit=limit, private=False)
        for group in (manifest['files'], generation['files']):
            for name, expected in group.items():
                require(not Path(name).is_absolute() and '..' not in Path(name).parts)
                require(digest(incoming(name, 16 * 1024 * 1024)) == expected,
                        'Unpacked file differs from the retained reader release')
        def reader(name):
            path = 'bin/' + name + '.py'
            source = incoming(path, 256 * 1024)
            require(digest(source) == manifest['files'][path])
            return source
        key_policy = dict(__name__='retained_package_policy', _KURA_REMOVAL_HOME_SOURCE=CORE_REMOVAL_HOME_SOURCE,
                          _KURA_EMBEDDED_LIFECYCLE_SOURCE=reader('kura_key_service_lifecycle'),
                          _KURA_EMBEDDED_JOURNAL_SOURCE=reader('kura_key_journal'),
                          _KURA_INCOMING_KEY_MANIFEST_SHA256=saved['manifestSha256'])
        exec(compile(reader('kura_key_store'), '<incoming-key-store>', 'exec'), key_policy)
        exec(compile(CORE_RETAINED_PREFLIGHT_SOURCE, '<retained-preflight>', 'exec'), key_policy)
        require(key_policy['prepare_retained_generation'](unpacked_layout=True) == 0,
                'Original retained generation credentials changed after unpack')

        # The independent snapshot validator is part of the current signed
        # package profile. Restore its two vendor units with the other paired
        # units before generation_assets() verifies the complete layout.
        native_validation = frozenset(manifest['files']) == self.api.NATIVE_VALIDATION_ASSETS
        profile_units = self.api.NATIVE_VALIDATION_UNITS if native_validation else self.api.UNITS
        require(set(manifest['units']) == set(profile_units), 'Unpaired retained key-service unit profile')
        units = {name: incoming('install/' + name) for name in manifest['units']}
        require(all(digest(raw) == manifest['units'][name] for name, raw in units.items()))
        main = incoming('install/kura.service').replace(b'INSTALL_DIR', b'/opt/eclipse')
        require(digest(main) == generation['unitSha256'])
        units['kura.service'] = main
        cohort = {'__name__': 'incoming_cohort'}
        helper = 'bin/kura_key_cohort.py'
        code = incoming(helper)
        require(digest(code) == generation['files'][helper])
        exec(compile(code, helper, 'exec'), cohort)
        cohort['validate'](self.physical, generation, lambda p: policy.read(p, private=False), policy.owner, unit=main)
        source = removal['PURGED_GENERATIONS'] / original if purged else retained / 'published-generation'
        launchers = {}
        for name in removal['GENERATION_LAUNCHERS']:
            target = self.physical / 'bin' / name
            raw = policy.read(source / name)
            template = incoming('libexec/key-backup/launchers/' + name)
            actual = policy.read(target, private=False)
            require(actual in (template, raw), 'Unpaired launcher at retained reinstall')
            if actual != raw:
                launchers[target] = raw
        logical = policy.path('/opt/eclipse/kura')
        placeholder = self.unpacked_main_directory(logical)
        vendor = policy.path('/lib/systemd/system').resolve(strict=True)
        policy.directory(vendor)
        for name, raw in units.items():
            for prefix in ('/usr/lib', '/lib'):
                path = policy.path(prefix + '/systemd/system/' + name)
                if os.path.lexists(path):
                    require(path.parent.resolve(strict=True) == vendor and
                            policy.read(vendor / name, private=False) == raw,
                            'Unexpected vendor unit during retained reinstall')
        dropin = policy.path('/etc/systemd/system/kura.service.d/40-kura-key-generations.conf')
        if purged:
            restored_dropin = policy.read(source / 'dropin')
            require(restored_dropin == incoming('share/key-management/key-generations.conf'),
                    'Purged credential drop-in differs from the paired template')
            policy.directory(dropin.parent, private=True, create=True)
            require(not os.path.lexists(dropin) or stat.S_IMODE(dropin.lstat().st_mode) == 0o400
                    and policy.read(dropin) == restored_dropin, 'Unexpected Main drop-in after purge')

        # Write only into the genuine package destinations. Interrupted copies
        # are accepted above only if byte-identical to the paired package.
        for target, raw in launchers.items():
            with tempfile.TemporaryDirectory(dir=target.parent) as stage:
                staged = Path(stage) / target.name
                staged.write_bytes(raw)
                staged.chmod(stat.S_IMODE(target.lstat().st_mode))
                with staged.open('rb') as stream:
                    os.fsync(stream.fileno())
                os.replace(staged, target)
        policy.sync(self.physical / 'bin')
        for name, raw in units.items():
            target = vendor / name
            if not os.path.lexists(target):
                with tempfile.TemporaryDirectory(dir=vendor) as stage:
                    staged = Path(stage) / name
                    staged.write_bytes(raw)
                    staged.chmod(0o644)
                    with staged.open('rb') as stream:
                        os.fsync(stream.fileno())
                    publish_sibling(staged, target)
        policy.sync(vendor)
        if purged and not os.path.lexists(dropin):
            with tempfile.TemporaryDirectory(dir=dropin.parent) as stage:
                staged = Path(stage) / dropin.name
                staged.write_bytes(restored_dropin)
                staged.chmod(0o400)
                with staged.open('rb') as stream:
                    os.fsync(stream.fileno())
                publish_sibling(staged, dropin)
            policy.sync(dropin.parent)
        if placeholder is not None:
            require(os.path.samestat(placeholder, logical.lstat()), 'Main unpack directory changed')
            logical.rmdir()  # The kernel also rejects nonempty directories and mount points.
        if not os.path.lexists(logical):
            logical.symlink_to(self.physical)
            policy.sync(logical.parent)
        self.paired_home()
        require(policy.generation_assets()['cohortSha256'] == saved['cohortSha256'],
                'Restored vendor layout differs from the original published cohort')

    def restore_published_launchers(self, original, secret):
        policy, require = self.policy, self.api.require
        current = policy.state / 'generation-current.json'
        if not os.path.lexists(current):
            return
        self.paired_home()
        copy = self.copies['upgrade']
        capture, _ = self.upgrade_capture(original, copy, secret)
        parked = copy / '.old-home'
        require(capture['source'] == dict(name=self.physical.name, **self.package_identity(parked)),
                'Published launchers require their original upgrade home')
        policy.check_extended_journal()
        publication = self.api.validate_publication(self.api.decode(policy.read(current, 8192)))
        self.api.archive_entry(policy, dict(directory='operations', operationId=publication['operationId']), secret)
        binding = policy.generation_assets()
        require(binding['manifestSha256'] == self.binding['manifestSha256'],
                'Published launchers require a paired incoming manifest')

        # After a partial write each destination must still be either the exact
        # packaged template or the exact launcher bound to the publication.
        replacements = {}
        original_hashes = {}
        for name in binding['launcherSha256s']:
            target = self.physical / 'bin' / name
            saved = policy.read(parked / 'bin' / name, private=False)
            actual = policy.read(target, private=False)
            template = policy.read(self.physical / 'libexec/key-backup/launchers' / name, private=False)
            require(actual in (saved, template), 'Unexpected incoming published launcher')
            original_hashes[name] = hashlib.sha256(saved).hexdigest()
            if saved != actual:
                replacements[target] = saved
        original_binding = dict(binding, launcherSha256s=original_hashes)
        del original_binding['cohortSha256']
        require(hashlib.sha256(self.api.encoded(original_binding)).hexdigest() == publication['cohortSha256'],
                'Retained launchers differ from the published generation')

        # Stage inside the authenticated recovery copy on the runtime filesystem.
        # Keep the originals intact until the normal postinst retires that copy.
        with tempfile.TemporaryDirectory(prefix='.launcher-', dir=copy) as stage:
            for target, saved in replacements.items():
                info = target.lstat()
                pending = Path(stage) / target.name
                with pending.open('xb') as stream:
                    stream.write(saved)
                    stream.flush()
                    os.fchown(stream.fileno(), info.st_uid, info.st_gid)
                    os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
                    os.fsync(stream.fileno())
                os.replace(pending, target)
        policy.sync(self.physical / 'bin')
        require(policy.generation_assets()['cohortSha256'] == publication['cohortSha256'],
                'Restored launchers differ from the published generation')

    def restore_package_history(self, original, mode, secret):
        if mode not in self.copies:
            return 'COPY'
        copy = self.copies[mode]
        require = self.api.require
        identity = self.package_identity
        if mode == 'reinstall':
            history = self.removal_history(original, copy, secret)
            if history is None:
                return 'COPY'
            parked, holder_identity, recorded, tag = history
            self.policy.directory(parked, private=True)
            require(list(identity(parked).values()) == holder_identity, 'Original deployment holding directory changed')
        else:
            # Older upgrade installers may have only a staged copy.
            if not os.path.lexists(copy / '.capture.json') and not os.path.lexists(copy / '.old-home'):
                return 'COPY'
            capture, tag = self.upgrade_capture(original, copy, secret)
            if 'packageHistoryDirectory' not in capture:
                return 'COPY'
            parked = copy / '.old-home'
            self.policy.directory(parked)
            require(capture['source'] == dict(name=self.physical.name, **identity(parked)),
                    'Original deployment home differs from its upgrade capture')
            recorded = capture['packageHistoryDirectory']
        self.paired_home()
        source = parked / 'packages'
        destination = self.physical / 'packages'
        require(all(stat.S_ISDIR(path.lstat().st_mode) for path in (source, destination)),
                'Deployment package directory changed during upgrade')
        handoff = copy / '.package-history-handoff.json'
        at_destination = identity(destination) == recorded
        factory = source if at_destination else destination
        binding = dict(originalDirectory=recorded, factoryDirectory=identity(factory), captureTag=tag)
        record = self.body(original, 'package-history-handoff', binding, secret)
        if os.path.lexists(handoff):
            require(self.policy.read(handoff, limit=4096) == record, 'Original package handoff directories changed')
        else:
            require(not at_destination and identity(source) == recorded, 'Original deployment directory is missing')
            with tempfile.TemporaryDirectory(dir=copy) as temp:
                pending = Path(temp) / 'handoff'
                self.policy.create(pending, record)
                publish_sibling(pending, handoff)
            self.policy.sync(copy)
        if not at_destination:
            require(identity(source) == recorded, 'Original deployment directory was replaced')
            # Current Debian profiles ship a flat default registry and optional factory DPs.
            # A new factory member travels with the retained directory, existing site entries win.
            for entry in sorted(factory.iterdir()):
                require(entry.name in CORE_CONFIGURE_FACTORY_PACKAGES and stat.S_ISREG(entry.lstat().st_mode),
                        'Unexpected entry in incoming deployment packages')
                target = source / entry.name
                with os.fdopen(os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
                    require(hashlib.file_digest(stream, 'sha256').hexdigest() ==
                            CORE_CONFIGURE_FACTORY_PACKAGES[entry.name], 'Incoming factory package changed')
                if not os.path.lexists(target):
                    publish_sibling(entry, target)
            self.policy.sync(source)
            self.policy.sync(factory)
            rename_package_entry(source, destination, 2)  # RENAME_EXCHANGE
        self.policy.sync(parked)
        self.policy.sync(self.physical)
        require(identity(destination) == recorded, 'Original package history was not restored')
        return 'PRESERVED'

    def retire_removed_packages(self, original, copy, secret):
        history = self.removal_history(original, copy, secret)
        if history is None:
            return
        parked, holder_identity, recorded, tag = history
        destination = self.physical / 'packages'
        require = self.api.require
        require(self.package_identity(destination) == recorded, 'Different installed deployment directory at retirement')
        if os.path.lexists(parked):
            self.policy.directory(parked, private=True)
            require(list(self.package_identity(parked).values()) == holder_identity, 'Different deployment holding directory')
            factory = parked / 'packages'
            if os.path.lexists(factory):
                binding = dict(originalDirectory=recorded, factoryDirectory=self.package_identity(factory), captureTag=tag)
                require(self.policy.read(copy / '.package-history-handoff.json', limit=4096)
                        == self.body(original, 'package-history-handoff', binding, secret),
                        'Different factory directory at retirement')
                shutil.rmtree(factory)
            parked.rmdir()
        self.policy.sync(parked.parent)

    def restore_siblings(self, original, mode):
        source = self.copies[mode] / 'siblings'
        if not os.path.lexists(source):
            return
        self.api.require(stat.S_ISDIR(source.lstat().st_mode), 'Invalid preserved sibling bundle directory')
        destination = self.physical / 'siblings'
        self.policy.directory(destination)
        # The generation reader scans every JAR recursively in siblings/, including
        # hidden directories. Keep incomplete JARs outside its catalogue.
        stage = self.physical / f'.kura-restore-{original}'
        self.api.require(self.physical.stat().st_dev == destination.stat().st_dev,
                         'Sibling bundle publication requires the runtime filesystem')
        if os.path.lexists(stage):
            # Only the authenticated fence's private unpublished work is disposable.
            self.policy.directory(stage, private=True)
            shutil.rmtree(stage)
        stage.mkdir(mode=0o700)
        # Open before cp so syncfs observes writeback errors from this batch.
        stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with tempfile.TemporaryDirectory(prefix='copy-', dir=stage) as directory:
                pending = []
                for sibling in sorted(source.iterdir()):
                    if sibling.name.startswith('.') or not stat.S_ISDIR(sibling.lstat().st_mode):
                        continue
                    target = destination / sibling.name
                    if os.path.lexists(target):
                        # dpkg may have unpacked a newer package in this transaction.
                        continue
                    staged = Path(directory) / sibling.name
                    subprocess.run(['/bin/cp', '-a', '--', str(sibling), str(staged)], check=True)
                    pending.append((staged, target))
                if pending:
                    sync_staged_filesystem(stage_fd)
                    for staged, target in pending:
                        publish_sibling(staged, target)
        finally:
            os.close(stage_fd)
            stage.rmdir()
            self.policy.sync(self.physical)
            self.policy.sync(destination)

    def apply(self, action, reconcile=None):
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
                require(fence is not None and action in ('status', 'restore-packages', 'restore-siblings', 'ready'),
                        'Configure data readiness is unresolved')
                require(self.source() == recovery, 'Original configure recovery copy changed')
                if action == 'restore-packages':
                    return self.restore_package_history(original, mode, secret), mode
                if action == 'restore-siblings':
                    require(mode in self.copies, 'No preserved sibling bundles to restore')
                    self.restore_siblings(original, mode)
                if action == 'ready':
                    # The staged source may be retired as soon as READY is
                    # durable. Flush the restored runtime trees first.
                    os.sync()
                    self.publish(directory, original, 'ready', recovery, secret)
                    return 'READY', mode
                return 'PREPARED', mode
            if action in ('configured', 'sibling-code', 'configure-route'):
                require(fence is None and policy.read(ready, limit=4096) == ready_body
                        and self.source()['mode'] == 'install', 'Core configuration is still in progress')
                receipt = directory / 'configured.json'
                if not os.path.lexists(receipt):
                    if action == 'configure-route':
                        return 'CONFIGURE', mode
                    require(action == 'configured', 'Core post-install has not finished')
                    self.publish(directory, original, 'configured', recovery, secret)
                require(policy.read(receipt, limit=4096) == self.body(original, 'configured', recovery, secret),
                        'Invalid completed Core post-install receipt')
                if action == 'sibling-code':
                    reconcile()
                return 'CONFIGURED', mode
            require(policy.read(ready, limit=4096) == ready_body and action in ('status', 'retire-copy'),
                    'Invalid configure data receipt')
            existing = self.source()
            require(existing == recovery or existing['mode'] == 'install', 'Refusing a different configure recovery copy')
            if action == 'retire-copy' and existing['mode'] != 'install':
                path = self.copies[mode]
                if mode == 'reinstall':
                    self.retire_removed_packages(original, path, secret)
                shutil.rmtree(path)
                policy.sync(path.parent)
            return 'READY', mode


def check_aborted_change(marker, phases):
    # An abort callback can also run while the old release is only half configured.
    # An active fence with its own configure directory has not finished teardown.
    # This check must still work after preinst has detached the old payload.
    try:
        fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_nlink != 1
                or stat.S_IMODE(meta.st_mode) != 0o600 or not 0 < meta.st_size <= 4096):
            raise ValueError('Invalid Core maintenance fence during package abort')
        raw = stream.read(4097)
        if len(raw) != meta.st_size:
            raise ValueError('Incomplete Core maintenance fence during package abort')
    fence = json.loads(raw)
    original = fence['id']
    if (fence.get('state') != 'MAINTENANCE' or not isinstance(original, str)
            or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', original)):
        raise ValueError('Unknown Core maintenance fence during package abort')
    try:
        (phases / original).lstat()
    except FileNotFoundError:
        return
    raise ValueError('Original Core configure is still fenced; keep the package unconfigured')


def main():
    actions = {'check-abort', 'status', 'resume', 'begin', 'prepared', 'restore-packages', 'restore-siblings', 'ready', 'retire-copy',
               'configured', 'configure-route', 'sibling-code'} | {
        f'setup-{step}' for step in INSTALLER_STEPS
    }
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise ValueError('Invalid Core configure action')
    action = sys.argv[1]
    if action == 'check-abort':
        check_aborted_change(Path('/var/lib/kura-key-service/maintenance.json'), Path('/var/lib/kura-package-configure'))
        return
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

        def prepare_brokers(mode):
            # ReloadConfig later requires a live system bus, including on first install.
            # Check before account or policy changes acquire an irreversible step intent.
            if Path('/run/systemd/system').is_dir():
                subprocess.run(['/usr/bin/busctl', '--system', '--timeout=5s', '--auto-start=no', 'call',
                                'org.freedesktop.DBus', '/org/freedesktop/DBus',
                                'org.freedesktop.DBus', 'GetId'], stdout=subprocess.DEVNULL, check=True, timeout=7)
            if mode != 'upgrade':
                return
            # PID 1 may have reopened persistently enabled listeners after
            # unpack. Restore the original fences before issuing this step.
            helpers = (
                ('kura_clock_setup.py', CORE_CONFIGURE_CLOCK_SETUP_SHA),
                ('kura_reboot_setup.py', CORE_CONFIGURE_REBOOT_SETUP_SHA),
            )
            for helper, expected in helpers:
                source = policy.read(physical / 'bin' / helper, private=False)
                lifecycle.require(hashlib.sha256(source).hexdigest() == expected, 'Unpaired Core broker setup')
            for helper, _ in helpers:
                subprocess.run(['/usr/bin/python3', '-I', '-B', '/opt/eclipse/kura/bin/' + helper,
                                'reassert_quiescence'], check=True, timeout=45)

        configure.run_step(step, invoke, prepare_brokers=prepare_brokers)
        return
    def reconcile():
        helper = physical / 'bin/kura_runtime_ownership.py'
        source = policy.read(helper, private=False)
        lifecycle.require(hashlib.sha256(source).hexdigest() == CORE_CONFIGURE_OWNERSHIP_SHA,
                          'Unpaired sibling ownership policy')
        subprocess.run(['/usr/bin/python3', '-I', '-B', str(helper), '--sibling-code'], check=True)

    phase, mode = configure.apply(action, reconcile)
    print(phase, mode, physical)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        sys.stderr.write(f'Core configure refused: {error}\n')
        sys.exit(1)
