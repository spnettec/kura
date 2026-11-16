#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Actual protected source loading/standalone embedding; installed assets/systemd are models."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import test_key_service_lifecycle as original

lifecycle=original.lifecycle
SOURCE=Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/bin'


class JournalModuleTest(unittest.TestCase):
    def setUp(self):
        self.base=original.LifecycleTest();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.policy=self.base.policy;self.file=self.base.physical/'bin/kura_key_journal.py'

    def test_loader_attests_actual_source_and_reuses_only_the_same_fingerprint(self):
        module=self.policy.journal_module();self.assertIs(module.Refused,lifecycle.Refused)
        self.assertIs(module.GwtSenderInventory.JOURNALS,lifecycle.GwtSenderInventory.JOURNALS)
        self.assertIs(module,self.policy.journal_module());self.assertTrue(callable(module.archive_reference_read))
        self.assertFalse(list(self.file.parent.glob('__pycache__/*')))

    def test_changed_missing_linked_or_writable_module_is_refused_even_after_cache(self):
        self.policy.journal_module();raw=self.file.read_bytes()
        for mode,content in [(0o640,raw+b'\n# changed'),(0o666,raw)]:
            self.base.write(self.file,content,mode)
            with self.assertRaises(lifecycle.Refused):self.policy.journal_module()
        self.base.write(self.file,raw,0o640);link=self.file.with_name('linked');os.link(self.file,link)
        with self.assertRaises(lifecycle.Refused):self.policy.journal_module()
        link.unlink();self.file.unlink()
        with self.assertRaises((lifecycle.Refused,OSError)):self.policy.journal_module()

    def test_old_asset_profile_remains_readable_but_cannot_borrow_an_unpinned_new_module(self):
        manifest=self.base.physical/'libexec/key-backup/manifest.json';value=json.loads(manifest.read_bytes())
        value['files'].pop('bin/kura_key_journal.py');self.base.write(manifest,json.dumps(value).encode(),0o640)
        self.assertEqual(set(lifecycle.PRE_JOURNAL_ASSETS),set(self.policy.assets()['files']))
        with self.assertRaises(lifecycle.Refused):self.policy.journal_module()

    def test_embedded_reader_runs_in_python_isolation_without_installed_module_or_standard_alias(self):
        source=(SOURCE/'kura_key_service_lifecycle.py').read_bytes();journal=(SOURCE/'kura_key_journal.py').read_bytes()
        work=self.base.root/'embedded-probe';work.mkdir();a=work/'lifecycle';a.write_bytes(source);b=work/'journal';b.write_bytes(journal)
        code="""import sys,types
from pathlib import Path
assert 'kura_key_service_lifecycle' not in sys.modules
ns={'__name__':'isolated_package_reader','__file__':'<new-package-preinst>','_KURA_EMBEDDED_JOURNAL_SOURCE':Path(sys.argv[2]).read_bytes()}
exec(compile(Path(sys.argv[1]).read_bytes(),ns['__file__'],'exec'),ns)
module=ns['Lifecycle']().journal_module()
assert module.Refused is ns['Refused'] and callable(module.archive_reference_read)
assert 'kura_key_service_lifecycle' not in sys.modules
print('ISOLATED_PAIRED_JOURNAL_OK')
"""
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(a),str(b)],cwd=work,capture_output=True,text=True,check=True)
        self.assertEqual('ISOLATED_PAIRED_JOURNAL_OK\n',result.stdout);self.assertEqual('',result.stderr)

    def test_embedding_preserves_exact_source_bytes_and_refuses_missing_or_duplicate_placeholder(self):
        # Keep the builder's real file identity; no product state or command is executed.
        path=Path(__file__).resolve().parents[2]/'kura-core/prepare-key-service.py'
        spec=importlib.util.spec_from_file_location('journal_builder_probe',path);builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        target=self.base.root/'preinst';token='raise RuntimeError("Kura key-journal reader was not embedded")'
        target.write_text(token+'\n');builder.embed_journal_reader(target,self.file)
        tree=ast.parse(target.read_text());value=ast.literal_eval(tree.body[0].value)
        self.assertEqual(self.file.read_bytes(),value);self.assertEqual(hashlib.sha256(value).hexdigest(),hashlib.sha256(self.file.read_bytes()).hexdigest())
        for text in ('',token+'\n'+token):
            target.write_text(text)
            with self.assertRaises(RuntimeError):builder.embed_journal_reader(target,self.file)


if __name__=='__main__':unittest.main()
