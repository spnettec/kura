#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Installer read compatibility; temporary keys only and package cohort modeled."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid

import test_key_generation_startup as original
import kura_key_recovery_setup as setup


class GenerationRecoverySetupTest(unittest.TestCase):
    def setUp(self):
        self.fixture=original.GenerationStartupTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.private=self.fixture.root/'var/lib/kura-key-recovery';self.private.mkdir(mode=0o700)
        for name in ('operations','starts'):(self.private/name).mkdir(mode=0o700)
        self.account=SimpleNamespace(pw_uid=os.geteuid(),pw_gid=os.getegid())
        self.installer=setup.Setup(self.fixture.root,owner=os.geteuid())

    def test_complete_generations_allow_install_resume_without_inventing_a_restore_or_start(self):
        before=self.fixture.identity();self.installer.resume_marker(self.account)
        self.assertEqual(before,self.fixture.identity());self.assertFalse((self.private/'pending.json').exists())
        self.assertEqual([],list((self.private/'starts').iterdir()));self.assertEqual([],list((self.fixture.state/'operations').iterdir()))

    def test_incomplete_generation_set_is_refused_and_not_repaired(self):
        (self.fixture.directory/'key-generations.json').unlink();before=self.fixture.identity()
        with self.assertRaises((original.service.Failure,OSError)):self.installer.resume_marker(self.account)
        self.assertEqual(before,self.fixture.identity());self.assertFalse((self.private/'pending.json').exists())

    def test_missing_canonical_generation_key_is_never_recovered_from_the_ring_by_installation(self):
        (self.fixture.directory/original.policy.CREDENTIAL).unlink();before=self.fixture.identity()
        with self.assertRaises((original.service.Failure,OSError)):self.installer.resume_marker(self.account)
        self.assertEqual(before,self.fixture.identity());self.assertFalse((self.private/'pending.json').exists())

    def test_missing_generation_pair_with_retained_publication_never_falls_back_to_single_key(self):
        for name in (original.policy.RING_CREDENTIAL,'key-generations.json'):(self.fixture.directory/name).unlink()
        marker=self.fixture.state/'generation-current.json';marker.write_bytes(b'retained publication identity');marker.chmod(0o600)
        raw=marker.read_bytes();before=self.fixture.identity()
        with self.assertRaises(original.service.Failure):self.installer.resume_marker(self.account)
        self.assertEqual(before,self.fixture.identity());self.assertEqual(raw,marker.read_bytes());self.assertFalse((self.private/'pending.json').exists())

    def test_cold_single_key_absence_keeps_recovery_installable_without_generating_a_key(self):
        for name in (original.policy.CREDENTIAL,original.policy.RING_CREDENTIAL,'key-generations.json'):(self.fixture.directory/name).unlink()
        before=self.fixture.identity();self.installer.resume_marker(self.account)
        self.assertEqual(before,self.fixture.identity());self.assertFalse((self.private/'pending.json').exists())

    def test_present_generation_keys_do_not_settle_an_original_unknown_restore(self):
        identity=str(uuid.uuid4());fingerprint=self.fixture.metadata['activeKeySha256']
        root=self.fixture.state/'operations'/(identity+'.json')
        root.write_bytes(original.service.encode(dict(schema=1,action='restore',operationId=identity,requestTag='1'*64,state='INTENT',response=None)));root.chmod(0o600)
        local=self.private/'operations'/(identity+'.json')
        local.write_bytes(original.service.encode(dict(schema=1,operationId=identity,expectedKeySha256=fingerprint,backupSha256='2'*64)));local.chmod(0o600)
        before=self.fixture.identity();root_bytes=root.read_bytes();local_bytes=local.read_bytes()
        with self.assertRaises(setup.Refused):self.installer.resume_marker(self.account)
        self.assertEqual(before,self.fixture.identity());self.assertEqual(root_bytes,root.read_bytes());self.assertEqual(local_bytes,local.read_bytes());self.assertFalse((self.private/'pending.json').exists())


if __name__=='__main__':unittest.main()
