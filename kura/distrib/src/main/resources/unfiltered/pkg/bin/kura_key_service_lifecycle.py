#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Root-only key-service package admission. Embedded verbatim in Core preinst."""
import base64
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
import sys
import types
import uuid

if __name__=='__main__':sys.modules['kura_key_service_lifecycle']=sys.modules[__name__]

FORMAT = "yofc-kura-gateway-master-key-v1"
GENERATION_FORMAT = "yofc-kura-gateway-key-generations-v1"
STATE = "/var/lib/kura-key-service"
MAIN_VENDOR_PATHS = ('/lib/systemd/system/kura.service', '/usr/lib/systemd/system/kura.service')
MAIN_LINKS = {'linked': '/etc/systemd/system/kura.service',
              'linked-runtime': '/run/systemd/system/kura.service'}
MAIN_LINK_BACKUP = '.kura-main-migration-link'
LEGACY_UNITS = ("kura-key-service.socket", "kura-key-service.service")
UNITS = (*LEGACY_UNITS, 'kura-key-recovery.service')
VALIDATION_UNITS = ('kura-snapshot-validation.socket', 'kura-snapshot-validation.service')
NATIVE_VALIDATION_UNITS = (*UNITS, *VALIDATION_UNITS)
LEGACY_ASSETS = frozenset(("bin/kura_key_store.py", "bin/kura_key_service.py", "bin/kura_key_service_lifecycle.py",
                   "libexec/key-backup/kura-key-crypto.jar", "libexec/key-backup/lib/bcprov-jdk18on-1.86.jar"))
COLD_V1_ASSETS = LEGACY_ASSETS | frozenset(('bin/kura_key_recovery.py', 'bin/kura_key_recovery_setup.py',
    'share/key-recovery/index.html', 'share/key-recovery/recovery.js', 'share/key-recovery/recovery.css'))
PRE_JOURNAL_ASSETS = COLD_V1_ASSETS | frozenset(('bin/kura_key_recovery_start.py',))
JOURNAL_V1_ASSETS = PRE_JOURNAL_ASSETS | frozenset(('bin/kura_key_journal.py',))
ASSETS = JOURNAL_V1_ASSETS | frozenset(('share/key-recovery/archive.js',))
NATIVE_VALIDATION_ASSETS = ASSETS | {'bin/kura_native_snapshot_validation.py'}
JOURNAL_ASSETS = (JOURNAL_V1_ASSETS, ASSETS, NATIVE_VALIDATION_ASSETS)


class Refused(RuntimeError):
    pass

class ActiveWriter(Refused):
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


GWT_BINDING_PURPOSE = 'yofc.kura.gwt-sender-namespace.v1'
GWT_DATA_FIELDS = frozenset(('dataDirectory', 'dataDevice', 'dataInode', 'dataUid'))
GWT_NAMESPACE_FIELDS = frozenset(('namespaceSha256', 'rootDevice', 'rootInode'))
GWT_BINDING_FIELDS = GWT_DATA_FIELDS | GWT_NAMESPACE_FIELDS | {'schema', 'purpose'}
SENDER_ADMISSION_PURPOSE = 'yofc.kura.sender-admission.v1'
SENDER_ADMISSION_CONTEXT = b'yofc-kura-sender-admission-v1\0'
PRIVATE_FENCE_PURPOSE = 'yofc.kura.sender-private-no-dispatch.v1'
PRIVATE_FENCE_CONTEXT = b'yofc-kura-sender-private-no-dispatch-v1\0'
ARCHIVE_INTENT_CONTEXT = b'yofc-kura-journal-archive-intent-v1\0'
ARCHIVE_RECEIPT_CONTEXT = b'yofc-kura-journal-archive-receipt-v1\0'
ARCHIVE_TABLES = frozenset(('operations', 'startups', 'handoffs', 'sender-admissions', 'package-history'))


def archive_references(value):
    require(isinstance(value, list) and 1 <= len(value) <= 128)
    result = []
    for item in value:
        require(isinstance(item, dict) and set(item) == {'directory', 'operationId'}
            and item['directory'] in ARCHIVE_TABLES and canonical_id(item['operationId']))
        result.append(dict(item))
    result.sort(key=lambda item: (item['directory'], item['operationId']))
    require(len({(item['directory'], item['operationId']) for item in result}) == len(result))
    return result


def archive_handoff_closed(policy, authority, secret):
    """Historical Root proof only. Never require the original JVM to remain alive."""
    request = authority['request']; identity = request['handoffId']
    revoked = read_handoff_revocation(policy, identity, secret)
    if revoked is not None:
        parent = policy.state/'sender-admissions'
        if os.path.lexists(parent):
            policy.directory(parent, private=True)
            for path in parent.iterdir():
                require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                value = validate_sender_admission(decode(policy.read(path, 8192)), path.name[:-5], secret)
                if value['target']['operationId'] in (request['publicationId'], request['startOperationId']):
                    require(value['state'] == 'NOT_ADMITTED')
                    native=handoff_operation_request(authority,start=value['target']['operationId']==request['startOperationId'])
                    require(value['target']==dict(directory='operations',operationId=native['operationId'],action=native['action'],
                        requestTag=hmac.new(secret,encoded(native),hashlib.sha256).hexdigest(),continuation=False))
                    check_sender_original(policy, value, secret)
        return
    originals = []
    for start in (False, True):
        native = handoff_operation_request(authority, start=start)
        raw = policy.read(policy.state/'operations'/(native['operationId']+'.json'), 65536)
        value = validate_record(decode(raw), native['operationId'])
        require(value['state'] == 'SUCCEEDED' and value['action'] == native['action']
            and hmac.compare_digest(value['requestTag'], hmac.new(secret, encoded(native), hashlib.sha256).hexdigest()))
        originals.append(value)
    path = policy.state/'generations'/request['preparationId']/'publication.json'
    raw = policy.read(path, 8192); publication = validate_publication(decode(raw))
    require(raw == encoded(publication) and stat.S_IMODE(path.lstat().st_mode) == 0o400
        and publication['operationId'] == request['publicationId']
        and all(publication[k] == request[k] for k in ('preparationId', 'verificationId'))
        and publication['source'] == authority['source'] and publication['generation'] == authority['generation']
        and publication['cohortSha256'] == request['expectedCohortSha256']
        and publication['historySha256'] == authority['historySha256']
        and publication['stoppedWriter'] == {k:v for k,v in authority['owner'].items() if k != 'uid'})
    published, started = (row['response'] for row in originals)
    require(published['publicationSha256'] == hashlib.sha256(raw).hexdigest()
        and all(published[k]==publication[k] for k in ('preparationId','verificationId','cohortSha256'))
        and published['ringSha256']==authority['generation']['ringSha256']
        and published['activeKeySha256']==authority['generation']['activeKeySha256']
        and started['publicationId'] == request['publicationId']
        and all(started[k] == published[k] for k in ('ringSha256', 'activeKeySha256', 'cohortSha256')))


def archive_entry(policy, reference, secret, *, inventory=None):
    """Select a positive immutable original; a missing original is never completion."""
    directory, identity = reference['directory'], reference['operationId']
    policy.directory(policy.state/directory, private=True)
    path = policy.state/directory/(identity+'.json'); raw = policy.read(path, 65536)
    value = decode(raw)
    if directory == 'operations':
        validate_record(value, identity); require(value['state'] == 'SUCCEEDED')
        response=value['response']
        if value['action'] in ('generation-publish','generation-core-start'):
            start=value['action']=='generation-core-start'
            native=dict(schema=1,action=value['action'],operationId=identity,expectedRingSha256=response['ringSha256'],
                expectedCohortSha256=response['cohortSha256'])
            if start:native['publicationId']=response['publicationId']
            else:native.update(preparationId=response['preparationId'],verificationId=response['verificationId'])
            require(hmac.compare_digest(value['requestTag'],hmac.new(secret,encoded(native),hashlib.sha256).hexdigest()))
            if not start:
                publication_raw=policy.read(policy.state/'generations'/response['preparationId']/'publication.json',8192)
                publication=validate_publication(decode(publication_raw))
                require(publication_raw==encoded(publication) and hashlib.sha256(publication_raw).hexdigest()==response['publicationSha256']
                    and publication['operationId']==identity
                    and all(response[k]==publication[k] for k in ('preparationId','verificationId','cohortSha256'))
                    and response['ringSha256']==publication['generation']['ringSha256']
                    and response['activeKeySha256']==publication['generation']['activeKeySha256'])
            else:
                archive_entry(policy,dict(directory='operations',operationId=response['publicationId']),secret,inventory=inventory)
                published=validate_record(decode(policy.read(policy.state/'operations'/(response['publicationId']+'.json'))),response['publicationId'])
                require(all(response[k]==published['response'][k] for k in ('ringSha256','activeKeySha256','cohortSha256')))
        if value['action'] in ('generation-prepare','generation-backup-verify'):
            preparation=identity if value['action']=='generation-prepare' else response['preparationId']
            prepared=value if preparation==identity else validate_record(decode(policy.read(
                policy.state/'operations'/(preparation+'.json'))),preparation)
            require(prepared['action']=='generation-prepare' and prepared['state']=='SUCCEEDED')
            history_raw=policy.read(policy.state/'generations'/preparation/'history.json',8192);history=decode(history_raw)
            require(hashlib.sha256(history_raw).hexdigest()==prepared['response']['historySha256']
                and history['preparationId']==preparation and history['generation']==prepared['response']['generation']
                and history['source']==prepared['response']['source'])
            require(hashlib.sha256(encoded(prepared['response']['backup'])).hexdigest()==history['backupSha256'])
            require(hashlib.sha256(policy.read(policy.state/'generations'/preparation/'keyring',512)).hexdigest()==history['generation']['ringSha256'])
            if value['action']=='generation-backup-verify':
                require(response['ringSha256']==history['generation']['ringSha256'] and response['backupSha256']==history['backupSha256'])
        if value['action'] in ('generation-cancel', 'generation-start-lease'):
            native = dict(schema=1, action=value['action'], operationId=identity, **value['intent'])
            require(hmac.compare_digest(value['requestTag'], hmac.new(secret, encoded(native), hashlib.sha256).hexdigest()))
        if value['action'] == 'generation-start-lease':
            lease=validate_start_lease(value['response'],identity)
            authority_path=policy.state/'handoffs'/(lease['handoffId']+'.json')
            authority_raw=policy.read(authority_path,8192)
            authority=validate_handoff_authority(decode(authority_raw),lease['handoffId'],secret)
            require(authority_raw==encoded(authority) and stat.S_IMODE(authority_path.lstat().st_mode)==0o400
                and lease['grantSha256']==hashlib.sha256(authority_raw).hexdigest()
                and lease['namespaceSha256']==gwt_namespace(policy.state,secret)['namespaceSha256']
                and lease['bootId']==authority['owner']['bootId']
                and all(lease[k]==authority['request'][k] for k in ('handoffId','publicationId','startOperationId')))
            body={k:v for k,v in lease.items() if k!='receiptTag'}
            require(hmac.compare_digest(lease['receiptTag'],hmac.new(secret,START_LEASE_CONTEXT+encoded(body),hashlib.sha256).hexdigest()))
        if value['action']=='generation-cancel':
            cancellation=policy.read(policy.state/'generations'/value['intent']['preparationId']/'cancellation.json',8192)
            require(hashlib.sha256(cancellation).hexdigest()==response['cancellationSha256'])
            event=decode(cancellation);body={k:v for k,v in event.items() if k!='receiptTag'}
            require(event['operationId']==identity and hmac.compare_digest(event['receiptTag'],hmac.new(secret,
                b'yofc-kura-cancel-receipt-v1\0'+encoded(body),hashlib.sha256).hexdigest()))
    elif directory == 'startups':
        validate_start(value, identity); require(value['state'] == 'SUCCEEDED')
        restored=validate_record(decode(policy.read(policy.state/'operations'/(value['restoreOperationId']+'.json'))),value['restoreOperationId'])
        require(restored['action']=='restore' and restored['state']=='SUCCEEDED'
            and restored['response']['keyChanged'] is True and restored['response']['existingReceiptPreserved'] is True
            and restored['response']['keySha256']==value['keySha256'])
        modern=value['schema']==2
        native=dict(schema=1,action='core-start-after-maintenance' if modern else 'core-start',operationId=identity,
            restoreOperationId=value['restoreOperationId'],expectedKeySha256=value['keySha256'])
        if modern:native.update({k:value[k] for k in ('predecessorStartOperationId','maintenanceId','manifestSha256')})
        require(hmac.compare_digest(value['requestTag'],hmac.new(secret,encoded(native),hashlib.sha256).hexdigest()))
        if modern:
            previous=validate_start(decode(policy.read(policy.state/'startups'/(value['predecessorStartOperationId']+'.json'))),value['predecessorStartOperationId'])
            maintenance=validate_maintenance(decode(policy.read(policy.state/'package-history'/(value['maintenanceId']+'.json'))),value['maintenanceId'])
            require(previous['state']=='SUCCEEDED' and previous['restoreOperationId']==value['restoreOperationId']
                and previous['keySha256']==value['keySha256']==maintenance['keySha256']
                and value['manifestSha256']==maintenance['manifestSha256'])
            if inventory is not None:require(maintenance_includes_startup(policy,maintenance,value['predecessorStartOperationId'],inventory=inventory))
    elif directory == 'sender-admissions':
        validate_sender_admission(value, identity, secret)
        require(value['namespaceSha256'] == gwt_namespace(policy.state, secret)['namespaceSha256']
            and value['state'] in ('TERMINAL', 'INTAKE', 'NOT_ADMITTED'))
        check_sender_original(policy, value, secret)
        if value['state']!='NOT_ADMITTED' and value['target']['directory']!='handoffs':
            archive_entry(policy,{k:value['target'][k] for k in ('directory','operationId')},secret,inventory=inventory)
    elif directory == 'package-history':
        validate_maintenance(value,identity)
        if value['schema']==2 and inventory is not None:maintenance_includes_startup(policy,value,'',inventory=inventory)
    else:
        validate_handoff_authority(value, identity, secret)
        require(raw == encoded(value) and stat.S_IMODE(path.lstat().st_mode) == 0o400)
        archive_handoff_closed(policy, value, secret)
    return dict(reference, sha256=hashlib.sha256(raw).hexdigest())


