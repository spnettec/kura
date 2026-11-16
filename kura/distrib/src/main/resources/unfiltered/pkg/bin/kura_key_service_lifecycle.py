#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Root-only key-service package admission. Embedded verbatim in Core preinst."""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
import sys
import uuid

FORMAT = "yofc-kura-gateway-master-key-v1"
GENERATION_FORMAT = "yofc-kura-gateway-key-generations-v1"
STATE = "/var/lib/kura-key-service"
LEGACY_UNITS = ("kura-key-service.socket", "kura-key-service.service")
UNITS = (*LEGACY_UNITS, 'kura-key-recovery.service')
LEGACY_ASSETS = frozenset(("bin/kura_key_store.py", "bin/kura_key_service.py", "bin/kura_key_service_lifecycle.py",
                   "libexec/key-backup/kura-key-crypto.jar", "libexec/key-backup/lib/bcprov-jdk18on-1.86.jar"))
COLD_V1_ASSETS = LEGACY_ASSETS | frozenset(('bin/kura_key_recovery.py', 'bin/kura_key_recovery_setup.py',
    'share/key-recovery/index.html', 'share/key-recovery/recovery.js', 'share/key-recovery/recovery.css'))
ASSETS = COLD_V1_ASSETS | frozenset(('bin/kura_key_recovery_start.py',))


class Refused(RuntimeError):
    pass

class Unresolved(Refused):
    pass


def require(ok, message="Invalid key-service state; preserve keys and operation receipts"):
    if not ok:
        raise Refused(message)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def decode(data):
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(Refused("Invalid JSON constant")))
    except (ValueError, UnicodeError, RecursionError):
        raise Refused("Invalid key-service state JSON") from None
    require(isinstance(value, dict))
    return value


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def canonical_id(value):
    try:
        parsed = uuid.UUID(value)
        return isinstance(value, str) and parsed.version == 4 and str(parsed) == value
    except (ValueError, TypeError, AttributeError):
        return False


def is_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def validate_generation_metadata(value):
    require(isinstance(value, dict) and set(value) ==
            {"ringSha256", "activeKeySha256", "legacyKeySha256", "keySha256s"})
    require(all(is_digest(value[k]) for k in ("ringSha256", "activeKeySha256", "legacyKeySha256")))
    keys = value["keySha256s"]
    require(isinstance(keys, list) and 2 <= len(keys) <= 8 and all(is_digest(k) for k in keys)
            and len(set(keys)) == len(keys) and value["activeKeySha256"] == keys[-1]
            and value["legacyKeySha256"] in keys[:-1])


def validate_preparation_response(response, action, identity):
    names = {"schema", "operationId", "state", "action", "published", "requiresExplicitCommit"}
    names |= ({"source", "generation", "historySha256", "backup"} if action == "generation-prepare" else
              {"preparationId", "ringSha256", "backupSha256"})
    require(isinstance(response, dict) and set(response) == names
            and type(response["schema"]) is int and response["schema"] == 1
            and response["operationId"] == identity and response["state"] == "SUCCEEDED"
            and response["action"] == action and response["published"] is False
            and response["requiresExplicitCommit"] is True)
    if action == "generation-prepare":
        source = response["source"]
        require(isinstance(source, dict) and set(source) == {"keySha256", "ringSha256"}
                and is_digest(source["keySha256"])
                and (source["ringSha256"] is None or is_digest(source["ringSha256"]))
                and is_digest(response["historySha256"]))
        validate_generation_metadata(response["generation"])
        require(source["keySha256"] in response["generation"]["keySha256s"][:-1])
        envelope = response["backup"]
        require(isinstance(envelope, dict) and set(envelope) == {"format", "operationId", "encrypted"}
                and envelope["format"] == GENERATION_FORMAT and envelope["operationId"] == identity
                and isinstance(envelope["encrypted"], str) and 0 < len(envelope["encrypted"]) <= 32768)
        try:
            require(bool(base64.b64decode(envelope["encrypted"], validate=True)))
        except ValueError:
            raise Refused("Invalid encrypted preparation receipt") from None
    else:
        require(canonical_id(response["preparationId"]) and is_digest(response["ringSha256"])
                and is_digest(response["backupSha256"]))


