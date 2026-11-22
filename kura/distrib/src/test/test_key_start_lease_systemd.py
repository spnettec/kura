#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""One owned installed-Core first-start lease, driven by the actual recovery page.

Only installation/probe helpers are shared. Historical closed tests and IDs are
never invoked. The original 900-second grant expires on the real boot clock.
The original authority is issued by local Root, not a GWT ADMIN/XSRF session.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import ssl
import struct
import subprocess
import sys
import time
import unittest
import uuid

import test_key_generation_core_systemd as install

OPTIONS = None
RUN = Path('/run/kura-start-lease-native')


def raw_rpc(request, timeout=75):
    data = json.dumps(request, sort_keys=True, separators=(',', ':')).encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(timeout); stream.connect('/run/kura-key-service/control.sock')
        stream.sendall(struct.pack('!I', len(data)) + data); stream.shutdown(socket.SHUT_WR)
        def read(size):
            value = bytearray()
            while len(value) < size:
                chunk = stream.recv(size-len(value))
                if not chunk: raise RuntimeError('Original connection ended; never redispatch')
                value.extend(chunk)
            return bytes(value)
        size = struct.unpack('!I', read(4))[0]
        if not 0 < size <= 65536: raise RuntimeError('Original frame size refused')
        reply = json.loads(read(size)); assert stream.recv(1) == b''
        return reply


