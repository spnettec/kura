#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh-only systemd/Root service/actual Rust FD client and real JDK21 worker.

No Main Core is started. All credentials/snapshots are disposable synthesized input.
The agent unit uses its real sandbox with a test-harness executable override.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import unittest

import test_core_snapshot_validation as validation

package = validation.package
service = validation.service


class SystemdCoreValidationTest(unittest.TestCase):
    copy = staticmethod(package.GenerationPackageTest.copy)
    put = staticmethod(validation.writer.WriterLeaseTest.put)
    snapshot = validation.CoreSnapshotValidationTest.snapshot
    seed = validation.CoreSnapshotValidationTest.seed

    def command(self, *arguments):
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=90)
        if result.returncode:
            # Systemd errors do not include private request data. Worker stdout is never forwarded.
            raise AssertionError('Fixture command failed: ' + result.stderr[-1000:])
        return result.stdout

    def setUp(self):
        self.assertEqual('linux',sys.platform); self.assertEqual(0,os.geteuid())
        self.assertTrue(Path('/.dockerenv').is_file())
        self.assertEqual('systemd',Path('/proc/1/comm').read_text().strip())
        destinations=['/opt/eclipse/kura','/etc/kura','/var/lib/kura-key-service',
                      '/etc/kura-management-agent','/fixtures/core-validation','/run/kura-key-service',
                      '/etc/systemd/system/kura-management-agent.service']
        destinations += ['/lib/systemd/system/'+name for name in (*package.lifecycle.UNITS,'kura.service')]
        self.assertFalse(any(os.path.lexists(name) for name in destinations),'Never adopt an existing runtime or credentials')
        validation.writer.WriterLeaseTest.setUp(self)
        self.seed(); self.policy.leave()
        target=Path('/fixtures/core-validation');target.mkdir(parents=True,mode=0o700)
        for name in ('plain.xml','current.aes','old.aes'):
            shutil.copyfile(self.directory/name,target/name);(target/name).chmod(0o600)
        for source,destination in ((self.home,Path('/opt/eclipse/kura')),(self.directory.parent,Path('/etc/kura')),
                                   (self.state,Path('/var/lib/kura-key-service'))):
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(source),str(destination))
        self.home=Path('/opt/eclipse/kura');self.directory=Path('/etc/kura/credentials');self.state=Path('/var/lib/kura-key-service')
        self.home.parent.chmod(0o755)
        for path in [self.home,*self.home.rglob('*')]:path.chmod(0o755 if path.is_dir() else 0o644)
        for name in (*package.lifecycle.UNITS,'kura.service'):
            self.copy(self.root/'lib/systemd/system'/name,Path('/lib/systemd/system')/name)
        self.command('/usr/sbin/groupadd','--system','kura-key-control')
        self.command('/usr/sbin/groupadd','--system','kura-management')
        self.command('/usr/sbin/useradd','--system','--user-group','--no-create-home','--shell','/usr/sbin/nologin',
                     '--groups','kura-key-control','kurad')
        daemon=pwd.getpwnam('kurad').pw_uid
        for name in ('plain.xml','current.aes','old.aes'):os.chown(target/name,daemon,daemon)
        system_java = Path('/usr/bin/java')
        if not os.path.lexists(system_java):
            system_java.symlink_to(validation.JAVA)
        runtime = subprocess.run([system_java, '-version'], capture_output=True, text=True, check=True, timeout=15)
        self.assertRegex(runtime.stderr, r'version "(?:2[1-9]|[3-9][0-9])(?:[."+-])')
        Path('/etc/kura-management-agent').mkdir(mode=0o700)
        self.put(Path('/etc/kura-management-agent/agent.env'),b'')
        self.put(target/'validator.json',service.encode(dict(schema=2,mode='plain',passwordPolicy='authenticated',key=dict(kind='core'))))
        unit=Path('/agent-source/packaging/kura-management-agent.service').read_text()
        self.assertIn('TemporaryFileSystem=/etc/kura:ro /var/lib:ro\n', unit)
        self.assertIn('BindPaths=/var/lib/kura-management-agent\n', unit)
        unit=unit.replace('Type=simple','Type=oneshot\nRemainAfterExit=yes')
        admission='ExecStartPre=/usr/bin/python3 -I /usr/lib/kura-management-agent/setup.py check\n'
        self.assertEqual(1, unit.count(admission))
        unit=unit.replace(admission,'')
        unit=unit.replace('ExecStart=/usr/bin/yofc-management-agent',
            'ExecStart='+str(BINARY)+' --exact core_validation::tests::core_validator_startup_without_root_service --ignored --nocapture')
        unit=unit.replace('Restart=on-failure','Restart=no')
        # The harness reads disposable Core-UID payloads while checking the parent masks.
        unit=unit.replace('CapabilityBoundingSet=CAP_NET_ADMIN\n',
                          'CapabilityBoundingSet=CAP_NET_ADMIN CAP_DAC_OVERRIDE\n')
        unit=unit.replace('[Install]','Environment=YOFC_DISPOSABLE_CORE_VALIDATION=1\n'
            'ReadWritePaths=/fixtures/core-validation\n\n[Install]')
        Path('/etc/systemd/system/kura-management-agent.service').write_text(unit)
        self.command('/usr/bin/systemctl','daemon-reload')

    def test_real_sandbox_fd_bridge_is_readonly_and_keeps_root_admin_protocol_unavailable_to_agent(self):
        before=self.snapshot()
        self.command('/usr/bin/systemctl','start','kura-management-agent.service')
        for unit in ('kura-key-service.socket','kura-key-service.service'):
            self.assertEqual('inactive',self.command('/usr/bin/systemctl','show',unit,'-p','ActiveState','--value').strip())
        self.command('/usr/bin/systemctl','stop','kura-management-agent.service')
        path=Path('/etc/systemd/system/kura-management-agent.service')
        path.write_text(path.read_text().replace('core_validator_startup_without_root_service','core_snapshot_fd_bridge_under_real_systemd'))
        self.command('/usr/bin/systemctl','daemon-reload')
        self.command('/usr/bin/systemctl','start','kura-key-service.socket')
        try:
            self.command('/usr/bin/systemctl','start','kura-management-agent.service')
        except AssertionError:
            log=self.command('/usr/bin/journalctl','--no-pager','-u','kura-management-agent.service','-n','30')
            self.fail(log[-3500:])
        self.assertEqual('active',self.command('/usr/bin/systemctl','is-active','kura-management-agent.service').strip())
        self.assertEqual('active',self.command('/usr/bin/systemctl','is-active','kura-key-service.service').strip())
        self.assertEqual('inactive',self.command('/usr/bin/systemctl','show','kura.service','-p','ActiveState','--value').strip())
        self.assertEqual(before,self.snapshot())
        self.assertEqual([],list((self.state/'operations').iterdir()))
        result=dict(schema=1,scope='real-systemd-readonly-validation',mainStarted=False,
                    actualRustClient=True,actualRootWorker=True,coreOwnedInputFd=True,agentStartsWithoutCore=True,
                    oldAndNewPasswordKeys=True,plainAndEncryptedSnapshots=True,
                    keysAndRootStateUnchanged=True,adminBackupRejected=True,unknownRedispatched=False)
        print('CORE_VALIDATION_SYSTEMD_OK '+json.dumps(result,sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repository',required=True,type=Path)
    parser.add_argument('--java',required=True,type=Path)
    parser.add_argument('--rust-test-binary',required=True,type=Path)
    parser.add_argument('--disposable-fixture',required=True,action='store_true')
    config,remaining=parser.parse_known_args()
    package.CONFIG=config.repository.resolve();validation.JAVA=config.java.resolve();BINARY=config.rust_test_binary.resolve()
    unittest.main(argv=[sys.argv[0],*remaining])
