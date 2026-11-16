#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Core-owned AES backup/recovery and staged generations. No active-key publication."""
import base64
import array
import contextlib
import ctypes
import datetime
import errno
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import socket
import ssl
import stat
import struct
import subprocess
import sys
import threading
import uuid

# Lazy helpers must share this entrypoint's exception and protocol classes.
if __name__ == '__main__':
    sys.modules['kura_key_service'] = sys.modules[__name__]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_key_store import (Store, KEY_PATH, RECEIPT_PATH, CORE_DEFAULT, OLD_DEVELOPMENT, Refused,
                            GENERATION_FORMAT, RING_PATH, RING_MAGIC, GENERATION_RECEIPT_PATH,
                            key_generations as parse_key_generations, generation_receipt as parse_generation_receipt,
                            key_generation_entries, encode_key_generations)
from kura_key_service_lifecycle import (Lifecycle, validate_record, validate_publication, Refused as LifecycleRefused,
                                       Unresolved as LifecycleUnresolved, GWT_BINDING_PURPOSE, GWT_DATA_FIELDS,
                                       GWT_NAMESPACE_FIELDS, gwt_namespace, validate_gwt_data, validate_gwt_binding,
                                       validate_sender_admission, validate_start, validate_handoff_authority,
                                       SENDER_ADMISSION_PURPOSE, SENDER_ADMISSION_CONTEXT, handoff_revocations,
                                       handoff_operation_request, archive_inventory, archive_references, archive_entry,
                                       active_journal_count, ARCHIVE_INTENT_CONTEXT, ARCHIVE_RECEIPT_CONTEXT,
                                       PRIVATE_FENCE_PURPOSE, PRIVATE_FENCE_CONTEXT, validate_gwt_intent, validate_sender_attempt,
                                       check_sender_original)

SOCKET = "/run/kura-key-service/control.sock"
STATE = "/var/lib/kura-key-service"
FORMAT = "yofc-kura-gateway-master-key-v1"
MAX_FRAME = 65536
MAX_OPERATIONS = 256
CIPHER = ["/usr/bin/java", "-Xms16m", "-Xmx96m", "-XX:MaxMetaspaceSize=64m",
          "-XX:ActiveProcessorCount=1", "-XX:+DisableAttachMechanism", "-XX:+PerfDisableSharedMem",
          "-jar", "/opt/eclipse/kura/libexec/key-backup/kura-key-crypto.jar"]


class Failure(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def require(ok, reason="INVALID_ARGUMENT"):
    if not ok:
        raise Failure(reason)


def rename_no_replace(source, destination):
    """Move one original inode without replacing a destination or creating hard links."""
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, "renameat2", None)
    require(rename is not None and sys.platform == "linux", "UNSUPPORTED")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise Failure("CONFLICT")
        raise OSError(code, "Atomic key publication refused")


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def decode(data):
    require(len(data) <= MAX_FRAME)
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(Failure("INVALID_ARGUMENT")))
    except (ValueError, UnicodeError, RecursionError):
        raise Failure("INVALID_ARGUMENT") from None
    require(isinstance(value, dict))
    return value


def fields(value, names):
    require(isinstance(value, dict) and set(value) == set(names))


def operation_id(value):
    require(isinstance(value, str))
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise Failure("INVALID_ARGUMENT") from None
    require(parsed.version == 4 and str(parsed) == value)
    return value


def digest(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None)
    return value


def passphrase(value):
    require(isinstance(value, str) and 12 <= len(value) <= 256 and "\0" not in value)
    try:
        raw = value.encode("utf-8")
    except UnicodeError:
        raise Failure("INVALID_ARGUMENT") from None
    require(len(raw) <= 1024)
    return raw


def receipt(value, key=None):
    fields(value, {"schema", "keySha256", "origin", "legacyKey", "unitDigests"})
    require(type(value["schema"]) is int and value["schema"] == 1)
    digest(value["keySha256"])
    require(value["origin"] in ("fresh", "legacy", "canonical"))
    require(type(value["legacyKey"]) is bool)
    require(isinstance(value["unitDigests"], list) and len(value["unitDigests"]) <= 3)
    for item in value["unitDigests"]:
        digest(item)
    if key is not None:
        require(len(key) in (16, 24, 32) and hashlib.sha256(key).hexdigest() == value["keySha256"])
        require(value["legacyKey"] == (key in (CORE_DEFAULT, OLD_DEVELOPMENT)))
    return value


def key_generations(raw):
    try:
        return parse_key_generations(raw)
    except Refused:
        raise Failure("INVALID_ARGUMENT") from None


