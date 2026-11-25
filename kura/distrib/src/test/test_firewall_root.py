# SPDX-License-Identifier: EPL-2.0
"""Isolated Linux descriptor/lock tests. Never initialize an installed Root."""
from contextlib import ExitStack, redirect_stderr
import fcntl
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BIN = Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'
sys.path.insert(0, str(BIN))
import kura_firewall_publish as broker
from kura_key_service import Manager
from kura_key_service_lifecycle import Lifecycle


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == os.getegid() == 0,
                     'Run in the isolated Linux Root unit-test container')
class FirewallRootTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kura-firewall-root-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager, self.policy = Manager(self.root), Lifecycle(self.root)
        for name in ('var/lib/dpkg', 'var/lib/kura-key-service', 'run/kura-key-service', 'opt/eclipse/kura/bin'):
            (self.root / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = self.root / 'var/lib/dpkg/lock'
        self.database.touch(mode=0o640)
        (self.manager.state / 'admission.lock').touch(mode=0o600)
        self.home = self.root / 'opt/eclipse/kura'
        self.source = self.home / 'bin/kura_firewall_publish.py'
        self.source.write_bytes(b'paired synthetic source\n')
        self.marker = self.root / 'worker-entered'
        self.worker = self.root / 'synthetic-worker'
        self.pub = self.root / 'var/lib/kura-legacy-firewall/publication'
        self.writers = self.root / 'run/kura-key-service/writers/lease.lock'
        self.reply = dict(schema=2, state='INITIALIZED', rootScopeScheme='kernel-fh-v2', rootScope='a' * 64)
        code = ("#!/usr/bin/python3\nimport json,os\nfrom pathlib import Path\n"
                f"assert os.path.samestat(os.fstat(3),os.stat({str(self.writers)!r}))\n"
                "status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)\n"
                "assert status['NoNewPrivs'].strip()=='1'\n"
                "assert all(int(status[key],16)==0 for key in ['CapEff','CapPrm','CapBnd','CapInh','CapAmb'])\n"
                f"Path({str(self.marker)!r}).write_text('inherited original FD3 with zero capabilities\\n')\n"
                f"print(json.dumps({self.reply!r}))\n")
        self.worker.write_text(code)
        self.worker.chmod(0o755)
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.object(broker, 'CORE_HOME', self.home))
        stack.enter_context(patch.object(broker, 'WORKER', self.worker))
        stack.enter_context(patch.object(broker, 'public_file', side_effect=lambda p: p.read_bytes()))
        self.sources = stack.enter_context(patch.object(broker, 'verify_sources', return_value={
            'files': {'kura_firewall_publish.py': hashlib.sha256(self.source.read_bytes()).hexdigest()}}))
        self.assets = stack.enter_context(patch.object(self.policy, 'assets', return_value={}))

    def invoke(self):
        return broker.initialize_domain(self.manager, self.policy)

    def refused(self, reason):
        with self.assertRaises(broker.Refused) as error:
            self.invoke()
        self.assertEqual(error.exception.reason, reason)
        self.assertFalse(self.marker.exists())

    def test_original_descriptor_reaches_child_and_parent_fences_are_released(self):
        self.assertEqual(self.invoke(), self.reply)
        self.assertEqual(self.pub.stat().st_mode & 0o7777, 0o700)
        self.assertTrue(self.marker.exists())
        with self.writers.open('rb') as writer:
            fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assets.assert_called_once_with()

    def test_main_shared_writer_lease_refuses_before_publication_directory_or_worker(self):
        fd = self.manager.writer_lock(create=True)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            self.refused('CORE_WRITERS_ACTIVE')
            self.assertFalse(self.pub.exists())
        finally:
            os.close(fd)

    def test_separate_dpkg_process_excludes_initializer_before_core_checks(self):
        command = ('import fcntl,sys; f=open(sys.argv[1],"r+"); '
                   'fcntl.lockf(f,fcntl.LOCK_EX); print("locked",flush=True); sys.stdin.read()')
        with subprocess.Popen([sys.executable, '-c', command, str(self.database)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as holder:
            self.assertEqual(holder.stdout.readline(), b'locked\n')
            try:
                self.refused('CORE_PACKAGE_MAINTENANCE_ACTIVE')
                self.assets.assert_not_called()
                self.assertFalse(self.pub.exists())
            finally:
                holder.communicate(b'', timeout=5)

    def test_modified_core_cli_source_refuses_before_writer_or_publication_creation(self):
        self.source.write_bytes(b'different release\n')
        self.refused('UNPAIRED_FIREWALL_INITIALIZER')
        self.assertFalse(self.pub.exists())
        self.assertFalse(self.writers.exists())

    def test_native_unsupported_and_unresolved_failures_remain_refusals(self):
        for reason in ('UNSUPPORTED_ROOT_IDENTITY', 'LEGACY_DOMAIN', 'UNRESOLVED', 'UNPAIRED', 'BUSY'):
            with self.subTest(reason=reason), patch.object(broker.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=1, stdout=b'', stderr=('Firewall publication failed: ' + reason).encode())):
                self.refused(reason)

    def test_native_reply_cannot_claim_business_receipt_or_wrong_root_scheme(self):
        invalid = [self.reply | {'operationId': 'caller-selected'}, self.reply | {'state': 'SUCCEEDED'},
                   self.reply | {'rootScopeScheme': 'legacy-v1'}, self.reply | {'rootScope': 'not-a-scope'},
                   self.reply | {'schema': True}]
        for value in invalid:
            with self.subTest(value=value), patch.object(broker.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout=json.dumps(value).encode(), stderr=b'')):
                self.refused('INVALID_ROOT_DOMAIN_RESULT')

    def test_cli_accepts_no_root_scope_or_original_id_arguments(self):
        with (patch.object(sys, 'argv', ['broker', '--initialize-persistent-root', '--root=elsewhere']),
              patch.object(broker, 'initialize_persistent_root') as initialize,
              patch.object(broker.socket, 'socket') as activated, redirect_stderr(StringIO())):
            self.assertEqual(broker.main(), 1)
        initialize.assert_not_called()
        activated.assert_not_called()


if __name__ == '__main__':
    unittest.main()
