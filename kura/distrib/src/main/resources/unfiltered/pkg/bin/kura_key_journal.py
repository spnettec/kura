#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Paired Root metadata and owner-private journal readers. No key writer."""
import contextlib
import datetime
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import stat
import uuid

JOURNAL_READER_PROTOCOL = 1

_lifecycle_api=globals().pop('_kura_lifecycle_api')
LifecycleGwtSenderInventory = _lifecycle_api['GwtSenderInventory']
require = _lifecycle_api['require']
Refused = _lifecycle_api['Refused']
Unresolved = _lifecycle_api['Unresolved']
decode = _lifecycle_api['decode']
encoded = _lifecycle_api['encoded']
canonical_id = _lifecycle_api['canonical_id']
is_digest = _lifecycle_api['is_digest']
GWT_DATA_FIELDS = _lifecycle_api['GWT_DATA_FIELDS']
GWT_NAMESPACE_FIELDS = _lifecycle_api['GWT_NAMESPACE_FIELDS']
HANDOFF_IDS = _lifecycle_api['HANDOFF_IDS']
HANDOFF_BINDING = _lifecycle_api['HANDOFF_BINDING']
validate_handoff_binding = _lifecycle_api['validate_handoff_binding']
validate_handoff_retired = _lifecycle_api['validate_handoff_retired']
validate_sender_closed = _lifecycle_api['validate_sender_closed']
validate_receiver_pending = _lifecycle_api['validate_receiver_pending']
receiver_restore_intent = _lifecycle_api['receiver_restore_intent']
receiver_start_intent = _lifecycle_api['receiver_start_intent']
validate_start = _lifecycle_api['validate_start']
handoff_revocation_view = _lifecycle_api['handoff_revocation_view']
validate_record = _lifecycle_api['validate_record']
validate_gwt_intent = _lifecycle_api['validate_gwt_intent']
validate_handoff_authority = _lifecycle_api['validate_handoff_authority']
validate_sender_admission = _lifecycle_api['validate_sender_admission']
validate_sender_attempt = _lifecycle_api['validate_sender_attempt']
validate_gwt_closed = _lifecycle_api['validate_gwt_closed']
check_sender_attempt = _lifecycle_api['check_sender_attempt']
check_sender_original = _lifecycle_api['check_sender_original']
active_journal_count = _lifecycle_api['active_journal_count']
PRIVATE_FENCE_PURPOSE = _lifecycle_api['PRIVATE_FENCE_PURPOSE']
PRIVATE_FENCE_CONTEXT = _lifecycle_api['PRIVATE_FENCE_CONTEXT']
SENDER_ADMISSION_CONTEXT = _lifecycle_api['SENDER_ADMISSION_CONTEXT']
ARCHIVE_INTENT_CONTEXT = _lifecycle_api['ARCHIVE_INTENT_CONTEXT']
ARCHIVE_RECEIPT_CONTEXT = _lifecycle_api['ARCHIVE_RECEIPT_CONTEXT']
archive_references = _lifecycle_api['archive_references']
archive_entry = _lifecycle_api['archive_entry']
validate_gwt_data = _lifecycle_api['validate_gwt_data']
validate_gwt_binding = _lifecycle_api['validate_gwt_binding']
read_handoff_revocation = _lifecycle_api['read_handoff_revocation']
archive_inventory = _lifecycle_api['archive_inventory']
del _lifecycle_api


def archive_correlation(policy, reference, secret):
    """Public metadata only. Never return request tags, backup bodies or a bearer."""
    directory,identity=reference['directory'],reference['operationId']
    value=decode(policy.read(policy.state/directory/(identity+'.json'),65536))
    if directory=='handoffs':
        validate_handoff_authority(value,identity,secret)
        return dict(kind='HANDOFF',request=value['request'],outcome='REVOKED' if read_handoff_revocation(policy,identity,secret) is not None else 'COMPLETED')
    if directory=='sender-admissions':
        validate_sender_admission(value,identity,secret)
        return dict(kind='PRIVATE_FENCE' if value['purpose']==PRIVATE_FENCE_PURPOSE else 'ADMISSION',source=value['source'],
            actorUid=value['owner']['uid'],target={k:value['target'][k] for k in ('directory','operationId','action','continuation')},
            outcome='NOT_ADMITTED' if value['state']=='NOT_ADMITTED' else 'COMPLETED')
    if directory=='operations':
        validate_record(value,identity);response=value['response'];action=value['action'];binding={}
        if action=='restore':binding['expectedKeySha256']=response['keySha256']
        elif action=='generation-prepare':binding['expectedSource']=response['source']
        elif action=='generation-backup-verify':binding=dict(preparationId=response['preparationId'],
            expectedRingSha256=response['ringSha256'],backupSha256=response['backupSha256'])
        return dict(kind='OPERATION',action=action,binding=binding,outcome='COMPLETED',responseSha256=hashlib.sha256(encoded(response)).hexdigest())
    return dict(kind='ROOT_RECORD',outcome='COMPLETED')


def archive_reference_read(manager,request,pid,uid,daemon,recovery):
    from kura_key_service import require, fields, Failure
    receiver=request['action']=='journal-archive-recovery-reference-read'
    fields(request,{'schema','action','namespaceSha256','directory','operationId'} |
        ({'attempt'} if receiver and request.get('directory')=='sender-admissions' else set()))
    require(type(request['schema']) is int and request['schema']==1)
    if receiver:require(recovery is not None and uid in (0,recovery),'FORBIDDEN')
    if uid==0:pass
    elif uid==daemon:manager.gwt_sender_owner(pid,uid,daemon)
    else:
        require(recovery is not None and uid==recovery,'FORBIDDEN');manager.recovery_sender_owner(pid,uid)
    try:reference=archive_references([{k:request[k] for k in ('directory','operationId')}])[0]
    except Refused:raise Failure('INVALID_ARGUMENT') from None
    with manager.sender_admissions.locked(),manager.lock(manager.state/'admission.lock',False):
        manager.maintenance();namespace=manager.gwt_namespace()['namespaceSha256'];require(request['namespaceSha256']==namespace,'CONFLICT')
        inventory=manager.archives();secret=manager.sender_admissions.secret()
        try:entry=archive_entry(manager,reference,secret,inventory=inventory)
        except (Refused,FileNotFoundError):raise Failure('ARCHIVE_UNSETTLED') from None
        key=(reference['directory'],reference['operationId']);owner=inventory['owners'].get(key)
        if owner is None:
            owner=next((identity for identity,(intent,_) in inventory['requests'].items()
                if any((row['directory'],row['operationId'])==key for row in intent['entries'])),None)
        proof=manager.archive_view(owner,*inventory['requests'][owner]) if owner else None
        allowed=False
        if owner is not None:
            intent=inventory['requests'][owner][0]
            allowed=uid==0 or intent['actorUid']==uid and intent['source']==('gwt' if uid==daemon else 'recovery')
        try:correlation=recovery_archive_correlation(manager,reference,secret,request.get('attempt'),recovery) if receiver else archive_correlation(manager,reference,secret)
        except (Refused,FileNotFoundError):raise Failure('ARCHIVE_UNSETTLED') from None
        return dict(schema=1,state='ARCHIVABLE' if proof is None else proof['state'],namespaceSha256=namespace,
            entry=entry,correlation=correlation,archive=proof,continuationAllowed=allowed,
            credentialsChanged=False,startRequested=False)


