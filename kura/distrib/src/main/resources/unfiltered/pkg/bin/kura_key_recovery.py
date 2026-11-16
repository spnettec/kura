#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""HTTPS cold recovery: encrypted backup + password, retained original key only.

The UI runs without capabilities and never reads a data key. The existing Root
socket decrypts and verifies the backup against its protected provisioning receipt.
CSRF tokens protect browser requests; they are not recovery authorization.
"""
import contextlib
import fcntl
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import os
from pathlib import Path
import pwd
import re
import secrets
import socket
import ssl
import stat
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kura_key_service as protocol
from kura_key_service_lifecycle import (HANDOFF_BINDING, HANDOFF_IDS, validate_handoff_binding,
    validate_sender_attempt, validate_sender_closed, receiver_start_intent, receiver_restore_intent,
    receiver_restore_pending, validate_receiver_pending, validate_handoff_retired, validate_start_lease, Lifecycle, Refused)

STATE = Path('/var/lib/kura-key-recovery')
ASSETS = Path('/opt/eclipse/kura/share/key-recovery')
MAX_OPERATIONS = 32
COOKIE = '__Host-kura-recovery'


def fail(reason):
    raise protocol.Failure(reason)


class SenderAdmission:
    """Consume an admission attempt before RPC; create private key intentions only after Root reserves."""
    context = threading.local()
    KINDS = frozenset(('restore','start','publish','continue','handoff-start','handoff-renewal'))

    @staticmethod
    def native_action(kind, request):
        return ('generation-start-lease' if kind == 'handoff-renewal' else 'generation-core-start' if kind == 'handoff-start'
            else 'generation-publish' if kind in ('publish','continue') else request['action'])

    def __init__(self, client, journal):
        self.client, self.journal = client, journal
        journal.archive_client=client
        self.directory = journal.directory/'admissions'

    def path(self, kind, identity):
        protocol.operation_id(identity)
        protocol.require(kind in self.KINDS)
        return self.directory/(identity+'-'+kind)

    def has_attempt(self, kind, identity):
        try:self.path(kind,identity).lstat();return True
        except FileNotFoundError:return False

    def has_key_intent(self, identity, *, permitted_start=None, permitted_restore=None, permitted_pending=None, permitted_handoff=None):
        protocol.operation_id(identity)
        restore=self.journal.record(identity)
        if restore is not None and restore!=permitted_restore:return True
        start=self.journal.start_record(identity)
        if start is not None and start!=permitted_start:return True
        if permitted_restore is not None and any(r['restoreOperationId']==identity for r in self.journal.start_records()):return True
        pending=self.journal.pending()
        if pending is not None and pending['operationId']==identity and pending!=permitted_pending:return True
        directory=self.journal.directory/'handoffs'
        try:directory.lstat()
        except FileNotFoundError:return False
        self.journal.check_directory(directory);slots=list(directory.iterdir())
        protocol.require(self.journal.active_count('HANDOFF',slots)<=MAX_OPERATIONS,'UNSAFE_JOURNAL')
        for slot in slots:
            self.journal.check_directory(slot);protocol.operation_id(slot.name)
            names={p.name for p in slot.iterdir()};protocol.require(names<=HandoffController.FILES,'UNSAFE_JOURNAL')
            saved=protocol.decode(self.journal.read(slot/'binding.json',8192))
            try:validate_handoff_binding(saved)
            except Refused:fail('UNSAFE_JOURNAL')
            protocol.require(saved['handoffId']==slot.name,'UNSAFE_JOURNAL')
            if slot.name == permitted_handoff: continue
            if names=={'binding.json'} and identity in (saved['publicationId'],saved['startOperationId']):return True
            if identity==saved['publicationId'] and names&{'publish.json','continue.json'}:return True
            if identity==saved['startOperationId'] and 'start.json' in names:return True
        return False

    def load(self, kind, identity):
        if not self.has_attempt(kind,identity):return None
        slot=self.path(kind,identity);self.journal.check_directory(self.directory);self.journal.check_directory(slot)
        names={p.name for p in slot.iterdir()}
        protocol.require(names in ({'intent.json'}, {'intent.json','namespace.json'}, {'intent.json','namespace.json','closed.json'})
            or kind=='restore' and names=={'intent.json','namespace.json','closed.json','pending.json'}, 'UNSAFE_JOURNAL')
        try:value=validate_sender_attempt(protocol.decode(self.journal.read(slot/'intent.json',12288)),'recovery')
        except Refused:fail('UNSAFE_JOURNAL')
        protocol.require(value['kind']==kind and value['nativeOperationId']==identity,'CONFLICT')
        namespace=None;closed=False
        if 'namespace.json' in names:
            namespace=protocol.decode(self.journal.read(slot/'namespace.json',4096));protocol.fields(namespace,{'schema','namespaceSha256'})
            protocol.require(type(namespace['schema']) is int and namespace['schema']==1,'UNSAFE_JOURNAL');protocol.digest(namespace['namespaceSha256'])
        if 'closed.json' in names:
            try:validate_sender_closed(protocol.decode(self.journal.read(slot/'closed.json',4096)),value,namespace)
            except Refused:fail('UNSAFE_JOURNAL')
            closed=True
        if 'pending.json' in names:
            try:validate_receiver_pending(protocol.decode(self.journal.read(slot/'pending.json')),value)
            except Refused:fail('UNSAFE_JOURNAL')
        return value,namespace,closed

    def view(self, kind, identity, *, close=False):
        saved=self.load(kind,identity)
        result=dict(schema=1,state='SENDER_ADMISSION',kind=kind,operationId=identity,phase='UNKNOWN',closeAllowed=False,closed=False)
        if saved is None:return dict(result,phase='NOT_RECORDED')
        attempt,namespace,closed=saved;metadata=attempt['request']
        for name in ('expectedKeySha256','restoreOperationId'):
            if name in metadata:result[name]=metadata[name]
        if kind=='start':
            result['startSchema']=2 if metadata['action']=='core-start-after-maintenance' else 1
            if result['startSchema']==2:
                for name in ('predecessorStartOperationId','maintenanceId','manifestSha256'):result[name]=metadata[name]
        if namespace is None:
            protocol.require(not close,'UNRESOLVED_OPERATION');return result
        try:
            realm=self.client(dict(schema=1,action='gwt-sender-namespace'))
            protocol.fields(realm,{'schema','namespaceSha256','rootDevice','rootInode'})
            protocol.require(type(realm['schema']) is int and realm['schema']==1 and realm['namespaceSha256']==namespace['namespaceSha256'],'CONFLICT')
            query=dict(schema=1,action='sender-admission-close' if close else 'sender-admission-read',admissionId=attempt['admissionId'],source='recovery',namespaceSha256=namespace['namespaceSha256'])
            reply=self.client(query)
            protocol.fields(reply,{'schema','admissionId','state','source','namespaceSha256','nativeOperationId','nativeAction','newlyReserved'})
            action=self.native_action(kind,metadata)
            protocol.require(type(reply['schema']) is int and reply['schema']==1 and reply['admissionId']==attempt['admissionId']
                and reply['source']=='recovery' and reply['namespaceSha256']==namespace['namespaceSha256'] and reply['nativeOperationId']==identity
                and reply['nativeAction']==action and reply['newlyReserved'] is False
                and reply['state'] in ('RESERVED','INTAKE','TERMINAL','NOT_ADMITTED'),'PROTOCOL_MISMATCH')
            if close:
                protocol.require(reply['state']=='NOT_ADMITTED','UNRESOLVED_OPERATION')
                if not closed:
                    self.journal.write_new(self.path(kind,identity)/'closed.json',dict(schema=1,purpose='yofc.kura.sender-not-admitted.v1',
                        admissionId=attempt['admissionId'],kind=kind,nativeOperationId=identity,namespaceSha256=namespace['namespaceSha256']))
                closed=True
            result.update(phase='UNKNOWN' if reply['state']=='INTAKE' else reply['state'],closed=closed and reply['state']=='NOT_ADMITTED',
                closeAllowed=not closed and kind!='continue' and reply['state'] in ('RESERVED','NOT_ADMITTED'))
            return result
        except (protocol.Failure,OSError,ValueError,KeyError,TypeError):
            if close:raise
            return result

    def close(self, kind, identity):
        current=self.view(kind,identity)
        protocol.require(current['closeAllowed'] or current['phase']=='NOT_ADMITTED' and current['closed'],'UNRESOLVED_OPERATION')
        return self.view(kind,identity,close=True)

    @classmethod
    def wrap(cls, request):
        current = getattr(cls.context, 'current', None)
        if current is None or not protocol.sender_mutation(request): return request
        protocol.require(request == current['request'], 'CONFLICT')
        return dict(schema=1, action='sender-command', admissionId=current['admissionId'], source='recovery',
            namespaceSha256=current['namespaceSha256'], request=request)

    def submit(self, kind, identity, request, callback):
        protocol.operation_id(identity); protocol.require(kind in self.KINDS)
        protocol.require(getattr(self.context, 'current', None) is None, 'BUSY')
        if not os.path.lexists(self.directory): self.directory.mkdir(mode=0o700); self.journal.sync(self.journal.directory)
        self.journal.check_directory(self.directory)
        slot = self.directory/(identity+'-'+kind)
        redacted = protocol.decode(protocol.encode(request)); redacted.pop('passphrase', None)
        if 'backup' in redacted: redacted['backupSha256'] = hashlib.sha256(protocol.encode(redacted.pop('backup'))).hexdigest()
        if 'token' in redacted: redacted['handoffId'] = redacted.pop('token').split('.')[1]
        if os.path.lexists(slot):
            self.journal.check_directory(slot)
            previous = protocol.decode(self.journal.read(slot/'intent.json', 12288))
            protocol.require(previous['kind'] == kind and previous['nativeOperationId'] == identity and previous['request'] == redacted, 'CONFLICT')
            fail('UNRESOLVED_OPERATION')  # Reservation/response ambiguity never reaches a later first writer.
        protocol.require(self.journal.active_count('ADMISSION',list(self.directory.iterdir())) < 256, 'CAPACITY')
        slot.mkdir(mode=0o700); self.journal.sync(self.directory)
        admission = str(uuid.uuid4())
        self.journal.write_new(slot/'intent.json', dict(schema=1, purpose='yofc.kura.sender-attempt.v1', admissionId=admission,
            kind=kind, nativeOperationId=identity, request=redacted))
        namespace = self.client(dict(schema=1, action='gwt-sender-namespace'))
        protocol.fields(namespace, {'schema', 'namespaceSha256', 'rootDevice', 'rootInode'})
        protocol.require(type(namespace['schema']) is int and namespace['schema'] == 1)
        realm = protocol.digest(namespace['namespaceSha256'])
        self.journal.write_new(slot/'namespace.json', dict(schema=1, namespaceSha256=realm))
        response = self.client(dict(schema=1, action='sender-reserve', admissionId=admission, source='recovery',
            namespaceSha256=realm, request=request))
        protocol.fields(response, {'schema', 'admissionId', 'state', 'source', 'namespaceSha256', 'nativeOperationId', 'nativeAction', 'newlyReserved'})
        expected_action = self.native_action(kind,request)
        protocol.require(type(response['schema']) is int and response['schema'] == 1 and response['admissionId'] == admission
            and response['state'] == 'RESERVED' and response['source'] == 'recovery' and response['namespaceSha256'] == realm
            and response['nativeOperationId'] == identity and response['nativeAction'] == expected_action
            and response['newlyReserved'] is True, 'UNRESOLVED_OPERATION')
        self.context.current = dict(admissionId=admission, namespaceSha256=realm, request=request)
        try: return callback()
        finally: self.context.current = None


class RootClient:
    def __call__(self, request):
        request = SenderAdmission.wrap(request)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            stream.settimeout(25)
            stream.connect(protocol.SOCKET)
            protocol.require(protocol.peer(stream)[1] == 0, 'FORBIDDEN')
            protocol.send_frame(stream, request)
            stream.shutdown(socket.SHUT_WR)
            response = protocol.decode(protocol.read_frame(stream))
            protocol.require(stream.recv(1) == b'', 'PROTOCOL_MISMATCH')
            return response


class Journal:
    """Public intent metadata only. An existing UUID never dispatches a writer."""
    def __init__(self, directory=STATE, *, archive_module=None):
        self.directory = Path(directory)
        self.owner = os.geteuid()
        self.archive_module=archive_module
        self.archive_client=None
        self._archive=None
        self.check_directory(self.directory)
        self.operations = self.directory / 'operations'
        try:
            self.operations.mkdir(mode=0o700)
        except FileExistsError:
            pass
        self.check_directory(self.operations)
        self.starts = self.directory / 'starts'
        try:self.starts.mkdir(mode=0o700)
        except FileExistsError:pass
        self.check_directory(self.starts)
        path = self.directory / 'admission.lock'
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.fsync(fd)
            os.close(fd)
            self.sync(self.directory)
        except FileExistsError:
            pass
        self.read(path, 0)
        self.thread_lock = threading.Lock()

    def history(self):
        protocol.require(self.archive_client is not None,'UNAVAILABLE')
        if self._archive is None:
            module=Lifecycle().journal_module() if self.archive_module is None else self.archive_module
            self._archive=module.RecoveryPrivateArchive(self,self.archive_client)
        return self._archive

    def active_count(self,kind,records):
        if not os.path.lexists(self.directory/'archives'):return len(records)
        try:
            self.check_directory(self.directory/'archives');history=self.history();count=0
            for record in records:
                step=None
                if isinstance(record,dict):identity=record['operationId']
                elif kind=='ADMISSION':
                    identity=record.name[:36];step=record.name[37:]
                    protocol.require(record.name==identity+'-'+step,'UNSAFE_JOURNAL')
                else:identity=record.name if kind=='HANDOFF' else record.name[:-5]
                if not history.archived(kind,identity,step):count+=1
            return count
        except Refused:fail('UNRESOLVED_OPERATION')

    def check_directory(self, path):
        st = path.lstat()
        protocol.require(stat.S_ISDIR(st.st_mode) and st.st_uid == self.owner
                         and stat.S_IMODE(st.st_mode) == 0o700, 'UNSAFE_JOURNAL')

    def read(self, path, limit=4096, *, durable=False):
        self.check_directory(path.parent)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            st = os.fstat(fd)
            protocol.require(stat.S_ISREG(st.st_mode) and st.st_uid == self.owner
                             and st.st_nlink == 1 and stat.S_IMODE(st.st_mode) == 0o600
                             and st.st_size <= limit, 'UNSAFE_JOURNAL')
            data = os.read(fd, limit + 1)
            if durable:os.fsync(fd)
            after=os.fstat(fd)
            try:current=path.lstat()
            except FileNotFoundError:fail('UNSAFE_JOURNAL')
            protocol.require(len(data)==st.st_size and len(data)<=limit
                and (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)==
                    (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
                and (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)==
                    (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns,current.st_ctime_ns), 'UNSAFE_JOURNAL')
            return data
        finally:
            os.close(fd)

    @staticmethod
    def sync(directory):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def lock(self):
        protocol.require(self.thread_lock.acquire(blocking=False), 'BUSY')
        fd = None
        try:
            path = self.directory / 'admission.lock'
            self.read(path, 0)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail('BUSY')
            yield
        finally:
            if fd is not None:
                os.close(fd)
            self.thread_lock.release()

    def record(self, identity):
        protocol.operation_id(identity)
        try:
            value = protocol.decode(self.read(self.operations / (identity + '.json')))
        except FileNotFoundError:
            return None
        protocol.fields(value, {'schema', 'operationId', 'expectedKeySha256', 'backupSha256'})
        protocol.require(type(value['schema']) is int and value['schema'] == 1
                         and value['operationId'] == identity, 'UNSAFE_JOURNAL')
        protocol.digest(value['expectedKeySha256'])
        protocol.digest(value['backupSha256'])
        return value

    def records(self):
        names = list(self.operations.iterdir())
        protocol.require(self.active_count('RESTORE',names) <= MAX_OPERATIONS, 'UNSAFE_JOURNAL')
        result = []
        for path in names:
            protocol.require(path.name.endswith('.json'), 'UNSAFE_JOURNAL')
            result.append(self.record(protocol.operation_id(path.name[:-5])))
        return result

    def admit(self, value):
        # Exclusive creation preserves ambiguous/incomplete admission across restarts.
        # A crash after create but before fsync leaves an unsafe slot, never a retry.
        self.check_directory(self.operations)
        fd = os.open(self.operations / (value['operationId'] + '.json'),
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(protocol.encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        self.sync(self.operations)


    def pending(self):
        try:value=protocol.decode(self.read(self.directory/'pending.json'))
        except FileNotFoundError:return None
        protocol.fields(value,{'schema','operationId','expectedKeySha256'})
        protocol.require(type(value['schema']) is int and value['schema']==1,'UNSAFE_JOURNAL')
        protocol.operation_id(value['operationId']);protocol.digest(value['expectedKeySha256'])
        return value

    def mark(self, identity, expected):
        value=dict(schema=1,operationId=identity,expectedKeySha256=expected)
        existing=self.pending()
        if existing is not None:
            protocol.require(existing==value,'UNRESOLVED_OPERATION')
            return
        self.write_new(self.directory/'pending.json',value)

    def retire_pending(self, destination, expected):
        source=self.directory/'pending.json'
        raw=self.read(source,durable=True)
        protocol.require(self.pending()==expected,'CONFLICT')
        self.check_directory(destination.parent)
        protocol.rename_no_replace(source,destination)
        self.sync(destination.parent);self.sync(self.directory)
        protocol.require(self.read(destination)==raw,'UNSAFE_JOURNAL')

    def write_new(self, path, value):
        self.check_directory(path.parent)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(protocol.encode(value));stream.flush();os.fsync(stream.fileno())
        self.sync(path.parent)

    def start_record(self, identity):
        protocol.operation_id(identity)
        try:value=protocol.decode(self.read(self.starts/(identity+'.json')))
        except FileNotFoundError:return None
        modern=type(value.get('schema')) is int and value['schema']==2
        extra={'predecessorStartOperationId','maintenanceId','manifestSha256'} if modern else set()
        protocol.fields(value,{'schema','operationId','restoreOperationId','expectedKeySha256'}|extra)
        protocol.require(type(value['schema']) is int and value['schema'] in (1,2) and value['operationId']==identity,'UNSAFE_JOURNAL')
        if modern:
            protocol.operation_id(value['predecessorStartOperationId']);protocol.operation_id(value['maintenanceId']);protocol.digest(value['manifestSha256'])
        protocol.operation_id(value['restoreOperationId']);protocol.digest(value['expectedKeySha256'])
        return value

    def start_records(self):
        self.check_directory(self.starts)
        paths=list(self.starts.iterdir());protocol.require(self.active_count('START',paths)<=MAX_OPERATIONS,'UNSAFE_JOURNAL')
        result=[]
        for path in paths:
            protocol.require(path.name.endswith('.json'),'UNSAFE_JOURNAL')
            result.append(self.start_record(path.name[:-5]))
        return result


class Controller:
    def __init__(self, client=None, journal=None, sender=None):
        self.client = RootClient() if client is None else client
        self.journal = Journal() if journal is None else journal
        self.sender = SenderAdmission(self.client, self.journal) if sender is None else sender
        self.inspect_lock = threading.Lock()
        self.last_inspect = None

    def call(self, action, **fields):
        value = self.client(dict(schema=1, action=action, **fields))
        protocol.require(isinstance(value, dict) and type(value.get('schema')) is int
                         and value['schema'] == 1, 'PROTOCOL_MISMATCH')
        if 'error' in value:
            protocol.fields(value, {'schema', 'error'})
            # Never reflect an upstream error string or exception into HTML/logs.
            protocol.require(value['error'] in {'BACKUP_REJECTED', 'BUSY', 'MAINTENANCE', 'CONFLICT',
                'KEY_MISSING', 'CAPACITY', 'UNRESOLVED_OPERATION', 'UNKNOWN', 'UNSAFE_JOURNAL',
                'UNSAFE_FILESYSTEM', 'UNAVAILABLE', 'CIPHER_UNAVAILABLE', 'INVALID_ARGUMENT', 'FORBIDDEN'}, 'UNAVAILABLE')
            fail(value['error'])
        return value

    def status(self):
        value = self.call('status')
        protocol.fields(value, {'schema', 'keyReady', 'keySha256', 'legacyKey', 'agentRequired'})
        protocol.digest(value['keySha256'])
        protocol.require(type(value['keyReady']) is bool and type(value['legacyKey']) is bool
                         and value['agentRequired'] is False, 'PROTOCOL_MISMATCH')
        pending=self.journal.pending()
        starts=self.active_start_records()
        linked=[r for r in starts if pending is not None and r['restoreOperationId']==pending['operationId']]
        leaves=self.start_leaves(linked)
        plan=None
        if pending is not None and leaves and value['keyReady']:
            try:plan=self.start_plan(pending)
            except (protocol.Failure,OSError,KeyError,ValueError):pass
        return dict(value,state='STATUS',pendingRestore=pending,pendingStart=leaves[0] if leaves else None,startPlan=plan)

    @staticmethod
    def start_leaves(records):
        ids={r['operationId'] for r in records}
        parents={r['predecessorStartOperationId'] for r in records if r['schema']==2}
        protocol.require(parents<=ids,'UNSAFE_JOURNAL')
        leaves=[r for r in records if r['operationId'] not in parents]
        protocol.require(len(leaves)==(1 if records else 0),'UNSAFE_JOURNAL')
        return leaves

    def start_plan(self,pending):
        value=self.call('core-start-plan',restoreOperationId=pending['operationId'],expectedKeySha256=pending['expectedKeySha256'])
        protocol.fields(value,{'schema','state','startAllowed','maintenanceId','predecessorStartOperationId','manifestSha256','blockingOperationId'})
        protocol.require(value['state']=='START_PLAN' and type(value['startAllowed']) is bool,'PROTOCOL_MISMATCH')
        for key in ['maintenanceId','predecessorStartOperationId','blockingOperationId']:
            if value[key] is not None:protocol.operation_id(value[key])
        if value['manifestSha256'] is not None:protocol.digest(value['manifestSha256'])
        if value['startAllowed']:
            protocol.require(value['blockingOperationId'] is None and all(value[k] is not None for k in
                ['maintenanceId','predecessorStartOperationId','manifestSha256']),'PROTOCOL_MISMATCH')
        return value

    @staticmethod
    def material(value):
        protocol.passphrase(value['passphrase'])
        raw = value['backupJson']
        protocol.require(isinstance(raw, str) and len(raw.encode('utf-8')) <= 49152, 'BACKUP_REJECTED')
        backup = protocol.decode(raw.encode('utf-8'))
        protocol.fields(backup, {'format', 'operationId', 'encrypted'})
        protocol.require(backup['format'] == protocol.FORMAT, 'BACKUP_REJECTED')
        protocol.operation_id(backup['operationId'])
        protocol.require(isinstance(backup['encrypted'], str) and 0 < len(backup['encrypted']) <= 32768,
                         'BACKUP_REJECTED')
        return backup

    def active_start_records(self):
        records=[]
        for record in self.journal.start_records():
            identity=record['operationId']
            if self.sender.has_attempt('start',identity):
                saved=self.sender.load('start',identity)
                if saved is not None and saved[2]:
                    try:expected=receiver_start_intent(saved[0])
                    except Refused:fail('UNSAFE_JOURNAL')
                    protocol.require(record==expected,'CONFLICT')
                    current=self.sender.view('start',identity)
                    if (current['phase']=='NOT_ADMITTED' and current['closed']
                        and not self.sender.has_key_intent(identity,permitted_start=expected)):
                        original=self.call('core-start-read',operationId=identity)
                        protocol.fields(original,{'schema','state'})
                        protocol.require(type(original['schema']) is int and original['schema']==1
                            and original['state']=='NOT_FOUND','UNRESOLVED_OPERATION')
                        continue  # Preserve the private file; only a confirmed original closure releases admission.
            records.append(record)
        return records

    def restore_marker_state(self, attempt):
        expected=receiver_restore_intent(attempt);identity=expected['operationId']
        local=self.journal.record(identity)
        if local is not None and local!=expected:return 'CONFLICT'
        archive=self.sender.path('restore',identity)/'pending.json'
        try:retired=protocol.decode(self.journal.read(archive))
        except FileNotFoundError:retired=None
        if retired is not None:
            try:validate_receiver_pending(retired,attempt)
            except Refused:fail('UNSAFE_JOURNAL')
        pending=self.journal.pending()
        if pending is not None and pending['operationId']==identity:
            return 'ACTIVE' if retired is None and pending==receiver_restore_pending(attempt) else 'CONFLICT'
        return 'CONFLICT' if local is not None and retired is None else 'RETIRED'

    def active_restore_records(self):
        records=[]
        for record in self.journal.records():
            identity=record['operationId']
            if self.sender.has_attempt('restore',identity):
                saved=self.sender.load('restore',identity)
                if saved is not None and saved[2]:
                    protocol.require(record==receiver_restore_intent(saved[0]),'CONFLICT')
                    current=self.sender.view('restore',identity)
                    if (current['phase']=='NOT_ADMITTED' and current['closed']
                        and self.restore_marker_state(saved[0])=='RETIRED'
                        and not self.sender.has_key_intent(identity,permitted_restore=record)):
                        original=self.call('operation-read',operationId=identity)
                        protocol.fields(original,{'schema','state'})
                        protocol.require(type(original['schema']) is int and original['schema']==1
                            and original['state']=='NOT_FOUND','UNRESOLVED_OPERATION')
                        continue
            records.append(record)
        return records

    def admission(self, value):
        command=value.get('command');protocol.require(command in ('read','close'))
        protocol.fields(value,{'command','kind','operationId'} | ({'backupJson','passphrase'} if command=='close' else set()))
        kind=value['kind'];protocol.require(kind in ('restore','start'));identity=protocol.operation_id(value['operationId'])
        with self.journal.lock():
            current=self.sender.view(kind,identity)
            saved=self.sender.load(kind,identity)
            permitted=None;restore=None;pending=None;marker='RETIRED'
            if kind=='start' and saved is not None:
                try:permitted=receiver_start_intent(saved[0])
                except Refused:fail('UNSAFE_JOURNAL')
            if kind=='restore' and saved is not None:
                try:restore=receiver_restore_intent(saved[0]);pending=receiver_restore_pending(saved[0])
                except Refused:fail('UNSAFE_JOURNAL')
                marker=self.restore_marker_state(saved[0])
            owning=marker=='CONFLICT' or self.sender.has_key_intent(identity,permitted_start=permitted,
                permitted_restore=restore,permitted_pending=pending)
            if owning:current.update(closeAllowed=False,closed=False)
            elif marker=='ACTIVE' and current['phase']=='NOT_ADMITTED' and current['closed']:
                current.update(closeAllowed=True,closed=False)
            if command=='read':return current
            protocol.require(not owning and (current['closeAllowed'] or current['phase']=='NOT_ADMITTED' and current['closed']),'UNRESOLVED_OPERATION')
            protocol.require(saved is not None,'UNRESOLVED_OPERATION');metadata=saved[0]['request']
            backup=self.material(value);backup_sha=hashlib.sha256(protocol.encode(backup)).hexdigest()
            if kind=='start':
                restore=self.journal.record(metadata['restoreOperationId'])
                protocol.require(restore is not None and restore['expectedKeySha256']==metadata['expectedKeySha256'],'CONFLICT')
                expected_backup=restore['backupSha256']
            else:expected_backup=metadata['backupSha256']
            protocol.require(backup_sha==expected_backup,'BACKUP_REJECTED')
            checked=self.inspect(dict(backupJson=value['backupJson'],passphrase=value['passphrase']))
            protocol.require(checked['sameDeviceKey'] and checked['keySha256']==metadata['expectedKeySha256'],'BACKUP_REJECTED')
            original=self.call('operation-read' if kind=='restore' else 'core-start-read',operationId=identity)
            protocol.fields(original,{'schema','state'});protocol.require(type(original['schema']) is int and original['schema']==1 and original['state']=='NOT_FOUND','UNRESOLVED_OPERATION')
            result=self.sender.close(kind,identity)
            if kind=='restore' and marker=='ACTIVE':
                self.journal.retire_pending(self.sender.path(kind,identity)/'pending.json',pending)
            return result

    def inspect(self, value, *, throttle=True):
        protocol.fields(value, {'backupJson', 'passphrase'})
        backup = self.material(value)
        protocol.require(self.inspect_lock.acquire(blocking=False), 'BUSY')
        try:
            protocol.require(not throttle or self.last_inspect is None or time.monotonic() - self.last_inspect >= 2, 'BUSY')
            self.last_inspect = time.monotonic()
            result = self.call('backup-inspect', backup=backup, passphrase=value['passphrase'])
        finally:
            self.inspect_lock.release()
        protocol.fields(result, {'schema', 'backupOperationId', 'keySha256', 'createdAt',
                                 'sameDeviceKey', 'keyReady', 'restoreAllowed'})
        protocol.require(result['backupOperationId'] == backup['operationId'], 'PROTOCOL_MISMATCH')
        protocol.digest(result['keySha256'])
        protocol.require(isinstance(result['createdAt'], str) and len(result['createdAt']) <= 128
                         and all(type(result[k]) is bool for k in ['sameDeviceKey', 'keyReady', 'restoreAllowed']),
                         'PROTOCOL_MISMATCH')
        result['restoreAllowed'] = result['restoreAllowed'] and result['sameDeviceKey'] and not result['keyReady']
        return dict(result, state='INSPECTED')

    def archive(self,value):
        command=value.get('command');kind=value.get('kind');identity=protocol.operation_id(value.get('operationId'))
        protocol.require(command in ('preview','query','archive','continue') and kind in ('RESTORE','START','ADMISSION'))
        mutate=command in ('archive','continue');extra={'senderKind'} if kind=='ADMISSION' else set()
        protocol.fields(value,{'command','kind','operationId'}|extra|({'backupJson','passphrase'} if mutate else set()))
        step=value.get('senderKind');protocol.require(step in ('restore','start') if kind=='ADMISSION' else step is None)
        try:
            with self.journal.lock():
                history=self.journal.history();snapshot=history.format.snapshot(kind,identity,step)
                if mutate:
                    metadata=snapshot['metadata'];backup=self.material(value)
                    restore=metadata if kind=='RESTORE' or kind=='ADMISSION' and step=='restore' else self.journal.record(metadata['restoreOperationId'])
                    protocol.require(restore is not None and restore['expectedKeySha256']==metadata['expectedKeySha256']
                        and hashlib.sha256(protocol.encode(backup)).hexdigest()==restore['backupSha256'],'BACKUP_REJECTED')
                    checked=self.inspect(dict(backupJson=value['backupJson'],passphrase=value['passphrase']))
                    protocol.require(checked['sameDeviceKey'] and checked['keySha256']==metadata['expectedKeySha256'],'BACKUP_REJECTED')
                return history.archive(kind,identity,step,preview=not mutate,continue_metadata=command=='continue')
        except Refused:fail('UNRESOLVED_OPERATION')

    def original(self, identity, expected=None):
        protocol.operation_id(identity)
        unknown = dict(schema=1, operationId=identity, state='UNKNOWN', resultSource='UNCONFIRMED')
        try:
            result = self.call('operation-read', operationId=identity)
            if result.get('state') != 'SUCCEEDED':
                return unknown
            protocol.fields(result, {'schema', 'operationId', 'state', 'action', 'keySha256',
                                     'keyChanged', 'existingReceiptPreserved'})
            protocol.digest(result['keySha256'])
            protocol.require(result['operationId'] == identity and result['action'] == 'restore'
                             and type(result['keyChanged']) is bool and result['existingReceiptPreserved'] is True
                             and (expected is None or result['keySha256'] == expected), 'PROTOCOL_MISMATCH')
            return dict(result, resultSource='ROOT_ORIGINAL')
        except (protocol.Failure, OSError, KeyError, ValueError):
            return unknown

    def restore(self, value):
        protocol.fields(value, {'operationId', 'expectedKeySha256', 'backupJson', 'passphrase'})
        identity = protocol.operation_id(value['operationId'])
        expected = protocol.digest(value['expectedKeySha256'])
        backup = self.material(value)
        intent = dict(schema=1, operationId=identity, expectedKeySha256=expected,
                      backupSha256=hashlib.sha256(protocol.encode(backup)).hexdigest())
        with self.journal.lock():
            prior = self.journal.record(identity)
            if prior is not None:
                protocol.require(prior == intent, 'CONFLICT')
                return self.original(identity, expected)
            protocol.require(not HandoffController(self.client, self.journal).pending(), 'UNRESOLVED_OPERATION')
            # Read the original before admission. A previously accepted Root UUID
            # cannot be sent again even when this UI has no local slot for it.
            original = self.call('operation-read', operationId=identity)
            if original.get('state') != 'NOT_FOUND':
                return self.original(identity, expected)
            protocol.fields(original, {'schema', 'state'})
            records = self.active_restore_records()
            protocol.require(self.journal.active_count('RESTORE',self.journal.records()) < MAX_OPERATIONS, 'CAPACITY')
            for record in self.active_start_records():
                protocol.require(self.start_original(record['operationId'])['state']=='SUCCEEDED','UNRESOLVED_OPERATION')
            for record in records:
                protocol.require(self.original(record['operationId'], record['expectedKeySha256'])['state'] == 'SUCCEEDED',
                                 'UNRESOLVED_OPERATION')
            state = self.status()
            protocol.require(not state['keyReady'] and state['keySha256'] == expected, 'CONFLICT')
            checked = self.inspect(dict(backupJson=value['backupJson'], passphrase=value['passphrase']), throttle=False)
            protocol.require(checked['restoreAllowed'] and checked['keySha256'] == expected, 'BACKUP_REJECTED')
            request = dict(schema=1, action='restore', operationId=identity, expectedKeySha256=expected,
                backup=backup, passphrase=value['passphrase'])
            def forward():
                self.journal.mark(identity,expected); self.journal.admit(intent)
                try: self.call('restore', operationId=identity, expectedKeySha256=expected, backup=backup, passphrase=value['passphrase'])
                except (protocol.Failure, OSError, KeyError, ValueError): pass
                return self.original(identity, expected)
            return self.sender.submit('restore', identity, request, forward)


    def start_original(self, identity, restore_id=None, expected=None):
        protocol.operation_id(identity)
        unknown=dict(schema=1,operationId=identity,state='UNKNOWN',resultSource='UNCONFIRMED')
        try:
            result=self.call('core-start-read',operationId=identity)
            modern=result.get('action')=='core-start-after-maintenance'
            extra={'predecessorStartOperationId','maintenanceId','manifestSha256'} if modern else set()
            protocol.fields(result,{'schema','operationId','restoreOperationId','keySha256','action','state','scope','jobPath'}|extra)
            if modern:
                protocol.operation_id(result['predecessorStartOperationId']);protocol.operation_id(result['maintenanceId']);protocol.digest(result['manifestSha256'])
            protocol.operation_id(result['restoreOperationId']);protocol.digest(result['keySha256'])
            protocol.require(result['operationId']==identity and result['action'] in ('core-start','core-start-after-maintenance')
                and result['state']=='SUCCEEDED' and result['scope']=='SYSTEMD_JOB_ACCEPTED'
                and re.fullmatch(r'/org/freedesktop/systemd1/job/[0-9]+',result['jobPath']) is not None
                and (restore_id is None or result['restoreOperationId']==restore_id)
                and (expected is None or result['keySha256']==expected),'PROTOCOL_MISMATCH')
            return dict(result,resultSource='ROOT_ORIGINAL')
        except (protocol.Failure,OSError,KeyError,ValueError,TypeError):return unknown

    def start(self,value,*,maintenance=False):
        extra={'predecessorStartOperationId','maintenanceId','manifestSha256'} if maintenance else set()
        protocol.fields(value,{'operationId','restoreOperationId','expectedKeySha256'}|extra)
        if maintenance:
            protocol.operation_id(value['predecessorStartOperationId']);protocol.operation_id(value['maintenanceId']);protocol.digest(value['manifestSha256'])
        identity=protocol.operation_id(value['operationId']);restore_id=protocol.operation_id(value['restoreOperationId'])
        expected=protocol.digest(value['expectedKeySha256'])
        intent=dict(schema=2 if maintenance else 1,**value)
        with self.journal.lock():
            prior=self.journal.start_record(identity)
            if prior is not None:
                protocol.require(prior==intent,'CONFLICT')
                return self.start_original(identity,restore_id,expected)
            protocol.require(not HandoffController(self.client, self.journal).pending(), 'UNRESOLVED_OPERATION')
            original=self.call('core-start-read',operationId=identity)
            if original.get('state')!='NOT_FOUND':return self.start_original(identity,restore_id,expected)
            pending=self.journal.pending()
            protocol.require(pending==dict(schema=1,operationId=restore_id,expectedKeySha256=expected),'CONFLICT')
            local=self.journal.record(restore_id)
            protocol.require(local is not None and local['expectedKeySha256']==expected,'CONFLICT')
            restored=self.original(restore_id,expected)
            protocol.require(restored['state']=='SUCCEEDED' and restored.get('keyChanged') is True,'UNRESOLVED_OPERATION')
            records=self.active_start_records()
            protocol.require(self.journal.active_count('START',self.journal.start_records())<MAX_OPERATIONS,'CAPACITY')
            if maintenance:
                plan=self.start_plan(pending)
                protocol.require(plan['startAllowed'] and all(plan[k]==value[k] for k in extra),'CONFLICT')
            for record in records:
                protocol.require(maintenance or record['restoreOperationId']!=restore_id,'CONFLICT')
                protocol.require(self.start_original(record['operationId'])['state']=='SUCCEEDED','UNRESOLVED_OPERATION')
            action = 'core-start-after-maintenance' if maintenance else 'core-start'
            request = dict(schema=1, action=action, **value)
            def forward():
                self.journal.write_new(self.journal.starts/(identity+'.json'),intent)
                try:self.call(action,**value)
                except (protocol.Failure,OSError,KeyError,ValueError):pass
                return self.start_original(identity,restore_id,expected)
            return self.sender.submit('start', identity, request, forward)

    def complete(self, value):
        protocol.fields(value,{'operationId'})
        identity=protocol.operation_id(value['operationId'])
        with self.journal.lock():
            slot=self.journal.start_record(identity)
            protocol.require(slot is not None,'CONFLICT')
            records=[r for r in self.active_start_records() if r['restoreOperationId']==slot['restoreOperationId']]
            leaves=self.start_leaves(records)
            protocol.require(leaves and leaves[0]['operationId']==identity,'CONFLICT')
            protocol.require(all(self.start_original(r['operationId'])['state']=='SUCCEEDED' for r in records),'UNRESOLVED_OPERATION')
            result=self.start_original(identity,slot['restoreOperationId'],slot['expectedKeySha256'])
            protocol.require(result['state']=='SUCCEEDED','UNRESOLVED_OPERATION')
            plan=self.start_plan(dict(operationId=slot['restoreOperationId'],expectedKeySha256=slot['expectedKeySha256']))
            protocol.require(plan['blockingOperationId'] is None,'UNRESOLVED_OPERATION')
            pending=self.journal.pending()
            if pending is not None:
                protocol.require(pending['operationId']==slot['restoreOperationId']
                    and pending['expectedKeySha256']==slot['expectedKeySha256'],'CONFLICT')
                (self.journal.directory/'pending.json').unlink();self.journal.sync(self.journal.directory)
            return result


class HandoffController:
    """Fixed original authority only. Never persist or recover a bearer from an ID.

    Each publish, continuation and start has an immutable sender INTENT. A lost
    reply permits original reads, never a second forwarding call. Completion is
    a local acknowledgement of two Root originals, not application readiness.
    """
    IDS = HANDOFF_IDS
    BINDING = HANDOFF_BINDING
    WRITERS = frozenset(('publish', 'continue', 'start'))
    FILES = frozenset(('binding.json', 'publish.json', 'continue.json', 'start.json', 'completed.json', 'retired.json'))

    def __init__(self, client, journal, sender=None):
        self.client, self.journal = client, journal
        self.sender = SenderAdmission(client, journal) if sender is None else sender
        self.directory = journal.directory / 'handoffs'
        try:
            self.directory.mkdir(mode=0o700)
            journal.sync(journal.directory)
        except FileExistsError:
            pass
        journal.check_directory(self.directory)

    @staticmethod
    def token(value):
        protocol.require(isinstance(value, str) and re.fullmatch(
            r'KURA-HANDOFF-1\.[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.[0-9a-f]{64}', value), 'INVALID_ARGUMENT')
        return value

    def call(self, token, command, **extra):
        value = self.client(dict(schema=1, action='generation-handoff-command', token=token, command=command, **extra))
        protocol.require(isinstance(value, dict) and type(value.get('schema')) is int and value['schema'] == 1, 'PROTOCOL_MISMATCH')
        if 'error' in value:
            protocol.fields(value, {'schema', 'error'})
            fail('UNAVAILABLE')  # Do not expose Root error text or request contents.
        return value

    @classmethod
    def binding(cls, info):
        binding = {name: info[name] for name in cls.BINDING}
        try: validate_handoff_binding(binding)
        except Refused: fail('PROTOCOL_MISMATCH')
        return binding

    def info(self, token):
        value = self.call(token, 'info')
        protocol.fields(value, self.BINDING | {'state', 'scope', 'issuedAt', 'expiresAt', 'mutationWindowOpen', 'startupAuthorized'})
        self.binding(value)
        protocol.require(value['handoffId'] == token.split('.')[1] and value['state'] in ('GRANT_RECORDED', 'GRANT_REVOKING', 'GRANT_REVOKED')
            and value['scope'] == 'ORIGINAL_AUTHORIZATION_ONLY' and value['startupAuthorized'] is False
            and type(value['mutationWindowOpen']) is bool and type(value['issuedAt']) is int
            and type(value['expiresAt']) is int and value['issuedAt'] >= 0 and value['expiresAt'] - value['issuedAt'] == 900, 'PROTOCOL_MISMATCH')
        protocol.require(value['state'] == 'GRANT_RECORDED' or value['mutationWindowOpen'] is False, 'PROTOCOL_MISMATCH')
        return value

    def retirement(self, binding):
        path = self.directory/binding['handoffId']/'retired.json'
        if not os.path.lexists(path): return None
        value = self.load(path)
        try: validate_handoff_retired(value, binding)
        except Refused: fail('UNSAFE_JOURNAL')
        original = self.client(dict(schema=1, action='generation-handoff-revocation-read', handoffId=binding['handoffId']))
        protocol.require(original == value, 'UNRESOLVED_OPERATION')
        self.retirement_attempts(binding, value['namespaceSha256'], closed=True)
        return value

    def retirement_attempts(self, binding, namespace=None, *, closed=False):
        slot = self.directory/binding['handoffId']
        for command, kind, key in (('publish', 'publish', 'publicationId'), ('start', 'handoff-start', 'startOperationId')):
            saved = self.sender.load(kind, binding[key])
            if saved is None:
                protocol.require(not os.path.lexists(slot/(command+'.json')), 'UNRESOLVED_OPERATION')
                continue
            attempt, realm, finished = saved
            protocol.require(attempt['request']['handoffId'] == binding['handoffId'] and realm is not None
                and (namespace is None or realm['namespaceSha256'] == namespace), 'CONFLICT')
            view = self.sender.view(kind, binding[key])
            protocol.require(view['phase'] in ('RESERVED', 'NOT_ADMITTED'), 'UNRESOLVED_OPERATION')
            if closed: protocol.require(finished and view['phase'] == 'NOT_ADMITTED' and view['closed'], 'UNRESOLVED_OPERATION')
        protocol.require(not self.sender.has_attempt('continue', binding['publicationId'])
            and not os.path.lexists(slot/'continue.json'), 'UNRESOLVED_OPERATION')

    def revoke(self, token):
        info = self.info(token); binding = self.binding(info); flags, completed, _ = self.local(info)
        protocol.require(not completed and not flags['continue'], 'UNRESOLVED_OPERATION')
        for identity in (binding['publicationId'], binding['startOperationId']):
            protocol.require(not self.sender.has_key_intent(identity, permitted_handoff=binding['handoffId']), 'UNRESOLVED_OPERATION')
        self.retirement_attempts(binding)
        for start in (False, True):
            original = self.original(token, info, start=start)
            protocol.require(original['state'] == 'NOT_RECORDED' and original['resultSource'] == 'ROOT_ABSENCE', 'UNRESOLVED_OPERATION')
        value = self.call(token, 'revoke')
        try: validate_handoff_retired(value, binding)
        except Refused: fail('PROTOCOL_MISMATCH')
        self.retirement_attempts(binding, value['namespaceSha256'])
        for kind, key in (('publish', 'publicationId'), ('handoff-start', 'startOperationId')):
            if self.sender.has_attempt(kind, binding[key]): self.sender.close(kind, binding[key])
        self.retirement_attempts(binding, value['namespaceSha256'], closed=True)
        slot = self.directory/binding['handoffId']
        if not os.path.lexists(slot):
            protocol.require(self.journal.active_count('HANDOFF',self.slots()) < MAX_OPERATIONS, 'CAPACITY')
            slot.mkdir(mode=0o700); self.journal.sync(self.directory); self.journal.write_new(slot/'binding.json', binding)
        if os.path.lexists(slot/'retired.json'): protocol.require(self.load(slot/'retired.json') == value, 'CONFLICT')
        else: self.journal.write_new(slot/'retired.json', value)
        return self.snapshot(token)

    def load(self, path):
        return protocol.decode(self.journal.read(path, 8192))

    def slots(self):
        self.journal.check_directory(self.directory)
        paths = list(self.directory.iterdir())
        protocol.require(self.journal.active_count('HANDOFF',paths) <= MAX_OPERATIONS, 'CAPACITY')
        for path in paths:
            protocol.operation_id(path.name); self.journal.check_directory(path)
            protocol.require({p.name for p in path.iterdir()} <= self.FILES, 'UNSAFE_JOURNAL')
        return paths

    def local(self, info):
        binding = self.binding(info); slot = self.directory / info['handoffId']
        paths = self.slots(); flags = {name: False for name in self.WRITERS}
        completed, other_pending = False, False
        for path in paths:
            protocol.require(not (os.path.lexists(path/'completed.json') and os.path.lexists(path/'retired.json')), 'UNSAFE_JOURNAL')
            saved = self.load(path / 'binding.json')
            protocol.fields(saved, self.BINDING); self.binding(saved)
            protocol.require(saved['handoffId'] == path.name, 'UNSAFE_JOURNAL')
            if path == slot:
                protocol.require(saved == binding, 'CONFLICT')
            for name in self.WRITERS:
                target = path / (name + '.json')
                if os.path.lexists(target):
                    intent = self.load(target)
                    extra = {'expectedRecoveryReceiptSha256'} if name == 'continue' else set()
                    protocol.fields(intent, self.BINDING | {'command'} | extra)
                    protocol.require({k: intent[k] for k in self.BINDING} == saved and intent['command'] == name, 'UNSAFE_JOURNAL')
                    if extra: protocol.digest(intent['expectedRecoveryReceiptSha256'])
                    if path == slot: flags[name] = True
            done = path / 'completed.json'
            if os.path.lexists(done):
                receipt = self.load(done)
                protocol.fields(receipt, self.BINDING | {'state', 'publicationSha256', 'jobPath'})
                protocol.require({k: receipt[k] for k in self.BINDING} == saved and receipt['state'] == 'ORIGINAL_REQUESTS_CONFIRMED'
                    and re.fullmatch(r'/org/freedesktop/systemd1/job/[0-9]+', receipt['jobPath']) is not None, 'UNSAFE_JOURNAL')
                protocol.digest(receipt['publicationSha256'])
                if path == slot: completed = True
            elif self.retirement(saved) is not None:
                protocol.require(not os.path.lexists(path/'continue.json'), 'UNSAFE_JOURNAL')
            elif path != slot:
                other_pending = True
        return flags, completed, other_pending

    def pending(self):
        slots = self.slots()
        if not slots: return False
        _, completed, other_pending = self.local(self.load(slots[0] / 'binding.json'))
        binding = self.load(slots[0]/'binding.json')
        return not completed and self.retirement(binding) is None or other_pending

    @staticmethod
    def unknown(identity):
        return dict(operationId=identity, state='UNKNOWN', resultSource='UNCONFIRMED', recoveryReceiptSha256=None)

    def original(self, token, info, *, start=False):
        identity = info['startOperationId' if start else 'publicationId']
        value = self.call(token, 'start-read' if start else 'publication-read')
        protocol.require(value.get('operationId') == identity, 'PROTOCOL_MISMATCH')
        if value.get('state') == 'NOT_RECORDED':
            protocol.fields(value, {'schema', 'operationId', 'state', 'scope'})
            protocol.require(value['scope'] == 'ORIGINAL_OPERATION_ONLY', 'PROTOCOL_MISMATCH')
            return dict(operationId=identity, state='NOT_RECORDED', resultSource='ROOT_ABSENCE', recoveryReceiptSha256=None)
        receipt = None
        if not start:
            protocol.fields(value, {'schema', 'action', 'operationId', 'state', 'scope', 'recoveryReceiptSha256', 'originalResult', 'startupAuthorized'})
            protocol.require(value['action'] == 'generation-publication-read' and value['scope'] == 'ORIGINAL_PUBLICATION_ONLY'
                and value['startupAuthorized'] is False and value['state'] in ('UNKNOWN', 'SUCCEEDED'), 'PROTOCOL_MISMATCH')
            receipt = value['recoveryReceiptSha256']
            if receipt is not None: protocol.digest(receipt)
            original = value['originalResult']
            protocol.require(isinstance(original, dict) and original.get('state') == value['state'], 'PROTOCOL_MISMATCH')
            value = original
        protocol.require(type(value.get('schema')) is int and value['schema'] == 1 and value.get('operationId') == identity, 'PROTOCOL_MISMATCH')
        if value.get('state') == 'UNKNOWN':
            protocol.fields(value, {'schema', 'operationId', 'state'})
            return dict(self.unknown(identity), resultSource='ROOT_ORIGINAL', recoveryReceiptSha256=receipt)
        common = {'schema', 'operationId', 'action', 'state', 'ringSha256', 'activeKeySha256', 'cohortSha256'}
        protocol.fields(value, common | ({'publicationId', 'scope', 'jobPath'} if start else
            {'preparationId', 'verificationId', 'publicationSha256', 'coreStopped', 'requiresExplicitStart'}))
        protocol.require(value['state'] == 'SUCCEEDED' and value['action'] == ('generation-core-start' if start else 'generation-publish')
            and value['ringSha256'] == info['ringSha256'] and value['cohortSha256'] == info['cohortSha256'], 'PROTOCOL_MISMATCH')
        protocol.digest(value['activeKeySha256'])
        result = dict(operationId=identity, state='SUCCEEDED', resultSource='ROOT_ORIGINAL', recoveryReceiptSha256=receipt,
            activeKeySha256=value['activeKeySha256'])
        if start:
            protocol.require(value['publicationId'] == info['publicationId'] and value['scope'] == 'SYSTEMD_JOB_ACCEPTED'
                and re.fullmatch(r'/org/freedesktop/systemd1/job/[0-9]+', value['jobPath']) is not None, 'PROTOCOL_MISMATCH')
            result.update(scope='SYSTEMD_JOB_ACCEPTED', jobPath=value['jobPath'])
        else:
            protocol.require(value['preparationId'] == info['preparationId'] and value['verificationId'] == info['verificationId']
                and value['coreStopped'] is True and value['requiresExplicitStart'] is True, 'PROTOCOL_MISMATCH')
            result['publicationSha256'] = protocol.digest(value['publicationSha256'])
        return result

    def renewal_attempts(self, token, info):
        result = []
        directory = self.journal.directory/'admissions'
        if not os.path.lexists(directory): return result
        self.journal.check_directory(directory)
        paths = list(directory.iterdir()); protocol.require(self.journal.active_count('ADMISSION',paths) <= 256, 'CAPACITY')
        for path in sorted(paths):
            if not path.name.endswith('-handoff-renewal'): continue
            identity = protocol.operation_id(path.name[:36])
            attempt, namespace, closed = self.sender.load('handoff-renewal', identity)
            if attempt['request']['handoffId'] != info['handoffId']: continue
            view = self.sender.view('handoff-renewal', identity)
            row = dict(operationId=identity, state='UNKNOWN', resultSource='UNCONFIRMED', closeAllowed=view['closeAllowed'], closed=view['closed'],
                expectedPublicationSha256=attempt['request']['expectedPublicationSha256'])
            original = self.call(token, 'start-lease-read', operationId=identity)
            protocol.require(original.get('operationId') == identity, 'PROTOCOL_MISMATCH')
            if original.get('state') == 'SUCCEEDED':
                try: validate_start_lease(original, identity)
                except Refused: fail('PROTOCOL_MISMATCH')
                protocol.require(namespace is not None and not closed and original['namespaceSha256'] == namespace['namespaceSha256']
                    and all(original[k] == info[k] for k in ('handoffId','publicationId','startOperationId'))
                    and original['publicationSha256'] == attempt['request']['expectedPublicationSha256'], 'PROTOCOL_MISMATCH')
                row.update(state='SUCCEEDED', resultSource='ROOT_ORIGINAL', closeAllowed=False,
                    issuedAt=original['issuedAt'], expiresAt=original['expiresAt'])
            elif original.get('state') == 'NOT_RECORDED':
                protocol.fields(original, {'schema','operationId','state','scope'})
                protocol.require(original['scope'] == 'ORIGINAL_OPERATION_ONLY', 'PROTOCOL_MISMATCH')
                if view['phase'] == 'NOT_ADMITTED' and view['closed']:
                    row.update(state='NOT_ADMITTED', resultSource='ROOT_ADMISSION_CLOSED', closeAllowed=False)
            else:
                protocol.fields(original, {'schema','operationId','state'})
                protocol.require(original['state'] == 'UNKNOWN', 'PROTOCOL_MISMATCH')
                row['closeAllowed'] = False
            result.append(row)
        return result

    def start_authorization(self, token, info, publication, start):
        if publication['state'] != 'SUCCEEDED' or start['state'] != 'NOT_RECORDED': return None
        value = self.call(token, 'start-lease-status')
        protocol.fields(value, {'schema','state','scope','handoffId','publicationId','startOperationId',
            'publicationSha256','renewalOperationId','windowOpen','renewalAllowed'})
        protocol.require(value['state'] == 'START_LEASE_STATUS' and value['scope'] == 'ORIGINAL_FIRST_START_ONLY'
            and all(value[k] == info[k] for k in ('handoffId','publicationId','startOperationId'))
            and type(value['windowOpen']) is bool and type(value['renewalAllowed']) is bool
            and (value['publicationSha256'] is None or value['publicationSha256'] == publication['publicationSha256'])
            and (value['renewalOperationId'] is None or protocol.operation_id(value['renewalOperationId']))
            and (not value['windowOpen'] or value['renewalOperationId'] is not None and value['publicationSha256'] is not None)
            and (not value['renewalAllowed'] or not value['windowOpen'] and not info['mutationWindowOpen'] and value['publicationSha256'] is not None), 'PROTOCOL_MISMATCH')
        return value

    def snapshot(self, token):
        info = self.info(token); flags, completed, other_pending = self.local(info)
        retired = self.retirement(self.binding(info)) is not None
        publication, start = self.original(token, info), self.original(token, info, start=True)
        absent = publication['state'] == start['state'] == 'NOT_RECORDED'
        if publication['state'] == start['state'] == 'SUCCEEDED':
            protocol.require(publication['activeKeySha256'] == start['activeKeySha256'], 'PROTOCOL_MISMATCH')
        if (flags['publish'] or flags['continue']) and publication['state'] == 'NOT_RECORDED':
            publication = self.unknown(info['publicationId'])
        if flags['start'] and start['state'] == 'NOT_RECORDED': start = self.unknown(info['startOperationId'])
        renewals = self.renewal_attempts(token, info)
        lease = self.start_authorization(token, info, publication, start)
        unsettled_renewal = any(row['state'] == 'UNKNOWN' for row in renewals)
        original_recovery_pending = self.journal.pending() is not None
        available = not completed and not retired and info['state'] == 'GRANT_RECORDED' and not other_pending and not original_recovery_pending and not unsettled_renewal
        allowed = dict(publish=available and info['mutationWindowOpen'] and not flags['publish'] and publication['state'] == 'NOT_RECORDED',
            start=available and (info['mutationWindowOpen'] or lease is not None and lease['windowOpen']) and not flags['start'] and publication['state'] == 'SUCCEEDED' and start['state'] == 'NOT_RECORDED',
            **{'continue': available and not flags['continue'] and not flags['start'] and publication['state'] == 'UNKNOWN' and publication['recoveryReceiptSha256'] is not None})
        for command,kind,identity in (('publish','publish',info['publicationId']),('continue','continue',info['publicationId']),('start','handoff-start',info['startOperationId'])):
            if self.sender.has_attempt(kind,identity):allowed[command]=False
        revoke_allowed = not completed and not retired and not original_recovery_pending
        try:
            protocol.require(absent)
            self.retirement_attempts(self.binding(info))
        except (protocol.Failure, OSError, ValueError, KeyError, TypeError): revoke_allowed = False
        return dict(schema=1, state='HANDOFF_STATUS', handoff=info, publication=publication, start=start,
            senderIntents=flags, completed=completed, allowed=allowed, originalRecoveryPending=original_recovery_pending,
            retired=retired, revocationAllowed=revoke_allowed, startAuthorization=lease, startRenewals=renewals,
            renewalAllowed=available and lease is not None and lease['renewalAllowed'] and not flags['start']
                and not self.sender.has_attempt('handoff-start', info['startOperationId']))

    def renew_start(self, value):
        command = value['command']; token = self.token(value['token']); identity = protocol.operation_id(value['operationId'])
        extra = {'expectedPublicationSha256'} if command == 'start-renew' else set()
        protocol.fields(value, {'token','command','operationId'} | extra)
        with self.journal.lock():
            current = self.snapshot(token); info = current['handoff']; binding = self.binding(info)
            protocol.require(identity not in {info[key] for key in self.IDS}, 'CONFLICT')
            if command == 'renewal-close':
                row = next((row for row in current['startRenewals'] if row['operationId'] == identity), None)
                protocol.require(row is not None and (row['closeAllowed'] or row['closed']) and row['state'] != 'SUCCEEDED', 'UNRESOLVED_OPERATION')
                self.sender.close('handoff-renewal', identity)
                return self.snapshot(token)
            protocol.digest(value['expectedPublicationSha256'])
            if self.sender.has_attempt('handoff-renewal', identity):
                saved = self.sender.load('handoff-renewal', identity)[0]['request']
                protocol.require(saved['handoffId'] == info['handoffId'] and saved['expectedPublicationSha256'] == value['expectedPublicationSha256'], 'CONFLICT')
                return current
            protocol.require(current['renewalAllowed'] and current['publication']['publicationSha256'] == value['expectedPublicationSha256'], 'UNRESOLVED_OPERATION')
            request = dict(schema=1, action='generation-handoff-command', token=token, command='start-renew',
                operationId=identity, expectedPublicationSha256=value['expectedPublicationSha256'])
            def forward():
                slot = self.directory/info['handoffId']
                if not os.path.lexists(slot):
                    protocol.require(self.journal.active_count('HANDOFF',self.slots()) < MAX_OPERATIONS, 'CAPACITY')
                    slot.mkdir(mode=0o700); self.journal.sync(self.directory); self.journal.write_new(slot/'binding.json', binding)
                try: self.call(token, 'start-renew', operationId=identity, expectedPublicationSha256=value['expectedPublicationSha256'])
                except (protocol.Failure, OSError, KeyError, ValueError, TypeError): pass
                try: return self.snapshot(token)
                except (protocol.Failure, OSError, KeyError, ValueError, TypeError):
                    return dict(schema=1, state='UNKNOWN', handoffId=info['handoffId'], scope='ORIGINAL_HANDOFF_ONLY')
            return self.sender.submit('handoff-renewal', identity, request, forward)

    def admission(self, token, step, *, close=False):
        protocol.require(step in ('publish','continue','start'))
        info=self.info(token);flags,_,_=self.local(info)
        kind='handoff-start' if step=='start' else step;identity=info['startOperationId' if step=='start' else 'publicationId']
        current=self.sender.view(kind,identity)
        saved=self.sender.load(kind,identity)
        if saved is not None:protocol.require(saved[0]['request']['handoffId']==info['handoffId'],'CONFLICT')
        owning=self.sender.has_key_intent(identity)
        if owning or step=='continue':current.update(closeAllowed=False,closed=False)
        if not close:return current
        protocol.require(not owning and step!='continue','UNRESOLVED_OPERATION')
        original=self.original(token,info,start=step=='start')
        protocol.require(original['state']=='NOT_RECORDED' and original['resultSource']=='ROOT_ABSENCE','UNRESOLVED_OPERATION')
        return self.sender.close(kind,identity)

    def execute(self, value):
        command = value.get('command')
        if command in ('archive-preview','archive-query','archive-confirm','archive-continue'):return self.archive(value)
        if command in ('start-renew','renewal-close'): return self.renew_start(value)
        if command == 'revoke':
            protocol.fields(value, {'token', 'command'}); token = self.token(value['token'])
            with self.journal.lock(): return self.revoke(token)
        if command in ('admission-read','admission-close'):
            protocol.fields(value,{'token','command','step'});token=self.token(value['token'])
            with self.journal.lock():return self.admission(token,value['step'],close=command=='admission-close')
        protocol.require(command in ('query', 'publish', 'continue', 'start', 'complete'), 'INVALID_ARGUMENT')
        extra = {'expectedRecoveryReceiptSha256'} if command == 'continue' else set()
        protocol.fields(value, {'token', 'command'} | extra); token = self.token(value['token'])
        if extra: protocol.digest(value['expectedRecoveryReceiptSha256'])
        with self.journal.lock():
            current = self.snapshot(token)
            if command == 'query': return current
            binding = self.binding(current['handoff']); slot = self.directory / binding['handoffId']
            if command == 'complete':
                protocol.require(current['publication']['state'] == current['start']['state'] == 'SUCCEEDED' and slot.exists(), 'UNRESOLVED_OPERATION')
                saved = dict(binding, state='ORIGINAL_REQUESTS_CONFIRMED', publicationSha256=current['publication']['publicationSha256'], jobPath=current['start']['jobPath'])
                if not os.path.lexists(slot / 'completed.json'): self.journal.write_new(slot / 'completed.json', saved)
                else: protocol.require(self.load(slot / 'completed.json') == saved, 'CONFLICT')
                return self.snapshot(token)
            if current['senderIntents'][command]: return current
            protocol.require(current['allowed'][command], 'UNRESOLVED_OPERATION')
            if extra:
                protocol.require(current['publication']['recoveryReceiptSha256'] == value['expectedRecoveryReceiptSha256'], 'CONFLICT')
            request = dict(schema=1, action='generation-handoff-command', token=token, command=command, **{key:value[key] for key in extra})
            identity = binding['startOperationId' if command == 'start' else 'publicationId']
            def forward():
                if not os.path.lexists(slot):
                    protocol.require(self.journal.active_count('HANDOFF',self.slots()) < MAX_OPERATIONS, 'CAPACITY')
                    slot.mkdir(mode=0o700); self.journal.sync(self.directory); self.journal.write_new(slot/'binding.json', binding)
                intent = dict(binding, command=command, **{key:value[key] for key in extra}); self.journal.write_new(slot/(command+'.json'), intent)
                try: self.call(token, command, **{key:value[key] for key in extra})
                except (protocol.Failure, OSError, KeyError, ValueError, TypeError): pass
                try: return self.snapshot(token)
                except (protocol.Failure, OSError, KeyError, ValueError, TypeError):
                    return dict(schema=1, state='UNKNOWN', handoffId=binding['handoffId'], scope='ORIGINAL_HANDOFF_ONLY')
            return self.sender.submit('handoff-start' if command == 'start' else command, identity, request, forward)

    def archive(self,value):
        kind=value.get('kind');protocol.require(kind in ('HANDOFF','ADMISSION'))
        protocol.fields(value,{'token','command','kind','operationId'}|({'senderKind'} if kind=='ADMISSION' else set()))
        token=self.token(value['token']);identity=protocol.operation_id(value['operationId']);step=value.get('senderKind')
        protocol.require(step in ('publish','continue','handoff-start','handoff-renewal') if kind=='ADMISSION' else step is None)
        try:
            with self.journal.lock():
                info=self.info(token);history=self.journal.history();snapshot=history.format.snapshot(kind,identity,step)
                protocol.require(identity==info['handoffId'] and snapshot['metadata']==self.binding(info) if kind=='HANDOFF'
                    else snapshot['attempt']['request']['handoffId']==info['handoffId'],'CONFLICT')
                return history.archive(kind,identity,step,preview=value['command'] in ('archive-preview','archive-query'),
                    continue_metadata=value['command']=='archive-continue')
        except Refused:fail('UNRESOLVED_OPERATION')


class RecoveryServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True  # Permit restart across TCP TIME_WAIT, without SO_REUSEPORT.
    request_queue_size = 8

    def __init__(self, address, controller, tls, assets=ASSETS):
        self.controller = controller
        self.handoffs = HandoffController(controller.client, controller.journal, sender=controller.sender)
        self.tls = tls
        self.assets = Path(assets)
        self.token = secrets.token_urlsafe(32)
        self.slots = threading.BoundedSemaphore(4)
        self.hostnames = {'localhost', socket.gethostname().lower()}
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            request.settimeout(5)
            wrapped = self.tls.wrap_socket(request, server_side=True)
            wrapped.settimeout(5)
            super().process_request_thread(wrapped, address)
        except (OSError, ssl.SSLError):
            self.shutdown_request(request)
        finally:
            self.slots.release()

    def handle_error(self, request, address):
        pass  # Never log request bodies, passwords, headers, paths or exceptions.


class Handler(BaseHTTPRequestHandler):
    server_version = 'KuraRecovery'
    sys_version = ''
    protocol_version = 'HTTP/1.0'

    def log_message(self, *_):
        pass

    def send_error(self, *_):
        self.error('INVALID_ARGUMENT')

    def authority(self):
        values = self.headers.get_all('Host', [])
        protocol.require(len(values) == 1 and re.fullmatch(r'[A-Za-z0-9.\[\]:_-]{1,255}', values[0]), 'FORBIDDEN')
        parsed = urlsplit('https://' + values[0])
        protocol.require(parsed.port == self.server.server_port and parsed.hostname is not None, 'FORBIDDEN')
        host = parsed.hostname.lower()
        if host not in self.server.hostnames:
            protocol.require(ipaddress.ip_address(host) == ipaddress.ip_address(self.connection.getsockname()[0]), 'FORBIDDEN')
        return 'https://' + values[0]

    def send(self, status, data, kind='application/json; charset=utf-8', cookie=False):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('Connection', 'close')
        if cookie:
            self.send_header('Set-Cookie', COOKIE + '=' + self.server.token + '; Secure; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers()
        self.wfile.write(data)

    def error(self, reason):
        self.send(400, protocol.encode(dict(schema=1, error=reason)))

    def do_GET(self):
        try:
            self.authority()
            mapping = {'/': ('index.html', 'text/html; charset=utf-8'),
                       '/handoff': ('index.html', 'text/html; charset=utf-8'),
                       '/recovery.js': ('recovery.js', 'text/javascript; charset=utf-8'),
                       '/recovery.css': ('recovery.css', 'text/css; charset=utf-8')}
            protocol.require(self.path in mapping, 'INVALID_ARGUMENT')
            name, kind = mapping[self.path]
            data = (self.server.assets / name).read_bytes()
            protocol.require(len(data) <= 65536, 'UNAVAILABLE')
            if name == 'index.html':
                protocol.require(data.count(b'KURA_RECOVERY_CSRF') == 1, 'UNAVAILABLE')
                data = data.replace(b'KURA_RECOVERY_CSRF', self.server.token.encode('ascii'))
                if self.path == '/handoff':
                    for before, after in ((b'data-view="recovery"', b'data-view="handoff"'),
                            (b'id="cold-flow"', b'id="cold-flow" hidden'), (b'id="handoff-flow" hidden', b'id="handoff-flow"')):
                        protocol.require(data.count(before) == 1, 'UNAVAILABLE'); data = data.replace(before, after)
            self.send(200, data, kind, cookie=name == 'index.html')
        except (protocol.Failure, ValueError, OSError):
            self.error('UNAVAILABLE')

    def do_POST(self):
        identity = None
        admitted = False
        writer = "restore"
        try:
            origin = self.authority()
            protocol.require(self.headers.get_all('Origin', []) == [origin], 'FORBIDDEN')
            protocol.require(self.headers.get('Sec-Fetch-Site', 'same-origin') == 'same-origin', 'FORBIDDEN')
            csrf = self.headers.get_all('X-Kura-Recovery-CSRF', [])
            protocol.require(len(csrf) == 1 and hmac.compare_digest(csrf[0], self.server.token), 'FORBIDDEN')
            cookies = self.headers.get_all('Cookie', [])
            protocol.require(len(cookies) == 1 and len(cookies[0]) <= 4096, 'FORBIDDEN')
            matching = [item.strip().split('=', 1)[1] for item in cookies[0].split(';')
                        if item.strip().startswith(COOKIE + '=')]
            protocol.require(len(matching) == 1 and hmac.compare_digest(matching[0], self.server.token), 'FORBIDDEN')
            protocol.require(self.headers.get_all('Content-Type', []) == ['application/json'], 'INVALID_ARGUMENT')
            protocol.require(self.headers.get('Transfer-Encoding') is None, 'INVALID_ARGUMENT')
            lengths = self.headers.get_all('Content-Length', [])
            protocol.require(len(lengths) == 1 and re.fullmatch(r'[0-9]{1,6}', lengths[0]), 'INVALID_ARGUMENT')
            length = int(lengths[0]);protocol.require(0 < length <= protocol.MAX_FRAME, 'INVALID_ARGUMENT')
            body = self.rfile.read(length);protocol.require(len(body) == length, 'INVALID_ARGUMENT')
            value = protocol.decode(body)
            if self.path == '/api/handoff':
                result = self.server.handoffs.execute(value)
            elif self.path == '/api/status':
                protocol.fields(value, set());result = self.server.controller.status()
            elif self.path == '/api/inspect':
                result = self.server.controller.inspect(value)
            elif self.path == '/api/admission':
                result = self.server.controller.admission(value)
            elif self.path == '/api/archive':
                result = self.server.controller.archive(value)
            elif self.path == '/api/original':
                protocol.fields(value, {'operationId'})
                result = self.server.controller.original(value['operationId'])
            elif self.path == '/api/start-original':
                protocol.fields(value, {'operationId'})
                result = self.server.controller.start_original(value['operationId'])
            elif self.path == '/api/complete':
                result = self.server.controller.complete(value)
            elif self.path == '/api/start-after-maintenance':
                writer = 'start'
                identity = protocol.operation_id(value.get('operationId'))
                result = self.server.controller.start(value,maintenance=True)
            elif self.path == '/api/start':
                writer = 'start'
                identity = protocol.operation_id(value.get('operationId'))
                result = self.server.controller.start(value)
            elif self.path == '/api/restore':
                identity = protocol.operation_id(value.get('operationId'))
                result = self.server.controller.restore(value)
            else:
                fail('INVALID_ARGUMENT')
            self.send(200, protocol.encode(result))
        except (protocol.Failure, OSError, ValueError, KeyError, TypeError) as failure:
            # A request may have been durably admitted before any local exception.
            # Admission absence is checked under the same journal lock, never used
            # to conclude that another process's in-flight request was rejected.
            if identity is not None:
                try:
                    with self.server.controller.journal.lock():
                        read = self.server.controller.journal.start_record if writer == "start" else self.server.controller.journal.record
                        admitted = read(identity) is not None or self.server.controller.sender.has_attempt(writer,identity)
                    if admitted:
                        self.send(200, protocol.encode((self.server.controller.start_original if writer == "start" else self.server.controller.original)(identity)))
                        return
                except (protocol.Failure, OSError, ValueError):
                    self.send(200, protocol.encode(dict(schema=1, operationId=identity, state='UNKNOWN', resultSource='UNCONFIRMED')))
                    return
                reason = failure.reason if isinstance(failure, protocol.Failure) else 'UNAVAILABLE'
                self.send(200, protocol.encode(dict(schema=1, operationId=identity, state='REJECTED', resultSource='SERVER_PREFLIGHT', error=reason)))
            else:
                self.error(failure.reason if isinstance(failure, protocol.Failure) else 'UNAVAILABLE')


def serve():
    protocol.require(os.geteuid() != 0 and sys.platform == 'linux', 'FORBIDDEN')
    account = pwd.getpwnam('kura-key-recovery')
    daemon = pwd.getpwnam('kurad')
    protocol.require(os.geteuid() == account.pw_uid and account.pw_uid != daemon.pw_uid
                     and account.pw_shell in ('/usr/sbin/nologin', '/sbin/nologin'), 'FORBIDDEN')
    credentials = Path('/run/credentials/kura-key-recovery.service')
    protocol.require(os.environ.get('CREDENTIALS_DIRECTORY') == str(credentials), 'UNAVAILABLE')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(credentials / 'tls.crt', credentials / 'tls.key')
    controller = Controller()
    # TLS and browser session establishment remain available while Core is healthy
    # or Root is temporarily unavailable. Every action retains its own Root gate;
    # this does not grant key restoration or a generation handoff from page access.
    with RecoveryServer(('0.0.0.0', 9443), controller, context) as server:
        server.serve_forever(poll_interval=0.5)


if __name__ == '__main__':
    try:
        protocol.require(sys.argv == [sys.argv[0], '--serve'])
        serve()
    except (protocol.Failure, OSError, KeyError, ValueError):
        sys.stderr.write('Kura cold recovery unavailable; preserve original keys, backup and operation ID\n')
        sys.exit(2)
