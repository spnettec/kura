#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Explicit fresh systemd fixture: real dpkg hooks, no Core or key-operation replay.

The generation credentials, empty newer-format archive directory and UNKNOWN row
are declared starting-state models. Native crypto/publication/start are never
dispatched. Opaque user files test preservation, not successful decryption.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
import sys
import tarfile
import unittest
import uuid

OPTIONS=None


class PackageUpgradeSystemdTest(unittest.TestCase):
    def command(self,args,*,timeout=90,allow_failure=False):
        name='step-'+str(len(self.steps))+'.log';log=self.fixture/name
        self.steps.append(dict(arguments=list(map(str,args)),log=name))
        with log.open('wb') as output:
            result=subprocess.run(list(map(str,args)),stdout=output,stderr=subprocess.STDOUT,
                timeout=timeout,env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',LC_ALL='C'))
        self.steps[-1]['returncode']=result.returncode
        text=log.read_text(errors='replace')
        if not allow_failure:self.assertEqual(0,result.returncode,text[-5000:])
        return result.returncode,text

    def setUp(self):
        if OPTIONS is None:self.skipTest('Requires explicit fresh disposable systemd/package fixture')
        self.assertEqual('linux',sys.platform);self.assertEqual(0,os.geteuid())
        self.assertTrue(Path('/.dockerenv').is_file());self.assertEqual('systemd',Path('/proc/1/comm').read_text().strip())
        for value in ('/opt/eclipse/kura','/etc/kura','/var/lib/kura-key-service','/run/kura-key-service','/lib/systemd/system/kura.service'):
            self.assertFalse(os.path.lexists(value),'Never adopt an existing Kura environment')
        self.fixture=Path('/run/kura-package-upgrade-fixture');self.fixture.mkdir(mode=0o700);self.steps=[]
        for package,digest in ((OPTIONS.old_package,OPTIONS.old_sha256),(OPTIONS.package,OPTIONS.package_sha256)):
            self.assertEqual(digest,hashlib.sha256(package.read_bytes()).hexdigest())
        Path('/usr/sbin/policy-rc.d').write_text('#!/bin/sh\nexit 101\n');Path('/usr/sbin/policy-rc.d').chmod(0o755)
        if OPTIONS.case!='fresh':
            process=subprocess.Popen(['dpkg-deb','--fsys-tarfile',str(OPTIONS.legacy_baseline)],stdout=subprocess.PIPE)
            units=[]
            with tarfile.open(fileobj=process.stdout,mode='r|*') as archive:
                for member in archive:
                    if member.isfile() and member.name.endswith('/install/kura.service'):units.append(archive.extractfile(member).read())
            process.stdout.close();self.assertEqual(0,process.wait());self.assertEqual(1,len(units))
            unit=Path('/lib/systemd/system/kura.service');unit.write_bytes(units[0].replace(b'INSTALL_DIR',b'/opt/eclipse'));unit.chmod(0o644)
        self.command(['systemctl','daemon-reload'])
        print('Installing the unmodified old archive and declared dependencies',flush=True)
        self.command(['apt-get','update'],timeout=180)
        initial=OPTIONS.package if OPTIONS.case=='fresh' else OPTIONS.old_package
        self.command(['apt-get','-y','--no-install-recommends','install','openjdk-21-jre-headless','locales',initial],timeout=360)
        self.home=Path('/opt/eclipse/kura').resolve(strict=True);self.credentials=Path('/etc/kura/credentials');self.state=Path('/var/lib/kura-key-service')
        sys.path.insert(0,str(self.home/'bin'))
        import kura_key_store as policy
        self.policy=policy
        key=(self.credentials/policy.CREDENTIAL).read_bytes()
        if OPTIONS.case=='fresh':
            self.assertEqual(32,len(key));self.assertNotIn(key,(policy.CORE_DEFAULT,policy.OLD_DEVELOPMENT))
        else:self.assertIn(key,(policy.CORE_DEFAULT,policy.OLD_DEVELOPMENT))
        self.assert_no_core()
        self.command(['systemctl','stop','kura-key-service.socket','kura-key-service.service','kura-key-recovery.service'])

    def assert_no_core(self):
        _,output=self.command(['systemctl','show','kura.service','--property=MainPID','--property=ControlPID','--property=ExecMainStartTimestampMonotonic'])
        values=dict(line.split('=',1) for line in output.splitlines() if '=' in line)
        self.assertEqual('0',values['MainPID']);self.assertEqual('0',values['ControlPID']);self.assertEqual('0',values['ExecMainStartTimestampMonotonic'])

    @staticmethod
    def identity(path):
        m=path.stat();return dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),dev=m.st_dev,ino=m.st_ino,
            uid=m.st_uid,gid=m.st_gid,mode=m.st_mode,size=m.st_size,mtimeNs=m.st_mtime_ns,ctimeNs=m.st_ctime_ns)

    def protected(self):
        names=[self.credentials/self.policy.CREDENTIAL,self.credentials/'provisioned.json',self.credentials/'.provision.lock',self.state/'journal.key']
        names.extend(p for p in (self.credentials/self.policy.RING_CREDENTIAL,self.credentials/'key-generations.json') if p.exists())
        return {str(p):self.identity(p) for p in names}

    def seed_generation_starting_state(self):
        p=self.policy;old=(self.credentials/p.CREDENTIAL).read_bytes();active=secrets.token_bytes(32)
        raw=p.RING_MAGIC+bytes([2,1,0,len(old)])+old+bytes([len(active)])+active
        metadata=dict(ringSha256=hashlib.sha256(raw).hexdigest(),activeKeySha256=hashlib.sha256(active).hexdigest(),
            legacyKeySha256=hashlib.sha256(old).hexdigest(),keySha256s=[hashlib.sha256(old).hexdigest(),hashlib.sha256(active).hexdigest()])
        receipt=json.loads((self.credentials/'provisioned.json').read_bytes());receipt.update(keySha256=metadata['activeKeySha256'],origin='canonical',legacyKey=False)
        for name,value,mode in ((p.CREDENTIAL,active,0o400),(p.RING_CREDENTIAL,raw,0o400),
            ('key-generations.json',json.dumps(dict(schema=1,purpose=p.GENERATION_FORMAT,**metadata)).encode(),0o600),
            ('provisioned.json',json.dumps(receipt).encode(),0o600)):
            path=self.credentials/name;path.write_bytes(value);path.chmod(mode)
        p.key_generations(raw)

    def test_real_package_transition(self):
        case=OPTIONS.case
        if case=='generation':
            self.seed_generation_starting_state()
            (self.state/'archives').mkdir(mode=0o700) # Declared partial/new-format state; no forged positive receipts.
        original=None
        if case=='unknown':
            identity=str(uuid.uuid4());original=self.state/'operations'/(identity+'.json')
            original.write_text(json.dumps(dict(schema=1,action='backup-create',operationId=identity,requestTag='1'*64,state='INTENT',response=None)))
            original.chmod(0o600)
        root_rows={str(path):self.identity(path) for path in (self.state/'operations').iterdir()}
        before=self.protected();old_prerm=self.identity(Path('/var/lib/dpkg/info/kura-core.prerm'))
        user=self.home/'user/package-upgrade-probe/opaque.bin';data=self.home/'data/package-upgrade-opaque.bin'
        account=pwd.getpwnam('kurad');payload=b'opaque preservation fixture, not a decryption proof\x00'+secrets.token_bytes(32)
        for path in (user,data):
            path.parent.mkdir(mode=0o700,exist_ok=True);path.write_bytes(payload);path.chmod(0o600);os.chown(path,account.pw_uid,account.pw_gid)
        (self.fixture/'before.json').write_text(json.dumps(dict(protected=before,rootOperations=root_rows,oldPrerm=old_prerm,
            userFiles={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (user,data)}),indent=2)+'\n')
        print('UPGRADE_BEGIN '+case,flush=True)
        code,output=self.command(['dpkg','-i',OPTIONS.package],timeout=240,allow_failure=True)
        self.assertEqual(before,self.protected());self.assertEqual(root_rows,{str(path):self.identity(path) for path in (self.state/'operations').iterdir()})
        self.assert_no_core()
        fallback='trying script from the new package instead' in output
        if case in ('generation','unknown'):self.assertTrue(fallback,output[-4000:])
        if case=='unknown':
            self.assertNotEqual(0,code);self.assertEqual(old_prerm,self.identity(Path('/var/lib/dpkg/info/kura-core.prerm')))
            self.assertEqual(payload,user.read_bytes());self.assertEqual(payload,data.read_bytes())
            self.assertFalse((self.state/'maintenance.json').exists(),'An unresolved original must fail before installation maintenance')
            result=dict(case=case,upgradeRefused=True,oldPrermFallback=fallback,originalUnknownId=original.stem,
                originalBytesAndCredentialsPreserved=True,nativeKeyDispatches=0,coreStarts=0)
        else:
            self.assertEqual(0,code,output[-6000:]);self.assertEqual(payload,user.read_bytes());self.assertEqual(payload,data.read_bytes())
            self.assertFalse((self.state/'maintenance.json').exists())
            self.command(['dpkg','-i',OPTIONS.package],timeout=240)
            self.assertEqual(before,self.protected());self.assertEqual(payload,user.read_bytes());self.assertEqual(payload,data.read_bytes());self.assert_no_core()
            self.command(['dpkg','--remove','kura-core'],timeout=180)
            self.assertEqual(before,self.protected())
            retained=Path('/var/lib/kura-retained')
            self.assertEqual(payload,(retained/'user/package-upgrade-probe/opaque.bin').read_bytes())
            self.assertEqual(payload,(retained/'data/package-upgrade-opaque.bin').read_bytes())
            removal=None
            if OPTIONS.retained_reinstall:
                removal=json.loads((self.state/'maintenance.json').read_bytes());self.assertEqual('remove',removal['firstAction'])
                self.command(['dpkg','-i',OPTIONS.package],timeout=240)
                self.assertEqual(before,self.protected());self.assertEqual(payload,user.read_bytes());self.assertEqual(payload,data.read_bytes());self.assert_no_core()
                completion=json.loads((self.state/'package-history'/(removal['id']+'.json')).read_bytes())
                self.assertEqual(removal['id'],completion['maintenanceId']);self.assertEqual('remove',completion['firstAction'])
                self.assertFalse((self.state/'maintenance.json').exists());self.assertFalse(retained.exists())
                self.command(['dpkg','--remove','kura-core'],timeout=180);self.assertEqual(before,self.protected())
                self.assertEqual(payload,(retained/'user/package-upgrade-probe/opaque.bin').read_bytes())
                self.assertEqual(payload,(retained/'data/package-upgrade-opaque.bin').read_bytes())
            self.command(['dpkg','--purge','kura-core'],timeout=180)
            self.assertEqual(before,self.protected());self.assertFalse(retained.exists())
            result=dict(case=case,upgrade=True,reinstall=True,remove=True,purge=True,oldPrermFallback=fallback,
                originalBytesAndCredentialsPreserved=True,retainedUserBytesVerifiedBeforeExplicitPurge=True,nativeKeyDispatches=0,coreStarts=0,
                retainedReinstall=OPTIONS.retained_reinstall,originalRemovalFenceId=removal['id'] if removal else None)
        result.update(steps=self.steps,startingStateModeled=case in ('generation','unknown'),cipherDecryptionAcceptance=False,fullPlatformAcceptance=False)
        (self.fixture/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print('PACKAGE_UPGRADE_SYSTEMD_OK '+json.dumps(result),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('package','old-package','legacy-baseline'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('package-sha256','old-sha256'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--case',choices=('single','fresh','generation','unknown'),required=True)
    parser.add_argument('--retained-reinstall',action='store_true')
    parser.add_argument('--disposable-fixture',action='store_true',required=True)
    OPTIONS,remaining=parser.parse_known_args();unittest.main(argv=[sys.argv[0]]+remaining)