def validate_publication(value):
    require(isinstance(value, dict) and set(value) == {
        'schema', 'purpose', 'operationId', 'preparationId', 'verificationId', 'historySha256',
        'source', 'generation', 'cohortSha256', 'stoppedWriter'})
    require(type(value['schema']) is int and value['schema'] == 1
            and value['purpose'] == 'yofc-kura-published-generation-v1')
    require(all(canonical_id(value[name]) for name in ('operationId', 'preparationId', 'verificationId')))
    validate_generation_metadata(value['generation'])
    source = value['source']
    require(isinstance(source, dict) and set(source) == {'keySha256', 'ringSha256'}
            and is_digest(source['keySha256'])
            and (source['ringSha256'] is None or is_digest(source['ringSha256']))
            and is_digest(value['historySha256']) and is_digest(value['cohortSha256']))
    writer = value['stoppedWriter']
    require(isinstance(writer, dict) and set(writer) == {
        'pid', 'startTicks', 'bootId', 'invocationId', 'lockDevice', 'lockInode'})
    require(type(writer['pid']) is int and writer['pid'] > 0
            and isinstance(writer['startTicks'], str) and writer['startTicks'].isdigit()
            and isinstance(writer['bootId'], str)
            and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', writer['bootId']) is not None
            and isinstance(writer['invocationId'], str)
            and re.fullmatch(r'[0-9a-f]{32}', writer['invocationId']) is not None
            and type(writer['lockDevice']) is int and writer['lockDevice'] >= 0
            and type(writer['lockInode']) is int and writer['lockInode'] > 0)
    return value


def validate_record(record, identity):
    cancel = isinstance(record, dict) and record.get('action') == 'generation-cancel'
    require(isinstance(record, dict) and set(record) ==
            {"schema", "operationId", "action", "requestTag", "state", "response"} | ({'intent'} if cancel else set()))
    require(type(record["schema"]) is int and record["schema"] == 1 and canonical_id(identity)
            and record["operationId"] == identity and record["action"] in
              ("backup-create", "generation-backup-create", "restore", "generation-restore", "generation-prepare", "generation-backup-verify",
                 "generation-publish", "generation-core-start", "generation-cancel")
            and record["state"] in ("INTENT", "SUCCEEDED") and is_digest(record["requestTag"]))
    response = record["response"]
    if cancel:
        intent = record['intent']
        require(isinstance(intent, dict) and set(intent) == {
            'preparationId', 'expectedHistorySha256', 'expectedRingSha256'})
        require(canonical_id(intent['preparationId']) and intent['preparationId'] != identity
                and is_digest(intent['expectedHistorySha256']) and is_digest(intent['expectedRingSha256']))
    if record["state"] == "INTENT":
        require(response is None)
        return record
    if cancel:
        require(isinstance(response, dict) and set(response) == {
            'schema', 'operationId', 'state', 'action', 'preparationId', 'historySha256', 'ringSha256',
            'cancellationSha256', 'credentialsChanged', 'historyRetained'})
        require(type(response['schema']) is int and response['schema'] == 1
                and response['operationId'] == identity and response['state'] == 'SUCCEEDED'
                and response['action'] == 'generation-cancel'
                and response['preparationId'] == intent['preparationId']
                and response['historySha256'] == intent['expectedHistorySha256']
                and response['ringSha256'] == intent['expectedRingSha256']
                and is_digest(response['cancellationSha256'])
                and response['credentialsChanged'] is False and response['historyRetained'] is True)
        return record
    if record['action'] in ('generation-publish', 'generation-core-start'):
        names = {'schema', 'operationId', 'state', 'action', 'ringSha256', 'activeKeySha256', 'cohortSha256'}
        publish = record['action'] == 'generation-publish'
        names |= ({'preparationId', 'verificationId', 'publicationSha256', 'coreStopped', 'requiresExplicitStart'}
                  if publish else {'publicationId', 'scope', 'jobPath'})
        require(isinstance(response, dict) and set(response) == names
                and type(response['schema']) is int and response['schema'] == 1
                and response['operationId'] == identity and response['state'] == 'SUCCEEDED'
                and response['action'] == record['action']
                and all(is_digest(response[k]) for k in ('ringSha256', 'activeKeySha256', 'cohortSha256')))
        if publish:
            require(canonical_id(response['preparationId']) and canonical_id(response['verificationId'])
                    and is_digest(response['publicationSha256']) and response['coreStopped'] is True
                    and response['requiresExplicitStart'] is True)
        else:
            require(canonical_id(response['publicationId']) and response['scope'] == 'SYSTEMD_JOB_ACCEPTED'
                    and isinstance(response['jobPath'], str)
                    and re.fullmatch(r'/org/freedesktop/systemd1/job/[0-9]+', response['jobPath']) is not None)
        return record
    if record["action"] in ("generation-prepare", "generation-backup-verify"):
        validate_preparation_response(response, record["action"], identity)
        return record
    names = {"schema", "operationId", "state", "action"}
    backup = record["action"] in ("backup-create", "generation-backup-create")
    modern_restore = record["action"] == "generation-restore"
    names |= ({"backup"} if backup else
              {"ringSha256", "activeKeySha256", "activeKeyRestored", "keyringRestored", "existingReceiptPreserved"}
              if modern_restore else {"keySha256", "keyChanged", "existingReceiptPreserved"})
    require(isinstance(response, dict) and set(response) == names)
    require(type(response["schema"]) is int and response["schema"] == 1
            and response["operationId"] == identity and response["state"] == "SUCCEEDED"
            and response["action"] == record["action"])
    if backup:
        envelope = response["backup"]
        expected_format = GENERATION_FORMAT if record["action"] == "generation-backup-create" else FORMAT
        require(isinstance(envelope, dict) and set(envelope) == {"format", "operationId", "encrypted"}
                and envelope["format"] == expected_format and envelope["operationId"] == identity
                and isinstance(envelope["encrypted"], str) and 0 < len(envelope["encrypted"]) <= 32768)
        try:
            require(bool(base64.b64decode(envelope["encrypted"], validate=True)))
        except ValueError:
            raise Refused("Invalid encrypted operation receipt") from None
    elif modern_restore:
        require(is_digest(response["ringSha256"]) and is_digest(response["activeKeySha256"])
                and type(response["activeKeyRestored"]) is bool and type(response["keyringRestored"]) is bool
                and response["existingReceiptPreserved"] is True)
    else:
        require(is_digest(response["keySha256"]) and type(response["keyChanged"]) is bool
                and response["existingReceiptPreserved"] is True)
    return record


