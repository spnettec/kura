# SPDX-License-Identifier: EPL-2.0
"""Check managed Main's kernel restriction and admission ordering."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BIN = Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'
sys.path.insert(0, str(BIN))
import kura_key_service as service
import kura_key_store as policy


@unittest.skipUnless(sys.platform == 'linux', 'Linux kernel process state')
class MainNoNewPrivilegesTest(unittest.TestCase):
    def test_process_restriction_survives_exec(self):
        source = '''import os, runpy, sys
require = runpy.run_path(sys.argv[1])['require_no_new_privileges']
require()
os.execv(sys.executable, [sys.executable, '-I', '-c',
    "from pathlib import Path; assert 'NoNewPrivs:\\t1' in Path('/proc/self/status').read_text()"])
'''
        subprocess.run([sys.executable, '-I', '-B', '-c', source, str(BIN / 'kura_key_store.py')],
                       check=True, timeout=5)

    def test_missing_process_restriction_does_not_dispatch_writer_acquisition(self):
        with patch.object(policy, 'require_no_new_privileges', side_effect=policy.Refused('kernel refusal')), \
                patch.object(policy, 'loaded_binding') as binding, patch.object(policy, 'root_exchange') as exchange:
            with self.assertRaisesRegex(policy.Refused, 'kernel refusal'):
                policy.exec_java(['-version'])
            binding.assert_not_called()
            exchange.assert_not_called()

    def test_nonroot_writer_with_clear_bit_refuses_before_lock_or_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = service.Manager(Path(temporary))
            request = dict(schema=1, action='writer-lease-acquire', keySha256='a' * 64, ringSha256=None)
            with patch.object(manager, 'writer_process', return_value=(999, '42')), \
                    patch.object(Path, 'read_bytes', return_value=b'Name:\tlauncher\nNoNewPrivs:\t0\n'), \
                    patch.object(manager, 'lock') as lock:
                with self.assertRaises(service.Failure) as error:
                    manager.acquire_writer_lease(request, pid=100, uid=999)
                self.assertEqual('WRITER_NO_NEW_PRIVS_REQUIRED', error.exception.reason)
                lock.assert_not_called()
            self.assertFalse((Path(temporary) / 'run/kura-key-service/writers').exists())
