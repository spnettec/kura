#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh installed Core, actual managed credentials and real controlled CM application.

Only installation helpers are shared with the historical generation test. Its
closed prepare/verify/publish/start test and IDs are never invoked or adopted.
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
import time
import unittest
import uuid
import zipfile

import test_key_generation_core_systemd as install

OPTIONS=None


class ManagedCoreRecoveryTest(unittest.TestCase):
    step=install.CoreGenerationTest.step
    run_command=install.CoreGenerationTest.run_command

    def setUp(self):
        if OPTIONS is None:self.skipTest('Requires explicit disposable installed-Core fixture')
        install.OPTIONS=OPTIONS
        install.CoreGenerationTest.setUp(self)
        self.data=self.home/'data/managed-recovery-probe'
        self.account=pwd.getpwnam('kurad')

    def install_probe(self):
        classes=self.temporary/'classes';classes.mkdir()
        jars=list((self.home/'plugins').rglob('*.jar'))
        source=Path(__file__).resolve().parent/'resources/managed-recovery-probe/ManagedRecoveryProbe.java'
        self.run_command([OPTIONS.java.parent/'javac','--release','21','-encoding','UTF-8','-cp',':'.join(map(str,jars)),'-d',classes,source])
        manifest=('Manifest-Version: 1.0\nBundle-ManifestVersion: 2\nBundle-SymbolicName: org.eclipse.kura.tests.managedrecovery\n'
                  'Bundle-Version: 1.0.0\nBundle-RequiredExecutionEnvironment: JavaSE-21\nService-Component: OSGI-INF/probe.xml\n'
                  'Import-Package: org.eclipse.kura,org.eclipse.kura.crypto,org.eclipse.kura.configuration,\n'
                  ' org.eclipse.kura.core.configuration,org.eclipse.kura.core.crypto,org.osgi.framework,\n'
                  ' org.osgi.framework.startlevel,org.osgi.service.cm,org.osgi.service.component\n\n')
        descriptor=('<component xmlns="http://www.osgi.org/xmlns/scr/v1.4.0" name="managed-recovery-probe" immediate="true" activate="activate">'
                    '<implementation class="org.eclipse.kura.tests.managedrecovery.ManagedRecoveryProbe"/>'
                    '<reference name="crypto" interface="org.eclipse.kura.crypto.CryptoService" bind="setCrypto"/>'
                    '<reference name="configuration" interface="org.eclipse.kura.configuration.ConfigurationService" bind="setConfiguration"/>'
                    '<reference name="admin" interface="org.osgi.service.cm.ConfigurationAdmin" bind="setAdmin"/></component>')
        self.probe=self.home/'plugins/5s/org.eclipse.kura.tests.managedrecovery-1.0.0.jar';self.probe.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(self.probe,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('META-INF/MANIFEST.MF',manifest);archive.writestr('OSGI-INF/probe.xml',descriptor)
            for path in classes.rglob('*.class'):archive.write(path,path.relative_to(classes).as_posix())
        # Explicit test profile: identical copied bootstrap at level 1, no main launcher/code edits.
        self.bootstrap=self.home/'plugins/1s/000-kura-recovery-bootstrap-1.0.0.jar';self.bootstrap.parent.mkdir(exist_ok=True)
        shutil.copyfile(self.home/'libexec/key-recovery/kura-offline-recovery.jar',self.bootstrap)
        self.expected_classes={}
        roles=json.loads((self.home/'libexec/key-backup/manifest.json').read_text())['generation']['readers']
        for role,name in [('crypto','org/eclipse/kura/core/crypto/CryptoServiceImpl.class'),
                          ('configuration','org/eclipse/kura/core/configuration/ConfigurationServiceAuditFacade.class'),
                          ('offline','org/eclipse/kura/tools/recovery/RecoveryBootstrap.class')]:
            with zipfile.ZipFile(self.home/roles[role]) as archive:self.expected_classes[role]=hashlib.sha256(archive.read(name)).hexdigest()

    def private(self,path,data,owner=False):
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        path.write_bytes(data);path.chmod(0o600)
        if owner:os.chown(path,self.account.pw_uid,self.account.pw_gid)

    def args_file(self,path,data):
        path.parent.mkdir(mode=0o750,parents=True,exist_ok=True);path.parent.chmod(0o750)
        os.chown(path.parent,0,self.account.pw_gid)
        path.write_bytes(data);path.chmod(0o640);os.chown(path,0,self.account.pw_gid)

    def wait_probe(self,phase):
        path=self.data/(phase+'.properties');deadline=time.monotonic()+75
        while time.monotonic()<deadline:
            if path.is_file():
                value=dict(line.split('=',1) for line in path.read_text().splitlines() if line and not line.startswith('#') and '=' in line)
                self.assertEqual('true',value.get('ok'),json.dumps(value))
                self.assertEqual(value['pid'],self.run_command(['systemctl','show','kura.service','-p','MainPID','--value']).strip())
                for role in ('crypto','configuration'):self.assertEqual(self.expected_classes[role],value[role+'ClassSha256'])
                return value
            time.sleep(0.2)
        log=Path('/var/log/kura-console.log')
        self.fail('Same Core startup did not become observable; no restart attempted. '+(log.read_text(errors='replace')[-7000:] if log.exists() else 'No console log'))

    def test_installed_core_applies_snapshot_with_pid1_ring_and_keeps_write_barrier(self):
        self.assertFalse(Path('/sys/class/net/eth0').exists())
        service=self.service;directory=Path('/etc/kura/credentials')
        old,proof=self.manager.canonical();active=secrets.token_bytes(32)
        original=self.temporary/'old-fixture-key';original.write_bytes(old);original.chmod(0o600)
        self.data.mkdir(mode=0o700)
        classpath=':'.join(str(p) for p in (self.home/'plugins').rglob('*.jar'))
        self.run_command([OPTIONS.java,'-Xmx128m','-cp',classpath,'org.eclipse.kura.tests.managedrecovery.ManagedRecoveryProbe',original,self.data/'original.cipher'])
        for path in (self.data,self.data/'original.cipher'):os.chown(path,self.account.pw_uid,self.account.pw_gid)
        # Synthetic pre-existing original set, initialized before any JVM. This is not a publication/rekey acceptance.
        ring=service.encode_key_generations([old,active],1,0);_,metadata=service.key_generations(ring)
        for name,data in [('kura_encryption_key',active),('kura_encryption_keyring',ring),
            ('provisioned.json',service.encode(dict(schema=1,keySha256=metadata['activeKeySha256'],origin='fresh',legacyKey=False,unitDigests=[]))),
            ('key-generations.json',service.encode(dict(schema=1,purpose=service.GENERATION_FORMAT,**metadata)))]:
            self.private(directory/name,data)
        self.manager=service.Manager();self.manager.generations()
        dropins=Path('/etc/systemd/system/kura.service.d');dropins.mkdir(mode=0o700,exist_ok=True)
        (dropins/'40-kura-key-generations.conf').write_bytes((self.home/'share/key-management/key-generations.conf').read_bytes())
        args=Path('/etc/kura/managed-recovery-fixture/jvm.args')
        self.args_file(args,b'-XX:ActiveProcessorCount=2\n-XX:+UseSerialGC\n-Dosgi.startLevel=6\n-Dkura.tests.managed.phase=ordinary\n')
        (dropins/'60-managed-recovery-fixture.conf').write_text('[Service]\nRestart=no\nEnvironment=KURA_JVM_ARGS_FILE='+str(args)+'\n')
        self.run_command(['systemctl','daemon-reload'])
        self.step('Starting installed Core in ordinary mode to retain an actual private YOFC snapshot')
        self.run_command(['systemctl','start','kura.service']);before=self.wait_probe('ordinary')
        self.run_command(['systemctl','stop','kura.service'])
        snapshots=self.home/'user/snapshots'
        target=max((p for p in snapshots.glob('snapshot_*.xml') if p.stem[9:].isdigit()),key=lambda p:int(p.stem[9:]))
        self.assertTrue(target.read_bytes().lstrip().startswith(b'<'),'Keep the actual YOFC plaintext configuration mode')
        source_sha=hashlib.sha256(target.read_bytes()).hexdigest()
        source_keys={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
        root_count=len(list(self.manager.operations.iterdir()))
        request_dir=self.home/'data/managed-recovery-request';request_dir.mkdir(mode=0o700);os.chown(request_dir,self.account.pw_uid,self.account.pw_gid)
        request=request_dir/'request.properties';receipt=request_dir/'applied.properties';identity='rec-'+str(uuid.uuid4())
        values={'schema':'1','restore.id':identity,'snapshot.path':str(target),'snapshot.sha256':source_sha,
            'snapshot.mode':'plain','password.policy':'logical-v1','receipt.path':str(receipt),'crypto.systemd.credentials':'true',
            'crypto.key.sha256':metadata['activeKeySha256'],'crypto.ring.sha256':metadata['ringSha256']}
        self.private(request,''.join(k+'='+v+'\n' for k,v in sorted(values.items())).encode(),owner=True)
        self.args_file(args,('-XX:ActiveProcessorCount=2\n-XX:+UseSerialGC\n-Dosgi.startLevel=6\n-Dkura.tests.managed.phase=controlled\n-Dkura.recovery.request='+str(request)+'\n').encode())
        self.step('MANAGED_CORE_START_INTENT '+json.dumps(dict(restoreId=identity,snapshotSha256=source_sha)))
        self.step('Starting controlled Main once; actual bootstrap must apply CM and preserve the write guard')
        self.run_command(['systemctl','start','kura.service']);after=self.wait_probe('controlled')
        self.assertNotEqual(before['pid'],after['pid']);self.assertEqual(before['originalSha256'],after['originalSha256'])
        self.assertEqual('true',after['writesBlocked']);self.assertEqual('true',after['cmMatched'])
        self.assertEqual(identity,after['restoreId']);self.assertEqual(source_sha,after['snapshotSha256'])
        self.assertEqual(self.expected_classes['offline'],after['bootstrapClassSha256'])
        self.assertEqual(metadata['activeKeySha256'],after['currentKeyId'])
        status=dict(line.split('=',1) for line in receipt.read_text().splitlines() if '=' in line)
        self.assertEqual('CM_APPLIED',status['status']);self.assertEqual('false',status['fullRecoveryVerified'])
        self.assertEqual(source_sha,hashlib.sha256(target.read_bytes()).hexdigest())
        self.assertEqual(source_keys,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()})
        self.assertEqual(root_count,len(list(self.manager.operations.iterdir())))
        self.step('MANAGED_CORE_CM_OK '+json.dumps(dict(restoreId=identity,actualInstalledCore=True,actualBootstrapAndCm=True,
            actualPid1Credentials=True,oldCipherUnchanged=True,oldCipherDecrypted=True,actualAuditFacade=True,
            writeBarrierRetained=True,cmCount=int(after['cmCount']),propertyCount=int(after['propertyCount']),
            normalPid=int(before['pid']),controlledPid=int(after['pid']),originalUnknownRedispatched=False,
            publicationInvoked=False,completionOrOrdinaryWriteRelease=False)))
        self.run_command(['systemctl','stop','kura.service'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True,type=Path)
    parser.add_argument('--package-sha256',required=True);parser.add_argument('--legacy-baseline',required=True,type=Path)
    parser.add_argument('--java',required=True,type=Path);parser.add_argument('--disposable-fixture',required=True,action='store_true')
    OPTIONS,remaining=parser.parse_known_args();unittest.main(argv=[sys.argv[0],*remaining])
