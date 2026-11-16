#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""New loopback HTTPS metadata fixture. Root, decryption, systemd and results are models."""
import argparse
import hashlib
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
import uuid

from test_key_receiver_admission_recovery import AdmissionRoot, recovery, protocol, BACKUP, PASSWORD, SHA

parser=argparse.ArgumentParser();parser.add_argument('--listen-host',default='127.0.0.1');parser.add_argument('--listen-port',type=int,default=0)
parser.add_argument('--public-port',type=int);options=parser.parse_args()
temporary=tempfile.TemporaryDirectory(prefix='kura-receiver-admission-browser-');directory=Path(temporary.name)
key,certificate=directory/'tls.key',directory/'tls.crt'
subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost',
    '-keyout',str(key),'-out',str(certificate)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_2;tls.load_cert_chain(certificate,key)
assets=Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/share/key-recovery'
server=None;sequence=0

def reset(kind='restore',maintenance=False):
    global root,journal,sender,identity,restore_id,selected,sequence
    selected=kind;sequence+=1;state=directory/('case-'+str(sequence));state.mkdir(mode=0o700)
    root=AdmissionRoot();journal=recovery.Journal(state);sender=recovery.SenderAdmission(root,journal)
    identity=str(uuid.uuid4());restore_id=str(uuid.uuid4())
    if kind in ('restore','start'):
        request=dict(schema=1,action='restore' if kind=='restore' else 'core-start',operationId=identity,expectedKeySha256=SHA)
        if kind=='restore':request.update(backup=BACKUP,passphrase=PASSWORD)
        else:
            request['restoreOperationId']=restore_id;root.cold.key_ready=True
            if maintenance:
                request.update(action='core-start-after-maintenance',predecessorStartOperationId=str(uuid.uuid4()),
                    maintenanceId=str(uuid.uuid4()),manifestSha256='a'*64)
            journal.admit(dict(schema=1,operationId=restore_id,expectedKeySha256=SHA,backupSha256=hashlib.sha256(protocol.encode(BACKUP)).hexdigest()))
            journal.mark(restore_id,SHA)
            root.cold.records[restore_id]=dict(schema=1,operationId=restore_id,state='SUCCEEDED',action='restore',keySha256=SHA,keyChanged=True,existingReceiptPreserved=True)
    else:
        identity=root.handoff.info['startOperationId' if kind=='handoff-start' else 'publicationId']
        request=dict(schema=1,action='generation-handoff-command',command='start' if kind=='handoff-start' else kind,token=root.handoff.token)
        if kind=='handoff-start':root.handoff.publication=root.handoff.published()
        if kind=='continue':
            request['expectedRecoveryReceiptSha256']='a'*64;root.handoff.receipt='a'*64
            root.handoff.publication=dict(schema=1,operationId=identity,state='UNKNOWN')
    try:sender.submit(kind,identity,request,lambda:(_ for _ in ()).throw(AssertionError('No native callback in metadata fixture')))
    except OSError:pass
    controller=recovery.Controller(root,journal,sender)
    if server is not None:server.controller=controller;server.handoffs=recovery.HandoffController(root,journal,sender)
    return controller

controller=reset();server=recovery.RecoveryServer((options.listen_host,options.listen_port),controller,tls,assets)
# Docker publishes this test listener only on host loopback. Keep production Host/Origin checks intact.
if options.public_port is not None:server.server_port=options.public_port
worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()

def describe():return dict(url='https://'+('localhost' if options.public_port is not None else '127.0.0.1')+':'+str(server.server_port),kind=selected,operationId=identity,restoreOperationId=restore_id,
    expectedKeySha256=SHA,backupJson=json.dumps(BACKUP),passphrase=PASSWORD,token=root.handoff.token,
    startIntent=recovery.receiver_start_intent(sender.load('start',identity)[0]) if selected=='start' else None,platform=sys.platform)

