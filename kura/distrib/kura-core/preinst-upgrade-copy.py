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
        require(not os.path.lexists(self.destination) and not os.path.lexists(policy.path('/var/lib/kura-retained')),
                'Existing recovery copy must be preserved')
        logical = self.base / 'kura'
        physical = logical.resolve(strict=True)
        require(physical.parent == self.base and logical.lstat().st_uid == policy.owner,
                'Upgrade source does not match the installed Core home')
        policy.directory(physical)
        control_sha = hashlib.sha256(policy.read(self.control, limit=1024 * 1024, private=False)).hexdigest()
        binding = dict(schema=1, maintenanceId=fence['id'], root=self.identity(policy.root),
                       source=dict(name=physical.name, **self.identity(physical)), preinstSha256=control_sha,
                       **self.versions)
        secret = policy.read(policy.state / 'journal.key', limit=32)
        require(len(secret) == 32)
        return binding, secret

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
            binding, secret = self.binding()
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
            binding, secret = self.binding()
            self.attest(stage, binding, secret)
            os.sync()
            rename_upgrade_copy(stage, self.destination)
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
    else:
        raise api.Refused('Unsupported upgrade preservation action')
