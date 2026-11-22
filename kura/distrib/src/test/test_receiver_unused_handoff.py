#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Production Root and receiver metadata through a direct adapter; Main/UID transport is modeled."""
import argparse
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import test_key_handoff_revocation as authority
import kura_key_recovery as recovery


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Disposable Linux Root/JDK21 only')
class ReceiverUnusedHandoffTest(unittest.TestCase):
    def setUp(self):
        self.fixture = authority.UnusedHandoffRevocationTest(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.manager, self.auth, self.token = self.fixture.manager, self.fixture.auth, self.fixture.token
        self.manager.sender_admissions.owner = lambda source,pid,uid,*args: dict(pid=pid,uid=uid,startTicks='123',bootId=self.auth.load(self.fixture.request['handoffId'])['owner']['bootId'])
        self.path = self.fixture.fixture.root/'var/lib/kura-key-recovery'
        self.path.mkdir(mode=0o700)
        self.journal = recovery.Journal(self.path)
        self.controller = recovery.HandoffController(self.client, self.journal)
        self.lose = False; self.metadata_calls = []
        self.addCleanup(patch.stopall)
        patch.object(authority.service, 'agent_peer', return_value=False).start()
        patch.object(self.manager, 'recovery_sender_owner', return_value=None).start()

    def client(self, request):
        self.metadata_calls.append(request.get('action'))
        value,_ = authority.service.serve_request(self.manager, recovery.SenderAdmission.wrap(request),os.getpid(),42,1001,42,None)
        if request.get('command') == 'revoke' and self.lose:
            self.lose=False;raise OSError('metadata response lost after durable revocation')
        return value

    def execute(self, command):
        return self.controller.execute(dict(token=self.token,command=command))

    def reserve_private(self, binding_only=False):
        info=self.controller.info(self.token);binding=self.controller.binding(info);slot=self.controller.directory/info['handoffId']
        def abandon():
            slot.mkdir(mode=0o700);self.journal.sync(self.controller.directory);self.journal.write_new(slot/'binding.json',binding)
            if not binding_only:self.journal.write_new(slot/'publish.json',dict(binding,command='publish'))
            raise OSError('sender interrupted before the native command')
        with self.assertRaises(OSError):
            self.controller.sender.submit('publish',info['publicationId'],dict(schema=1,action='generation-handoff-command',token=self.token,command='publish'),abandon)
        return slot

    def private_snapshot(self):
        return {str(path.relative_to(self.path)):(path.read_bytes(),path.stat().st_ino,path.stat().st_mtime_ns,path.stat().st_ctime_ns)
            for path in self.path.rglob('*.json')}

    def test_unused_grant_can_be_revoked_without_creating_any_key_request_or_claiming_start_success(self):
        current=self.execute('query');self.assertTrue(current['revocationAllowed'])
        value=self.execute('revoke');self.assertTrue(value['retired']);self.assertFalse(value['completed'])
        self.assertEqual('GRANT_REVOKED',value['handoff']['state']);self.assertFalse(any(value['allowed'].values()))
        self.assertFalse(self.controller.pending());self.assertEqual(0,self.fixture.fixture.count_stops())
        self.assertEqual(2,len(list(self.manager.operations.iterdir())))
        before=self.private_snapshot();self.execute('query');self.assertEqual(before,self.private_snapshot())

    def test_reserved_private_intent_is_retained_and_closed_only_after_positive_root_revocation(self):
        self.reserve_private();before=self.private_snapshot();self.assertTrue(self.controller.pending())
        value=self.execute('revoke');self.assertTrue(value['retired']);self.assertFalse(self.controller.pending())
        self.assertEqual(before,{key:value for key,value in self.private_snapshot().items() if key in before})
        phase=self.controller.sender.view('publish',self.fixture.request['publicationId'])
        self.assertEqual('NOT_ADMITTED',phase['phase']);self.assertTrue(phase['closed'])
        self.assertEqual(0,self.fixture.fixture.count_stops())

    def test_binding_only_interruption_preserves_the_original_reserved_attempt(self):
        slot=self.reserve_private(binding_only=True);before=self.private_snapshot()
        self.assertTrue(self.execute('revoke')['retired'])
        self.assertFalse((slot/'publish.json').exists());self.assertEqual(before,{key:value for key,value in self.private_snapshot().items() if key in before})

    def test_lost_root_reply_requires_explicit_metadata_finish_and_never_a_new_native_send(self):
        self.reserve_private();self.lose=True
        with self.assertRaises(OSError):self.execute('revoke')
        value=self.execute('query');self.assertFalse(value['retired']);self.assertTrue(value['revocationAllowed'])
        self.assertEqual('GRANT_REVOKED',value['handoff']['state'])
        self.assertTrue(self.execute('revoke')['retired']);self.assertEqual(0,self.fixture.fixture.count_stops())

    def test_interrupted_private_retirement_cannot_be_concluded_by_a_query(self):
        slot=self.reserve_private();write=self.journal.write_new
        def interrupted(path,value):
            if path.name=='retired.json':raise OSError('local disposition interrupted')
            return write(path,value)
        with patch.object(self.journal,'write_new',side_effect=interrupted):
            with self.assertRaises(OSError):self.execute('revoke')
        self.assertFalse((slot/'retired.json').exists());before=self.private_snapshot()
        self.assertFalse(self.execute('query')['retired']);self.assertEqual(before,self.private_snapshot())
        self.assertTrue(self.execute('revoke')['retired'])

    def test_intake_without_native_original_remains_unknown_and_blocks_revocation(self):
        with patch.object(self.auth.generations,'request',side_effect=authority.service.Failure('UNKNOWN')):
            value=self.execute('publish')
        self.assertEqual('UNKNOWN',value['publication']['state']);self.assertFalse(value['revocationAllowed'])
        before=self.private_snapshot()
        with self.assertRaises(authority.service.Failure):self.execute('revoke')
        self.assertEqual(before,self.private_snapshot());self.assertFalse((self.manager.state/'handoff-revocations').exists())

    def test_private_attempt_with_foreign_namespace_cannot_be_retired_or_clear_pending(self):
        self.reserve_private();identity=self.fixture.request['publicationId']
        path=self.controller.sender.path('publish',identity)/'namespace.json'
        path.write_bytes(authority.service.encode(dict(schema=1,namespaceSha256='f'*64)))
        before=self.private_snapshot()
        with self.assertRaises(authority.service.Failure):self.execute('revoke')
        self.assertEqual(before,self.private_snapshot());self.assertFalse((self.manager.state/'handoff-revocations').exists())

    def test_retained_private_disposition_must_keep_matching_root_proof(self):
        self.execute('revoke')
        with patch.object(self.controller,'client',return_value=dict(schema=1,error='UNAVAILABLE')):
            with self.assertRaises(authority.service.Failure):self.controller.pending()

    def package_gate(self):
        import kura_key_service_lifecycle as lifecycle
        for path in [self.path,*self.path.rglob('*')]:os.chown(path,42,42)
        account=SimpleNamespace(pw_uid=42,pw_gid=42,pw_shell='/usr/sbin/nologin')
        with patch.object(lifecycle.pwd,'getpwnam',side_effect=lambda name:account if name=='kura-key-recovery' else SimpleNamespace(pw_uid=0,pw_gid=0)):
            with lifecycle.Lifecycle(self.fixture.fixture.root,0).recovery_locked():pass

    def test_private_package_gate_accepts_only_the_bound_original_unused_revocation(self):
        self.reserve_private();self.execute('revoke');self.package_gate()

    def test_private_package_gate_rejects_a_retirement_that_conceals_root_intake(self):
        self.reserve_private();self.execute('revoke');row=self.manager.sender_admissions.records()[0]
        self.manager.sender_admissions.write(dict(row,state='INTAKE'))
        import kura_key_service_lifecycle as lifecycle
        with self.assertRaises(lifecycle.Refused):self.package_gate()

    def test_private_package_gate_rejects_a_changed_revocation_fingerprint(self):
        slot=self.reserve_private();self.execute('revoke');path=slot/'retired.json'
        value=authority.service.decode(path.read_bytes());value['revocationSha256']='f'*64
        path.write_bytes(authority.service.encode(value))
        import kura_key_service_lifecycle as lifecycle
        with self.assertRaises(lifecycle.Refused):self.package_gate()


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repository',required=True,type=Path)
    parser.add_argument('--java',required=True,type=Path);parser.add_argument('--cipher-jar',required=True,type=Path)
    options,remaining=parser.parse_known_args()
    authority.original.base.package.CONFIG=options.repository.resolve();authority.original.base.JAVA=options.java.resolve();authority.original.base.CIPHER=options.cipher_jar.resolve()
    unittest.main(argv=[sys.argv[0],*remaining])
