# SPDX-License-Identifier: EPL-2.0
import os
from pathlib import Path
import pwd
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_network_sender_retention as retention
from kura_clock_journal import Refused, digest


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Linux package ownership and atomic publication')
class NetworkSenderRetentionTest(unittest.TestCase):
    def setUp(self):
        self.user = pwd.getpwnam('nobody')
        # Root stages the package copy on /var/lib. Data below it belongs to the sender.
        self.stage = Path('/var/lib') / ('.kura-retained.tmp.' + uuid4().hex)
        self.stage.mkdir(0o700)
        self.addCleanup(shutil.rmtree, self.stage)
        self.site = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/var/lib')))
        self.site.chmod(0o711)
        self.archive = self.site / 'retention.json'
        for target, value in [('ARCHIVE', self.archive), ('HOME', self.site)]:
            self.enterContext(patch.object(retention, target, value))
        self.enterContext(patch.object(retention.pwd, 'getpwnam', return_value=self.user))
        self.enterContext(patch.object(retention, 'inactive'))
        self.enterContext(patch.object(retention, 'public_file', return_value=b'1' * 32))
        self.senders = {name: (self.site / name, *fields[1:]) for name, fields in retention.SENDERS.items()}
        self.enterContext(patch.object(retention, 'SENDERS', self.senders))
        self.contents = {}
        for parent in (self.stage, self.site):
            path = parent / 'data'
            path.mkdir(0o700)
            os.chown(path, self.user.pw_uid, self.user.pw_gid)
        for name, (actor, _limit, *_) in self.senders.items():
            actor.mkdir(0o700)
            meta = actor.stat()
            scope = digest(['1' * 32, meta.st_dev, meta.st_ino])
            op = str(uuid4())
            fields = {'dhcp-control': [op, scope, ''], 'bind-control': [op, scope, 'service', 'stop', '', ''],
                      'modem-control': ['reset', '/org/freedesktop/NetworkManager/Devices/1', '0123', scope, op]}
            self.contents[name] = '\n'.join(['1', *fields[name], '']).encode()
            self.write_pending(self.stage, name, self.contents[name])

    def write_pending(self, parent, name, raw):
        folder = parent / 'data' / name
        folder.mkdir(0o700)
        os.chown(folder, self.user.pw_uid, self.user.pw_gid)
        path = folder / 'pending'
        path.write_bytes(raw)
        path.chmod(0o600)
        os.chown(path, self.user.pw_uid, self.user.pw_gid)
        return path

    def test_partial_restore_resumes_without_replacing_an_existing_operation(self):
        retention.archive(self.stage)
        retention.archive(self.stage)
        original = self.write_pending(self.site, 'bind-control', self.contents['bind-control'])
        inode = original.stat().st_ino
        retention.restore()
        self.assertFalse(self.archive.exists())
        self.assertEqual(inode, original.stat().st_ino)
        for name, content in self.contents.items():
            path = self.site / 'data' / name / 'pending'
            self.assertEqual(content, retention.read(path, self.user.pw_uid))
            self.assertEqual([], list(self.senders[name][0].iterdir()))

    def test_conflicting_live_record_retains_archive(self):
        retention.archive(self.stage)
        path = self.write_pending(self.site, 'dhcp-control', b'conflict')
        with self.assertRaises(Refused):
            retention.restore()
        self.assertTrue(self.archive.exists())
        self.assertEqual(b'conflict', path.read_bytes())

    def test_other_root_rejected_before_restoring_any_record(self):
        retention.archive(self.stage)
        actor = self.senders['modem-control'][0]
        actor.rename(actor.with_suffix('.original'))
        actor.mkdir(0o700)
        with self.assertRaises(Refused):
            retention.restore()
        self.assertEqual([], list((self.site / 'data').iterdir()))
        self.assertTrue(self.archive.exists())

    def test_no_pending_requires_no_archive(self):
        for name in self.senders:
            (self.stage / 'data' / name / 'pending').unlink()
        retention.archive(self.stage)
        self.assertFalse(self.archive.exists())