def recovery_archive_correlation(policy,reference,secret,attempt,uid):
    """Receiver-specific public metadata; no bearer, backup, passphrase or request tag."""
    directory,identity=reference['directory'],reference['operationId']
    value=decode(policy.read(policy.state/directory/(identity+'.json'),65536))
    if directory=='sender-admissions':
        require(attempt is not None)
        check_sender_attempt(policy,attempt,dict(schema=1,namespaceSha256=value['namespaceSha256']),'recovery',uid)
        require(attempt['admissionId']==identity)
        if attempt['kind'] in ('publish','continue','handoff-start','handoff-renewal'):
            request=attempt['request'];path=policy.state/'handoffs'/(request['handoffId']+'.json')
            raw=policy.read(path,8192);grant=validate_handoff_authority(decode(raw),request['handoffId'],secret)
            require(raw==encoded(grant) and stat.S_IMODE(path.lstat().st_mode)==0o400)
            key='startOperationId' if attempt['kind']=='handoff-start' else 'publicationId'
            if attempt['kind']!='handoff-renewal':require(attempt['nativeOperationId']==grant['request'][key])
            require(value['target']['action']==('generation-start-lease' if attempt['kind']=='handoff-renewal'
                else 'generation-core-start' if attempt['kind']=='handoff-start' else 'generation-publish')
                and value['target']['continuation']==(attempt['kind']=='continue'))
        return dict(archive_correlation(policy,reference,secret),attemptSha256=hashlib.sha256(encoded(attempt)).hexdigest())
    require(attempt is None)
    if directory=='operations':return archive_correlation(policy,reference,secret)
    if directory=='startups':
        validate_start(value,identity)
        intent=dict(schema=value['schema'],operationId=identity,restoreOperationId=value['restoreOperationId'],expectedKeySha256=value['keySha256'])
        if value['schema']==2:intent.update({k:value[k] for k in ('predecessorStartOperationId','maintenanceId','manifestSha256')})
        return dict(kind='STARTUP',intent=intent,outcome='COMPLETED')
    require(directory=='handoffs');validate_handoff_authority(value,identity,secret);request=value['request']
    binding={k:request[k] for k in HANDOFF_IDS};binding.update(schema=1,operator=request['operator'],historySha256=value['historySha256'],
        ringSha256=request['expectedRingSha256'],cohortSha256=request['expectedCohortSha256'])
    revoked=read_handoff_revocation(policy,identity,secret)
    if revoked is not None:return dict(kind='HANDOFF',binding=binding,outcome='REVOKED',terminal=handoff_revocation_view(revoked))
    published=validate_record(decode(policy.read(policy.state/'operations'/(request['publicationId']+'.json'))),request['publicationId'])['response']
    started=validate_record(decode(policy.read(policy.state/'operations'/(request['startOperationId']+'.json'))),request['startOperationId'])['response']
    return dict(kind='HANDOFF',binding=binding,outcome='COMPLETED',terminal=dict(binding,state='ORIGINAL_REQUESTS_CONFIRMED',
        publicationSha256=published['publicationSha256'],jobPath=started['jobPath']))

class RecoveryPrivateFormat:
    """One private format shared by the receiver UID and the independent package reader."""
    PURPOSE='yofc.kura.recovery-private-archive.v1'
    KINDS=frozenset(('RESTORE','START','HANDOFF','ADMISSION'))
    STEPS=frozenset(('restore','start','publish','continue','handoff-start','handoff-renewal'))

    def __init__(self,state,uid,gid,read,directory):
        self.state,self.uid,self.gid,self._read,self._directory=state,uid,gid,read,directory

    def directory(self,path):
        self._directory(path);require(path.lstat().st_gid==self.gid)

    def read(self,path,limit):
        self.directory(path.parent);raw=self._read(path,limit);m=path.lstat()
        require(m.st_uid==self.uid and m.st_gid==self.gid and m.st_nlink==1 and stat.S_IMODE(m.st_mode)==0o600)
        return raw

    def selector(self,kind,identity,step=None):
        require(kind in self.KINDS and canonical_id(identity))
        require(step in self.STEPS if kind=='ADMISSION' else step is None)
        return kind+'-'+identity+('-'+step if step is not None else '')

    def path(self,kind,identity,step=None):return self.state/'archives'/(self.selector(kind,identity,step)+'.json')

    def binding(self,namespace):
        require(isinstance(namespace,dict) and set(namespace)=={'schema','namespaceSha256','rootDevice','rootInode'}
            and type(namespace['schema']) is int and namespace['schema']==1 and is_digest(namespace['namespaceSha256']))
        for name in ('rootDevice','rootInode'):
            require(isinstance(namespace[name],str) and namespace[name].isascii() and namespace[name].isdecimal()
                and str(int(namespace[name]))==namespace[name] and len(namespace[name])<=20)
        require(int(namespace['rootInode'])>0)
        self.directory(self.state);m=self.state.lstat()
        return dict(namespace,privateDevice=str(m.st_dev),privateInode=str(m.st_ino),privateUid=self.uid,privateGid=self.gid)

    def admission(self,identity,step):
        slot=self.state/'admissions'/(identity+'-'+step);self.directory(slot.parent);self.directory(slot)
        names={p.name for p in slot.iterdir()}
        require(names in ({'intent.json','namespace.json'},{'intent.json','namespace.json','closed.json'})
            or step=='restore' and names=={'intent.json','namespace.json','closed.json','pending.json'})
        attempt=validate_sender_attempt(decode(self.read(slot/'intent.json',12288)),'recovery')
        require(attempt['kind']==step and attempt['nativeOperationId']==identity)
        namespace=decode(self.read(slot/'namespace.json',4096))
        require(set(namespace)=={'schema','namespaceSha256'} and type(namespace['schema']) is int
            and namespace['schema']==1 and is_digest(namespace['namespaceSha256']))
        if 'closed.json' in names:validate_sender_closed(decode(self.read(slot/'closed.json',4096)),attempt,namespace)
        if 'pending.json' in names:validate_receiver_pending(decode(self.read(slot/'pending.json',4096)),attempt)
        return dict(attempt=attempt,namespace=namespace,names=names,paths=[slot/name for name in sorted(names)])

    def snapshot(self,kind,identity,step=None):
        self.selector(kind,identity,step);attempt=None;namespace=None;closed=False;terminal=None
        if kind=='ADMISSION':
            sender=self.admission(identity,step);attempt=sender['attempt'];namespace=sender['namespace']
            paths=sender['paths'];metadata=attempt['request'];closed='closed.json' in sender['names']
            reference=dict(directory='sender-admissions',operationId=attempt['admissionId'])
        elif kind in ('RESTORE','START'):
            path=self.state/('operations' if kind=='RESTORE' else 'starts')/(identity+'.json');self.directory(path.parent)
            metadata=decode(self.read(path,4096));paths=[path]
            if kind=='RESTORE':
                require(set(metadata)=={'schema','operationId','expectedKeySha256','backupSha256'} and metadata['schema']==1
                    and type(metadata['schema']) is int and all(is_digest(metadata[k]) for k in ('expectedKeySha256','backupSha256')))
            else:
                require(type(metadata.get('schema')) is int and metadata['schema'] in (1,2))
                extra={'predecessorStartOperationId','maintenanceId','manifestSha256'} if metadata['schema']==2 else set()
                require(set(metadata)=={'schema','operationId','restoreOperationId','expectedKeySha256'}|extra
                    and canonical_id(metadata['restoreOperationId']) and is_digest(metadata['expectedKeySha256']))
                if extra:require(canonical_id(metadata['predecessorStartOperationId']) and canonical_id(metadata['maintenanceId']) and is_digest(metadata['manifestSha256']))
            require(metadata['operationId']==identity)
            name='restore' if kind=='RESTORE' else 'start';slot=self.state/'admissions'/(identity+'-'+name)
            if os.path.lexists(slot/'closed.json'):
                sender=self.admission(identity,name);attempt=sender['attempt'];namespace=sender['namespace'];closed=True
                require(metadata==(receiver_restore_intent(attempt) if kind=='RESTORE' else receiver_start_intent(attempt)))
                if kind=='RESTORE':self.retired_restore(identity,sender)
                reference=dict(directory='sender-admissions',operationId=attempt['admissionId'])
            else:reference=dict(directory='operations' if kind=='RESTORE' else 'startups',operationId=identity)
        else:
            slot=self.state/'handoffs'/identity;self.directory(slot.parent);self.directory(slot)
            names={p.name for p in slot.iterdir()}
            require('binding.json' in names and len(names&{'completed.json','retired.json'})==1
                and names<={'binding.json','publish.json','continue.json','start.json','completed.json','retired.json'})
            metadata=decode(self.read(slot/'binding.json',8192));validate_handoff_binding(metadata);require(metadata['handoffId']==identity)
            for command in ('publish','continue','start'):
                if command+'.json' not in names:continue
                value=decode(self.read(slot/(command+'.json'),8192));extra={'expectedRecoveryReceiptSha256'} if command=='continue' else set()
                require(set(value)==HANDOFF_BINDING|{'command'}|extra and value['command']==command
                    and {k:value[k] for k in HANDOFF_BINDING}==metadata)
                if extra:require(is_digest(value['expectedRecoveryReceiptSha256']))
            terminal=decode(self.read(slot/('retired.json' if 'retired.json' in names else 'completed.json'),8192))
            if 'retired.json' in names:
                validate_handoff_retired(terminal,metadata);require('continue.json' not in names)
            else:
                require(set(terminal)==HANDOFF_BINDING|{'state','publicationSha256','jobPath'}
                    and {k:terminal[k] for k in HANDOFF_BINDING}==metadata and terminal['state']=='ORIGINAL_REQUESTS_CONFIRMED'
                    and is_digest(terminal['publicationSha256']))
            paths=[slot/name for name in sorted(names)];reference=dict(directory='handoffs',operationId=identity)
        files={str(path.relative_to(self.state)):hashlib.sha256(self.read(path,12288)).hexdigest() for path in paths}
        return dict(files=files,metadata=metadata,attempt=attempt,namespace=namespace,closed=closed,terminal=terminal,reference=reference)

    def retired_restore(self,identity,sender):
        require('closed.json' in sender['names'] and 'pending.json' in sender['names'],
            'Retire the original receiver pending marker before archiving its negative admission')
        if os.path.lexists(self.state/'pending.json'):
            require(decode(self.read(self.state/'pending.json',4096))['operationId']!=identity)

    def correlate(self,kind,identity,step,snapshot,correlation,binding):
        metadata=snapshot['metadata'];reference=snapshot['reference'];require(isinstance(correlation,dict))
        if reference['directory']=='sender-admissions':
            require(set(correlation)=={'kind','source','actorUid','target','outcome','attemptSha256'})
            attempt=snapshot['attempt'];name=attempt['kind'];request=attempt['request']
            require(correlation['kind']=='ADMISSION' and correlation['source']=='recovery' and type(correlation['actorUid']) is int
                and correlation['actorUid']==self.uid and snapshot['namespace']==dict(schema=1,namespaceSha256=binding['namespaceSha256'])
                and correlation['attemptSha256']==hashlib.sha256(encoded(attempt)).hexdigest()
                and correlation['outcome'] in ('COMPLETED','NOT_ADMITTED'))
            action='generation-start-lease' if name=='handoff-renewal' else 'generation-core-start' if name=='handoff-start' else 'generation-publish' if name in ('publish','continue') else request['action']
            require(correlation['target']==dict(directory='startups' if name=='start' else 'operations',operationId=identity,action=action,continuation=name=='continue'))
            if snapshot['closed']:require(correlation['outcome']=='NOT_ADMITTED')
            if kind!='ADMISSION':require(correlation['outcome']=='NOT_ADMITTED' and snapshot['closed'])
            elif correlation['outcome']=='NOT_ADMITTED':
                if name in ('restore','start'):
                    owning=self.state/('operations' if name=='restore' else 'starts')/(identity+'.json')
                    if os.path.lexists(owning):
                        require(snapshot['closed'],'Close the original receiver attempt before archiving it')
                        if name=='restore':self.retired_restore(identity,self.admission(identity,name))
            return
        if kind=='RESTORE':
            require(set(correlation)=={'kind','action','binding','outcome','responseSha256'} and correlation['kind']=='OPERATION'
                and correlation['action']=='restore' and correlation['outcome']=='COMPLETED'
                and correlation['binding']==dict(expectedKeySha256=metadata['expectedKeySha256']) and is_digest(correlation['responseSha256']))
        elif kind=='START':require(correlation==dict(kind='STARTUP',intent=metadata,outcome='COMPLETED'))
        else:require(kind=='HANDOFF' and set(correlation)=={'kind','binding','outcome','terminal'} and correlation['kind']=='HANDOFF'
            and correlation['binding']==metadata and correlation['terminal']==snapshot['terminal']
            and correlation['outcome']==('REVOKED' if snapshot['terminal'].get('state')!='ORIGINAL_REQUESTS_CONFIRMED' else 'COMPLETED'))

    def marker(self,kind,identity,step,binding):
        value=decode(self.read(self.path(kind,identity,step),65536))
        require(set(value)=={'schema','purpose','kind','operationId','senderKind','binding','privateFiles','reference','entrySha256','request','continuationAllowed'}
            and type(value['schema']) is int and value['schema']==1 and value['purpose']==self.PURPOSE and value['kind']==kind
            and value['operationId']==identity and value['senderKind']==step and value['binding']==binding
            and type(value['continuationAllowed']) is bool and is_digest(value['entrySha256']))
        snapshot=self.snapshot(kind,identity,step)
        require(value['privateFiles']==snapshot['files'] and value['reference']==snapshot['reference'],'Receiver archive original bytes changed')
        request=value['request'];require(isinstance(request,dict) and set(request)=={'schema','action','archiveId','namespaceSha256','entries','expectedEntriesSha256'}
            and type(request['schema']) is int and request['schema']==1 and request['action']=='journal-archive' and canonical_id(request['archiveId'])
            and request['namespaceSha256']==binding['namespaceSha256'] and is_digest(request['expectedEntriesSha256']))
        refs=archive_references(request['entries']);require(refs==request['entries'] and snapshot['reference'] in refs)
        return value,snapshot

    def inventory(self,policy,namespace):
        parent=self.state/'archives';result=set()
        if not os.path.lexists(parent):return result
        self.directory(parent);binding=self.binding(namespace);inventory=archive_inventory(policy);secret=policy.read(policy.state/'journal.key',32)
        for path in parent.iterdir():
            name=path.name;require(name.endswith('.json'));parts=name[:-5].split('-',1);require(len(parts)==2 and parts[0] in self.KINDS)
            kind,tail=parts;identity=tail[:36];step=tail[37:] if len(tail)>36 else None
            require(name==self.path(kind,identity,step).name)
            marker,snapshot=self.marker(kind,identity,step,binding);reference=snapshot['reference']
            entry=archive_entry(policy,reference,secret,inventory=inventory);require(entry['sha256']==marker['entrySha256'])
            self.correlate(kind,identity,step,snapshot,recovery_archive_correlation(policy,reference,secret,snapshot['attempt'],self.uid),binding)
            request=marker['request'];original=inventory['requests'].get(request['archiveId'])
            if original is None:continue
            intent,receipt=original
            require(intent['requestTag']==hmac.new(secret,encoded(request),hashlib.sha256).hexdigest()
                and intent['entriesSha256']==request['expectedEntriesSha256']
                and [{k:row[k] for k in ('directory','operationId')} for row in intent['entries']]==request['entries'])
            if receipt is not None:result.add((kind,identity,step))
        return result


