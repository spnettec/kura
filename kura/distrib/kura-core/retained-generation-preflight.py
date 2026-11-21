# SPDX-License-Identifier: EPL-2.0
"""Package-only admission before unpack into a Core removed under its original fence.

Embedded beside the incoming key policy. The installed key reader and ordinary
startup entry points do not acquire an admission path for removed installations.
"""


def prepare_retained_generation(*, unpacked_layout=False):
    removal = {'__name__': 'packaged_removal'}
    exec(compile(_KURA_REMOVAL_HOME_SOURCE, '<packaged-removal>', 'exec'), removal)

    class RemovedStore(Store):
        verified = False

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
            saved = removal['retained_generation'](retained, fence['id'])
            require(saved and saved['manifestSha256'] == _KURA_INCOMING_KEY_MANIFEST_SHA256,
                    'Incoming release differs from the retained generation cohort')

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
            archive = retained / 'encryption'
            removal['protected'](archive, True)
            require(self.key(archive / CREDENTIAL) == self.key(self.path(KEY_PATH)) and
                    self.read(archive / 'provisioned.json', private=True) == self.read(self.path(RECEIPT_PATH), private=True),
                    'Retained encryption archive differs from the original credentials')
            if not unpacked_layout:
                require(not any(os.path.lexists(self.path(p)) for p in
                                ('/opt/eclipse/kura', '/usr/lib/systemd/system/kura.service', '/lib/systemd/system/kura.service')),
                        'Retained pre-unpack requires the removed installation')
            require(removal['retained_generation'](retained, fence['id']) == saved and lifecycle.fence() == fence,
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