def write_new(path, value):
    data = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as out: out.write(data); out.flush(); os.fsync(fd)
    finally: os.close(fd)
    fd = os.open(path.parent, os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def file_identity(path):
    m = path.lstat()
    return dict(dev=m.st_dev,ino=m.st_ino,uid=m.st_uid,gid=m.st_gid,mode=m.st_mode&0o7777,
        nlink=m.st_nlink,size=m.st_size,mtimeNs=m.st_mtime_ns,ctimeNs=m.st_ctime_ns,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def process_status(pid):
    wanted = ('Uid','Gid','CapEff','CapBnd','CapAmb','NoNewPrivs')
    result = {k:v.strip() for k,v in (line.split(':',1) for line in Path('/proc',str(pid),'status').read_text().splitlines() if ':' in line) if k in wanted}
    result['startTicks'] = Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]
    result['pid'] = pid
    return result


class NativeStartLeaseSystemdTest(unittest.TestCase):
    step = install.CoreGenerationTest.step
    run_command = install.CoreGenerationTest.run_command
    install_probe = install.CoreGenerationTest.install_probe
    wait_probe = install.CoreGenerationTest.wait_probe
    assert_providers = install.CoreGenerationTest.assert_providers

    def setUp(self):
        if OPTIONS is None: self.skipTest('Explicit fresh disposable installed-Core fixture required')
        install.OPTIONS = OPTIONS
        install.CoreGenerationTest.setUp(self)
        RUN.mkdir(mode=0o700)

    def rpc(self, request):
        if self.service.sender_mutation(request):
            realm = raw_rpc(dict(schema=1,action='gwt-sender-namespace'))['namespaceSha256']
            identity = request.get('handoffId',request.get('operationId')); admission = str(uuid.uuid4())
            write_new(RUN/(identity+'-local-intent.json'),dict(action=request['action'],nativeOperationId=identity,
                admissionId=admission,namespaceSha256=realm))
            frame = dict(schema=1,action='sender-reserve',admissionId=admission,source='local-admin',namespaceSha256=realm,request=request)
            reserved = raw_rpc(frame)
            self.assertEqual('RESERVED',reserved.get('state'),reserved.get('error'))
            self.assertIs(reserved.get('newlyReserved'),True)
            reply = raw_rpc(dict(frame,action='sender-command'))
        else: reply = raw_rpc(request)
        self.assertNotIn('error',reply,reply.get('error'))
        return reply

    def wait(self, callback, seconds=1800):
        deadline = time.monotonic()+seconds
        while time.monotonic()<deadline:
            value = callback()
            if value: return value
            time.sleep(0.25)
        self.fail('Original owned request remains unconfirmed; preserve this fixture and all IDs')

    def unit_pid(self, name):
        return int(self.run_command(['systemctl','show',name,'-p','MainPID','--value']).strip())

    @staticmethod
    def credentials():
        return {p.name:file_identity(p) for p in Path('/etc/kura/credentials').iterdir() if p.is_file()}

    def succeeded(self, identity):
        value = self.manager.record(identity)
        return value if value is not None and value['state']=='SUCCEEDED' else None

    def test_actual_recovery_main_and_browser_renew_only_the_original_first_start(self):
        self.run_command(['systemctl','start','kura-key-service.socket','kura-key-recovery.service'])
        self.run_command(['systemctl','start','kura.service'])
        before = self.wait_probe(); self.assert_providers(before); old_pid = int(before['pid'])
        root_pid = self.unit_pid('kura-key-service.service'); recovery_pid = self.unit_pid('kura-key-recovery.service')
        peers = dict(root=process_status(root_pid),recovery=process_status(recovery_pid),core=process_status(old_pid))
        for name in ('root','recovery'):
            for k in ('CapEff','CapBnd','CapAmb'):self.assertEqual('0000000000000000',peers[name][k])
            self.assertEqual('1',peers[name]['NoNewPrivs'])
        ids = dict(zip(('preparationId','verificationId','handoffId','publicationId','startOperationId'),[str(uuid.uuid4()) for _ in range(5)]))
        write_new(RUN/'original-ids.json',ids)
        password = uuid.uuid4().hex+uuid.uuid4().hex
        prepared = self.rpc(dict(schema=1,action='generation-prepare',operationId=ids['preparationId'],
            passphrase=password,expectedSource=dict(keySha256=self.original_key_hash,ringSha256=None)))
        self.assertEqual('SUCCEEDED',prepared['state'])
        verified = self.rpc(dict(schema=1,action='generation-backup-verify',operationId=ids['verificationId'],
            preparationId=ids['preparationId'],expectedRingSha256=prepared['generation']['ringSha256'],
            backup=prepared['backup'],passphrase=password));self.assertEqual('SUCCEEDED',verified['state'])
        request = dict(schema=1,action='generation-handoff-create',**ids,expectedRingSha256=prepared['generation']['ringSha256'],
            expectedCohortSha256=self.manager.require_generation_cohort()['cohortSha256'],operator='owned-installed-first-start-lease')
        issued = self.rpc(request);self.assertEqual('GRANT_RECORDED',issued['state']);token=issued['token']
        authority = self.manager.handoff_component().load(ids['handoffId'])
        self.assertEqual(old_pid,authority['owner']['pid'])
        wrong_peer_request = dict(schema=1,action='sender-reserve',admissionId=str(uuid.uuid4()),source='recovery',
            namespaceSha256=raw_rpc(dict(schema=1,action='gwt-sender-namespace'))['namespaceSha256'],request=dict(
                schema=1,action='generation-handoff-command',token=token,command='start-renew',
                operationId=str(uuid.uuid4()),expectedPublicationSha256='0'*64))
        count = len(self.manager.sender_admissions.records())
        wrong = subprocess.run(['runuser','-u','kura-key-recovery','--','python3','-B',__file__,'--probe-peer'],
            input=json.dumps(wrong_peer_request),capture_output=True,text=True,timeout=20)
        self.assertEqual(0,wrong.returncode,wrong.stderr[-600:]);self.assertEqual('FORBIDDEN',json.loads(wrong.stdout).get('error'))
        self.assertEqual(count,len(self.manager.sender_admissions.records()))
        grant_path = self.manager.state/'handoffs'/(ids['handoffId']+'.json');grant_before=file_identity(grant_path)
        certificate = ssl.PEM_cert_to_DER_cert(Path('/etc/kura/recovery-tls/server.crt').read_text())
        write_new(RUN/'browser-session.json',dict(token=token,handoffId=ids['handoffId'],
            certificateSha256=hashlib.sha256(certificate).hexdigest(),sourceHead=OPTIONS.source_head))
        self.step('BROWSER_READY: actual installed Core, Root and recovery Main; original authority issued by local Root')
        published = self.wait(lambda:self.succeeded(ids['publicationId']))['response']
        self.assertEqual(0,self.unit_pid('kura.service'))
        self.assertEqual('SUCCEEDED',published['state']);credentials_after_publication=self.credentials()
        write_new(RUN/'publication-confirmed.json',dict(publicationId=ids['publicationId'],
            expiresBoottimeNs=authority['expiresBoottimeNs'],realBootClockNs=time.clock_gettime_ns(time.CLOCK_BOOTTIME)))
        self.step('PUBLISHED_WAITING_FOR_REAL_EXPIRY: preserve the same original grant and startup ID')
        def lease():
            values=[self.manager.record(p.name[:-5]) for p in self.manager.operations.iterdir()]
            matches=[v for v in values if v['action']=='generation-start-lease' and v['state']=='SUCCEEDED' and v['intent']['handoffId']==ids['handoffId']]
            self.assertLessEqual(len(matches),1)
            return matches[0] if matches else None
        renewed=self.wait(lease);lease_id=renewed['operationId'];response=renewed['response']
        self.assertGreaterEqual(response['issuedBoottimeNs'],authority['expiresBoottimeNs'])
        self.assertEqual(ids['startOperationId'],response['startOperationId'])
        self.assertEqual(credentials_after_publication,self.credentials())
        self.assertEqual(grant_before,file_identity(grant_path));self.assertIsNone(self.manager.record(ids['startOperationId']))
        admission=raw_rpc(dict(schema=1,action='generation-start-admission',ringSha256=published['ringSha256'],activeKeySha256=published['activeKeySha256']))
        self.assertEqual('GENERATION_START_REQUIRED',admission.get('error'))
        write_new(RUN/'lease-verified.json',dict(leaseOperationId=lease_id,originalStartupId=ids['startOperationId'],ordinaryStartupStillFenced=True))
        started=self.wait(lambda:self.succeeded(ids['startOperationId']))['response']
        self.assertEqual('SYSTEMD_JOB_ACCEPTED',started['scope'])
        after=self.wait_probe(previous=old_pid);self.assert_providers(after)
        self.assertEqual(before['originalSha256'],after['originalSha256']);self.assertEqual('true',after['currentHasGeneration'])
        self.assertEqual(published['activeKeySha256'],after['currentKeyId']);self.assertNotEqual(old_pid,int(after['pid']))
        self.assertEqual(grant_before,file_identity(grant_path))
        self.assertEqual(root_pid,self.unit_pid('kura-key-service.service'));self.assertEqual(recovery_pid,self.unit_pid('kura-key-recovery.service'))
        self.assertEqual(peers['root'],process_status(root_pid));self.assertEqual(peers['recovery'],process_status(recovery_pid))
        write_new(RUN/'providers-ready.json',dict(newCorePid=int(after['pid']),originalCipherPreservedAndDecrypted=True,
            currentCipherUsesPublishedKey=True,originalGrantExactMetadataPreserved=True))
        self.wait(lambda:(Path('/var/lib/kura-key-recovery/handoffs')/ids['handoffId']/'completed.json').exists(),120)
        operations=[self.manager.record(p.name[:-5]) for p in self.manager.operations.iterdir()]
        self.assertEqual(5,len(operations));self.assertTrue(all(v['state']=='SUCCEEDED' for v in operations))
        self.assertEqual(6,len(self.manager.sender_admissions.records()))
        result=dict(schema=1,sourceHead=OPTIONS.source_head,packageSha256=OPTIONS.package_sha256,
            scope='actual-installed-single-Core-profile-original-first-start-lease',issuer='local Root; GWT ADMIN/XSRF not exercised',
            actualSystemdRootAndRecoveryMain=True,actualNativeLeaseWrite=True,realGrantExpirySeconds=900,
            originalIds=ids,leaseOperationId=lease_id,originalCorePid=old_pid,newCorePid=int(after['pid']),
            originalStartupIdUnchanged=True,originalGrantExactMetadataPreserved=True,
            originalCipherPreservedAndDecrypted=True,currentCipherUsesPublishedKey=True,ordinaryStartupStillFencedUntilExplicitRequest=True,
            rootAndRecoveryPidsAndTicksUnchanged=True,peers=peers,allFiveNativeOperationsSucceeded=True,
            sameRecoveryUidOtherProcessDeniedBeforeReservation=True,
            runtimeProfile=dict(heapMiB=256,extraBundle='generation DS probe',legacyServiceUnitSeed=True),
            unknownRedispatched=False,gwtHumanSessionAcceptance=False,allProvidersAccepted=False,fullBrokerAccepted=False)
        write_new(RUN/'result.json',result);self.step('INSTALLED_FIRST_START_LEASE_OK '+json.dumps(result,sort_keys=True))


if __name__=='__main__':
    if sys.argv[1:]==['--probe-peer']:
        print(json.dumps(raw_rpc(json.load(sys.stdin))));raise SystemExit(0)
    parser=argparse.ArgumentParser()
    parser.add_argument('--package',type=Path,required=True);parser.add_argument('--package-sha256',required=True)
    parser.add_argument('--source-head',required=True);parser.add_argument('--legacy-baseline',type=Path,required=True)
    parser.add_argument('--java',type=Path,required=True);parser.add_argument('--disposable-fixture',action='store_true',required=True)
    OPTIONS,remaining=parser.parse_known_args();unittest.main(argv=[sys.argv[0],*remaining])
