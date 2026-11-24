#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Real storage, crypto, JAR pairing and flock; systemd/process boundaries are explicit fakes."""
import argparse
import io
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch
import uuid

import test_key_generation_cohort as package
import test_key_writer_lease as writer

service = package.service
JAVA = None
CIPHER = None


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Requires disposable Linux Root and JDK21')
class GenerationPublicationTest(unittest.TestCase):
    copy = staticmethod(package.GenerationPackageTest.copy)
    put = staticmethod(writer.WriterLeaseTest.put)
    refused = writer.WriterLeaseTest.refused

    def setUp(self):
        writer.WriterLeaseTest.setUp(self)
        self.manager.cipher = [str(JAVA), *service.CIPHER[1:-1], str(CIPHER)]
        self.policy.leave()
        self.component, self.cohort = self.manager.generation_component()
        self.component.runner = self.run_command
        self.component.no_foreign_processes = Mock()
        self.component.process_group = lambda _: '/system.slice/kura.service'
        accounts = patch.object(self.component.__class__.__init__.__globals__['pwd'], 'getpwnam',
                                return_value=types.SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid()))
        accounts.start(); self.addCleanup(accounts.stop)
        self.group = self.root / 'sys/fs/cgroup/system.slice/kura.service'
        self.group.mkdir(parents=True)
        (self.group.parents[1] / 'cgroup.controllers').write_text('cpu memory\n')
        self.set_group(True)
        self.phase = 'active'
        self.commands = []
        self.stop_error = None
        self.retain_group = False
        self.fd = self.manager.acquire_writer_lease(dict(schema=1, action='writer-lease-acquire', **self.binding), os.getpid(), os.geteuid())[1]
        self.addCleanup(self.close_lease)
        self.password = 'only-a-disposable-fixture-passphrase'
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

    def close_lease(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def set_group(self, populated):
        (self.group / 'cgroup.events').write_text('populated ' + ('1' if populated else '0') + '\nfrozen 0\n')
        (self.group / 'cgroup.procs').write_text(str(os.getpid()) + '\n' if populated else '')

    def run_command(self, command, **options):
        self.assertTrue(options['close_fds'])
        self.assertEqual({'PATH': '/usr/bin:/bin', 'LANG': 'C'}, options['env'])
        self.assertEqual('/', options['cwd'])
        self.commands.append(tuple(command))
        if command[0] == '/usr/bin/busctl':
            self.assertEqual('StartUnit', command[7])
            self.assertEqual(['ss', 'kura.service', 'fail'], command[-3:])
            return subprocess.CompletedProcess(command, 0, 'o "/org/freedesktop/systemd1/job/23"\n', '')
        self.assertEqual(['/usr/bin/systemctl', '--system', '--no-ask-password', '--no-pager'], command[:4])
        if command[4:6] == ['show', 'kura.service']:
            active = self.phase == 'active'
            values = dict(Id='kura.service', LoadState='loaded', ActiveState='active' if active else 'inactive',
                          SubState='running' if active else 'dead', MainPID=str(os.getpid()) if active else '0',
                          ControlPID='0', User='kurad', Group='kurad', KillMode='control-group',
                          FragmentPath='/lib/systemd/system/kura.service', NeedDaemonReload='no',
                          DropInPaths='/etc/systemd/system/kura.service.d/40-kura-key-generations.conf'
                                      if (self.root / 'etc/systemd/system/kura.service.d/40-kura-key-generations.conf').exists() else '',
                          ControlGroup='/system.slice/kura.service' if active else '', InvocationID='1' * 32)
            return subprocess.CompletedProcess(command, 0, ''.join(k + '=' + v + '\n' for k, v in values.items()), '')
        if command[4] == 'show':
            self.assertIn(command[5], ('kura-management-agent.service', 'kura-management-agent.socket'))
            return subprocess.CompletedProcess(command, 0, 'LoadState=not-found\n', '')
        if command[4:] == ['--job-mode=fail', 'stop', 'kura.service']:
            if self.stop_error is not None:
                raise self.stop_error
            self.close_lease()
            self.phase = 'stopped'
            if not self.retain_group:
                self.set_group(False)
            return subprocess.CompletedProcess(command, 0, '', '')
        self.assertEqual(['daemon-reload'], command[4:])
        return subprocess.CompletedProcess(command, 0, '', '')

    def publish(self, request=None):
        return self.component.request(self.publish_request if request is None else request)

    def count_stops(self):
        return sum(command[-2:] == ('stop', 'kura.service') for command in self.commands)

    def start_request(self):
        return dict(schema=1, action='generation-core-start', operationId=str(uuid.uuid4()),
                    publicationId=self.publish_request['operationId'],
                    expectedRingSha256=self.prepared['generation']['ringSha256'],
                    expectedCohortSha256=self.cohort['cohortSha256'])

    def admission(self):
        return self.manager.handle(dict(schema=1, action='credential-start-admission',
                                keySha256=self.prepared['generation']['activeKeySha256'],
                                ringSha256=self.prepared['generation']['ringSha256']))

    def test_plan_is_read_only_and_requires_current_real_package_bound_writer(self):
        request = {k: v for k, v in self.publish_request.items() if k not in ('operationId', 'expectedCohortSha256')}
        request['action'] = 'generation-publication-plan'
        before = writer.WriterLeaseTest.snapshot(self)
        result = self.component.request(request)
        self.assertEqual('PUBLICATION_PLAN', result['state'])
        self.assertEqual(self.cohort['cohortSha256'], result['cohortSha256'])
        self.assertEqual(before, writer.WriterLeaseTest.snapshot(self))
        self.assertEqual(0, self.count_stops())

    def test_publication_preserves_original_material_and_requires_separate_typed_start(self):
        old = (self.directory / 'provisioned.json').read_bytes()
        result = self.publish()
        self.assertTrue(result['coreStopped'])
        self.assertTrue(result['requiresExplicitStart'])
        self.assertEqual(1, self.count_stops())
        raw, metadata, _ = self.manager.generations()
        self.assertEqual(self.prepared['generation'], metadata)
        self.assertEqual(self.key, service.key_generation_entries(raw)[0][0])
        stage = self.state / 'generations' / self.preparation
        self.assertEqual(self.key, (stage / 'source-active-key').read_bytes())
        self.assertEqual(old, (stage / 'source-provisioned.json').read_bytes())
        self.assertEqual(0o400, (stage / 'source-active-key').stat().st_mode & 0o777)
        self.assertEqual(self.publish_request['operationId'], self.component.current()['operationId'])
        self.refused('GENERATION_START_REQUIRED', self.admission)
        start = self.start_request()
        authorized = self.component.request(start, start=True)
        self.assertEqual('SYSTEMD_JOB_ACCEPTED', authorized['scope'])
        self.assertEqual('CREDENTIAL_READY', self.admission()['state'])
        commands = list(self.commands)
        self.assertEqual(authorized, self.component.request(start, start=True))
        self.assertEqual(result, self.publish())
        self.assertEqual(commands, self.commands)
        self.refused('START_ALREADY_AUTHORIZED', lambda: self.component.request(self.start_request(), start=True))

    def test_package_admits_only_original_published_credentials_and_paired_incoming_manifest(self):
        self.publish()
        fence = dict(schema=1, id=str(uuid.uuid4()), state='MAINTENANCE', firstAction='upgrade')
        self.put(self.state / 'maintenance.json', service.encode(fence))
        before = writer.WriterLeaseTest.snapshot(self)
        policy = writer.policy
        store = policy.Store(self.root)
        for action in ('upgrade', 'package'):
            self.assertTrue(store.prepare(action)['keyReady'])
        source = package.SOURCE / 'unfiltered/pkg/bin'
        readers = dict(_KURA_EMBEDDED_LIFECYCLE_SOURCE=(source / 'kura_key_service_lifecycle.py').read_bytes(),
                       _KURA_EMBEDDED_JOURNAL_SOURCE=(source / 'kura_key_journal.py').read_bytes(),
                       _KURA_INCOMING_KEY_MANIFEST_SHA256=self.cohort['manifestSha256'])
        with patch.dict(vars(policy), readers):
            self.assertTrue(store.prepare('upgrade')['keyReady'])
            with patch.object(policy, '_KURA_INCOMING_KEY_MANIFEST_SHA256', '0' * 64):
                with self.assertRaisesRegex(policy.Refused, 'cohort migration'):
                    store.prepare('upgrade')
        self.assertEqual(before, writer.WriterLeaseTest.snapshot(self))
        dropin = store.path(policy.GENERATION_DROPIN)
        dropin.chmod(0o600)
        with self.assertRaisesRegex(policy.Refused, 'paired template'):
            store.prepare('upgrade')
        dropin.chmod(0o400)
        current = self.state / 'generation-current.json'
        current.rename(current.with_suffix('.held'))
        with self.assertRaisesRegex(policy.Refused, 'Incomplete published'):
            store.prepare('upgrade')

    def test_preparation_history_published_round_allows_new_staging_without_discarding_original_material(self):
        result = self.publish()
        directory = self.state / 'generations' / self.preparation
        before = {p.name:(p.stat().st_ino, p.read_bytes()) for p in directory.iterdir()}
        source = self.manager.generation_source()[-1]
        request = dict(schema=1, action='generation-prepare', operationId=str(uuid.uuid4()),
                       expectedSource=source, passphrase=self.password)
        second = self.manager.handle(request)
        self.assertEqual(3, len(second['generation']['keySha256s']))
        self.assertEqual(before, {p.name:(p.stat().st_ino, p.read_bytes()) for p in directory.iterdir()})
        history = self.manager.handle(dict(schema=1, action='generation-history', afterPreparationId=None, limit=16))
        rows = {row['preparationId']:row for row in history['entries']}
        self.assertEqual('PUBLISHED', rows[self.preparation]['state'])
        self.assertEqual(result['publicationSha256'], rows[self.preparation]['publicationSha256'])
        self.assertEqual('PREPARED', rows[second['operationId']]['state'])

    def test_preparation_history_missing_original_publication_never_admits_another_round(self):
        self.publish()
        (self.state / 'generations' / self.preparation / 'publication.json').unlink()
        history = self.manager.handle(dict(schema=1, action='generation-history', afterPreparationId=None, limit=16))
        self.assertEqual('UNAVAILABLE', history['entries'][0]['state'])
        source = self.manager.generation_source()[-1]
        self.refused('UNSAFE_JOURNAL', lambda:self.manager.handle(dict(schema=1,
            action='generation-prepare', operationId=str(uuid.uuid4()), expectedSource=source, passphrase=self.password)))

    def test_preparation_history_original_unknown_publication_is_not_classified_as_published(self):
        original = self.manager.atomic
        def lost(path, raw, **options):
            if path == self.manager.operations / (self.publish_request['operationId'] + '.json') and b'"state":"SUCCEEDED"' in raw:
                raise OSError('Fixture lost original publication result')
            return original(path, raw, **options)
        with patch.object(self.manager, 'atomic', side_effect=lost):
            self.refused('UNKNOWN', self.publish)
        history = self.manager.handle(dict(schema=1, action='generation-history', afterPreparationId=None, limit=16))
        self.assertTrue(history['hasUnresolvedRecords'])
        self.assertEqual('UNKNOWN', history['entries'][0]['state'])
        self.assertEqual(self.publish_request['operationId'], history['entries'][0]['publicationId'])
        self.assertEqual(1, self.count_stops())

    def test_preparation_history_cancelled_round_cannot_be_published_or_planned(self):
        self.manager.handle(dict(schema=1, action='generation-cancel', operationId=str(uuid.uuid4()),
            preparationId=self.preparation, expectedHistorySha256=self.prepared['historySha256'],
            expectedRingSha256=self.prepared['generation']['ringSha256']))
        self.refused('PREPARATION_CANCELLED', self.publish)
        request = {k:v for k,v in self.publish_request.items() if k not in ('operationId','expectedCohortSha256')}
        request['action'] = 'generation-publication-plan'
        self.refused('PREPARATION_CANCELLED', lambda:self.component.request(request))
        self.assertEqual(0, self.count_stops())
        self.assertFalse((self.manager.operations / (self.publish_request['operationId'] + '.json')).exists())

    def test_unverified_archive_refuses_before_intent_or_stop(self):
        self.refused('BACKUP_NOT_VERIFIED', lambda: self.publish(dict(self.publish_request, verificationId=str(uuid.uuid4()))))
        self.assertEqual(0, self.count_stops())
        self.assertIsNone(self.manager.record(self.publish_request['operationId']))

    def test_changed_package_cannot_adopt_the_already_running_writer(self):
        path = self.home / 'bin/start_kura_background.sh'
        path.write_bytes(path.read_bytes().replace(b'1024m', b'768m'))
        self.refused('COHORT_CHANGED', self.publish)
        self.assertIsNone(self.manager.record(self.publish_request['operationId']))
        self.assertEqual(0, self.count_stops())

    def test_missing_runtime_registration_refuses_before_intent(self):
        for path in self.manager.writer_directory().glob('*.json'):
            path.unlink()
        self.refused('WRITER_UNREGISTERED', self.publish)
        self.assertIsNone(self.manager.record(self.publish_request['operationId']))
        self.assertEqual(0, self.count_stops())

    def test_original_unknown_never_repeats_stop_or_writes_on_read_or_new_id(self):
        self.stop_error = subprocess.TimeoutExpired('fixed StopUnit', 50)
        self.refused('UNKNOWN', self.publish)
        original = self.publish_request['operationId']
        self.assertEqual('INTENT', self.manager.record(original)['state'])
        self.assertEqual(self.key, (self.directory / 'kura_encryption_key').read_bytes())
        self.assertEqual('UNKNOWN', self.publish()['state'])
        self.assertEqual('UNKNOWN', self.manager.handle(dict(schema=1, action='operation-read', operationId=original))['state'])
        self.refused('UNRESOLVED_OPERATION', lambda: self.publish(dict(self.publish_request, operationId=str(uuid.uuid4()))))
        self.assertEqual(1, self.count_stops())
        with self.assertRaises(package.lifecycle.Unresolved):
            self.policy.check_records()

    def test_stop_ack_without_empty_descendant_group_cannot_publish(self):
        self.retain_group = True
        self.refused('UNKNOWN', self.publish)
        self.assertFalse((self.directory / 'kura_encryption_keyring').exists())
        self.assertEqual(self.key, (self.directory / 'kura_encryption_key').read_bytes())
        self.assertEqual(1, self.count_stops())

    def test_surviving_kernel_writer_blocks_publication_after_stop(self):
        survivor = os.dup(self.fd)
        try:
            self.refused('UNKNOWN', self.publish)
            self.assertFalse((self.directory / 'kura_encryption_keyring').exists())
            self.assertEqual(self.key, (self.directory / 'kura_encryption_key').read_bytes())
        finally:
            os.close(survivor)
        self.assertEqual('UNKNOWN', self.publish()['state'])
        self.assertEqual(1, self.count_stops())

    def test_partial_canonical_publication_keeps_original_and_remains_unknown(self):
        atomic = self.manager.atomic
        def fail_key(path, value, **options):
            if path == self.directory / 'kura_encryption_key':
                raise OSError('injected publication interruption')
            return atomic(path, value, **options)
        with patch.object(self.manager, 'atomic', side_effect=fail_key):
            self.refused('UNKNOWN', self.publish)
        self.assertTrue((self.directory / 'kura_encryption_keyring').exists())
        self.assertEqual(self.key, (self.directory / 'kura_encryption_key').read_bytes())
        self.assertEqual(self.key, (self.state / 'generations' / self.preparation / 'source-active-key').read_bytes())
        self.assertEqual('UNKNOWN', self.publish()['state'])
        self.assertEqual(1, self.count_stops())

    def test_present_canonical_files_and_commit_marker_never_settle_lost_final_receipt(self):
        atomic = self.manager.atomic
        def lose_final(path, value, **options):
            if path == self.manager.operations / (self.publish_request['operationId'] + '.json') and service.decode(value)['state'] == 'SUCCEEDED':
                raise OSError('injected lost final journal')
            return atomic(path, value, **options)
        with patch.object(self.manager, 'atomic', side_effect=lose_final):
            self.refused('UNKNOWN', self.publish)
        self.assertTrue((self.state / 'generation-current.json').exists())
        self.assertEqual(self.prepared['generation'], self.manager.generations()[1])
        self.refused('UNRESOLVED_OPERATION', self.admission)
        self.assertEqual('UNKNOWN', self.publish()['state'])
        self.refused('UNRESOLVED_OPERATION', lambda: self.component.request(self.start_request(), start=True))
        self.assertEqual(1, self.count_stops())

    def test_lost_start_receipt_never_repeats_start_and_blocks_ordinary_boot(self):
        self.publish()
        request = self.start_request()
        atomic = self.manager.atomic
        def lose_final(path, value, **options):
            if path == self.manager.operations / (request['operationId'] + '.json') and service.decode(value)['state'] == 'SUCCEEDED':
                raise OSError('injected lost StartUnit result')
            return atomic(path, value, **options)
        with patch.object(self.manager, 'atomic', side_effect=lose_final):
            self.refused('UNKNOWN', lambda: self.component.request(request, start=True))
        self.assertEqual('UNKNOWN', self.component.request(request, start=True)['state'])
        self.refused('UNRESOLVED_OPERATION', self.admission)
        self.refused('UNRESOLVED_OPERATION', lambda: self.component.request(self.start_request(), start=True))
        self.assertEqual(1, sum(command[0] == '/usr/bin/busctl' for command in self.commands))

    def test_original_stop_failure_reports_phase_without_exposing_exception_detail(self):
        self.stop_error = OSError("private worker detail")
        with patch("sys.stderr", new_callable=io.StringIO) as diagnostics:
            self.refused('UNKNOWN', self.publish)
        self.assertIn(f"{self.publish_request['operationId']} stopped at stop (OSError)", diagnostics.getvalue())
        self.assertNotIn("private worker detail", diagnostics.getvalue())
        self.assertEqual(1, self.count_stops())
        self.assertEqual('INTENT', self.manager.record(self.publish_request['operationId'])['state'])

    def test_foreign_agent_unit_is_fenced_before_intent(self):
        (self.root / 'lib/systemd/system/kura-management-agent.service').write_text('[Service]\n')
        self.refused('AGENT_GENERATION_UNAVAILABLE', self.publish)
        self.assertIsNone(self.manager.record(self.publish_request['operationId']))
        self.assertEqual(0, self.count_stops())

    def test_cold_peer_cannot_publish_start_or_get_a_publication_plan(self):
        for action in ('generation-publication-plan', 'generation-publish', 'generation-core-start'):
            self.refused('FORBIDDEN', lambda: self.manager.handle(dict(self.publish_request, action=action), recovery_only=True))
        self.assertEqual([], self.commands)

    def test_generation_component_ignores_unverified_pyc_and_keeps_base_independent(self):
        (self.home / 'bin/__pycache__').mkdir()
        (self.home / 'bin/__pycache__/kura_key_generation.cpython-312.pyc').write_bytes(b'untrusted cache')
        component, binding = self.manager.generation_component()
        self.assertEqual(self.cohort, binding)
        self.assertIsNotNone(component)
        (self.home / 'bin/kura_key_generation.py').unlink()
        self.assertEqual(2, self.policy.assets()['protocol'])
        self.refused('COHORT_UNAVAILABLE', self.manager.generation_component)

    def test_missing_generation_halves_never_fall_back_to_single_key_backup_or_boot(self):
        self.publish()
        self.component.request(self.start_request(), start=True)
        (self.directory / 'kura_encryption_keyring').unlink()
        (self.directory / 'key-generations.json').unlink()
        self.refused('GENERATION_REQUIRED', lambda: self.manager.handle(dict(schema=1, action='backup-create',
                     operationId=str(uuid.uuid4()), passphrase=self.password)))
        self.refused('GENERATION_REQUIRED', self.admission)
        # Even losing the convenience marker cannot erase the original successful publication journal.
        (self.state / 'generation-current.json').unlink()
        self.refused('GENERATION_REQUIRED', lambda: self.manager.canonical())


class EntrypointIdentityTest(unittest.TestCase):
    def test_actual_isolated_main_and_lazy_helpers_share_protocol_exceptions(self):
        script = '''import importlib.util, sys
path = sys.argv[1]
spec = importlib.util.spec_from_file_location('__main__', path)
module = importlib.util.module_from_spec(spec)
sys.modules['__main__'] = module
sys.argv = [path]
try:
    spec.loader.exec_module(module)
except SystemExit as stopped:
    assert stopped.code == 2
else:
    raise AssertionError('Invalid entrypoint arguments must refuse without a daemon or client')
import kura_key_recovery_start, kura_key_generation
assert module.Failure is kura_key_recovery_start.Failure
assert module.Failure is kura_key_generation.Failure
print('ROOT_MAIN_HELPERS_SHARE_PROTOCOL')
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script,
                                 str(package.SOURCE / 'unfiltered/pkg/bin/kura_key_service.py')],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('ROOT_MAIN_HELPERS_SHARE_PROTOCOL\n', result.stdout)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--java', type=Path, required=True)
    parser.add_argument('--cipher-jar', type=Path, required=True)
    args, remaining = parser.parse_known_args()
    package.CONFIG = args.repository.resolve()
    JAVA = args.java.resolve()
    CIPHER = args.cipher_jar.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