class SenderAdmissions:
    """Root-owned reservations and a durable, single intake for every sender identity."""
    def __init__(self, manager):
        self.manager = manager
        self.directory = manager.state/'sender-admissions'
        self.context = threading.local()

    @contextlib.contextmanager
    def locked(self):
        if getattr(self.context, 'locked', False):
            yield
            return
        with self.manager.lock(self.manager.state/'sender-admission.lock', True):
            self.context.locked = True
            try: yield
            finally: self.context.locked = False

    def secret(self):
        secret = self.manager.read(self.manager.state/'journal.key', 32)
        require(len(secret) == 32, 'UNSAFE_JOURNAL')
        return secret

    def tag(self, request):
        return hmac.new(self.secret(), encode(request), hashlib.sha256).hexdigest()

    def load(self, identity):
        operation_id(identity)
        if not os.path.lexists(self.directory): return None
        self.manager.directory(self.directory, private=True)
        try: raw = self.manager.read(self.directory/(identity+'.json'), 8192)
        except FileNotFoundError: return None
        try: value = validate_sender_admission(decode(raw), identity, self.secret())
        except LifecycleRefused: raise Failure('UNSAFE_JOURNAL') from None
        require(value['namespaceSha256'] == self.manager.gwt_namespace()['namespaceSha256'], 'CONFLICT')
        if value['purpose']==PRIVATE_FENCE_PURPOSE:
            try:check_sender_original(self.manager,value,self.secret())
            except LifecycleRefused:raise Failure('UNSAFE_JOURNAL') from None
        return value

    def write(self, value, *, create=False):
        require(value.get('purpose')==SENDER_ADMISSION_PURPOSE,'FORBIDDEN')
        if not create and os.path.lexists(self.directory/(value['admissionId']+'.json')):
            require(not self.archive_claimed(value),'ARCHIVED_ORIGINAL')
        if not os.path.lexists(self.directory):
            self.directory.mkdir(mode=0o700); self.manager.sync(self.manager.state)
        self.manager.directory(self.directory, private=True)
        value = dict(value); value.pop('receiptTag', None)
        value['receiptTag'] = hmac.new(self.secret(), SENDER_ADMISSION_CONTEXT + encode(value), hashlib.sha256).hexdigest()
        self.manager.atomic(self.directory/(value['admissionId']+'.json'), encode(value), no_replace=create)
        return self.load(value['admissionId'])

    def records(self):
        if not os.path.lexists(self.directory): return []
        self.manager.directory(self.directory, private=True)
        paths = list(self.directory.iterdir())
        require(self.manager.active_records('sender-admissions',[operation_id(p.name[:-5]) for p in paths if p.name.endswith('.json')]) <= 256, 'CAPACITY')
        result = []
        for path in paths:
            require(path.name.endswith('.json'), 'UNSAFE_JOURNAL')
            value = self.load(operation_id(path.name[:-5])); require(value is not None, 'UNSAFE_JOURNAL'); result.append(value)
        return result

    def native_target(self, request, *, directory='operations'):
        return dict(directory=directory, operationId=operation_id(request['operationId']),
            action=request['action'], requestTag=self.tag(request), continuation=False)

    def require_capacity(self, *, admission=None, handoff=None, native=None):
        """Project both journals under the sender/admission locks, without reserving a writer.

        Immutable grants promise their missing fixed operations. An unmaterialized
        RESERVED/INTAKE issuer promises two anonymous slots in each journal, so
        the sender-private intent gap cannot spend them. Neither time nor absence
        releases a promise. Positive unused revocation permanently fences both IDs.
        Existing originals consume promises; their durable rows still count.
        """
        manager = self.manager; inventory=manager.archives()
        records = self.records()
        if admission is not None:
            require(all(row['admissionId'] != admission['admissionId'] for row in records), 'CONFLICT')
            records.append(admission)
        present = {}
        for directory in ('operations', 'startups'):
            parent = manager.state/directory
            paths = []
            if os.path.lexists(parent):
                manager.directory(parent, private=True); paths = list(parent.iterdir())
            identities = set()
            for path in paths:
                require(path.name.endswith('.json'), 'UNSAFE_JOURNAL')
                identities.add(operation_id(path.name[:-5]))
            present[directory] = identities
        authorities = {}
        parent = manager.state/'handoffs'
        if os.path.lexists(parent):
            manager.directory(parent, private=True); paths = list(parent.iterdir())
            require(manager.active_records('handoffs',[operation_id(p.name[:-5]) for p in paths if p.name.endswith('.json')],inventory=inventory) <= 32, 'CAPACITY')
            for path in paths:
                require(path.name.endswith('.json'), 'UNSAFE_JOURNAL')
                identity = operation_id(path.name[:-5]); raw = manager.read(path, 8192)
                try: value = validate_handoff_authority(decode(raw), identity, self.secret())
                except LifecycleRefused: raise Failure('UNSAFE_JOURNAL') from None
                require(raw == encode(value) and stat.S_IMODE(path.lstat().st_mode) == 0o400, 'UNSAFE_JOURNAL')
                authorities[identity] = value
        if handoff is not None:
            require(handoff['handoffId'] not in authorities, 'CONFLICT')
            authorities[handoff['handoffId']] = dict(request=handoff, requestTag=self.tag(handoff))
        try: revoked = handoff_revocations(manager)
        except LifecycleRefused: raise Failure('UNSAFE_JOURNAL') from None
        fixed = {}; promised = {'operations': set(), 'startups': set()}; shared = set()
        other_ids = {value['request'][key] for value in authorities.values()
            for key in ('handoffId', 'preparationId', 'verificationId')}
        for identity, value in authorities.items():
            for start in (False, True):
                target = self.native_target(handoff_operation_request(value, start=start))
                key = target['operationId']
                require(key not in fixed and key not in other_ids, 'CONFLICT')
                fixed[key] = (target, identity in revoked)
                for directory in ('startups', 'handoffs'):
                    require(not os.path.lexists(manager.state/directory/(key+'.json')), 'CONFLICT')
                original = self.native(target)
                matches = [row for row in records if row['target']['operationId'] == key]
                require(all(all(row['target'][k] == target[k] for k in
                    ('directory', 'operationId', 'action', 'requestTag')) for row in matches), 'CONFLICT')
                if identity in revoked:
                    require(original is None and all(row['state'] in ('RESERVED', 'NOT_ADMITTED') for row in matches), 'UNSAFE_JOURNAL')
                elif original is None:
                    promised['operations'].add(key)
                    if not matches: shared.add(key)
        anonymous = 0
        for row in records:
            target = row['target']; identity = target['operationId']
            if target['directory'] == 'handoffs':
                if identity in authorities:
                    require(target['requestTag'] == authorities[identity]['requestTag']
                        and row['state'] in ('RESERVED', 'INTAKE', 'TERMINAL'), 'CONFLICT')
                elif row['state'] in ('RESERVED', 'INTAKE'):
                    anonymous += 1
            elif row['state'] in ('RESERVED', 'INTAKE') and not (identity in fixed and fixed[identity][1]):
                if self.native(target) is None: promised[target['directory']].add(identity)
        if native is not None:
            identity = native['operationId']
            if identity in fixed:
                target, retired = fixed[identity]
                require(not retired and all(native[k] == target[k] for k in
                    ('directory', 'operationId', 'action', 'requestTag')), 'CONFLICT')
            if self.native(native) is None: promised[native['directory']].add(identity)
        used = dict(operations=manager.active_records('operations',present['operations'],inventory=inventory)+len(promised['operations'])+2*anonymous,
            startups=manager.active_records('startups',present['startups'],inventory=inventory)+len(promised['startups']),
            admissions=manager.active_records('sender-admissions',[r['admissionId'] for r in records],inventory=inventory)+len(shared)+2*anonymous,
            handoffs=manager.active_records('handoffs',authorities,inventory=inventory)+anonymous)
        require(used['operations'] <= MAX_OPERATIONS and used['admissions'] <= 256
            and used['startups'] <= 32 and used['handoffs'] <= 32, 'CAPACITY')
        return used

    def owner(self, source, pid, uid, daemon, recovery):
        require(source in ('gwt', 'recovery', 'local-admin'), 'FORBIDDEN')
        if source == 'gwt': self.manager.gwt_sender_owner(pid, uid, daemon)
        elif source == 'recovery':
            require(recovery is not None and uid == recovery, 'FORBIDDEN')
            self.manager.recovery_sender_owner(pid, uid)
        else: require(uid == 0, 'FORBIDDEN')
        process = self.manager.writer_process(pid)
        require(process is not None and process[0] == uid, 'FORBIDDEN')
        return dict(pid=pid, uid=uid, startTicks=process[1], bootId=Path('/proc/sys/kernel/random/boot_id').read_text().strip())

    def target(self, wire, source, pid, uid, daemon):
        request = wire
        if source == 'gwt':
            require(request.get('action') == 'gwt-bound-request', 'FORBIDDEN')
            request = self.manager.unwrap_gwt_request(request, pid, uid, daemon)
        action = request.get('action'); continuation = False; directory = 'operations'
        if source == 'recovery':
            require(action in ('restore', 'generation-restore', 'core-start', 'core-start-after-maintenance', 'generation-handoff-command'), 'FORBIDDEN')
        if action == 'generation-handoff-command':
            component = self.manager.handoff_component(); grant = component.authenticate(request.get('token'))
            command = request.get('command'); require(command in ('publish', 'continue', 'start', 'start-renew'), 'FORBIDDEN')
            native = component.renewal_request(grant, request) if command == 'start-renew' else component.operation_request(grant, start=command == 'start')
            if command == 'continue':
                receipt = component.generations.recovery_receipt(native['operationId'])
                require(receipt is not None and hashlib.sha256(receipt[0]).hexdigest() == request.get('expectedRecoveryReceiptSha256'), 'UNRESOLVED_OPERATION')
                component.publication_matches(grant, receipt[1]['publication']); continuation = True
        elif action == 'generation-publication-recover':
            component, _ = self.manager.generation_component(); identity = operation_id(request.get('operationId'))
            receipt = component.recovery_receipt(identity)
            require(receipt is not None and hashlib.sha256(receipt[0]).hexdigest() == request.get('expectedRecoveryReceiptSha256'), 'UNRESOLVED_OPERATION')
            original = self.manager.record(identity); require(original is not None and original['action'] == 'generation-publish', 'UNRESOLVED_OPERATION')
            return dict(directory='operations', operationId=identity, action='generation-publish', requestTag=original['requestTag'], continuation=True)
        elif action == 'generation-cancel-recover':
            identity = operation_id(request.get('operationId')); digest(request.get('expectedCancellationSha256'))
            original = self.manager.record(identity)
            require(original is not None and original['action'] == 'generation-cancel' and original['state'] == 'INTENT', 'UNRESOLVED_OPERATION')
            return dict(directory='operations', operationId=identity, action='generation-cancel', requestTag=original['requestTag'], continuation=True)
        else:
            require(action in SENDER_MUTATIONS, 'FORBIDDEN')
            native = request
        action = native['action']
        if action=='generation-handoff-create':
            for key in ('handoffId','publicationId','startOperationId'):self.manager.require_not_archive_id(operation_id(native.get(key)))
        if action in ('core-start', 'core-start-after-maintenance'): directory = 'startups'
        elif action == 'generation-handoff-create': directory = 'handoffs'
        identity = operation_id(native.get('handoffId') if directory == 'handoffs' else native.get('operationId'))
        return dict(directory=directory, operationId=identity, action=action, requestTag=self.tag(native), continuation=continuation)

    def native(self, target):
        path = self.manager.state/target['directory']/(target['operationId']+'.json')
        try:
            raw = self.manager.read(path, 8192 if target['directory'] == 'handoffs' else MAX_FRAME)
            value = decode(raw)
        except FileNotFoundError: return None
        try:
            if target['directory'] == 'operations': value = validate_record(value, target['operationId'])
            elif target['directory'] == 'startups': value = validate_start(value, target['operationId'])
            else:
                require(stat.S_IMODE(path.lstat().st_mode) == 0o400 and raw == encode(value), 'UNSAFE_JOURNAL')
                value = validate_handoff_authority(value, target['operationId'], self.secret())
        except LifecycleRefused: raise Failure('UNSAFE_JOURNAL') from None
        require(value['requestTag'] == target['requestTag'], 'CONFLICT')
        if target['directory'] == 'operations': require(value['action'] == target['action'], 'CONFLICT')
        return value

    def settled(self, value):
        if value['state'] == 'NOT_ADMITTED':
            self.require_no_native(value['target']['operationId'], 'UNSAFE_JOURNAL'); return True
        native = self.native(value['target'])
        success = native is not None and (value['target']['directory'] == 'handoffs' or native.get('state') == 'SUCCEEDED')
        if value['state'] == 'TERMINAL': require(success, 'UNSAFE_JOURNAL')
        if success:
            require(value['state'] != 'RESERVED', 'UNSAFE_JOURNAL')
            if value['state'] == 'INTAKE' and not self.archive_claimed(value): value.update(self.write(dict(value, state='TERMINAL')))
            return True
        return False

    def archive_claimed(self,value):
        return any(row['directory']=='sender-admissions' and row['operationId']==value['admissionId']
            for intent,_ in self.manager.archives()['requests'].values() for row in intent['entries'])

    def require_no_native(self, identity, reason='UNRESOLVED_OPERATION'):
        # A closed original must not conceal a different native action/directory.
        operation_id(identity)
        for name in ('operations', 'startups', 'handoffs'):
            parent = self.manager.state/name
            if os.path.lexists(parent): self.manager.directory(parent, private=True)
            require(not os.path.lexists(parent/(identity+'.json')), reason)

    def require_settled(self):
        if not os.path.lexists(self.directory): return
        with self.locked():
            current = getattr(self.context, 'current', None)
            excluded = set() if current is None else {current['admissionId'], current['parentAdmissionId']}
            for value in self.records():
                if value['admissionId'] not in excluded: require(self.settled(value), 'UNRESOLVED_OPERATION')

    @staticmethod
    def view(value, *, fresh=False):
        return dict(schema=1, admissionId=value['admissionId'], state=value['state'], source=value['source'],
            namespaceSha256=value['namespaceSha256'], nativeOperationId=value['target']['operationId'],
            nativeAction=value['target']['action'], newlyReserved=fresh)

    def private_fence(self, request, pid, uid, daemon, recovery):
        return self.manager.journal_module().private_fence(self,request,pid,uid,daemon,recovery)

    @staticmethod
    def private_fence_view(value):
        return dict(schema=1,state='PRIVATE_FENCE_RECORDED',admissionId=value['admissionId'],source=value['source'],
            namespaceSha256=value['namespaceSha256'],nativeOperationId=value['target']['operationId'],
            nativeAction=value['target']['action'],privateProof=value['privateProof'],
            receiptSha256=hashlib.sha256(encode(value)).hexdigest(),credentialsChanged=False,startRequested=False)

    def reserve(self, request, pid, uid, daemon, recovery):
        fields(request, {'schema', 'action', 'admissionId', 'source', 'namespaceSha256', 'request'})
        require(type(request['schema']) is int and request['schema'] == 1)
        identity = operation_id(request['admissionId'])
        with self.locked():
            self.manager.maintenance(); owner = self.owner(request['source'], pid, uid, daemon, recovery)
            require(request['namespaceSha256'] == self.manager.gwt_namespace()['namespaceSha256'], 'CONFLICT')
            target = self.target(request['request'], request['source'], pid, uid, daemon)
            tag = self.tag(request['request']); previous = self.load(identity)
            if previous is not None:
                require(previous['source'] == request['source'] and previous['owner']['uid'] == uid
                    and previous['requestTag'] == tag and previous['target'] == target, 'CONFLICT')
                return self.view(previous)
            self.manager.require_not_archive_id(identity)
            self.manager.require_unrevoked_operation(target['operationId'])
            records = self.records(); parent = None; denied = False
            for value in records:
                same = all(value['target'][k] == target[k] for k in ('directory', 'operationId', 'action', 'requestTag'))
                if same and target['continuation'] and not value['target']['continuation'] and value['state'] == 'INTAKE':
                    require(parent is None and not self.settled(value), 'CONFLICT'); parent = value['admissionId']; continue
                require(value['target']['operationId'] != target['operationId'], 'CONFLICT')
                if not self.settled(value): denied = True
            prior = self.native(target)
            require(prior is None or target['continuation'] and prior.get('state') == 'INTENT', 'CONFLICT')
            try:
                ignored = {} if not target['continuation'] else {
                    'recovering_cancel' if target['action'] == 'generation-cancel' else 'recovering_publication': target['operationId']}
                Lifecycle(self.manager.root, self.manager.owner).check_records(**ignored)
            except LifecycleUnresolved: denied = True
            except LifecycleRefused: raise Failure('UNSAFE_JOURNAL') from None
            # A rejected continuation must not claim the already existing native original was absent.
            require(not denied or prior is None, 'UNRESOLVED_OPERATION')
            value = dict(schema=1, purpose=SENDER_ADMISSION_PURPOSE, admissionId=identity, source=request['source'],
                namespaceSha256=request['namespaceSha256'], owner=owner, requestTag=tag, target=target,
                parentAdmissionId=parent, state='NOT_ADMITTED' if denied else 'RESERVED')
            with self.manager.lock(self.manager.state/'admission.lock', False):
                self.require_capacity(admission=value)
                return self.view(self.write(value, create=True), fresh=not denied)

    def read(self, request, pid, uid, daemon, recovery, *, close=False):
        fields(request, {'schema', 'action', 'admissionId', 'source', 'namespaceSha256'})
        require(type(request['schema']) is int and request['schema'] == 1)
        with self.locked():
            self.manager.maintenance(); self.owner(request['source'], pid, uid, daemon, recovery)
            require(request['namespaceSha256'] == self.manager.gwt_namespace()['namespaceSha256'], 'CONFLICT')
            value = self.load(operation_id(request['admissionId'])); require(value is not None, 'NOT_FOUND')
            require(value['purpose']==SENDER_ADMISSION_PURPOSE,'FORBIDDEN')
            require(value['source'] == request['source'] and value['owner']['uid'] == uid
                and value['namespaceSha256'] == request['namespaceSha256'], 'FORBIDDEN')
            if close:
                # Only an explicit close can seal a reservation; reads never settle missing native originals.
                require(value['state'] in ('RESERVED', 'NOT_ADMITTED') and self.native(value['target']) is None, 'UNRESOLVED_OPERATION')
                self.require_no_native(value['target']['operationId'])
                if value['state'] == 'RESERVED': value = self.write(dict(value, state='NOT_ADMITTED'))
            elif self.settled(value) and value['state'] not in ('TERMINAL', 'NOT_ADMITTED') and not self.archive_claimed(value):
                value = self.write(dict(value, state='TERMINAL'))
            result=self.view(value)
            if value['state']=='INTAKE' and self.archive_claimed(value):result['state']='TERMINAL'
            return result

    def execute(self, request, pid, uid, daemon, recovery, dispatch):
        fields(request, {'schema', 'action', 'admissionId', 'source', 'namespaceSha256', 'request'})
        require(type(request['schema']) is int and request['schema'] == 1)
        with self.locked():
            self.manager.maintenance(); owner = self.owner(request['source'], pid, uid, daemon, recovery)
            value = self.load(operation_id(request['admissionId'])); require(value is not None, 'NOT_FOUND')
            require(value['source'] == request['source'] and value['namespaceSha256'] == request['namespaceSha256']
                == self.manager.gwt_namespace()['namespaceSha256'] and value['owner'] == owner
                and hmac.compare_digest(value['requestTag'], self.tag(request['request'])), 'CONFLICT')
            require(value['state'] == 'RESERVED', 'UNRESOLVED_OPERATION')
            self.manager.require_unrevoked_operation(value['target']['operationId'])
            require(self.target(request['request'], request['source'], pid, uid, daemon) == value['target'], 'CONFLICT')
            self.context.current = value
            try:
                self.require_settled()
                with self.manager.lock(self.manager.state/'admission.lock', False):
                    # Also cover reservations saved by an older version: no new
                    # INTAKE is allowed to discover capacity only in its writer.
                    self.require_capacity()
                    value = self.write(dict(value, state='INTAKE')); self.context.current = value
                # Persist intake before any native handler, even one that fails its own preflight.
                result = dispatch(request['request'])
                if self.settled(value) and value['parentAdmissionId'] is not None:
                    parent = self.load(value['parentAdmissionId']); require(parent is not None, 'UNSAFE_JOURNAL'); self.settled(parent)
                return result
            finally: self.context.current = None