def archive_inventory(policy):
    """Authenticate logical archives before exempting any original from an active budget.

    Originals stay at their canonical paths. Old readers and late-frame fences
    continue to see them; no read moves data or finishes an incomplete archive.
    """
    parent = policy.state/'archives'; result = dict(archived=set(), requests={}, head=None, depths={}, owners={}); claimed=set()
    if not os.path.lexists(parent): return result
    policy.directory(parent, private=True)
    secret = policy.read(policy.state/'journal.key', 32); require(len(secret) == 32)
    namespace = gwt_namespace(policy.state, secret)['namespaceSha256']
    groups={}
    for path in parent.iterdir():
        parts=path.name.split('.');require(len(parts)==3 and canonical_id(parts[0])
            and parts[1] in ('intent','receipt') and parts[2]=='json')
        groups.setdefault(parts[0],set()).add(parts[1]+'.json')
    for identity,names in groups.items():
        require(names in ({'intent.json'}, {'intent.json', 'receipt.json'}))
        path = parent/(identity+'.intent.json'); raw = policy.read(path, 65536); intent = decode(raw)
        require(set(intent) == {'schema','purpose','archiveId','namespaceSha256','source','actorUid',
            'createdAt','entries','entriesSha256','requestTag','receiptTag','previousArchiveId','previousArchiveSha256'}
            and type(intent['schema']) is int and intent['schema'] == 1
            and intent['purpose'] == 'yofc.kura.journal-archive-intent.v1' and intent['archiveId'] == identity
            and intent['namespaceSha256'] == namespace and intent['source'] in ('gwt','recovery','local-admin')
            and type(intent['actorUid']) is int and 0 <= intent['actorUid'] < 0xffffffff
            and type(intent['createdAt']) is int and intent['createdAt'] >= 0
            and ((intent['previousArchiveId'] is None and intent['previousArchiveSha256'] is None) or
                canonical_id(intent['previousArchiveId']) and is_digest(intent['previousArchiveSha256']))
            and all(is_digest(intent[k]) for k in ('entriesSha256','requestTag','receiptTag'))
            and raw == encoded(intent) and stat.S_IMODE(path.lstat().st_mode) == 0o400)
        entries = intent['entries']; require(isinstance(entries,list))
        require(all(isinstance(row,dict) and set(row)=={'directory','operationId','sha256'}
            and is_digest(row['sha256']) for row in entries))
        references = archive_references([{k:row[k] for k in ('directory','operationId')} for row in entries])
        require(references == [{k:row[k] for k in ('directory','operationId')} for row in entries]
            and hashlib.sha256(encoded(entries)).hexdigest() == intent['entriesSha256'])
        body = {k:v for k,v in intent.items() if k != 'receiptTag'}
        require(hmac.compare_digest(intent['receiptTag'],hmac.new(secret,ARCHIVE_INTENT_CONTEXT+encoded(body),hashlib.sha256).hexdigest()))
        for reference, entry in zip(references,entries):
            require(archive_entry(policy,reference,secret)==entry)
            key=(entry['directory'],entry['operationId']);require(key not in claimed);claimed.add(key)
        receipt = None
        if 'receipt.json' in names:
            path=parent/(identity+'.receipt.json'); receipt_raw=policy.read(path,8192); receipt=decode(receipt_raw)
            require(set(receipt)=={'schema','purpose','archiveId','namespaceSha256','intentSha256','entriesSha256','archivedAt','receiptTag'}
                and type(receipt['schema']) is int and receipt['schema']==1
                and receipt['purpose']=='yofc.kura.journal-archive-receipt.v1' and receipt['archiveId']==identity
                and receipt['namespaceSha256']==namespace and receipt['intentSha256']==hashlib.sha256(raw).hexdigest()
                and receipt['entriesSha256']==intent['entriesSha256']
                and type(receipt['archivedAt']) is int and receipt['archivedAt']>=0
                and is_digest(receipt['receiptTag']) and receipt_raw==encoded(receipt)
                and stat.S_IMODE(path.lstat().st_mode)==0o400)
            body={k:v for k,v in receipt.items() if k!='receiptTag'}
            require(hmac.compare_digest(receipt['receiptTag'],hmac.new(secret,ARCHIVE_RECEIPT_CONTEXT+encoded(body),hashlib.sha256).hexdigest()))
            for reference, entry in zip(references,entries):
                key=(entry['directory'],entry['operationId']); require(key not in result['archived'])
                result['archived'].add(key)
                result['owners'][key]=identity
        result['requests'][identity]=(intent,receipt)
    children={};closed=set()
    for identity,(intent,receipt) in result['requests'].items():
        previous=intent['previousArchiveId'];require(previous!=identity and previous not in children);children[previous]=identity
        if previous is not None:
            parent_value=result['requests'].get(previous)
            require(parent_value is not None and parent_value[1] is not None
                and hashlib.sha256(encoded(parent_value[1])).hexdigest()==intent['previousArchiveSha256'])
        if receipt is not None:closed.add(identity)
    current=children.get(None);visited=set();depth=0
    while current is not None:
        require(current not in visited);visited.add(current)
        intent,receipt=result['requests'][current]
        if receipt is not None:
            result['depths'][current]=depth;result['head']=current;depth+=1
        else:require(current not in children)
        current=children.get(current)
    require(len(visited)==len(result['requests']))
    for intent,_ in result['requests'].values():
        for entry in intent['entries']:
            if entry['directory']=='package-history':
                value=validate_maintenance(decode(policy.read(policy.state/'package-history'/(entry['operationId']+'.json'))),entry['operationId'])
                if value['schema']==2:maintenance_includes_startup(policy,value,'',inventory=result)
    return result


def active_journal_count(policy, directory, identities, *, inventory=None):
    require(directory in ARCHIVE_TABLES)
    inventory = archive_inventory(policy) if inventory is None else inventory
    count=0
    for identity in identities:
        if (directory,identity) in inventory['archived']:continue
        if directory=='sender-admissions':
            try:value=decode(policy.read(policy.state/directory/(identity+'.json'),8192))
            except FileNotFoundError:value=None  # A projected ordinary reservation still consumes capacity.
            if value is not None and value.get('purpose')==PRIVATE_FENCE_PURPOSE:
                secret=policy.read(policy.state/'journal.key',32)
                validate_sender_admission(value,identity,secret);check_sender_original(policy,value,secret)
                require(value['namespaceSha256']==gwt_namespace(policy.state,secret)['namespaceSha256'])
                continue  # Permanent metadata fence, with no writer/reservation capacity.
        count+=1
    return count


def maintenance_includes_startup(policy, maintenance, identity, *, inventory=None):
    if maintenance['schema']==2:
        inventory=archive_inventory(policy) if inventory is None else inventory
        head=maintenance['precedingArchiveId'];require(head in inventory['depths'])
        require(hashlib.sha256(encoded(inventory['requests'][head][1])).hexdigest()==maintenance['precedingArchiveSha256'])
    if identity in maintenance['precedingStartupIds']:return True
    if maintenance['schema']==1:return False
    owner=inventory['owners'].get(('startups',identity))
    return owner is not None and inventory['depths'][owner]<=inventory['depths'][head]


def validate_sender_admission(value, identity, secret):
    fence=isinstance(value,dict) and value.get('purpose')==PRIVATE_FENCE_PURPOSE
    require(isinstance(value, dict) and set(value) == ({'schema', 'purpose', 'admissionId', 'source', 'namespaceSha256',
        'owner', 'requestTag', 'target', 'parentAdmissionId', 'state', 'receiptTag'} | ({'privateProof'} if fence else set()))
        and type(value['schema']) is int and value['schema'] == 1 and value['purpose'] in (SENDER_ADMISSION_PURPOSE,PRIVATE_FENCE_PURPOSE)
        and canonical_id(identity) and value['admissionId'] == identity
        and value['source'] in ('gwt', 'recovery', 'local-admin')
        and value['state'] in ('RESERVED', 'INTAKE', 'TERMINAL', 'NOT_ADMITTED')
        and all(is_digest(value[k]) for k in ('namespaceSha256', 'requestTag', 'receiptTag'))
        and (value['parentAdmissionId'] is None or canonical_id(value['parentAdmissionId'])))
    owner = value['owner']
    require(isinstance(owner, dict) and set(owner) == {'pid', 'uid', 'startTicks', 'bootId'}
        and type(owner['pid']) is int and 0 < owner['pid'] <= 0x7fffffff
        and type(owner['uid']) is int and 0 <= owner['uid'] < 0xffffffff
        and isinstance(owner['startTicks'], str) and re.fullmatch(r'[0-9]{1,20}', owner['startTicks']) is not None
        and canonical_id(owner['bootId']))
    target = value['target']
    require(isinstance(target, dict) and set(target) == {'directory', 'operationId', 'action', 'requestTag', 'continuation'}
        and target['directory'] in ('operations', 'startups', 'handoffs') and canonical_id(target['operationId'])
        and isinstance(target['action'], str) and 1 <= len(target['action']) <= 64 and is_digest(target['requestTag'])
        and type(target['continuation']) is bool)
    require(len(secret) == 32 and hmac.compare_digest(value['receiptTag'], hmac.new(secret,
        SENDER_ADMISSION_CONTEXT + encoded({k: v for k, v in value.items() if k != 'receiptTag'}), hashlib.sha256).hexdigest()))
    if fence:
        proof=value['privateProof']
        require(isinstance(proof,dict) and set(proof)==GWT_DATA_FIELDS|{'kind','metadataSha256','receiptSha256','blockedIds'})
        validate_gwt_data({k:proof[k] for k in GWT_DATA_FIELDS})
        blocked=proof['blockedIds']
        require(value['state']=='NOT_ADMITTED' and value['parentAdmissionId'] is None and target['continuation'] is False
            and proof['dataUid']==owner['uid'] and proof['kind'] in ('LEGACY','GENERATION','HANDOFF','restore','start')
            and all(is_digest(proof[k]) for k in ('metadataSha256','receiptSha256'))
            and isinstance(blocked,list) and len(blocked)==(3 if proof['kind']=='HANDOFF' else 1)
            and all(canonical_id(key) for key in blocked) and blocked==sorted(set(blocked))
            and target['operationId'] in blocked and identity not in blocked)
        require(target['directory']==('handoffs' if proof['kind']=='HANDOFF' else 'startups' if proof['kind']=='start' else 'operations'))
        actions={'LEGACY':('backup-create','restore'),'GENERATION':('generation-prepare','generation-backup-verify'),
            'HANDOFF':('generation-handoff-create',),'restore':('restore',),'start':('core-start','core-start-after-maintenance')}
        require(value['source'] in ('gwt','recovery') and target['action'] in actions[proof['kind']]
            and ((value['source']=='gwt')==(proof['kind'] in ('LEGACY','GENERATION','HANDOFF'))))
        body=dict(source=value['source'],namespaceSha256=value['namespaceSha256'],privateProof=proof,
            directory=target['directory'],operationId=target['operationId'],action=target['action'])
        require(value['requestTag']==target['requestTag']==hmac.new(secret,PRIVATE_FENCE_CONTEXT+encoded(body),hashlib.sha256).hexdigest())
    return value


