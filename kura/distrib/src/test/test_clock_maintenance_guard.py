# SPDX-License-Identifier: EPL-2.0
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4


DISTRIB = Path(__file__).resolve().parents[2]
GUARD = DISTRIB / 'kura-core/clock-maintenance-guard.py'
JOURNAL = DISTRIB / 'src/main/resources/unfiltered/pkg/bin/kura_clock_journal.py'
CONTROL = DISTRIB / 'src/main/resources/variants/linux/unfiltered/deb/control'


@unittest.skipIf(os.getuid() == 0, 'Models the separate clock account with the test UID')
class ClockMaintenanceGuardTest(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.state = Path(root.name)
        self.source = JOURNAL.read_bytes()
        self.guard = {}
        definitions = GUARD.read_text().split('\nrequire(sys.argv', 1)[0]
        exec(compile(definitions, str(GUARD), 'exec'), self.guard)
        self.guard['state'] = self.state
        self.guard['read'] = lambda *args, **kwargs: json.dumps(
            dict(schema=1, uid=os.getuid(), gid=os.getgid())).encode()
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        lookup = patch.object(self.guard['pwd'], 'getpwnam', return_value=account)
        lookup.start()
        self.addCleanup(lookup.stop)
        self.journal_api = {}
        exec(compile(self.source, str(JOURNAL), 'exec'), self.journal_api)
        boot = str(uuid4())
        self.journal = self.journal_api['Journal'](self.state, boot_id=lambda: boot)

    def verify(self):
        self.guard['check_existing_operations'](self.source)

    def test_no_namespace_is_created_and_missing_lock_stays_missing(self):
        with self.assertRaises(FileNotFoundError):
            self.verify()
        self.assertEqual([], list(self.state.iterdir()))
        with self.journal.lock():
            pass
        self.verify()
        self.assertEqual(['admission.lock'], [p.name for p in self.state.iterdir()])

    def test_known_result_allows_check_but_an_original_unknown_refuses_without_writes(self):
        with self.journal.lock():
            namespace = self.journal.namespace()
            intent = dict(schema=1, action='adjust-realtime', namespace=namespace, requestId=str(uuid4()),
                          cohortSha256='0' * 64, correctionMillis=0)
            self.journal.prepare(intent)
            self.journal.commit(intent, lambda nanos: None)
        self.verify()
        unknown = dict(intent, requestId=str(uuid4()))
        with self.journal.lock():
            self.journal.prepare(unknown)
            with self.assertRaisesRegex(self.journal_api['Refused'], 'UNCONFIRMED'):
                self.journal.commit(unknown, self.unconfirmed)
        before = {p.relative_to(self.state): p.read_bytes() for p in self.state.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(RuntimeError, 'Unpaired or unresolved clock broker'):
            self.verify()
        self.assertEqual(before, {p.relative_to(self.state): p.read_bytes()
                                  for p in self.state.rglob('*') if p.is_file()})
        self.assertFalse((self.state / 'maintenance.json').exists())

    def unconfirmed(self, _nanos):
        raise self.journal_api['Refused']('UNCONFIRMED')


class PackageClockOrderingTest(unittest.TestCase):
    def test_read_only_clock_check_precedes_key_fence_and_clock_quiesce(self):
        for name, fence in (('preinst', 'keyServicePackageAdmission --enter'),
                            ('prerm', 'kura_key_service_lifecycle.py" --enter')):
            with self.subTest(script=name):
                script = (CONTROL / name).read_text()
                early = script.index('clockMaintenanceGuard check || exit 1')
                reboot = script.index("<<'KURA_REBOOT_MAINTENANCE_GUARD'", early)
                key = script.index(fence, early)
                late = script.index('clockMaintenanceGuard || exit 1', key)
                self.assertLess(early, reboot)
                self.assertLess(reboot, key)
                self.assertLess(key, late)