class RecoveryPrivateArchive:
    """Receiver-owned metadata only. Caller holds the receiver journal lock."""
    def __init__(self,journal,client):
        self.journal,self.client=journal,client;self.state=journal.directory
        self.format=RecoveryPrivateFormat(self.state,journal.owner,self.state.lstat().st_gid,journal.read,journal.check_directory)

    def call(self,request):
        result=self.client(request)
        require(isinstance(result,dict) and type(result.get('schema')) is int and result['schema']==1 and 'error' not in result,
            'Receiver archive original is unavailable')
        return result

    def lookup(self,snapshot,binding):
        request=dict(schema=1,action='journal-archive-recovery-reference-read',namespaceSha256=binding['namespaceSha256'],**snapshot['reference'])
        if snapshot['attempt'] is not None:request['attempt']=snapshot['attempt']
        result=self.call(request)
        require(set(result)=={'schema','state','namespaceSha256','entry','correlation','archive','continuationAllowed','credentialsChanged','startRequested'}
            and result['namespaceSha256']==binding['namespaceSha256'] and result['state'] in ('ARCHIVABLE','ARCHIVE_RECORDED','UNKNOWN')
            and type(result['continuationAllowed']) is bool and result['credentialsChanged'] is False and result['startRequested'] is False)
        entry=result['entry'];require(isinstance(entry,dict) and set(entry)=={'directory','operationId','sha256'}
            and {k:entry[k] for k in snapshot['reference']}==snapshot['reference'] and is_digest(entry['sha256']))
        require(result['archive'] is not None or result['continuationAllowed'] is False)
        return result

    def request_from_view(self,proof,binding):
        base={'schema','archiveId','namespaceSha256','state','scope','entries','entriesSha256','intentSha256','originalsRetained','credentialsChanged','startRequested'}
        require(isinstance(proof,dict) and set(proof)==base|({'receiptSha256'} if proof.get('state')=='ARCHIVE_RECORDED' else set())
            and type(proof['schema']) is int and proof['schema']==1 and canonical_id(proof['archiveId'])
            and proof['namespaceSha256']==binding['namespaceSha256'] and proof['state'] in ('ARCHIVE_RECORDED','UNKNOWN')
            and proof['scope']=='ROOT_JOURNAL_ACTIVE_CAPACITY_ONLY' and proof['originalsRetained'] is True
            and proof['credentialsChanged'] is False and proof['startRequested'] is False
            and all(is_digest(proof[k]) for k in ('entriesSha256','intentSha256')))
        if proof['state']=='ARCHIVE_RECORDED':require(is_digest(proof['receiptSha256']))
        entries=proof['entries'];require(isinstance(entries,list) and 1<=len(entries)<=128)
        refs=[]
        for entry in entries:
            require(isinstance(entry,dict) and set(entry)=={'directory','operationId','sha256'} and is_digest(entry['sha256']))
            refs.append({k:entry[k] for k in ('directory','operationId')})
        require(refs==archive_references(refs) and hashlib.sha256(encoded(entries)).hexdigest()==proof['entriesSha256'])
        return dict(schema=1,action='journal-archive',archiveId=proof['archiveId'],namespaceSha256=binding['namespaceSha256'],entries=refs,expectedEntriesSha256=proof['entriesSha256'])

    def check(self,kind,identity,step,marker,snapshot,binding):
        observed=self.lookup(snapshot,binding);self.format.correlate(kind,identity,step,snapshot,observed['correlation'],binding)
        require(marker['entrySha256']==observed['entry']['sha256'])
        if observed['archive'] is not None:
            require(observed['state']==observed['archive']['state'] and observed['entry'] in observed['archive']['entries']
                and marker['request']==self.request_from_view(observed['archive'],binding))
        else:require(observed['state']=='ARCHIVABLE')
        return observed

    def list(self,cursor=None,*,handoff_id=None):
        require(cursor is None or isinstance(cursor,str) and len(cursor)<=80)
        def selector(row):return row['kind']+':'+row['operationId']+(':'+row['senderKind'] if row['senderKind'] else '')
        if cursor:
            parts=cursor.split(':');require(len(parts) in (2,3));self.format.selector(parts[0],parts[1],parts[2] if len(parts)==3 else None)
        rows=[];self.format.directory(self.state)
        for kind,name in (('RESTORE','operations'),('START','starts'),('HANDOFF','handoffs'),('ADMISSION','admissions')):
            if (kind in ('RESTORE','START')) and handoff_id is not None or kind=='HANDOFF' and handoff_id is None:continue
            parent=self.state/name
            if not os.path.lexists(parent):continue
            self.format.directory(parent)
            for path in parent.iterdir():
                step=None;name=path.name
                if kind in ('RESTORE','START'):
                    require(name.endswith('.json'));identity=name[:-5];self.format.selector(kind,identity)
                    self.format.snapshot(kind,identity)
                elif kind=='HANDOFF':
                    identity=name;self.format.selector(kind,identity);self.format.directory(path)
                    metadata=decode(self.format.read(path/'binding.json',8192));validate_handoff_binding(metadata);require(metadata['handoffId']==identity)
                    if identity!=handoff_id:continue
                else:
                    require(len(name)>37 and name[36]=='-');identity,step=name[:36],name[37:];self.format.selector(kind,identity,step)
                    if (step in ('restore','start'))!=(handoff_id is None):continue
                    metadata=self.format.admission(identity,step)['attempt']['request']
                    if handoff_id is not None and metadata.get('handoffId')!=handoff_id:continue
                row=dict(kind=kind,operationId=identity,senderKind=step)
                if cursor and selector(row)<=cursor:continue
                rows.append(row);rows.sort(key=selector)
                if len(rows)>21:rows.pop()
        more=len(rows)>20
        if more:rows.pop()
        return dict(schema=1,state='ARCHIVE_HISTORY',records=rows,nextCursor=selector(rows[-1]) if more else None)

    def review(self,kind,identity,step=None):
        snapshot=self.format.snapshot(kind,identity,step);path=self.format.path(kind,identity,step);marker=None
        if os.path.lexists(path):
            saved=decode(self.format.read(path,65536));namespace=saved['binding']
            binding=self.format.binding({key:namespace[key] for key in ('schema','namespaceSha256','rootDevice','rootInode')})
            marker,snapshot=self.format.marker(kind,identity,step,binding)
        view=dict(schema=1,kind=kind,operationId=identity,senderKind=step,state='UNAVAILABLE',privateAttempt=marker is not None,
            archiveId=marker['request']['archiveId'] if marker else None,reviewSha256=None,archiveAllowed=False,continueAllowed=False,archived=False)
        try:
            binding=self.format.binding(self.call(dict(schema=1,action='gwt-sender-namespace')))
            if marker is not None:
                require(marker['binding']==binding);observed=self.check(kind,identity,step,marker,snapshot,binding)
            else:
                observed=self.lookup(snapshot,binding);self.format.correlate(kind,identity,step,snapshot,observed['correlation'],binding)
            proof=observed['archive']
            if proof is not None:
                self.request_from_view(proof,binding)
                require(observed['state']==proof['state'] and observed['entry'] in proof['entries'])
                if marker is None:view['archiveId']=proof['archiveId']
            done=observed['state']=='ARCHIVE_RECORDED'
            view.update(state='UNKNOWN' if marker and proof is None else observed['state'],
                archiveAllowed=marker is None and (observed['state']!='UNKNOWN' or observed['continuationAllowed']),
                continueAllowed=marker is not None and not done and proof is not None and marker['continuationAllowed'] and observed['continuationAllowed'],
                archived=marker is not None and done)
            fingerprint=dict(kind=kind,operationId=identity,senderKind=step,privateFiles=snapshot['files'],binding=binding,observed=observed,localIntent=marker)
            view['reviewSha256']=hashlib.sha256(encoded(fingerprint)).hexdigest()
        except Exception:
            view.update(state='UNAVAILABLE',reviewSha256=None,archiveAllowed=False,continueAllowed=False,archived=False)
        return view

    def confirm(self,kind,identity,step,expected,*,continue_metadata=False):
        require(is_digest(expected));view=self.review(kind,identity,step)
        if view['archived']:return view
        if expected!=view['reviewSha256']:
            view.update(error='STALE_REVIEW',archiveAllowed=False,continueAllowed=False);return view
        if not view['continueAllowed' if continue_metadata else 'archiveAllowed']:
            view.update(error='ARCHIVE_NOT_ALLOWED',archiveAllowed=False,continueAllowed=False);return view
        try:self.archive(kind,identity,step,continue_metadata=continue_metadata)
        except Exception:
            # One original metadata dispatch only. A missing reply can authorize reads, never a late first send.
            result=self.review(kind,identity,step)
            if not result['archived']:result['error']='ARCHIVE_UNCONFIRMED' if result['privateAttempt'] else 'ARCHIVE_PREFLIGHT_REFUSED'
            return result
        return self.review(kind,identity,step)

    def archive(self,kind,identity,step=None,*,preview=False,continue_metadata=False):
        path=self.format.path(kind,identity,step);binding=self.format.binding(self.call(dict(schema=1,action='gwt-sender-namespace')))
        if os.path.lexists(path):
            marker,snapshot=self.format.marker(kind,identity,step,binding);observed=self.check(kind,identity,step,marker,snapshot,binding)
            if continue_metadata and observed['state']!='ARCHIVE_RECORDED':
                require(not preview and marker['continuationAllowed'] and observed['continuationAllowed'] and observed['archive'] is not None,
                    'Only an existing original metadata archive can be continued')
                self.call(dict(marker['request'],action='journal-archive-continue'))
                observed=self.check(kind,identity,step,marker,snapshot,binding)
            return observed
        require(not continue_metadata,'No original private archive intent')
        snapshot=self.format.snapshot(kind,identity,step);observed=self.lookup(snapshot,binding)
        self.format.correlate(kind,identity,step,snapshot,observed['correlation'],binding)
        if preview:return observed
        if observed['archive'] is not None:
            request=self.request_from_view(observed['archive'],binding);allowed=observed['continuationAllowed']
        else:
            plan=self.call(dict(schema=1,action='journal-archive-plan',namespaceSha256=binding['namespaceSha256'],entries=[snapshot['reference']]))
            require(set(plan)=={'schema','state','namespaceSha256','entries','entriesSha256','originalsRetained','credentialsChanged','startRequested'}
                and plan['state']=='ARCHIVE_PLAN' and plan['namespaceSha256']==binding['namespaceSha256'] and plan['entries']==[observed['entry']]
                and plan['entriesSha256']==hashlib.sha256(encoded(plan['entries'])).hexdigest() and plan['originalsRetained'] is True
                and plan['credentialsChanged'] is False and plan['startRequested'] is False)
            request=dict(schema=1,action='journal-archive',archiveId=str(uuid.uuid4()),namespaceSha256=binding['namespaceSha256'],entries=[snapshot['reference']],expectedEntriesSha256=plan['entriesSha256']);allowed=True
        marker=dict(schema=1,purpose=self.format.PURPOSE,kind=kind,operationId=identity,senderKind=step,binding=binding,
            privateFiles=snapshot['files'],reference=snapshot['reference'],entrySha256=observed['entry']['sha256'],request=request,continuationAllowed=allowed)
        if not os.path.lexists(path.parent):path.parent.mkdir(mode=0o700);self.journal.sync(self.state)
        self.format.directory(path.parent);self.journal.write_new(path,marker)
        require(self.format.snapshot(kind,identity,step)['files']==snapshot['files'])
        if observed['archive'] is None:self.call(request)
        return self.check(kind,identity,step,marker,snapshot,binding)

    def archived(self,kind,identity,step=None):
        if not os.path.lexists(self.format.path(kind,identity,step)):return False
        return self.archive(kind,identity,step,preview=True)['state']=='ARCHIVE_RECORDED'