def validate_sender_attempt(value, source):
    require(isinstance(value, dict) and set(value) == {'schema', 'purpose', 'admissionId', 'kind', 'nativeOperationId', 'request'}
        and type(value['schema']) is int and value['schema'] == 1 and value['purpose'] == 'yofc.kura.sender-attempt.v1'
        and canonical_id(value['admissionId']) and canonical_id(value['nativeOperationId']) and isinstance(value['request'], dict))
    if source == 'gwt':
        require(value['kind'] in ('LEGACY', 'GENERATION', 'HANDOFF'))
        require(validate_gwt_intent(value['kind'], value['request']) == value['nativeOperationId'])
    else:
        require(source == 'recovery' and value['kind'] in ('restore', 'start', 'publish', 'continue', 'handoff-start', 'handoff-renewal'))
        request = value['request']; action = request.get('action')
        if value['kind'] == 'restore':
            require(set(request) == {'schema', 'action', 'operationId', 'expectedKeySha256', 'backupSha256'}
                and action == 'restore' and request['operationId'] == value['nativeOperationId']
                and all(is_digest(request[k]) for k in ('expectedKeySha256', 'backupSha256')))
        elif value['kind'] == 'start':
            extra = {'predecessorStartOperationId', 'maintenanceId', 'manifestSha256'} if action == 'core-start-after-maintenance' else set()
            require(action in ('core-start', 'core-start-after-maintenance') and set(request) ==
                {'schema', 'action', 'operationId', 'restoreOperationId', 'expectedKeySha256'} | extra
                and request['operationId'] == value['nativeOperationId'] and canonical_id(request['restoreOperationId'])
                and is_digest(request['expectedKeySha256']))
            if extra: require(canonical_id(request['predecessorStartOperationId']) and canonical_id(request['maintenanceId']) and is_digest(request['manifestSha256']))
        else:
            command = 'start' if value['kind'] == 'handoff-start' else 'start-renew' if value['kind'] == 'handoff-renewal' else value['kind']
            extra = {'expectedRecoveryReceiptSha256'} if command == 'continue' else {'operationId','expectedPublicationSha256'} if command == 'start-renew' else set()
            require(set(request) == {'schema', 'action', 'command', 'handoffId'} | extra
                and action == 'generation-handoff-command' and request['command'] == command and canonical_id(request['handoffId']))
            if command == 'continue': require(is_digest(request['expectedRecoveryReceiptSha256']))
            if command == 'start-renew': require(request['operationId'] == value['nativeOperationId'] and is_digest(request['expectedPublicationSha256']))
        require(type(request.get('schema')) is int and request['schema'] == 1)
    return value


def check_private_fence_links(policy, values):
    """Package readers reject contradictory retained IDs, without private reads."""
    claimed=set()
    for value in values:
        if value.get('purpose')==PRIVATE_FENCE_PURPOSE:
            identities=set(value['privateProof']['blockedIds']+[value['admissionId']])
            require(not claimed&identities);claimed.update(identities)
    if not claimed:return
    secret=policy.read(policy.state/'journal.key',32)
    for value in values:
        validate_sender_admission(value,value['admissionId'],secret)
        if value['purpose']!=PRIVATE_FENCE_PURPOSE:
            require(value['admissionId'] not in claimed and value['target']['operationId'] not in claimed,
                'A retained reservation contradicts a permanent private fence')
    parent=policy.state/'handoffs'
    if os.path.lexists(parent):
        policy.directory(parent,private=True)
        for path in parent.iterdir():
            require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
            authority=validate_handoff_authority(decode(policy.read(path,8192)),path.name[:-5],secret)
            require(not claimed&{authority['request'][key] for key in HANDOFF_IDS},
                'A retained authority contradicts a permanent private fence')
    for identity in claimed:
        require(not any(os.path.lexists(policy.state/'archives'/(identity+suffix)) for suffix in ('.intent.json','.receipt.json')))


def validate_sender_closed(value, attempt, namespace):
    require(isinstance(value, dict) and set(value) == {'schema','purpose','admissionId','kind','nativeOperationId','namespaceSha256'}
        and type(value['schema']) is int and value['schema'] == 1 and value['purpose'] == 'yofc.kura.sender-not-admitted.v1'
        and all(value[key] == attempt[key] for key in ('admissionId','kind','nativeOperationId'))
        and value['namespaceSha256'] == namespace['namespaceSha256'])
    return value


def validate_gwt_closed(value, attempt, namespace):
    validate_sender_attempt(attempt, 'gwt')
    require(isinstance(value, dict) and set(value) == {'schema','purpose','admissionId','kind','nativeOperationId','namespaceSha256','files'}
        and type(value['schema']) is int and value['schema'] == 1 and value['purpose'] == 'yofc.kura.gwt-unconsumed-intent.v1'
        and all(value[k] == attempt[k] for k in ('admissionId','kind','nativeOperationId'))
        and value['namespaceSha256'] == namespace['namespaceSha256'])
    identity = attempt['nativeOperationId']; files = value['files']
    require(isinstance(files, dict) and 1 <= len(files) <= 5 and all(is_digest(v) for v in files.values()))
    if attempt['kind'] == 'LEGACY':
        names = {'request.json','request-complete','submitted','result.json','result-complete'}
        require({'request.json','request-complete'} <= set(files) <= names)
    else:
        require(set(files) == {'intent'})
    return value


def receiver_start_intent(attempt):
    """The complete private startup metadata implied by its original reservation."""
    validate_sender_attempt(attempt, 'recovery')
    require(attempt['kind'] == 'start')
    request = attempt['request']
    return dict(schema=2 if request['action'] == 'core-start-after-maintenance' else 1,
        **{key: value for key, value in request.items() if key not in ('schema', 'action')})


def receiver_restore_intent(attempt):
    validate_sender_attempt(attempt, 'recovery')
    require(attempt['kind'] == 'restore')
    return dict(schema=1, **{key: attempt['request'][key]
        for key in ('operationId', 'expectedKeySha256', 'backupSha256')})


def receiver_restore_pending(attempt):
    intent = receiver_restore_intent(attempt)
    return {key: intent[key] for key in ('schema', 'operationId', 'expectedKeySha256')}


def validate_receiver_pending(value, attempt):
    require(isinstance(value, dict) and type(value.get('schema')) is int
        and value == receiver_restore_pending(attempt), 'Retired recovery marker does not match its original request')
    return value


def check_sender_attempt(policy, value, namespace, source, uid):
    validate_sender_attempt(value, source)
    require(isinstance(namespace, dict) and set(namespace) == {'schema', 'namespaceSha256'}
        and type(namespace['schema']) is int and namespace['schema'] == 1 and is_digest(namespace['namespaceSha256']))
    secret = policy.read(policy.state/'journal.key', 32)
    require(namespace['namespaceSha256'] == gwt_namespace(policy.state, secret)['namespaceSha256'])
    identity = value['admissionId']
    try: raw = policy.read(policy.state/'sender-admissions'/(identity+'.json'), 8192)
    except FileNotFoundError: raise Unresolved('Sender reservation is missing; preserve its original attempt') from None
    root = validate_sender_admission(decode(raw), identity, secret)
    require(root['purpose']==SENDER_ADMISSION_PURPOSE,
        'A private no-dispatch fence is not an ordinary sender-attempt receipt')
    require(root['source'] == source and root['owner']['uid'] == uid and root['target']['operationId'] == value['nativeOperationId']
        and root['namespaceSha256'] == namespace['namespaceSha256'])
    if source == 'gwt':
        require(root['target']['action'] == value['request']['action'] and root['target']['continuation'] is False
            and root['target']['directory'] == ('handoffs' if value['kind'] == 'HANDOFF' else 'operations'),
            'GWT reservation does not match the original intent type and action')
    if source == 'recovery' and value['kind'] == 'restore':
        require(root['target']['directory'] == 'operations' and root['target']['action'] == 'restore'
            and root['target']['continuation'] is False, 'Recovery reservation has a different native target')
    if source == 'recovery' and value['kind'] == 'handoff-renewal':
        request = value['request']
        native = dict(schema=1, action='generation-start-lease', operationId=value['nativeOperationId'],
            handoffId=request['handoffId'], expectedPublicationSha256=request['expectedPublicationSha256'])
        require(root['target'] == dict(directory='operations', action='generation-start-lease', operationId=value['nativeOperationId'],
            continuation=False, requestTag=hmac.new(secret, encoded(native), hashlib.sha256).hexdigest()),
            'Start renewal reservation does not match the original metadata intent')
    if source == 'recovery' and value['kind'] == 'start':
        tag = hmac.new(secret, encoded(value['request']), hashlib.sha256).hexdigest()
        require(root['target']['directory'] == 'startups' and root['target']['action'] == value['request']['action']
            and root['target']['continuation'] is False and root['requestTag'] == tag and root['target']['requestTag'] == tag,
            'Startup reservation does not match the complete original request')
    check_sender_original(policy, root, secret)
    return root


def check_sender_original(policy, value, secret):
    """Read the exact original; an absent result never settles an admitted command."""
    target = value['target']; path = policy.state/target['directory']/(target['operationId']+'.json')
    try: raw = policy.read(path, 65536); native = decode(raw)
    except FileNotFoundError: native = None
    if value['state'] == 'NOT_ADMITTED':
        require(native is None, 'A closed sender reservation cannot conceal a native original')
        for name in ('operations', 'startups', 'handoffs'):
            parent = policy.state/name
            if os.path.lexists(parent): policy.directory(parent, private=True)
            require(not os.path.lexists(parent/(target['operationId']+'.json')),
                'A closed sender reservation cannot conceal another native action or directory')
        if value['purpose']==PRIVATE_FENCE_PURPOSE:
            path=policy.state/'sender-admissions'/(value['admissionId']+'.json')
            require(policy.read(path,8192)==encoded(value) and stat.S_IMODE(path.lstat().st_mode)==0o400)
            for identity in value['privateProof']['blockedIds']+[value['admissionId']]:
                for name in ('operations','startups','handoffs'):
                    require(not os.path.lexists(policy.state/name/(identity+'.json')),
                        'A permanent private no-dispatch fence cannot conceal a native original')
        return
    if value['state'] == 'RESERVED' or native is None:
        raise Unresolved('Unresolved sender admission; preserve original IDs and receipts')
    if target['directory'] == 'operations':
        validate_record(native, target['operationId']); require(native['action'] == target['action'])
    elif target['directory'] == 'startups': validate_start(native, target['operationId'])
    else:
        require(stat.S_IMODE(path.lstat().st_mode) == 0o400 and raw == encoded(native))
        validate_handoff_authority(native, target['operationId'], secret)
    require(native['requestTag'] == target['requestTag'])
    if target['directory'] != 'handoffs' and native['state'] != 'SUCCEEDED':
        raise Unresolved('Native sender result is unresolved; retain the original UUID')


def validate_gwt_data(value):
    require(isinstance(value, dict) and set(value) == GWT_DATA_FIELDS)
    path = value['dataDirectory']
    require(isinstance(path, str) and path.startswith('/') and not path.startswith('//') and path != '/'
        and str(Path(path)) == path and '..' not in Path(path).parts
        and all(ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in path))
    try: require(len(path.encode('utf-8')) <= 4096)
    except UnicodeError: raise Refused('Invalid effective Core data directory') from None
    for name in ('dataDevice', 'dataInode'):
        require(isinstance(value[name], str) and re.fullmatch(r'0|[1-9][0-9]{0,19}', value[name]) is not None)
    require(int(value['dataInode']) > 0 and type(value['dataUid']) is int and 0 < value['dataUid'] < 0xffffffff)
    return value


