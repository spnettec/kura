#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh Linux HTTPS/private-file/Root-HMAC fixture. Main, history and backup inspection are models."""
import argparse
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import time

import test_key_recovery_archive as cold
import test_key_recovery_handoff_archive as handoffs

parser=argparse.ArgumentParser()
parser.add_argument('--repository',type=Path,required=True)
parser.add_argument('--java',type=Path,required=True)
parser.add_argument('--cipher-jar',type=Path,required=True)
parser.add_argument('--public-port',type=int,required=True)
args=parser.parse_args()
assert os.geteuid()==0 and os.path.exists('/.dockerenv')
handoffs.original.original.base.package.CONFIG=args.repository.resolve()
handoffs.original.original.base.JAVA=args.java.resolve()
handoffs.original.original.base.CIPHER=args.cipher_jar.resolve()
recovery=cold.recovery
PASSWORD='synthetic browser archive material 52!'
temporary=tempfile.TemporaryDirectory(prefix='recovery-archive-browser-')
directory=Path(temporary.name);key=directory/'tls.key';certificate=directory/'tls.crt'
subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost',
    '-keyout',str(key),'-out',str(certificate)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_2;tls.load_cert_chain(certificate,key)
fixture=None;server=None;mode='healthy';http_loss=False


def reset(kind='RESTORE',count=1):
    global fixture,reference,backup,token,originals,mode,http_loss,atomic
    if fixture is not None:fixture.doCleanups()
    mode='healthy';http_loss=False;token=None
    if kind.startswith('HANDOFF') or kind.startswith('ADMISSION:') and kind.split(':')[1] not in ('restore','start'):
        fixture=handoffs.RecoveryHandoffArchiveTest();fixture.setUp()
        grant,token=fixture.local(completed=kind=='ADMISSION:continue')
        if kind=='HANDOFF':identity=grant['handoffId']
        else:identity=fixture.negative_admission(grant,kind.split(':')[1],completed=kind=='ADMISSION:continue')[0]
        backup=None
    else:
        fixture=cold.RecoveryPrivateArchiveTest();fixture.setUp();identity,_,backup=fixture.restore()
        if kind=='START':identity=fixture.start(identity)[0]
        elif kind.startswith('ADMISSION:'):
            identity=fixture.negative(kind.split(':')[1],backup=backup,restore_identity=identity)[0]
        for _ in range(1,count):fixture.restore()
    parts=kind.split(':');reference=dict(kind=parts[0],operationId=identity,senderKind=parts[1] if len(parts)>1 else None)
    atomic=fixture.manager.atomic
    def metadata_atomic(path,value,**extra):
        if mode=='after-intent' and path.name.endswith('.receipt.json'):raise OSError('modeled archive interruption')
        return atomic(path,value,**extra)
    fixture.manager.atomic=metadata_atomic
    original_client=fixture.client
    def client(request):
        if mode=='offline':raise OSError('modeled offline Root')
        if request['action']=='backup-inspect' and request['passphrase']!=PASSWORD:raise cold.service.Failure('BACKUP_REJECTED')
        return original_client(request)
    fixture.journal.archive_client=client;fixture.history.client=client
    controller=recovery.Controller(client,fixture.journal)
    controller.status=lambda:dict(schema=1,state='UNAVAILABLE')  # Main/key status is outside this metadata fixture.
    archive=controller.archive
    def browser_archive(value):
        global http_loss
        controller.last_inspect=None
        result=archive(value)
        if mode=='delay' and value['command'] in ('query','preview'):time.sleep(.6)
        if http_loss and value['command'] in ('archive','continue'):http_loss=False;raise OSError('modeled lost HTTP reply')
        return result
    controller.archive=browser_archive
    if server is not None:
        server.controller=controller;server.handoffs=recovery.HandoffController(client,fixture.journal)
    originals={str(p):(p.read_bytes(),p.stat()) for p in fixture.directory.rglob('*') if p.is_file()}
    return controller


controller=reset()
assets=args.repository/'kura/distrib/src/main/resources/unfiltered/pkg/share/key-recovery'
server=recovery.RecoveryServer(('0.0.0.0',18443),controller,tls,assets);server.server_port=args.public_port
worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()


def describe():
    return dict(url='https://localhost:'+str(args.public_port),reference=reference,token=token,
        backupJson=json.dumps(backup) if backup else None,passphrase=PASSWORD)


print(json.dumps(describe()),flush=True)
try:
    for line in __import__('sys').stdin:
        request=json.loads(line);command=request['command']
        if command=='reset':reset(request.get('kind','RESTORE'),request.get('count',1));result=describe()
        elif command=='mode':
            mode=request['value'];fixture.lose='before' if mode=='before' else None;http_loss=mode=='lose-http'
            if mode=='stale':
                path=fixture.manager.operations/(reference['operationId']+'.json')
                value=cold.service.decode(path.read_bytes());value['response']['existingReceiptPreserved']=False;atomic(path,cold.service.encode(value))
            result=dict(ok=True)
        elif command=='stats':
            files=list(fixture.directory.rglob('*.json'))
            result=dict(firstSends=sum(v['action']=='journal-archive' for v in fixture.calls),
                continuations=sum(v['action']=='journal-archive-continue' for v in fixture.calls),
                privateOriginalsPreserved=all(p.exists() and (p.read_bytes(),p.stat())==saved for name,saved in originals.items() for p in [Path(name)]),
                secretsOnDisk=any(PASSWORD.encode() in p.read_bytes() or token and token.encode() in p.read_bytes() for p in files),
                archiveIds=sorted(cold.service.decode(p.read_bytes())['request']['archiveId'] for p in (fixture.directory/'archives').glob('*.json')))
        elif command=='stop':print(json.dumps(dict(ok=True)),flush=True);break
        else:raise ValueError('Unknown fixture command')
        print(json.dumps(result),flush=True)
finally:
    server.shutdown();server.server_close();worker.join(3)
    if fixture is not None:fixture.doCleanups()
    temporary.cleanup()
