# SPDX-License-Identifier: EPL-2.0
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_reboot_setup as setup  # noqa: E402
from kura_clock_journal import Refused, create, decode, digest, encode, read  # noqa: E402
from kura_reboot_journal import RebootJournal  # noqa: E402

BOOT = '6b9eba0a-149f-4d03-8653-5e05843a112c'
OPERATION = 'c31b1b11-cb66-4db8-94d6-9d9e2f1b7ee4'
CALLER = SimpleNamespace(pw_uid=997, pw_gid=991)


class PackageLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.state = self.root / 'root'
        self.sender = self.root / 'sender'
        self.authority = self.root / 'authority'
        self.installation = self.root / 'installation'
        self.vendor = self.root / 'vendor'
        self.vendor.mkdir()
        self.package = self.root / 'package'
        copies = self.package / setup.COHORT.parent
        copies.mkdir(parents=True)
        self.manifest = {'files': {}}
        for name in (setup.ACTOR, setup.SOCKET):
            unit = copies / name
            unit.write_text(name + '\n')
            self.manifest['files'][(setup.COHORT.parent / name).as_posix()] = setup.file_hash(unit.read_bytes())
        self.active = False
        self.calls = []
        self.enterContext(patch.multiple(setup, AUTHORITY=self.authority, INSTALLATION=self.installation,
            STATE=self.state, SENDER=self.sender, VENDOR=self.vendor, HOME=self.package,
            read=lambda path, owner, mode=0o600: read(path, os.geteuid(), mode),
            account_binding=lambda path: decode(path.read_bytes()), sender_binding=self.binding,
            publish_path=self.rename, activity=self.activity, verify_unit_sources=lambda units: None,
            unit_directory_present=lambda directory: directory.is_dir(), public_file=Path.read_bytes, run=self.systemctl))
        self.enterContext(patch.object(setup.pwd, 'getpwnam', return_value=CALLER))
        self.enterContext(patch.object(setup.os, 'chown'))
        self.enterContext(patch.object(setup.Policy, 'packaged', return_value=self.manifest))
        self.enterContext(patch.object(setup.Policy, 'check', side_effect=self.policy))

    def binding(self, binding):
        self.assertEqual(encode(binding), (self.sender / 'binding.json').read_bytes())

    def policy(self, *, actor, include_main):
        self.assertTrue(actor)
        self.assertFalse(include_main)
        for unit in (setup.ACTOR, setup.SOCKET):
            name = (setup.COHORT.parent / unit).as_posix()
            self.assertEqual(setup.file_hash((self.vendor / unit).read_bytes()), self.manifest['files'][name])
        return digest(self.manifest), decode(self.authority.read_bytes())

    @staticmethod
    def rename(source, target, replace):
        if not replace and target.exists():
            raise FileExistsError(target)
        source.rename(target)

    def activity(self, unit):
        return {'ActiveState': 'active' if unit == setup.SOCKET and self.active else 'inactive',
                'LoadState': 'loaded' if (self.vendor / unit).exists() else 'not-found'}

    def systemctl(self, *args):
        self.calls.append(args)
        if args[0] == 'enable':
            self.active = True
        if args[0] == 'stop':
            self.active = False
        return 'enabled\n' if args[0] == 'is-enabled' else ''

    def test_configure_bootstraps_one_identity_and_activates_paired_socket(self):
        setup.resume()
        first = self.installation.read_bytes()
        binding = decode(first)
        self.assertEqual(first, self.authority.read_bytes())
        self.binding(binding)
        self.assertFalse((self.state / setup.FENCE).exists())
        self.assertTrue(self.active)
        setup.resume()
        self.assertEqual(first, self.installation.read_bytes())
        self.assertEqual(1, self.calls.count(('enable', '--now', setup.SOCKET)))

    def test_bootstrap_interruption_resumes_before_exposing_authority(self):
        publish = setup.durable_publish

        def lose_before_authority(path, value, mode):
            if path == self.authority:
                raise OSError('simulated stop before authority publication')
            publish(path, value, mode)

        with patch.object(setup, 'durable_publish', side_effect=lose_before_authority):
            with self.assertRaisesRegex(OSError, 'before authority'):
                setup.resume()
        reserved = self.installation.read_bytes()
        root = (self.state / 'namespace.json').read_bytes()
        self.assertFalse(self.authority.exists())
        self.assertFalse(self.active)
        setup.resume()
        self.assertEqual(reserved, self.authority.read_bytes())
        self.assertEqual(root, (self.state / 'namespace.json').read_bytes())

    def test_existing_authority_refuses_missing_state_and_missing_sender(self):
        setup.resume()
        binding = self.authority.read_bytes()
        saved = self.root / 'preserved'
        self.state.rename(saved)
        with self.assertRaises(FileNotFoundError):
            setup.resume()
        self.assertFalse(self.state.exists())
        saved.rename(self.state)
        self.sender.rename(saved)
        with self.assertRaises(FileNotFoundError):
            setup.resume()
        self.assertFalse(self.sender.exists())
        self.assertEqual(binding, self.authority.read_bytes())

    def test_reinstall_keeps_ambiguous_request_and_original_sender_pending(self):
        setup.resume()
        binding = decode(self.authority.read_bytes())
        journal = RebootJournal(self.state, binding['namespace'], digest(self.manifest), lambda: BOOT)
        request = dict(schema=1, action='reboot', namespace=binding['namespace'], requestId=OPERATION,
                       bootId=BOOT, cohortSha256=digest(self.manifest))
        result = journal.submit(request, lambda: ('UNKNOWN', 'DISPATCH_UNCONFIRMED'))
        pending = self.sender / 'pending.json'
        create(pending, request)
        original = {p: p.read_bytes() for p in (
            self.installation, self.authority, pending, self.state / 'operations' / OPERATION / 'result.json')}
        setup.quiesce()
        setup.remove()
        self.assertFalse(any(self.vendor.iterdir()))
        self.assertTrue((self.state / setup.FENCE).is_file())
        setup.resume()
        self.assertEqual(original, {p: p.read_bytes() for p in original})
        self.assertEqual(result, journal.status(binding['namespace'], OPERATION, digest(request)))
        self.assertFalse(journal.context()['acceptingWrites'])

    def test_retry_after_socket_activation_keeps_existing_fence_until_paired(self):
        real = self.systemctl

        def crash_after_enable(*args):
            value = real(*args)
            if args[0] == 'enable':
                raise OSError('lost enable acknowledgement')
            return value

        with patch.object(setup, 'run', side_effect=crash_after_enable):
            with self.assertRaisesRegex(OSError, 'lost enable'):
                setup.resume()
        before = self.authority.read_bytes()
        self.assertTrue(self.active)
        self.assertTrue((self.state / setup.FENCE).is_file())
        setup.resume()
        self.assertFalse((self.state / setup.FENCE).exists())
        self.assertEqual(before, self.authority.read_bytes())
        self.assertEqual(1, self.calls.count(('enable', '--now', setup.SOCKET)))

    def test_tampered_installed_unit_is_never_replaced_from_unrelated_bytes(self):
        setup.resume()
        setup.quiesce()
        unit = self.vendor / setup.SOCKET
        unit.write_text('unpaired')
        with self.assertRaisesRegex(Refused, '^UNPAIRED_UNIT$'):
            setup.resume()
        self.assertEqual('unpaired', unit.read_text())
        self.assertTrue((self.state / setup.FENCE).is_file())
        self.assertFalse(self.active)

    def test_residual_state_without_original_installation_is_refused(self):
        self.state.mkdir(mode=0o700)
        with self.assertRaisesRegex(Refused, '^UNPAIRED_INSTALLATION$'):
            setup.resume()
        self.assertFalse(self.authority.exists())
        self.assertFalse(self.installation.exists())

    def test_quiesce_before_first_configuration_is_read_only(self):
        setup.quiesce()
        self.assertFalse(self.authority.exists())
        self.assertEqual([], self.calls)


if __name__ == '__main__':
    unittest.main()
