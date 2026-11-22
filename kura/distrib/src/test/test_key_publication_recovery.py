#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh storage/JDK21/flock models; systemd and process authority are fakes."""
import argparse
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import select
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

import test_key_generation_publication as base

service = base.service


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Disposable Linux Root/JDK21 models only')
class PublicationRecoveryTest(unittest.TestCase):
    copy = staticmethod(base.GenerationPublicationTest.copy)
    put = staticmethod(base.GenerationPublicationTest.put)
    setUp = base.GenerationPublicationTest.setUp
    close_lease = base.GenerationPublicationTest.close_lease
    set_group = base.GenerationPublicationTest.set_group
    run_command = base.GenerationPublicationTest.run_command
    publish = base.GenerationPublicationTest.publish
    count_stops = base.GenerationPublicationTest.count_stops
    admission = base.GenerationPublicationTest.admission
    start_request = base.GenerationPublicationTest.start_request
    refused = base.GenerationPublicationTest.refused

    def paths(self):
        result = self.component.publication_paths()
        result['publication'] = self.state / 'generations' / self.preparation / 'publication.json'
        result['checkpoint'] = self.state / 'generations' / self.preparation / 'publication-recovery.json'
        result['result'] = self.manager.operations / (self.publish_request['operationId'] + '.json')
        return result

    def snapshot(self):
        result = {}
        for directory in (self.directory, self.state):
            for path in directory.rglob('*'):
                if path.is_file():
                    result[str(path.relative_to(self.root))] = self.component.file_snapshot(path)
        return result

    def info(self):
        return self.component.publication_read(dict(schema=1, action='generation-publication-read',
                                                    operationId=self.publish_request['operationId']))

    def recovery_request(self):
        return dict(schema=1, action='generation-publication-recover', operationId=self.publish_request['operationId'],
                    expectedRecoveryReceiptSha256=self.info()['recoveryReceiptSha256'] or '0' * 64)

    def recover(self):
        return self.component.recover_publication(self.recovery_request())

    def interrupt(self, name, *, after=False):
        atomic = self.manager.atomic
        path = self.paths()[name]
        def fail(target, value, **options):
            hit = target == path and (name != 'result' or service.decode(value)['state'] == 'SUCCEEDED')
            if hit and not after:
                raise OSError('injected original publication boundary')
            result = atomic(target, value, **options)
            if hit:
                raise OSError('injected lost acknowledgement after completed rename')
            return result
        with patch.object(self.manager, 'atomic', side_effect=fail):
            self.refused('UNKNOWN', self.publish)
        self.assertEqual('UNKNOWN', self.manager.handle(dict(schema=1, action='operation-read',
                                                            operationId=self.publish_request['operationId']))['state'])
        self.assertEqual(1, self.count_stops())

    def complete_original(self):
        paths = self.paths()
        before = {name: self.component.file_snapshot(path) for name, path in paths.items()
                  if name != 'result' and path.exists()}
        directory = self.state / 'generations' / self.preparation
        staged = {name: self.component.file_snapshot(directory / name) for name in
                  ('keyring', 'history.json', 'source-active-key', 'source-provisioned.json')}
        result = self.recover()
        self.assertEqual('SUCCEEDED', result['state'])
        self.assertEqual(self.publish_request['operationId'], result['operationId'])
        self.assertTrue(result['coreStopped'])
        self.assertTrue(result['requiresExplicitStart'])
        self.assertEqual(self.prepared['generation'], self.manager.generations()[1])
        self.assertEqual((directory / 'keyring').read_bytes(), (self.directory / 'kura_encryption_keyring').read_bytes())
        for name, metadata in before.items():
            # Existing proposed files and all immutable receipts keep their inode.
            if name in ('checkpoint', 'publication') or metadata['sha256'] == hashlib.sha256(
                    self.component.publication_targets(self.component.current(),
                        (directory / 'keyring').read_bytes(), service.decode((directory / 'history.json').read_bytes()),
                        (self.home / 'share/key-management/key-generations.conf').read_bytes())[name][0]).hexdigest():
                self.assertEqual(metadata, self.component.file_snapshot(paths[name]), name)
        self.assertEqual(staged, {name: self.component.file_snapshot(directory / name) for name in staged})
        self.assertEqual(self.key, service.key_generation_entries(self.manager.generations()[0])[0][0])
        self.assertEqual(1, self.count_stops())
        self.assertFalse(any(command[0] == '/usr/bin/busctl' for command in self.commands))
        self.assertEqual(3, len(list(self.manager.operations.iterdir())))
        self.refused('GENERATION_START_REQUIRED', self.admission)
        settled = self.snapshot()
        commands = list(self.commands)
        self.assertEqual(result, self.recover())
        self.assertEqual(settled, self.snapshot())
        self.assertEqual(commands, self.commands)

    def test_interruption_before_ring(self):
        self.interrupt('ring'); self.complete_original()

    def test_interruption_before_active_key(self):
        self.interrupt('activeKey'); self.complete_original()

    def test_interruption_before_provisioning_receipt(self):
        self.interrupt('provisioned'); self.complete_original()

    def test_interruption_before_generation_receipt(self):
        self.interrupt('generationReceipt'); self.complete_original()

    def test_interruption_before_dropin(self):
        self.interrupt('dropin'); self.complete_original()

    def test_interruption_before_immutable_publication(self):
        self.interrupt('publication'); self.complete_original()

    def test_interruption_before_current_binding(self):
        self.interrupt('current'); self.complete_original()

    def test_lost_original_final_result(self):
        self.interrupt('result'); self.complete_original()

    def test_visible_completed_ring_rename_is_not_repeated(self):
        self.interrupt('ring', after=True); self.complete_original()

    def test_missing_original_stop_handoff_proof_stays_unknown_without_writes(self):
        self.interrupt('checkpoint')
        before = self.snapshot(); commands = list(self.commands)
        self.assertIsNone(self.info()['recoveryReceiptSha256'])
        self.assertEqual('UNKNOWN', self.recover()['state'])
        self.assertEqual('UNKNOWN', self.publish()['state'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(commands, self.commands)

    def test_metadata_query_is_read_only_and_does_not_authorize_startup(self):
        self.interrupt('activeKey')
        before = self.snapshot(); commands = list(self.commands)
        info = self.info()
        self.assertEqual('UNKNOWN', info['state'])
        self.assertEqual('ORIGINAL_PUBLICATION_ONLY', info['scope'])
        self.assertFalse(info['startupAuthorized'])
        self.assertEqual(64, len(info['recoveryReceiptSha256']))
        for forbidden in ('keyring', 'encrypted', 'passphrase', 'sourceFiles', 'receiptTag'):
            self.assertNotIn(forbidden, service.encode(info).decode())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(commands, self.commands)

    def test_exact_fields_hash_and_original_id_are_required_before_writes(self):
        self.interrupt('ring')
        before = self.snapshot()
        request = self.recovery_request(); request['expectedRecoveryReceiptSha256'] = '0' * 64
        self.refused('CONFLICT', lambda: self.component.recover_publication(request))
        request = self.recovery_request(); request['operationId'] = str(uuid.uuid4())
        self.refused('CONFLICT', lambda: self.component.recover_publication(request))
        request = self.recovery_request(); request['replacementKey'] = 'not-permitted'
        self.refused('INVALID_ARGUMENT', lambda: self.component.recover_publication(request))
        self.assertEqual(before, self.snapshot())

    def test_other_original_unknown_still_blocks_recovery(self):
        self.interrupt('ring')
        identity = str(uuid.uuid4())
        self.manager.atomic(self.manager.operations / (identity + '.json'), service.encode(dict(
            schema=1, action='backup-create', operationId=identity, requestTag='0' * 64, state='INTENT', response=None)))
        before = self.snapshot()
        self.refused('UNRESOLVED_OPERATION', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_foreign_source_content_cannot_be_overwritten(self):
        self.interrupt('ring')
        self.manager.atomic(self.paths()['activeKey'], b'foreign-original-key-material-1234', mode=0o400)
        before = self.snapshot()
        self.refused('CONFLICT', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_another_original_publication_unknown_is_not_excluded(self):
        self.interrupt('ring')
        identity = str(uuid.uuid4())
        self.manager.atomic(self.manager.operations / (identity + '.json'), service.encode(dict(
            schema=1, action='generation-publish', operationId=identity, requestTag='0' * 64, state='INTENT', response=None)))
        before = self.snapshot()
        self.refused('UNRESOLVED_OPERATION', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_agent_installed_after_original_intent_still_blocks_continuation(self):
        self.interrupt('ring')
        unit = self.root / 'etc/systemd/system/kura-management-agent.service'
        unit.parent.mkdir(parents=True, exist_ok=True)
        self.put(unit, b'[Service]\nExecStart=/bin/false\n')
        before = self.snapshot()
        self.refused('AGENT_GENERATION_UNAVAILABLE', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_identical_source_bytes_in_a_new_inode_are_not_adopted(self):
        self.interrupt('ring')
        path = self.paths()['activeKey']; self.manager.atomic(path, path.read_bytes(), mode=0o400)
        before = self.snapshot()
        self.refused('CONFLICT', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_changed_already_published_prefix_is_not_overwritten(self):
        self.interrupt('activeKey')
        self.manager.atomic(self.paths()['ring'], b'foreign-published-prefix', mode=0o400)
        before = self.snapshot()
        self.refused('CONFLICT', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_changed_source_backup_is_not_accepted(self):
        self.interrupt('activeKey')
        self.manager.atomic(self.state / 'generations' / self.preparation / 'source-active-key', b'x' * 32, mode=0o400)
        before = self.snapshot()
        self.refused('CONFLICT', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_edited_checkpoint_cannot_invent_a_stop_receipt(self):
        self.interrupt('ring')
        path = self.paths()['checkpoint']; value = service.decode(path.read_bytes())
        value['publication']['stoppedWriter']['pid'] += 1
        self.manager.atomic(path, service.encode(value), mode=0o400)
        before = self.snapshot()
        self.refused('UNSAFE_JOURNAL', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_original_request_tag_cannot_be_retargeted(self):
        self.interrupt('ring')
        path = self.paths()['result']; value = service.decode(path.read_bytes()); value['requestTag'] = '0' * 64
        self.manager.atomic(path, service.encode(value))
        before = self.snapshot()
        self.refused('UNSAFE_JOURNAL', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_surviving_kernel_writer_blocks_local_continuation(self):
        self.interrupt('ring')
        descriptor = self.manager.writer_lock()
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            before = self.snapshot()
            self.refused('WRITERS_ACTIVE', self.recover)
            self.assertEqual(before, self.snapshot())
        finally:
            os.close(descriptor)
        self.assertEqual(1, self.count_stops())

    def test_reappeared_core_is_never_stopped_again(self):
        self.interrupt('ring')
        self.phase = 'active'; self.set_group(True)
        before = self.snapshot()
        self.refused('CORE_NOT_DRAINED', self.recover)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(1, self.count_stops())

    def test_replaced_kernel_lock_cannot_adopt_the_original_handoff(self):
        self.interrupt('ring')
        self.manager.atomic(self.manager.writer_directory() / 'lease.lock', b'')
        before = self.snapshot()
        self.refused('UNSAFE_WRITER_STATE', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_cross_boot_receipt_does_not_authorize_continuation(self):
        self.interrupt('ring')
        path = self.paths()['checkpoint']; value = service.decode(path.read_bytes())
        value['publication']['stoppedWriter']['bootId'] = '00000000-0000-0000-0000-000000000000'
        value.pop('receiptTag')
        value['receiptTag'] = hmac.new((self.state / 'journal.key').read_bytes(),
            b'yofc-kura-publication-recovery-v1\0' + service.encode(value), hashlib.sha256).hexdigest()
        self.manager.atomic(path, service.encode(value), mode=0o400)
        before = self.snapshot()
        self.refused('UNSAFE_WRITER_STATE', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_recovery_failure_resumes_only_unfinished_original_files(self):
        self.interrupt('activeKey')
        request = self.recovery_request(); atomic = self.manager.atomic
        def fail(path, value, **options):
            if path == self.paths()['generationReceipt']:
                raise OSError('injected local continuation interruption')
            return atomic(path, value, **options)
        with patch.object(self.manager, 'atomic', side_effect=fail):
            self.refused('UNKNOWN', lambda: self.component.recover_publication(request))
        self.assertEqual(request, self.recovery_request())
        self.complete_original()

    def test_later_marker_never_authorizes_a_gap_in_an_earlier_prefix(self):
        self.interrupt('ring')
        checkpoint = service.decode(self.paths()['checkpoint'].read_bytes())
        self.manager.atomic(self.paths()['current'], service.encode(checkpoint['publication']))
        before = self.snapshot()
        self.refused('UNSAFE_JOURNAL', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_missing_immutable_marker_after_current_commit_is_not_recreated(self):
        self.interrupt('result')
        self.paths()['publication'].unlink()
        before = self.snapshot()
        self.refused('UNSAFE_JOURNAL', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_cold_peer_agent_and_core_uid_cannot_dispatch_publication_recovery(self):
        self.interrupt('ring')
        before = self.snapshot(); request = self.recovery_request()
        for action in ('generation-publication-read', 'generation-publication-recover'):
            self.refused('FORBIDDEN', lambda: self.manager.handle(dict(request, action=action), recovery_only=True))
        with patch.object(service, 'agent_peer', return_value=False):
            self.refused('FORBIDDEN', lambda: service.serve_request(self.manager, request, 1, 42, 42, None, None))
        with patch.object(service, 'agent_peer', return_value=True):
            self.refused('FORBIDDEN', lambda: service.serve_request(self.manager, request, 1, 0, 42, None, None))
        self.assertEqual(before, self.snapshot())

    def test_pending_paired_dropin_reload_is_reconciled_without_another_stop(self):
        self.interrupt('dropin', after=True)
        run = self.run_command
        pending = True
        def command(arguments, **options):
            nonlocal pending
            if arguments[4:] == ['daemon-reload']:
                pending = False
            result = run(arguments, **options)
            if pending and arguments[4:6] == ['show', 'kura.service']:
                result.stdout = result.stdout.replace('NeedDaemonReload=no', 'NeedDaemonReload=yes').replace(
                    'DropInPaths=/etc/systemd/system/kura.service.d/40-kura-key-generations.conf', 'DropInPaths=')
            return result
        self.component.runner = command
        self.complete_original()
        self.assertFalse(pending)
        self.assertEqual(1, sum(command[4:] == ('daemon-reload',) for command in self.commands))

    def test_foreign_loaded_dropin_cannot_be_reconciled(self):
        self.interrupt('ring')
        run = self.run_command
        def command(arguments, **options):
            result = run(arguments, **options)
            if arguments[4:6] == ['show', 'kura.service']:
                result.stdout = result.stdout.replace('DropInPaths=\n', 'DropInPaths=/etc/systemd/system/kura.service.d/foreign.conf\n')
            return result
        self.component.runner = command
        before = self.snapshot()
        self.refused('UNMANAGED_CORE', self.recover)
        self.assertEqual(before, self.snapshot())

    def test_changed_package_still_blocks_original_continuation(self):
        self.interrupt('ring')
        with patch.object(self.manager, 'require_generation_cohort', return_value=dict(self.cohort, cohortSha256='0' * 64)):
            before = self.snapshot()
            self.refused('COHORT_CHANGED', self.recover)
            self.assertEqual(before, self.snapshot())

    def test_existing_generation_set_can_continue_next_original_publication(self):
        self.publish()
        self.component.request(self.start_request(), start=True)
        old_raw, old_metadata, _ = self.manager.generations()
        old_active = (self.directory / 'kura_encryption_key').read_bytes()
        old_stage = self.state / 'generations' / self.preparation
        preserved = {path: self.component.file_snapshot(path) for path in old_stage.iterdir() if path.is_file()}
        dropin = self.component.file_snapshot(self.paths()['dropin'])
        # Use a new actual process/lease identity. Unit/cgroup boundaries remain
        # the same explicit fakes as the rest of this storage/crypto suite.
        code = '''import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/bin')
import kura_key_service as service
manager=service.Manager(Path(sys.argv[2]))
source=manager.generation_source()[-1]
_,descriptor=manager.acquire_writer_lease(dict(schema=1,action='writer-lease-acquire',**source),os.getpid(),os.geteuid())
print('READY',flush=True)
sys.stdin.read(1)
os.close(descriptor)
'''
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(self.home), str(self.root)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def stop_child():
            if child.poll() is None:
                child.stdin.write('x'); child.stdin.flush()
                child.wait(timeout=10)
            for pipe in (child.stdin, child.stdout, child.stderr):
                if not pipe.closed:
                    pipe.close()
        self.addCleanup(stop_child)
        self.assertTrue(select.select([child.stdout], [], [], 10)[0])
        line = child.stdout.readline()
        if line != 'READY\n':
            self.fail('Fresh writer did not acquire its original lease: ' + child.stderr.read()[-1000:])
        run = self.run_command
        def command(arguments, **options):
            if arguments[4:] == ['--job-mode=fail', 'stop', 'kura.service']:
                stop_child()
            result = run(arguments, **options)
            if arguments[4:6] == ['show', 'kura.service'] and self.phase == 'active':
                result.stdout = result.stdout.replace('MainPID=' + str(os.getpid()) + '\n', 'MainPID=' + str(child.pid) + '\n')
            return result
        self.component.runner = command
        self.phase = 'active'; self.set_group(True)
        self.binding = dict(keySha256=old_metadata['activeKeySha256'], ringSha256=old_metadata['ringSha256'])
        self.preparation = str(uuid.uuid4())
        self.prepared = self.manager.handle(dict(schema=1, action='generation-prepare', operationId=self.preparation,
                                               passphrase=self.password, expectedSource=self.binding))
        self.verification = str(uuid.uuid4())
        self.manager.handle(dict(schema=1, action='generation-backup-verify', operationId=self.verification,
                                 preparationId=self.preparation, expectedRingSha256=self.prepared['generation']['ringSha256'],
                                 backup=self.prepared['backup'], passphrase=self.password))
        self.publish_request = dict(schema=1, action='generation-publish', operationId=str(uuid.uuid4()),
                                    preparationId=self.preparation, verificationId=self.verification,
                                    expectedRingSha256=self.prepared['generation']['ringSha256'],
                                    expectedCohortSha256=self.cohort['cohortSha256'])
        atomic = self.manager.atomic
        def interrupt(path, value, **options):
            if path == self.paths()['activeKey']:
                raise OSError('injected second original publication boundary')
            return atomic(path, value, **options)
        with patch.object(self.manager, 'atomic', side_effect=interrupt):
            self.refused('UNKNOWN', self.publish)
        self.assertEqual(2, self.count_stops())
        self.assertEqual('SUCCEEDED', self.recover()['state'])
        self.assertEqual(2, self.count_stops())
        keys = service.key_generation_entries(self.manager.generations()[0])[0]
        self.assertEqual(service.key_generation_entries(old_raw)[0], keys[:-1])
        stage = self.state / 'generations' / self.preparation
        self.assertEqual(old_raw, (stage / 'source-keyring').read_bytes())
        self.assertEqual(old_active, (stage / 'source-active-key').read_bytes())
        self.assertEqual(dropin, self.component.file_snapshot(self.paths()['dropin']))
        self.assertEqual(preserved, {path: self.component.file_snapshot(path) for path in preserved})
        self.refused('GENERATION_START_REQUIRED', self.admission)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--cipher-jar', required=True, type=Path)
    options, remaining = parser.parse_known_args()
    base.package.CONFIG = options.repository.resolve()
    base.JAVA = options.java.resolve(); base.CIPHER = options.cipher_jar.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
