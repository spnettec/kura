#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Independent HTTPS sender contracts with synthetic Root replies, never a gateway."""
import copy
import http.client
import json
import os
from pathlib import Path
import sys
import ssl
import subprocess
import tempfile
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_key_recovery as recovery
import kura_key_service_lifecycle as lifecycle
from sender_admission_model import SenderModel

protocol = recovery.protocol
HASH, OTHER = 'a' * 64, 'b' * 64


class Root:
    def __init__(self):
        ids = [str(uuid.uuid4()) for _ in range(5)]
        self.info = dict(schema=1, state='GRANT_RECORDED', scope='ORIGINAL_AUTHORIZATION_ONLY',
            **dict(zip(recovery.HandoffController.IDS, ids)), operator='authenticated-original-admin',
            ringSha256=HASH, cohortSha256=OTHER, historySha256=HASH, issuedAt=2000, expiresAt=2900,
            mutationWindowOpen=True, startupAuthorized=False)
        self.token = 'KURA-HANDOFF-1.' + ids[0] + '.' + HASH
        self.calls = []; self.writes = dict(publish=0, start=0, **{'continue': 0})
        self.publication = self.start = None
        self.receipt = None; self.loss = False; self.absent = False; self.partial = False

    def published(self):
        value = self.info
        return dict(schema=1, operationId=value['publicationId'], action='generation-publish', state='SUCCEEDED',
            preparationId=value['preparationId'], verificationId=value['verificationId'], ringSha256=HASH,
            activeKeySha256=OTHER, cohortSha256=OTHER, publicationSha256=HASH, coreStopped=True, requiresExplicitStart=True)

    def started(self):
        return dict(schema=1, operationId=self.info['startOperationId'], action='generation-core-start', state='SUCCEEDED',
            publicationId=self.info['publicationId'], ringSha256=HASH, activeKeySha256=OTHER,
            cohortSha256=OTHER, scope='SYSTEMD_JOB_ACCEPTED', jobPath='/org/freedesktop/systemd1/job/712')

    def __call__(self, request):
        self.calls.append(copy.deepcopy(request))
        assert request['schema'] == 1 and request['action'] == 'generation-handoff-command'
        assert request['token'] == self.token
        command = request['command']; extra = {'expectedRecoveryReceiptSha256'} if command == 'continue' else set()
        assert set(request) == {'schema', 'action', 'token', 'command'} | extra
        if command == 'info': return copy.deepcopy(self.info)
        if command == 'start-lease-status':
            return dict(schema=1, state='START_LEASE_STATUS', scope='ORIGINAL_FIRST_START_ONLY',
                handoffId=self.info['handoffId'], publicationId=self.info['publicationId'], startOperationId=self.info['startOperationId'],
                publicationSha256=self.publication['publicationSha256'] if self.publication and self.publication['state']=='SUCCEEDED' else None,
                renewalOperationId=None, windowOpen=False, renewalAllowed=False)
        if command in self.writes:
            self.writes[command] += 1
            if not self.absent:
                if command == 'publish':
                    self.publication = (dict(schema=1, operationId=self.info['publicationId'], state='UNKNOWN') if self.partial else self.published())
                    if self.partial: self.receipt = HASH
                elif command == 'continue':
                    assert request['expectedRecoveryReceiptSha256'] == self.receipt
                    if not self.partial: self.publication = self.published()
                else: self.start = self.started()
            if self.loss: raise OSError('Synthetic reply lost')
            return dict(schema=1, state='UNUSED_WRITER_REPLY')
        start = command == 'start-read'; value = self.start if start else self.publication
        identity = self.info['startOperationId' if start else 'publicationId']
        if value is None:
            return dict(schema=1, state='NOT_RECORDED', operationId=identity, scope='ORIGINAL_OPERATION_ONLY')
        if start: return copy.deepcopy(value)
        return dict(schema=1, action='generation-publication-read', operationId=identity, state=value['state'],
            scope='ORIGINAL_PUBLICATION_ONLY', recoveryReceiptSha256=self.receipt, originalResult=copy.deepcopy(value), startupAuthorized=False)


class HandoffRecoveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='kura-handoff-sender-'); self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name); self.path.chmod(0o700)
        self.root = Root(); self.journal = recovery.Journal(self.path)
        self.controller = recovery.HandoffController(self.root, self.journal, sender=SenderModel())

    def execute(self, command, **extra):
        return self.controller.execute(dict(token=self.root.token, command=command, **extra))

    def rejected(self, call):
        with self.assertRaises((protocol.Failure, OSError, ValueError, KeyError, TypeError)): call()

    def test_queries_never_create_an_intent_or_publish_start_or_continue(self):
        result = self.execute('query')
        self.assertTrue(result['allowed']['publish']); self.assertFalse(result['allowed']['start'])
        self.assertEqual([], list(self.controller.directory.iterdir())); self.assertEqual(0, sum(self.root.writes.values()))

    def test_https_startup_does_not_depend_on_a_live_root_or_core_status_request(self):
        account = SimpleNamespace(pw_uid=998, pw_shell='/usr/sbin/nologin'); daemon = SimpleNamespace(pw_uid=997)
        controller = SimpleNamespace(status=lambda: self.fail('Startup must not call unavailable Root'))
        with patch.object(recovery.os,'geteuid',return_value=998),patch.object(recovery.sys,'platform','linux'),\
                patch.object(recovery.pwd,'getpwnam',side_effect=lambda name: account if name=='kura-key-recovery' else daemon),\
                patch.dict(recovery.os.environ,{'CREDENTIALS_DIRECTORY':'/run/credentials/kura-key-recovery.service'}),\
                patch.object(recovery.ssl,'SSLContext'),patch.object(recovery,'Controller',return_value=controller),\
                patch.object(recovery,'RecoveryServer') as server:
            recovery.serve(); server.return_value.__enter__.return_value.serve_forever.assert_called_once()

    def test_first_publication_is_forwarded_once_and_bearer_never_enters_files(self):
        self.assertEqual('SUCCEEDED', self.execute('publish')['publication']['state'])
        self.assertEqual('SUCCEEDED', self.execute('publish')['publication']['state'])
        self.assertEqual(1, self.root.writes['publish']); self.assertEqual(0, self.root.writes['start'])
        for path in self.controller.directory.rglob('*.json'):
            self.assertNotIn(self.root.token, path.read_text()); self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_lost_reply_uses_original_result_without_a_second_writer(self):
        self.root.loss = True
        result = self.execute('publish'); self.assertEqual('ROOT_ORIGINAL', result['publication']['resultSource'])
        restarted = recovery.HandoffController(self.root, recovery.Journal(self.path), sender=SenderModel())
        result = restarted.execute(dict(token=self.root.token, command='publish'))
        self.assertEqual('SUCCEEDED', result['publication']['state']); self.assertEqual(1, self.root.writes['publish'])

    def test_sender_intent_and_root_absence_remain_unknown_across_restart(self):
        self.root.absent = True; self.root.loss = True
        self.assertEqual('UNKNOWN', self.execute('publish')['publication']['state'])
        self.controller = recovery.HandoffController(self.root, recovery.Journal(self.path), sender=SenderModel())
        result = self.execute('publish'); self.assertEqual('UNKNOWN', result['publication']['state'])
        self.assertFalse(result['allowed']['publish']); self.assertEqual(1, self.root.writes['publish'])

    def test_original_publication_continuation_has_its_own_single_sender_intent(self):
        self.root.partial = True; result = self.execute('publish')
        self.assertEqual('UNKNOWN', result['publication']['state']); self.assertTrue(result['allowed']['continue'])
        self.rejected(lambda: self.execute('continue', expectedRecoveryReceiptSha256=OTHER))
        self.root.partial = False
        result = self.execute('continue', expectedRecoveryReceiptSha256=HASH)
        self.assertEqual('SUCCEEDED', result['publication']['state'])
        self.execute('continue', expectedRecoveryReceiptSha256=HASH)
        self.assertEqual(dict(publish=1, start=0, **{'continue': 1}), self.root.writes)

    def test_uncertain_continuation_is_query_only_even_if_a_receipt_is_present(self):
        self.root.partial = True; self.execute('publish'); self.root.loss = True
        result = self.execute('continue', expectedRecoveryReceiptSha256=HASH)
        self.assertFalse(result['allowed']['continue']); self.assertEqual('UNKNOWN', result['publication']['state'])
        self.execute('continue', expectedRecoveryReceiptSha256=HASH); self.assertEqual(1, self.root.writes['continue'])

    def test_start_requires_original_publication_and_is_not_application_readiness(self):
        self.rejected(lambda: self.execute('start')); self.execute('publish')
        result = self.execute('start'); self.assertEqual('SYSTEMD_JOB_ACCEPTED', result['start']['scope'])
        self.execute('start'); self.assertEqual(1, self.root.writes['start'])
        self.assertNotIn('applicationReady', result)

    def test_expired_window_blocks_first_publish_and_start_but_keeps_queries(self):
        self.root.info['mutationWindowOpen'] = False
        self.rejected(lambda: self.execute('publish')); self.assertFalse(self.execute('query')['allowed']['publish'])
        self.root.publication = self.root.published(); self.rejected(lambda: self.execute('start'))
        self.assertEqual(0, sum(self.root.writes.values()))

    def test_completion_requires_both_original_results_and_never_forwards_a_root_mutation(self):
        self.rejected(lambda: self.execute('complete')); self.execute('publish')
        self.rejected(lambda: self.execute('complete')); self.execute('start'); before = copy.deepcopy(self.root.writes)
        result = self.execute('complete'); self.assertTrue(result['completed'])
        self.execute('complete'); self.execute('publish'); self.execute('start')
        self.assertEqual(before, self.root.writes)

    def test_uncompleted_handoff_blocks_a_different_authority_before_its_intent(self):
        self.execute('publish'); other = Root(); self.controller.client = other
        result = self.controller.execute(dict(command='query', token=other.token)); self.assertFalse(result['allowed']['publish'])
        self.rejected(lambda: self.controller.execute(dict(command='publish', token=other.token)))
        self.assertEqual(0, sum(other.writes.values())); self.assertEqual(1, len(self.controller.slots()))

    def test_unacknowledged_original_key_recovery_blocks_new_handoff_writers(self):
        self.journal.mark(str(uuid.uuid4()), HASH)
        result = self.execute('query'); self.assertTrue(result['originalRecoveryPending'])
        self.assertFalse(result['allowed']['publish']); self.rejected(lambda: self.execute('publish'))
        self.assertEqual(0, sum(self.root.writes.values()))

    def test_unconfirmed_handoff_blocks_new_legacy_restore_and_start_before_root_dispatch(self):
        self.root.absent = True; self.execute('publish')
        calls = []
        def forbidden(request): calls.append(request); raise AssertionError('Legacy writer must remain fenced')
        legacy = recovery.Controller(forbidden, self.journal, sender=SenderModel())
        backup = dict(format=protocol.FORMAT, operationId=str(uuid.uuid4()), encrypted='synthetic-backup')
        self.rejected(lambda: legacy.restore(dict(operationId=str(uuid.uuid4()), expectedKeySha256=HASH,
            backupJson=json.dumps(backup), passphrase='Synthetic original key recovery password!')))
        self.rejected(lambda: legacy.start(dict(operationId=str(uuid.uuid4()), restoreOperationId=str(uuid.uuid4()), expectedKeySha256=HASH)))
        self.assertEqual([], calls)

    def test_wrong_bindings_scope_job_and_extra_fields_cannot_be_confirmed(self):
        self.execute('publish'); self.root.publication['cohortSha256'] = HASH
        self.rejected(lambda: self.execute('query')); self.rejected(lambda: self.execute('start'))
        self.assertEqual(0, self.root.writes['start'])
        self.root.publication = self.root.published(); self.root.start = self.root.started(); self.root.start['scope'] = 'APPLICATION_READY'
        self.rejected(lambda: self.execute('complete'))
        self.root.info['startupAuthorized'] = True; self.rejected(lambda: self.execute('query'))

    def test_publication_and_start_must_confirm_the_same_active_key(self):
        self.execute('publish'); self.execute('start'); self.root.start['activeKeySha256'] = HASH
        self.rejected(lambda: self.execute('complete'))
        self.assertFalse((self.controller.directory/self.root.info['handoffId']/'completed.json').exists())

    def test_arbitrary_commands_paths_ids_and_old_backup_material_never_reach_root(self):
        for body in [dict(command='restore', token=self.root.token), dict(command='publish', token='backup-file'),
                dict(command='publish', token=self.root.token, operationId=str(uuid.uuid4())),
                dict(command='publish', token=self.root.token, path='/etc/kura/credentials')]:
            self.rejected(lambda: self.controller.execute(body))
        self.assertEqual([], self.root.calls)

    def test_intent_directory_sync_failure_never_sends_and_does_not_become_retry_permission(self):
        sync = self.journal.sync
        def failure(path):
            if (path / 'publish.json').exists(): raise OSError('Synthetic directory sync failure')
            sync(path)
        with patch.object(self.journal, 'sync', side_effect=failure): self.rejected(lambda: self.execute('publish'))
        self.controller = recovery.HandoffController(self.root, recovery.Journal(self.path), sender=SenderModel())
        result = self.execute('publish'); self.assertEqual('UNKNOWN', result['publication']['state'])
        self.assertEqual(0, self.root.writes['publish'])

    def test_corrupt_or_linked_intents_block_every_new_write(self):
        self.execute('publish'); slot = self.controller.directory / self.root.info['handoffId']
        (slot / 'publish.json').write_text('{'); self.rejected(lambda: self.execute('start'))
        (slot / 'publish.json').unlink(); (slot / 'publish.json').symlink_to(slot / 'binding.json')
        self.rejected(lambda: self.execute('publish')); self.assertEqual(1, self.root.writes['publish'])


class HandoffPackageGateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='kura-handoff-package-'); self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name); state = self.path/'var/lib/kura-key-recovery'; state.mkdir(parents=True, mode=0o700)
        self.root = Root(); self.journal = recovery.Journal(state); self.controller = recovery.HandoffController(self.root, self.journal, sender=SenderModel())
        self.gate = lifecycle.Lifecycle(self.path, owner=os.geteuid())
        (self.gate.state/'operations').mkdir(parents=True, mode=0o700)
        self.recovery_uid = 65534 if os.geteuid() == 0 else os.geteuid()
        self.recovery_gid = 65534 if os.geteuid() == 0 else os.getegid()
        account = SimpleNamespace(pw_uid=self.recovery_uid, pw_gid=self.recovery_gid, pw_shell='/usr/sbin/nologin')
        daemon = SimpleNamespace(pw_uid=self.recovery_uid+1)
        identities = patch.object(lifecycle.pwd, 'getpwnam', side_effect=lambda name: account if name == 'kura-key-recovery' else daemon)
        identities.start(); self.addCleanup(identities.stop)

    def execute(self, command): return self.controller.execute(dict(token=self.root.token, command=command))

    def originals(self):
        for response in (self.root.publication, self.root.start):
            if response is not None:
                identity = response['operationId']; record = dict(schema=1, operationId=identity, action=response['action'],
                    requestTag=HASH, state='SUCCEEDED', response=response)
                path = self.gate.state/'operations'/(identity+'.json'); path.write_bytes(protocol.encode(record)); path.chmod(0o600)

    def accepted(self):
        if os.geteuid() == 0:
            # Model the real installer/Recovery UID separation when Root is available.
            # These are synthetic metadata files in this test's private tree only.
            for path in [*self.journal.directory.rglob('*'),self.journal.directory]:
                os.chown(path,self.recovery_uid,self.recovery_gid)
        with self.gate.recovery_locked(): pass

    def test_empty_handoff_state_keeps_legacy_package_path_available(self): self.accepted()

    def test_unconfirmed_sender_intent_blocks_package_change_even_if_root_record_is_absent(self):
        self.root.absent = True; self.execute('publish')
        with self.assertRaises(lifecycle.Refused): self.accepted()

    def test_acknowledgement_is_cross_checked_against_both_root_originals(self):
        self.execute('publish'); self.execute('start'); self.execute('complete'); self.originals(); self.accepted()
        path = self.gate.state/'operations'/(self.root.info['startOperationId']+'.json'); path.unlink()
        with self.assertRaises(OSError): self.accepted()

    def test_sender_completion_never_settles_a_root_intent(self):
        self.execute('publish'); self.execute('start'); self.execute('complete'); self.originals()
        identity = self.root.info['publicationId']; path = self.gate.state/'operations'/(identity+'.json')
        value = json.loads(path.read_bytes()); value.update(state='INTENT', response=None); path.write_bytes(protocol.encode(value))
        with self.assertRaises(lifecycle.Refused): self.accepted()

    def test_mismatched_completed_generation_or_start_job_is_rejected(self):
        self.execute('publish'); self.execute('start'); self.execute('complete'); self.originals()
        path = self.controller.directory/self.root.info['handoffId']/'completed.json'
        value = json.loads(path.read_bytes()); value['jobPath'] = '/org/freedesktop/systemd1/job/713'; path.write_bytes(protocol.encode(value))
        with self.assertRaises(lifecycle.Refused): self.accepted()


class HandoffHttpTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='kura-handoff-https-'); self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name); self.root = Root(); self.journal = recovery.Journal(self.path)
        key, certificate = self.path/'tls.key', self.path/'tls.crt'
        subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost',
            '-keyout',str(key),'-out',str(certificate)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.load_cert_chain(certificate,key)
        assets = Path(__file__).resolve().parents[1]/'main/resources/unfiltered/pkg/share/key-recovery'
        self.server = recovery.RecoveryServer(('127.0.0.1',0),recovery.Controller(self.root,self.journal, sender=SenderModel()),tls,assets)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.origin = 'https://127.0.0.1:'+str(self.server.server_port)

    def request(self,path,body=None,headers=None):
        stream = http.client.HTTPSConnection('127.0.0.1',self.server.server_port,context=ssl._create_unverified_context(),timeout=5)
        fields = {'Origin':self.origin,'Content-Type':'application/json','X-Kura-Recovery-CSRF':self.server.token,
            'Cookie':recovery.COOKIE+'='+self.server.token}
        fields.update(headers or {})
        stream.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),fields)
        response = stream.getresponse(); raw = response.read(); result = response.status,dict(response.getheaders()),raw; stream.close(); return result

    def test_handoff_document_has_its_own_view_and_the_same_secure_session_gate(self):
        status,headers,body = self.request('/handoff')
        self.assertEqual(200,status); self.assertIn(b'data-view="handoff"',body)
        self.assertIn(b'id="cold-flow" hidden',body); self.assertIn(b'id="handoff-flow">',body)
        self.assertIn('Secure; HttpOnly; SameSite=Strict',headers['Set-Cookie']); self.assertEqual('no-store',headers['Cache-Control'])
        self.assertNotIn(self.root.token.encode(),body); self.assertEqual([],self.root.calls)

    def test_repeated_https_writer_requests_only_read_the_original_after_first_admission(self):
        for _ in range(2):
            status,_,body = self.request('/api/handoff',dict(token=self.root.token,command='publish'))
            self.assertEqual(200,status); self.assertEqual('SUCCEEDED',json.loads(body)['publication']['state'])
        self.assertEqual(1,self.root.writes['publish'])

    def test_origin_csrf_and_cookie_failures_precede_any_root_call(self):
        for headers in [{'Origin':'https://attacker.invalid'},{'X-Kura-Recovery-CSRF':'wrong'},{'Cookie':'other=value'}]:
            status,_,_=self.request('/api/handoff',dict(token=self.root.token,command='publish'),headers)
            self.assertEqual(400,status)
        self.assertEqual([],self.root.calls)

    def test_old_backup_authorization_and_caller_selected_ids_cannot_invoke_handoff(self):
        for body in [dict(command='publish',backupJson='{}',passphrase='synthetic old backup password'),
                dict(command='publish',token=self.root.token,operationId=str(uuid.uuid4()))]:
            status,_,_=self.request('/api/handoff',body); self.assertEqual(400,status)
        self.assertEqual([],self.root.calls); self.assertEqual([],list(self.server.handoffs.directory.iterdir()))


if __name__ == '__main__': unittest.main()