def validate_maintenance(record, identity):
    require(isinstance(record,dict) and set(record)=={'schema','maintenanceId','firstAction','manifestSha256',
            'keySha256','precedingStartupIds','previousMaintenanceId'})
    require(type(record['schema']) is int and record['schema']==1 and canonical_id(identity)
            and record['maintenanceId']==identity and record['firstAction'] in ('install','upgrade')
            and is_digest(record['manifestSha256']) and is_digest(record['keySha256'])
            and (record['previousMaintenanceId'] is None or canonical_id(record['previousMaintenanceId']))
            and record['previousMaintenanceId']!=identity)
    ids=record['precedingStartupIds']
    require(isinstance(ids,list) and len(ids)<=32 and all(canonical_id(v) for v in ids)
            and ids==sorted(set(ids)))
    return record


def validate_start(record, identity):
    require(isinstance(record,dict) and type(record.get('schema')) is int and record['schema'] in (1,2))
    modern=record['schema']==2
    extra={'predecessorStartOperationId','maintenanceId','manifestSha256'} if modern else set()
    require(set(record)=={'schema','operationId','restoreOperationId','keySha256','requestTag','state','response'}|extra)
    require(canonical_id(identity) and record['operationId']==identity and canonical_id(record['restoreOperationId'])
            and is_digest(record['keySha256']) and is_digest(record['requestTag']) and record['state'] in ('INTENT','SUCCEEDED'))
    if modern:
        require(canonical_id(record['predecessorStartOperationId']) and canonical_id(record['maintenanceId'])
                and is_digest(record['manifestSha256']) and record['predecessorStartOperationId']!=identity)
    response=record['response']
    if record['state']=='INTENT':require(response is None)
    else:
        require(isinstance(response,dict) and set(response)=={'schema','operationId','restoreOperationId',
                'keySha256','action','state','scope','jobPath'}|extra)
        require(type(response['schema']) is int and response['schema']==1
                and all(response[k]==record[k] for k in {'operationId','restoreOperationId','keySha256','state'}|extra)
                and response['action']==('core-start-after-maintenance' if modern else 'core-start')
                and response['scope']=='SYSTEMD_JOB_ACCEPTED')
        import re
        require(isinstance(response['jobPath'],str) and re.fullmatch(r'/org/freedesktop/systemd1/job/[0-9]+',response['jobPath']))
    return record


