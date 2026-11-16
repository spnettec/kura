#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Actual installer/private archive reads with a distinct non-root test account; Root roles/history are modeled."""
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_key_recovery_archive as original
import kura_key_recovery_setup as setup

service=original.service
lifecycle=original.lifecycle


@unittest.skipUnless(sys.platform=='linux' and os.geteuid()!=0,'Run as an ordinary disposable Linux UID')
class InstallerArchiveTest(unittest.TestCase):
    def setUp(self):
        self.fixture=original.RecoveryPrivateArchiveTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.installer=setup.Setup(self.fixture.base.root,owner=os.geteuid())
        self.account=SimpleNamespace(pw_uid=os.geteuid(),pw_gid=os.getegid(),pw_shell='/usr/sbin/nologin')
        self.accounts=patch.object(lifecycle.pwd,'getpwnam',side_effect=lambda name:self.account if name=='kura-key-recovery'
            else SimpleNamespace(pw_uid=os.geteuid()+1,pw_gid=os.getegid(),pw_shell='/usr/sbin/nologin'))
        self.accounts.start();self.addCleanup(self.accounts.stop)

    def test_installer_and_resume_accept_33_retained_restores_only_with_matching_archive(self):
        f=self.fixture;identities=[f.restore()[0] for _ in range(32)];f.start(identities[0])
        for identity in identities[1:]:
            value=f.manager.record(identity);value['response']['keyChanged']=False
            f.manager.atomic(f.manager.operations/(identity+'.json'),service.encode(value))
        f.history.archive('RESTORE',identities[0]);extra=f.restore()[0];value=f.manager.record(extra);value['response']['keyChanged']=False
        f.manager.atomic(f.manager.operations/(extra+'.json'),service.encode(value));before=f.files();keys=f.base.data_identity()
        self.installer.state(self.account);self.installer.resume_marker(self.account)
        self.assertEqual(before,f.files());self.assertEqual(keys,f.base.data_identity());self.assertIsNone(f.journal.pending())
        self.assertEqual(33,len(f.journal.records()))

    def test_installer_resume_skips_only_authenticated_closed_restore_with_retired_pending(self):
        f=self.fixture;identity,_=f.negative(owning=True,closed=True);f.history.archive('RESTORE',identity)
        before=f.files();keys=f.base.data_identity();self.installer.state(self.account);self.installer.resume_marker(self.account)
        self.assertEqual(before,f.files());self.assertEqual(keys,f.base.data_identity());self.assertIsNone(f.journal.pending())
        self.assertIsNone(f.manager.record(identity))

    def test_installer_refuses_changed_or_unknown_original_without_adding_pending_or_touching_keys(self):
        f=self.fixture;identity=f.restore()[0];f.history.archive('RESTORE',identity)
        value=f.manager.record(identity);value.update(state='INTENT',response=None)
        f.manager.atomic(f.manager.operations/(identity+'.json'),service.encode(value));before=f.files();keys=f.base.data_identity()
        with self.assertRaises(setup.Refused):self.installer.state(self.account)
        self.assertEqual(before,f.files());self.assertEqual(keys,f.base.data_identity());self.assertIsNone(f.journal.pending())


if __name__=='__main__':unittest.main()
