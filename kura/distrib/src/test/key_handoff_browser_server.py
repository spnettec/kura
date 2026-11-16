#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Loopback TLS browser fixture. Production Handler/controller, synthetic Root only.

No installed gateway, Unix Root socket, data key, systemd action or customer data.
The synthetic capability is sent only to the owning test process over stdout.
"""
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading

import test_key_handoff_recovery as model
from sender_admission_model import SenderModel

temporary = tempfile.TemporaryDirectory(prefix='kura-browser-handoff-')
directory = Path(temporary.name)
key, certificate = directory/'tls.key', directory/'tls.crt'
subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
    '-subj','/CN=localhost','-keyout',str(key),'-out',str(certificate)], check=True,
    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.minimum_version = ssl.TLSVersion.TLSv1_2
tls.load_cert_chain(certificate,key)
assets = Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/share/key-recovery'
server = None; sequence = 0

def reset():
    global root, journal, sequence
    sequence += 1; state = directory/('case-'+str(sequence)); state.mkdir(mode=0o700)
    root = model.Root(); journal = model.recovery.Journal(state)
    controller = model.recovery.Controller(root,journal, sender=SenderModel())
    if server is not None:
        server.controller = controller; server.handoffs = model.recovery.HandoffController(root,journal, sender=SenderModel())
    return controller

controller = reset()
server = model.recovery.RecoveryServer(('127.0.0.1',0),controller,tls,assets)
worker = threading.Thread(target=server.serve_forever,daemon=True); worker.start()

def describe():
    return dict(url='https://127.0.0.1:'+str(server.server_port),token=root.token,handoffId=root.info['handoffId'])

print(json.dumps(describe()),flush=True)
try:
    for line in sys.stdin:
        request = json.loads(line); command = request['command']
        if command == 'reset':
            reset(); response = describe()
        elif command == 'set':
            for name,value in request['values'].items():
                if name == 'expired': root.info['mutationWindowOpen'] = not value
                else:
                    assert name in ('partial','absent','loss') and type(value) is bool
                    setattr(root,name,value)
            response = dict(ok=True)
        elif command == 'stats':
            files = list(journal.directory.rglob('*.json'))
            response = dict(writes=root.writes,rootCalls=len(root.calls),
                bearerOnDisk=any(root.token.encode() in path.read_bytes() for path in files),metadataFiles=len(files))
        elif command == 'stop':
            print(json.dumps(dict(ok=True)),flush=True); break
        else: raise ValueError('Unknown fixture control')
        print(json.dumps(response),flush=True)
finally:
    server.shutdown(); server.server_close(); worker.join(timeout=3); temporary.cleanup()