class Manager:
    """The root and cipher arguments exist for isolated tests, never on the wire or command line."""
    def __init__(self, root=Path("/"), owner=0, cipher=None):
        self.store = Store(root, owner)
        self.root = self.store.root
        self.owner = owner
        self.state = self.store.path(STATE)
        self.operations = self.state / "operations"
        self.cipher = list(CIPHER if cipher is None else cipher)
        self.sender_admissions = SenderAdmissions(self)

    def archives(self):
        try: return archive_inventory(self)
        except (LifecycleRefused, FileNotFoundError): raise Failure('UNSAFE_JOURNAL') from None

    def active_records(self, directory, identities, *, inventory=None):
        try: return active_journal_count(self,directory,identities,inventory=inventory)
        except (LifecycleRefused, FileNotFoundError): raise Failure('UNSAFE_JOURNAL') from None

    @staticmethod
    def archive_view(identity, intent, receipt):
        result=dict(schema=1,archiveId=identity,namespaceSha256=intent['namespaceSha256'],
            state='ARCHIVE_RECORDED' if receipt is not None else 'UNKNOWN',scope='ROOT_JOURNAL_ACTIVE_CAPACITY_ONLY',
            entries=intent['entries'],entriesSha256=intent['entriesSha256'],intentSha256=hashlib.sha256(encode(intent)).hexdigest(),
            originalsRetained=True,credentialsChanged=False,startRequested=False)
        if receipt is not None:result['receiptSha256']=hashlib.sha256(encode(receipt)).hexdigest()
        return result

    def journal_module(self):
        try:return Lifecycle(self.root,self.owner).journal_module()
        except (LifecycleRefused,OSError,ValueError):raise Failure('COHORT_UNAVAILABLE') from None

    def archive_journal(self, request, pid, uid, daemon, recovery):
        return self.journal_module().archive_journal(self,request,pid,uid,daemon,recovery)

    def recovery_sender_owner(self, pid, uid):
        output = subprocess.run(['/usr/bin/systemctl', '--system', '--no-ask-password', '--no-pager', 'show',
            'kura-key-recovery.service', '--property=Id', '--property=ActiveState', '--property=SubState',
            '--property=MainPID', '--property=ControlPID', '--property=User', '--property=ControlGroup'],
            capture_output=True, text=True, check=False, timeout=5, close_fds=True, cwd='/',
            env={'PATH':'/usr/bin:/bin','LANG':'C'})
        require(output.returncode == 0 and len(output.stdout) <= 4096, 'FORBIDDEN')
        pairs = [line.split('=', 1) for line in output.stdout.splitlines() if '=' in line]
        require(len(pairs) == 7 and len(dict(pairs)) == 7, 'FORBIDDEN'); unit = dict(pairs)
        require(unit == dict(Id='kura-key-recovery.service', ActiveState='active', SubState='running',
            MainPID=str(pid), ControlPID='0', User='kura-key-recovery', ControlGroup='/system.slice/kura-key-recovery.service')
            and self.writer_process(pid) is not None and self.writer_process(pid)[0] == uid, 'FORBIDDEN')

    def require_unrevoked_operation(self, identity):
        operation_id(identity)
        self.require_not_archive_id(identity)
        try:
            revoked = handoff_revocations(self)
        except LifecycleRefused:
            raise Failure('UNSAFE_JOURNAL') from None
        require(all(identity not in (authority['request']['publicationId'], authority['request']['startOperationId'])
            for _, authority, _ in revoked.values()), 'HANDOFF_REVOKED')

    def require_not_archive_id(self, identity):
        operation_id(identity)
        require(not any(os.path.lexists(self.state/'archives'/(identity+suffix))
            for suffix in ('.intent.json','.receipt.json')),'CONFLICT')
        parent=self.state/'sender-admissions'
        if os.path.lexists(parent):
            self.directory(parent,private=True)
            for path in parent.iterdir():
                require(path.name.endswith('.json'),'UNSAFE_JOURNAL')
                value=self.sender_admissions.load(operation_id(path.name[:-5]))
                if value['purpose']==PRIVATE_FENCE_PURPOSE:
                    require(identity not in value['privateProof']['blockedIds']+[value['admissionId']],'CONFLICT')

    def gwt_namespace(self):
        self.directory(self.state, private=True)
        try:
            return gwt_namespace(self.state, self.read(self.state / 'journal.key', 32))
        except LifecycleRefused:
            raise Failure('UNSAFE_JOURNAL') from None

    def gwt_sender_owner(self, pid, uid, daemon):
        # The effective SystemService directory is reported by the actual Main JVM.
        # Root never executes a property provider or traverses the Core-private data tree.
        require(type(daemon) is int and daemon > 0 and uid == daemon, 'FORBIDDEN')
        core, _ = self.generation_component()
        unit = core.unit(generation_mode=os.path.lexists(self.store.path(GENERATION_RECEIPT_PATH)))
        process = self.writer_process(pid)
        require(unit['ActiveState'] == 'active' and unit['SubState'] == 'running'
            and unit['ControlPID'] == '0' and int(unit['MainPID']) == pid
            and unit['ControlGroup'] == '/system.slice/kura.service'
            and re.fullmatch(r'[0-9a-f]{32}', unit['InvocationID']) is not None
            and process is not None and process[0] == uid
            and core.process_group(pid) == unit['ControlGroup'], 'UNMANAGED_CORE')

    def bind_gwt_sender(self, request, pid, uid, daemon):
        fields(request, {'schema', 'action'} | GWT_DATA_FIELDS | GWT_NAMESPACE_FIELDS)
        require(type(request['schema']) is int and request['schema'] == 1 and request['action'] == 'gwt-sender-bind')
        try:
            validate_gwt_data({k: request[k] for k in GWT_DATA_FIELDS})
        except LifecycleRefused:
            raise Failure('INVALID_ARGUMENT') from None
        require(request['dataUid'] == uid, 'FORBIDDEN')
        with self.lock(self.state / 'admission.lock', True):
            self.maintenance(); self.gwt_sender_owner(pid, uid, daemon)
            namespace = self.gwt_namespace()
            require(all(request[k] == namespace[k] for k in GWT_NAMESPACE_FIELDS), 'CONFLICT')
            binding = dict(schema=1, purpose=GWT_BINDING_PURPOSE, **namespace,
                **{k: request[k] for k in GWT_DATA_FIELDS})
            path = self.state / 'gwt-sender.json'
            if os.path.lexists(path):
                try: previous = validate_gwt_binding(decode(self.read(path, 8192)))
                except LifecycleRefused: raise Failure('UNSAFE_JOURNAL') from None

                require(previous == binding, 'CONFLICT')
            else:
                self.atomic(path, encode(binding), no_replace=True)
            # No key/start UUID is admitted, completed, retried or inferred by registration.
            return dict(binding, state='GWT_SENDER_BOUND')

    def unwrap_gwt_request(self, request, pid, uid, daemon):
        fields(request, {'schema', 'action', 'binding', 'request'})
        require(type(request['schema']) is int and request['schema'] == 1)
        try: binding = validate_gwt_binding(request['binding'])
        except LifecycleRefused: raise Failure('INVALID_ARGUMENT') from None
        with self.lock(self.state / 'admission.lock', False):
            self.maintenance(); self.gwt_sender_owner(pid, uid, daemon)
            try: original = validate_gwt_binding(decode(self.read(self.state / 'gwt-sender.json', 8192)))
            except LifecycleRefused: raise Failure('UNSAFE_JOURNAL') from None
            namespace = self.gwt_namespace()
            require(binding == original and all(binding[k] == namespace[k] for k in GWT_NAMESPACE_FIELDS), 'CONFLICT')
        inner = request['request']
        require(isinstance(inner, dict) and inner.get('action') in GWT_MUTATIONS | GWT_ORIGINAL_READS | ARCHIVE_ACTIONS | PRIVATE_FENCE_ACTIONS, 'FORBIDDEN')
        return inner

    def directory(self, path, private=False):
        # Do not create or repair directories as a side effect of status or backup.
        path = Path(path)
        current = self.root
        for part in ("", *path.relative_to(self.root).parts):
            current = current / part
            m = current.lstat()
            require(stat.S_ISDIR(m.st_mode) and m.st_uid == self.owner and not m.st_mode & 0o022,
                    "UNSAFE_FILESYSTEM")
        if private:
            require(not m.st_mode & 0o077, "UNSAFE_FILESYSTEM")

    @contextlib.contextmanager
    def lock(self, path, exclusive):
        self.directory(path.parent, private=True)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            m = os.fstat(fd)
            require(stat.S_ISREG(m.st_mode) and m.st_nlink == 1 and m.st_uid == self.owner
                    and not m.st_mode & 0o077, "UNSAFE_FILESYSTEM")
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Failure("BUSY") from None
            yield
        finally:
            os.close(fd)

    def read(self, path, limit=MAX_FRAME):
        try:
            return self.store.read(path, private=True, limit=limit)
        except Refused:
            raise Failure("UNSAFE_FILESYSTEM") from None

    def atomic(self, path, data, mode=0o600, no_replace=False):
        self.directory(path.parent, private=True)
        temporary = path.parent / (".key-service-" + secrets.token_hex(16))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if no_replace:
                # Unlike link/unlink, renameat2 never exposes a two-link canonical secret.
                  rename_no_replace(temporary, path)
            else:
                if os.path.lexists(path):
                    self.read(path)
                os.replace(temporary, path)
            self.sync(path.parent)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def sync(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def canonical(self, allow_missing=False, *, allow_generations=False):
        directory = self.store.path("/etc/kura/credentials")
        self.directory(directory, private=True)
        # A single-key artifact must never be offered as a complete rotated-key backup.
        # lexists also fences malformed entries and dangling links; no fallback to v1.
        published = os.path.lexists(self.state / 'generation-current.json')
        if not allow_generations and not published and self.operations.is_dir():
            for path in self.operations.iterdir():
                require(path.name.endswith('.json'), 'UNSAFE_JOURNAL')
                record = self.record(operation_id(path.name[:-5]))
                if record['action'] == 'generation-publish' and record['state'] == 'SUCCEEDED':
                    published = True
                    break
        require(allow_generations or not published and not any(os.path.lexists(self.store.path(path))
                                            for path in (RING_PATH, GENERATION_RECEIPT_PATH)), "GENERATION_REQUIRED")
        proof = receipt(decode(self.read(self.store.path(RECEIPT_PATH), 8192)))
        try:
            key = self.read(self.store.path(KEY_PATH), 32)
        except FileNotFoundError:
            require(allow_missing, "KEY_MISSING")
            key = None
        if key is not None:
            receipt(proof, key)
        return key, proof

    def generation_receipt(self):
        self.directory(self.store.path("/etc/kura/credentials"), private=True)
        try:
            return parse_generation_receipt(self.read(self.store.path(GENERATION_RECEIPT_PATH), 2048))
        except FileNotFoundError:
            raise Failure("KEY_GENERATIONS_MISSING") from None
        except (OSError, Refused):
            raise Failure("UNSAFE_FILESYSTEM") from None

    def generations(self):
        current, proof = self.canonical(allow_generations=True)
        trusted = self.generation_receipt()
        try:
            raw = self.read(self.store.path(RING_PATH), 512)
        except FileNotFoundError:
            raise Failure("KEY_GENERATIONS_MISSING") from None
        except OSError:
            raise Failure("UNSAFE_FILESYSTEM") from None
        try:
            active, metadata = key_generations(raw)
        except Failure:
            raise Failure("UNSAFE_FILESYSTEM") from None
        require(hmac.compare_digest(active, current), "UNSAFE_FILESYSTEM")
        require(metadata == trusted, "UNSAFE_FILESYSTEM")
        return raw, metadata, proof

    def crypt(self, encrypt, password, value):
        require(len(value) <= 32768)
        frame = b"KKB1" + bytes([1 if encrypt else 2]) + struct.pack("!I", len(password)) + password
        frame += struct.pack("!I", len(value)) + value
        try:
            result = subprocess.run(self.cipher, input=frame, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                                    timeout=20, check=False, close_fds=True, cwd="/")
        except subprocess.TimeoutExpired:
            raise Failure("CIPHER_UNAVAILABLE") from None
        require(result.returncode == 0 and 0 < len(result.stdout) <= 32768,
                "CIPHER_UNAVAILABLE" if encrypt else "BACKUP_REJECTED")
        return result.stdout

    def unpack(self, envelope, password):
        fields(envelope, {"format", "operationId", "encrypted"})
        require(envelope["format"] == FORMAT, "BACKUP_REJECTED")
        original = operation_id(envelope["operationId"])
        require(isinstance(envelope["encrypted"], str) and len(envelope["encrypted"]) <= 32768)
        try:
            encrypted = base64.b64decode(envelope["encrypted"], validate=True)
        except ValueError:
            raise Failure("BACKUP_REJECTED") from None
        data = decode(self.crypt(False, password, encrypted))
        fields(data, {"schema", "purpose", "operationId", "createdAt", "key", "receipt"})
        require(type(data["schema"]) is int and data["schema"] == 1 and data["purpose"] == FORMAT,
                "BACKUP_REJECTED")
        require(data["operationId"] == original and isinstance(data["createdAt"], str), "BACKUP_REJECTED")
        require(isinstance(data["key"], str), "BACKUP_REJECTED")
        try:
            key = base64.b64decode(data["key"], validate=True)
        except ValueError:
            raise Failure("BACKUP_REJECTED") from None
        receipt(data["receipt"], key)
        return key, data

    def unpack_generations(self, envelope, password):
        fields(envelope, {"format", "operationId", "encrypted"})
        require(envelope["format"] == GENERATION_FORMAT, "BACKUP_REJECTED")
        original = operation_id(envelope["operationId"])
        require(isinstance(envelope["encrypted"], str) and 0 < len(envelope["encrypted"]) <= 32768)
        try:
            encrypted = base64.b64decode(envelope["encrypted"], validate=True)
        except ValueError:
            raise Failure("BACKUP_REJECTED") from None
        data = decode(self.crypt(False, password, encrypted))
        fields(data, {"schema", "purpose", "operationId", "createdAt", "keyring", "receipt"})
        require(type(data["schema"]) is int and data["schema"] == 1
                and data["purpose"] == GENERATION_FORMAT and data["operationId"] == original,
                "BACKUP_REJECTED")
        require(isinstance(data["createdAt"], str) and 0 < len(data["createdAt"]) <= 64
                and isinstance(data["keyring"], str) and 0 < len(data["keyring"]) <= 684, "BACKUP_REJECTED")
        try:
            created = datetime.datetime.fromisoformat(data["createdAt"])
            require(created.tzinfo is not None and created.utcoffset() is not None, "BACKUP_REJECTED")
            raw = base64.b64decode(data["keyring"], validate=True)
            active, metadata = key_generations(raw)
            receipt(data["receipt"], active)
        except (ValueError, Failure):
            raise Failure("BACKUP_REJECTED") from None
        return raw, metadata, data

    def record(self, identity):
        path = self.operations / (identity + ".json")
        try:
            record = decode(self.read(path))
        except FileNotFoundError:
            return None
        try:
            record = validate_record(record, identity)
        except LifecycleRefused:
            raise Failure("UNSAFE_JOURNAL") from None
        if record['action'] in ('generation-cancel', 'generation-start-lease'):
            original = dict(schema=1, action=record['action'], operationId=identity, **record['intent'])
            secret = self.read(self.state / 'journal.key', 32)
            require(len(secret) == 32 and hmac.compare_digest(record['requestTag'],
                    hmac.new(secret, encode(original), hashlib.sha256).hexdigest()), 'UNSAFE_JOURNAL')
        return record

    def public_record(self, record):
        if record is None:
            return {"schema": 1, "state": "NOT_FOUND"}
        if record["state"] == "INTENT":
            return {"schema": 1, "operationId": record["operationId"], "state": "UNKNOWN"}
        require(isinstance(record["response"], dict), "UNSAFE_JOURNAL")
        return record["response"]

    def journal_admission(self, request, *, directory='operations'):
        self.require_not_archive_id(request['operationId'])
        self.directory(self.operations, private=True)
        names = list(self.operations.iterdir())
        for path in names:
            require(path.name.endswith(".json"), "UNSAFE_JOURNAL")
            identity = operation_id(path.name[:-5])
            record = self.record(identity)
            require(record is not None and record["state"] != "INTENT", "UNRESOLVED_OPERATION")
        self.sender_admissions.require_capacity(native=self.sender_admissions.native_target(request, directory=directory))

    def maintenance(self):
        try:
            require(Lifecycle(self.root, self.owner).fence() is None, "MAINTENANCE")
        except LifecycleRefused:
            raise Failure("UNSAFE_JOURNAL") from None

    def settled(self, *, recovering_publication=None):
        self.sender_admissions.require_settled()
        try:
            policy = Lifecycle(self.root, self.owner)
            if recovering_publication is None:
                policy.check_records()
            else:
                policy.check_records(recovering_publication=recovering_publication)
        except LifecycleUnresolved:
            raise Failure("UNRESOLVED_OPERATION") from None
        except LifecycleRefused:
            raise Failure("UNSAFE_JOURNAL") from None

    @staticmethod
    def generation_restore_supported():
        return sys.platform == "linux" and hasattr(ctypes.CDLL(None), "renameat2")

    def generation_restore_state(self, raw, metadata):
        active, _ = key_generations(raw)
        current, proof = self.canonical(True, allow_generations=True)
        trusted = self.generation_receipt()
        require(trusted["activeKeySha256"] == proof["keySha256"], "UNSAFE_FILESYSTEM")
        require(metadata == trusted, "CONFLICT")
        require(current is None or hmac.compare_digest(current, active), "CONFLICT")
        try:
            ring = self.read(self.store.path(RING_PATH), 512)
        except FileNotFoundError:
            ring = None
        except OSError:
            raise Failure("UNSAFE_FILESYSTEM") from None
        require(ring is None or hmac.compare_digest(ring, raw), "CONFLICT")
        return active, current, ring, proof

    def restore_generations(self, request, *, recovery_only):
        fields(request, {"schema", "action", "operationId", "passphrase", "backup", "expectedRingSha256"})
        identity = operation_id(request["operationId"])
        password = passphrase(request["passphrase"])
        expected = digest(request["expectedRingSha256"])
        with self.lock(self.state / "admission.lock", True):
            self.maintenance()
            secret = self.read(self.state / "journal.key", 32)
            require(len(secret) == 32, "UNSAFE_JOURNAL")
            tag = hmac.new(secret, encode(request), hashlib.sha256).hexdigest()
            prior = self.record(identity)
            if prior is not None:
                require(hmac.compare_digest(prior["requestTag"], tag), "CONFLICT")
                return self.public_record(prior)
            self.settled()
            self.journal_admission(request)
            with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), True):
                raw, metadata, _ = self.unpack_generations(request["backup"], password)
                require(metadata["ringSha256"] == expected, "CONFLICT")
                active, current, ring, proof = self.generation_restore_state(raw, metadata)
                missing = current is None or ring is None
                require(not recovery_only or missing, "CONFLICT")
                require(not missing or self.generation_restore_supported(), "UNSUPPORTED")
                record = dict(schema=1, operationId=identity, action="generation-restore",
                              requestTag=tag, state="INTENT", response=None)
                try:
                    self.atomic(self.operations / (identity + ".json"), encode(record))
                    # Only missing, strictly original bytes may be published. No overwrite or new generation.
                    if ring is None:
                        self.atomic(self.store.path(RING_PATH), raw, mode=0o400, no_replace=True)
                    if current is None:
                        self.atomic(self.store.path(KEY_PATH), active, mode=0o400, no_replace=True)
                    restored, observed, observed_proof = self.generations()
                    require(restored == raw and observed == metadata and observed_proof == proof, "UNKNOWN")
                    response = dict(schema=1, operationId=identity, action="generation-restore", state="SUCCEEDED",
                                    ringSha256=metadata["ringSha256"], activeKeySha256=metadata["activeKeySha256"],
                                    activeKeyRestored=current is None, keyringRestored=ring is None,
                                    existingReceiptPreserved=True)
                    record.update(state="SUCCEEDED", response=response)
                    self.atomic(self.operations / (identity + ".json"), encode(record))
                    return response
                except (OSError, Failure, Refused):
                    raise Failure("UNKNOWN") from None

    def create_generation_backup(self, request):
        fields(request, {"schema", "action", "operationId", "passphrase"})
        identity = operation_id(request["operationId"])
        password = passphrase(request["passphrase"])
        with self.lock(self.state / "admission.lock", True):
            self.maintenance()
            journal_key = self.read(self.state / "journal.key", 32)
            require(len(journal_key) == 32, "UNSAFE_JOURNAL")
            tag = hmac.new(journal_key, encode(request), hashlib.sha256).hexdigest()
            existing = self.record(identity)
            if existing is not None:
                require(hmac.compare_digest(existing["requestTag"], tag), "CONFLICT")
                return self.public_record(existing)
            self.settled()
            self.journal_admission(request)
            with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), False):
                raw, _, proof = self.generations()
                record = dict(schema=1, operationId=identity, action="generation-backup-create",
                              requestTag=tag, state="INTENT", response=None)
                try:
                    self.atomic(self.operations / (identity + ".json"), encode(record))
                    payload = dict(schema=1, purpose=GENERATION_FORMAT, operationId=identity,
                                   createdAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                   keyring=base64.b64encode(raw).decode("ascii"), receipt=proof)
                    encrypted = self.crypt(True, password, encode(payload))
                    response = dict(schema=1, operationId=identity, state="SUCCEEDED", action=record["action"],
                                    backup=dict(format=GENERATION_FORMAT, operationId=identity,
                                                encrypted=base64.b64encode(encrypted).decode("ascii")))
                    record.update(state="SUCCEEDED", response=response)
                    self.atomic(self.operations / (identity + ".json"), encode(record))
                    return response
                except (OSError, Failure, Refused):
                    raise Failure("UNKNOWN") from None

    def generation_source(self):
        if any(os.path.lexists(self.store.path(p)) for p in (RING_PATH, GENERATION_RECEIPT_PATH)):
            raw, metadata, proof = self.generations()
            keys, _, legacy = key_generation_entries(raw)
        else:
            current, proof = self.canonical()
            keys, legacy, raw, metadata = [current], 0, None, None
        source = dict(keySha256=proof["keySha256"], ringSha256=metadata["ringSha256"] if metadata else None)
        return keys, legacy, raw, metadata, proof, source

    def require_generation_cohort(self):
        try:
            return Lifecycle(self.root, self.owner).generation_assets()
        except (OSError, ValueError, LifecycleRefused):
            raise Failure('COHORT_UNAVAILABLE') from None

    def generation_module(self, name):
        require(name in ('kura_key_generation', 'kura_key_validation'))
        policy = Lifecycle(self.root, self.owner)
        binding = self.require_generation_cohort()
        home = self.store.path('/opt/eclipse/kura').resolve(strict=True)
        raw = policy.read(home / 'libexec/key-backup/manifest.json', private=False)
        require(hashlib.sha256(raw).hexdigest() == binding['manifestSha256'], 'COHORT_CHANGED')
        relative = 'bin/' + name + '.py'
        expected = decode(raw)['generation']['files'][relative]
        # Cohort-pinned executable sources have a separate bound from wire frames.
        source = policy.read(home / relative, limit=131072, private=False)
        require(hashlib.sha256(source).hexdigest() == expected, 'COHORT_CHANGED')
        namespace = {'__name__': name, '__file__': str(home / relative)}
        exec(compile(source, str(home / relative), 'exec'), namespace)
        return namespace, binding

    def generation_component(self):
        namespace, binding = self.generation_module('kura_key_generation')
        return namespace['Generations'](self), binding

    def handoff_component(self):
        namespace, _ = self.generation_module('kura_key_generation')
        return namespace['Handoffs'](self)

    def validation_component(self):
        namespace, _ = self.generation_module('kura_key_validation')
        return namespace['Validation'](self)

    def generation_start_authorized(self, source, cohort):
        if not os.path.lexists(self.state / 'generation-current.json'):
            records = [self.record(p.name[:-5]) for p in self.operations.iterdir()]
            if all(record['action'] != 'generation-publish' for record in records):
                return
        component, binding = self.generation_component()
        require(cohort is None or binding == cohort, 'COHORT_CHANGED')
        component.require_start(source, binding)

    @staticmethod
    def writer_process(pid):
        require(type(pid) is int and pid > 0, 'INVALID_WRITER')
        path = Path('/proc') / str(pid)
        try:
            owner = path.stat().st_uid
            raw = (path / 'stat').read_text()
        except FileNotFoundError:
            return None
        parts = raw.rsplit(')', 1)[1].split()
        require(len(parts) >= 20 and parts[19].isdigit(), 'INVALID_WRITER')
        return owner, parts[19]

    def writer_directory(self, *, create=False):
        parent = self.store.path('/run/kura-key-service')
        self.directory(parent)
        path = parent / 'writers'
        if create and not os.path.lexists(path):
            path.mkdir(mode=0o700)
            self.sync(parent)
        self.directory(path, private=True)
        return path

    def writer_lock(self, *, create=False):
        path = self.writer_directory(create=create) / 'lease.lock'
        if create and not os.path.lexists(path):
            self.atomic(path, b'', no_replace=True)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            value = os.fstat(fd)
            require(stat.S_ISREG(value.st_mode) and value.st_uid == self.owner and value.st_nlink == 1
                    and stat.S_IMODE(value.st_mode) == 0o600 and value.st_size == 0
                    and (value.st_dev, value.st_ino) == (path.lstat().st_dev, path.lstat().st_ino), 'UNSAFE_WRITER_STATE')
            return fd
        except BaseException:
            os.close(fd)
            raise

    def writer_record(self, path):
        value = decode(self.read(path, 4096))
        fields(value, {'schema', 'state', 'pid', 'startTicks', 'bootId', 'uid', 'keySha256', 'ringSha256', 'lockDevice', 'lockInode', 'cohortSha256'})
        require(type(value['schema']) is int and value['schema'] == 1 and value['state'] == 'LEASE_GRANTED'
                and type(value['pid']) is int and 0 < value['pid'] <= 0x7fffffff
                and isinstance(value['startTicks'], str) and re.fullmatch(r'[0-9]{1,20}', value['startTicks']) is not None
                and path.name == str(value['pid']) + '-' + value['startTicks'] + '.json'
                and type(value['uid']) is int and 0 <= value['uid'] < 0xffffffff
                and isinstance(value['bootId'], str)
                and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value['bootId']) is not None
                and type(value['lockDevice']) is int and value['lockDevice'] >= 0
                and type(value['lockInode']) is int and value['lockInode'] > 0, 'UNSAFE_WRITER_STATE')
        digest(value['keySha256'])
        digest(value['cohortSha256'])
        if value['ringSha256'] is not None:
            digest(value['ringSha256'])
        return value

    def writer_registration(self, pid):
        process = self.writer_process(pid)
        require(process is not None, 'WRITER_UNREGISTERED')
        try:
            value = self.writer_record(self.writer_directory() / (str(pid) + '-' + process[1] + '.json'))
        except FileNotFoundError:
            raise Failure('WRITER_UNREGISTERED') from None
        require(value['uid'] == process[0]
                and value['bootId'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'UNSAFE_WRITER_STATE')
        return value

    @contextlib.contextmanager
    def exclusive_writers(self):
        fd = self.writer_lock()
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Failure('WRITERS_ACTIVE') from None
            yield os.fstat(fd)
        finally:
            os.close(fd)

    def acquire_writer_lease(self, request, pid, uid):
        fields(request, {'schema', 'action', 'keySha256', 'ringSha256'})
        require(type(request['schema']) is int and request['schema'] == 1
                and request['action'] == 'writer-lease-acquire' and sys.platform == 'linux', 'INVALID_ARGUMENT')
        digest(request['keySha256'])
        if request['ringSha256'] is not None:
            digest(request['ringSha256'])
        process = self.writer_process(pid)
        require(process is not None and type(uid) is int and uid == process[0], 'INVALID_WRITER')
        with self.lock(self.state / 'admission.lock', True):
            self.maintenance(); self.settled()
            cohort = self.require_generation_cohort()
            with self.lock(self.store.path('/etc/kura/credentials/.provision.lock'), False):
                _, _, _, _, _, source = self.generation_source()
                require(all(request[k] == source[k] for k in source), 'CONFLICT')
                self.generation_start_authorized(source, cohort)
                fd = self.writer_lock(create=True)
                accepted = False
                try:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise Failure('WRITERS_FENCED') from None
                    root = self.writer_directory()
                    records = [p for p in root.iterdir() if p.name != 'lease.lock']
                    require(len(records) <= 64, 'CAPACITY')
                    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
                    live = 0
                    for path in records:
                        require(re.fullmatch(r'[1-9][0-9]*-[0-9]+\.json', path.name) is not None, 'UNSAFE_WRITER_STATE')
                        prior = self.writer_record(path)
                        current = self.writer_process(prior['pid'])
                        if prior['bootId'] != boot or current is None or current != (prior['uid'], prior['startTicks']):
                            # Only ephemeral runtime cache is pruned, never an operation/result journal.
                            path.unlink()
                            self.sync(root)
                        else:
                            live += 1
                    require(live < 64, 'CAPACITY')
                    # Runtime registrations have no operation IDs and never settle key/start intents.
                    metadata = os.fstat(fd)
                    value = dict(schema=1, state='LEASE_GRANTED', pid=pid, startTicks=process[1], uid=uid,
                                 bootId=boot,
                                 lockDevice=metadata.st_dev, lockInode=metadata.st_ino, cohortSha256=cohort['cohortSha256'], **source)
                    path = root / (str(pid) + '-' + process[1] + '.json')
                    require(not os.path.lexists(path), 'WRITER_ALREADY_REGISTERED')
                    self.atomic(path, encode(value), no_replace=True)
                    require(self.writer_process(pid) == process, 'INVALID_WRITER')
                    response = dict(schema=1, state='WRITER_LEASE_GRANTED', peerPid=pid, startTicks=process[1],
                                    lockDevice=metadata.st_dev, lockInode=metadata.st_ino, cohortSha256=cohort['cohortSha256'], **source)
                    accepted = True
                    return response, fd
                finally:
                    if not accepted:
                        os.close(fd)

    def prepared_generation(self, identity):
        record = self.record(identity)
        require(record is not None and record["action"] == "generation-prepare"
                and record["state"] == "SUCCEEDED", "CONFLICT")
        response = record["response"]
        directory = self.state / "generations" / identity
        self.directory(directory, private=True)
        history_bytes = self.read(directory / "history.json", 8192)
        require(hashlib.sha256(history_bytes).hexdigest() == response["historySha256"], "UNSAFE_JOURNAL")
        history = decode(history_bytes)
        fields(history, {"schema", "purpose", "preparationId", "createdAt", "source", "sourceReceipt",
                         "sourceGenerationReceipt", "provisioned", "generation", "backupSha256"})
        require(type(history["schema"]) is int and history["schema"] == 1
                and history["purpose"] == "yofc-kura-prepared-generation-v1"
                and history["preparationId"] == identity and history["source"] == response["source"]
                and history["generation"] == response["generation"]
                and hashlib.sha256(encode(response["backup"])).hexdigest() == history["backupSha256"], "UNSAFE_JOURNAL")
        raw = self.read(directory / "keyring", 512)
        active, metadata = key_generations(raw)
        require(metadata == history["generation"], "UNSAFE_JOURNAL")
        receipt(history["provisioned"], active)
        keys, _, legacy = key_generation_entries(raw)
        source = history["source"]
        if source["ringSha256"] is None:
            require(len(keys) == 2 and legacy == 0 and history["sourceGenerationReceipt"] is None
                    and not os.path.lexists(directory / "source-keyring"), "UNSAFE_JOURNAL")
            previous = keys[0]
        else:
            original = self.read(directory / "source-keyring", 512)
            previous, original_metadata = key_generations(original)
            old_keys, _, old_legacy = key_generation_entries(original)
            require(keys[:-1] == old_keys and legacy == old_legacy
                    and original_metadata == history["sourceGenerationReceipt"]
                    and original_metadata["ringSha256"] == source["ringSha256"], "UNSAFE_JOURNAL")
        receipt(history["sourceReceipt"], previous)
        require(source["keySha256"] == history["sourceReceipt"]["keySha256"], "UNSAFE_JOURNAL")
        return raw, history, response

    def read_preparation(self, request):
        """Read the immutable preparation receipt, never infer later publication/start state."""
        fields(request, {'schema', 'action', 'preparationId'})
        require(request['action'] == 'generation-preparation-read', 'INVALID_ARGUMENT')
        identity = operation_id(request['preparationId'])
        response = dict(schema=1, action=request['action'], preparationId=identity,
                        scope='IMMUTABLE_PREPARATION_ONLY')
        with self.lock(self.state / 'admission.lock', False):
            self.maintenance()
            record = self.record(identity)
            if record is None:
                return dict(response, state='NOT_FOUND')
            require(record['action'] == 'generation-prepare', 'CONFLICT')
            if record['state'] == 'INTENT':
                return dict(response, state='UNKNOWN')
            with self.lock(self.store.path('/etc/kura/credentials/.provision.lock'), False):
                try:
                    _, history, prepared = self.prepared_generation(identity)
                except (OSError, Refused):
                    raise Failure('UNSAFE_JOURNAL') from None
                return dict(response, state='RECORDED', createdAt=history['createdAt'],
                            source=history['source'], generation=history['generation'],
                            historySha256=prepared['historySha256'], backupSha256=history['backupSha256'])

    def preparation_records(self):
        self.directory(self.operations, private=True)
        paths = list(self.operations.iterdir())
        require(self.active_records('operations',[operation_id(p.name[:-5]) for p in paths if p.name.endswith('.json')]) <= MAX_OPERATIONS, 'UNSAFE_JOURNAL')
        result = {}
        for path in paths:
            require(path.name.endswith('.json'), 'UNSAFE_JOURNAL')
            identity = operation_id(path.name[:-5])
            record = self.record(identity)
            require(record is not None, 'UNSAFE_JOURNAL')
            result[identity] = record
        return result

    def preparation_ids(self, records):
        result = {identity for identity, record in records.items() if record['action'] == 'generation-prepare'}
        parent = self.state / 'generations'
        if os.path.lexists(parent):
            self.directory(parent, private=True)
            paths = list(parent.iterdir())
            require(self.active_records('operations',[operation_id(p.name) for p in paths]) <= MAX_OPERATIONS, 'UNSAFE_JOURNAL')
            for path in paths:
                try:
                    identity = operation_id(path.name)
                except Failure:
                    raise Failure('UNSAFE_JOURNAL') from None
                self.directory(path, private=True)
                result.add(identity)
        return sorted(result)

    def preparation_state(self, identity, records=None):
        """Historical events only; current canonical credentials and business health are independent."""
        records = self.preparation_records() if records is None else records
        preparation = records.get(identity)
        if preparation is None:
            return dict(preparationId=identity, state='ORPHANED')
        require(preparation['action'] == 'generation-prepare', 'UNSAFE_JOURNAL')
        if preparation['state'] == 'INTENT':
            return dict(preparationId=identity, state='UNKNOWN')
        _, history, prepared = self.prepared_generation(identity)
        result = dict(preparationId=identity, state='PREPARED', createdAt=history['createdAt'],
                      source=history['source'], generation=history['generation'],
                      historySha256=prepared['historySha256'], backupSha256=history['backupSha256'])
        directory = self.state / 'generations' / identity
        cancelled = [record for record in records.values() if record['action'] == 'generation-cancel'
                     and record['intent']['preparationId'] == identity]
        published = [record for record in records.values() if record['action'] == 'generation-publish'
                     and record['state'] == 'SUCCEEDED' and record['response']['preparationId'] == identity]
        require(len(cancelled) <= 1 and len(published) <= 1, 'UNSAFE_JOURNAL')
        cancellation = directory / 'cancellation.json'
        publication = directory / 'publication.json'
        has_cancel = os.path.lexists(cancellation)
        has_publish = os.path.lexists(publication)
        require(not ((has_cancel or cancelled) and (has_publish or published)), 'UNSAFE_JOURNAL')
        if has_cancel:
            raw = self.read(cancellation, 8192)
            value = decode(raw)
            fields(value, {'schema', 'purpose', 'operationId', 'preparationId', 'historySha256',
                           'ringSha256', 'source', 'createdAt', 'receiptTag'})
            require(type(value['schema']) is int and value['schema'] == 1
                    and value['purpose'] == 'yofc-kura-generation-cancel-v1'
                    and value['preparationId'] == identity and value['source'] == history['source']
                    and value['historySha256'] == prepared['historySha256']
                    and value['ringSha256'] == history['generation']['ringSha256']
                    and isinstance(value['createdAt'], str) and 0 < len(value['createdAt']) <= 64,
                    'UNSAFE_JOURNAL')
            digest(value['receiptTag'])
            body = {name: item for name, item in value.items() if name != 'receiptTag'}
            secret = self.read(self.state / 'journal.key', 32)
            require(len(secret) == 32 and raw == encode(value)
                    and hmac.compare_digest(value['receiptTag'], hmac.new(secret,
                        b'yofc-kura-cancel-receipt-v1\0' + encode(body), hashlib.sha256).hexdigest()), 'UNSAFE_JOURNAL')
            require(len(cancelled) == 1 and cancelled[0]['operationId'] == value['operationId'], 'UNSAFE_JOURNAL')
            record = cancelled[0]
            require(record['intent'] == dict(preparationId=identity,
                    expectedHistorySha256=prepared['historySha256'],
                    expectedRingSha256=history['generation']['ringSha256']), 'UNSAFE_JOURNAL')
            fingerprint = hashlib.sha256(raw).hexdigest()
            if record['state'] == 'SUCCEEDED':
                require(record['response']['cancellationSha256'] == fingerprint, 'UNSAFE_JOURNAL')
            result.update(state='CANCELLED' if record['state'] == 'SUCCEEDED' else 'UNKNOWN',
                          cancellationId=record['operationId'], cancellationSha256=fingerprint)
        elif cancelled:
            require(cancelled[0]['state'] == 'INTENT', 'UNSAFE_JOURNAL')
            result.update(state='UNKNOWN', cancellationId=cancelled[0]['operationId'])
        elif has_publish:
            raw = self.read(publication, 8192)
            try:
                value = validate_publication(decode(raw))
            except LifecycleRefused:
                raise Failure('UNSAFE_JOURNAL') from None
            require(value['preparationId'] == identity and value['historySha256'] == prepared['historySha256']
                    and value['source'] == history['source'] and value['generation'] == history['generation'],
                    'UNSAFE_JOURNAL')
            record = records.get(value['operationId'])
            require(record is not None and record['action'] == 'generation-publish', 'UNSAFE_JOURNAL')
            fingerprint = hashlib.sha256(raw).hexdigest()
            if record['state'] == 'SUCCEEDED':
                response = record['response']
                require(len(published) == 1 and published[0]['operationId'] == record['operationId']
                        and response['publicationSha256'] == fingerprint
                        and all(response[k] == value[k] for k in ('preparationId', 'verificationId', 'cohortSha256'))
                        and response['ringSha256'] == history['generation']['ringSha256']
                        and response['activeKeySha256'] == history['generation']['activeKeySha256'], 'UNSAFE_JOURNAL')
            result.update(state='PUBLISHED' if record['state'] == 'SUCCEEDED' else 'UNKNOWN',
                          publicationId=record['operationId'], publicationSha256=fingerprint)
        elif published:
            raise Failure('UNSAFE_JOURNAL')
        if result['state'] == 'PREPARED':
            verified = [record for record in records.values() if record['action'] == 'generation-backup-verify'
                        and record['state'] == 'SUCCEEDED' and record['response']['preparationId'] == identity]
            require(len(verified) <= 1, 'UNSAFE_JOURNAL')
            if verified:
                response = verified[0]['response']
                require(response['ringSha256'] == history['generation']['ringSha256']
                        and response['backupSha256'] == history['backupSha256'], 'UNSAFE_JOURNAL')
                result.update(state='VERIFIED', verificationId=verified[0]['operationId'])
        return result

    def require_open_preparation(self, identity):
        state = self.preparation_state(identity)['state']
        require(state != 'CANCELLED', 'PREPARATION_CANCELLED')
        require(state != 'PUBLISHED', 'ALREADY_PUBLISHED')
        require(state in ('PREPARED', 'VERIFIED'), 'UNRESOLVED_OPERATION')

    def require_closed_preparations(self):
        records = self.preparation_records()
        for identity in self.preparation_ids(records):
            require(self.preparation_state(identity, records)['state'] in ('CANCELLED', 'PUBLISHED'),
                    'PREPARATION_PENDING')

    def preparation_history(self, request):
        fields(request, {'schema', 'action', 'afterPreparationId', 'limit'})
        require(request['action'] == 'generation-history', 'INVALID_ARGUMENT')
        require(type(request['limit']) is int and 1 <= request['limit'] <= 16, 'INVALID_ARGUMENT')
        cursor = request['afterPreparationId']
        if cursor is not None:
            operation_id(cursor)
        with self.lock(self.state / 'admission.lock', False):
            self.maintenance()
            with self.lock(self.store.path('/etc/kura/credentials/.provision.lock'), False):
                records = self.preparation_records()
                identities = self.preparation_ids(records)
                require(cursor is None or cursor in identities, 'CONFLICT')
                unresolved = False
                try:
                    self.settled()
                except Failure as failure:
                    if failure.reason != 'UNRESOLVED_OPERATION':
                        raise
                    unresolved = True
                rows = []
                for identity in identities:
                    try:
                        row = self.preparation_state(identity, records)
                    except (OSError, Failure, Refused, LifecycleRefused):
                        row = dict(preparationId=identity, state='UNAVAILABLE', reason='UNSAFE_JOURNAL')
                    rows.append(row)
                offset = 0 if cursor is None else identities.index(cursor) + 1
                page = rows[offset:offset + request['limit']]
                more = offset + len(page) < len(rows)
                response = dict(schema=1, action=request['action'], scope='HISTORICAL_EVENTS_ONLY',
                                entries=page, hasUnresolvedRecords=unresolved,
                                historyRevision=hashlib.sha256(encode(rows)).hexdigest(),
                                nextAfterPreparationId=page[-1]['preparationId'] if more else None)
                require(len(encode(response)) <= MAX_FRAME, 'CAPACITY')
                return response

    def cancel_preparation(self, request, *, recover=False):
        names = {'schema', 'action', 'operationId'} | ({'expectedCancellationSha256'} if recover else
                {'preparationId', 'expectedHistorySha256', 'expectedRingSha256'})
        fields(request, names)
        require(request['action'] == ('generation-cancel-recover' if recover else 'generation-cancel'), 'INVALID_ARGUMENT')
        identity = operation_id(request['operationId'])
        for name in ('expectedCancellationSha256',) if recover else ('expectedHistorySha256', 'expectedRingSha256'):
            digest(request[name])
        if not recover:
            operation_id(request['preparationId'])
            require(request['preparationId'] != identity, 'INVALID_ARGUMENT')
        with self.lock(self.state / 'admission.lock', True):
            self.maintenance()
            secret = self.read(self.state / 'journal.key', 32)
            require(len(secret) == 32, 'UNSAFE_JOURNAL')
            tag = hmac.new(secret, encode(request), hashlib.sha256).hexdigest()
            record = self.record(identity)
            if not recover and record is not None:
                require(hmac.compare_digest(record['requestTag'], tag), 'CONFLICT')
                return self.public_record(record)
            if recover:
                require(record is not None and record['action'] == 'generation-cancel', 'CONFLICT')
                if record['state'] == 'SUCCEEDED':
                    require(record['response']['cancellationSha256'] == request['expectedCancellationSha256'], 'CONFLICT')
                    return self.public_record(record)
                try:
                    Lifecycle(self.root, self.owner).check_records(recovering_cancel=identity)
                except LifecycleUnresolved:
                    raise Failure('UNRESOLVED_OPERATION') from None
                except LifecycleRefused:
                    raise Failure('UNSAFE_JOURNAL') from None
                intent = record['intent']
            else:
                self.settled()
                self.journal_admission(request)
                intent = {name: request[name] for name in ('preparationId', 'expectedHistorySha256', 'expectedRingSha256')}
            with self.lock(self.store.path('/etc/kura/credentials/.provision.lock'), False):
                preparation = intent['preparationId']
                row = self.preparation_state(preparation)
                _, history, prepared = self.prepared_generation(preparation)
                require(intent['expectedHistorySha256'] == prepared['historySha256']
                        and intent['expectedRingSha256'] == history['generation']['ringSha256'], 'CONFLICT')
                _, _, _, metadata, proof, source = self.generation_source()
                require(source == history['source'] and proof == history['sourceReceipt']
                        and metadata == history['sourceGenerationReceipt'], 'CONFLICT')
                directory = self.state / 'generations' / preparation
                path = directory / 'cancellation.json'
                if recover:
                    require(row['state'] == 'UNKNOWN' and row.get('cancellationId') == identity, 'CONFLICT')
                    if 'cancellationSha256' not in row:
                        return self.public_record(record)  # Never recreate a missing original receipt.
                    require(row['cancellationSha256'] == request['expectedCancellationSha256'], 'CONFLICT')
                    raw = self.read(path, 8192)
                else:
                    require(row['state'] != 'CANCELLED', 'ALREADY_CANCELLED')
                    require(row['state'] != 'PUBLISHED', 'ALREADY_PUBLISHED')
                    require(row['state'] in ('PREPARED', 'VERIFIED'), 'UNRESOLVED_OPERATION')
                    value = dict(schema=1, purpose='yofc-kura-generation-cancel-v1', operationId=identity,
                                 preparationId=preparation, historySha256=prepared['historySha256'],
                                 ringSha256=history['generation']['ringSha256'], source=source,
                                 createdAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
                    value['receiptTag'] = hmac.new(secret,
                        b'yofc-kura-cancel-receipt-v1\0' + encode(value), hashlib.sha256).hexdigest()
                    raw = encode(value)
                    record = dict(schema=1, operationId=identity, action='generation-cancel', requestTag=tag,
                                  state='INTENT', response=None, intent=intent)
                try:
                    if not recover:
                        self.atomic(self.operations / (identity + '.json'), encode(record))
                        self.atomic(path, raw, mode=0o400, no_replace=True)
                    else:
                        self.sync(directory)  # Original file bytes/inode remain unchanged.
                    response = dict(schema=1, operationId=identity, action='generation-cancel', state='SUCCEEDED',
                                    preparationId=preparation, historySha256=prepared['historySha256'],
                                    ringSha256=history['generation']['ringSha256'],
                                    cancellationSha256=hashlib.sha256(raw).hexdigest(),
                                    credentialsChanged=False, historyRetained=True)
                    record.update(state='SUCCEEDED', response=response)
                    self.atomic(self.operations / (identity + '.json'), encode(record))
                    return response
                except (OSError, Failure, Refused):
                    raise Failure('UNKNOWN') from None

    def stage_generation(self, request, *, verify=False):
        expected = {"schema", "action", "operationId", "passphrase"}
        expected |= {"preparationId", "expectedRingSha256", "backup"} if verify else {"expectedSource"}
        fields(request, expected)
        identity = operation_id(request["operationId"])
        password = passphrase(request["passphrase"])
        if verify:
            preparation = operation_id(request["preparationId"])
            digest(request["expectedRingSha256"])
        else:
            fields(request["expectedSource"], {"keySha256", "ringSha256"})
            digest(request["expectedSource"]["keySha256"])
            if request["expectedSource"]["ringSha256"] is not None:
                digest(request["expectedSource"]["ringSha256"])
        with self.lock(self.state / "admission.lock", True):
            self.maintenance()
            journal_key = self.read(self.state / "journal.key", 32)
            require(len(journal_key) == 32, "UNSAFE_JOURNAL")
            tag = hmac.new(journal_key, encode(request), hashlib.sha256).hexdigest()
            existing = self.record(identity)
            if existing is not None:
                require(hmac.compare_digest(existing["requestTag"], tag), "CONFLICT")
                return self.public_record(existing)
            self.settled()
            self.journal_admission(request)
            with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), False):
                keys, legacy, original_ring, original_metadata, proof, source = self.generation_source()
                if verify:
                    try:
                        raw, history, prepared = self.prepared_generation(preparation)
                    except OSError:
                        raise Failure("UNSAFE_FILESYSTEM") from None
                    self.require_open_preparation(preparation)
                    require(history["source"] == source and history["sourceReceipt"] == proof
                            and history["sourceGenerationReceipt"] == original_metadata, "CONFLICT")
                    require(request["expectedRingSha256"] == history["generation"]["ringSha256"]
                            and request["backup"] == prepared["backup"], "BACKUP_REJECTED")
                    uploaded, _, data = self.unpack_generations(request["backup"], password)
                    require(uploaded == raw and data["receipt"] == history["provisioned"]
                            and data["operationId"] == preparation and data["createdAt"] == history["createdAt"], "BACKUP_REJECTED")
                    for path in self.operations.iterdir():
                        prior = self.record(operation_id(path.name[:-5]))
                        require(prior["action"] != "generation-backup-verify"
                                or prior["response"]["preparationId"] != preparation, "ALREADY_VERIFIED")
                else:
                    require(request["expectedSource"] == source, "CONFLICT")
                    require(len(keys) < 8, "CAPACITY")
                    require(self.generation_restore_supported(), "UNSUPPORTED")
                    parent = self.state / "generations"
                    self.require_closed_preparations()
                record = dict(schema=1, operationId=identity, action=request["action"],
                              requestTag=tag, state="INTENT", response=None)
                try:
                    self.atomic(self.operations / (identity + ".json"), encode(record))
                    if verify:
                        response = dict(schema=1, operationId=identity, state="SUCCEEDED", action=request["action"],
                                        preparationId=preparation, ringSha256=history["generation"]["ringSha256"],
                                        backupSha256=history["backupSha256"], published=False, requiresExplicitCommit=True)
                    else:
                        fresh = secrets.token_bytes(32)
                        require(fresh not in keys and fresh not in (CORE_DEFAULT, OLD_DEVELOPMENT), "UNKNOWN")
                        raw = encode_key_generations([*keys, fresh], len(keys), legacy)
                        _, metadata = key_generations(raw)
                        proposed = receipt(dict(schema=1, keySha256=metadata["activeKeySha256"], origin="canonical",
                                                legacyKey=False, unitDigests=proof["unitDigests"]), fresh)
                        created = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        payload = dict(schema=1, purpose=GENERATION_FORMAT, operationId=identity, createdAt=created,
                                       keyring=base64.b64encode(raw).decode("ascii"), receipt=proposed)
                        encrypted = self.crypt(True, password, encode(payload))
                        backup = dict(format=GENERATION_FORMAT, operationId=identity,
                                      encrypted=base64.b64encode(encrypted).decode("ascii"))
                        history = dict(schema=1, purpose="yofc-kura-prepared-generation-v1", preparationId=identity,
                                       createdAt=created, source=source, sourceReceipt=proof, sourceGenerationReceipt=original_metadata,
                                       provisioned=proposed, generation=metadata, backupSha256=hashlib.sha256(encode(backup)).hexdigest())
                        # Immutable private staging only. Canonical credentials/receipts and units stay untouched.
                        parent.mkdir(mode=0o700, exist_ok=True)
                        self.directory(parent, private=True)
                        self.sync(self.state)
                        directory = parent / identity
                        directory.mkdir(mode=0o700)
                        self.sync(parent)
                        self.atomic(directory / "keyring", raw, mode=0o400, no_replace=True)
                        if original_ring is not None:
                            self.atomic(directory / "source-keyring", original_ring, mode=0o400, no_replace=True)
                        history_bytes = encode(history)
                        self.atomic(directory / "history.json", history_bytes, mode=0o400, no_replace=True)
                        require(self.read(directory / "keyring", 512) == raw
                                and self.read(directory / "history.json", 8192) == history_bytes, "UNKNOWN")
                        response = dict(schema=1, operationId=identity, state="SUCCEEDED", action=request["action"],
                                        source=source, generation=metadata, historySha256=hashlib.sha256(history_bytes).hexdigest(),
                                        backup=backup, published=False, requiresExplicitCommit=True)
                    record.update(state="SUCCEEDED", response=response)
                    self.atomic(self.operations / (identity + ".json"), encode(record))
                    return response
                except (OSError, Failure, Refused):
                    raise Failure("UNKNOWN") from None

    def handle(self, request, *, recovery_only=False):
        require(isinstance(request, dict) and type(request.get("schema")) is int and request["schema"] == 1)
        action = request.get("action")
        if recovery_only:
            require(action in ('status', 'backup-inspect', 'operation-read', 'restore', 'core-start', 'core-start-read', 'core-start-plan', 'core-start-after-maintenance', 'recovery-info', 'generation-backup-inspect', 'generation-restore'), 'FORBIDDEN')
        if action == 'generation-preparation-read':
            return self.read_preparation(request)
        if action == 'generation-history':
            return self.preparation_history(request)
        if action in ('generation-cancel', 'generation-cancel-recover'):
            return self.cancel_preparation(request, recover=action == 'generation-cancel-recover')
        if action in ("generation-prepare", "generation-backup-verify"):
            return self.stage_generation(request, verify=action == "generation-backup-verify")
        if action == 'core-validation-info':
            return self.validation_component().info(request)
        if action in ('generation-publication-read', 'generation-publication-recover',
                      'generation-publication-plan', 'generation-publish', 'generation-core-start'):
            try:
                component, _ = self.generation_component()
                if action == 'generation-publication-read':
                    return component.publication_read(request)
                if action == 'generation-publication-recover':
                    return component.recover_publication(request)
                return component.request(request, start=action == 'generation-core-start')
            except LifecycleRefused:
                raise Failure('UNSAFE_JOURNAL') from None
        if action == "credential-start-admission":
            fields(request, {"schema", "action", "keySha256", "ringSha256"})
            digest(request["keySha256"])
            if request["ringSha256"] is not None:
                digest(request["ringSha256"])
            with self.lock(self.state / "admission.lock", False):
                self.maintenance()
                self.settled()
                with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), False):
                    try:
                        _, _, _, _, _, source = self.generation_source()
                    except OSError:
                        raise Failure("UNSAFE_FILESYSTEM") from None
                    require(all(request[k] == source[k] for k in ("keySha256", "ringSha256")), "CONFLICT")
                    cohort = self.require_generation_cohort() if source['ringSha256'] is not None else None
                    self.generation_start_authorized(source, cohort)
                    return dict(schema=1, state="CREDENTIAL_READY", **source)
        if action == "generation-start-admission":
            fields(request, {"schema", "action", "ringSha256", "activeKeySha256"})
            digest(request["ringSha256"]); digest(request["activeKeySha256"])
            with self.lock(self.state / "admission.lock", False):
                self.maintenance()
                self.settled()
                with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), False):
                    _, metadata, _ = self.generations()
                    require(all(request[k] == metadata[k] for k in ("ringSha256", "activeKeySha256")), "CONFLICT")
                    cohort = self.require_generation_cohort()
                    self.generation_start_authorized(dict(keySha256=metadata['activeKeySha256'], ringSha256=metadata['ringSha256']), cohort)
                    return dict(schema=1, state="GENERATION_READY", ringSha256=metadata["ringSha256"],
                                activeKeySha256=metadata["activeKeySha256"])
        if action == "generation-restore":
            return self.restore_generations(request, recovery_only=recovery_only)
        if action == "generation-backup-create":
            return self.create_generation_backup(request)
        if action == "generation-backup-inspect":
            fields(request, {"schema", "action", "backup", "passphrase"})
            password = passphrase(request["passphrase"])
            with self.lock(self.state / "admission.lock", False):
                self.maintenance()
                blocked = False
                try:
                    self.settled()
                except Failure as failure:
                    if failure.reason != "UNRESOLVED_OPERATION":
                        raise
                    blocked = True
                with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), False):
                    current = self.generation_receipt()
                    key, proof = self.canonical(True, allow_generations=True)
                    require(current["activeKeySha256"] == proof["keySha256"], "UNSAFE_FILESYSTEM")
                    raw, metadata, data = self.unpack_generations(request["backup"], password)
                    compatible = current == metadata
                    allowed = False
                    ring_ready = False
                    if compatible:
                        _, key, ring, _ = self.generation_restore_state(raw, metadata)
                        ring_ready = ring is not None
                        allowed = not blocked and self.generation_restore_supported() and (not recovery_only or key is None or ring is None)
                    return dict(schema=1, backupOperationId=data["operationId"], createdAt=data["createdAt"],
                                **metadata, matchesRetainedReceipt=compatible, activeKeyReady=key is not None,
                                keyringReady=ring_ready, restoreSupported=self.generation_restore_supported(),
                                restoreAllowed=allowed, restoreBlockedByUnresolvedOperation=blocked)
        if action in ("core-start", "core-start-read", "core-start-plan", "core-start-after-maintenance"):
            from kura_key_recovery_start import Starter
            return Starter(self).handle(request)
        if action == 'recovery-info':
            fields(request, {'schema','action'})
            with self.lock(self.state/'admission.lock', False):
                self.maintenance()
                directory=self.store.path('/etc/kura/recovery-tls')
                self.directory(directory,private=True)
                data=self.read(directory/'server.crt',16384)
                try:pem=data.decode('ascii')
                except UnicodeError:raise Failure('UNAVAILABLE') from None
                require(re.fullmatch(r'-----BEGIN CERTIFICATE-----\n[A-Za-z0-9+/=\n]+-----END CERTIFICATE-----\n?',pem) is not None,'UNAVAILABLE')
                try:
                    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    context.load_verify_locations(cadata=pem)
                    der=ssl.PEM_cert_to_DER_cert(pem)
                except (ssl.SSLError,ValueError):raise Failure('UNAVAILABLE') from None
                return dict(schema=1,recoveryPort=9443,certificatePem=pem,
                            certificateSha256=hashlib.sha256(der).hexdigest(),agentRequired=False)
        if action == "status":
            fields(request, {"schema", "action"})
            with self.lock(self.state / "admission.lock", False):
                self.maintenance()
                with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), False):
                    key, proof = self.canonical(True)
                    return {"schema": 1, "keyReady": key is not None, "keySha256": proof["keySha256"],
                            "legacyKey": proof["legacyKey"], "agentRequired": False}
        if action == "operation-read":
            fields(request, {"schema", "action", "operationId"})
            identity = operation_id(request["operationId"])
            with self.lock(self.state / "admission.lock", False):
                self.maintenance()
                record = self.record(identity)
                require(not recovery_only or record is None or record['action'] in ('restore', 'generation-restore'), 'FORBIDDEN')
                return self.public_record(record)
        if action == "backup-inspect":
            fields(request, {"schema", "action", "backup", "passphrase"})
            password = passphrase(request["passphrase"])
            with self.lock(self.state / "admission.lock", False):
                self.maintenance()
                key, data = self.unpack(request["backup"], password)
                with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), False):
                    current, proof = self.canonical(True)
                    compatible = proof["keySha256"] == data["receipt"]["keySha256"]
                    return {"schema": 1, "backupOperationId": data["operationId"],
                            "keySha256": data["receipt"]["keySha256"], "createdAt": data["createdAt"],
                            "sameDeviceKey": compatible, "keyReady": current is not None,
                            "restoreAllowed": compatible and (current is None if recovery_only else (current is None or current == key))}
        require(action in ("backup-create", "restore"))
        expected = {"schema", "action", "operationId", "passphrase"}
        if action == "restore":
            expected |= {"backup", "expectedKeySha256"}
        fields(request, expected)
        identity = operation_id(request["operationId"])
        password = passphrase(request["passphrase"])
        with self.lock(self.state / "admission.lock", True):
            self.maintenance()
            # Installer creates this independent journal key; status never provisions a data key.
            journal_key = self.read(self.state / "journal.key", 32)
            require(len(journal_key) == 32, "UNSAFE_JOURNAL")
            tag = hmac.new(journal_key, encode(request), hashlib.sha256).hexdigest()
            existing = self.record(identity)
            if existing is not None:
                require(hmac.compare_digest(existing["requestTag"], tag), "CONFLICT")
                return self.public_record(existing)
            self.journal_admission(request)
            with self.lock(self.store.path("/etc/kura/credentials/.provision.lock"), action == "restore"):
                current, proof = self.canonical(action == "restore")
                require(not recovery_only or current is None, 'CONFLICT')
                key = None
                if action == "restore":
                    digest(request["expectedKeySha256"])
                    key, data = self.unpack(request["backup"], password)
                    require(request["expectedKeySha256"] == proof["keySha256"]
                            == data["receipt"]["keySha256"], "CONFLICT")
                    require(current is None or current == key, "CONFLICT")
                    if current is None:
                        require(sys.platform == "linux" and hasattr(ctypes.CDLL(None), "renameat2"), "UNSUPPORTED")
                record = dict(schema=1, operationId=identity, action=action, requestTag=tag,
                              state="INTENT", response=None)
                # From this point every ambiguous failure is UNKNOWN. Never redispatch on read.
                try:
                    self.atomic(self.operations / (identity + ".json"), encode(record))
                    if action == "backup-create":
                        created = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        payload = dict(schema=1, purpose=FORMAT, operationId=identity, createdAt=created,
                                       key=base64.b64encode(current).decode("ascii"), receipt=proof)
                        encrypted = self.crypt(True, password, encode(payload))
                        response = dict(schema=1, operationId=identity, state="SUCCEEDED", action=action,
                                        backup=dict(format=FORMAT, operationId=identity,
                                                    encrypted=base64.b64encode(encrypted).decode("ascii")))
                    else:
                        if current is None:
                            self.atomic(self.store.path(KEY_PATH), key, mode=0o400, no_replace=True)
                        response = dict(schema=1, operationId=identity, state="SUCCEEDED", action=action,
                                        keySha256=proof["keySha256"], keyChanged=current is None,
                                        existingReceiptPreserved=True)
                    record.update(state="SUCCEEDED", response=response)
                    self.atomic(self.operations / (identity + ".json"), encode(record))
                    return response
                except (OSError, Failure, Refused):
                    raise Failure("UNKNOWN") from None