class GwtSenderInventory:
    """Full-privilege package reader only; the no-capability Root daemon never uses it."""
    JOURNALS = LifecycleGwtSenderInventory.JOURNALS

    def __init__(self, policy, binding):
        self.policy, self.binding = policy, validate_gwt_binding(binding)
        self.closed = {}
        self.data = policy.path(binding['dataDirectory'])
        require(self.data.resolve(strict=True) == self.data, 'Effective Core data directory moved or aliased')
        m = self.data.lstat()
        require(stat.S_ISDIR(m.st_mode) and m.st_uid == binding['dataUid'] and not m.st_mode & 0o022
            and str(m.st_dev) == binding['dataDevice'] and str(m.st_ino) == binding['dataInode'],
            'Effective Core data directory changed; preserve its original sender journals')

    def directory(self, path):
        m = path.lstat()
        require(stat.S_ISDIR(m.st_mode) and m.st_uid == self.binding['dataUid'] and stat.S_IMODE(m.st_mode) == 0o700)

    def info(self, path, limit):
        m = path.lstat()
        require(stat.S_ISREG(m.st_mode) and m.st_uid == self.binding['dataUid'] and m.st_nlink == 1
            and stat.S_IMODE(m.st_mode) == 0o600 and m.st_size <= limit)
        return m

    identity = staticmethod(LifecycleGwtSenderInventory.identity)

    def read(self, path, limit):
        before = self.info(path, limit)
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            require(self.identity(before) == self.identity(os.fstat(fd)))
            chunks = bytearray()
            while len(chunks) <= limit:
                block = os.read(fd, min(65536, limit + 1 - len(chunks)))
                if not block: break
                chunks.extend(block)
            require(len(chunks) == before.st_size and self.identity(before) == self.identity(os.fstat(fd))
                == self.identity(self.info(path, limit)))
            return bytes(chunks)
        finally: os.close(fd)

    @contextlib.contextmanager
    def lock(self, path):
        before = self.info(path, 0)
        fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            require(self.identity(before) == self.identity(os.fstat(fd)))
            try: fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise Refused('GWT key sender is active; package change refused') from None
            # POSIX fcntl locks match Java FileLock. Do not open/close a second FD for this inode.
            require(self.identity(before) == self.identity(path.lstat()))
            yield
        finally: os.close(fd)

    @contextlib.contextmanager
    def locked(self):
        with contextlib.ExitStack() as locks:
            locks.enter_context(self.lock(self.data / '.gateway-key-admission.lock'))
            for directory, lock, _ in self.JOURNALS.values():
                parent = self.data / directory
                if os.path.lexists(parent):
                    self.directory(parent); locks.enter_context(self.lock(parent / lock))
            yield self

    def original(self, identity, intent):
        path = self.policy.state / 'operations' / (identity + '.json')
        root = validate_record(decode(self.policy.read(path)), identity)
        require(root['state'] == 'SUCCEEDED' and root['action'] == intent['action'],
            'Unresolved GWT key operation; retain its original UUID')
        result = root['response']
        if intent['action'] == 'restore': require(result['keySha256'] == intent['expectedKeySha256'])
        elif intent['action'] == 'generation-prepare': require(result['source'] == intent['expectedSource'])
        elif intent['action'] == 'generation-backup-verify':
            require(result['preparationId'] == intent['preparationId'] and result['ringSha256'] == intent['expectedRingSha256']
                and result['backupSha256'] == intent['backupSha256'])
        return root

    def legacy(self, slot):
        self.directory(slot); names = {p.name for p in slot.iterdir()}
        require({'request.json', 'request-complete'} <= names <=
            {'request.json', 'request-complete', 'submitted', 'result.json', 'result-complete'})
        raw = self.read(slot/'request.json', 4096); digest = hashlib.sha256(raw).hexdigest().encode('ascii') + b'\n'
        require(self.read(slot/'request-complete', 65) == digest)
        intent = decode(raw); require(intent.pop('schema', None) == 'yofc.kura.gateway-key.request.v1')
        created = intent.pop('createdAtUnixMs', None)
        require(type(created) is int and 0 < created <= 0x7fffffffffffffff)
        intent['schema'] = 1; require(validate_gwt_intent('LEGACY', intent) == slot.name)
        if 'submitted' in names: require(self.read(slot/'submitted', 65) == digest)
        local = None
        if {'result.json', 'result-complete'} & names:
            saved = self.read(slot/'result.json', 65536)
            require(self.read(slot/'result-complete', 65) == hashlib.sha256(saved).hexdigest().encode('ascii') + b'\n')
            document = decode(saved)
            require(set(document) == {'schema', 'requestSha256', 'result'}
                and document['schema'] == 'yofc.kura.gateway-key.result.v1' and document['requestSha256'] == digest.decode().strip())
            local = document['result']; require(isinstance(local, dict) and local.get('operationId') == slot.name
                and local.get('action') == intent['action'])
        if slot.name in self.closed:
            kind, original = self.closed[slot.name]
            require(kind == 'LEGACY' and original == intent)
            if local is not None:
                require(local.get('state') == 'REJECTED' and local.get('resultSource') in ('SERVER_PREFLIGHT','ROOT_PREFLIGHT')
                    and set(local) in ({'operationId','action','state','resultSource','error'},
                        {'operationId','action','state','resultSource','error','blockingOperationId'})
                    and isinstance(local.get('error'), str))
                if local['resultSource'] == 'SERVER_PREFLIGHT':
                    require(local['error'] in {'INVALID_ARGUMENT','UNAVAILABLE','BUSY','UNRESOLVED_OPERATION'})
                if 'blockingOperationId' in local:
                    require(local['resultSource'] == 'SERVER_PREFLIGHT' and local['error'] == 'UNRESOLVED_OPERATION'
                        and canonical_id(local['blockingOperationId']))
            self.absent(slot.name)
            return slot.name
        if local is not None and local.get('state') == 'REJECTED' and local.get('resultSource') == 'SERVER_PREFLIGHT':
            require(set(local) in ({'operationId', 'action', 'state', 'resultSource', 'error'},
                {'operationId', 'action', 'state', 'resultSource', 'error', 'blockingOperationId'}))
            require(local['error'] in {'INVALID_ARGUMENT', 'UNAVAILABLE', 'BUSY', 'UNRESOLVED_OPERATION'})
            if 'blockingOperationId' in local:
                require(local['error'] == 'UNRESOLVED_OPERATION' and canonical_id(local['blockingOperationId']))
            self.absent(slot.name)
        else:
            self.original(slot.name, intent)
            if local is not None and local.get('resultSource') == 'ROOT_ORIGINAL':
                require(set(local) == {'operationId', 'action', 'state', 'resultSource', 'original'}
                    and local['state'] == 'SUCCEEDED' and local['original'] == self.original(slot.name, intent)['response'])
            elif local is not None:
                # Historical ROOT_PREFLIGHT is not proof. Even with a matching Root success,
                # preserve and refuse an unrecognised or malformed cached result.
                require(local.get('state') == 'REJECTED' and local.get('resultSource') == 'ROOT_PREFLIGHT'
                    and set(local) == {'operationId', 'action', 'state', 'resultSource', 'error'})
        return slot.name

    def absent(self, identity):
        for directory in ('operations', 'startups', 'handoffs'):
            require(not os.path.lexists(self.policy.state/directory/(identity+'.json')),
                'A local no-dispatch receipt cannot conceal an original Root record')
        require(identity not in self.authority_ids, 'A local no-dispatch receipt cannot conceal a reserved handoff UUID')

    def closed_attempts(self):
        self.closed = {}; parent = self.data/'gateway-key-admissions'
        if not os.path.lexists(parent): return
        self.directory(parent); slots = list(parent.iterdir()); require(sum(('ADMISSION',p.name) not in self.archived for p in slots) <= 256)
        for slot in slots:
            require(canonical_id(slot.name)); self.directory(slot); names = {p.name for p in slot.iterdir()}
            require(names in ({'intent.json','complete','namespace.json'}, {'intent.json','complete','namespace.json','closed.json'}))
            raw = self.read(slot/'intent.json',12288)
            require(self.read(slot/'complete',65) == hashlib.sha256(raw).hexdigest().encode('ascii')+b'\n')
            attempt = validate_sender_attempt(decode(raw),'gwt'); require(attempt['nativeOperationId'] == slot.name)
            namespace = decode(self.read(slot/'namespace.json',4096))
            root = check_sender_attempt(self.policy,attempt,namespace,'gwt',self.binding['dataUid'])
            if 'closed.json' not in names: continue
            receipt = validate_gwt_closed(decode(self.read(slot/'closed.json',12288)),attempt,namespace)
            require(root['state'] == 'NOT_ADMITTED', 'A retained GWT intent requires the original Root non-admission')
            self.absent(slot.name)
            for name, fingerprint in receipt['files'].items():
                if attempt['kind'] == 'LEGACY': path = self.data/'gateway-key-operations'/slot.name/name
                else:
                    folder = 'gateway-key-generations' if attempt['kind'] == 'GENERATION' else 'gateway-key-handoffs'
                    path = self.data/folder/(slot.name+'.json')
                require(hashlib.sha256(self.read(path,65536)).hexdigest() == fingerprint,
                    'Retained GWT intent bytes have changed')
            if attempt['kind'] == 'LEGACY':
                directory = self.data/'gateway-key-operations'/slot.name
                require({p.name for p in directory.iterdir()} == set(receipt['files']))
            self.closed[slot.name] = (attempt['kind'], attempt['request'])

    def private_archives(self):
        """Validate every retained private intent, including pending metadata attempts."""
        parent=self.data/'gateway-key-archives';result=set()
        if not os.path.lexists(parent):return result
        self.directory(parent);inventory=archive_inventory(self.policy);secret=self.policy.read(self.policy.state/'journal.key',32)
        for path in parent.iterdir():
            parts=path.name[:-5].split('-',1)
            require(path.name.endswith('.json') and len(parts)==2 and canonical_id(parts[1])
                and parts[0] in ('LEGACY','GENERATION','HANDOFF','ADMISSION','NOT_DISPATCHED'))
            kind,identity=parts;marker=decode(self.read(path,65536))
            require(set(marker)=={'schema','purpose','kind','operationId','binding','privateFiles','reference','entrySha256','request','continuationAllowed'}
                and type(marker['schema']) is int and marker['schema']==1 and marker['purpose']=='yofc.kura.gwt-private-archive.v1'
                and marker['kind']==kind and marker['operationId']==identity and marker['binding']==self.binding
                and type(marker['continuationAllowed']) is bool and is_digest(marker['entrySha256']))
            files=marker['privateFiles'];require(isinstance(files,dict) and 1<=len(files)<=8 and all(is_digest(v) for v in files.values()))
            if kind in ('LEGACY','GENERATION','HANDOFF'):
                directory=self.JOURNALS[kind][0];slot=self.data/directory/(identity if kind=='LEGACY' else identity+'.json')
                if kind=='LEGACY':
                    self.directory(slot);names={p.name for p in slot.iterdir()}
                    require({'request.json','request-complete'}<=names<= {'request.json','request-complete','submitted','result.json','result-complete'})
                    expected={str((slot/name).relative_to(self.data)) for name in names}
                    metadata=decode(self.read(slot/'request.json',4096));require(metadata.pop('schema',None)=='yofc.kura.gateway-key.request.v1')
                    created=metadata.pop('createdAtUnixMs',None);require(type(created) is int and created>0);metadata['schema']=1
                else:
                    expected={str(slot.relative_to(self.data))};metadata=decode(self.read(slot,8192))
                require(validate_gwt_intent(kind,metadata)==identity)
            elif kind=='ADMISSION':
                slot=self.data/'gateway-key-admissions'/identity;self.directory(slot);names={p.name for p in slot.iterdir()}
                require(names in ({'intent.json','complete','namespace.json'},{'intent.json','complete','namespace.json','closed.json'}))
                expected={str((slot/name).relative_to(self.data)) for name in names}
                attempt=validate_sender_attempt(decode(self.read(slot/'intent.json',12288)),'gwt');require(attempt['nativeOperationId']==identity)
                metadata=attempt['request']
            else:
                slot=self.data/'gateway-key-not-dispatched'/identity;self.directory(slot)
                require({p.name for p in slot.iterdir()}=={'receipt.json','complete'})
                expected={str((slot/name).relative_to(self.data)) for name in ('receipt.json','complete')}
                receipt=decode(self.read(slot/'receipt.json',12288))
                require(set(receipt)=={'schema','kind','dataDirectory','dataDevice','dataInode','request'}
                    and receipt['schema']=='yofc.kura.gateway-key.no-dispatch.v1'
                    and all(receipt[k]==self.binding[k] for k in ('dataDirectory','dataDevice','dataInode')))
                metadata=receipt['request']
                require(validate_gwt_intent(receipt['kind'],metadata)==identity)
            require(set(files)==expected)
            for name,fingerprint in files.items():
                relative=Path(name);require(not relative.is_absolute() and str(relative)==name and '..' not in relative.parts)
                require(hashlib.sha256(self.read(self.data/relative,65536)).hexdigest()==fingerprint,'Private archive original bytes changed')
            reference=archive_references([marker['reference']])[0]
            entry=archive_entry(self.policy,reference,secret,inventory=inventory)
            require(entry['sha256']==marker['entrySha256'])
            correlation=archive_correlation(self.policy,reference,secret)
            if reference['directory']=='sender-admissions':
                sender=self.data/'gateway-key-admissions'/identity;self.directory(sender)
                attempt=validate_sender_attempt(decode(self.read(sender/'intent.json',12288)),'gwt')
                require(attempt['nativeOperationId']==identity and attempt['admissionId']==reference['operationId']
                    and attempt['request']==metadata)
                namespace=decode(self.read(sender/'namespace.json',4096))
                require(namespace==dict(schema=1,namespaceSha256=self.binding['namespaceSha256']))
                require(correlation['kind']=='ADMISSION' and correlation['source']=='gwt' and correlation['actorUid']==self.binding['dataUid']
                    and correlation['target']==dict(directory='handoffs' if attempt['kind']=='HANDOFF' else 'operations',
                        operationId=identity,action=metadata['action'],continuation=False)
                    and (kind=='ADMISSION' or correlation['outcome']=='NOT_ADMITTED'))
                if kind=='ADMISSION' and correlation['outcome']=='NOT_ADMITTED':
                    folder=self.JOURNALS[attempt['kind']][0]
                    owning=self.data/folder/(identity if attempt['kind']=='LEGACY' else identity+'.json')
                    require(not os.path.lexists(owning) or os.path.lexists(sender/'closed.json'),
                        'Retain the unconsumed owning intent before archiving its negative admission')
                if kind not in ('ADMISSION','NOT_DISPATCHED'):
                    closed=validate_gwt_closed(decode(self.read(sender/'closed.json',12288)),attempt,namespace)
                    require(closed['files'])  # Exact retained bytes are checked again by closed_attempts().
            elif kind=='HANDOFF':require(reference==dict(directory='handoffs',operationId=identity)
                and correlation['kind']=='HANDOFF' and correlation['request']==metadata)
            else:
                require(kind in ('LEGACY','GENERATION') and reference==dict(directory='operations',operationId=identity)
                    and correlation['kind']=='OPERATION' and correlation['action']==metadata['action']
                    and all(metadata.get(k)==v for k,v in correlation['binding'].items()))
            request=marker['request'];require(isinstance(request,dict) and set(request)=={'schema','action','archiveId','namespaceSha256','entries','expectedEntriesSha256'}
                and type(request['schema']) is int and request['schema']==1 and request['action']=='journal-archive'
                and canonical_id(request['archiveId']) and request['namespaceSha256']==self.binding['namespaceSha256']
                and is_digest(request['expectedEntriesSha256']))
            refs=archive_references(request['entries']);require(refs==request['entries'] and reference in refs)
            original=inventory['requests'].get(request['archiveId'])
            if original is None:continue  # Pending metadata is retained and stays in every active budget.
            intent,receipt=original
            require(intent['requestTag']==hmac.new(secret,encoded(request),hashlib.sha256).hexdigest()
                and intent['entriesSha256']==request['expectedEntriesSha256']
                and [{k:row[k] for k in ('directory','operationId')} for row in intent['entries']]==refs)
            if receipt is not None:result.add((kind,identity))
        return result

    def no_dispatch_archived(self,slot,raw,receipt):
        path=slot/'archive.json'
        if not os.path.lexists(path):return False
        request=decode(self.read(path,16384))
        require(set(request)=={'schema','action','source','admissionId','namespaceSha256',*GWT_DATA_FIELDS,'kind','intent','receiptSha256'}
            and type(request['schema']) is int and request['schema']==1 and request['action']=='sender-private-fence'
            and request['source']=='gwt' and canonical_id(request['admissionId']) and request['admissionId']!=slot.name
            and request['namespaceSha256']==self.binding['namespaceSha256']
            and all(request[k]==self.binding[k] for k in GWT_DATA_FIELDS) and type(request['dataUid']) is int
            and request['kind']==receipt['kind'] and request['intent']==receipt['request']
            and request['receiptSha256']==hashlib.sha256(raw).hexdigest())
        identity=request['admissionId'];parent=self.policy.state/'sender-admissions'
        if not os.path.lexists(parent):return False
        try:root_raw=self.policy.read(parent/(identity+'.json'),8192)
        except FileNotFoundError:return False  # Pending metadata never frees a private active slot.
        secret=self.policy.read(self.policy.state/'journal.key',32)
        value=validate_sender_admission(decode(root_raw),identity,secret)
        require(value['purpose']==PRIVATE_FENCE_PURPOSE and value['namespaceSha256']==request['namespaceSha256']
            and value['source']=='gwt' and value['owner']['uid']==self.binding['dataUid'])
        blocked=sorted([request['intent'][k] for k in ('handoffId','publicationId','startOperationId')]
            if request['kind']=='HANDOFF' else [slot.name])
        require(value['privateProof']==dict(**{k:request[k] for k in GWT_DATA_FIELDS},kind=request['kind'],
            receiptSha256=request['receiptSha256'],metadataSha256=hashlib.sha256(encoded(request['intent'])).hexdigest(),blockedIds=blocked)
            and value['target']['operationId']==slot.name and value['target']['action']==request['intent']['action'])
        check_sender_original(self.policy,value,secret);return True

    def check(self):
        marker = decode(self.read(self.data/'gateway-key-namespace.json', 8192))
        require(marker == self.binding, 'Core and Root sender namespaces differ')
        self.authority_ids = set()
        authorities = self.policy.state/'handoffs'
        if os.path.lexists(authorities):
            self.policy.directory(authorities, private=True); files = list(authorities.iterdir())
            require(active_journal_count(self.policy,'handoffs',[p.name[:-5] for p in files]) <= 32)
            for path in files:
                require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                raw = self.policy.read(path, 8192)
                authority = validate_handoff_authority(decode(raw), path.name[:-5], self.policy.read(self.policy.state/'journal.key', 32))
                require(raw == encoded(authority) and stat.S_IMODE(path.lstat().st_mode) == 0o400)
                self.authority_ids.update(authority['request'][k] for k in HANDOFF_IDS)
        self.archived=self.private_archives();self.closed_attempts()
        owning = set()
        for kind, (directory, lock, limit) in self.JOURNALS.items():
            parent = self.data/directory
            if not os.path.lexists(parent): continue
            files = [p for p in parent.iterdir() if p.name != lock]
            require(sum((kind,p.name if kind=='LEGACY' else p.name[:-5]) not in self.archived for p in files) <= limit)
            for path in files:
                if kind == 'LEGACY': require(canonical_id(path.name)); identity = self.legacy(path)
                else:
                    require(path.name.endswith('.json') and canonical_id(path.name[:-5]))
                    intent = decode(self.read(path, 8192 if kind == 'HANDOFF' else 4096))
                    identity = validate_gwt_intent(kind, intent); require(identity == path.name[:-5])
                    if identity in self.closed:
                        require(self.closed[identity] == (kind,intent)); self.absent(identity)
                    elif kind == 'GENERATION': self.original(identity, intent)
                    else:
                        authority_path = self.policy.state/'handoffs'/(identity+'.json')
                        raw = self.policy.read(authority_path, 8192)
                        authority = validate_handoff_authority(decode(raw), identity, self.policy.read(self.policy.state/'journal.key', 32))
                        require(raw == encoded(authority) and stat.S_IMODE(authority_path.lstat().st_mode) == 0o400
                            and authority['request'] == intent)
                require(identity not in owning, 'A UUID is occupied by multiple GWT sender journals'); owning.add(identity)
        parent = self.data/'gateway-key-not-dispatched'
        if os.path.lexists(parent):
            self.directory(parent); slots = list(parent.iterdir());active=0
            for slot in slots:
                require(canonical_id(slot.name) and slot.name not in owning); self.directory(slot)
                require({p.name for p in slot.iterdir()} in ({'receipt.json','complete'},{'receipt.json','complete','archive.json'}))
                raw = self.read(slot/'receipt.json', 12288)
                require(self.read(slot/'complete', 65) == hashlib.sha256(raw).hexdigest().encode('ascii') + b'\n')
                receipt = decode(raw)
                require(set(receipt) == {'schema', 'kind', 'dataDirectory', 'dataDevice', 'dataInode', 'request'}
                    and receipt['schema'] == 'yofc.kura.gateway-key.no-dispatch.v1'
                    and all(receipt[k] == self.binding[k] for k in ('dataDirectory', 'dataDevice', 'dataInode'))
                    and validate_gwt_intent(receipt['kind'], receipt['request']) == slot.name)
                self.absent(slot.name)
                if ('NOT_DISPATCHED',slot.name) not in self.archived and not self.no_dispatch_archived(slot,raw,receipt):active+=1
            require(active<=64)
        require(set(self.closed) <= owning, 'A closed GWT admission cannot conceal missing original intent files')
        return len(owning)