print(json.dumps(describe()),flush=True)
try:
    for line in sys.stdin:
        value=json.loads(line);command=value['command']
        if command=='reset':reset(value.get('kind','restore'),value.get('maintenance',False));reply=describe()
        elif command=='set':
            if 'phase' in value:next(iter(root.records.values()))['state']=value['phase']
            if 'loseClose' in value:root.lose_close=value['loseClose']
            if value.get('releaseThrottle'):server.controller.last_inspect=None
            if value.get('foreignNamespace'):root.namespace='d'*64
            if value.get('privateIntent'):
                if selected=='restore':journal.admit(dict(schema=1,operationId=identity,expectedKeySha256=SHA,backupSha256=hashlib.sha256(protocol.encode(BACKUP)).hexdigest()))
                elif selected=='start':journal.write_new(journal.starts/(identity+'.json'),recovery.receiver_start_intent(sender.load('start',identity)[0]))
            if value.get('pendingMarker'):journal.mark(identity,SHA)
            if value.get('archiveInterrupted'):server.controller.journal.retire_pending=lambda *args:(_ for _ in ()).throw(OSError('modeled archive interruption'))
            if value.get('releaseArchive'):server.controller.journal.retire_pending=recovery.Journal.retire_pending.__get__(journal)
            if value.get('privateHandoff'):
                binding=server.handoffs.binding(root.handoff.info);slot=server.handoffs.directory/binding['handoffId']
                slot.mkdir(mode=0o700);journal.sync(slot.parent);journal.write_new(slot/'binding.json',binding)
                if value['privateHandoff']!='binding-only':journal.write_new(slot/'publish.json',dict(binding,command='publish'))
            if 'loseRevoke' in value:root.lose_revoke=value['loseRevoke']
            if value.get('retirementInterrupted'):
                write=journal.write_new
                def interrupted(path,value):
                    if path.name=='retired.json':raise OSError('modeled private disposition interruption')
                    return write(path,value)
                journal.write_new=interrupted
            if value.get('releaseRetirement'):journal.write_new=recovery.Journal.write_new.__get__(journal)
            reply=dict(ok=True)
        elif command=='stats':
            files=list(journal.directory.rglob('*.json'))
            reply=dict(nativeKeyWrites=root.native_writes,closes=root.closes,reservations=len(root.records),
                phase=next(iter(root.records.values()))['state'],closedReceipts=len(list(sender.directory.rglob('closed.json'))),
                credentialsOnDisk=any(PASSWORD.encode() in p.read_bytes() or root.handoff.token.encode() in p.read_bytes() for p in files),
                pendingMarkerActive=journal.pending() is not None,archivedPendingMarkers=len(list(sender.directory.glob('*/pending.json'))),
                privateRestoreFiles={p.name:dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),inode=p.stat().st_ino,
                    uid=p.stat().st_uid,gid=p.stat().st_gid,mode=p.stat().st_mode,nlink=p.stat().st_nlink,
                    mtimeNs=p.stat().st_mtime_ns,ctimeNs=p.stat().st_ctime_ns) for p in journal.operations.iterdir()},
                privateStartFiles={p.name:dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),inode=p.stat().st_ino,
                    uid=p.stat().st_uid,gid=p.stat().st_gid,mode=p.stat().st_mode,nlink=p.stat().st_nlink,
                    mtimeNs=p.stat().st_mtime_ns,ctimeNs=p.stat().st_ctime_ns) for p in journal.starts.iterdir()},
                revocations=root.revocations,retiredHandoffs=len(list(server.handoffs.directory.glob('*/retired.json'))),
                privateHandoffFiles={str(p.relative_to(journal.directory)):dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),inode=p.stat().st_ino,
                    mtimeNs=p.stat().st_mtime_ns,ctimeNs=p.stat().st_ctime_ns) for p in server.handoffs.directory.rglob('*.json')})
        elif command=='stop':print(json.dumps(dict(ok=True)),flush=True);break
        else:raise ValueError('Unknown fixture command')
        print(json.dumps(reply),flush=True)
finally:
    server.shutdown();server.server_close();worker.join(3);temporary.cleanup()
