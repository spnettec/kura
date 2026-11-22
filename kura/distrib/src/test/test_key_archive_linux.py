#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh disposable Linux UDS/three UIDs/zero caps. Main/systemd and old history are models.

Metadata archive only: no data key, cipher, installed gateway or service-start write.
"""
import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import select
import socket
import struct
import subprocess
import sys
import tempfile
import uuid


def drop(uid):
    library=ctypes.CDLL(None,use_errno=True)
    for cap in range(64):
        if library.prctl(24,cap,0,0,0)!=0 and ctypes.get_errno()!=errno.EINVAL:raise OSError('capability drop refused')
    if uid:
        os.setgroups([65534] if uid==65533 else []);os.setgid(uid);os.setuid(uid)


def rpc(request):
    raw=json.dumps(request,separators=(',',':')).encode()
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        connection.settimeout(8);connection.connect('/run/kura-key-service/control.sock')
        connection.sendall(struct.pack('!I',len(raw))+raw);connection.shutdown(socket.SHUT_WR)
        def read(size):
            result=bytearray()
            while len(result)<size:
                value=connection.recv(size-len(result));assert value;result.extend(value)
            return bytes(result)
        size=struct.unpack('!I',read(4))[0];assert 0<size<=65536
        result=json.loads(read(size));assert connection.recv(1)==b'';return result


WORKER=r'''
import hashlib,json,os,socket,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]);import kura_key_service as service
root,expected,stop=map(Path,sys.argv[2:5]);manager=service.Manager(root)
profile=sys.argv[6] if len(sys.argv)>6 else 'root-archive';receiver=profile=='recovery-history'
def status(pid):
    result={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in Path('/proc/'+str(pid)+'/status').read_text().splitlines()
        if line.split(':',1)[0] in ('Uid','CapEff','CapBnd','CapAmb','NoNewPrivs')}
    assert result['NoNewPrivs']=='1' and all(result[k]=='0000000000000000' for k in ('CapEff','CapBnd','CapAmb'));return result
class Main:
    def unit(self,**kw):return dict(ActiveState='active',SubState='running',MainPID=str(json.loads(expected.read_bytes())['core']),
        ControlPID='0',ControlGroup='/system.slice/kura.service',InvocationID='a'*32)
    def process_group(self,pid):return '/system.slice/kura.service'
manager.generation_component=lambda:(Main(),None)
def recovery(pid,uid):service.require(uid==65533 and pid==json.loads(expected.read_bytes())['recovery'] and manager.writer_process(pid)[0]==uid,'FORBIDDEN')
manager.recovery_sender_owner=recovery
manager.crypt=lambda *args:(_ for _ in ()).throw(AssertionError('archive invoked cipher'))
denied=[]
for name in ('core-private','var/lib/kura-key-recovery' if receiver else 'recovery-private'):
    try:list((root/name).iterdir())
    except PermissionError:denied.append(True)
assert denied==[True,True];root_status=status(os.getpid());actions=[];peers={}
print('ARCHIVE_ROOT_READY',flush=True)
with socket.socket(fileno=int(sys.argv[5])) as listener:
    listener.settimeout(.2)
    while not stop.exists():
        try:connection,_=listener.accept()
        except TimeoutError:continue
        with connection:
            connection.settimeout(8);pid,uid,gid=service.peer(connection);peers[str(uid)]=status(pid)
            request=service.decode(service.read_frame(connection));assert connection.recv(1)==b'';actions.append(request['action'])
            try:response,descriptor=service.serve_request(manager,request,pid,uid,65534,65533,None);assert descriptor is None
            except service.Failure as error:response=dict(schema=1,error=error.reason)
            service.send_frame(connection,response)
fences=profile=='private-fences';history=profile=='private-history'
assert len(list(manager.operations.iterdir()))==(1 if history or receiver else 0) and not manager.store.path(service.KEY_PATH).exists()
assert len(manager.sender_admissions.records())==(7 if receiver else 6 if fences or history else 4)
assert len(manager.archives()['archived'])==(5 if receiver else 3 if history else 0 if fences else 2)
print(json.dumps(dict(rootStatus=root_status,peers=peers,rootPrivateReadsRefused=denied,actions=actions,
    archives=5 if receiver else 3 if history else 0 if fences else 2,privateFences=2 if fences else 0,originalAdmissions=7 if receiver else 6 if history else 4,
    modeledHistoricalNativeOperations=1 if history or receiver else 0,modeledHistoricalStartups=1 if receiver else 0,
    nativeKeyOperations=0,cipherCalls=0,installedMainAndHumanSession=False,
    systemdAndMain='modeled; SO_PEERCRED, process UIDs/caps, transport and archive handlers actual')),flush=True)
'''


RECEIVER_PEER=r'''
import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]);import kura_key_recovery as recovery
from kura_key_service_lifecycle import Lifecycle
protocol=recovery.protocol;root=Path(sys.argv[2]);journal=recovery.Journal(root/'var/lib/kura-key-recovery',archive_module=Lifecycle(root).journal_module())
client=recovery.RootClient();sender=recovery.SenderAdmission(client,journal);history=journal.history()
print('CLIENT_READY',flush=True)
for line in sys.stdin:
    request=json.loads(line);action=request.get('testAction')
    if action is None:result=client(request)
    else:
        with journal.lock():
            if action=='recovery-seed':
                realm=client(dict(schema=1,action='gwt-sender-namespace'))['namespaceSha256']
                restore=request['restoreId'];start=request['startId'];key='1'*64
                backup=dict(format=protocol.FORMAT,operationId=restore,encrypted='YQ==');backup_sha=recovery.hashlib.sha256(protocol.encode(backup)).hexdigest()
                journal.write_new(journal.operations/(restore+'.json'),dict(schema=1,operationId=restore,expectedKeySha256=key,backupSha256=backup_sha))
                journal.write_new(journal.starts/(start+'.json'),dict(schema=1,operationId=start,restoreOperationId=restore,expectedKeySha256=key))
                parent=journal.directory/'admissions';parent.mkdir(mode=0o700)
                for identity,step,admission in [(restore,'restore',request['restoreAdmissionId']),(start,'start',request['startAdmissionId']),(request['deniedId'],'restore',request['deniedAdmissionId'])]:
                    metadata=dict(schema=1,action='core-start' if step=='start' else 'restore',operationId=identity,expectedKeySha256=key)
                    metadata.update(restoreOperationId=restore) if step=='start' else metadata.update(backupSha256=backup_sha)
                    slot=parent/(identity+'-'+step);slot.mkdir(mode=0o700)
                    journal.write_new(slot/'intent.json',dict(schema=1,purpose='yofc.kura.sender-attempt.v1',admissionId=admission,kind=step,nativeOperationId=identity,request=metadata))
                    journal.write_new(slot/'namespace.json',dict(schema=1,namespaceSha256=realm))
                result=dict(state='RECEIVER_HISTORY_SEEDED')
            elif action=='recovery-archive':result=history.archive(request['kind'],request['operationId'],request.get('senderKind'),preview=request.get('preview',False))
            elif action=='recovery-list':
                result=dict(restores=len(journal.records()),starts=len(journal.start_records()),admissions=[sender.view(p.name[37:],p.name[:36])['phase'] for p in sorted((journal.directory/'admissions').iterdir())])
            elif action=='recovery-old-id':
                identity=request['operationId'];metadata=sender.load('restore',identity)[0]['request'];calls=[]
                try:sender.submit('restore',identity,metadata,lambda:calls.append('writer'))
                except protocol.Failure as failure:assert failure.reason=='UNRESOLVED_OPERATION'
                assert not calls;result=dict(lateCallbacks=0)
            else:raise AssertionError('unsupported receiver metadata command')
    print(json.dumps(result),flush=True)
'''


def check_private_fences(manager,root,namespace,ask,core,recovery,rogue,bound,java_peer=False):
    results=[]
    for peer,source,kind,directory,uid,wrap in [(core,'gwt','LEGACY','core-private',65534,bound),
            (recovery,'recovery','restore','recovery-private',65533,lambda value:value)]:
        data=root/directory;target=str(uuid.uuid4())
        intent=dict(schema=1,action='backup-create',operationId=target,operator='modeled-private-admin') if source=='gwt' else dict(
            schema=1,action='restore',operationId=target,expectedKeySha256='1'*64,backupSha256='2'*64)
        if source=='gwt' and java_peer:
            assert ask(peer,dict(testAction='record',operationId=target))['state']=='LOCAL_NO_DISPATCH_RECORDED'
            for _ in range(63):assert ask(peer,dict(testAction='record',operationId=str(uuid.uuid4())))['state']=='LOCAL_NO_DISPATCH_RECORDED'
            path=data/'gateway-key-not-dispatched'/target/'receipt.json';raw=path.read_bytes();intent=json.loads(raw)['request']
        else:
            raw=json.dumps(dict(schema=1,kind=kind,request=intent),separators=(',',':')).encode()
            path=data/'private-no-dispatch.json';path.write_bytes(raw);path.chmod(0o600);os.chown(path,uid,uid)
        request=dict(schema=1,action='sender-private-fence',source=source,kind=kind,intent=intent,receiptSha256=hashlib.sha256(raw).hexdigest(),
            admissionId=str(uuid.uuid4()),namespaceSha256=namespace['namespaceSha256'],dataDirectory=str(data) if source=='gwt' and java_peer else '/'+directory,
            dataDevice=str(data.stat().st_dev),dataInode=str(data.stat().st_ino),dataUid=uid)
        if source=='gwt':
            assert ask(core,request)['error']=='FORBIDDEN'
            assert ask(rogue,bound(request))['error']=='UNMANAGED_CORE'
        before={p.name:(p.read_bytes(),p.stat()) for p in manager.sender_admissions.directory.iterdir()}
        plan=ask(peer,wrap(dict(request,action='sender-private-fence-plan')));assert plan['state']=='PRIVATE_FENCE_PLAN'
        assert before=={p.name:(p.read_bytes(),p.stat()) for p in manager.sender_admissions.directory.iterdir()}
        if source=='gwt' and java_peer:
            result=ask(peer,dict(testAction='archive',operationId=target));request=json.loads((path.parent/'archive.json').read_bytes())
            assert ask(peer,dict(testAction='archive',operationId=target))==result  # Original query only.
            assert ask(peer,dict(testAction='record',operationId=str(uuid.uuid4())))['state']=='LOCAL_NO_DISPATCH_RECORDED'
            assert ask(peer,dict(testAction='list'))['records']==65
        else:result=ask(peer,wrap(request))
        assert result['state']=='PRIVATE_FENCE_RECORDED'
        assert result['privateProof']['receiptSha256']==hashlib.sha256(raw).hexdigest()
        query=dict({k:request[k] for k in ('schema','source','admissionId','namespaceSha256')},action='sender-private-fence-read')
        assert ask(peer,wrap(query))==result
        wrong=dict(query,source='recovery' if source=='gwt' else 'gwt')
        assert ask(recovery if source=='gwt' else core,wrong if source=='gwt' else bound(wrong))['error']=='CONFLICT'
        original=manager.sender_admissions.directory/(request['admissionId']+'.json');assert original.stat().st_mode&0o777==0o400
        assert original.stat().st_uid==0 and hashlib.sha256(original.read_bytes()).hexdigest()==result['receiptSha256']
        for identity in (target,request['admissionId']):
            native=dict(schema=1,action='restore',operationId=identity,passphrase='synthetic-never-used',expectedKeySha256='1'*64,
                backup=dict(format='yofc-kura-gateway-master-key-v1',operationId=str(uuid.uuid4()),encrypted='YQ=='))
            reserve=dict(schema=1,action='sender-reserve',admissionId=str(uuid.uuid4()),source='recovery',
                namespaceSha256=namespace['namespaceSha256'],request=native)
            assert ask(recovery,reserve)['error']=='CONFLICT'
        assert raw==path.read_bytes();results.append(result)
    assert len(results)==2


def seed_private_history(manager,namespace):
    """Only historic outcomes are modeled. HMAC and subsequent transport/handlers are real."""
    import kura_key_service as service
    result={name:str(uuid.uuid4()) for name in ('legacyId','admissionId','deniedId','deniedAdmissionId')}
    for identity,admission,phase in [(result['legacyId'],result['admissionId'],'INTAKE'),
            (result['deniedId'],result['deniedAdmissionId'],'NOT_ADMITTED')]:
        native=dict(schema=1,action='backup-create',operationId=identity,passphrase='synthetic-modeled-history-only')
        if phase=='INTAKE':
            response=dict(schema=1,action='backup-create',operationId=identity,state='SUCCEEDED',
                backup=dict(format=service.FORMAT,operationId=identity,encrypted='YQ=='))
            manager.atomic(manager.operations/(identity+'.json'),service.encode(dict(schema=1,action='backup-create',
                operationId=identity,requestTag=manager.sender_admissions.tag(native),state='SUCCEEDED',response=response)))
        manager.sender_admissions.write(dict(schema=1,purpose=service.SENDER_ADMISSION_PURPOSE,admissionId=admission,
            source='gwt',namespaceSha256=namespace['namespaceSha256'],owner=dict(uid=65534,pid=os.getpid(),
            startTicks=manager.writer_process(os.getpid())[1],bootId=Path('/proc/sys/kernel/random/boot_id').read_text().strip()),
            requestTag=manager.sender_admissions.tag(native),target=manager.sender_admissions.native_target(native),
            parentAdmissionId=None,state=phase),create=True)
    return result


def check_private_history(manager,root,namespace,ask,core,recovery,rogue,bound,seed):
    reference=dict(schema=1,action='journal-archive-reference-read',namespaceSha256=namespace['namespaceSha256'],
        directory='operations',operationId=seed['legacyId'])
    assert ask(core,reference)['error']=='FORBIDDEN'
    assert ask(rogue,bound(reference))['error']=='UNMANAGED_CORE'
    assert ask(core,dict(testAction='history-seed',**seed))['state']=='HISTORICAL_METADATA_SEEDED'
    private=root/'core-private'
    originals={str(p.relative_to(private)):(p.read_bytes(),p.stat()) for p in private.rglob('*') if p.is_file()}
    native={p.name:(p.read_bytes(),p.stat()) for p in manager.operations.iterdir()}
    first=None
    for kind,identity in [('LEGACY',seed['legacyId']),('ADMISSION',seed['legacyId']),
            ('NOT_DISPATCHED',seed['deniedId']),('ADMISSION',seed['deniedId'])]:
        request=dict(testAction='history-archive',kind=kind,operationId=identity)
        result=ask(core,request);assert result['state']=='ARCHIVE_RECORDED',result
        assert result['credentialsChanged'] is False and result['startRequested'] is False
        assert ask(core,request)==result  # Existing private intent is query-only.
        if first is None:first=result
    assert ask(core,dict(testAction='history-list'))==dict(legacy=1,admissions=2,denied=1)
    assert ask(core,dict(testAction='history-old-id',operationId=seed['legacyId']))['lateCallbacks']==0
    assert originals=={name:((private/name).read_bytes(),(private/name).stat()) for name in originals}
    assert native=={p.name:(p.read_bytes(),p.stat()) for p in manager.operations.iterdir()}
    assert len(list((private/'gateway-key-archives').iterdir()))==4
    assert len(manager.archives()['archived'])==3
    query=dict(schema=1,action='journal-archive-read',namespaceSha256=namespace['namespaceSha256'],archiveId=first['archive']['archiveId'])
    assert ask(recovery,query)['state']=='ARCHIVE_RECORDED'


def seed_recovery_history(manager,namespace):
    import kura_key_service as service
    seed={name:str(uuid.uuid4()) for name in ('restoreId','startId','restoreAdmissionId','startAdmissionId','deniedId','deniedAdmissionId')}
    restore=seed['restoreId'];start=seed['startId'];key='1'*64
    native_restore=dict(schema=1,action='restore',operationId=restore,expectedKeySha256=key,passphrase='synthetic historical model only',
        backup=dict(format=service.FORMAT,operationId=restore,encrypted='YQ=='))
    result=dict(schema=1,action='restore',operationId=restore,state='SUCCEEDED',keySha256=key,keyChanged=True,existingReceiptPreserved=True)
    manager.atomic(manager.operations/(restore+'.json'),service.encode(dict(schema=1,action='restore',operationId=restore,state='SUCCEEDED',requestTag=manager.sender_admissions.tag(native_restore),response=result)))
    native_start=dict(schema=1,action='core-start',operationId=start,restoreOperationId=restore,expectedKeySha256=key)
    response=dict(schema=1,action='core-start',operationId=start,restoreOperationId=restore,keySha256=key,state='SUCCEEDED',scope='SYSTEMD_JOB_ACCEPTED',jobPath='/org/freedesktop/systemd1/job/42')
    directory=manager.state/'startups';directory.mkdir(mode=0o700)
    manager.atomic(directory/(start+'.json'),service.encode(dict(schema=1,operationId=start,restoreOperationId=restore,keySha256=key,requestTag=manager.sender_admissions.tag(native_start),state='SUCCEEDED',response=response)))
    for native,admission,phase,directory in [(native_restore,seed['restoreAdmissionId'],'INTAKE','operations'),(native_start,seed['startAdmissionId'],'INTAKE','startups'),
            (dict(native_restore,operationId=seed['deniedId']),seed['deniedAdmissionId'],'NOT_ADMITTED','operations')]:
        manager.sender_admissions.write(dict(schema=1,purpose=service.SENDER_ADMISSION_PURPOSE,admissionId=admission,source='recovery',namespaceSha256=namespace['namespaceSha256'],
            owner=dict(uid=65533,pid=os.getpid(),startTicks=manager.writer_process(os.getpid())[1],bootId=Path('/proc/sys/kernel/random/boot_id').read_text().strip()),
            requestTag=manager.sender_admissions.tag(native),target=manager.sender_admissions.native_target(native,directory=directory),parentAdmissionId=None,state=phase),create=True)
    return seed


def check_recovery_history(manager,root,namespace,ask,core,recovery,rogue,seed):
    from types import SimpleNamespace
    from unittest.mock import patch
    import kura_key_service_lifecycle as lifecycle
    import kura_key_recovery_setup as setup
    reference=dict(schema=1,action='journal-archive-recovery-reference-read',namespaceSha256=namespace['namespaceSha256'],directory='operations',operationId=seed['restoreId'])
    assert ask(core,reference)['error']=='FORBIDDEN';assert ask(rogue,reference)['error']=='FORBIDDEN'
    assert ask(recovery,dict(testAction='recovery-seed',**seed))['state']=='RECEIVER_HISTORY_SEEDED'
    private=root/'var/lib/kura-key-recovery'
    originals={str(p.relative_to(private)):(p.read_bytes(),p.stat()) for p in private.rglob('*') if p.is_file()}
    native={str(p.relative_to(manager.state)):(p.read_bytes(),p.stat()) for name in ('operations','startups') for p in (manager.state/name).iterdir()}
    steps=[('RESTORE',seed['restoreId'],None),('START',seed['startId'],None),('ADMISSION',seed['restoreId'],'restore'),('ADMISSION',seed['startId'],'start'),('ADMISSION',seed['deniedId'],'restore')]
    for kind,identity,step in steps:
        command=dict(testAction='recovery-archive',kind=kind,operationId=identity,senderKind=step)
        before={str(p.relative_to(private)):p.read_bytes() for p in private.rglob('*.json')}
        assert ask(recovery,dict(command,preview=True))['state']=='ARCHIVABLE'
        assert before=={str(p.relative_to(private)):p.read_bytes() for p in private.rglob('*.json')}
        result=ask(recovery,command);assert result['state']=='ARCHIVE_RECORDED',result
        assert ask(recovery,command)==result  # Never a second metadata first send.
    result=ask(recovery,dict(testAction='recovery-list'));assert result['restores']==result['starts']==1
    assert sorted(result['admissions'])==['NOT_ADMITTED','TERMINAL','TERMINAL']
    assert ask(recovery,dict(testAction='recovery-old-id',operationId=seed['restoreId']))['lateCallbacks']==0
    assert originals=={name:((private/name).read_bytes(),(private/name).stat()) for name in originals}
    assert native=={str(p.relative_to(manager.state)):(p.read_bytes(),p.stat()) for name in ('operations','startups') for p in (manager.state/name).iterdir()}
    account=lambda name:SimpleNamespace(pw_uid=65533 if name=='kura-key-recovery' else 65534,pw_gid=65533,pw_shell='/usr/sbin/nologin')
    policy=lifecycle.Lifecycle(root)
    with manager.sender_admissions.locked(),manager.lock(manager.state/'admission.lock',False),patch.object(lifecycle.pwd,'getpwnam',side_effect=account):
        with policy.recovery_locked():pass  # Full independent package entrypoint; no receiver module imported by it.
        before={str(p.relative_to(private)):(p.read_bytes(),p.stat()) for p in private.rglob('*') if p.is_file()}
        setup.Setup(root).state(account('kura-key-recovery'))
        assert before=={str(p.relative_to(private)):(p.read_bytes(),p.stat()) for p in private.rglob('*') if p.is_file()}


def main(repository,private_fences=False,java=None,classpath=None,private_history=False,recovery_history=False):
    assert sys.platform=='linux' and os.geteuid()==0 and Path('/.dockerenv').exists()
    assert not Path('/etc/kura').exists() and not Path('/var/lib/kura-key-service').exists()
    source=repository/'kura/distrib/src/main/resources/unfiltered/pkg/bin';sys.path.insert(0,str(source))
    import kura_key_service as service
    work=Path(tempfile.mkdtemp(prefix='root-archive-uds-'));work.chmod(0o755);root=work/'root';root.mkdir(mode=0o755)
    for name,uid in [('core-private',65534),('var/lib/kura-key-recovery' if recovery_history else 'recovery-private',65533)]:
        path=root/name;path.mkdir(parents=True,mode=0o700);os.chown(path,uid,uid)
    state=root/'var/lib/kura-key-service';(state/'operations').mkdir(parents=True,mode=0o700)
    for path in (root/'var',root/'var/lib'):path.chmod(0o755)
    state.chmod(0o700)
    for name,raw in [('journal.key',os.urandom(32)),('admission.lock',b''),('sender-admission.lock',b'')]:
        path=state/name;path.write_bytes(raw);path.chmod(0o600)
    manager=service.Manager(root);namespace=manager.gwt_namespace();rows=[]
    # The transport/Main roles remain models. The new journal implementation itself
    # is read from an actual Root-owned, manifest-pinned package file, without pyc.
    import kura_key_service_lifecycle as lifecycle
    home=root/'opt/eclipse/kura';home.mkdir(parents=True,mode=0o755)
    for name in lifecycle.ASSETS:
        path=home/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((source/'kura_key_journal.py').read_bytes() if name=='bin/kura_key_journal.py' else b'modeled package asset');path.chmod(0o644)
    unit_hashes={}
    for name in lifecycle.UNITS:
        path=root/'lib/systemd/system'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'modeled systemd unit');path.chmod(0o644)
        unit_hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest=dict(schema=1,protocol=1,files={name:hashlib.sha256((home/name).read_bytes()).hexdigest() for name in lifecycle.ASSETS},units=unit_hashes)
    (home/'libexec/key-backup/manifest.json').write_bytes(service.encode(manifest));(home/'libexec/key-backup/manifest.json').chmod(0o644)
    for _ in range(4):
        native=dict(schema=1,action='backup-create',operationId=str(uuid.uuid4()),passphrase='synthetic-closed-history')
        rows.append(manager.sender_admissions.write(dict(schema=1,purpose=service.SENDER_ADMISSION_PURPOSE,
            admissionId=str(uuid.uuid4()),source='local-admin',namespaceSha256=namespace['namespaceSha256'],
            owner=dict(uid=0,pid=os.getpid(),startTicks=manager.writer_process(os.getpid())[1],bootId=Path('/proc/sys/kernel/random/boot_id').read_text().strip()),
            requestTag=manager.sender_admissions.tag(native),target=manager.sender_admissions.native_target(native),parentAdmissionId=None,state='NOT_ADMITTED'),create=True))
    seed=seed_recovery_history(manager,namespace) if recovery_history else seed_private_history(manager,namespace) if private_history else None
    originals={p.name:(p.read_bytes(),p.stat()) for p in manager.sender_admissions.directory.iterdir()}
    run=Path('/run/kura-key-service');run.mkdir(mode=0o755)
    listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listener.bind(str(run/'control.sock'));listener.listen(8)
    os.chown(run/'control.sock',0,65534);os.chmod(run/'control.sock',0o660)
    clients=[];server=None;stop=work/'stop';expected=work/'expected.json'
    def client(uid):
        command=[sys.executable,'-B',str(Path(__file__).resolve()),'--client']
        if java is not None and uid==65534 and not clients:
            command=[str(java),'-cp',classpath,'org.eclipse.kura.web.server.keybackup.PrivateArchivePeerProbe',str(root/'core-private')]
        if recovery_history and uid==65533 and len(clients)==1:
            command=[sys.executable,'-B','-c',RECEIVER_PEER,str(source),str(root)]
        process=subprocess.Popen(command,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,preexec_fn=lambda:drop(uid),cwd='/')
        clients.append(process);assert process.stdout.readline().strip()=='CLIENT_READY';return process
    def ask(process,request):
        process.stdin.write(json.dumps(request)+'\n');process.stdin.flush()
        assert select.select([process.stdout],[],[],12)[0],'original peer response remains unconfirmed'
        response=process.stdout.readline();assert response,process.stderr.read();return json.loads(response)
    try:
        core=client(65534);recovery=client(65533);rogue=client(65533 if recovery_history else 65534)
        expected.write_text(json.dumps(dict(core=core.pid,recovery=recovery.pid)));expected.chmod(0o600)
        server=subprocess.Popen([sys.executable,'-B','-c',WORKER,str(source),str(root),str(expected),str(stop),str(listener.fileno())]
            +(['recovery-history'] if recovery_history else ['private-history'] if private_history else ['private-fences'] if private_fences else []),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,preexec_fn=lambda:drop(0),pass_fds=(listener.fileno(),),cwd='/')
        assert server.stdout.readline().strip()=='ARCHIVE_ROOT_READY'
        binding=dict(schema=1,action='gwt-sender-bind',**namespace,dataDirectory=str(root/'core-private') if java else '/core-private',
            dataUid=65534,dataDevice=str((root/'core-private').stat().st_dev),dataInode=str((root/'core-private').stat().st_ino))
        value=ask(core,binding);assert value['state']=='GWT_SENDER_BOUND';persisted={k:v for k,v in value.items() if k!='state'}
        def bound(request):return dict(schema=1,action='gwt-bound-request',binding=persisted,request=request)
        if recovery_history:check_recovery_history(manager,root,namespace,ask,core,recovery,rogue,seed)
        elif private_history:check_private_history(manager,root,namespace,ask,core,recovery,rogue,bound,seed)
        elif private_fences:check_private_fences(manager,root,namespace,ask,core,recovery,rogue,bound,java is not None)
        else:
            def plan(index):return dict(schema=1,action='journal-archive-plan',namespaceSha256=namespace['namespaceSha256'],
                entries=[dict(directory='sender-admissions',operationId=rows[index]['admissionId'])])
            assert ask(core,plan(0))['error']=='FORBIDDEN'
            assert ask(rogue,bound(plan(0)))['error']=='UNMANAGED_CORE'
            first=None
            for index,(peer,wrap) in enumerate([(core,bound),(recovery,lambda value:value)]):
                value=ask(peer,wrap(plan(index)));assert value['state']=='ARCHIVE_PLAN'
                request=dict(plan(index),action='journal-archive',archiveId=str(uuid.uuid4()),expectedEntriesSha256=value['entriesSha256'])
                result=ask(peer,wrap(request));assert result['state']=='ARCHIVE_RECORDED'
                assert result['credentialsChanged'] is False and result['startRequested'] is False
                read=dict(schema=1,action='journal-archive-read',namespaceSha256=namespace['namespaceSha256'],archiveId=request['archiveId'])
                assert ask(peer,wrap(read))==result
                if first is None:first=request
            assert ask(recovery,dict(first,action='journal-archive-continue'))['error']=='CONFLICT'
            old=rows[0]['target'];native=dict(schema=1,action='backup-create',operationId=old['operationId'],passphrase='synthetic-closed-history')
            late=dict(schema=1,action='sender-reserve',admissionId=str(uuid.uuid4()),source='gwt',namespaceSha256=namespace['namespaceSha256'],request=bound(native))
            assert ask(core,late)['error']=='CONFLICT'
        assert originals=={p.name:(p.read_bytes(),p.stat()) for p in manager.sender_admissions.directory.iterdir() if p.name in originals}
        stop.touch();out,error=server.communicate(timeout=8);assert server.returncode==0,error
        result=json.loads(out);result['testedNativeSourceSha256']={name:hashlib.sha256((source/name).read_bytes()).hexdigest()
            for name in ('kura_key_service.py','kura_key_service_lifecycle.py','kura_key_store.py','kura_key_journal.py')+
                (('kura_key_recovery.py','kura_key_recovery_setup.py') if recovery_history else ())}
        result.update(originalAdmissionBytesAndMetadataExact=True,lateClosedOriginalRefused=not recovery_history,gwtRawMetadataRefused=True,
            foreignSameUidPidRefused=True,crossSourceContinuationRefused=not private_fences and not private_history and not recovery_history,
            crossSourcePrivateProofReadRefused=private_fences,unknownRedispatched=False)
        if java:result.update(actualJavaPrivateArchive=True,privateOriginalCount=4 if private_history else 65,javaBytecodeRelease=11,javaRuntimeFloor=21,
            unicodePrivateReceiptMatched=True,humanGwtSession=False)
        if private_history:result.update(nativeOriginalBytesAndMetadataExact=True,claimedIntakeReadDidNotRewriteOriginal=True,
            rootArchiveAdoptedWithoutNewId=True,privateOriginalBytesAndMetadataExact=True,latePrivateWriterCallbacks=0,
            modeledHistoricalBackupBody=True)
        if recovery_history:result.update(nativeOriginalBytesAndMetadataExact=True,claimedIntakeReadDidNotRewriteOriginal=True,
            privateOriginalBytesAndMetadataExact=True,latePrivateWriterCallbacks=0,independentFullPackageRecoveryReader=True,
            installerStateReaderAcceptedWithoutRewriting=True,accountMappingsModeled=True,
            ordinaryArchiveSourceAuthorizationActual=True,installedRecoveryAndHumanHttpsSession=False)
        print(json.dumps(result))
    finally:
        for peer in clients:
            peer.stdin.close()
            try:peer.wait(timeout=5)
            except subprocess.TimeoutExpired:peer.terminate();peer.wait(timeout=5)
        if server is not None and server.poll() is None:stop.touch();server.wait(timeout=8)
        listener.close()


if __name__=='__main__':
    if sys.argv[1:]==['--client']:
        print('CLIENT_READY',flush=True)
        for line in sys.stdin:print(json.dumps(rpc(json.loads(line))),flush=True)
    else:
        parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repository',type=Path,required=True)
        parser.add_argument('--private-fences',action='store_true');parser.add_argument('--private-history',action='store_true')
        parser.add_argument('--recovery-history',action='store_true')
        parser.add_argument('--java',type=Path);parser.add_argument('--classpath');args=parser.parse_args()
        assert sum((args.private_fences,args.private_history,args.recovery_history))<=1
        if args.java is not None:assert (args.private_fences or args.private_history) and args.classpath
        if args.private_history:assert args.java is not None
        main(args.repository.resolve(),args.private_fences,args.java,args.classpath,args.private_history,args.recovery_history)
