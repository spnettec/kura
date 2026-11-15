#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Core-owned read-only snapshot validation; no key or plaintext response to an agent."""
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from kura_key_service import Failure, require, fields, digest, encode, decode
from kura_key_store import KEY_PATH, RING_PATH

PURPOSE = 'yofc-kura-core-credential-validation-v1'
MAX_SNAPSHOT = 32 << 20
WORKER = ('/usr/bin/java', '-Xms16m', '-Xmx128m', '-XX:MaxMetaspaceSize=64m',
          '-XX:ActiveProcessorCount=1', '-XX:+UseSerialGC', '-XX:+DisableAttachMechanism',
          '-XX:+PerfDisableSharedMem', '-jar', '/opt/eclipse/kura/libexec/key-recovery/kura-offline-recovery.jar')


class Validation:
    def __init__(self, manager, runner=None):
        self.manager = manager
        self.runner = subprocess.run if runner is None else runner

    def binding(self):
        manager = self.manager
        _, _, _, _, _, source = manager.generation_source()
        cohort = manager.require_generation_cohort()
        value = dict(schema=1, purpose=PURPOSE, activeKeySha256=source['keySha256'],
                     ringSha256=source['ringSha256'], cohortSha256=cohort['cohortSha256'])
        return value, hashlib.sha256(encode(value)).hexdigest()

    def info(self, request):
        fields(request, {'schema', 'action'})
        require(type(request['schema']) is int and request['schema'] == 1
                and request['action'] == 'core-validation-info')
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', False):
            manager.maintenance(); manager.settled()
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                binding, fingerprint = self.binding()
                return dict(schema=1, state='CORE_CREDENTIALS_READY', binding=binding, bindingSha256=fingerprint)

    @staticmethod
    def metadata(fd):
        value = os.fstat(fd)
        return (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
                value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    @staticmethod
    def report(raw, expected_sha, mode, policy):
        value = decode(raw)
        names = {'schema', 'artifactSha256', 'mode', 'configurationCount', 'factoryCount', 'propertyCount',
                 'passwordValueCount', 'authenticatedPasswordCount', 'legacyPasswordCount',
                 'keyAuthenticated', 'fullRecoveryVerified'}
        require(names <= set(value) <= names | {'logicalPasswordCount', 'passwordEncoding'}, 'VALIDATION_UNAVAILABLE')
        require(type(value['schema']) is int and value['schema'] == 1 and value['artifactSha256'] == expected_sha
                and value['mode'] == mode and value['fullRecoveryVerified'] is False
                and type(value['keyAuthenticated']) is bool, 'VALIDATION_UNAVAILABLE')
        for name in ('configurationCount', 'factoryCount', 'propertyCount', 'passwordValueCount',
                     'authenticatedPasswordCount', 'legacyPasswordCount'):
            require(type(value[name]) is int and 0 <= value[name] <= 65536, 'VALIDATION_UNAVAILABLE')
        logical = value.get('logicalPasswordCount', 0)
        require(type(logical) is int and 0 <= logical <= 65536, 'VALIDATION_UNAVAILABLE')
        require(1 <= value['configurationCount'] <= 4096 and value['factoryCount'] <= value['configurationCount']
                and value['authenticatedPasswordCount'] + value['legacyPasswordCount'] + logical == value['passwordValueCount']
                and value['keyAuthenticated'] == (mode == 'aes-gcm' or value['authenticatedPasswordCount'] > 0)
                and (policy == 'legacy' or value['legacyPasswordCount'] == 0)
                and value.get('passwordEncoding') in (None, 'BASE64_LOGICAL_V1')
                and (logical == 0 or value.get('passwordEncoding') == 'BASE64_LOGICAL_V1')
                and (value.get('passwordEncoding') is None or value['authenticatedPasswordCount'] == value['legacyPasswordCount'] == 0)
                and (policy != 'authenticated' or logical == 0 or mode == 'aes-gcm')
                and (policy != 'legacy' or value.get('passwordEncoding') is None)
                and (policy != 'logical-v1' or value.get('passwordEncoding') == 'BASE64_LOGICAL_V1'
                     and value['authenticatedPasswordCount'] == value['legacyPasswordCount'] == 0), 'VALIDATION_UNAVAILABLE')
        return value

    def validate(self, request, descriptor, uid, *, core_uid=None):
        fields(request, {'schema', 'action', 'snapshotSha256', 'mode', 'passwordPolicy', 'expectedBindingSha256'})
        require(type(request['schema']) is int and request['schema'] == 1
                and request['action'] == 'core-snapshot-validate')
        digest(request['snapshotSha256']); digest(request['expectedBindingSha256'])
        require(request['mode'] in ('plain', 'aes-gcm')
                and request['passwordPolicy'] in ('authenticated', 'legacy', 'logical-v1'))
        require(type(descriptor) is int and descriptor >= 0 and type(uid) is int and uid >= 0)
        require(core_uid is None or type(core_uid) is int and core_uid > 0)
        before = self.metadata(descriptor)
        # Restore uploads belong to the agent; the placed target belongs to kurad.
        # The latter UID is resolved by the server, never supplied in the request.
        require(stat.S_ISREG(before[4]) and before[2] in (uid, core_uid) and before[5] == 1
                and not stat.S_IMODE(before[4]) & 0o077 and 0 < before[6] <= MAX_SNAPSHOT
                and fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY, 'UNSAFE_VALIDATION_INPUT')
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', False):
            manager.maintenance(); manager.settled()
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                binding, fingerprint = self.binding()
                require(fingerprint == request['expectedBindingSha256'], 'CONFLICT')
                with tempfile.TemporaryDirectory(prefix='kura-core-validation-') as temporary:
                    path = Path(temporary) / 'snapshot'
                    digestor = hashlib.sha256()
                    count = 0
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
                    with os.fdopen(fd, 'wb') as output:
                        while count <= before[6]:
                            chunk = os.pread(descriptor, min(65536, before[6] + 1 - count), count)
                            if not chunk:
                                break
                            output.write(chunk); digestor.update(chunk); count += len(chunk)
                    require(count == before[6] and self.metadata(descriptor) == before
                            and digestor.hexdigest() == request['snapshotSha256'], 'CONFLICT')
                    arguments = [*WORKER, 'validate', '--input', str(path), '--mode', request['mode'],
                                 '--password-policy', request['passwordPolicy']]
                    if binding['ringSha256'] is None:
                        arguments += ['--key-file', KEY_PATH]
                    else:
                        arguments += ['--keyring-file', RING_PATH, '--keyring-sha256', binding['ringSha256']]
                    try:
                        result = self.runner(arguments, capture_output=True, timeout=35, check=False, close_fds=True,
                                             cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C'})
                    except (OSError, subprocess.TimeoutExpired):
                        raise Failure('VALIDATION_UNAVAILABLE') from None
                    require(result.returncode == 0 and not result.stderr and 0 < len(result.stdout) <= 4096,
                            'VALIDATION_REJECTED')
                    report = self.report(result.stdout, request['snapshotSha256'], request['mode'], request['passwordPolicy'])
                    require(self.binding() == (binding, fingerprint) and self.metadata(descriptor) == before, 'CONFLICT')
                    return dict(schema=1, state='CORE_SNAPSHOT_VALIDATED', binding=binding,
                                bindingSha256=fingerprint, report=report)
