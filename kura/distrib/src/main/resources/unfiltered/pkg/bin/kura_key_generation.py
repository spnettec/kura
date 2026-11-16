#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fixed-unit generation publication. Original uncertain dispatches are never retried."""
import hashlib
import hmac
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
import time

from kura_key_service import (Failure, require, fields, digest, operation_id, encode, decode,
                              KEY_PATH, RECEIPT_PATH, RING_PATH, GENERATION_RECEIPT_PATH,
                              GENERATION_FORMAT, key_generations)
from kura_key_service_lifecycle import (Lifecycle, Refused, validate_generation_metadata, validate_publication,
    handoff_revocations, handoff_revocation_view, HANDOFF_REVOCATION_PURPOSE, HANDOFF_REVOCATION_CONTEXT)

DROPIN = '/etc/systemd/system/kura.service.d/40-kura-key-generations.conf'
TEMPLATE = 'share/key-management/key-generations.conf'
CURRENT = 'generation-current.json'
PURPOSE = 'yofc-kura-published-generation-v1'
RECOVERY = 'publication-recovery.json'
RECOVERY_PURPOSE = 'yofc-kura-publication-recovery-v1'
RECOVERY_CONTEXT = b'yofc-kura-publication-recovery-v1\0'
PROPERTIES = ('Id', 'LoadState', 'ActiveState', 'SubState', 'MainPID', 'ControlPID', 'User', 'Group',
              'KillMode', 'FragmentPath', 'DropInPaths', 'NeedDaemonReload', 'ControlGroup', 'InvocationID')
SYSTEMCTL = ('/usr/bin/systemctl', '--system', '--no-ask-password', '--no-pager')
START = ('/usr/bin/busctl', '--system', '--timeout=15s', 'call', 'org.freedesktop.systemd1',
         '/org/freedesktop/systemd1', 'org.freedesktop.systemd1.Manager', 'StartUnit', 'ss', 'kura.service', 'fail')