class Lifecycle:
    def __init__(self, root=Path("/"), owner=0, runner=None):
        self.root = Path(root).resolve()
        self.owner = owner
        self.state = self.path(STATE)
        self.runner = subprocess.run if runner is None else runner

    def path(self, name):
        value = Path(name)
        require(value.is_absolute() and ".." not in value.parts)
        return self.root / value.relative_to("/")

    def directory(self, path, private=False, create=False):
        current = self.root
        for part in ("", *path.relative_to(self.root).parts):
            current = current / part
            if create and not os.path.lexists(current):
                current.mkdir(mode=0o700 if private and current == path or current in (self.state, self.state / "operations", self.state / "startups", self.state / "package-history") else 0o755)
            m = current.lstat()
            require(stat.S_ISDIR(m.st_mode) and m.st_uid == self.owner and not m.st_mode & 0o022,
                    "Unsafe key-service directory; preserve state")
        if private:
            require(not m.st_mode & 0o077, "Key-service journal directory must be private")

    def read(self, path, limit=65536, private=True):
        self.directory(path.parent, private=private)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            m = os.fstat(fd)
            require(stat.S_ISREG(m.st_mode) and m.st_uid == self.owner and m.st_nlink == 1
                    and not m.st_mode & (0o7077 if private else 0o7022) and m.st_size <= limit)
            data = bytearray()
            while len(data) <= limit:
                block = os.read(fd, min(65536, limit + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
            after = os.fstat(fd)
            now = path.lstat()
            require(len(data) == m.st_size and len(data) <= limit
                    and (m.st_dev, m.st_ino, m.st_size, m.st_mtime_ns, m.st_ctime_ns)
                    == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    and (m.st_dev, m.st_ino) == (now.st_dev, now.st_ino))
            return bytes(data)
        finally:
            os.close(fd)

    @staticmethod
    def sync(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def create(self, path, data):
        self.directory(path.parent, private=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            # An incomplete private file is retained and fails validation next time.
            pass
        self.sync(path.parent)

    def initialize(self):
        self.directory(self.state, private=True, create=True)
        self.directory(self.state / "operations", private=True, create=True)
        names = list(self.state.iterdir())
        require({p.name for p in names} <= {"operations", "admission.lock", "journal.key", "maintenance.json", "startups", "package-history"})
        lock = self.state / "admission.lock"
        if not os.path.lexists(lock):
            require(not list((self.state / "operations").iterdir()), "Missing admission lock with saved operations")
            self.create(lock, b"")
        require(self.read(lock) == b"", "Invalid key-service admission lock")

    @contextlib.contextmanager
    def locked(self):
        self.directory(self.state, private=True)
        fd = os.open(self.state / "admission.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            m = os.fstat(fd)
            require(stat.S_ISREG(m.st_mode) and m.st_uid == self.owner and m.st_nlink == 1
                    and m.st_size == 0 and not m.st_mode & 0o077)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused("Key operation is active; package change refused before stop or file replacement") from None
            yield
        finally:
            os.close(fd)

    def check_records(self, *, recovering_cancel=None):
        self.directory(self.state / "operations", private=True)
        paths = list((self.state / "operations").iterdir())
        require(len(paths) <= 256)
        for path in paths:
            require(path.name.endswith(".json") and canonical_id(path.name[:-5]))
            record = validate_record(decode(self.read(path)), path.name[:-5])
            if record["state"] != "SUCCEEDED":
                if path.name[:-5] == recovering_cancel and record['action'] == 'generation-cancel':
                    continue
                raise Unresolved("Unresolved key operation; preserve original UUID and package state")
        startups=self.state/'startups'
        if os.path.lexists(startups):
            self.directory(startups,private=True)
            starts=list(startups.iterdir());require(len(starts)<=32)
            for path in starts:
                require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                record=validate_start(decode(self.read(path)),path.name[:-5])
                if record['state'] != 'SUCCEEDED':
                    raise Unresolved('Unresolved Core start; retain original UUID')
        history=self.state/'package-history'
        if os.path.lexists(history):
            self.directory(history,private=True)
            records=list(history.iterdir());require(len(records)<=128)
            for path in records:
                require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                validate_maintenance(decode(self.read(path)),path.name[:-5])
        return paths

    def fence(self):
        marker = self.state / "maintenance.json"
        if not os.path.lexists(marker):
            return None
        value = decode(self.read(marker))
        require(set(value) == {"schema", "id", "state", "firstAction"}
                and type(value["schema"]) is int and value["schema"] == 1 and canonical_id(value["id"])
                and value["state"] == "MAINTENANCE" and value["firstAction"] in ("install", "upgrade", "remove"))
        return value

    def assets(self, *, generation_binding=False):
        logical = self.path("/opt/eclipse/kura")
        physical = logical.resolve(strict=True)
        require(physical.parent == self.path("/opt/eclipse") and physical.is_dir())
        if logical.is_symlink():
            require(logical.lstat().st_uid == self.owner)
        manifest_raw = self.read(physical / "libexec/key-backup/manifest.json", private=False)
        manifest = decode(manifest_raw)
        modern = type(manifest.get("schema")) is int and manifest["schema"] == 2
        require(set(manifest) == {"schema", "protocol", "files", "units"} | ({"generation"} if modern else set())
                and type(manifest["schema"]) is int and manifest["schema"] == (2 if modern else 1)
                and type(manifest["protocol"]) is int and manifest["protocol"] == (2 if modern else 1)
                and isinstance(manifest["files"], dict) and isinstance(manifest["units"], dict))
        profile = (frozenset(manifest['files']), frozenset(manifest['units']))
        require((profile == (ASSETS, frozenset(UNITS)) and isinstance(manifest['generation'], dict))
                if modern else profile in ((LEGACY_ASSETS, frozenset(LEGACY_UNITS)), (COLD_V1_ASSETS, frozenset(UNITS)), (ASSETS, frozenset(UNITS))),
                'Unrecognized key-service package profile')
        for name, expected in manifest["files"].items():
            require(isinstance(name, str) and name and not Path(name).is_absolute()
                    and str(Path(name)) == name and all(p not in ('.', '..') for p in Path(name).parts))
            require(is_digest(expected))
            require(hashlib.sha256(self.read(physical / name, limit=16*1024*1024, private=False)).hexdigest() == expected,
                    "Installed key-service asset differs from its package manifest")
        for name, expected in manifest["units"].items():
            require(is_digest(expected))
            unit = self.path("/lib/systemd/system/" + name).resolve(strict=True)
            require(hashlib.sha256(self.read(unit, private=False)).hexdigest() == expected,
                    "Installed key-service unit differs from its package manifest")
        if generation_binding:
            require(modern, 'This package has no complete generation-reader cohort')
            generation = manifest['generation']
            require(set(generation) == {'files', 'readers', 'unitSha256', 'writerProtocol'}
                    and type(generation['writerProtocol']) is int and generation['writerProtocol'] == 1
                    and isinstance(generation['files'], dict)
                    and 1 <= len(generation['files']) <= 512 and is_digest(generation['unitSha256']))
            for name, expected in generation['files'].items():
                require(isinstance(name, str) and name and not Path(name).is_absolute()
                        and str(Path(name)) == name and all(p not in ('.', '..') for p in Path(name).parts)
                        and is_digest(expected))
                require(hashlib.sha256(self.read(physical / name, limit=16*1024*1024, private=False)).hexdigest() == expected,
                        'Installed generation reader differs from its package manifest')
            unit = self.read(self.path('/lib/systemd/system/kura.service').resolve(strict=True), private=False)
            require(hashlib.sha256(unit).hexdigest() == generation['unitSha256'], 'Installed generation Core unit is not paired')
            # Embedded preinst must still inspect old protocol-1 packages without this
            # new helper. Execute only the source bytes already attested above, never pyc.
            name = 'bin/kura_key_cohort.py'
            require(name in generation['files'])
            source = self.read(physical / name, limit=65536, private=False)
            require(hashlib.sha256(source).hexdigest() == generation['files'][name])
            namespace = {'__name__': 'kura_key_cohort', '__file__': str(physical / name)}
            exec(compile(source, str(physical / name), 'exec'), namespace)
            try:
                observed = namespace['validate'](physical, generation, lambda p: self.read(p, private=False), self.owner, unit=unit)
            except namespace['Refused']:
                raise Refused('Generation-reader package is not paired; preserve keys and original operation IDs') from None
            binding = dict(schema=1, purpose='yofc-kura-key-generation-package-v1',
                           manifestSha256=hashlib.sha256(manifest_raw).hexdigest(),
                           launcherSha256s={Path(name).name: value for name, value in observed.items()})
            return dict(binding, cohortSha256=hashlib.sha256(encoded(binding)).hexdigest())
        return manifest

    def generation_assets(self):
        return self.assets(generation_binding=True)

    @contextlib.contextmanager
    def recovery_locked(self):
        state = self.path('/var/lib/kura-key-recovery')
        if not os.path.lexists(state):
            yield
            return
        account = pwd.getpwnam('kura-key-recovery')
        daemon = pwd.getpwnam('kurad')
        require(account.pw_uid not in (0,daemon.pw_uid) and account.pw_shell in ('/usr/sbin/nologin','/sbin/nologin'))
        def directory(path):
            m=path.lstat();require(stat.S_ISDIR(m.st_mode) and m.st_uid==account.pw_uid
                and m.st_gid==account.pw_gid and stat.S_IMODE(m.st_mode)==0o700)
        def read(path, limit):
            directory(path.parent)
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
            try:
                m=os.fstat(fd);require(stat.S_ISREG(m.st_mode) and m.st_nlink==1 and m.st_uid==account.pw_uid
                    and m.st_gid==account.pw_gid and stat.S_IMODE(m.st_mode)==0o600 and m.st_size<=limit)
                data=os.read(fd,limit+1);after=os.fstat(fd);now=path.lstat()
                require(len(data)==m.st_size and len(data)<=limit and
                    (m.st_dev,m.st_ino,m.st_size,m.st_mtime_ns,m.st_ctime_ns)==
                    (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) and
                    (m.st_dev,m.st_ino)==(now.st_dev,now.st_ino))
                return data
            finally:os.close(fd)
        self.directory(state.parent)
        directory(state);directory(state/'operations')
        require({'operations','admission.lock'} <= {p.name for p in state.iterdir()} <= {'operations','admission.lock','starts','pending.json'})
        require(read(state/'admission.lock',0)==b'')
        fd=os.open(state/'admission.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise Refused('Cold recovery is active; package change refused') from None
            files=list((state/'operations').iterdir());require(len(files)<=32)
            for path in files:
                require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                value=decode(read(path,4096))
                require(set(value)=={'schema','operationId','expectedKeySha256','backupSha256'}
                    and type(value['schema']) is int and value['schema']==1 and value['operationId']==path.name[:-5]
                    and is_digest(value['expectedKeySha256']) and is_digest(value['backupSha256']))
                original=validate_record(decode(self.read(self.state/'operations'/path.name)),value['operationId'])
                require(original['state']=='SUCCEEDED' and original['action']=='restore'
                    and original['response']['keySha256']==value['expectedKeySha256'],
                    'Unresolved cold recovery; retain original UUID and package state')
            if os.path.lexists(state/'pending.json'):
                pending=decode(read(state/'pending.json',4096))
                require(set(pending)=={'schema','operationId','expectedKeySha256'} and type(pending['schema']) is int
                        and pending['schema']==1 and canonical_id(pending['operationId']) and is_digest(pending['expectedKeySha256']))
                local=decode(read(state/'operations'/(pending['operationId']+'.json'),4096))
                require(local['expectedKeySha256']==pending['expectedKeySha256'])
            if os.path.lexists(state/'starts'):
                directory(state/'starts');starts=list((state/'starts').iterdir());require(len(starts)<=32)
                for path in starts:
                    require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                    local=decode(read(path,4096))
                    modern=type(local.get('schema')) is int and local['schema']==2
                    extra={'predecessorStartOperationId','maintenanceId','manifestSha256'} if modern else set()
                    require(set(local)=={'schema','operationId','restoreOperationId','expectedKeySha256'}|extra
                            and type(local['schema']) is int and local['schema'] in (1,2) and local['operationId']==path.name[:-5]
                            and canonical_id(local['restoreOperationId']) and is_digest(local['expectedKeySha256']))
                    if modern:require(canonical_id(local['predecessorStartOperationId']) and canonical_id(local['maintenanceId']) and is_digest(local['manifestSha256']))
                    root=validate_start(decode(self.read(self.state/'startups'/path.name)),local['operationId'])
                    require(root['state']=='SUCCEEDED' and root['restoreOperationId']==local['restoreOperationId']
                            and root['keySha256']==local['expectedKeySha256'] and all(root.get(k)==local[k] for k in extra),'Unresolved Core handoff; retain original UUID')
            yield
        finally:os.close(fd)

    def no_overrides(self):
        for prefix in ("/etc", "/run", "/usr/lib", "/lib"):
            base = self.path(prefix + "/systemd/system")
            for name in UNITS:
                if prefix in ("/etc", "/run"):
                    require(not os.path.lexists(base / name), "Custom key-service unit requires reviewed migration")
                stem, kind = name.rsplit(".", 1)
                parts = stem.split("-")
                folders = [name + ".d", kind + ".d"]
                folders += ["-".join(parts[:i]) + "-." + kind + ".d" for i in range(1, len(parts))]
                for folder in folders:
                    path = base / folder
                    if os.path.lexists(path):
                        require(not path.is_symlink() and path.is_dir() and path.lstat().st_uid == self.owner
                                and not path.lstat().st_mode & 0o022 and not list(path.glob("*.conf")),
                                "Custom key-service drop-in requires reviewed migration")

    def command(self, arguments):
        result = self.runner(["/usr/bin/systemctl", *arguments], capture_output=True, text=True,
                             timeout=35, check=False, env={"PATH": "/usr/bin:/bin", "LANG": "C"})
        require(result.returncode == 0, "Key-service manager command failed; preserve fenced state")
        return result.stdout

    def stop_units(self):
        if not self.path("/run/systemd/system").is_dir():
            require(not any(os.path.lexists(self.path("/lib/systemd/system/" + name)) for name in UNITS),
                    "Installed key service requires its systemd manager")
            return
        for name in UNITS: # Stop listener first, then the idle worker service.
            output = self.command(["show", name, "--property=LoadState", "--property=ActiveState",
                                   "--property=MainPID", "--property=ControlPID"])
            properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
            if properties.get("LoadState") != "not-found":
                self.command(["stop", name])
                output = self.command(["show", name, "--property=ActiveState", "--property=MainPID", "--property=ControlPID"])
                properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
            require(properties.get("ActiveState") in ("inactive", "failed")
                    and properties.get("MainPID", "0") == "0" and properties.get("ControlPID", "0") == "0",
                    "Key-service processes are still active; package change refused")

    def enter(self, action):
        require(action in ("install", "upgrade", "remove"))
        self.no_overrides()
        registered = any(os.path.lexists(self.path("/lib/systemd/system/" + name)) for name in UNITS)
        if self.path("/run/systemd/system").is_dir():
            for name in UNITS:
                output = self.command(["show", name, "--property=LoadState"])
                properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
                require(properties.get("LoadState") in ("loaded", "masked", "not-found"))
                registered |= properties["LoadState"] != "not-found"
        previous_fence = self.fence() if os.path.lexists(self.state) else None
        if registered and previous_fence is None:
            manifest=self.assets() # Never execute an unknown installed helper or silently adopt another unit.
            for name in set(UNITS)-set(manifest['units']):
                require(not os.path.lexists(self.path('/lib/systemd/system/'+name)), 'Foreign recovery unit requires reviewed migration')
                if self.path('/run/systemd/system').is_dir():
                    properties=dict(line.split('=',1) for line in self.command(['show',name,'--property=LoadState']).splitlines() if '=' in line)
                    require(properties.get('LoadState')=='not-found', 'Foreign recovery service requires reviewed migration')
        self.initialize()
        with self.recovery_locked(), self.locked():
            paths = self.check_records()
            secret = self.state / "journal.key"
            if not os.path.lexists(secret):
                require(not paths, "Journal key missing with saved operations; do not replace it")
                self.create(secret, secrets.token_bytes(32))
            require(len(self.read(secret, limit=32)) == 32)
            marker = self.fence()
            if marker is None:
                marker = dict(schema=1, id=str(uuid.uuid4()), state="MAINTENANCE", firstAction=action)
                self.create(self.state / "maintenance.json", encoded(marker))
            self.stop_units()
        return marker

    def leave(self):
        self.no_overrides()
        manifest=self.assets()
        with self.locked():
            self.check_records()
            if manifest.get('schema') == 2:
                directory = self.path('/etc/systemd/system/kura.service.d')
                if not os.path.lexists(directory):
                    self.directory(directory, private=True, create=True)
                    self.sync(directory.parent)
            # Created only after unpack: old prerm must still recognize the old journal.
            if frozenset(manifest["files"]) == ASSETS:
                self.directory(self.state / "startups", private=True, create=True)
                self.sync(self.state)
            require(len(self.read(self.state / "journal.key", limit=32)) == 32)
            fence=self.fence()
            # Reuse the data-key consumer's exact private-file and receipt checks.
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from kura_key_service import Manager
            manager = Manager(self.root, self.owner)
            with manager.lock(manager.store.path("/etc/kura/credentials/.provision.lock"), False):
                _,_,_,_,proof,_=manager.generation_source()
            if fence is not None and fence['firstAction'] in ('install','upgrade') and frozenset(manifest['files'])==ASSETS:
                # The existing installer stops Main synchronously. Record its terminal
                # predecessor set under the package lock, never infer UNKNOWN from Main0.
                if self.path('/run/systemd/system').is_dir():
                    info=dict(line.split('=',1) for line in self.command(['show','kura.service','--property=ActiveState',
                        '--property=MainPID','--property=ControlPID']).splitlines() if '=' in line)
                    require(info.get('ActiveState') in ('inactive','failed') and info.get('MainPID')=='0'
                            and info.get('ControlPID')=='0','Core must be stopped before publishing package handoff')
                history=self.state/'package-history';self.directory(history,private=True,create=True)
                ids=sorted(path.name[:-5] for path in (self.state/'startups').iterdir())
                prior=[]
                for path in history.iterdir():
                    require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                    record=validate_maintenance(decode(self.read(path)),path.name[:-5])
                    if record['maintenanceId']!=fence['id']:prior.append(record)
                require(len(ids)<=32 and len(prior)<128)
                parents={item['previousMaintenanceId'] for item in prior}
                heads=[item for item in prior if item['maintenanceId'] not in parents]
                require(len(heads)==(1 if prior else 0),'Package history head is ambiguous')
                previous=heads[0]['maintenanceId'] if heads else None
                home=self.path('/opt/eclipse/kura').resolve(strict=True)
                value=dict(schema=1,maintenanceId=fence['id'],firstAction=fence['firstAction'],
                    manifestSha256=hashlib.sha256(self.read(home/'libexec/key-backup/manifest.json',private=False)).hexdigest(),
                    keySha256=proof['keySha256'],precedingStartupIds=ids,previousMaintenanceId=previous)
                validate_maintenance(value,fence['id']);target=history/(fence['id']+'.json')
                if os.path.lexists(target):require(decode(self.read(target))==value)
                else:self.create(target,encoded(value))
                self.sync(self.state)
            marker = self.state / "maintenance.json"
            if os.path.lexists(marker):
                marker.unlink()
                self.sync(self.state)

    def remove_units(self):
        self.no_overrides()
        manifest = self.assets()
        with self.locked():
            self.check_records()
            require(self.fence() is not None, "Package admission fence is missing")
            self.stop_units()
            self.command(["disable", "kura-key-service.socket"])
            if 'kura-key-recovery.service' in manifest['units']:
                self.command(['disable','kura-key-recovery.service'])
            for name in manifest['units']:
                path = self.path("/lib/systemd/system/" + name).resolve(strict=True)
                require(hashlib.sha256(self.read(path, private=False)).hexdigest() == manifest["units"][name])
                path.unlink()
                self.sync(path.parent)
            self.command(["daemon-reload"])


if __name__ == "__main__":
    try:
        require(os.geteuid() == 0, "Key-service package admission requires root")
        lifecycle = Lifecycle()
        if len(sys.argv) == 3 and sys.argv[1] == "--enter":
            lifecycle.enter(sys.argv[2])
        elif sys.argv[1:] == ["--leave"]:
            lifecycle.leave()
        elif sys.argv[1:] == ["--remove-units"]:
            lifecycle.remove_units()
        else:
            raise Refused("Unsupported key-service package admission action")
    except Exception:
        sys.stderr.write("Key-service package admission refused; retain keys, receipts, backups and installation\n")
        sys.exit(1)