def read_exact(stream, size):
    output = bytearray()
    while len(output) < size:
        part = stream.recv(size - len(output))
        require(bool(part), "PROTOCOL_MISMATCH")
        output.extend(part)
    return bytes(output)


def read_frame(stream):
    length = struct.unpack("!I", read_exact(stream, 4))[0]
    require(0 < length <= MAX_FRAME, "PROTOCOL_MISMATCH")
    return read_exact(stream, length)


def read_request_frame(stream):
    """Receive at most one CLOEXEC input FD, including on fragmented frames/EOF."""
    descriptors = []
    accepted = False

    def part(count):
        value, ancillary, flags, _ = stream.recvmsg(count, socket.CMSG_SPACE(8), socket.MSG_CMSG_CLOEXEC)
        valid = True
        for level, kind, raw in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                valid = False
                continue
            fds = array.array('i')
            fds.frombytes(raw[:len(raw) - len(raw) % fds.itemsize])
            descriptors.extend(fds)
        require(valid and not flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC) and len(descriptors) <= 1,
                'PROTOCOL_MISMATCH')
        return value

    def exact(count):
        value = bytearray()
        while len(value) < count:
            chunk = part(count - len(value))
            require(bool(chunk), 'PROTOCOL_MISMATCH')
            value.extend(chunk)
        return bytes(value)

    try:
        length = struct.unpack('!I', exact(4))[0]
        require(0 < length <= MAX_FRAME, 'PROTOCOL_MISMATCH')
        value = decode(exact(length))
        require(part(1) == b'', 'PROTOCOL_MISMATCH')
        accepted = True
        return value, descriptors[0] if descriptors else None
    finally:
        if not accepted:
            for fd in descriptors:
                os.close(fd)


