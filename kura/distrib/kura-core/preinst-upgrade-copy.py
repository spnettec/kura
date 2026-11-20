# SPDX-License-Identifier: EPL-2.0
"""Publish a complete upgrade source copy under the original maintenance fence."""
import ctypes
import hashlib
import hmac
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid


def rename_upgrade_copy(stage, destination):
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(destination), 1):  # AT_FDCWD, RENAME_NOREPLACE
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


class UpgradeCopy:
    def __init__(self, api, policy, control, old_version, new_version):
        self.api = api
        self.policy = policy
        self.base = policy.path('/opt/eclipse')
        self.destination = self.base / '.kura-preserve'
        self.control = control
        for version in (old_version, new_version):
            api.require(re.fullmatch(r'[0-9][0-9A-Za-z.+:~_-]{0,199}', version), 'Invalid upgrade version')
        self.versions = dict(oldVersion=old_version, newVersion=new_version)

    @staticmethod
    def identity(path):
        value = path.lstat()
        return dict(device=value.st_dev, inode=value.st_ino)

    def binding(self):
        policy, require = self.policy, self.api.require
        policy.check_records()
        policy.no_overrides()
        fence = policy.fence()
        require(fence is not None and fence['firstAction'] == 'upgrade',
                'Upgrade preservation requires its original maintenance fence')
        require(not os.path.lexists(policy.path('/var/lib/kura-retained')), 'Existing removal copy must be preserved')
        require(not os.path.lexists(policy.path('/var/lib/kura-package-configure') / fence['id']),
                'Continue the original configure instead of unpacking again')
        boot = policy.path('/proc/sys/kernel/random/boot_id').read_text().strip()
        require(str(uuid.UUID(boot)) == boot, 'Invalid running kernel boot identity')
        control_sha = hashlib.sha256(policy.read(self.control, limit=1024 * 1024, private=False)).hexdigest()
        binding = dict(schema=2, maintenanceId=fence['id'], root=self.identity(policy.root), bootId=boot,
                       preinstSha256=control_sha, **self.versions)
        secret = policy.read(policy.state / 'journal.key', limit=32)
        require(len(secret) == 32)
        return binding, secret

    def installed_source(self):
        logical = self.base / 'kura'
        physical = logical.resolve(strict=True)
        self.api.require(physical.parent == self.base and logical.lstat().st_uid == self.policy.owner,
                         'Upgrade source does not match the installed Core home')
        self.policy.directory(physical)
        alias = dict(self.identity(logical), target=os.readlink(logical) if logical.is_symlink() else None)
        return dict(source=dict(name=physical.name, **self.identity(physical)), logical=alias)

    def unpublished_binding(self):
        self.api.require(not os.path.lexists(self.destination), 'Existing recovery copy must be preserved')
        binding, secret = self.binding()
        return dict(binding, **self.installed_source()), secret

    @staticmethod
    def prefix(binding):
        return f".kura-preserve.tmp.{binding['maintenanceId']}."

    def receipt(self, stage, binding, secret):
        data = dict(binding, stage=self.identity(stage))
        data['tag'] = hmac.new(secret, b'kura-core-preinst-capture-v1\0' + self.api.encoded(data),
                               hashlib.sha256).hexdigest()
        return self.api.encoded(data)

    def attest(self, stage, binding, secret):
        self.api.require(stage.parent == self.base and
                         re.fullmatch(re.escape(self.prefix(binding)) + r'[a-z0-9_]{8}', stage.name),
                         'Unexpected upgrade staging path')
        self.policy.directory(stage, private=True)
        self.api.require(self.policy.read(stage / '.capture.json', limit=4096) == self.receipt(stage, binding, secret),
                         'Upgrade staging belongs to another source, package or Root')

    def prepare(self):
        with self.policy.locked():
            binding, secret = self.unpublished_binding()
            for prior in self.base.glob(self.prefix(binding) + '*'):
                self.policy.directory(prior, private=True)
                if os.path.lexists(prior / '.capture.json'):
                    self.attest(prior, binding, secret)
                    shutil.rmtree(prior)
            stage = Path(tempfile.mkdtemp(prefix=self.prefix(binding), dir=self.base))
            pending = stage / '.capture.pending'
            self.policy.create(pending, self.receipt(stage, binding, secret))
            pending.rename(stage / '.capture.json')
            self.policy.sync(stage)
            self.policy.sync(self.base)
            return stage

    def publish(self, stage):
        with self.policy.locked():
            binding, secret = self.unpublished_binding()
            self.attest(stage, binding, secret)
            os.sync()
            rename_upgrade_copy(stage, self.destination)
            self.policy.sync(self.base)

    def published_source(self):
        policy, require = self.policy, self.api.require
        binding, secret = self.binding()
        policy.directory(self.destination, private=True)
        raw = policy.read(self.destination / '.capture.json', limit=4096)
        saved = self.api.decode(raw)
        source, alias = saved['source'], saved['logical']
        expected = dict(binding, source=source, logical=alias)
        require(hmac.compare_digest(raw, self.receipt(self.destination, expected, secret)),
                'Published upgrade copy belongs to another source, package, boot or Root')
        for credential, limit in (('kura_encryption_key', 32), ('provisioned.json', 4096)):
            saved_credential = policy.read(self.destination / 'encryption' / credential, limit=limit)
            installed = policy.read(policy.path('/etc/kura/credentials') / credential, limit=limit)
            require(saved_credential == installed, 'Published copy differs from the installed encryption credential')
        name = source['name']
        require(name == 'kura' or re.fullmatch(r'kura_[A-Za-z0-9.+~_-]+', name), 'Invalid original Core home')
        live = self.base / name
        parked = self.destination / '.old-home'
        require(os.path.lexists(live) != os.path.lexists(parked), 'Original Core home is missing or ambiguous')
        original = live if os.path.lexists(live) else parked
        policy.directory(original)
        require(dict(name=name, **self.identity(original)) == source, 'Original Core home was replaced')
        if name != 'kura':
            logical = self.base / 'kura'
            require(logical.is_symlink() and logical.lstat().st_uid == policy.owner
                    and alias == dict(self.identity(logical), target=os.readlink(logical)),
                    'Original Core runtime link changed')
        if policy.path('/run/systemd/system').is_dir():
            output = policy.command(['show', 'kura.service', '--property=ActiveState',
                                     '--property=MainPID', '--property=ControlPID'])
            require(set(output.splitlines()) == {'ActiveState=inactive', 'MainPID=0', 'ControlPID=0'},
                    'Main must be stopped under the original maintenance fence')
        return live, parked, original

    def arrange_source(self, *, restore):
        with self.policy.locked():
            live, parked, original = self.published_source()
            target = live if restore else parked
            if original != target:
                # Move the whole original tree. A retry can use the same files
                # for the ordinary package checks even if unpack never began.
                rename_upgrade_copy(original, target)
            self.policy.sync(self.destination)
            self.policy.sync(self.base)


def run_upgrade_copy(api, policy, arguments):
    action, control, old_version, new_version, *extra = arguments
    api.require(os.environ.get('DPKG_MAINTSCRIPT_NAME') == 'preinst'
                and os.environ.get('DPKG_MAINTSCRIPT_PACKAGE') == 'kura-core',
                'Upgrade preservation requires the package preinst')
    capture = UpgradeCopy(api, policy, Path(control), old_version, new_version)
    if action == '--prepare-upgrade-copy' and not extra:
        print(capture.prepare())
    elif action == '--publish-upgrade-copy' and len(extra) == 1:
        capture.publish(Path(extra[0]))
    elif action in ('--restore-upgrade-source', '--detach-upgrade-source') and not extra:
        capture.arrange_source(restore=action == '--restore-upgrade-source')
    else:
        raise api.Refused('Unsupported upgrade preservation action')