def private_fence(self, request, pid, uid, daemon, recovery):
    """Attest an explicit private no-dispatch receipt, never an absent INTAKE.

    A distinct signed purpose and domain identify this metadata fence. It is
    not an ordinary reservation or a reconstruction of an old request HMAC.
    Root trusts the authenticated Main's assertion without reading private files.
    """
    from kura_key_service import (require, fields, operation_id, digest, encode, decode, Failure, PRIVATE_FENCE_ACTIONS, ARCHIVE_ACTIONS)
    LifecycleRefused=Refused
    action=request.get('action');require(action in PRIVATE_FENCE_ACTIONS)
    base={'schema','action','source','namespaceSha256','admissionId'}
    fields(request,base if action.endswith('-read') else base|GWT_DATA_FIELDS|{'kind','intent','receiptSha256'})
    require(type(request['schema']) is int and request['schema']==1 and request['source'] in ('gwt','recovery'))
    identity=operation_id(request['admissionId']);manager=self.manager
    with self.locked(),manager.lock(manager.state/'admission.lock',True):
        manager.maintenance();owner=self.owner(request['source'],pid,uid,daemon,recovery)
        require(request['namespaceSha256']==manager.gwt_namespace()['namespaceSha256'],'CONFLICT')
        previous=self.load(identity)
        if action.endswith('-read'):
            if previous is None:return dict(schema=1,state='NOT_RECORDED',admissionId=identity,scope='PRIVATE_FENCE_ONLY')
            require(previous['purpose']==PRIVATE_FENCE_PURPOSE and previous['source']==request['source']
                and previous['owner']['uid']==uid,'CONFLICT')
            check_sender_original(manager,previous,self.secret())
            return self.private_fence_view(previous)
        data={k:request[k] for k in GWT_DATA_FIELDS};intent=request['intent'];kind=request['kind'];require(isinstance(intent,dict))
        try:
            validate_gwt_data(data);require(data['dataUid']==uid,'FORBIDDEN')
            if request['source']=='gwt':
                require(kind in ('LEGACY','GENERATION','HANDOFF'))
                native_id=validate_gwt_intent(kind,intent)
                binding=validate_gwt_binding(decode(manager.read(manager.state/'gwt-sender.json',8192)))
                require(all(binding[k]==data[k] for k in GWT_DATA_FIELDS),'CONFLICT')
            else:
                require(kind in ('restore','start'))
                native_id=operation_id(intent.get('operationId'))
                validate_sender_attempt(dict(schema=1,purpose='yofc.kura.sender-attempt.v1',admissionId=identity,
                    kind=kind,nativeOperationId=native_id,request=intent),'recovery')
        except LifecycleRefused:raise Failure('INVALID_ARGUMENT') from None
        digest(request['receiptSha256']);blocked=sorted([intent[k] for k in ('handoffId','publicationId','startOperationId')]
            if kind=='HANDOFF' else [native_id]);require(identity not in blocked,'CONFLICT')
        proof=dict(data,kind=kind,metadataSha256=hashlib.sha256(encode(intent)).hexdigest(),
            receiptSha256=request['receiptSha256'],blockedIds=blocked)
        directory='handoffs' if kind=='HANDOFF' else 'startups' if kind=='start' else 'operations'
        body=dict(source=request['source'],namespaceSha256=request['namespaceSha256'],privateProof=proof,
            directory=directory,operationId=native_id,action=intent['action'])
        tag=hmac.new(self.secret(),PRIVATE_FENCE_CONTEXT+encode(body),hashlib.sha256).hexdigest()
        if previous is not None:
            require(previous['purpose']==PRIVATE_FENCE_PURPOSE and previous['requestTag']==tag
                and previous['owner']['uid']==uid,'CONFLICT')
            check_sender_original(manager,previous,self.secret());return self.private_fence_view(previous)
        # Check every native table and retained reservation, including archived
        # rows. No pending issuer may hold undisclosed fixed child IDs.
        protected=set(blocked+[identity]);records=self.records()
        for key in protected:
            self.require_no_native(key);manager.require_not_archive_id(key)
            require(self.load(key) is None,'CONFLICT')
        for row in records:
            require(row['target']['operationId'] not in protected,'UNRESOLVED_OPERATION')
            require(not (row['target']['directory']=='handoffs' and row['state'] in ('RESERVED','INTAKE')
                and self.native(row['target']) is None),'UNRESOLVED_OPERATION')
        grants=manager.state/'handoffs'
        if os.path.lexists(grants):
            manager.directory(grants,private=True)
            for path in grants.iterdir():
                require(path.name.endswith('.json'),'UNSAFE_JOURNAL')
                try:value=validate_handoff_authority(decode(manager.read(path,8192)),operation_id(path.name[:-5]),self.secret())
                except LifecycleRefused:raise Failure('UNSAFE_JOURNAL') from None
                require(not protected&{value['request'][k] for k in
                    ('handoffId','preparationId','verificationId','publicationId','startOperationId')},'CONFLICT')
        if action.endswith('-plan'):return dict(schema=1,state='PRIVATE_FENCE_PLAN',admissionId=identity,**body,
            credentialsChanged=False,startRequested=False)
        value=dict(schema=1,purpose=PRIVATE_FENCE_PURPOSE,admissionId=identity,source=request['source'],
            namespaceSha256=request['namespaceSha256'],owner=owner,requestTag=tag,privateProof=proof,
            target=dict(directory=directory,operationId=native_id,action=intent['action'],requestTag=tag,continuation=False),
            parentAdmissionId=None,state='NOT_ADMITTED')
        value['receiptTag']=hmac.new(self.secret(),SENDER_ADMISSION_CONTEXT+encode(value),hashlib.sha256).hexdigest()
        self.directory.mkdir(mode=0o700,exist_ok=True);manager.directory(self.directory,private=True);manager.sync(manager.state)
        try:
            manager.atomic(self.directory/(identity+'.json'),encode(value),mode=0o400,no_replace=True)
            return self.private_fence_view(self.load(identity))
        except (Failure,LifecycleRefused,OSError):raise Failure('UNKNOWN') from None