def agent_peer(pid):
    # The packaged Root agent must not use the administrative key/backup protocol.
    # ProtectControlGroups on its unit prevents moving a child out of this cgroup.
    try:
        raw = Path('/proc/' + str(pid) + '/cgroup').read_text()
    except OSError:
        raise Failure('FORBIDDEN') from None
    lines = raw.splitlines()
    require(len(lines) == 1 and lines[0].startswith('0::/'), 'FORBIDDEN')
    path = lines[0][3:]
    base = '/system.slice/kura-management-agent.service'
    return path == base or path.startswith(base + '/')


GWT_MUTATIONS = frozenset(('backup-create', 'restore', 'generation-prepare', 'generation-backup-verify', 'generation-handoff-create'))
GWT_ORIGINAL_READS = frozenset(('operation-read', 'generation-handoff-read', 'generation-handoff-token-read', 'generation-publication-plan'))
ARCHIVE_ACTIONS = frozenset(('journal-archive-plan','journal-archive','journal-archive-read','journal-archive-continue','journal-archive-reference-read','journal-archive-recovery-reference-read'))
PRIVATE_FENCE_ACTIONS = frozenset(('sender-private-fence-plan','sender-private-fence','sender-private-fence-read'))
SENDER_MUTATIONS = GWT_MUTATIONS | frozenset(('generation-backup-create', 'generation-restore', 'core-start',
    'core-start-after-maintenance', 'generation-cancel', 'generation-cancel-recover', 'generation-publish',
    'generation-core-start', 'generation-publication-recover', 'generation-handoff-command'))