class Generations:
    def __init__(self, manager, runner=None):
        self.manager = manager
        self.runner = subprocess.run if runner is None else runner

    def command(self, command, *, timeout=15):
        result = self.runner(list(command), capture_output=True, text=True, timeout=timeout,
                             check=False, close_fds=True, cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C'})
        require(result.returncode == 0 and isinstance(result.stdout, str) and len(result.stdout) <= 8192,
                'SYSTEMD_UNAVAILABLE')
        return result.stdout

    def unit(self, *, generation_mode, recovery=False):
        raw = self.command((*SYSTEMCTL, 'show', 'kura.service', *['--property=' + p for p in PROPERTIES]))
        lines = raw.splitlines()
        require(len(lines) == len(PROPERTIES) and all('=' in line for line in lines), 'UNMANAGED_CORE')
        result = dict(line.split('=', 1) for line in lines)
        require(set(result) == set(PROPERTIES), 'UNMANAGED_CORE')
        require(all(result[k] == v for k, v in dict(Id='kura.service', LoadState='loaded', User='kurad', Group='kurad',
                                                  KillMode='control-group').items())
                and result['NeedDaemonReload'] in (('no', 'yes') if recovery else ('no',)), 'UNMANAGED_CORE')
        require(result['FragmentPath'] in ('/lib/systemd/system/kura.service', '/usr/lib/systemd/system/kura.service')
                and self.manager.store.path(result['FragmentPath']).resolve(strict=True)
                == self.manager.store.path('/lib/systemd/system/kura.service').resolve(strict=True), 'UNMANAGED_CORE')
        require(result['DropInPaths'] in (('', DROPIN) if recovery else ((DROPIN if generation_mode else ''),)), 'UNMANAGED_CORE')
        require(all(re.fullmatch(r'[0-9]{1,10}', result[k]) is not None for k in ('MainPID', 'ControlPID')), 'UNMANAGED_CORE')
        require(result['ControlGroup'] in ('', '/system.slice/kura.service')
                and re.fullmatch(r'(?:[0-9a-f]{32})?', result['InvocationID']) is not None, 'UNMANAGED_CORE')
        return result

    def dropin(self, *, generation_mode):
        manager = self.manager
        path = manager.store.path(DROPIN)
        manager.directory(path.parent, private=True)
        names = [p.name for p in path.parent.iterdir()]
        require(names == [path.name] if generation_mode else not names, 'UNMANAGED_CORE')
        home = manager.store.path('/opt/eclipse/kura').resolve(strict=True)
        template = Lifecycle(manager.root, manager.owner).read(home / TEMPLATE, private=False)
        require(template == b'[Service]\nLoadCredential=kura_encryption_keyring:/etc/kura/credentials/kura_encryption_keyring\n'
                            b'LoadCredential=key-generations.json:/etc/kura/credentials/key-generations.json\n', 'COHORT_UNAVAILABLE')
        if generation_mode:
            require(manager.read(path, 4096) == template, 'UNMANAGED_CORE')
        return template

    @staticmethod
    def process_group(pid):
        raw = (Path('/proc') / str(pid) / 'cgroup').read_text()
        lines = raw.splitlines()
        require(len(lines) == 1 and lines[0].startswith('0::/'), 'UNSUPPORTED_CGROUP')
        return lines[0][3:]

    def no_foreign_processes(self, uid):
        # The whole managed control group is drained. Same-UID processes outside it
        # could still carry old credentials and must be rejected before publication.
        require(type(uid) is int and uid > 0, 'UNMANAGED_CORE')
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():
                continue
            try:
                if path.stat().st_uid != uid:
                    continue
                group = self.process_group(int(path.name))
            except FileNotFoundError:
                continue
            require(group == '/system.slice/kura.service' or group.startswith('/system.slice/kura.service/'), 'UNMANAGED_WRITER')

    def cgroup_empty(self, *, required=False):
        base = self.manager.store.path('/sys/fs/cgroup')
        require((base / 'cgroup.controllers').is_file(), 'UNSUPPORTED_CGROUP')
        path = base / 'system.slice/kura.service'
        if not path.exists():
            require(not required, 'UNMANAGED_CORE')
            return True
        try:
            events = (path / 'cgroup.events').read_text()
            processes = (path / 'cgroup.procs').read_text()
        except FileNotFoundError:
            # Called after a successful synchronous StopUnit, never to settle a lost dispatch.
            if not required and not path.exists():
                return True
            raise
        require(len(events) <= 256 and len(processes) <= 65536, 'UNSUPPORTED_CGROUP')
        entries = [line.split() for line in events.splitlines()]
        require(entries and all(len(row) == 2 for row in entries), 'UNSUPPORTED_CGROUP')
        values = dict(entries)
        require(len(values) == len(entries) and values.get('populated') in ('0', '1'), 'UNSUPPORTED_CGROUP')
        return values['populated'] == '0' and not processes.strip()

    def no_optional_agent(self):
        # Its existing single-key validation path is not a generation delegation.
        for name in ('kura-management-agent.service', 'kura-management-agent.socket'):
            raw = self.command((*SYSTEMCTL, 'show', name, '--property=LoadState'))
            require(raw.strip() == 'LoadState=not-found', 'AGENT_GENERATION_UNAVAILABLE')
            for base in ('/etc/systemd/system', '/run/systemd/system', '/lib/systemd/system', '/usr/lib/systemd/system'):
                require(not os.path.lexists(self.manager.store.path(base + '/' + name)), 'AGENT_GENERATION_UNAVAILABLE')

    def current(self):
        manager = self.manager
        value = decode(manager.read(manager.state / CURRENT, 8192))
        try:
            validate_publication(value)
        except Refused:
            raise Failure('UNSAFE_JOURNAL') from None
        raw = encode(value)
        immutable = manager.state / 'generations' / value['preparationId'] / 'publication.json'
        require(manager.read(immutable, 8192) == raw, 'UNSAFE_JOURNAL')
        record = manager.record(value['operationId'])
        require(record is not None and record['action'] == 'generation-publish' and record['state'] == 'SUCCEEDED', 'UNRESOLVED_OPERATION')
        response = record['response']
        require(response['publicationSha256'] == hashlib.sha256(raw).hexdigest()
                and all(response[k] == value[k] for k in ('preparationId', 'verificationId', 'cohortSha256'))
                and response['ringSha256'] == value['generation']['ringSha256']
                and response['activeKeySha256'] == value['generation']['activeKeySha256'], 'UNSAFE_JOURNAL')
        return value

    def require_start(self, source, cohort):
        manager = self.manager
        publications = [manager.record(p.name[:-5]) for p in manager.operations.iterdir()]
        publications = [r for r in publications if r['action'] == 'generation-publish']
        if not publications and not os.path.lexists(manager.state / CURRENT):
            return  # Pre-existing original-set restoration profile; never fabricate a publication.
        current = self.current()
        require(source == dict(keySha256=current['generation']['activeKeySha256'], ringSha256=current['generation']['ringSha256']), 'CONFLICT')
        self.dropin(generation_mode=True)
        matches = [manager.record(p.name[:-5]) for p in manager.operations.iterdir()]
        matches = [r for r in matches if r['action'] == 'generation-core-start' and r['state'] == 'SUCCEEDED'
                   and r['response']['publicationId'] == current['operationId']]
        require(len(matches) == 1, 'GENERATION_START_REQUIRED')
        response = matches[0]['response']
        require(response['ringSha256'] == source['ringSha256'] and response['activeKeySha256'] == source['keySha256']
                and response['cohortSha256'] == cohort['cohortSha256'], 'COHORT_CHANGED')

    def prepared(self, request):
        manager = self.manager
        raw, history, prepared = manager.prepared_generation(request['preparationId'])
        manager.require_open_preparation(request['preparationId'])
        verification = manager.record(request['verificationId'])
        require(verification is not None and verification['action'] == 'generation-backup-verify'
                and verification['state'] == 'SUCCEEDED', 'BACKUP_NOT_VERIFIED')
        response = verification['response']
        require(response['preparationId'] == request['preparationId']
                and response['ringSha256'] == request['expectedRingSha256'] == history['generation']['ringSha256']
                and response['backupSha256'] == history['backupSha256'], 'BACKUP_NOT_VERIFIED')
        _, _, _, metadata, proof, source = manager.generation_source()
        require(history['source'] == source and history['sourceReceipt'] == proof
                and history['sourceGenerationReceipt'] == metadata, 'CONFLICT')
        cohort = manager.require_generation_cohort()
        template = self.dropin(generation_mode=source['ringSha256'] is not None)
        self.no_optional_agent()
        return raw, history, prepared, source, cohort, template

    def active_core(self, source, cohort):
        manager = self.manager
        unit = self.unit(generation_mode=source['ringSha256'] is not None)
        require(unit['ActiveState'] == 'active' and unit['SubState'] == 'running'
                and int(unit['MainPID']) > 0 and unit['ControlPID'] == '0'
                and unit['ControlGroup'] == '/system.slice/kura.service'
                and len(unit['InvocationID']) == 32, 'CORE_NOT_ACTIVE')
        pid = int(unit['MainPID'])
        writer = manager.writer_registration(pid)
        require(all(writer[k] == source[k] for k in source) and writer['cohortSha256'] == cohort['cohortSha256'], 'COHORT_CHANGED')
        fd = manager.writer_lock()
        try:
            metadata = os.fstat(fd)
            require((metadata.st_dev, metadata.st_ino) == (writer['lockDevice'], writer['lockInode']), 'UNSAFE_WRITER_STATE')
        finally:
            os.close(fd)
        require(writer['uid'] == pwd.getpwnam('kurad').pw_uid
                and self.process_group(pid) == unit['ControlGroup'], 'UNMANAGED_CORE')
        self.no_foreign_processes(writer['uid'])
        require(not self.cgroup_empty(required=True), 'CORE_NOT_ACTIVE')
        return unit, writer

    def stopped(self, *, generation_mode, uid, recovery=False):
        unit = self.unit(generation_mode=generation_mode, recovery=recovery)
        require(unit['ActiveState'] == 'inactive' and unit['SubState'] == 'dead'
                and unit['MainPID'] == '0' and unit['ControlPID'] == '0' and self.cgroup_empty(), 'CORE_NOT_DRAINED')
        self.no_foreign_processes(uid)

    def publication_paths(self):
        manager = self.manager
        return dict(ring=manager.store.path(RING_PATH), activeKey=manager.store.path(KEY_PATH),
                    provisioned=manager.store.path(RECEIPT_PATH), generationReceipt=manager.store.path(GENERATION_RECEIPT_PATH),
                    dropin=manager.store.path(DROPIN), current=manager.state / CURRENT)

    def file_snapshot(self, path):
        try:
            before = path.lstat()
        except FileNotFoundError:
            return None
        raw = self.manager.read(path, 8192)
        after = path.lstat()
        def metadata(value):
            return dict(device=value.st_dev, inode=value.st_ino, uid=value.st_uid, gid=value.st_gid,
                        mode=stat.S_IMODE(value.st_mode), nlink=value.st_nlink, size=value.st_size,
                        mtimeNs=value.st_mtime_ns, ctimeNs=value.st_ctime_ns)
        require(metadata(before) == metadata(after), 'UNSAFE_FILESYSTEM')
        return dict(metadata(after), sha256=hashlib.sha256(raw).hexdigest())

    def recovery_receipt(self, identity):
        manager = self.manager
        records = manager.record(identity)
        require(records is not None and records['action'] == 'generation-publish', 'CONFLICT')
        # Find only the checkpoint belonging to this original operation. No path
        # or replacement publication/preparation ID is accepted from the caller.
        matches = []
        for preparation in manager.preparation_ids(manager.preparation_records()):
            path = manager.state / 'generations' / preparation / RECOVERY
            if not os.path.lexists(path):
                continue
            raw = manager.read(path, 8192)
            value = decode(raw)
            fields(value, {'schema', 'purpose', 'publication', 'sourceFiles', 'writerUid', 'receiptTag'})
            require(type(value['schema']) is int and value['schema'] == 1
                    and value['purpose'] == RECOVERY_PURPOSE and raw == encode(value), 'UNSAFE_JOURNAL')
            digest(value['receiptTag'])
            body = {key: item for key, item in value.items() if key != 'receiptTag'}
            secret = manager.read(manager.state / 'journal.key', 32)
            require(len(secret) == 32 and hmac.compare_digest(value['receiptTag'],
                    hmac.new(secret, RECOVERY_CONTEXT + encode(body), hashlib.sha256).hexdigest()), 'UNSAFE_JOURNAL')
            try:
                publication = validate_publication(value['publication'])
            except Refused:
                raise Failure('UNSAFE_JOURNAL') from None
            require(publication['preparationId'] == preparation and stat.S_IMODE(path.lstat().st_mode) == 0o400,
                    'UNSAFE_JOURNAL')
            files = value['sourceFiles']
            fields(files, set(self.publication_paths()))
            require(type(value['writerUid']) is int and value['writerUid'] >= 0, 'UNSAFE_JOURNAL')
            for name, metadata in files.items():
                if metadata is None:
                    require(name not in ('activeKey', 'provisioned'), 'UNSAFE_JOURNAL')
                    continue
                fields(metadata, {'device', 'inode', 'uid', 'gid', 'mode', 'nlink', 'size', 'mtimeNs', 'ctimeNs', 'sha256'})
                digest(metadata['sha256'])
                require(all(type(metadata[key]) is int and metadata[key] >= 0 for key in metadata if key != 'sha256')
                        and metadata['inode'] > 0 and metadata['uid'] == manager.owner and metadata['nlink'] == 1
                        and metadata['mode'] in (0o400, 0o600) and metadata['size'] <= 8192, 'UNSAFE_JOURNAL')
            if publication['operationId'] == identity:
                request = dict(schema=1, action='generation-publish', operationId=identity,
                               preparationId=preparation, verificationId=publication['verificationId'],
                               expectedRingSha256=publication['generation']['ringSha256'],
                               expectedCohortSha256=publication['cohortSha256'])
                require(hmac.compare_digest(records['requestTag'],
                        hmac.new(secret, encode(request), hashlib.sha256).hexdigest()), 'UNSAFE_JOURNAL')
                matches.append((raw, value, request))
        require(len(matches) <= 1, 'UNSAFE_JOURNAL')
        return matches[0] if matches else None

    def publication_read(self, request):
        fields(request, {'schema', 'action', 'operationId'})
        require(type(request['schema']) is int and request['schema'] == 1
                and request['action'] == 'generation-publication-read', 'INVALID_ARGUMENT')
        identity = operation_id(request['operationId'])
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', False):
            manager.maintenance()
            record = manager.record(identity)
            require(record is not None and record['action'] == 'generation-publish', 'CONFLICT')
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                receipt = self.recovery_receipt(identity)
                return dict(schema=1, action=request['action'], operationId=identity,
                            state='SUCCEEDED' if record['state'] == 'SUCCEEDED' else 'UNKNOWN',
                            scope='ORIGINAL_PUBLICATION_ONLY',
                            recoveryReceiptSha256=hashlib.sha256(receipt[0]).hexdigest() if receipt else None,
                            originalResult=manager.public_record(record), startupAuthorized=False)

    def publication_targets(self, value, raw, history, template):
        active, metadata = key_generations(raw)
        publication = encode(value)
        return dict(ring=(raw, 0o400), activeKey=(active, 0o400), provisioned=(encode(history['provisioned']), 0o600),
                    generationReceipt=(encode(dict(schema=1, purpose=GENERATION_FORMAT, **metadata)), 0o600),
                    dropin=(template, 0o400), current=(publication, 0o600))

    def publication_progress(self, value, targets, source_files):
        manager = self.manager
        paths = self.publication_paths()
        paths['publication'] = manager.state / 'generations' / value['preparationId'] / 'publication.json'
        expected = dict(targets, publication=(encode(value), 0o400))
        states = {}
        old_seen = False
        for name in ('ring', 'activeKey', 'provisioned', 'generationReceipt', 'dropin', 'publication', 'current'):
            current = self.file_snapshot(paths[name])
            data, mode = expected[name]
            before = source_files.get(name)
            new = current is not None and current['sha256'] == hashlib.sha256(data).hexdigest() and current['mode'] == mode
            old = current == before
            require(new or old, 'CONFLICT')
            # Durable operations have a fixed order. A later receipt cannot
            # authorize filling a foreign gap in an earlier completed step.
            if new and not old:
                require(not old_seen, 'UNSAFE_JOURNAL')
            elif old and not new:
                old_seen = True
            states[name] = new
        return paths, expected, states

    def finish_publication(self, value, raw, history, cohort, template, record, source_files, uid, *, recovering=False):
        manager = self.manager
        targets = self.publication_targets(value, raw, history, template)
        paths, expected, done = self.publication_progress(value, targets, source_files)
        for name in ('ring', 'activeKey', 'provisioned', 'generationReceipt', 'dropin'):
            if not done[name]:
                data, mode = expected[name]
                manager.atomic(paths[name], data, mode=mode, no_replace=source_files[name] is None)
        if recovering:
            unit = self.unit(generation_mode=True, recovery=True)
            reload_needed = unit['NeedDaemonReload'] == 'yes' or unit['DropInPaths'] != DROPIN
        else:
            reload_needed = True
        if reload_needed:
            self.command((*SYSTEMCTL, 'daemon-reload'))
        self.stopped(generation_mode=True, uid=uid)
        require(manager.generations()[1] == value['generation'] and manager.require_generation_cohort() == cohort, 'COHORT_CHANGED')
        self.dropin(generation_mode=True)
        for name in ('publication', 'current'):
            if not done[name]:
                data, mode = expected[name]
                manager.atomic(paths[name], data, mode=mode, no_replace=name == 'publication' or source_files.get(name) is None)
        # Reconcile a visible rename whose directory sync was interrupted.
        for directory in {path.parent for path in paths.values()}:
            manager.sync(directory)
        publication = encode(value)
        response = dict(schema=1, operationId=value['operationId'], action='generation-publish', state='SUCCEEDED',
                        preparationId=value['preparationId'], verificationId=value['verificationId'],
                        ringSha256=value['generation']['ringSha256'], activeKeySha256=value['generation']['activeKeySha256'],
                        cohortSha256=cohort['cohortSha256'], publicationSha256=hashlib.sha256(publication).hexdigest(),
                        coreStopped=True, requiresExplicitStart=True)
        record.update(state='SUCCEEDED', response=response)
        manager.atomic(manager.operations / (value['operationId'] + '.json'), encode(record))
        return response

    def recover_publication(self, request):
        fields(request, {'schema', 'action', 'operationId', 'expectedRecoveryReceiptSha256'})
        require(type(request['schema']) is int and request['schema'] == 1
                and request['action'] == 'generation-publication-recover', 'INVALID_ARGUMENT')
        identity = operation_id(request['operationId'])
        digest(request['expectedRecoveryReceiptSha256'])
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', True):
            manager.maintenance()
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), True):
                record = manager.record(identity)
                require(record is not None and record['action'] == 'generation-publish', 'CONFLICT')
                receipt = self.recovery_receipt(identity)
                if receipt is None:
                    return manager.public_record(record)  # Never fabricate a stop/lock handoff proof.
                receipt_raw, checkpoint, _ = receipt
                require(hashlib.sha256(receipt_raw).hexdigest() == request['expectedRecoveryReceiptSha256'], 'CONFLICT')
                if record['state'] == 'SUCCEEDED':
                    return manager.public_record(record)
                manager.settled(recovering_publication=identity)
                value = checkpoint['publication']
                raw, history, prepared = manager.prepared_generation(value['preparationId'])
                require(prepared['historySha256'] == value['historySha256']
                        and history['generation'] == value['generation'] and history['source'] == value['source'], 'CONFLICT')
                directory = manager.state / 'generations' / value['preparationId']
                require(not os.path.lexists(directory / 'cancellation.json'), 'CONFLICT')
                verification = manager.record(value['verificationId'])
                require(verification is not None and verification['action'] == 'generation-backup-verify'
                        and verification['state'] == 'SUCCEEDED'
                        and verification['response']['preparationId'] == value['preparationId']
                        and verification['response']['ringSha256'] == value['generation']['ringSha256']
                        and verification['response']['backupSha256'] == history['backupSha256'], 'BACKUP_NOT_VERIFIED')
                files = checkpoint['sourceFiles']
                require(hashlib.sha256(manager.read(directory / 'source-active-key', 32)).hexdigest()
                        == files['activeKey']['sha256'] == value['source']['keySha256'], 'CONFLICT')
                proof = manager.read(directory / 'source-provisioned.json', 8192)
                require(hashlib.sha256(proof).hexdigest() == files['provisioned']['sha256']
                        and decode(proof) == history['sourceReceipt'], 'CONFLICT')
                generation = value['source']['ringSha256'] is not None
                require((files['ring'] is not None) == (files['generationReceipt'] is not None) == generation
                        and (files['dropin'] is not None) == generation, 'CONFLICT')
                if generation:
                    old_ring = manager.read(directory / 'source-keyring', 512)
                    old_receipt = manager.read(directory / 'source-generation-receipt.json', 2048)
                    require(hashlib.sha256(old_ring).hexdigest() == files['ring']['sha256'] == value['source']['ringSha256']
                            and hashlib.sha256(old_receipt).hexdigest() == files['generationReceipt']['sha256']
                            and decode(old_receipt) == dict(schema=1, purpose=GENERATION_FORMAT,
                                                           **history['sourceGenerationReceipt']), 'CONFLICT')
                cohort = manager.require_generation_cohort()
                require(cohort['cohortSha256'] == value['cohortSha256'], 'COHORT_CHANGED')
                self.no_optional_agent()
                template = self.dropin(generation_mode=os.path.lexists(manager.store.path(DROPIN)))
                require(value['stoppedWriter']['bootId'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                        'UNSAFE_WRITER_STATE')
                uid = checkpoint['writerUid']
                require(uid == pwd.getpwnam('kurad').pw_uid, 'UNMANAGED_CORE')
                self.stopped(generation_mode=generation, uid=uid, recovery=True)
                with manager.exclusive_writers() as locked:
                    require((locked.st_dev, locked.st_ino) == (value['stoppedWriter']['lockDevice'],
                            value['stoppedWriter']['lockInode']), 'UNSAFE_WRITER_STATE')
                    self.stopped(generation_mode=generation, uid=uid, recovery=True)
                    self.publication_progress(value, self.publication_targets(value, raw, history, template), files)
                    try:
                        manager.sync(directory)
                        return self.finish_publication(value, raw, history, cohort, template, record, files, uid, recovering=True)
                    except (OSError, Failure, Refused, subprocess.TimeoutExpired, ValueError, KeyError):
                        raise Failure('UNKNOWN') from None

    def request(self, request, *, start=False, expected_owner=None):
        manager = self.manager
        plan = request['action'] == 'generation-publication-plan'
        require(request['action'] in ('generation-publication-plan', 'generation-publish', 'generation-core-start')
                and start == (request['action'] == 'generation-core-start'), 'INVALID_ARGUMENT')
        names = {'schema', 'action', 'expectedRingSha256'} | ({'publicationId'} if start else {'preparationId', 'verificationId'})
        if not plan:
            names |= {'operationId', 'expectedCohortSha256'}
        fields(request, names)
        require(type(request['schema']) is int and request['schema'] == 1, 'INVALID_ARGUMENT')
        for name in ('publicationId',) if start else ('preparationId', 'verificationId'):
            operation_id(request[name])
        digest(request['expectedRingSha256'])
        if not plan:
            identity = operation_id(request['operationId'])
            digest(request['expectedCohortSha256'])
        with manager.lock(manager.state / 'admission.lock', not plan):
            manager.maintenance()
            if not plan:
                manager.require_unrevoked_operation(identity)
                secret = manager.read(manager.state / 'journal.key', 32)
                require(len(secret) == 32, 'UNSAFE_JOURNAL')
                tag = hmac.new(secret, encode(request), hashlib.sha256).hexdigest()
                prior = manager.record(identity)
                if prior is not None:
                    require(hmac.compare_digest(prior['requestTag'], tag), 'CONFLICT')
                    return manager.public_record(prior)
            manager.settled()
            if not plan:
                manager.journal_admission()
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), not plan and not start):
                if start:
                    return self.start(request, identity, tag, expected_owner=expected_owner)
                raw, history, prepared, source, cohort, template = self.prepared(request)
                unit, writer = self.active_core(source, cohort)
                if expected_owner is not None:
                    require(all(writer[name] == expected_owner[name] for name in
                                ('pid', 'uid', 'startTicks', 'bootId', 'lockDevice', 'lockInode'))
                            and unit['InvocationID'] == expected_owner['invocationId'], 'OWNER_CHANGED')
                if plan:
                    return dict(schema=1, state='PUBLICATION_PLAN', preparationId=request['preparationId'],
                                verificationId=request['verificationId'], ringSha256=history['generation']['ringSha256'],
                                cohortSha256=cohort['cohortSha256'], corePid=writer['pid'], requiresExplicitCommit=True)
                require(request['expectedCohortSha256'] == cohort['cohortSha256'], 'COHORT_CHANGED')
                require(not os.path.lexists(manager.state / 'generations' / request['preparationId'] / 'publication.json'), 'ALREADY_PUBLISHED')
                record = dict(schema=1, operationId=identity, action=request['action'], requestTag=tag, state='INTENT', response=None)
                try:
                    manager.atomic(manager.operations / (identity + '.json'), encode(record))
                    directory = manager.state / 'generations' / request['preparationId']
                    # Preserve exact old bytes before any stop or canonical replacement.
                    manager.atomic(directory / 'source-active-key', manager.read(manager.store.path(KEY_PATH), 32), mode=0o400, no_replace=True)
                    manager.atomic(directory / 'source-provisioned.json', manager.read(manager.store.path(RECEIPT_PATH), 8192), mode=0o400, no_replace=True)
                    if source['ringSha256'] is not None:
                        manager.atomic(directory / 'source-generation-receipt.json', manager.read(manager.store.path(GENERATION_RECEIPT_PATH), 2048), mode=0o400, no_replace=True)
                    # Synchronous StopUnit completion is mandatory, once for this original UUID.
                    self.command((*SYSTEMCTL, '--job-mode=fail', 'stop', 'kura.service'), timeout=50)
                    self.stopped(generation_mode=source['ringSha256'] is not None, uid=writer['uid'])
                    with manager.exclusive_writers() as locked:
                        require((locked.st_dev, locked.st_ino) == (writer['lockDevice'], writer['lockInode']), 'UNSAFE_WRITER_STATE')
                        again = self.prepared(request)
                        require(again[:5] == (raw, history, prepared, source, cohort), 'COHORT_CHANGED')
                        self.stopped(generation_mode=source['ringSha256'] is not None, uid=writer['uid'])
                        active, metadata = key_generations(raw)
                        value = dict(schema=1, purpose=PURPOSE, operationId=identity,
                                     preparationId=request['preparationId'], verificationId=request['verificationId'],
                                     historySha256=prepared['historySha256'], source=source, generation=metadata,
                                     cohortSha256=cohort['cohortSha256'], stoppedWriter=dict(pid=writer['pid'],
                                     startTicks=writer['startTicks'], bootId=writer['bootId'], invocationId=unit['InvocationID'],
                                     lockDevice=writer['lockDevice'], lockInode=writer['lockInode']))
                        # Only a completed original StopUnit plus the exclusive
                        # kernel writer handoff may authorize local continuation.
                        # A crash before this immutable proof stays UNKNOWN.
                        source_files = {name: self.file_snapshot(path) for name, path in self.publication_paths().items()}
                        checkpoint = dict(schema=1, purpose=RECOVERY_PURPOSE, publication=value,
                                          sourceFiles=source_files, writerUid=writer['uid'])
                        checkpoint['receiptTag'] = hmac.new(secret, RECOVERY_CONTEXT + encode(checkpoint), hashlib.sha256).hexdigest()
                        manager.atomic(directory / RECOVERY, encode(checkpoint), mode=0o400, no_replace=True)
                        # Canonical state stays boot-fenced by this same original
                        # INTENT until all fixed steps and the final result sync.
                        return self.finish_publication(value, raw, history, cohort, template, record, source_files, writer['uid'])
                except (OSError, Failure, Refused, subprocess.TimeoutExpired, ValueError, KeyError):
                    raise Failure('UNKNOWN') from None

    def start(self, request, identity, tag, *, expected_owner=None):
        manager = self.manager
        current = self.current()
        require(request['publicationId'] == current['operationId']
                and request['expectedRingSha256'] == current['generation']['ringSha256'], 'CONFLICT')
        _, metadata, _ = manager.generations()
        cohort = manager.require_generation_cohort()
        require(metadata == current['generation'] and request['expectedCohortSha256'] == cohort['cohortSha256'] == current['cohortSha256'], 'COHORT_CHANGED')
        self.no_optional_agent(); self.dropin(generation_mode=True)
        self.stopped(generation_mode=True, uid=pwd.getpwnam('kurad').pw_uid)
        for path in manager.operations.iterdir():
            prior = manager.record(path.name[:-5])
            require(prior['action'] != 'generation-core-start' or prior['response']['publicationId'] != current['operationId'], 'START_ALREADY_AUTHORIZED')
        with manager.exclusive_writers() as locked:
            if expected_owner is not None:
                require((locked.st_dev, locked.st_ino) == (expected_owner['lockDevice'], expected_owner['lockInode'])
                        and expected_owner['bootId'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
                        and expected_owner['uid'] == pwd.getpwnam('kurad').pw_uid, 'UNSAFE_WRITER_STATE')
            self.stopped(generation_mode=True, uid=pwd.getpwnam('kurad').pw_uid)
            record = dict(schema=1, operationId=identity, action=request['action'], requestTag=tag, state='INTENT', response=None)
            try:
                manager.atomic(manager.operations / (identity + '.json'), encode(record))
                raw = self.command(START, timeout=18)
                match = re.fullmatch(r'o "(/org/freedesktop/systemd1/job/[0-9]+)"\n?', raw)
                require(match is not None, 'UNKNOWN')
                response = dict(schema=1, operationId=identity, action=request['action'], state='SUCCEEDED',
                                publicationId=current['operationId'], ringSha256=metadata['ringSha256'],
                                activeKeySha256=metadata['activeKeySha256'], cohortSha256=cohort['cohortSha256'],
                                scope='SYSTEMD_JOB_ACCEPTED', jobPath=match[1])
                record.update(state='SUCCEEDED', response=response)
                manager.atomic(manager.operations / (identity + '.json'), encode(record))
                return response
            except (OSError, Failure, Refused, subprocess.TimeoutExpired, ValueError, KeyError):
                raise Failure('UNKNOWN') from None


HANDOFF_PURPOSE = 'yofc-kura-generation-handoff-v1'
HANDOFF_RECEIPT = b'yofc-kura-generation-handoff-receipt-v1\0'
HANDOFF_TOKEN = b'yofc-kura-generation-handoff-token-v1\0'
HANDOFF_REQUEST = frozenset(('schema', 'action', 'handoffId', 'preparationId', 'verificationId',
                             'publicationId', 'startOperationId', 'expectedRingSha256', 'expectedCohortSha256', 'operator'))


class Handoffs:
    """A recorded authority delegates only two preselected original operations.

    It is not a key-operation result or a general recovery credential. Bearer
    bytes are derived on demand and never stored in the authorization record.
    """
    def __init__(self, manager):
        self.manager = manager
        self.generations = Generations(manager)
        self.clock = lambda: time.clock_gettime_ns(time.CLOCK_BOOTTIME)

    def secret(self):
        value = self.manager.read(self.manager.state / 'journal.key', 32)
        require(len(value) == 32, 'UNSAFE_JOURNAL')
        return value

    @staticmethod
    def validate_request(value):
        fields(value, HANDOFF_REQUEST)
        require(type(value['schema']) is int and value['schema'] == 1
                and value['action'] == 'generation-handoff-create', 'INVALID_ARGUMENT')
        names = ('handoffId', 'preparationId', 'verificationId', 'publicationId', 'startOperationId')
        require(len({operation_id(value[name]) for name in names}) == len(names), 'INVALID_ARGUMENT')
        digest(value['expectedRingSha256']); digest(value['expectedCohortSha256'])
        operator = value['operator']
        require(isinstance(operator, str), 'INVALID_ARGUMENT')
        try:
            size = len(operator.encode('utf-8'))
        except UnicodeError:
            raise Failure('INVALID_ARGUMENT') from None
        require(operator.strip() and size <= 128
                and all(ord(char) >= 32 and not 127 <= ord(char) <= 159 for char in operator), 'INVALID_ARGUMENT')

    def load(self, identity):
        manager = self.manager
        parent = manager.state / 'handoffs'
        if not os.path.lexists(parent):
            return None
        manager.directory(parent, private=True)
        path = parent / (operation_id(identity) + '.json')
        try:
            raw = manager.read(path, 8192)
        except FileNotFoundError:
            return None
        value = decode(raw)
        fields(value, {'schema', 'purpose', 'request', 'requestTag', 'owner', 'source', 'generation',
                       'historySha256', 'nonce', 'issuedBoottimeNs', 'expiresBoottimeNs', 'issuedAt', 'expiresAt', 'receiptTag'})
        require(type(value['schema']) is int and value['schema'] == 1 and value['purpose'] == HANDOFF_PURPOSE
                and raw == encode(value) and stat.S_IMODE(path.lstat().st_mode) == 0o400, 'UNSAFE_JOURNAL')
        self.validate_request(value['request'])
        require(value['request']['handoffId'] == identity, 'UNSAFE_JOURNAL')
        for name in ('requestTag', 'historySha256', 'nonce', 'receiptTag'):
            digest(value[name])
        secret = self.secret()
        require(hmac.compare_digest(value['requestTag'], hmac.new(secret, encode(value['request']), hashlib.sha256).hexdigest())
                and hmac.compare_digest(value['receiptTag'], hmac.new(secret, HANDOFF_RECEIPT
                    + encode({key: item for key, item in value.items() if key != 'receiptTag'}), hashlib.sha256).hexdigest()),
                'UNSAFE_JOURNAL')
        source = value['source']; fields(source, {'keySha256', 'ringSha256'})
        digest(source['keySha256'])
        if source['ringSha256'] is not None:
            digest(source['ringSha256'])
        try:
            validate_generation_metadata(value['generation'])
        except Refused:
            raise Failure('UNSAFE_JOURNAL') from None
        owner = value['owner']
        fields(owner, {'pid', 'uid', 'startTicks', 'bootId', 'invocationId', 'lockDevice', 'lockInode'})
        require(all(type(owner[name]) is int and owner[name] >= 0 for name in ('pid', 'uid', 'lockDevice', 'lockInode'))
                and owner['pid'] > 0 and owner['lockInode'] > 0 and isinstance(owner['startTicks'], str)
                and owner['startTicks'].isdigit() and isinstance(owner['invocationId'], str)
                and re.fullmatch(r'[0-9a-f]{32}', owner['invocationId']) is not None, 'UNSAFE_JOURNAL')
        operation_id(owner['bootId'])
        require(all(type(value[name]) is int and value[name] >= 0 for name in
                    ('issuedBoottimeNs', 'expiresBoottimeNs', 'issuedAt', 'expiresAt'))
                and value['expiresBoottimeNs'] - value['issuedBoottimeNs'] == 900_000_000_000
                and value['expiresAt'] - value['issuedAt'] == 900
                and value['generation']['ringSha256'] == value['request']['expectedRingSha256'], 'UNSAFE_JOURNAL')
        return value

    def metadata(self, value):
        request = value['request']
        revocation = self.revocation(value)
        state = 'GRANT_RECORDED' if revocation is None else ('GRANT_REVOKED' if
            all(item['state'] == 'NOT_ADMITTED' for item in self.unused_admissions(value)) else 'GRANT_REVOKING')
        return dict(schema=1, state=state, scope='ORIGINAL_AUTHORIZATION_ONLY',
                    handoffId=request['handoffId'], operator=request['operator'], preparationId=request['preparationId'],
                    verificationId=request['verificationId'], publicationId=request['publicationId'],
                    startOperationId=request['startOperationId'], ringSha256=request['expectedRingSha256'],
                    cohortSha256=request['expectedCohortSha256'], historySha256=value['historySha256'],
                    issuedAt=value['issuedAt'], expiresAt=value['expiresAt'], mutationWindowOpen=revocation is None and self.window_open(value),
                    startupAuthorized=False)

    def revocation(self, value):
        try:
            revoked = handoff_revocations(self.manager)
        except Refused:
            raise Failure('UNSAFE_JOURNAL') from None
        result = revoked.get(value['request']['handoffId'])
        require(result is None or result[1] == value, 'UNSAFE_JOURNAL')
        return result

    def unused_admissions(self, value):
        manager = self.manager; targets = {self.operation_request(value)['operationId']: self.operation_request(value),
            self.operation_request(value, start=True)['operationId']: self.operation_request(value, start=True)}
        for identity in targets:
            for directory in ('operations', 'startups', 'handoffs'):
                require(not os.path.lexists(manager.state/directory/(identity+'.json')), 'UNRESOLVED_OPERATION')
        matches = []
        for item in manager.sender_admissions.records():
            target = item['target']
            if target['operationId'] not in targets: continue
            native = targets[target['operationId']]
            require(target == dict(directory='operations', operationId=native['operationId'], action=native['action'],
                requestTag=manager.sender_admissions.tag(native), continuation=False)
                and item['state'] in ('RESERVED', 'NOT_ADMITTED'), 'UNRESOLVED_OPERATION')
            matches.append(item)
        return matches

    def revocation_read(self, value):
        result = self.revocation(value)
        require(result is not None and all(item['state'] == 'NOT_ADMITTED' for item in self.unused_admissions(value)),
            'UNRESOLVED_OPERATION')
        return handoff_revocation_view(result)

    def revoke(self, token, pid, uid, daemon, recovery):
        manager = self.manager
        if uid == daemon: manager.gwt_sender_owner(pid, uid, daemon)
        elif recovery is not None and uid == recovery: manager.recovery_sender_owner(pid, uid)
        else: require(uid == 0, 'FORBIDDEN')
        # Same lock order as native intake. Revocation cannot race a reserved sender-command.
        with manager.sender_admissions.locked(), manager.lock(manager.state/'admission.lock', True):
            manager.maintenance(); value = self.authenticate(token)
            matches = self.unused_admissions(value)
            if self.revocation(value) is None:
                with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                    # Absence alone is not a no-dispatch proof for historical grants. The
                    # exact original live Core/writer/source must still own the prepared round.
                    self.owner(value['request'], 0, 0, daemon, expected=value)
                    receipt = dict(schema=1, purpose=HANDOFF_REVOCATION_PURPOSE, handoffId=value['request']['handoffId'],
                        grantSha256=hashlib.sha256(encode(value)).hexdigest(),
                        namespaceSha256=manager.gwt_namespace()['namespaceSha256'], revokedAt=int(time.time()), revokedByUid=uid)
                    receipt['receiptTag'] = hmac.new(self.secret(), HANDOFF_REVOCATION_CONTEXT + encode(receipt), hashlib.sha256).hexdigest()
                    parent = manager.state/'handoff-revocations'
                    parent.mkdir(mode=0o700, exist_ok=True); manager.directory(parent, private=True); manager.sync(manager.state)
                    # The permanent fence is durable before sealing any old reservation.
                    manager.atomic(parent/(value['request']['handoffId']+'.json'), encode(receipt), mode=0o400, no_replace=True)
            for item in matches:
                if item['state'] == 'RESERVED': manager.sender_admissions.write(dict(item, state='NOT_ADMITTED'))
            return self.revocation_read(value)

    def window_open(self, value):
        return value['owner']['bootId'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip() \
            and value['issuedBoottimeNs'] <= self.clock() <= value['expiresBoottimeNs']

    def token(self, value):
        signature = hmac.new(self.secret(), HANDOFF_TOKEN + encode(value), hashlib.sha256).hexdigest()
        return 'KURA-HANDOFF-1.' + value['request']['handoffId'] + '.' + signature

    def authenticate(self, token):
        require(isinstance(token, str) and len(token) <= 128, 'FORBIDDEN')
        parts = token.split('.')
        require(len(parts) == 3 and parts[0] == 'KURA-HANDOFF-1', 'FORBIDDEN')
        identity = operation_id(parts[1]); digest(parts[2])
        value = self.load(identity)
        require(value is not None and hmac.compare_digest(token, self.token(value)), 'FORBIDDEN')
        return value

    def owner(self, request, pid, uid, daemon, *, expected=None):
        require(uid == 0 or uid == daemon, 'FORBIDDEN')
        raw, history, prepared, source, cohort, _ = self.generations.prepared(request)
        require(cohort['cohortSha256'] == request['expectedCohortSha256'], 'COHORT_CHANGED')
        unit, writer = self.generations.active_core(source, cohort)
        require(uid == 0 or pid == writer['pid'] and uid == writer['uid'] == daemon, 'FORBIDDEN')
        current = {name: writer[name] for name in ('pid', 'uid', 'startTicks', 'bootId', 'lockDevice', 'lockInode')}
        current['invocationId'] = unit['InvocationID']
        if expected is not None:
            require(current == expected['owner'] and source == expected['source']
                    and history['generation'] == expected['generation']
                    and prepared['historySha256'] == expected['historySha256'], 'OWNER_CHANGED')
        return current, source, history, prepared

    def create(self, request, pid, uid, daemon):
        require(uid == 0 or uid == daemon, 'FORBIDDEN')
        self.validate_request(request)
        require(sys_platform_linux() and hasattr(time, 'CLOCK_BOOTTIME'), 'UNSUPPORTED')
        manager = self.manager
        with manager.sender_admissions.locked(), manager.lock(manager.state / 'admission.lock', True):
            manager.maintenance(); manager.settled()
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                existing = self.load(request['handoffId'])
                if existing is not None:
                    require(existing['request'] == request, 'CONFLICT')
                    self.owner(request, pid, uid, daemon, expected=existing)
                    return dict(self.metadata(existing), token=self.token(existing))
                parent = manager.state / 'handoffs'
                if os.path.lexists(parent):
                    manager.directory(parent, private=True)
                    files = list(parent.iterdir()); require(len(files) < 32, 'CAPACITY')
                    for path in files:
                        require(path.name.endswith('.json'), 'UNSAFE_JOURNAL')
                        prior = self.load(operation_id(path.name[:-5]))
                        require(prior is not None, 'UNSAFE_JOURNAL')
                        old_ids = {prior['request'][key] for key in
                            ('handoffId', 'preparationId', 'verificationId', 'publicationId', 'startOperationId')}
                        require(not old_ids & {request[key] for key in ('handoffId', 'publicationId', 'startOperationId')}, 'HANDOFF_EXISTS')
                        if prior['request']['preparationId'] == request['preparationId']:
                            require(self.revocation(prior) is not None, 'HANDOFF_EXISTS')
                            self.revocation_read(prior)
                            require(all(prior['request'][key] == request[key] for key in
                                ('verificationId', 'operator', 'expectedRingSha256', 'expectedCohortSha256')), 'CONFLICT')
                            self.owner(request, pid, uid, daemon, expected=prior)
                for name in ('publicationId', 'startOperationId'):
                    require(manager.record(request[name]) is None
                            and not os.path.lexists(manager.state / 'startups' / (request[name] + '.json')), 'CONFLICT')
                owner, source, history, prepared = self.owner(request, pid, uid, daemon)
                issued = self.clock(); wall = int(time.time())
                value = dict(schema=1, purpose=HANDOFF_PURPOSE, request=dict(request),
                             requestTag=hmac.new(self.secret(), encode(request), hashlib.sha256).hexdigest(),
                             owner=owner, source=source, generation=history['generation'], historySha256=prepared['historySha256'],
                             nonce=secrets.token_hex(32), issuedBoottimeNs=issued, expiresBoottimeNs=issued + 900_000_000_000,
                             issuedAt=wall, expiresAt=wall + 900)
                value['receiptTag'] = hmac.new(self.secret(), HANDOFF_RECEIPT + encode(value), hashlib.sha256).hexdigest()
                parent.mkdir(mode=0o700, exist_ok=True); manager.directory(parent, private=True); manager.sync(manager.state)
                manager.atomic(parent / (request['handoffId'] + '.json'), encode(value), mode=0o400, no_replace=True)
                return dict(self.metadata(value), token=self.token(value))

    def read(self, request, pid, uid, daemon, *, token=False):
        fields(request, {'schema', 'action', 'handoffId'})
        require(type(request['schema']) is int and request['schema'] == 1
                and request['action'] == ('generation-handoff-token-read' if token else 'generation-handoff-read'), 'INVALID_ARGUMENT')
        require(uid == 0 or uid == daemon, 'FORBIDDEN')
        identity = operation_id(request['handoffId']); manager = self.manager
        with manager.lock(manager.state / 'admission.lock', False):
            manager.maintenance()
            with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'), False):
                value = self.load(identity)
                if value is None:
                    return dict(schema=1, handoffId=identity, state='NOT_RECORDED', scope='ORIGINAL_AUTHORIZATION_ONLY')
                if token:
                    self.owner(value['request'], pid, uid, daemon, expected=value)
                result = self.metadata(value)
                if token:
                    result['token'] = self.token(value)
                return result

    @staticmethod
    def operation_request(value, *, start=False):
        request = value['request']
        result = dict(schema=1, action='generation-core-start' if start else 'generation-publish',
                      operationId=request['startOperationId' if start else 'publicationId'],
                      expectedRingSha256=request['expectedRingSha256'], expectedCohortSha256=request['expectedCohortSha256'])
        if start:
            result['publicationId'] = request['publicationId']
        else:
            result.update(preparationId=request['preparationId'], verificationId=request['verificationId'])
        return result

    def original(self, value, *, start=False):
        identity = value['request']['startOperationId' if start else 'publicationId']
        action = 'generation-core-start' if start else 'generation-publish'
        manager = self.manager
        with manager.lock(manager.state / 'admission.lock', False):
            manager.maintenance()
            record = manager.record(identity)
            require(record is None or record['action'] == action, 'CONFLICT')
            if record is not None:
                require(hmac.compare_digest(record['requestTag'], hmac.new(self.secret(),
                    encode(self.operation_request(value, start=start)), hashlib.sha256).hexdigest()), 'CONFLICT')
            return record

    def publication_matches(self, value, publication):
        request = value['request']
        require(publication['operationId'] == request['publicationId']
                and publication['preparationId'] == request['preparationId']
                and publication['verificationId'] == request['verificationId']
                and publication['historySha256'] == value['historySha256']
                and publication['source'] == value['source'] and publication['generation'] == value['generation']
                and publication['cohortSha256'] == request['expectedCohortSha256']
                and publication['stoppedWriter'] == {key: item for key, item in value['owner'].items() if key != 'uid'}, 'CONFLICT')

    def command(self, request, pid, uid, daemon, recovery):
        command = request.get('command')
        require(command in ('info', 'publication-read', 'publish', 'continue', 'start-read', 'start',
            'revoke', 'revocation-read'), 'INVALID_ARGUMENT')
        fields(request, {'schema', 'action', 'token', 'command'} | ({'expectedRecoveryReceiptSha256'} if command == 'continue' else set()))
        require(type(request['schema']) is int and request['schema'] == 1
                and request['action'] == 'generation-handoff-command', 'INVALID_ARGUMENT')
        if command == 'continue':
            digest(request['expectedRecoveryReceiptSha256'])
        require(uid == 0 or uid == daemon or recovery is not None and uid == recovery, 'FORBIDDEN')
        if command in ('publish', 'continue', 'start'):
            require(uid == 0 or recovery is not None and uid == recovery, 'FORBIDDEN')
        manager = self.manager
        if command == 'revoke':
            return self.revoke(request['token'], pid, uid, daemon, recovery)
        with manager.lock(manager.state / 'admission.lock', False):
            manager.maintenance()
            value = self.authenticate(request['token'])
            if command == 'revocation-read': return self.revocation_read(value)
            if command == 'info': return self.metadata(value)
            if command in ('publish', 'continue', 'start'):
                require(self.revocation(value) is None, 'HANDOFF_REVOKED')
        original = value['request']
        start = command in ('start', 'start-read')
        record = self.original(value, start=start)
        if command == 'publication-read' and record is not None:
            return self.generations.publication_read(dict(schema=1, action='generation-publication-read',
                                                          operationId=original['publicationId']))
        if command in ('publication-read', 'start-read') or record is not None and (
                command in ('publish', 'start') or record['state'] == 'SUCCEEDED'):
            return manager.public_record(record) if record is not None else dict(schema=1,
                operationId=original['startOperationId' if start else 'publicationId'], state='NOT_RECORDED',
                scope='ORIGINAL_OPERATION_ONLY')
        if command == 'continue':
            if record is None:
                return dict(schema=1, operationId=original['publicationId'], state='NOT_RECORDED', scope='ORIGINAL_OPERATION_ONLY')
            receipt = self.generations.recovery_receipt(original['publicationId'])
            if receipt is not None:
                self.publication_matches(value, receipt[1]['publication'])
            return self.generations.recover_publication(dict(schema=1, action='generation-publication-recover',
                operationId=original['publicationId'], expectedRecoveryReceiptSha256=request['expectedRecoveryReceiptSha256']))
        require(self.window_open(value), 'HANDOFF_EXPIRED')
        # The recorded authority is synced before a new key operation can be
        # admitted. Reading a grant never concludes a remote operation succeeded.
        manager.sync(manager.state / 'handoffs')
        if command == 'publish':
            return self.generations.request(self.operation_request(value), expected_owner=value['owner'])
        self.publication_matches(value, self.generations.current())
        return self.generations.request(self.operation_request(value, start=True), start=True, expected_owner=value['owner'])


def sys_platform_linux():
    # Kept local to this attested module; no environment-selected clock fallback.
    import sys
    return sys.platform == 'linux'
