# SPDX-License-Identifier: EPL-2.0
"""Package-only admission before unpack into a Core removed under its original fence.

Embedded beside the incoming key policy. The installed key reader and ordinary
startup entry points do not acquire an admission path for removed installations.
"""


def check_removed_generation_release(api, lifecycle, saved, publication, secret, *, purged):
    removed_manifest = saved['manifestSha256']
    if removed_manifest == _KURA_INCOMING_KEY_MANIFEST_SHA256:
        return
    predecessors = _KURA_INCOMING_KEY_PREDECESSORS
    origin_manifest = saved.get('publicationManifestSha256', removed_manifest)
    require(purged and removed_manifest in predecessors and origin_manifest in predecessors,
            'Incoming release differs from the retained generation cohort')

    operations = lifecycle.state / 'operations'
    lifecycle.directory(operations, private=True)
    records = [api.validate_record(api.decode(lifecycle.read(path)), path.stem) for path in operations.iterdir()]
    starts = [record for record in records if record['action'] == 'generation-core-start'
              and record['state'] == 'SUCCEEDED' and record['response']['publicationId'] == publication['operationId']]
    require(len(starts) == 1, 'Cohort replacement requires the original completed generation startup')
    api.archive_entry(lifecycle, dict(directory='operations', operationId=starts[0]['operationId']), secret)


def prepare_retained_generation(*, unpacked_layout=False):
    removal = {'__name__': 'packaged_removal'}
    exec(compile(_KURA_REMOVAL_HOME_SOURCE, '<packaged-removal>', 'exec'), removal)

    class RemovedStore(Store):
        verified = False

        def check_publication_layout(self, has_dropin, published):
            if has_dropin == published:
                return
            require(published and not has_dropin, 'Original generation publication required')
            api = paired_lifecycle()
            lifecycle = api.Lifecycle(self.root, self.owner)
            fence = lifecycle.fence()
            require(fence and fence['firstAction'] == 'remove', 'Original purge fence required')
            removal['purged_generation'](fence['id'])

        @contextlib.contextmanager
        def locked(self):
            # Flock the original credential lock inode. No creation or writable
            # descriptor is needed to inspect a removed installation.
            path = self.path('/etc/kura/credentials/.provision.lock')
            removal['protected'](path, False)
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                original = os.fstat(lock.fileno())
                require(stat.S_ISREG(original.st_mode) and original.st_uid == 0 and original.st_nlink == 1
                        and not original.st_mode & 0o7077 and stat.S_IMODE(path.parent.lstat().st_mode) == 0o700
                        and os.path.samestat(original, path.lstat()), 'Unsafe original credential lock')
                yield
                require(os.path.samestat(original, path.lstat()), 'Original credential lock changed')

        def check_published_maintenance(self, api, lifecycle, metadata, receipt):
            retained = self.path('/var/lib/kura-retained')
            fence = lifecycle.fence()
            require(fence and fence['firstAction'] == 'remove', 'Original removal fence required')
            lifecycle.check_extended_journal()
            purged = not os.path.lexists(retained)
            saved = (removal['purged_generation'](fence['id']) if purged else
                     removal['retained_generation'](retained, fence['id']))
            require(saved, 'Original removed credential cohort is absent')

            publication = api.validate_publication(api.decode(lifecycle.read(lifecycle.state / 'generation-current.json', 8192)))
            slot = lifecycle.state / 'generations' / publication['preparationId']
            require(publication['generation'] == metadata and
                    api.decode(lifecycle.read(slot / 'history.json', 8192))['provisioned'] == receipt and
                    api.decode(lifecycle.read(slot / 'publication-recovery.json', 16384))['publication'] == publication,
                    'Original generation history differs from the retained credentials')
            secret = lifecycle.read(lifecycle.state / 'journal.key', 32)
            require(len(secret) == 32, 'Invalid original journal key')
            for key in ('operationId', 'verificationId'):
                api.archive_entry(lifecycle, dict(directory='operations', operationId=publication[key]), secret)
            check_removed_generation_release(api, lifecycle, saved, publication, secret, purged=purged)
            if not purged:
                archive = retained / 'encryption'
                removal['protected'](archive, True)
                require(self.key(archive / CREDENTIAL) == self.key(self.path(KEY_PATH)) and
                        self.read(archive / 'provisioned.json', private=True) == self.read(self.path(RECEIPT_PATH), private=True),
                        'Retained encryption archive differs from the original credentials')
            else:
                require(not os.path.lexists(self.path('/opt/eclipse/.kura-preserve')) and
                        not list(retained.parent.glob('.kura-retained.purging-*')),
                        'Original purge still has application recovery copies')
                dropin = self.path(GENERATION_DROPIN)
                require(not os.path.lexists(dropin) or unpacked_layout and
                        stat.S_IMODE(dropin.lstat().st_mode) == 0o400 and self.read(dropin, private=True) ==
                        removal['generation_input'](removal['PURGED_GENERATIONS'] / fence['id'] / 'dropin'),
                        'Unexpected Main drop-in after original purge')
            if not unpacked_layout:
                require(not any(os.path.lexists(self.path(p)) for p in
                                ('/opt/eclipse/kura', '/usr/lib/systemd/system/kura.service', '/lib/systemd/system/kura.service')),
                        'Retained pre-unpack requires the removed installation')
            observed = (removal['purged_generation'](fence['id']) if purged else
                        removal['retained_generation'](retained, fence['id']))
            require(observed == saved and lifecycle.fence() == fence,
                    'Original retained generation changed during admission')
            self.verified = True

    try:
        store = RemovedStore()
        require(os.geteuid() == 0 and os.path.lexists(store.path('/var/lib/kura-key-service/generation-current.json'))
                and os.path.lexists(store.path(RING_PATH)), 'Original published credentials required')
        store.prepare('package')
        require(store.verified, 'Original generation publication required')
        return 0
    except (RuntimeError, OSError, ValueError, KeyError, TypeError):
        print('Kura retained generation preflight refused the original removal or incoming cohort.', file=sys.stderr)
        return 1
