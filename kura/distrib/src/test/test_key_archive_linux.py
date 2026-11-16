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
for name in ('core-private','recovery-private'):
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
assert not list(manager.operations.iterdir()) and not manager.store.path(service.KEY_PATH).exists()
assert len(manager.sender_admissions.records())==4 and len(manager.archives()['archived'])==2
print(json.dumps(dict(rootStatus=root_status,peers=peers,rootPrivateReadsRefused=denied,actions=actions,
    archives=2,originalAdmissions=4,nativeKeyOperations=0,cipherCalls=0,installedMainAndHumanSession=False,
    systemdAndMain='modeled; SO_PEERCRED, process UIDs/caps, transport and archive handlers actual')),flush=True)
'''


def main(repository):
    assert sys.platform=='linux' and os.geteuid()==0 and Path('/.dockerenv').exists()
    assert not Path('/etc/kura').exists() and not Path('/var/lib/kura-key-service').exists()
    source=repository/'kura/distrib/src/main/resources/unfiltered/pkg/bin';sys.path.insert(0,str(source))
    import kura_key_service as service
    work=Path(tempfile.mkdtemp(prefix='root-archive-uds-'));work.chmod(0o755);root=work/'root';root.mkdir(mode=0o755)
    for name,uid in [('core-private',65534),('recovery-private',65533)]:
        path=root/name;path.mkdir(mode=0o700);os.chown(path,uid,uid)
    state=root/'var/lib/kura-key-service';(state/'operations').mkdir(parents=True,mode=0o700)
    for path in (root/'var',root/'var/lib'):path.chmod(0o755)
    state.chmod(0o700)
    for name,raw in [('journal.key',os.urandom(32)),('admission.lock',b''),('sender-admission.lock',b'')]:
        path=state/name;path.write_bytes(raw);path.chmod(0o600)
    manager=service.Manager(root);namespace=manager.gwt_namespace();rows=[]
    for _ in range(4):
        native=dict(schema=1,action='backup-create',operationId=str(uuid.uuid4()),passphrase='synthetic-closed-history')
        rows.append(manager.sender_admissions.write(dict(schema=1,purpose=service.SENDER_ADMISSION_PURPOSE,
            admissionId=str(uuid.uuid4()),source='local-admin',namespaceSha256=namespace['namespaceSha256'],
            owner=dict(uid=0,pid=os.getpid(),startTicks=manager.writer_process(os.getpid())[1],bootId=Path('/proc/sys/kernel/random/boot_id').read_text().strip()),
            requestTag=manager.sender_admissions.tag(native),target=manager.sender_admissions.native_target(native),parentAdmissionId=None,state='NOT_ADMITTED'),create=True))
    originals={p.name:(p.read_bytes(),p.stat()) for p in manager.sender_admissions.directory.iterdir()}
    run=Path('/run/kura-key-service');run.mkdir(mode=0o755)
    listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listener.bind(str(run/'control.sock'));listener.listen(8)
    os.chown(run/'control.sock',0,65534);os.chmod(run/'control.sock',0o660)
    clients=[];server=None;stop=work/'stop';expected=work/'expected.json'
    def client(uid):
        process=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--client'],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,preexec_fn=lambda:drop(uid),cwd='/')
        clients.append(process);assert process.stdout.readline().strip()=='CLIENT_READY';return process
    def ask(process,request):
        process.stdin.write(json.dumps(request)+'\n');process.stdin.flush()
        assert select.select([process.stdout],[],[],12)[0],'original peer response remains unconfirmed'
        response=process.stdout.readline();assert response,process.stderr.read();return json.loads(response)
    try:
        core=client(65534);recovery=client(65533);rogue=client(65534)
        expected.write_text(json.dumps(dict(core=core.pid,recovery=recovery.pid)));expected.chmod(0o600)
        server=subprocess.Popen([sys.executable,'-B','-c',WORKER,str(source),str(root),str(expected),str(stop),str(listener.fileno())],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,preexec_fn=lambda:drop(0),pass_fds=(listener.fileno(),),cwd='/')
        assert server.stdout.readline().strip()=='ARCHIVE_ROOT_READY'
        binding=dict(schema=1,action='gwt-sender-bind',**namespace,dataDirectory='/core-private',
            dataUid=65534,dataDevice=str((root/'core-private').stat().st_dev),dataInode=str((root/'core-private').stat().st_ino))
        value=ask(core,binding);assert value['state']=='GWT_SENDER_BOUND';persisted={k:v for k,v in value.items() if k!='state'}
        def bound(request):return dict(schema=1,action='gwt-bound-request',binding=persisted,request=request)
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
        assert originals=={p.name:(p.read_bytes(),p.stat()) for p in manager.sender_admissions.directory.iterdir()}
        stop.touch();out,error=server.communicate(timeout=8);assert server.returncode==0,error
        result=json.loads(out);result['testedNativeSourceSha256']={name:hashlib.sha256((source/name).read_bytes()).hexdigest()
            for name in ('kura_key_service.py','kura_key_service_lifecycle.py','kura_key_store.py')}
        result.update(originalAdmissionBytesAndMetadataExact=True,lateClosedOriginalRefused=True,gwtRawMetadataRefused=True,
            foreignSameUidPidRefused=True,crossSourceContinuationRefused=True,unknownRedispatched=False)
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
        main(parser.parse_args().repository.resolve())