def gwt_namespace(state, secret):
    require(len(secret) == 32)
    metadata = state.lstat()
    require(stat.S_ISDIR(metadata.st_mode))
    identity = dict(rootDevice=str(metadata.st_dev), rootInode=str(metadata.st_ino))
    identity['namespaceSha256'] = hmac.new(secret, b'yofc-kura-gwt-namespace-v1\0' + encoded(identity), hashlib.sha256).hexdigest()
    return identity


def validate_gwt_binding(value):
    require(isinstance(value, dict) and set(value) == GWT_BINDING_FIELDS
        and type(value['schema']) is int and value['schema'] == 1 and value['purpose'] == GWT_BINDING_PURPOSE
        and is_digest(value['namespaceSha256']))
    validate_gwt_data({k: value[k] for k in GWT_DATA_FIELDS})
    for name in ('rootDevice', 'rootInode'):
        require(isinstance(value[name], str) and re.fullmatch(r'0|[1-9][0-9]{0,19}', value[name]) is not None)
    require(int(value['rootInode']) > 0)
    return value


def validate_gwt_intent(kind, value):
    require(isinstance(value, dict) and type(value.get('schema')) is int and value['schema'] == 1)
    user = value.get('operator')
    require(isinstance(user, str) and user.strip() and all(ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in user))
    try: require(len(user.encode('utf-8')) <= 128)
    except UnicodeError: raise Refused('Invalid GWT operator') from None
    action = value.get('action')
    if kind == 'HANDOFF':
        require(set(value) == {'schema', 'action', 'operator', *HANDOFF_IDS, 'expectedRingSha256', 'expectedCohortSha256'}
            and action == 'generation-handoff-create' and all(canonical_id(value[k]) for k in HANDOFF_IDS)
            and len({value[k] for k in HANDOFF_IDS}) == 5
            and all(is_digest(value[k]) for k in ('expectedRingSha256', 'expectedCohortSha256')))
        return value['handoffId']
    require(canonical_id(value.get('operationId')))
    common = {'schema', 'action', 'operationId', 'operator'}
    if kind == 'LEGACY':
        require(action in ('backup-create', 'restore') and set(value) == common |
            ({'backupSha256', 'expectedKeySha256'} if action == 'restore' else set()))
        if action == 'restore': require(is_digest(value['backupSha256']) and is_digest(value['expectedKeySha256']))
    else:
        require(kind == 'GENERATION' and action in ('generation-prepare', 'generation-backup-verify'))
        if action == 'generation-prepare':
            require(set(value) == common | {'expectedSource'})
            source = value['expectedSource']
            require(isinstance(source, dict) and set(source) == {'keySha256', 'ringSha256'} and is_digest(source['keySha256'])
                and (source['ringSha256'] is None or is_digest(source['ringSha256'])))
        else:
            require(set(value) == common | {'preparationId', 'expectedRingSha256', 'backupSha256'}
                and canonical_id(value['preparationId']) and value['preparationId'] != value['operationId']
                and all(is_digest(value[k]) for k in ('expectedRingSha256', 'backupSha256')))
    return value['operationId']


def validate_handoff_authority(value, identity, secret):
    require(isinstance(value, dict) and set(value) == {'schema', 'purpose', 'request', 'requestTag', 'owner', 'source',
        'generation', 'historySha256', 'nonce', 'issuedBoottimeNs', 'expiresBoottimeNs', 'issuedAt', 'expiresAt', 'receiptTag'}
        and type(value['schema']) is int and value['schema'] == 1 and value['purpose'] == 'yofc-kura-generation-handoff-v1'
        and validate_gwt_intent('HANDOFF', value['request']) == identity and len(secret) == 32)
    require(all(is_digest(value[k]) for k in ('requestTag', 'historySha256', 'nonce', 'receiptTag')))
    require(hmac.compare_digest(value['requestTag'], hmac.new(secret, encoded(value['request']), hashlib.sha256).hexdigest())
        and hmac.compare_digest(value['receiptTag'], hmac.new(secret, b'yofc-kura-generation-handoff-receipt-v1\0' +
            encoded({k: v for k, v in value.items() if k != 'receiptTag'}), hashlib.sha256).hexdigest()))
    source = value['source']; require(isinstance(source, dict) and set(source) == {'keySha256', 'ringSha256'}
        and is_digest(source['keySha256']) and (source['ringSha256'] is None or is_digest(source['ringSha256'])))
    validate_generation_metadata(value['generation'])
    owner = value['owner']; require(isinstance(owner, dict)
        and set(owner) == {'pid', 'uid', 'startTicks', 'bootId', 'invocationId', 'lockDevice', 'lockInode'}
        and all(type(owner[k]) is int and owner[k] >= 0 for k in ('pid', 'uid', 'lockDevice', 'lockInode'))
        and owner['pid'] > 0 and owner['lockInode'] > 0 and isinstance(owner['startTicks'], str) and owner['startTicks'].isdigit()
        and isinstance(owner['invocationId'], str) and re.fullmatch(r'[0-9a-f]{32}', owner['invocationId']) is not None
        and canonical_id(owner['bootId']))
    require(all(type(value[k]) is int and value[k] >= 0 for k in ('issuedBoottimeNs', 'expiresBoottimeNs', 'issuedAt', 'expiresAt'))
        and value['expiresBoottimeNs'] - value['issuedBoottimeNs'] == 900_000_000_000
        and value['expiresAt'] - value['issuedAt'] == 900 and value['generation']['ringSha256'] == value['request']['expectedRingSha256'])
    return value


def handoff_operation_request(value, *, start=False):
    """The two fixed native requests covered by one authenticated authority."""
    request = value['request']
    result = dict(schema=1, action='generation-core-start' if start else 'generation-publish',
        operationId=request['startOperationId' if start else 'publicationId'],
        expectedRingSha256=request['expectedRingSha256'], expectedCohortSha256=request['expectedCohortSha256'])
    if start:
        result['publicationId'] = request['publicationId']
    else:
        result.update(preparationId=request['preparationId'], verificationId=request['verificationId'])
    return result


HANDOFF_IDS = ('handoffId', 'preparationId', 'verificationId', 'publicationId', 'startOperationId')
HANDOFF_BINDING = frozenset(('schema', 'operator', 'ringSha256', 'cohortSha256', 'historySha256', *HANDOFF_IDS))
HANDOFF_REVOCATION_PURPOSE = 'yofc.kura.unused-handoff-revocation.v1'
HANDOFF_REVOCATION_CONTEXT = b'yofc-kura-unused-handoff-revocation-v1\0'


def read_handoff_revocation(policy, identity, secret):
    """Read one permanent fence without archive-inventory recursion."""
    parent=policy.state/'handoff-revocations'
    if not os.path.lexists(parent):return None
    policy.directory(parent,private=True)
    path=parent/(identity+'.json')
    try:raw=policy.read(path,8192)
    except FileNotFoundError:return None
    value=decode(raw);namespace=gwt_namespace(policy.state,secret)['namespaceSha256']
    require(isinstance(value,dict) and set(value)=={'schema','purpose','handoffId','grantSha256',
        'namespaceSha256','revokedAt','revokedByUid','receiptTag'}
        and type(value['schema']) is int and value['schema']==1 and value['purpose']==HANDOFF_REVOCATION_PURPOSE
        and value['handoffId']==identity and value['namespaceSha256']==namespace
        and type(value['revokedAt']) is int and value['revokedAt']>=0
        and type(value['revokedByUid']) is int and value['revokedByUid']>=0
        and is_digest(value['grantSha256']) and is_digest(value['receiptTag'])
        and raw==encoded(value) and stat.S_IMODE(path.lstat().st_mode)==0o400)
    require(hmac.compare_digest(value['receiptTag'],hmac.new(secret,HANDOFF_REVOCATION_CONTEXT+
        encoded({k:v for k,v in value.items() if k!='receiptTag'}),hashlib.sha256).hexdigest()))
    authority_path=policy.state/'handoffs'/(identity+'.json');authority_raw=policy.read(authority_path,8192)
    authority=validate_handoff_authority(decode(authority_raw),identity,secret)
    require(authority_raw==encoded(authority) and stat.S_IMODE(authority_path.lstat().st_mode)==0o400
        and value['grantSha256']==hashlib.sha256(authority_raw).hexdigest())
    for key in ('publicationId','startOperationId'):
        for directory in ('operations','startups','handoffs'):
            require(not os.path.lexists(policy.state/directory/(authority['request'][key]+'.json')),
                'A revoked unused authority cannot conceal an original operation')
    return value,authority,hashlib.sha256(raw).hexdigest()


def handoff_revocations(policy):
    """Authenticated permanent fences, including a revocation interrupted before sender closure."""
    parent=policy.state/'handoff-revocations'
    if not os.path.lexists(parent):return {}
    policy.directory(parent,private=True);policy.directory(policy.state/'handoffs',private=True)
    paths=list(parent.iterdir())
    for path in paths:require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
    require(active_journal_count(policy,'handoffs',[path.name[:-5] for path in paths])<=32)
    secret=policy.read(policy.state/'journal.key',32);result={}
    for path in paths:
        value=read_handoff_revocation(policy,path.name[:-5],secret);require(value is not None)
        result[path.name[:-5]]=value
    return result


def handoff_revocation_view(revoked):
    receipt, authority, fingerprint = revoked; request = authority['request']
    return dict(schema=1, **{key: request[key] for key in (*HANDOFF_IDS, 'operator')},
        ringSha256=request['expectedRingSha256'], cohortSha256=request['expectedCohortSha256'],
        historySha256=authority['historySha256'], state='UNUSED_AUTHORITY_REVOKED', scope='FIXED_OPERATIONS_NOT_ADMITTED',
        namespaceSha256=receipt['namespaceSha256'], revocationSha256=fingerprint)


def validate_handoff_retired(value, binding):
    validate_handoff_binding(binding)
    require(isinstance(value, dict) and set(value) == HANDOFF_BINDING | {'state', 'scope', 'namespaceSha256', 'revocationSha256'}
        and {key: value[key] for key in HANDOFF_BINDING} == binding and value['state'] == 'UNUSED_AUTHORITY_REVOKED'
        and value['scope'] == 'FIXED_OPERATIONS_NOT_ADMITTED' and is_digest(value['namespaceSha256'])
        and is_digest(value['revocationSha256']))
    return value


def validate_handoff_binding(value):
    require(isinstance(value, dict) and set(value) == HANDOFF_BINDING
        and type(value['schema']) is int and value['schema'] == 1
        and all(canonical_id(value[name]) for name in HANDOFF_IDS)
        and len({value[name] for name in HANDOFF_IDS}) == len(HANDOFF_IDS)
        and all(is_digest(value[name]) for name in ('ringSha256', 'cohortSha256', 'historySha256')))
    user = value['operator']; require(isinstance(user, str))
    try:
        require(user.strip() and len(user.encode('utf-8')) <= 128
            and all(ord(char) >= 32 and not 127 <= ord(char) <= 159 for char in user))
    except UnicodeError:
        raise Refused('Invalid handoff binding') from None


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


START_LEASE_CONTEXT = b'yofc.kura.generation-start-lease.v1\0'


def validate_start_lease(value, identity):
    names = {'schema','operationId','action','state','purpose','scope','handoffId','publicationId','startOperationId',
        'publicationSha256','grantSha256','namespaceSha256','bootId','issuedBoottimeNs','expiresBoottimeNs',
        'issuedAt','expiresAt','receiptTag','credentialsChanged','startRequested'}
    require(isinstance(value, dict) and set(value) == names and type(value['schema']) is int and value['schema'] == 1
        and value['action'] == 'generation-start-lease' and value['state'] == 'SUCCEEDED'
        and value['purpose'] == 'yofc.kura.generation-start-lease.v1' and value['scope'] == 'ORIGINAL_FIRST_START_ONLY'
        and value['operationId'] == identity and all(canonical_id(value[k]) for k in
            ('operationId','handoffId','publicationId','startOperationId','bootId'))
        and len({value[k] for k in ('operationId','handoffId','publicationId','startOperationId')}) == 4
        and all(is_digest(value[k]) for k in ('publicationSha256','grantSha256','namespaceSha256','receiptTag'))
        and all(type(value[k]) is int and value[k] >= 0 for k in ('issuedBoottimeNs','expiresBoottimeNs','issuedAt','expiresAt'))
        and value['expiresBoottimeNs'] - value['issuedBoottimeNs'] == 900_000_000_000
        and value['expiresAt'] - value['issuedAt'] == 900 and value['credentialsChanged'] is False and value['startRequested'] is False)
    return value