def archive_journal(self, request, pid, uid, daemon, recovery):
    """Explicit metadata only. No cipher, unit command or key writer is reachable."""
    from kura_key_service import (require, fields, operation_id, digest, encode, decode, Failure, PRIVATE_FENCE_ACTIONS, ARCHIVE_ACTIONS)
    LifecycleRefused=Refused
    if request.get('action') in ('journal-archive-reference-read','journal-archive-recovery-reference-read'):
        return archive_reference_read(self,request,pid,uid,daemon,recovery)
    action=request.get('action');require(action in ARCHIVE_ACTIONS)
    expected={'schema','action','namespaceSha256'}|({'entries'} if action=='journal-archive-plan' else
        {'archiveId'} if action=='journal-archive-read' else {'archiveId','entries','expectedEntriesSha256'})
    fields(request,expected);require(type(request['schema']) is int and request['schema']==1)
    if uid==0:source='local-admin'
    elif uid==daemon:self.gwt_sender_owner(pid,uid,daemon);source='gwt'
    else:
        require(recovery is not None and uid==recovery,'FORBIDDEN')
        self.recovery_sender_owner(pid,uid);source='recovery'
    with self.sender_admissions.locked(),self.lock(self.state/'admission.lock',True):
        self.maintenance();namespace=self.gwt_namespace()['namespaceSha256']
        require(request['namespaceSha256']==namespace,'CONFLICT');inventory=self.archives()
        if action=='journal-archive-read':
            identity=operation_id(request['archiveId']);previous=inventory['requests'].get(identity)
            return self.archive_view(identity,*previous) if previous else dict(schema=1,archiveId=identity,
                namespaceSha256=namespace,state='NOT_RECORDED',scope='ORIGINAL_ARCHIVE_ONLY')
        try:references=archive_references(request['entries'])
        except LifecycleRefused:raise Failure('INVALID_ARGUMENT') from None
        if action=='journal-archive-plan':
            try:entries=[archive_entry(self,ref,self.sender_admissions.secret(),inventory=inventory) for ref in references]
            except (LifecycleRefused,FileNotFoundError):raise Failure('ARCHIVE_UNSETTLED') from None
            require(all((row['directory'],row['operationId']) not in inventory['archived'] for row in entries),'ALREADY_ARCHIVED')
            return dict(schema=1,state='ARCHIVE_PLAN',namespaceSha256=namespace,entries=entries,
                entriesSha256=hashlib.sha256(encode(entries)).hexdigest(),originalsRetained=True,credentialsChanged=False,startRequested=False)
        identity=operation_id(request['archiveId']);digest(request['expectedEntriesSha256'])
        native=dict(schema=1,action='journal-archive',archiveId=identity,namespaceSha256=namespace,
            entries=references,expectedEntriesSha256=request['expectedEntriesSha256'])
        tag=self.sender_admissions.tag(native);previous=inventory['requests'].get(identity)
        if previous is not None:
            intent,receipt=previous
            require(intent['requestTag']==tag and (uid==0 or intent['actorUid']==uid and intent['source']==source),'CONFLICT')
            if receipt is not None or action=='journal-archive':return self.archive_view(identity,intent,receipt)
        else:
            require(action=='journal-archive','NOT_FOUND')
            self.require_not_archive_id(identity)
            require(all(receipt is not None for _,receipt in inventory['requests'].values()),'UNRESOLVED_ARCHIVE')
            for directory in ('operations','startups','handoffs','sender-admissions','package-history'):
                require(not os.path.lexists(self.state/directory/(identity+'.json')),'CONFLICT')
            senders=self.sender_admissions.records()
            require(all(row['target']['operationId']!=identity for row in senders),'CONFLICT')
            require(not any(row['target']['directory']=='handoffs' and row['state'] in ('RESERVED','INTAKE')
                and self.sender_admissions.native(row['target']) is None for row in senders),'UNRESOLVED_OPERATION')
            grants=self.state/'handoffs'
            if os.path.lexists(grants):
                for path in grants.iterdir():
                    require(path.name.endswith('.json'),'UNSAFE_JOURNAL');value=decode(self.read(path,8192))
                    try:validate_handoff_authority(value,operation_id(path.name[:-5]),self.sender_admissions.secret())
                    except LifecycleRefused:raise Failure('UNSAFE_JOURNAL') from None
                    require(identity not in {value['request'][key] for key in
                        ('handoffId','preparationId','verificationId','publicationId','startOperationId')},'CONFLICT')
            claimed={(row['directory'],row['operationId']) for intent,_ in inventory['requests'].values() for row in intent['entries']}
            require(not any((ref['directory'],ref['operationId']) in claimed for ref in references),'ALREADY_ARCHIVED')
            try:entries=[archive_entry(self,ref,self.sender_admissions.secret(),inventory=inventory) for ref in references]
            except (LifecycleRefused,FileNotFoundError):raise Failure('ARCHIVE_UNSETTLED') from None
            require(hashlib.sha256(encode(entries)).hexdigest()==request['expectedEntriesSha256'],'CONFLICT')
            intent=dict(schema=1,purpose='yofc.kura.journal-archive-intent.v1',archiveId=identity,namespaceSha256=namespace,
                source=source,actorUid=uid,createdAt=int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
                entries=entries,entriesSha256=request['expectedEntriesSha256'],requestTag=tag,
                previousArchiveId=inventory['head'],previousArchiveSha256=hashlib.sha256(encode(
                    inventory['requests'][inventory['head']][1])).hexdigest() if inventory['head'] is not None else None)
            intent['receiptTag']=hmac.new(self.sender_admissions.secret(),ARCHIVE_INTENT_CONTEXT+encode(intent),hashlib.sha256).hexdigest()
            parent=self.state/'archives';parent.mkdir(mode=0o700,exist_ok=True);self.directory(parent,private=True);self.sync(self.state)
            try:self.atomic(parent/(identity+'.intent.json'),encode(intent),mode=0o400,no_replace=True)
            except (Failure,OSError):raise Failure('UNKNOWN') from None
        # Recheck only the original signed metadata. Continuing an archive never
        # replays a key operation, changes an ID or fills a missing native result.
        try:
            self.sync(self.state/'archives')
            entries=[archive_entry(self,ref,self.sender_admissions.secret(),inventory=inventory) for ref in references]
            require(entries==intent['entries'],'CONFLICT')
            receipt=dict(schema=1,purpose='yofc.kura.journal-archive-receipt.v1',archiveId=identity,
                namespaceSha256=namespace,intentSha256=hashlib.sha256(encode(intent)).hexdigest(),
                entriesSha256=intent['entriesSha256'],archivedAt=int(datetime.datetime.now(datetime.timezone.utc).timestamp()))
            receipt['receiptTag']=hmac.new(self.sender_admissions.secret(),ARCHIVE_RECEIPT_CONTEXT+encode(receipt),hashlib.sha256).hexdigest()
            self.atomic(self.state/'archives'/(identity+'.receipt.json'),encode(receipt),mode=0o400,no_replace=True)
            return self.archive_view(identity,intent,receipt)
        except (LifecycleRefused,Failure,OSError):raise Failure('UNKNOWN') from None