def sender_mutation(request):
    return request.get('action') in SENDER_MUTATIONS and not (
        request.get('action') == 'generation-handoff-command' and request.get('command') in
        ('info', 'publication-read', 'start-read', 'revoke', 'revocation-read', 'start-lease-status', 'start-lease-read'))


def serve_request(manager, request, pid, uid, daemon, recovery, input_descriptor):
    action = request.get('action')
    bound=False
    require(not agent_peer(pid) or action in ('core-validation-info', 'core-snapshot-validate'), 'FORBIDDEN')
    if action == 'sender-reserve':
        require(input_descriptor is None)
        return manager.sender_admissions.reserve(request, pid, uid, daemon, recovery), None
    if action in ('sender-admission-read', 'sender-admission-close'):
        require(input_descriptor is None)
        return manager.sender_admissions.read(request, pid, uid, daemon, recovery, close=action.endswith('-close')), None
    if action == 'sender-command':
        require(input_descriptor is None)
        return manager.sender_admissions.execute(request, pid, uid, daemon, recovery,
            lambda inner: serve_request(manager, inner, pid, uid, daemon, recovery, None))
    if action == 'gwt-sender-namespace':
        fields(request, {'schema', 'action'})
        require(type(request['schema']) is int and request['schema'] == 1 and input_descriptor is None)
        with manager.lock(manager.state / 'admission.lock', False):
            manager.maintenance()
            return dict(schema=1, **manager.gwt_namespace()), None
    if action == 'gwt-sender-bind':
        require(input_descriptor is None)
        return manager.bind_gwt_sender(request, pid, uid, daemon), None
    if action == 'gwt-bound-request':
        require(input_descriptor is None)
        request = manager.unwrap_gwt_request(request, pid, uid, daemon)
        action = request['action']
        bound=True
    elif uid == daemon and action in GWT_MUTATIONS:
        require(getattr(manager.sender_admissions.context, 'current', None) is not None, 'FORBIDDEN')
    if sender_mutation(request):
        # Includes independent recovery and local Root clients. No old wire format bypasses reservation/intake.
        require(getattr(manager.sender_admissions.context, 'current', None) is not None, 'FORBIDDEN')
    require(uid != daemon or action not in ('core-start', 'core-start-after-maintenance', 'generation-publication-recover'), 'FORBIDDEN')
    if action == 'core-snapshot-validate':
        require(uid in (0, daemon) and (recovery is None or uid != recovery), 'FORBIDDEN')
        require(input_descriptor is not None, 'PROTOCOL_MISMATCH')
        return manager.validation_component().validate(request, input_descriptor, uid, core_uid=daemon), None
    require(input_descriptor is None, 'PROTOCOL_MISMATCH')
    if action in PRIVATE_FENCE_ACTIONS:
        require(uid!=daemon or bound,'FORBIDDEN')
        return manager.sender_admissions.private_fence(request,pid,uid,daemon,recovery),None
    if action in ARCHIVE_ACTIONS:
        require(uid!=daemon or bound,'FORBIDDEN')
        return manager.archive_journal(request,pid,uid,daemon,recovery),None
    if action == 'generation-handoff-revocation-read':
        fields(request, {'schema', 'action', 'handoffId'})
        require(type(request['schema']) is int and request['schema'] == 1, 'INVALID_ARGUMENT')
        if recovery is not None and uid == recovery: manager.recovery_sender_owner(pid, uid)
        else: require(uid in (0, daemon), 'FORBIDDEN')
        component = manager.handoff_component()
        with manager.lock(manager.state/'admission.lock', False):
            manager.maintenance(); grant = component.load(operation_id(request['handoffId']))
            require(grant is not None, 'NOT_FOUND')
            return component.revocation_read(grant), None
    if action in ('generation-handoff-create', 'generation-handoff-read',
                  'generation-handoff-token-read', 'generation-handoff-command'):
        if action != 'generation-handoff-command':
            require(uid in (0, daemon), 'FORBIDDEN')
        component = manager.handoff_component()
        if action == 'generation-handoff-create':
            return component.create(request, pid, uid, daemon), None
        if action == 'generation-handoff-command':
            return component.command(request, pid, uid, daemon, recovery), None
        return component.read(request, pid, uid, daemon, token=action == 'generation-handoff-token-read'), None
    if action == 'writer-lease-acquire':
        require(recovery is None or uid != recovery, 'FORBIDDEN')
        return manager.acquire_writer_lease(request, pid, uid)
    return manager.handle(request, recovery_only=recovery is not None and uid == recovery), None


