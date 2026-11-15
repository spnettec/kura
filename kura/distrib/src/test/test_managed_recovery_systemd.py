#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh-only actual PID1 credentials and the packaged Java recovery loader.

No Main Core, CM application, key publication or historical operation is run.
Synthetic credentials are removed with the owning disposable container.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import sys
import unittest
import uuid

import test_key_generation_cohort as package

OPTIONS=None


class ManagedRecoverySystemdTest(unittest.TestCase):
    copy=staticmethod(package.GenerationPackageTest.copy)

    def command(self,*arguments):
        result=subprocess.run(list(map(str,arguments)),capture_output=True,text=True,timeout=60)
        self.assertEqual(0,result.returncode,result.stderr[-1500:])
        return result.stdout

    def setUp(self):
        if OPTIONS is None:self.skipTest('Requires explicit disposable fixture')
        self.assertEqual('linux',sys.platform);self.assertEqual(0,os.geteuid())
        self.assertTrue(Path('/.dockerenv').is_file())
        self.assertEqual('systemd',Path('/proc/1/comm').read_text().strip())
        self.unit=Path('/etc/systemd/system/kura-managed-reader-probe.service')
        self.credentials=Path('/fixtures/managed-credentials')
        self.inputs=Path('/var/lib/kura-managed-reader-probe')
        for path in [self.unit,self.credentials,self.inputs,Path('/opt/eclipse/kura'),Path('/etc/kura'),Path('/var/lib/kura-key-service')]:
            self.assertFalse(os.path.lexists(path),'Never adopt an installed Core, credentials or retained runtime')
        try:pwd.getpwnam('kurad')
        except KeyError:pass
        else:self.fail('Never adopt an existing Kura identity')
        package.GenerationPackageTest.setUp(self)
        self.policy.generation_assets()  # Actual paired JARs and required interfaces, not a metadata-only fake.
        self.home.parent.chmod(0o755)
        Path('/opt/eclipse').mkdir(parents=True,exist_ok=True)
        Path('/opt/eclipse').chmod(0o755)
        shutil.move(str(self.home),'/opt/eclipse/kura');self.home=Path('/opt/eclipse/kura')
        for path in [self.home,*self.home.rglob('*')]:path.chmod(0o755 if path.is_dir() else 0o644)
        self.credentials.mkdir(parents=True,mode=0o700)
        self.inputs.mkdir(mode=0o700)
        old=secrets.token_bytes(16);active=secrets.token_bytes(32);alternate=secrets.token_bytes(32)
        ring=package.service.encode_key_generations([old,active],1,0)
        for name,value in [('old',old),('active',active),('alternate',alternate),('ring',ring),('malformed',b'not-a-ring')]:
            path=self.credentials/name;path.write_bytes(value);path.chmod(0o600)
        self.hashes={name:hashlib.sha256((self.credentials/name).read_bytes()).hexdigest()
                     for name in ['active','alternate','ring','malformed']}
        offline=self.home/package.cohort.OFFLINE
        self.classpath=str(OPTIONS.repository/'kura/tools/kura-offline-recovery/target/test-classes')+':'+str(offline)+':'+str(offline.parent/'lib/*')
        self.probe='org.eclipse.kura.tools.recovery.ManagedCredentialProbe'
        self.java=[str(OPTIONS.java),'-Xms16m','-Xmx128m','-XX:MaxMetaspaceSize=64m','-XX:ActiveProcessorCount=1',
                   '-XX:+UseSerialGC','-XX:+DisableAttachMechanism','-XX:+PerfDisableSharedMem','-cp',self.classpath,self.probe]
        self.assertEqual('',self.command(*self.java,'seed',self.credentials))
        self.command('/usr/sbin/useradd','--system','--user-group','--no-create-home','--shell','/usr/sbin/nologin','kurad')
        account=pwd.getpwnam('kurad');self.owner=(account.pw_uid,account.pw_gid)
        os.chown(self.inputs,*self.owner)
        for name in ('mixed.xml','mixed-old.aes','mixed-current.aes','single.xml','single.aes'):
            self.copy(self.credentials/name,self.inputs/name);(self.inputs/name).chmod(0o600);os.chown(self.inputs/name,*self.owner)
        self.before=self.snapshot()

    def snapshot(self):
        result={}
        for path in self.credentials.iterdir():
            s=path.stat();result[path.name]=(hashlib.sha256(path.read_bytes()).hexdigest(),s.st_ino,s.st_uid,s.st_gid,s.st_mode,s.st_mtime_ns,s.st_ctime_ns)
        return result

    def run_case(self,profile,name,artifact,key,ring,expected_key,expected_ring,accepted,count):
        request=self.inputs/'request.properties'
        manifest=dict(schema='1',**{'restore.id':'rec-'+str(uuid.uuid4()),'snapshot.path':str(self.inputs/artifact),
            'snapshot.sha256':hashlib.sha256((self.inputs/artifact).read_bytes()).hexdigest(),
            'snapshot.mode':'aes-gcm' if artifact.endswith('.aes') else 'plain','password.policy':'authenticated',
            'receipt.path':str(self.inputs/'unused-receipt'),'crypto.systemd.credentials':'true',
            'crypto.key.sha256':expected_key,'crypto.ring.sha256':expected_ring})
        request.write_text(''.join(k+'='+v+'\n' for k,v in sorted(manifest.items())))
        request.chmod(0o600);os.chown(request,*self.owner)
        capabilities=['NoNewPrivileges=yes','CapabilityBoundingSet=','AmbientCapabilities=']
        if profile=='core-capabilities':
            source=(package.SOURCE/'filtered/pkg/install/kura.service').read_text().splitlines()
            capabilities=['NoNewPrivileges=no']
            for option in ['CapabilityBoundingSet=','AmbientCapabilities=']:
                lines=[line for line in source if line.startswith(option)];self.assertEqual(1,len(lines));capabilities+=lines
        unit=['[Unit]','Description=Disposable managed credential reader probe','StartLimitIntervalSec=0','[Service]','Type=oneshot','RemainAfterExit=yes',
              'User=kurad','Group=kurad','UMask=0077','ProtectSystem=strict','ProtectHome=yes','PrivateTmp=yes',
              'InaccessiblePaths=/fixtures/managed-credentials','ProtectControlGroups=yes','MemoryMax=256M','TasksMax=64',
              'LimitCORE=0','LimitMEMLOCK=0',*capabilities]
        if key:unit+=['LoadCredential=kura_encryption_key:'+str(self.credentials/key)]
        if ring:unit+=['LoadCredential=kura_encryption_keyring:'+str(self.credentials/ring)]
        unit+=['ExecStart='+' '.join(self.java+['read' if accepted else 'reject',str(request),str(count)])]
        self.unit.write_text('\n'.join(unit)+'\n');self.unit.chmod(0o644)
        self.command('/usr/bin/systemctl','daemon-reload')
        start=subprocess.run(['/usr/bin/systemctl','start',self.unit.name],capture_output=True,text=True,timeout=60)
        invocation=self.command('/usr/bin/systemctl','show',self.unit.name,'-p','InvocationID','--value').strip()
        log=self.command('/usr/bin/journalctl','--no-pager','-o','cat','_SYSTEMD_INVOCATION_ID='+invocation)
        self.assertEqual(0,start.returncode,name+': '+log[-2000:])
        marker='MANAGED_CREDENTIAL_READER_OK' if accepted else 'MANAGED_CREDENTIAL_REJECTED'
        self.assertIn(marker,log,name)
        self.assertEqual('0',self.command('/usr/bin/systemctl','show',self.unit.name,'-p','ExecMainStatus','--value').strip())
        self.command('/usr/bin/systemctl','stop',self.unit.name)
        self.assertFalse((self.inputs/'unused-receipt').exists())
        self.assertEqual(self.before,self.snapshot())

    def test_actual_pid1_loaded_credentials_bind_exact_keys_and_never_fallback(self):
        sha=self.hashes
        cases=[
            ('single-plain','single.xml','active',None,sha['active'],'none',True,1),
            ('single-aes','single.aes','active',None,sha['active'],'none',True,1),
            ('generations-plain','mixed.xml','active','ring',sha['active'],sha['ring'],True,2),
            ('generations-old-aes','mixed-old.aes','active','ring',sha['active'],sha['ring'],True,2),
            ('generations-new-aes','mixed-current.aes','active','ring',sha['active'],sha['ring'],True,2),
            ('missing-ring','mixed.xml','active',None,sha['active'],sha['ring'],False,0),
            ('unexpected-ring','single.xml','active','ring',sha['active'],'none',False,0),
            ('wrong-key-fingerprint','mixed.xml','active','ring','0'*64,sha['ring'],False,0),
            ('wrong-ring-fingerprint','mixed.xml','active','ring',sha['active'],'0'*64,False,0),
            ('active-ring-mismatch','mixed.xml','alternate','ring',sha['alternate'],sha['ring'],False,0),
            ('malformed-ring','mixed.xml','active','malformed',sha['active'],sha['malformed'],False,0),
            ('missing-key','mixed.xml',None,'ring',sha['active'],sha['ring'],False,0),
            ('no-credential-directory','mixed.xml',None,None,sha['active'],sha['ring'],False,0),
        ]
        passed=0
        for profile in ['empty-capabilities','core-capabilities']:
            for case in cases:
                with self.subTest(profile=profile,case=case[0]):
                    self.run_case(profile,*case);passed+=1
        helper=self.home/'bin/kura_key_store.py';original=helper.read_text()
        mutations=[('stale-inode','identity=(m.st_dev,m.st_ino,','identity=(m.st_dev,m.st_ino+1,'),
                   ('bad-receipt-version','LOADED_CREDENTIAL_PROOF_PROTOCOL = 1','LOADED_CREDENTIAL_PROOF_PROTOCOL = 2'),
                   ('wrong-receipt-digest',"*identity,hashlib.sha256(value).hexdigest()","*identity,'0'*64")]
        try:
            for profile in ['empty-capabilities','core-capabilities']:
                for name,old,new in mutations:
                    with self.subTest(profile=profile,receipt=name):
                        self.assertEqual(1,original.count(old));helper.write_text(original.replace(old,new))
                        self.run_case(profile,name,'mixed.xml','active','ring',sha['active'],sha['ring'],False,0);passed+=1
        finally:helper.write_text(original)
        expected=2*(len(cases)+len(mutations))
        self.assertEqual(expected,passed,'Every case must pass before publishing the success marker')
        self.assertFalse(Path('/var/lib/kura-key-service').exists())
        self.assertFalse(Path('/run/kura-key-service').exists())
        print('MANAGED_RECOVERY_SYSTEMD_OK '+json.dumps(dict(profiles=2,scenariosPerProfile=len(cases)+len(mutations),
              receiptTamperScenariosPerProfile=len(mutations),jvms=expected,
              actualPid1Credentials=True,privateSourceHidden=True,oldAndNewData=True,keysUnchanged=True,
              mainStarted=False,cmApplied=False,unknownRedispatched=False),sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repository',required=True,type=Path)
    parser.add_argument('--java',required=True,type=Path)
    parser.add_argument('--disposable-fixture',required=True,action='store_true')
    OPTIONS,remaining=parser.parse_known_args()
    OPTIONS.repository=OPTIONS.repository.resolve();OPTIONS.java=OPTIONS.java.resolve();package.CONFIG=OPTIONS.repository
    unittest.main(argv=[sys.argv[0],*remaining])
