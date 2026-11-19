# SPDX-License-Identifier: EPL-2.0
import base64
import errno
from hashlib import sha256
from pathlib import Path
import os
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import Mock, patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_chrony_config as chrony
import kura_clock_broker as broker
import kura_clock_journal as journal


ORIGINAL = b'pool 2.debian.pool.ntp.org iburst\nkeyfile /etc/chrony/chrony.keys\nsourcedir /etc/chrony/sources.d\n'
CANDIDATE = (b'# existing trust policy\nserver 2001:db8::1 iburst nts minpoll 6\n'
             b'keyfile /etc/chrony/chrony.keys\nsourcedir /etc/chrony/sources.d\nmakestep 1 3\n')
UNIT = 'chrony.service'


class DirectiveTest(unittest.TestCase):
    def test_scope_preserves_system_directives_while_accepting_typed_sources(self):
        self.assertEqual(chrony.protected_directives(ORIGINAL), chrony.protected_directives(CANDIDATE))
        for extra in (b'include /tmp/another.conf', b'allow all', b'cmdport 323', b'user root',
                      b'logdir /tmp', b'\tserver example.org iburst extra',
                      b'server example.org nts nts', b'server example.org port 65536', b'peer 1.2.3.4 maxsources 3'):
            with self.subTest(extra=extra):
                self.assertNotEqual(chrony.protected_directives(ORIGINAL),
                                    chrony.protected_directives(CANDIDATE + extra + b'\n'))
        with self.assertRaises(OSError):
            chrony.protected_directives(b'# comment\x00\n')

    def test_payload_accepts_bounded_canonical_utf8_only(self):
        value = dict(unit=UNIT, content=base64.b64encode(CANDIDATE).decode('ascii'))
        self.assertEqual(journal.chrony_configuration(value), CANDIDATE)
        for content in ('Zh==', '/w==', base64.b64encode(b'a' * 16385).decode('ascii')):
            with self.subTest(contentLength=len(content)), self.assertRaises(journal.Refused):
                journal.chrony_configuration(dict(value, content=content))


class ActiveConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.argument = dict(unit=UNIT, content=base64.b64encode(CANDIDATE).decode('ascii'))
        self.before = dict(fragment='paired-distro-unit', state='active', pid=123, started=1234)
        self.after = dict(self.before, pid=321, started=5678)
        self.request = str(uuid.uuid4())
        self.binding = 'a' * 64
        self.wanted = sha256(CANDIDATE).hexdigest()

    def test_changed_active_profile_restarts_once_and_verifies_new_process_and_file(self):
        with patch.object(broker, 'chrony_config_runtime', side_effect=[self.before]*3 + [self.after]), \
                patch.object(broker, 'require_chrony_bus_identity') as authorize, \
                patch.object(broker, 'chrony_config_exchange',
                             side_effect=[sha256(ORIGINAL).hexdigest(), self.binding, self.wanted, self.wanted]) as exchange, \
                patch.object(broker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            broker.configure_chrony(self.argument, self.request, self.binding)
        authorize.assert_called_once()
        self.assertEqual(exchange.call_args_list[1].args, (self.argument, self.request, self.binding))
        self.assertEqual(exchange.call_count, 4)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ['/usr/bin/systemctl', '--system', '--no-ask-password', 'restart', UNIT])

    def test_lost_restart_result_remains_unresolved_after_publication(self):
        with patch.object(broker, 'chrony_config_runtime', return_value=self.before), \
                patch.object(broker, 'require_chrony_bus_identity'), \
                patch.object(broker, 'chrony_config_exchange',
                             side_effect=[sha256(ORIGINAL).hexdigest(), self.binding, self.wanted]), \
                patch.object(broker.subprocess, 'run', side_effect=subprocess.TimeoutExpired('systemctl', 15)) as run, \
                self.assertRaisesRegex(journal.Refused, 'UNCERTAIN_CHRONY_CONFIG_ACTIVATION'):
            broker.configure_chrony(self.argument, self.request, self.binding)
        run.assert_called_once()

    def test_changed_runtime_refuses_before_publication(self):
        with patch.object(broker, 'chrony_config_runtime', side_effect=[self.before, self.after]), \
                patch.object(broker, 'require_chrony_bus_identity'), \
                patch.object(broker, 'chrony_config_exchange', return_value=sha256(ORIGINAL).hexdigest()) as exchange, \
                patch.object(broker.subprocess, 'run') as run, self.assertRaisesRegex(OSError, 'changed before publication'):
            broker.configure_chrony(self.argument, self.request, self.binding)
        exchange.assert_called_once_with(UNIT)
        run.assert_not_called()


@unittest.skipUnless(sys.platform == 'linux' and os.getuid() == 0, 'Linux Root file metadata')
class PublicationTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'chrony.conf'
        self.path.write_bytes(ORIGINAL)
        self.path.chmod(0o644)
        self.config = chrony.Config(self.path, Mock(return_value='vendor'))
        self.request = str(uuid.uuid4())
        self.backup = self.path.with_name('.kura-chrony-original-' + self.request)

    def test_publishes_after_parse_and_preserves_exact_original_under_id(self):
        prepared = self.config.prepare(UNIT, CANDIDATE)
        parser = Mock()
        self.assertEqual(self.config.commit(UNIT, CANDIDATE, prepared, self.request, parser), prepared)
        parser.assert_called_once()
        self.assertEqual(self.path.read_bytes(), CANDIDATE)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.backup.read_bytes(), ORIGINAL)
        self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)

    def test_changed_original_refuses_before_parser_or_publication(self):
        prepared = self.config.prepare(UNIT, CANDIDATE)
        self.path.write_bytes(ORIGINAL + b'# root operator edit\n')
        parser = Mock()
        with self.assertRaisesRegex(OSError, 'changed'):
            self.config.commit(UNIT, CANDIDATE, prepared, self.request, parser)
        parser.assert_not_called()
        self.assertFalse(self.backup.exists())

    def test_denied_system_directive_leaves_original_in_place(self):
        with self.assertRaises(OSError) as raised:
            self.config.prepare(UNIT, CANDIDATE + b'include /etc/chrony/test.conf\n')
        self.assertEqual(raised.exception.errno, errno.EPERM)
        self.assertEqual(self.path.read_bytes(), ORIGINAL)
        self.assertFalse(self.backup.exists())

    def test_failure_after_publish_is_unresolved_and_keeps_original_copy(self):
        prepared = self.config.prepare(UNIT, CANDIDATE)
        replace = os.replace

        def interrupt(source, target):
            replace(source, target)
            raise OSError(errno.EIO, 'lost acknowledgement')

        with patch.object(chrony.os, 'replace', side_effect=interrupt), \
                self.assertRaisesRegex(journal.Refused, 'UNCERTAIN_CHRONY_CONFIG'):
            self.config.commit(UNIT, CANDIDATE, prepared, self.request, Mock())
        self.assertEqual(self.path.read_bytes(), CANDIDATE)
        self.assertEqual(self.backup.read_bytes(), ORIGINAL)