def send_frame(stream, value):
    data = encode(value)
    require(len(data) <= MAX_FRAME, "PROTOCOL_MISMATCH")
    stream.sendall(struct.pack("!I", len(data)) + data)


def send_descriptor_frame(stream, value, descriptor):
    data = encode(value)
    require(len(data) <= MAX_FRAME, 'PROTOCOL_MISMATCH')
    frame = struct.pack('!I', len(data)) + data
    sent = stream.sendmsg([frame], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, struct.pack('i', descriptor))])
    require(sent > 0, 'PROTOCOL_MISMATCH')
    if sent < len(frame):
        stream.sendall(frame[sent:])


def peer(stream):
    require(sys.platform == "linux" and hasattr(socket, "SO_PEERCRED"), "UNSUPPORTED")
    return struct.unpack("3i", stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))


def recovery_identity(daemon):
    try:
        account = pwd.getpwnam('kura-key-recovery')
    except KeyError:
        return None  # The previous package generation has no recovery account.
    require(account.pw_uid not in (0, daemon) and account.pw_shell in ('/usr/sbin/nologin', '/sbin/nologin'), 'FORBIDDEN')
    return account.pw_uid


def serve():
    require(os.geteuid() == 0, "FORBIDDEN")
    require(os.environ.get("LISTEN_PID") == str(os.getpid()) and os.environ.get("LISTEN_FDS") == "1",
            "UNAVAILABLE")
    listener = socket.socket(fileno=3)
    require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM
            and listener.getsockname() == SOCKET
            and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1, "UNAVAILABLE")
    daemon = pwd.getpwnam("kurad").pw_uid
    require(daemon != 0, "FORBIDDEN")
    recovery = recovery_identity(daemon)
    lifecycle = Lifecycle()
    lifecycle.no_overrides()
    lifecycle.assets()
    require(lifecycle.fence() is None, "MAINTENANCE")
    manager = Manager()
    while True:
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(3)
            descriptor = None
            input_descriptor = None
            try:
                pid, uid, _ = peer(connection)
                require(uid in (0, daemon) or recovery is not None and uid == recovery, "FORBIDDEN")
                request, input_descriptor = read_request_frame(connection)
                response, descriptor = serve_request(manager, request, pid, uid, daemon, recovery, input_descriptor)
            except Failure as failure:
                response = {"schema": 1, "error": failure.reason}
            except (OSError, Refused, KeyError):
                response = {"schema": 1, "error": "UNAVAILABLE"}
            try:
                if descriptor is None:
                    send_frame(connection, response)
                else:
                    send_descriptor_frame(connection, response, descriptor)
            except (OSError, Failure):
                pass  # Original durable UUID can be read; never repeat a mutation here.
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if input_descriptor is not None:
                    os.close(input_descriptor)


def client():
    data = sys.stdin.buffer.read(MAX_FRAME + 1)
    request = decode(data)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(25)
        connection.connect(SOCKET)
        require(peer(connection)[1] == 0, "FORBIDDEN")
        send_frame(connection, request)
        connection.shutdown(socket.SHUT_WR)
        result = read_frame(connection)
        require(connection.recv(1) == b"", "PROTOCOL_MISMATCH")
        sys.stdout.buffer.write(encode(decode(result)) + b"\n")


if __name__ == "__main__":
    try:
        require(len(sys.argv) == 2 and sys.argv[1] in ("--serve", "--client"))
        serve() if sys.argv[1] == "--serve" else client()
    except (Failure, OSError, Refused, LifecycleRefused, KeyError):
        # The GWT adapter maps a lost mutating response to UNKNOWN with the original UUID.
        sys.stderr.write("Kura gateway key service unavailable; preserve the original operation ID\n")
        sys.exit(2)
