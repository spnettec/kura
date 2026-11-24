#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Actual isolated Python/package source selection. Temporary credentials only; no key writer or gateway."""
import hashlib
import importlib.util
import json
import marshal
import os
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid
import ast

import test_key_generation_startup as original


class PreunpackPolicyTest(unittest.TestCase):
    def setUp(self):
        self.fixture=original.GenerationStartupTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.source=Path(original.policy.__file__).parent
        self.work=self.root/'untrusted-working';self.work.mkdir(mode=0o700)
        self.marker=self.work/'untrusted-reader-ran'
        self.poison="from pathlib import Path\nPath("+repr(str(self.marker))+").write_text('unexpected reader')\nraise AssertionError('untrusted lifecycle executed')\n"
        (self.work/'kura_key_service_lifecycle.py').write_text(self.poison)
        self.inputs=self.root/'incoming';self.inputs.mkdir(mode=0o700)
        for name in ('kura_key_store.py','kura_key_service_lifecycle.py','kura_key_journal.py'):
            path=self.inputs/name;path.write_bytes((self.source/name).read_bytes());path.chmod(0o644)

    def run_policy(self,*,embedded=True,anchor='<stdin>',journal=True,action='upgrade'):
        program="""from pathlib import Path
import json,sys
sys.pycache_prefix=None
source,root,anchor,embedded,journal,action=sys.argv[1:]
namespace={'__name__':'incoming_key_policy','__file__':anchor}
if embedded=='yes':
    namespace['_KURA_EMBEDDED_LIFECYCLE_SOURCE']=(Path(source)/'kura_key_service_lifecycle.py').read_bytes()
    if journal=='yes':namespace['_KURA_EMBEDDED_JOURNAL_SOURCE']=(Path(source)/'kura_key_journal.py').read_bytes()
exec(compile((Path(source)/'kura_key_store.py').read_bytes(),'<incoming-key-policy>','exec'),namespace)
result=namespace['Store'](Path(root),__import__('os').geteuid()).prepare(action)
assert result['keyReady'] is True
print('PAIRED_PREUNPACK_POLICY_OK')
"""
        return subprocess.run([sys.executable,'-I','-B','-c',program,str(self.inputs),str(self.root),anchor,
            'yes' if embedded else 'no','yes' if journal else 'no',action],cwd=self.work,capture_output=True,text=True,timeout=12)

    def test_incoming_policy_uses_its_own_lifecycle_and_never_adds_the_stdin_working_directory(self):
        before=self.fixture.identity();result=self.run_policy()
        self.assertEqual(0,result.returncode,result.stderr);self.assertEqual('PAIRED_PREUNPACK_POLICY_OK\n',result.stdout)
        self.assertFalse(self.marker.exists());self.assertEqual(before,self.fixture.identity())

    def test_unpaired_stdin_policy_is_refused_without_importing_a_working_directory_reader(self):
        before=self.fixture.identity();result=self.run_policy(embedded=False)
        self.assertNotEqual(0,result.returncode);self.assertFalse(self.marker.exists());self.assertEqual(before,self.fixture.identity())

    def test_partial_embedded_pair_is_refused_without_an_installed_or_working_directory_fallback(self):
        before=self.fixture.identity();result=self.run_policy(journal=False)
        self.assertNotEqual(0,result.returncode);self.assertFalse(self.marker.exists());self.assertEqual(before,self.fixture.identity())

    def test_installed_policy_executes_only_checked_companion_source_not_a_matching_poisoned_cache(self):
        ledger=self.inputs/'kura_key_service_lifecycle.py'
        with patch.object(sys,'pycache_prefix',None):cache=Path(importlib.util.cache_from_source(str(ledger)))
        cache.parent.mkdir(mode=0o700)
        st=ledger.stat();cache.write_bytes(importlib.util.MAGIC_NUMBER+struct.pack('<III',0,int(st.st_mtime)&0xffffffff,st.st_size)
            +marshal.dumps(compile(self.poison,str(ledger),'exec')))
        before=self.fixture.identity();raw=cache.read_bytes();result=self.run_policy(embedded=False,anchor=str(self.inputs/'kura_key_store.py'))
        self.assertEqual(0,result.returncode,result.stderr);self.assertFalse(self.marker.exists());self.assertEqual(raw,cache.read_bytes());self.assertEqual(before,self.fixture.identity())

    def test_writable_or_linked_installed_companion_is_refused_without_touching_original_credentials(self):
        ledger=self.inputs/'kura_key_service_lifecycle.py';before=self.fixture.identity()
        ledger.chmod(0o666);result=self.run_policy(embedded=False,anchor=str(self.inputs/'kura_key_store.py'))
        self.assertNotEqual(0,result.returncode);self.assertEqual(before,self.fixture.identity())
        ledger.chmod(0o644);os.link(ledger,self.inputs/'linked-reader');result=self.run_policy(embedded=False,anchor=str(self.inputs/'kura_key_store.py'))
        self.assertNotEqual(0,result.returncode);self.assertEqual(before,self.fixture.identity())

    def test_unknown_original_stays_unknown_and_blocks_preparation_even_with_matching_keys(self):
        identity=str(uuid.uuid4());path=self.fixture.state/'operations'/(identity+'.json')
        path.write_bytes(original.service.encode(dict(schema=1,action='backup-create',operationId=identity,requestTag='1'*64,state='INTENT',response=None)));path.chmod(0o600)
        raw=path.read_bytes();before=self.fixture.identity();result=self.run_policy()
        self.assertNotEqual(0,result.returncode);self.assertFalse(self.marker.exists());self.assertEqual(raw,path.read_bytes());self.assertEqual(before,self.fixture.identity())

    def test_builder_embeds_exact_policy_readers_and_refuses_missing_or_duplicate_placeholders(self):
        path=Path(__file__).resolve().parents[2]/'kura-core/prepare-key-service.py'
        spec=importlib.util.spec_from_file_location('policy_pair_builder',path);builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        preinst=self.root/'preinst';token='raise RuntimeError("Kura key-policy readers were not embedded")'
        manifest=self.root/'manifest.json'
        manifest.write_bytes(b'{"generation":{"publishedPredecessorManifestSha256s":["0000000000000000000000000000000000000000000000000000000000000000"]}}')
        preinst.write_text(token+'\n');builder.embed_policy_readers(preinst,self.inputs/'kura_key_service_lifecycle.py',self.inputs/'kura_key_journal.py',manifest)
        values={n.targets[0].id:ast.literal_eval(n.value) for n in ast.parse(preinst.read_text()).body}
        self.assertEqual((self.inputs/'kura_key_service_lifecycle.py').read_bytes(),values['_KURA_EMBEDDED_LIFECYCLE_SOURCE'])
        self.assertEqual((self.inputs/'kura_key_journal.py').read_bytes(),values['_KURA_EMBEDDED_JOURNAL_SOURCE'])
        self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(),values['_KURA_INCOMING_KEY_MANIFEST_SHA256'])
        self.assertEqual(('0' * 64,), values['_KURA_INCOMING_KEY_PREDECESSORS'])
        for text in ('',token+'\n'+token):
            preinst.write_text(text)
            with self.assertRaises(RuntimeError):builder.embed_policy_readers(preinst,self.inputs/'kura_key_service_lifecycle.py',self.inputs/'kura_key_journal.py',manifest)

    @unittest.skipUnless(sys.platform=='linux','Immutable Root archive publication uses Linux renameat2')
    def test_incoming_policy_keeps_all_257_originals_and_accepts_only_positive_archived_capacity(self):
        api=original.policy.paired_lifecycle();api.__dict__['_KURA_EMBEDDED_JOURNAL_SOURCE']=(self.source/'kura_key_journal.py').read_bytes()
        manager=original.service.Manager(self.root,os.geteuid());manager.journal_module=lambda:api.Lifecycle(self.root,os.geteuid()).journal_module()
        lock=manager.state/'sender-admission.lock';lock.write_bytes(b'');lock.chmod(0o600)
        identities=[]
        for _ in range(257):
            identity=str(uuid.uuid4());identities.append(identity)
            response=dict(schema=1,operationId=identity,action='backup-create',state='SUCCEEDED',backup=dict(format=original.service.FORMAT,operationId=identity,encrypted='YQ=='))
            path=manager.operations/(identity+'.json');path.write_bytes(original.service.encode(dict(schema=1,operationId=identity,action='backup-create',state='SUCCEEDED',requestTag='1'*64,response=response)));path.chmod(0o600)
        namespace=manager.gwt_namespace()['namespaceSha256'];references=[dict(directory='operations',operationId=identities[0])]
        plan=manager.archive_journal(dict(schema=1,action='journal-archive-plan',namespaceSha256=namespace,entries=references),111,0,1001,42)
        manager.archive_journal(dict(schema=1,action='journal-archive',archiveId=str(uuid.uuid4()),namespaceSha256=namespace,entries=references,expectedEntriesSha256=plan['entriesSha256']),111,0,1001,42)
        before={p.name:p.read_bytes() for p in manager.operations.iterdir()};keys=self.fixture.identity();result=self.run_policy()
        self.assertEqual(0,result.returncode,result.stderr);self.assertFalse(self.marker.exists());self.assertEqual(keys,self.fixture.identity())
        self.assertEqual(before,{p.name:p.read_bytes() for p in manager.operations.iterdir()});self.assertEqual(257,len(before))

    def maintenance(self,action='upgrade'):
        marker=self.fixture.state/'maintenance.json'
        marker.write_bytes(original.service.encode(dict(schema=1,id=str(uuid.uuid4()),state='MAINTENANCE',firstAction=action)));marker.chmod(0o600)
        return marker

    def test_package_continues_valid_maintenance_without_replacing_generation_keys_or_admitting_boot(self):
        marker=self.maintenance();before=self.fixture.identity();raw=marker.read_bytes()
        result=self.run_policy(action='auto');self.assertNotEqual(0,result.returncode)
        result=self.run_policy(action='package');self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual(before,self.fixture.identity());self.assertEqual(raw,marker.read_bytes());self.assertFalse(self.marker.exists())

    def test_package_refuses_absent_fence_and_incomplete_original_credentials(self):
        before=self.fixture.identity();result=self.run_policy(action='package');self.assertNotEqual(0,result.returncode);self.assertEqual(before,self.fixture.identity())
        self.maintenance()
        (self.fixture.directory/original.policy.CREDENTIAL).unlink();before=self.fixture.identity()
        result=self.run_policy(action='package');self.assertNotEqual(0,result.returncode);self.assertEqual(before,self.fixture.identity())

    def test_package_reinstall_consumes_the_original_remove_fence_without_replacing_it(self):
        marker=self.maintenance('remove');raw=marker.read_bytes();before=self.fixture.identity()
        result=self.run_policy(action='package');self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual(before,self.fixture.identity());self.assertEqual(raw,marker.read_bytes())

    def test_package_single_key_is_preserved_but_unknown_still_blocks_without_repair(self):
        for name in (original.policy.RING_CREDENTIAL,'key-generations.json'):(self.fixture.directory/name).unlink()
        self.maintenance();before=self.fixture.identity()
        result=self.run_policy(action='package');self.assertEqual(0,result.returncode,result.stderr);self.assertEqual(before,self.fixture.identity())
        identity=str(uuid.uuid4());path=self.fixture.state/'operations'/(identity+'.json')
        path.write_bytes(original.service.encode(dict(schema=1,action='backup-create',operationId=identity,requestTag='1'*64,state='INTENT',response=None)));path.chmod(0o600)
        raw=path.read_bytes();result=self.run_policy(action='package');self.assertNotEqual(0,result.returncode)
        self.assertEqual(raw,path.read_bytes());self.assertEqual(before,self.fixture.identity())


if __name__=='__main__':unittest.main()
