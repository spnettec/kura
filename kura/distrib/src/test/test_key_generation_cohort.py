#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Real built JARs in disposable package trees. Never install, boot or rotate Kura."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SOURCE = Path(__file__).resolve().parents[1] / "main/resources"
sys.path.insert(0, str(SOURCE / "unfiltered/pkg/bin"))
import kura_key_cohort as cohort
import kura_key_service_lifecycle as lifecycle
import kura_key_service as service

CONFIG = None


class GenerationPackageTest(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        temporary = tempfile.TemporaryDirectory(prefix="kura-generation-package-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "opt/eclipse/kura"
        self.home.mkdir(parents=True, mode=0o750)
        main_template = SOURCE / "filtered/pkg/install/kura.service"
        unit_files = cohort.managed_unit(main_template.read_bytes().replace(b"INSTALL_DIR", b"/opt/eclipse"))
        for name in lifecycle.ASSETS | cohort.FIXED_FILES | unit_files:
            if name.startswith(cohort.TEMPLATES) or name.startswith("libexec/"):
                continue
            self.copy(SOURCE / "unfiltered/pkg" / name, self.home / name)
        for name in (*lifecycle.UNITS, "kura.service", "manage_kura_users.sh"):
            base = "filtered" if name == "kura.service" else "unfiltered"
            self.copy(SOURCE / base / "pkg/install" / name, self.home / "install" / name)
        for name in cohort.LAUNCHERS:
            raw = (SOURCE / "filtered/pkg/bin" / name).read_bytes()
            raw = raw.replace(b"@kura.mem.size@", b"1024m").replace(b"${kura.mem.size}", b"1024m")
            target = self.home / "bin" / name
            target.write_bytes(raw); target.chmod(0o640)
        readers = (cohort.ROLES[role][0] for role in ("crypto", "configuration", "snapshot"))
        # The package builder also audits its public crypto API and its consumers.
        for bsn in ("org.eclipse.kura.api", *readers):
            matches = list((CONFIG / "kura" / bsn / "target").glob(bsn + "-*.jar"))
            self.assertEqual(1, len(matches), "Build the canonical reader modules before running this suite")
            self.copy(matches[0], self.home / "plugins/4s" / matches[0].name)
        spec = importlib.util.spec_from_file_location("prepare_key_service", SOURCE.parents[2] / "kura-core/prepare-key-service.py")
        self.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.builder)
        self.manifest = self.builder.prepare(self.home, CONFIG / "kura/distrib/kura-key-crypto/target",
                                             CONFIG / "kura/tools/kura-offline-recovery/target")
        for name in (*lifecycle.UNITS, "kura.service"):
            self.copy(self.home / "install" / name, self.root / "lib/systemd/system" / name)
        self.generation = self.manifest["generation"]
        self.policy = lifecycle.Lifecycle(self.root, os.geteuid())

    @staticmethod
    def copy(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o640)

    def save_manifest(self):
        path = self.home / "libexec/key-backup/manifest.json"
        path.write_text(json.dumps(self.manifest, sort_keys=True))

    def rewrite_jar(self, relative, change_manifest=None, remove=None):
        path = self.home / relative
        raw = io.BytesIO()
        with zipfile.ZipFile(path) as original, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as target:
            for info in original.infolist():
                if info.filename == remove:
                    continue
                value = original.read(info)
                if info.filename == "META-INF/MANIFEST.MF" and change_manifest:
                    value = change_manifest(value)
                target.writestr(info, value)
        path.write_bytes(raw.getvalue())
        self.generation["files"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.save_manifest()

    def test_real_reader_set_and_private_classpath_are_paired_with_actual_core_units(self):
        self.assertEqual(2, self.policy.assets()["protocol"])
        binding = self.policy.generation_assets()
        self.assertEqual(64, len(binding["cohortSha256"]))
        self.assertEqual(set(cohort.LAUNCHERS), set(binding["launcherSha256s"]))
        self.assertFalse((self.root / "etc/kura/credentials").exists())
        self.assertFalse((self.root / "var/lib/kura-key-service").exists())
        before = {p: (p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
                  for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(binding, self.policy.generation_assets())
        self.assertEqual(before, {p: (p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in before})

    def test_actual_postinst_install_directory_cleanup_keeps_generation_cohort(self):
        binding = self.policy.generation_assets()
        shutil.rmtree(self.home / 'install')
        self.assertEqual(2, self.policy.assets()['protocol'])
        self.assertEqual(binding, self.policy.generation_assets())

    def test_broken_core_reader_keeps_cold_base_available_but_refuses_real_generation_boot_admission(self):
        directory = self.root / 'etc/kura/credentials'
        directory.mkdir(parents=True, mode=0o700)
        state = self.root / 'var/lib/kura-key-service'
        (state / 'operations').mkdir(parents=True, mode=0o700)
        active = bytes(range(32))
        raw = service.encode_key_generations([service.CORE_DEFAULT, active], 1, 0)
        _, metadata = service.key_generations(raw)
        values = {'kura_encryption_key': active, 'kura_encryption_keyring': raw,
                  'provisioned.json': service.encode(dict(schema=1, keySha256=metadata['activeKeySha256'], origin='canonical', legacyKey=False, unitDigests=[])),
                  'key-generations.json': service.encode(dict(schema=1, purpose=service.GENERATION_FORMAT, **metadata)),
                  '.provision.lock': b''}
        for name, value in values.items():
            path = directory / name
            path.write_bytes(value); path.chmod(0o600)
        (state / 'admission.lock').write_bytes(b''); (state / 'admission.lock').chmod(0o600)
        manager = service.Manager(self.root, os.geteuid())
        requests = [dict(schema=1, action='credential-start-admission', keySha256=metadata['activeKeySha256'], ringSha256=metadata['ringSha256']),
                    dict(schema=1, action='generation-start-admission', activeKeySha256=metadata['activeKeySha256'], ringSha256=metadata['ringSha256'])]
        for request in requests:
            self.assertIn(manager.handle(request)['state'], ('CREDENTIAL_READY', 'GENERATION_READY'))
        (self.home / self.generation['readers']['crypto']).unlink()
        self.assertEqual(2, self.policy.assets()['protocol'])
        for request in requests:
            with self.assertRaises(service.Failure) as error:
                manager.handle(request)
            self.assertEqual('COHORT_UNAVAILABLE', error.exception.reason)
        self.assertEqual(values, {name: (directory / name).read_bytes() for name in values})
        self.assertEqual([], list((state / 'operations').iterdir()))

    def test_missing_main_unit_or_generation_helper_does_not_disable_cold_base(self):
        for path in (self.root / 'lib/systemd/system/kura.service', self.home / 'bin/kura_key_cohort.py',
                     self.home / cohort.FRAMEWORK_STOP):
            raw = path.read_bytes()
            path.unlink()
            self.assertEqual(2, self.policy.assets()['protocol'])
            with self.assertRaises((lifecycle.Refused, OSError)):
                self.policy.generation_assets()
            path.write_bytes(raw); path.chmod(0o640)

    def test_original_protocol_one_assets_still_support_base_recovery_without_generation_claims(self):
        self.manifest = {key: value for key, value in self.manifest.items() if key != 'generation'}
        self.manifest.update(schema=1, protocol=1)
        self.save_manifest()
        self.assertEqual(1, self.policy.assets()['protocol'])
        with self.assertRaises(lifecycle.Refused):
            self.policy.generation_assets()

    def test_original_journal_profile_still_requires_its_complete_generation_reader_cohort(self):
        self.manifest['files'].pop('share/key-recovery/archive.js')
        (self.home/'share/key-recovery/archive.js').unlink();self.save_manifest()
        self.assertEqual(lifecycle.JOURNAL_V1_ASSETS,frozenset(self.policy.assets()['files']))
        self.assertEqual(1,self.policy.generation_assets()['schema'])
        role=self.manifest['generation']['readers']['crypto']
        (self.home/role).write_bytes(b'changed original reader')
        with self.assertRaises(lifecycle.Refused):self.policy.generation_assets()

    def test_declared_capability_without_the_actual_reader_class_is_refused(self):
        self.rewrite_jar(cohort.OFFLINE, remove="org/eclipse/kura/tools/recovery/RecoveryCrypto.class")
        with self.assertRaises(lifecycle.Refused):
            self.policy.generation_assets()

    def test_same_version_different_private_crypto_artifact_is_refused(self):
        path = next(name for name in self.generation["files"] if name.startswith("libexec/key-recovery/lib/org.eclipse.kura.core.crypto-"))
        self.rewrite_jar(path, lambda data: data.replace(b"Manifest-Version: 1.0", b"Manifest-Version: 1.0\r\nTest-Mismatch: true", 1))
        with self.assertRaises(lifecycle.Refused):
            self.policy.generation_assets()

    def test_duplicate_reader_bsn_under_another_name_is_refused(self):
        source = self.home / self.generation["readers"]["crypto"]
        self.copy(source, self.home / "siblings/duplicate/4s/renamed-reader.jar")
        with self.assertRaises(lifecycle.Refused):
            self.policy.generation_assets()

    def test_removed_capability_cannot_be_hidden_by_refreshing_outer_file_hashes(self):
        path = self.generation["readers"]["crypto"]
        self.rewrite_jar(path, lambda raw: raw.replace(b"kura.crypto.key.generations", b"test.crypto.old.generation"))
        with self.assertRaises(lifecycle.Refused):
            self.policy.generation_assets()

    def test_old_crypto_cannot_supply_managed_recovery_even_when_both_copies_match(self):
        runtime=self.generation['readers']['crypto']
        private=next(name for name in self.generation['files'] if name.startswith('libexec/key-recovery/lib/org.eclipse.kura.core.crypto-'))
        def old_manifest(raw):
            raw=raw.replace(b'\r\n',b'\n').replace(b'\n ',b'')
            self.assertEqual(1,raw.count(b'kura.crypto.key.generations.paired'))
            return raw.replace(b'kura.crypto.key.generations.paired',b'test.crypto.old.generations.paired')
        for name in (runtime,private):self.rewrite_jar(name,old_manifest)
        self.assertEqual((self.home/runtime).read_bytes(),(self.home/private).read_bytes())
        self.assertEqual(2,self.policy.assets()['protocol'])
        with self.assertRaises(lifecycle.Refused):self.policy.generation_assets()

    def test_offline_reader_requires_the_active_pair_interface_and_managed_loader(self):
        path=self.home/cohort.OFFLINE;original=path.read_bytes()
        for capability in (b'kura.crypto.key.generations.paired',b'kura.crypto.systemd.recovery'):
            path.write_bytes(original)
            def old_manifest(raw):
                raw=raw.replace(b'\r\n',b'\n').replace(b'\n ',b'')
                self.assertEqual(1,raw.count(capability))
                return raw.replace(capability,b'test.reader.old.capability')
            self.rewrite_jar(cohort.OFFLINE,old_manifest)
            self.assertEqual(2,self.policy.assets()['protocol'])
            with self.assertRaises(lifecycle.Refused):self.policy.generation_assets()

    def test_old_native_credential_reader_is_refused_after_outer_hash_refresh(self):
        path=self.home/'bin/kura_key_store.py'
        raw=path.read_bytes();self.assertEqual(1,raw.count(b'LOADED_CREDENTIAL_PROOF_PROTOCOL = 1'))
        raw=raw.replace(b'LOADED_CREDENTIAL_PROOF_PROTOCOL = 1',b'LOADED_CREDENTIAL_PROOF_PROTOCOL = 0')
        path.write_bytes(raw)
        self.manifest['files']['bin/kura_key_store.py']=hashlib.sha256(raw).hexdigest();self.save_manifest()
        self.assertEqual(2,self.policy.assets()['protocol'])
        with self.assertRaises(lifecycle.Refused):self.policy.generation_assets()

    def test_actual_installer_heap_adjustment_is_allowed_and_changes_exact_runtime_binding(self):
        before = self.policy.generation_assets()
        for name in cohort.LAUNCHERS:
            path = self.home / "bin" / name
            path.write_bytes(path.read_bytes().replace(b"-Xms1024m -Xmx1024m", b"-Xms256m -Xmx512m"))
        after = self.policy.generation_assets()
        self.assertNotEqual(before["cohortSha256"], after["cohortSha256"])
        self.assertEqual(before["manifestSha256"], after["manifestSha256"])

    def test_binding_uses_the_validated_launcher_bytes_instead_of_a_second_unchecked_read(self):
        path = self.home / "bin/start_kura_debug.sh"
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        original = self.policy.read
        changed = False
        def read_and_change(source, **options):
            nonlocal changed
            value = original(source, **options)
            if source.resolve() == path.resolve() and not changed:
                changed = True
                path.write_bytes(value + b"\nexit 0\n")
            return value
        with patch.object(self.policy, 'read', side_effect=read_and_change):
            binding = self.policy.generation_assets()
        self.assertTrue(changed)
        self.assertEqual(expected, binding['launcherSha256s'][path.name])
        with self.assertRaises(lifecycle.Refused):
            self.policy.generation_assets()

    def test_other_launcher_changes_are_refused_instead_of_normalized_away(self):
        path = self.home / "bin/start_kura_debug.sh"
        path.write_bytes(path.read_bytes() + b"\nexit 0\n")
        with self.assertRaises(lifecycle.Refused):
            self.policy.generation_assets()

    def test_legacy_or_missing_managed_main_unit_is_refused_even_with_matching_file_fingerprint(self):
        path = self.root / "lib/systemd/system/kura.service"
        path.write_bytes(path.read_bytes().replace(b"check-loaded-managed", b"check-loaded"))
        self.generation["unitSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.save_manifest()
        with self.assertRaises(lifecycle.Refused):
            self.policy.generation_assets()

    def test_unpaired_stop_program_and_changed_kill_mode_are_refused(self):
        path = self.root / "lib/systemd/system/kura.service"
        original = path.read_bytes()
        for raw in (original.replace(b"kura_framework_stop.py", b"kura_other_stop.py"),
                    original.replace(b"kura_watchdog_maintenance.py pulse", b"kura_watchdog_maintenance.py disarm"),
                    original.replace(b"KillMode=control-group", b"KillMode=mixed")):
            path.write_bytes(raw)
            self.generation["unitSha256"] = hashlib.sha256(raw).hexdigest()
            self.save_manifest()
            with self.assertRaises(lifecycle.Refused):
                self.policy.generation_assets()

    def test_bad_offline_classpath_cannot_escape_the_private_library_set(self):
        self.rewrite_jar(cohort.OFFLINE, lambda raw: raw.replace(b"Class-Path: lib/", b"Class-Path: ../", 1))
        with self.assertRaises(lifecycle.Refused):
            self.policy.generation_assets()

    def test_unregistered_file_fields_or_boolean_protocol_are_refused(self):
        original = self.manifest["protocol"]
        self.manifest["protocol"] = True
        self.save_manifest()
        with self.assertRaises(lifecycle.Refused):
            self.policy.generation_assets()
        self.manifest["protocol"] = original
        self.generation["files"]["../foreign"] = "a" * 64
        self.save_manifest()
        with self.assertRaises(lifecycle.Refused):
            self.policy.generation_assets()

    def test_linked_reader_or_changed_template_never_attests(self):
        path = self.home / self.generation["readers"]["crypto"]
        other = path.parent / "saved-reader"
        path.rename(other); path.symlink_to(other.name)
        with self.assertRaises((lifecycle.Refused, OSError)):
            self.policy.generation_assets()

    def test_folded_manifest_values_and_quoted_capability_commas_keep_their_meaning(self):
        values = cohort.headers(b'Manifest-Version: 1.0\r\nProvide-Capability: one;uses:="a,b",\r\n two;version:Version="1.0.0"\r\n\r\nName: ignored\r\n')
        self.assertEqual({"one", "two"}, set(cohort.clauses(values["provide-capability"])))
        self.assertNotIn("provide-capability", cohort.headers(b'Manifest-Version: 1.0\n\n Provide-Capability: untrusted\n'))
        self.assertEqual("值", cohort.headers(b'Key: \xe5\r\n \x80\xbc\r\n')["key"])
        with self.assertRaises(cohort.Refused):
            cohort.headers(b"Manifest-Version: 1.0\nmanifest-version: 1.0\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    config, remaining = parser.parse_known_args()
    CONFIG = config.repository.resolve(strict=True)
    unittest.main(argv=[sys.argv[0], *remaining])