def validate_record(record, identity):
    cancel = isinstance(record, dict) and record.get('action') == 'generation-cancel'
    lease = isinstance(record, dict) and record.get('action') == 'generation-start-lease'
    require(isinstance(record, dict) and set(record) ==
            {"schema", "operationId", "action", "requestTag", "state", "response"} | ({'intent'} if cancel or lease else set()))
    require(type(record["schema"]) is int and record["schema"] == 1 and canonical_id(identity)
            and record["operationId"] == identity and record["action"] in
              ("backup-create", "generation-backup-create", "restore", "generation-restore", "generation-prepare", "generation-backup-verify",
                 "generation-publish", "generation-core-start", "generation-cancel", "generation-start-lease")
            and record["state"] in ("INTENT", "SUCCEEDED") and is_digest(record["requestTag"]))
    response = record["response"]
    if lease:
        intent = record['intent']
        require(isinstance(intent, dict) and set(intent) == {'handoffId','expectedPublicationSha256'}
            and canonical_id(intent['handoffId']) and intent['handoffId'] != identity and is_digest(intent['expectedPublicationSha256']))
    if cancel:
        intent = record['intent']
        require(isinstance(intent, dict) and set(intent) == {
            'preparationId', 'expectedHistorySha256', 'expectedRingSha256'})
        require(canonical_id(intent['preparationId']) and intent['preparationId'] != identity
                and is_digest(intent['expectedHistorySha256']) and is_digest(intent['expectedRingSha256']))
    if record["state"] == "INTENT":
        require(response is None)
        return record
    if lease:
        validate_start_lease(response, identity)
        require(response['handoffId'] == intent['handoffId'] and response['publicationSha256'] == intent['expectedPublicationSha256'])
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
    require(isinstance(record,dict) and type(record.get('schema')) is int and record['schema'] in (1,2))
    require(set(record)=={'schema','maintenanceId','firstAction','manifestSha256',
            'keySha256','precedingStartupIds','previousMaintenanceId'}|({'precedingArchiveId','precedingArchiveSha256'} if record['schema']==2 else set()))
    require(canonical_id(identity)
            and record['maintenanceId']==identity and record['firstAction'] in ('install','upgrade','remove')
            and is_digest(record['manifestSha256']) and is_digest(record['keySha256'])
            and (record['previousMaintenanceId'] is None or canonical_id(record['previousMaintenanceId']))
            and record['previousMaintenanceId']!=identity)
    ids=record['precedingStartupIds']
    require(isinstance(ids,list) and len(ids)<=32 and all(canonical_id(v) for v in ids)
            and ids==sorted(set(ids)))
    if record['schema']==2:
        require(canonical_id(record['precedingArchiveId']) and is_digest(record['precedingArchiveSha256']))
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


