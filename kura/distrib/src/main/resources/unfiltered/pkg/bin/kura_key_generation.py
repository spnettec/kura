#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fixed-unit generation publication. Original uncertain dispatches are never retried."""
import hashlib
import hmac
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess

from kura_key_service import (Failure, require, fields, digest, operation_id, encode, decode,
                              KEY_PATH, RECEIPT_PATH, RING_PATH, GENERATION_RECEIPT_PATH,
                              GENERATION_FORMAT, key_generations)
from kura_key_service_lifecycle import Lifecycle, Refused, validate_publication

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

    def request(self, request, *, start=False):
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
                    return self.start(request, identity, tag)
                raw, history, prepared, source, cohort, template = self.prepared(request)
                unit, writer = self.active_core(source, cohort)
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

    def start(self, request, identity, tag):
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
        with manager.exclusive_writers():
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
