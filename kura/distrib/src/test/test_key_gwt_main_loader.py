#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Protected production component loader and real kernel UIDs; systemd/cgroups are modeled."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_key_handoff as original

service = original.service


@unittest.skipUnless(sys.platform=='linux' and os.geteuid()==0, 'Disposable Linux Root/JDK21 only')
class GwtMainLoaderTest(unittest.TestCase):
    def setUp(self):
        self.fixture=original.HandoffTest(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.manager=self.fixture.manager; self.uid=1001; self.main=self.child()

    def child(self):
        child=subprocess.Popen([sys.executable,'-B','-c','import os,sys;print(os.getpid(),flush=True);sys.stdin.buffer.read(1)'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,user=self.uid,group=self.uid,extra_groups=[],cwd='/',
            env={'PATH':'/usr/bin:/bin','LANG':'C'})
        def close():
            child.stdin.close()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=5)
            child.stdout.close()
        self.addCleanup(close);self.assertEqual(str(child.pid),child.stdout.readline().strip())
        self.assertEqual(self.uid,self.manager.writer_process(child.pid)[0]);return child

    def unit(self, command, **options):
        result=self.fixture.run_command(command,**options)
        return subprocess.CompletedProcess(command,result.returncode,
            result.stdout.replace('MainPID='+str(os.getpid())+'\n','MainPID='+str(self.main.pid)+'\n'),result.stderr)

    def peer(self, pid):
        read=Path.read_text;group=Path('/proc')/str(self.main.pid)/'cgroup'
        def modeled_group(path,*args,**kwargs):
            return '0::/system.slice/kura.service\n' if path==group else read(path,*args,**kwargs)
        with patch.object(service.subprocess,'run',side_effect=self.unit),patch.object(Path,'read_text',modeled_group):
            return self.manager.gwt_sender_owner(pid,self.uid,self.uid)

    def test_actual_cohort_loader_admits_only_the_declared_main_with_a_real_kernel_uid(self):
        before=self.fixture.snapshot();self.peer(self.main.pid)
        self.assertEqual(before,self.fixture.snapshot());self.assertFalse((self.manager.state/'gwt-sender.json').exists())
        self.assertFalse((self.manager.state/'sender-admissions').exists())

    def test_another_process_with_the_same_kernel_uid_is_not_the_declared_main(self):
        other=self.child();before=self.fixture.snapshot()
        self.fixture.refused('UNMANAGED_CORE',lambda:self.peer(other.pid))
        self.assertEqual(before,self.fixture.snapshot())

    def test_modified_generation_source_refuses_main_authority_without_creating_an_admission(self):
        source=self.manager.store.path('/opt/eclipse/kura/bin/kura_key_generation.py')
        self.fixture.put(source,source.read_bytes()+b'\n# incompatible staged helper\n',mode=0o644)
        before=self.fixture.snapshot();self.fixture.refused('COHORT_UNAVAILABLE',lambda:self.peer(self.main.pid))
        self.assertEqual(before,self.fixture.snapshot());self.assertFalse((self.manager.state/'sender-admissions').exists())


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repository',required=True,type=Path)
    parser.add_argument('--java',required=True,type=Path);parser.add_argument('--cipher-jar',required=True,type=Path)
    options,remaining=parser.parse_known_args();original.base.package.CONFIG=options.repository.resolve()
    original.base.JAVA=options.java.resolve();original.base.CIPHER=options.cipher_jar.resolve()
    unittest.main(argv=[sys.argv[0],*remaining])