class GwtSenderInventory:
    """Compatibility facade; the package-pinned journal module owns the reader."""
    JOURNALS = {'LEGACY': ('gateway-key-operations', '.key.lock', 64),
                'GENERATION': ('gateway-key-generations', '.generation.lock', 64),
                'HANDOFF': ('gateway-key-handoffs', '.handoff.lock', 32)}
    @staticmethod
    def identity(m):
        return m.st_dev, m.st_ino, m.st_size, m.st_uid, m.st_gid, m.st_mode, m.st_nlink, m.st_mtime_ns, m.st_ctime_ns

    def __new__(cls,policy,binding):
        return policy.journal_module().GwtSenderInventory(policy,binding)


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

    def journal_module(self):
        """Use the new preinst's embedded reader, or the installed manifest-pinned source.

        Old installed helpers and pyc are never executed by the new preinst.
        The module is loaded only after this lifecycle module is fully defined.
        """
        source=globals().get('_KURA_EMBEDDED_JOURNAL_SOURCE');name='bin/kura_key_journal.py'
        if source is None:
            manifest=self.assets();require(name in manifest['files'],'Key-journal reader package is not paired')
            home=self.path('/opt/eclipse/kura').resolve(strict=True)
            source=self.read(home/name,limit=131072,private=False)
            require(hashlib.sha256(source).hexdigest()==manifest['files'][name])
        require(isinstance(source,bytes) and 0<len(source)<=131072)
        fingerprint=hashlib.sha256(source).hexdigest()
        cached=getattr(self,'_journal_module',None)
        if cached is not None and cached[0]==fingerprint:return cached[1]
        module=types.ModuleType('kura_key_journal');module.__file__='<paired key-journal reader>'
        module.__dict__['_kura_lifecycle_api']=dict(globals())
        exec(compile(source,module.__file__,'exec',dont_inherit=True),module.__dict__)
        require(type(getattr(module,'JOURNAL_READER_PROTOCOL',None)) is int and module.JOURNAL_READER_PROTOCOL==1
            and all(callable(getattr(module,name,None)) for name in
                ('GwtSenderInventory','private_fence','archive_journal','RecoveryPrivateFormat','RecoveryPrivateArchive')),
            'Unsupported paired key-journal reader protocol')
        self._journal_module=(fingerprint,module);return module

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
        require({p.name for p in names} <= {"operations", "admission.lock", "journal.key", "maintenance.json", "startups", "package-history", "gwt-sender.json", 'sender-admissions', 'sender-admission.lock',
            'generations','generation-current.json','handoffs','handoff-revocations','archives'})
        try:self.check_extended_journal()
        except (OSError,KeyError,TypeError,ValueError):raise Refused('Invalid retained generation/archive layout; preserve keys and original IDs') from None
        lock = self.state / "admission.lock"
        if not os.path.lexists(lock):
            require(not list((self.state / "operations").iterdir()), "Missing admission lock with saved operations")
            self.create(lock, b"")
        require(self.read(lock) == b"", "Invalid key-service admission lock")
        sender = self.state/'sender-admission.lock'
        if not os.path.lexists(sender):
            require(not os.path.lexists(self.state/'sender-admissions'), 'Missing sender lock with saved reservations')
            self.create(sender, b'')
        require(self.read(sender, limit=0) == b'')

    def check_extended_journal(self):
        """Validate known generation/authority bytes before accepting their layout.

        This is an independent package reader. It executes no installed Manager,
        performs no key repair and never interprets a partial result as closed.
        """
        inventory=archive_inventory(self)
        sender=self.state/'sender-admissions'
        values=[]
        if os.path.lexists(sender):
            self.directory(sender,private=True)
            for path in sender.iterdir():
                require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                value=decode(self.read(path,8192))
                values.append(value)
                if value.get('purpose')==PRIVATE_FENCE_PURPOSE:
                    secret=self.read(self.state/'journal.key',32)
                    validate_sender_admission(value,path.name[:-5],secret);check_sender_original(self,value,secret)
                    require(value['namespaceSha256']==gwt_namespace(self.state,secret)['namespaceSha256'])
        check_private_fence_links(self,values)
        extended=any(os.path.lexists(self.state/name) for name in
            ('generations','generation-current.json','handoffs','handoff-revocations'))
        if not extended:return
        secret=self.read(self.state/'journal.key',32);require(len(secret)==32)
        def record(identity):
            require(canonical_id(identity))
            return validate_record(decode(self.read(self.state/'operations'/(identity+'.json'))),identity)
        authorities=self.state/'handoffs'
        if os.path.lexists(authorities):
            self.directory(authorities,private=True);paths=list(authorities.iterdir())
            require(active_journal_count(self,'handoffs',[p.name[:-5] for p in paths],inventory=inventory)<=32)
            for path in paths:
                require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                raw=self.read(path,8192);authority=validate_handoff_authority(decode(raw),path.name[:-5],secret)
                require(raw==encoded(authority) and stat.S_IMODE(path.lstat().st_mode)==0o400)
                request=authority['request'];prepared=record(request['preparationId']);verified=record(request['verificationId'])
                require(prepared['action']=='generation-prepare' and verified['action']=='generation-backup-verify')
                if prepared['state']!='SUCCEEDED' or verified['state']!='SUCCEEDED':raise Unresolved('Original authority preparation is incomplete')
                require(prepared['response']['generation']==authority['generation']
                    and prepared['response']['historySha256']==authority['historySha256']
                    and verified['response']['preparationId']==request['preparationId']
                    and verified['response']['ringSha256']==request['expectedRingSha256'])
                for start in (False,True):
                    native=handoff_operation_request(authority,start=start);target=self.state/'operations'/(native['operationId']+'.json')
                    if os.path.lexists(target):
                        original=record(native['operationId'])
                        require(original['action']==native['action'] and hmac.compare_digest(original['requestTag'],
                            hmac.new(secret,encoded(native),hashlib.sha256).hexdigest()))
        handoff_revocations(self)
        parent=self.state/'generations'
        if os.path.lexists(parent):
            self.directory(parent,private=True);paths=list(parent.iterdir())
            require(active_journal_count(self,'operations',[p.name for p in paths],inventory=inventory)<=256)
            allowed={'keyring','source-keyring','history.json','cancellation.json','publication.json',
                'publication-recovery.json','source-active-key','source-provisioned.json','source-generation-receipt.json'}
            for slot in paths:
                require(canonical_id(slot.name));self.directory(slot,private=True)
                names={p.name for p in slot.iterdir()};require(names<=allowed)
                prepared=record(slot.name)
                require(prepared['action']=='generation-prepare')
                if prepared['state']!='SUCCEEDED':raise Unresolved('Original preparation is incomplete; preserve keys and UUID')
                require({'keyring','history.json'}<=names and not {'publication.json','cancellation.json'}<=names)
                raw=self.read(slot/'history.json',8192);history=decode(raw);response=prepared['response']
                require(set(history)=={'schema','purpose','preparationId','createdAt','source','sourceReceipt',
                    'sourceGenerationReceipt','provisioned','generation','backupSha256'}
                    and type(history['schema']) is int and history['schema']==1
                    and history['purpose']=='yofc-kura-prepared-generation-v1' and history['preparationId']==slot.name
                    and history['source']==response['source'] and history['generation']==response['generation']
                    and hashlib.sha256(raw).hexdigest()==response['historySha256']
                    and hashlib.sha256(encoded(response['backup'])).hexdigest()==history['backupSha256'])
                validate_generation_metadata(history['generation'])
                require(hashlib.sha256(self.read(slot/'keyring',512)).hexdigest()==history['generation']['ringSha256'])
                for name in names:
                    path=slot/name;self.read(path,65536);require(stat.S_IMODE(path.lstat().st_mode)==0o400)
                if 'source-active-key' in names:
                    require(hashlib.sha256(self.read(slot/'source-active-key',32)).hexdigest()==history['source']['keySha256'])
                if 'source-provisioned.json' in names:
                    require(decode(self.read(slot/'source-provisioned.json',8192))==history['sourceReceipt'])
                if 'source-generation-receipt.json' in names:
                    require(history['sourceGenerationReceipt'] is not None)
                    require(decode(self.read(slot/'source-generation-receipt.json',8192))==dict(
                        schema=1,purpose=GENERATION_FORMAT,**history['sourceGenerationReceipt']))
                if history['source']['ringSha256'] is None:
                    require('source-keyring' not in names and history['sourceGenerationReceipt'] is None)
                else:
                    require('source-keyring' in names)
                    validate_generation_metadata(history['sourceGenerationReceipt'])
                    require(hashlib.sha256(self.read(slot/'source-keyring',512)).hexdigest()==history['source']['ringSha256']
                        ==history['sourceGenerationReceipt']['ringSha256'])
                if 'cancellation.json' in names:
                    raw=self.read(slot/'cancellation.json',8192);value=decode(raw)
                    require(set(value)=={'schema','purpose','operationId','preparationId','historySha256','ringSha256','source','createdAt','receiptTag'}
                        and type(value['schema']) is int and value['schema']==1 and value['purpose']=='yofc-kura-generation-cancel-v1'
                        and value['preparationId']==slot.name and value['source']==history['source']
                        and value['historySha256']==response['historySha256'] and value['ringSha256']==history['generation']['ringSha256']
                        and raw==encoded(value))
                    body={k:v for k,v in value.items() if k!='receiptTag'}
                    require(is_digest(value['receiptTag']) and hmac.compare_digest(value['receiptTag'],hmac.new(secret,
                        b'yofc-kura-cancel-receipt-v1\0'+encoded(body),hashlib.sha256).hexdigest()))
                    cancelled=record(value['operationId']);require(cancelled['action']=='generation-cancel')
                    if cancelled['state']!='SUCCEEDED':raise Unresolved('Original cancellation is incomplete')
                    require(cancelled['response']['cancellationSha256']==hashlib.sha256(raw).hexdigest())
                if 'publication.json' in names:
                    require({'source-active-key','source-provisioned.json','publication-recovery.json'}<=names)
                    raw=self.read(slot/'publication.json',8192);value=validate_publication(decode(raw))
                    require(raw==encoded(value) and value['preparationId']==slot.name
                        and value['historySha256']==response['historySha256'] and value['source']==history['source']
                        and value['generation']==history['generation'])
                    published=record(value['operationId']);require(published['action']=='generation-publish')
                    if published['state']!='SUCCEEDED':raise Unresolved('Original publication is incomplete')
                    require(published['response']['publicationSha256']==hashlib.sha256(raw).hexdigest())
                if 'publication-recovery.json' in names:
                    raw=self.read(slot/'publication-recovery.json',16384);value=decode(raw)
                    require(set(value)=={'schema','purpose','publication','sourceFiles','writerUid','receiptTag'}
                        and type(value['schema']) is int and value['schema']==1 and value['purpose']=='yofc-kura-publication-recovery-v1'
                        and raw==encoded(value) and validate_publication(value['publication'])['preparationId']==slot.name)
                    body={k:v for k,v in value.items() if k!='receiptTag'}
                    require(is_digest(value['receiptTag']) and hmac.compare_digest(value['receiptTag'],hmac.new(secret,
                        b'yofc-kura-publication-recovery-v1\0'+encoded(body),hashlib.sha256).hexdigest()))
        current=self.state/'generation-current.json'
        if os.path.lexists(current):
            raw=self.read(current,8192);value=validate_publication(decode(raw))
            immutable=self.state/'generations'/value['preparationId']/'publication.json'
            require(raw==encoded(value) and self.read(immutable,8192)==raw)
            original=record(value['operationId'])
            require(original['action']=='generation-publish')
            if original['state']!='SUCCEEDED':raise Unresolved('Current publication is incomplete')
            require(original['response']['publicationSha256']==hashlib.sha256(raw).hexdigest())

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

    def check_records(self, *, recovering_cancel=None, recovering_publication=None):
        inventory=archive_inventory(self)
        handoff_revocations(self)
        self.directory(self.state / "operations", private=True)
        paths = list((self.state / "operations").iterdir())
        require(active_journal_count(self,'operations',[p.name[:-5] for p in paths],inventory=inventory) <= 256)
        for path in paths:
            require(path.name.endswith(".json") and canonical_id(path.name[:-5]))
            record = validate_record(decode(self.read(path)), path.name[:-5])
            if record["state"] != "SUCCEEDED":
                if path.name[:-5] == recovering_cancel and record['action'] == 'generation-cancel':
                    continue
                if path.name[:-5] == recovering_publication and record['action'] == 'generation-publish':
                    continue
                raise Unresolved("Unresolved key operation; preserve original UUID and package state")
        startups=self.state/'startups'
        if os.path.lexists(startups):
            self.directory(startups,private=True)
            starts=list(startups.iterdir());require(active_journal_count(self,'startups',[p.name[:-5] for p in starts],inventory=inventory)<=32)
            for path in starts:
                require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                record=validate_start(decode(self.read(path)),path.name[:-5])
                if record['state'] != 'SUCCEEDED':
                    raise Unresolved('Unresolved Core start; retain original UUID')
        history=self.state/'package-history'
        if os.path.lexists(history):
            self.directory(history,private=True)
            records=list(history.iterdir());require(active_journal_count(self,'package-history',[p.name[:-5] for p in records],inventory=inventory)<=128)
            for path in records:
                require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                value=validate_maintenance(decode(self.read(path)),path.name[:-5])
                if value['schema']==2:maintenance_includes_startup(self,value,'',inventory=inventory)
        return paths

    @contextlib.contextmanager
    def sender_locked(self):
        path = self.state/'sender-admission.lock'; require(self.read(path, limit=0) == b'')
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise Refused('A sender admission is active; package change refused') from None
            yield
        finally: os.close(fd)

    def check_sender_admissions(self):
        directory = self.state/'sender-admissions'
        if not os.path.lexists(directory): return
        self.directory(directory, private=True); paths = list(directory.iterdir())
        require(active_journal_count(self,'sender-admissions',[p.name[:-5] for p in paths]) <= 256)
        secret = self.read(self.state/'journal.key', 32); namespace = gwt_namespace(self.state, secret)['namespaceSha256']
        values=[]
        for path in paths:
            require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
            value = validate_sender_admission(decode(self.read(path, 8192)), path.name[:-5], secret)
            require(value['namespaceSha256'] == namespace)
            check_sender_original(self, value, secret)
            values.append(value)
        check_private_fence_links(self,values)

    @contextlib.contextmanager
    def gwt_locked(self):
        path = self.state/'gwt-sender.json'
        if not os.path.lexists(path):
            # Legacy/unregistered directory discovery remains a separate migration gate.
            yield None
            return
        binding = validate_gwt_binding(decode(self.read(path, 8192)))
        namespace = gwt_namespace(self.state, self.read(self.state/'journal.key', 32))
        require(all(binding[k] == namespace[k] for k in GWT_NAMESPACE_FIELDS))
        require(binding['dataUid'] == pwd.getpwnam('kurad').pw_uid)
        with GwtSenderInventory(self, binding).locked() as inventory:
            yield inventory

    def fence(self):
        marker = self.state / "maintenance.json"
        if not os.path.lexists(marker):
            return None
        value = decode(self.read(marker))
        require(set(value) == {"schema", "id", "state", "firstAction"}
                and type(value["schema"]) is int and value["schema"] == 1 and canonical_id(value["id"])
                and value["state"] == "MAINTENANCE" and value["firstAction"] in ("install", "upgrade", "remove"))
        return value

    def main_unit_state(self):
        value = self.command(['show', 'kura.service', '--property=UnitFileState', '--value']).strip()
        require(value in ('enabled', 'enabled-runtime', 'disabled', 'static', 'masked', 'masked-runtime'),
                'Unsupported Main boot choice; preserve installation')
        return value

    def check_main_package_layout(self, manifest=None):
        """Reject unsupported existing layouts before a new maintenance fence.

        This is package admission, not startup or cold-recovery admission. Do
        not require an absent/broken Core reader merely to keep recovery alive,
        and do not reinterpret an already admitted package transaction while
        its files are being replaced.
        """
        require(not any(os.path.lexists(self.path(path).with_name(MAIN_LINK_BACKUP)) for path in MAIN_LINKS.values()),
                'Complete the existing Main link migration before package maintenance')
        if not self.path('/run/systemd/system').is_dir() or not any(
                os.path.lexists(self.path(prefix + '/systemd/system/kura.service'))
                for prefix in ('/etc', '/run', '/lib', '/usr/lib')):
            return
        if self.main_unit_state() == 'static':
            self.paired_main_unit(manifest, 'static')

    @staticmethod
    def main_unit_digest(manifest):
        generation = manifest.get('generation') if manifest and manifest['schema'] == 2 else None
        require(isinstance(generation, dict) and is_digest(generation.get('unitSha256')),
                'Main unit has no paired package definition; preserve installation')
        return generation['unitSha256']

    def main_vendor_path(self):
        vendor = self.path(MAIN_VENDOR_PATHS[0])
        physical = vendor.parent.resolve(strict=True) / vendor.name
        require(physical in tuple(self.path(path) for path in MAIN_VENDOR_PATHS),
                'Main vendor path requires reviewed migration')
        return physical

    def main_unit_properties(self, *extra):
        fields = ('Id', 'Names', 'LoadState', 'UnitFileState', 'SourcePath', 'DropInPaths',
                  'NeedDaemonReload', 'Transient', 'FragmentPath', *extra)
        output = self.command(['show', 'kura.service', '--property=' + ','.join(fields)])
        rows = [line.split('=', 1) for line in output.splitlines()]
        require(all(len(row) == 2 for row in rows) and len(rows) == len(fields),
                'Unexpected Main unit properties; preserve installation')
        properties = dict(rows)
        require(properties.keys() == set(fields), 'Unexpected Main unit properties; preserve installation')
        return properties

    def paired_main_unit(self, manifest, choice):
        expected = self.main_unit_digest(manifest)
        physical = self.main_vendor_path()
        unit = self.read(physical, private=False)
        require(hashlib.sha256(unit).hexdigest() == expected,
                'Main unit differs from its package; reviewed migration is required')
        properties = self.main_unit_properties()
        fragment = properties.pop('FragmentPath')
        fields = dict(Id='kura.service', Names='kura.service', LoadState='loaded', UnitFileState=choice,
                      SourcePath='', DropInPaths='', NeedDaemonReload='no', Transient='no')
        require(properties == fields and fragment in MAIN_VENDOR_PATHS, 'Effective Main unit requires reviewed migration')
        loaded = self.path(fragment)
        require(loaded.parent.resolve(strict=True) / loaded.name == physical
                and self.read(physical, private=False) == unit, 'Main unit changed during package pairing')
        return unit

    @staticmethod
    def main_accounts():
        # cp -a preserves numeric data owners. Recreating either name with a
        # different UID would leave the restored files owned by another user.
        return {name: dict(uid=pwd.getpwnam(name).pw_uid, gid=pwd.getpwnam(name).pw_gid)
                for name in ('kura', 'kurad')}

    def retain_main_state(self, directory):
        directory = Path(directory)
        require(directory.parent == self.path('/var/lib')
                and re.fullmatch(r'\.kura-retained\.tmp\.[A-Za-z0-9]{8}', directory.name),
                'Unsupported Main retention directory')
        self.directory(directory, private=True)
        self.directory(directory / 'systemd', private=True)
        with self.locked():
            self.check_records()
            fence = self.fence()
            require(fence is not None and fence['firstAction'] == 'remove')
            manifest = self.assets()
            saved = self.read(directory / 'systemd/kura.service', private=False)
            choice = self.main_unit_state()
            if choice == 'static':
                installed = self.paired_main_unit(manifest, choice)
            else:
                installed = self.read(self.path('/lib/systemd/system/kura.service').resolve(strict=True), private=False)
            require(saved == installed, 'Saved Main unit changed before retention')
            # Schema 2 attests that the static choice came from a paired vendor
            # unit. Older receipts did not record that package admission fact.
            value = dict(schema=2 if choice == 'static' else 1, purpose='yofc.kura.retained-main.v1',
                         maintenanceId=fence['id'], unitSha256=hashlib.sha256(saved).hexdigest(), unitFileState=choice,
                         accounts=self.main_accounts())
            secret = self.read(self.state / 'journal.key', 32)
            require(len(secret) == 32)
            value['receiptTag'] = hmac.new(secret, b'yofc-kura-retained-main-v1\0' + encoded(value), hashlib.sha256).hexdigest()
            self.create(directory / 'systemd/main-state.json', encoded(value))
            if manifest.get('schema') == 2 and self.without_retired_main_caps(saved) != saved:
                installed_manifest = self.path('/opt/eclipse/kura').resolve(strict=True) / 'libexec/key-backup/manifest.json'
                raw = self.read(installed_manifest, private=False)
                require(decode(raw) == manifest)
                self.create(directory / 'systemd/source-package-manifest.json', raw)

    def check_main_source_package(self, directory, fence, unit_digest):
        # A staged manifest must be the last complete package recorded by this Root.
        history = self.state / 'package-history'
        self.directory(history, private=True)
        receipts = {}
        for path in history.iterdir():
            record = validate_maintenance(decode(self.read(path)), path.name[:-5])
            require(path.name.endswith('.json') and record['maintenanceId'] != fence['id'],
                    'Unexpected package history for retained Main')
            receipts[record['maintenanceId']] = record
        previous = {record['previousMaintenanceId'] for record in receipts.values()}
        heads = receipts.keys() - previous
        require(len(heads) == 1, 'Retained static Main has no unique source package')
        head = receipts[next(iter(heads))]
        cursor = head
        visited = set()
        while cursor is not None:
            identity = cursor['maintenanceId']
            require(identity not in visited, 'Invalid source package history')
            visited.add(identity)
            predecessor = cursor['previousMaintenanceId']
            require(predecessor is None or predecessor in receipts, 'Incomplete source package history')
            cursor = receipts.get(predecessor)
        require(len(visited) == len(receipts), 'Invalid source package history')

        evidence = directory / 'systemd/source-package-manifest.json'
        require(os.path.lexists(evidence), 'Retained static Main requires the original package manifest')
        raw = self.read(evidence)
        require(hashlib.sha256(raw).hexdigest() == head['manifestSha256'],
                'Retained static Main manifest differs from the original package')
        manifest = decode(raw)
        require(type(manifest.get('schema')) is int and manifest['schema'] == 2
                and isinstance(manifest.get('generation'), dict)
                and manifest['generation'].get('unitSha256') == unit_digest,
                'Original package cannot pair the retained static Main')

    def retained_main_state(self, restore=False):
        directory = self.path('/var/lib/kura-retained')
        self.directory(directory, private=True)
        with self.locked():
            self.check_records()
            fence = self.fence()
            require(fence is not None and fence['firstAction'] == 'remove')
            value = decode(self.read(directory / 'systemd/main-state.json', 8192))
            require(set(value) == {'schema', 'purpose', 'maintenanceId', 'unitSha256',
                                   'unitFileState', 'accounts', 'receiptTag'}
                    and type(value['schema']) is int
                    and (value['schema'] == 1 or value['schema'] == 2 and value['unitFileState'] == 'static')
                    and value['purpose'] == 'yofc.kura.retained-main.v1'
                    and value['maintenanceId'] == fence['id'] and is_digest(value['receiptTag'])
                    and is_digest(value['unitSha256'])
                    and value['unitFileState'] in ('enabled', 'enabled-runtime', 'disabled', 'static', 'masked', 'masked-runtime')
                    and encoded(value['accounts']) == encoded(self.main_accounts()),
                    'Retained Main state or numeric account identity changed')
            body = {k: v for k, v in value.items() if k != 'receiptTag'}
            secret = self.read(self.state / 'journal.key', 32)
            require(len(secret) == 32 and hmac.compare_digest(value['receiptTag'], hmac.new(secret,
                    b'yofc-kura-retained-main-v1\0' + encoded(body), hashlib.sha256).hexdigest()),
                    'Retained Main state belongs to another package admission')
            require(hashlib.sha256(self.read(directory / 'systemd/kura.service', private=False)).hexdigest()
                    == value['unitSha256'], 'Retained Main unit changed')
            expected = value['unitFileState']
            if expected == 'static' and value['schema'] == 1:
                self.check_main_source_package(directory, fence, value['unitSha256'])
            if restore:
                current = self.main_unit_state()
                if expected == 'static':
                    # When the new package adds [Install], the equivalent
                    # boot choice for a static unit is to leave it disabled.
                    require(current in ('static', 'disabled'), 'Main boot choice changed during retained reinstall')
                    self.paired_main_unit(self.assets(), current)
                elif current != expected:
                    require(current == 'disabled' and expected in ('enabled', 'enabled-runtime'),
                            'Main boot choice changed during retained reinstall')
                    self.command(['enable', *(['--runtime'] if expected == 'enabled-runtime' else []), 'kura.service'])
                    require(self.main_unit_state() == expected, 'Main boot choice was not restored')
            return value

    @staticmethod
    def without_retired_main_caps(unit):
        def directive(match):
            caps = match[2].split()
            kept = [cap for cap in caps if cap.lower() not in (b'cap_sys_boot', b'cap_dac_override')]
            return match[0] if caps == kept else match[1] + b' '.join(kept)

        return re.sub(rb'(?im)^([ \t]*(?:AmbientCapabilities|CapabilityBoundingSet)[ \t]*=[ \t]*)([^\r\n]*)',
                      directive, unit)

    def check_main_reboot_source(self):
        logical = self.path('/lib/systemd/system/kura.service')
        if os.path.lexists(logical):
            raw = self.read(self.main_vendor_path(), private=False)
            if self.without_retired_main_caps(raw) != raw:
                require(hashlib.sha256(raw).hexdigest() == self.main_unit_digest(self.assets()),
                        'Unpaired Main capability grant requires reviewed migration')

    def package_main_restore_decision(self, directory):
        directory = Path(directory)
        retained = directory == self.path('/var/lib/kura-retained')
        require(retained or directory == self.path('/opt/eclipse/.kura-preserve'),
                'Unrecognized Main package preservation directory')
        self.directory(directory, private=True)
        self.directory(directory / 'systemd', private=True)
        old = self.read(directory / 'systemd/kura.service', private=False)
        new = self.read(self.main_vendor_path(), private=False)
        # The supported historical static receipts already establish their
        # source unit's package pairing.
        state = self.retained_main_state() if retained else None
        migrated = self.without_retired_main_caps(old)
        if migrated == old:
            return 'restore'
        incoming = self.assets()
        require(hashlib.sha256(new).hexdigest() == self.main_unit_digest(incoming)
                and self.without_retired_main_caps(new) == new,
                'Incoming Main unit must be the paired vendor unit without the old grant')
        with self.locked():
            fence = self.fence()
            require(fence is not None and fence['firstAction'] == ('remove' if retained else 'upgrade'))
            if retained:
                require(fence['id'] == state['maintenanceId']
                        and hashlib.sha256(old).hexdigest() == state['unitSha256'])
            if not retained or (state['unitFileState'] != 'static' and migrated != new):
                self.check_main_source_package(directory, fence, hashlib.sha256(old).hexdigest())
        return 'vendor'

    def check_main_reboot_permissions(self):
        if not self.path('/run/systemd/system').is_dir():
            return
        properties = self.main_unit_properties('MainPID', 'ControlPID', 'ActiveState',
                                               'AmbientCapabilities', 'CapabilityBoundingSet')
        require(properties['MainPID'] == properties['ControlPID'] == '0'
                and properties['ActiveState'] in ('inactive', 'failed'),
                'Main must be inactive for privilege cutover')
        if properties['UnitFileState'] in ('masked', 'masked-runtime'):
            require(properties['LoadState'] == 'masked')
            return
        require(properties['LoadState'] == 'loaded' and properties['NeedDaemonReload'] == 'no',
                'Verify loaded Main before releasing package maintenance')
        for field in ('AmbientCapabilities', 'CapabilityBoundingSet'):
            caps = properties[field].split()
            require(all(re.fullmatch(r'cap_[a-z0-9_]+', cap) for cap in caps) and not {'cap_sys_boot', 'cap_dac_override'}.intersection(caps),
                    'Effective Main capabilities are invalid or include CAP_SYS_BOOT or CAP_DAC_OVERRIDE; preserve package maintenance')

    def assets(self, *, generation_binding=False, _linked_main_unit=None):
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
        recovery_units = frozenset(UNITS)
        recovery_profiles = {(files, recovery_units) for files in (PRE_JOURNAL_ASSETS, JOURNAL_V1_ASSETS, ASSETS)}
        recognized = (recovery_profiles | {(NATIVE_VALIDATION_ASSETS, frozenset(NATIVE_VALIDATION_UNITS))}) if modern else (
            recovery_profiles | {(LEGACY_ASSETS, frozenset(LEGACY_UNITS)), (COLD_V1_ASSETS, recovery_units)})
        require(profile in recognized and (not modern or isinstance(manifest['generation'], dict)),
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
            unit = _linked_main_unit
            if unit is None:
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
        require({'operations','admission.lock'} <= {p.name for p in state.iterdir()} <=
            {'operations','admission.lock','starts','pending.json','handoffs','admissions','archives'})
        require(read(state/'admission.lock',0)==b'')
        fd=os.open(state/'admission.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise Refused('Cold recovery is active; package change refused') from None
            archived_private=set()
            if os.path.lexists(state/'archives'):
                namespace=dict(schema=1,**gwt_namespace(self.state,self.read(self.state/'journal.key',32)))
                archived_private=self.journal_module().RecoveryPrivateFormat(state,account.pw_uid,account.pw_gid,read,directory).inventory(self,namespace)
            closed_starts = {}; closed_restores = {}; closed_handoffs = {}
            if os.path.lexists(state/'admissions'):
                directory(state/'admissions'); slots = list((state/'admissions').iterdir())
                require(sum(('ADMISSION',p.name[:36],p.name[37:]) not in archived_private for p in slots)<=256)
                for slot in slots:
                    directory(slot); names = {p.name for p in slot.iterdir()}
                    require(names in ({'intent.json','namespace.json'}, {'intent.json','namespace.json','closed.json'},
                        {'intent.json','namespace.json','closed.json','pending.json'}))
                    value = validate_sender_attempt(decode(read(slot/'intent.json', 12288)), 'recovery')
                    require(slot.name == value['nativeOperationId']+'-'+value['kind'])
                    namespace = decode(read(slot/'namespace.json', 4096))
                    original = check_sender_attempt(self, value, namespace, 'recovery', account.pw_uid)
                    archived = None
                    if 'pending.json' in names:
                        archived = validate_receiver_pending(decode(read(slot/'pending.json',4096)), value)
                    if 'closed.json' in names:
                        validate_sender_closed(decode(read(slot/'closed.json', 4096)), value, namespace)
                        require(original['state'] == 'NOT_ADMITTED', 'Closed receiver attempt has no Root not-admitted original')
                        if value['kind'] == 'start':
                            closed_starts[value['nativeOperationId']] = receiver_start_intent(value)
                        if value['kind'] == 'restore' and archived is not None:
                            closed_restores[value['nativeOperationId']] = receiver_restore_intent(value)
                        if value['kind'] in ('publish', 'handoff-start'):
                            closed_handoffs[(value['kind'], value['nativeOperationId'])] = value
            files=list((state/'operations').iterdir());require(sum(('RESTORE',p.name[:-5],None) not in archived_private for p in files)<=32)
            for path in files:
                require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                value=decode(read(path,4096))
                require(set(value)=={'schema','operationId','expectedKeySha256','backupSha256'}
                    and type(value['schema']) is int and value['schema']==1 and value['operationId']==path.name[:-5]
                    and is_digest(value['expectedKeySha256']) and is_digest(value['backupSha256']))
                if value['operationId'] in closed_restores:
                    require(value == closed_restores[value['operationId']], 'Retired restore intent has changed')
                    continue
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
                require(pending['operationId'] not in closed_restores, 'Retired recovery marker remains active')
            if os.path.lexists(state/'starts'):
                directory(state/'starts');starts=list((state/'starts').iterdir())
                require(sum(('START',p.name[:-5],None) not in archived_private for p in starts)<=32)
                for path in starts:
                    require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                    local=decode(read(path,4096))
                    modern=type(local.get('schema')) is int and local['schema']==2
                    extra={'predecessorStartOperationId','maintenanceId','manifestSha256'} if modern else set()
                    require(set(local)=={'schema','operationId','restoreOperationId','expectedKeySha256'}|extra
                            and type(local['schema']) is int and local['schema'] in (1,2) and local['operationId']==path.name[:-5]
                            and canonical_id(local['restoreOperationId']) and is_digest(local['expectedKeySha256']))
                    if modern:require(canonical_id(local['predecessorStartOperationId']) and canonical_id(local['maintenanceId']) and is_digest(local['manifestSha256']))
                    require(local['restoreOperationId'] not in closed_restores, 'Retired restore has a private startup child')
                    if local['operationId'] in closed_starts:
                        require(local == closed_starts[local['operationId']], 'Closed startup private intent has changed')
                        continue  # The authenticated Root NOT_ADMITTED record already proves native absence.
                    root=validate_start(decode(self.read(self.state/'startups'/path.name)),local['operationId'])
                    require(root['state']=='SUCCEEDED' and root['restoreOperationId']==local['restoreOperationId']
                            and root['keySha256']==local['expectedKeySha256'] and all(root.get(k)==local[k] for k in extra),'Unresolved Core handoff; retain original UUID')
            if os.path.lexists(state/'handoffs'):
                directory(state/'handoffs'); handoffs = list((state/'handoffs').iterdir())
                require(sum(('HANDOFF',p.name,None) not in archived_private for p in handoffs)<=32)
                for slot in handoffs:
                    require(canonical_id(slot.name)); directory(slot)
                    names = {p.name for p in slot.iterdir()}
                    require('binding.json' in names and len(names & {'completed.json','retired.json'}) == 1 and names <=
                        {'binding.json', 'completed.json', 'retired.json', 'publish.json', 'continue.json', 'start.json'},
                        'Unresolved fixed-operation handoff; preserve original requests')
                    binding = decode(read(slot/'binding.json', 8192)); validate_handoff_binding(binding)
                    require(binding['handoffId'] == slot.name)
                    for name in ('publish', 'continue', 'start'):
                        if os.path.lexists(slot/(name+'.json')):
                            intent = decode(read(slot/(name+'.json'), 8192))
                            extra = {'expectedRecoveryReceiptSha256'} if name == 'continue' else set()
                            require(set(intent) == HANDOFF_BINDING | {'command'} | extra
                                and {key: intent[key] for key in HANDOFF_BINDING} == binding and intent['command'] == name)
                            if extra: require(is_digest(intent['expectedRecoveryReceiptSha256']))
                    if 'retired.json' in names:
                        retired = validate_handoff_retired(decode(read(slot/'retired.json',8192)), binding)
                        revoked = handoff_revocations(self).get(slot.name)
                        require(revoked is not None and retired == handoff_revocation_view(revoked)
                            and 'continue.json' not in names, 'Unconfirmed unused-authority retirement')
                        for command, kind, key in (('publish','publish','publicationId'), ('start','handoff-start','startOperationId')):
                            if command+'.json' in names:
                                attempt = closed_handoffs.get((kind,binding[key]))
                                require(attempt is not None and attempt['request']['handoffId'] == slot.name,
                                    'Retired handoff has an unclosed original sender attempt')
                        continue
                    completed = decode(read(slot/'completed.json', 8192))
                    require(set(completed) == HANDOFF_BINDING | {'state', 'publicationSha256', 'jobPath'}
                        and {key: completed[key] for key in HANDOFF_BINDING} == binding
                        and completed['state'] == 'ORIGINAL_REQUESTS_CONFIRMED')
                    originals = {}
                    for name, key in (('publish', 'publicationId'), ('start', 'startOperationId')):
                        identity = binding[key]
                        original = validate_record(decode(self.read(self.state/'operations'/(identity+'.json'))), identity)
                        require(original['state'] == 'SUCCEEDED' and original['action'] ==
                            ('generation-publish' if name == 'publish' else 'generation-core-start'),
                            'Unresolved original handoff; retain original UUID')
                        result = original['response']; originals[name] = result
                        require(all(result[field] == binding[field] for field in ('ringSha256', 'cohortSha256')))
                    published, started = originals['publish'], originals['start']
                    require(published['preparationId'] == binding['preparationId'] and published['verificationId'] == binding['verificationId']
                        and started['publicationId'] == binding['publicationId'] and started['activeKeySha256'] == published['activeKeySha256']
                        and completed['publicationSha256'] == published['publicationSha256'] and completed['jobPath'] == started['jobPath'])
            yield dict(archived=archived_private,closedRestores=closed_restores)
        finally:os.close(fd)

    def no_overrides(self):
        for prefix in ("/etc", "/run", "/usr/lib", "/lib"):
            base = self.path(prefix + "/systemd/system")
            for name in NATIVE_VALIDATION_UNITS:
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
            require(not any(os.path.lexists(self.path("/lib/systemd/system/" + name)) for name in NATIVE_VALIDATION_UNITS),
                    "Installed key service requires its systemd manager")
            return
        for name in NATIVE_VALIDATION_UNITS: # Stop listener first, then the idle worker service.
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

    def check_pending_keystore_passwords(self):
        home = self.path('/opt/eclipse/kura')
        if not os.path.lexists(home):
            return
        physical = home.resolve(strict=True)
        require(physical.parent == home.parent and (physical == home or physical.name.startswith('kura_')),
                'Cannot identify the Core directory for keystore maintenance')
        self.directory(physical)

        def scan_error(error):
            raise Refused('Cannot inspect the Core directory for pending PKCS12 password changes') from error

        # Randomization publishes these names before replacing the PKCS12. Copying the
        # tree changes the inode that its encrypted recovery record authenticates.
        for directory, dirs, files, _ in os.fwalk(physical, follow_symlinks=False, onerror=scan_error):
            if re.fullmatch(r'\.kura-keystore-[0-9a-f]{64}', os.path.basename(directory)):
                if any(re.fullmatch(r'password-change-[0-9a-f]{64}', name) for name in (*files, *dirs)):
                    raise ActiveWriter('Finish the original PKCS12 password change before Core maintenance')

    def check_package_writers(self, *, allow_main=False):
        self.check_pending_keystore_passwords()
        # All three packaged Main launchers use this registry. Its outstanding
        # archive publication binds the original directories and files by inode.
        registry = self.path('/opt/eclipse/kura/packages/dpa.properties').resolve()
        receipt = registry.with_name('.' + registry.name + '.publication')
        try:
            receipt.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ActiveWriter('Finish the original deployment package publication before Core maintenance')

        runtime = self.path('/run/kura-key-service')
        writers = runtime / 'writers'
        if not os.path.lexists(runtime):
            return
        self.directory(runtime)
        if not os.path.lexists(writers):
            return
        self.directory(writers, private=True)
        lease = writers / 'lease.lock'
        if not os.path.lexists(lease):
            require(not any(writers.iterdir()), 'Missing registered writer lease')
            return
        fd = os.open(lease, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == self.owner and info.st_nlink == 1
                    and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size == 0
                    and os.path.samestat(info, lease.lstat()), 'Unsafe registered writer lease')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if allow_main and self.managed_writer_registered(writers, info):
                    return  # The maintainer script drains Main and checks the kernel lock again.
                raise ActiveWriter('A Kura writer is still active; package change refused') from None
        finally:
            os.close(fd)

    def managed_writer_registered(self, writers, lock):
        status = self.command(['show', 'kura.service', '--property=MainPID'])
        match = re.fullmatch(r'MainPID=([1-9][0-9]*)', status.strip())
        if not match or match[1] == '1':
            return False
        pid = match[1]
        process = self.path('/proc/' + pid)
        # The Root broker records the lease before exec. A maintainer may read
        # start ticks without having ptrace access to a non-root JVM's fd table.
        try:
            ticks = (process / 'stat').read_text().rsplit(')', 1)[-1].split()[19]
            require(ticks.isdigit(), 'Invalid managed writer start time')
            record = decode(self.read(writers / (pid + '-' + ticks + '.json'), limit=4096))
            uid = process.stat().st_uid
        except (FileNotFoundError, ProcessLookupError):
            return False
        expected = dict(schema=1, state='LEASE_GRANTED', pid=int(pid), startTicks=ticks,
                        bootId=self.path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                        uid=uid, lockDevice=lock.st_dev, lockInode=lock.st_ino)
        return all(record.get(key) == value for key, value in expected.items())

    def enter(self, action):
        require(action in ("install", "upgrade", "remove"))
        self.no_overrides()
        registered = any(os.path.lexists(self.path("/lib/systemd/system/" + name)) for name in NATIVE_VALIDATION_UNITS)
        if self.path("/run/systemd/system").is_dir():
            for name in NATIVE_VALIDATION_UNITS:
                output = self.command(["show", name, "--property=LoadState"])
                properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
                require(properties.get("LoadState") in ("loaded", "masked", "not-found"))
                registered |= properties["LoadState"] != "not-found"
        previous_fence = self.fence() if os.path.lexists(self.state) else None
        manifest = None
        if registered and previous_fence is None:
            manifest=self.assets() # Never execute an unknown installed helper or silently adopt another unit.
            for name in set(NATIVE_VALIDATION_UNITS)-set(manifest['units']):
                require(not os.path.lexists(self.path('/lib/systemd/system/'+name)), 'Foreign recovery unit requires reviewed migration')
                if self.path('/run/systemd/system').is_dir():
                    properties=dict(line.split('=',1) for line in self.command(['show',name,'--property=LoadState']).splitlines() if '=' in line)
                    require(properties.get('LoadState')=='not-found', 'Foreign recovery service requires reviewed migration')
        if previous_fence is None:
            self.check_main_package_layout(manifest)
        self.initialize()
        with self.sender_locked(), self.gwt_locked() as gwt, self.recovery_locked(), self.locked():
            self.check_package_writers(allow_main=True)
            self.check_sender_admissions()
            if gwt is not None: gwt.check()
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
            if frozenset(manifest["files"]) in JOURNAL_ASSETS:
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
            if fence is not None and frozenset(manifest['files']) in JOURNAL_ASSETS:
                # The existing installer stops Main synchronously. Record its terminal
                # predecessor set under the package lock, never infer UNKNOWN from Main0.
                # A reinstall completes the retained remove fence under its original UUID.
                if self.path('/run/systemd/system').is_dir():
                    info=dict(line.split('=',1) for line in self.command(['show','kura.service','--property=ActiveState',
                        '--property=MainPID','--property=ControlPID']).splitlines() if '=' in line)
                    require(info.get('ActiveState') in ('inactive','failed') and info.get('MainPID')=='0'
                            and info.get('ControlPID')=='0','Core must be stopped before publishing package handoff')
                history=self.state/'package-history';self.directory(history,private=True,create=True)
                archives=archive_inventory(self)
                ids=sorted(path.name[:-5] for path in (self.state/'startups').iterdir()
                    if ('startups',path.name[:-5]) not in archives['archived'])
                prior=[]
                for path in history.iterdir():
                    require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                    record=validate_maintenance(decode(self.read(path)),path.name[:-5])
                    if record['maintenanceId']!=fence['id']:prior.append(record)
                require(len(ids)<=32 and active_journal_count(self,'package-history',
                    [row['maintenanceId'] for row in prior],inventory=archives)<128)
                parents={item['previousMaintenanceId'] for item in prior}
                heads=[item for item in prior if item['maintenanceId'] not in parents]
                require(len(heads)==(1 if prior else 0),'Package history head is ambiguous')
                previous=heads[0]['maintenanceId'] if heads else None
                home=self.path('/opt/eclipse/kura').resolve(strict=True)
                value=dict(schema=1,maintenanceId=fence['id'],firstAction=fence['firstAction'],
                    manifestSha256=hashlib.sha256(self.read(home/'libexec/key-backup/manifest.json',private=False)).hexdigest(),
                    keySha256=proof['keySha256'],precedingStartupIds=ids,previousMaintenanceId=previous)
                if archives['head'] is not None:
                    head=archives['head'];value.update(schema=2,precedingArchiveId=head,
                        precedingArchiveSha256=hashlib.sha256(encoded(archives['requests'][head][1])).hexdigest())
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
        elif sys.argv[1:] == ['--check-stopped-writers']:
            lifecycle.check_package_writers()
        elif sys.argv[1:] == ["--leave"]:
            lifecycle.leave()
        elif sys.argv[1:] == ["--remove-units"]:
            lifecycle.remove_units()
        elif len(sys.argv) == 3 and sys.argv[1] == '--retain-main-state':
            lifecycle.retain_main_state(sys.argv[2])
        elif sys.argv[1:] == ['--check-retained-main-state']:
            lifecycle.retained_main_state()
        elif sys.argv[1:] == ['--restore-retained-main-state']:
            lifecycle.retained_main_state(restore=True)
        elif sys.argv[1:] == ['--check-main-reboot-source']:
            lifecycle.check_main_reboot_source()
        elif len(sys.argv) == 3 and sys.argv[1] == '--package-main-restore-decision':
            print(lifecycle.package_main_restore_decision(sys.argv[2]))
        elif sys.argv[1:] == ['--check-main-reboot-permissions']:
            lifecycle.check_main_reboot_permissions()
        elif (len(sys.argv) > 1 and sys.argv[1] in ('--prepare-upgrade-copy', '--publish-upgrade-copy',
                                                   '--restore-upgrade-source', '--detach-upgrade-source')
              and '_KURA_EMBEDDED_UPGRADE_COPY_SOURCE' in globals()):
            namespace = {}
            exec(compile(_KURA_EMBEDDED_UPGRADE_COPY_SOURCE, '<incoming upgrade copy>', 'exec'), namespace)
            namespace['run_upgrade_copy'](sys.modules[__name__], lifecycle, sys.argv[1:],
                                          _KURA_EMBEDDED_UPGRADE_PAYLOAD)
        elif sys.argv[1:] == ['--migrate-linked-main'] and '_KURA_EMBEDDED_MAIN_LINK_MIGRATION_SOURCE' in globals():
            namespace = {}
            exec(compile(_KURA_EMBEDDED_MAIN_LINK_MIGRATION_SOURCE, '<incoming Main link migration>', 'exec'), namespace)
            namespace['migrate_linked_main'](lifecycle)
        else:
            raise Refused("Unsupported key-service package admission action")
    except ActiveWriter as error:
        sys.stderr.write(str(error) + '\n')
        sys.exit(1)
    except Exception:
        sys.stderr.write("Key-service package admission refused; retain keys, receipts, backups and installation\n")
        sys.exit(1)
