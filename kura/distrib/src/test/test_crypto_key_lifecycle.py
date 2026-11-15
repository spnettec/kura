"""Core key lifecycle contracts: preserve encrypted data, reject ambiguous upgrades."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HELPER = Path(__file__).resolve().parents[1] / "main/resources/unfiltered/pkg/bin/kura_key_store.py"
spec = importlib.util.spec_from_file_location("kura_key_policy",HELPER)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

class EncryptionKeyLifecycleTests(unittest.TestCase):
    def setUp(self):
        previous_umask = os.umask(0o077)
        self.addCleanup(os.umask,previous_umask)
        self.temp = tempfile.TemporaryDirectory(prefix="kura-key-policy-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = policy.Store(self.root)
        self.key = self.store.path(policy.KEY_PATH)

    def put(self, absolute, value, mode=0o600):
        path = self.store.path(absolute)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value if isinstance(value,bytes) else value.encode())
        path.chmod(mode)
        return path

    def legacy(self, value="0123456789abcdef"):
        return self.put("/usr/lib/systemd/system/kura.service",
            "[Service]\nUser=kurad\nExecStart=/bin/sh /opt/eclipse/kura/bin/start_kura_background.sh\n"
            "Environment=KURA_CRYPTO_SECRET_KEY="+value+"\n",0o644)

    def current_unit(self):
        return self.put("/usr/lib/systemd/system/kura.service",
            "[Service]\nUser=kurad\nExecStartPre=/usr/bin/python3 -I /opt/eclipse/kura/bin/kura_key_store.py check-loaded\n"
            "ExecStart=/bin/sh /opt/eclipse/kura/bin/start_kura_background.sh\n"
            "LoadCredential=kura_encryption_key:"+policy.KEY_PATH+"\n",0o644)

    def test_fresh_install_gets_private_random_key_and_is_byte_idempotent(self):
        self.assertEqual(self.store.prepare("install")["source"],"fresh")
        value = self.key.read_bytes()
        self.assertEqual(len(value),32)
        self.assertEqual(self.key.stat().st_mode&0o777,0o400)
        self.assertEqual(self.key.parent.stat().st_mode&0o777,0o700)
        receipt = self.store.path(policy.RECEIPT_PATH)
        before = (value,receipt.read_bytes(),self.key.stat().st_ino,receipt.stat().st_ino)
        self.current_unit()
        self.store.prepare("upgrade")
        self.assertEqual(before,(self.key.read_bytes(),receipt.read_bytes(),self.key.stat().st_ino,receipt.stat().st_ino))

    def test_independent_installs_do_not_share_an_encryption_key(self):
        self.store.prepare("install")
        second = self.root/"another-host"
        second.mkdir(mode=0o700)
        policy.Store(second).prepare("install")
        self.assertNotEqual(self.key.read_bytes(),(second/policy.KEY_PATH.lstrip("/")).read_bytes())

    def test_legacy_unit_key_is_preserved_before_old_state_changes(self):
        self.legacy()
        snapshot = self.put("/opt/eclipse/kura/user/snapshots/snapshot_4.xml",b"opaque-encrypted-existing-snapshot")
        store = self.put("/opt/eclipse/kura/data/store.save",b"opaque-encrypted-existing-store")
        before = (snapshot.read_bytes(),store.read_bytes())
        result = self.store.prepare("upgrade")
        self.assertEqual(self.key.read_bytes(),b"0123456789abcdef")
        self.assertEqual(result["source"],"legacy")
        self.assertEqual(before,(snapshot.read_bytes(),store.read_bytes()))

    def test_legacy_missing_custom_key_preserves_the_actual_core_default(self):
        self.put("/usr/lib/systemd/system/kura.service",
            "[Service]\nExecStart=/bin/sh /opt/eclipse/kura/bin/start_kura_background.sh\n",0o644)
        result = self.store.prepare("upgrade")
        self.assertEqual(self.key.read_bytes(),policy.CORE_DEFAULT)
        self.assertTrue(result["legacyKey"])

    def test_invalid_legacy_custom_key_preserves_old_core_fallback(self):
        self.legacy("invalid")
        self.store.prepare("upgrade")
        self.assertEqual(self.key.read_bytes(),policy.CORE_DEFAULT)

    def test_private_credential_bytes_take_precedence_over_legacy_environment(self):
        value = bytes(range(32))
        self.put("/etc/legacy-kura-key",value,0o400)
        unit = self.legacy()
        unit.write_text(unit.read_text()+"LoadCredential=kura_encryption_key:/etc/legacy-kura-key\n")
        self.store.prepare("upgrade")
        self.assertEqual(self.key.read_bytes(),value)

    def test_missing_existing_key_never_creates_a_replacement_for_data(self):
        existing = self.put("/opt/eclipse/kura/data/store.save",b"existing-ciphertext")
        with self.assertRaises(policy.Refused):
            self.store.prepare("upgrade")
        self.assertFalse(self.key.exists())
        self.assertEqual(existing.read_bytes(),b"existing-ciphertext")

    def test_existing_canonical_and_legacy_conflict_is_not_overwritten(self):
        self.store.prepare("install")
        before = self.key.read_bytes()
        self.legacy()
        with self.assertRaises(policy.Refused):
            self.store.prepare("upgrade")
        self.assertEqual(self.key.read_bytes(),before)

    def test_live_key_disagreement_refuses_before_key_publication(self):
        self.legacy()
        self.store.running_key = lambda: b"different-key-16"
        with self.assertRaises(policy.Refused):
            self.store.prepare("upgrade")
        self.assertFalse(self.key.exists())

    def test_symlinked_key_cannot_redirect_publication(self):
        target = self.put("/outside",b"outside-value",0o400)
        self.key.parent.mkdir(parents=True,mode=0o700)
        self.key.symlink_to(target)
        with self.assertRaises((policy.Refused,OSError)):
            self.store.prepare("install")
        self.assertEqual(target.read_bytes(),b"outside-value")

    def test_hardlinked_key_is_refused(self):
        self.store.prepare("install")
        os.link(self.key,self.root/"second-link")
        with self.assertRaises(policy.Refused):
            self.store.prepare("auto")

    def test_fifo_key_is_refused_without_waiting_for_a_writer(self):
        self.key.parent.mkdir(parents=True,mode=0o700)
        os.mkfifo(self.key,0o600)
        with self.assertRaises(policy.Refused):
            self.store.prepare("install")

    def test_symlinked_credential_ancestor_is_refused(self):
        outside = self.root/"outside-directory"
        outside.mkdir(mode=0o700)
        (self.root/"etc").symlink_to(outside)
        with self.assertRaises(policy.Refused):
            self.store.prepare("install")
        self.assertEqual(list(outside.iterdir()),[])

    def test_nonprivate_existing_key_is_refused_without_rewriting_it(self):
        self.store.prepare("install")
        value = self.key.read_bytes()
        self.key.chmod(0o644)
        with self.assertRaises(policy.Refused):
            self.store.prepare("auto")
        self.assertEqual(self.key.read_bytes(),value)

    def test_malformed_receipt_never_rotates_existing_key(self):
        self.store.prepare("install")
        before = self.key.read_bytes()
        self.store.path(policy.RECEIPT_PATH).write_text("[]")
        with self.assertRaises(policy.Refused):
            self.store.prepare("auto")
        self.assertEqual(self.key.read_bytes(),before)

    def test_custom_environment_file_requires_review_before_data_changes(self):
        unit = self.legacy()
        unit.write_text(unit.read_text()+"EnvironmentFile=/etc/custom-secret\n")
        snapshot = self.put("/opt/eclipse/kura/user/snapshots/snapshot_1.xml",b"ciphertext")
        with self.assertRaises(policy.Refused):
            self.store.prepare("upgrade")
        self.assertFalse(self.key.exists())
        self.assertEqual(snapshot.read_bytes(),b"ciphertext")

    def test_key_startup_dropin_requires_review(self):
        self.legacy()
        self.put("/etc/systemd/system/kura.service.d/secret.conf",
                 "[Service]\nEnvironment=KURA_CRYPTO_SECRET_KEY=another-key-1234\n",0o644)
        with self.assertRaises(policy.Refused):
            self.store.prepare("upgrade")
        self.assertFalse(self.key.exists())

    def test_networking_capability_dropin_is_not_a_key_override(self):
        self.legacy()
        self.put("/usr/lib/systemd/system/kura.service.d/kura-networking.conf",
                 "[Service]\nAmbientCapabilities=CAP_NET_ADMIN\n",0o644)
        self.store.prepare("upgrade")
        self.assertEqual(self.key.read_bytes(),b"0123456789abcdef")

    def test_retained_key_archive_can_recover_without_any_new_key(self):
        self.store.prepare("install")
        value = self.key.read_bytes()
        destination = self.store.path("/var/lib/kura-retained/encryption")
        self.store.archive(destination)
        self.key.rename(self.key.with_name("previous-key-retained"))
        self.store.path(policy.RECEIPT_PATH).rename(self.key.parent/"previous-receipt-retained")
        self.store.prepare("install")
        self.assertEqual(self.key.read_bytes(),value)
        self.assertEqual((destination/policy.CREDENTIAL).read_bytes(),value)

    def test_archive_conflict_keeps_both_original_key_values(self):
        self.store.prepare("install")
        before = self.key.read_bytes()
        destination = self.store.path("/var/lib/kura-retained/encryption")
        destination.mkdir(parents=True,mode=0o700)
        (destination/policy.CREDENTIAL).write_bytes(b"conflicting-key!")
        (destination/policy.CREDENTIAL).chmod(0o400)
        with self.assertRaises(policy.Refused):
            self.store.archive(destination)
        self.assertEqual(self.key.read_bytes(),before)
        self.assertEqual((destination/policy.CREDENTIAL).read_bytes(),b"conflicting-key!")

    def test_saved_unit_is_verified_without_reverting_credential_unit(self):
        legacy = self.legacy()
        saved = self.put("/opt/eclipse/.kura-preserve/systemd/kura.service",legacy.read_bytes(),0o600)
        self.store.prepare("upgrade")
        target = self.current_unit()
        original_target = target.read_bytes()
        self.store.verify_migration(saved,target)
        self.assertEqual(target.read_bytes(),original_target)
        self.assertNotIn(b"Environment=KURA_CRYPTO_SECRET_KEY",target.read_bytes())

    def test_removed_legacy_credential_source_can_use_the_admitted_unit_digest(self):
        source = self.put("/etc/legacy-key",bytes(range(32)),0o400)
        unit = self.legacy()
        unit.write_text(unit.read_text()+"LoadCredential=kura_encryption_key:/etc/legacy-key\n")
        saved = self.put("/opt/eclipse/.kura-preserve/systemd/kura.service",unit.read_bytes(),0o600)
        self.store.prepare("upgrade")
        source.rename(source.with_suffix(".retained"))
        target = self.current_unit()
        self.store.verify_migration(saved,target)
        self.assertEqual(self.key.read_bytes(),bytes(range(32)))

    def test_changed_unit_source_is_refused(self):
        unit = self.legacy()
        self.store.read(unit)
        unit.write_text(unit.read_text()+"# concurrent edit\n")
        with self.assertRaises(policy.Refused):
            self.store.stable()

    def test_loaded_credential_check_does_not_fall_back_to_environment_key(self):
        folder = self.root/"loaded"
        folder.mkdir(mode=0o700)
        key = folder/policy.CREDENTIAL
        env = dict(os.environ,CREDENTIALS_DIRECTORY=str(folder),
                   KURA_CRYPTO_SECRET_KEY="0123456789abcdef")
        def run():
            return subprocess.run([sys.executable,"-I",str(HELPER),"check-loaded"],
                                  env=env,capture_output=True,text=True)
        self.assertNotEqual(run().returncode,0)
        key.write_bytes(b"invalid")
        key.chmod(0o400)
        self.assertNotEqual(run().returncode,0)
        value = bytes(range(32))
        key.chmod(0o600)
        key.write_bytes(value)
        self.assertEqual(run().returncode,0)
        key.chmod(0o644)
        self.assertNotEqual(run().returncode,0)

class LoadedCredentialAclTests(unittest.TestCase):
    UID = 61721

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="kura-native-acl-")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.key = self.folder/policy.CREDENTIAL
        self.key.write_bytes(bytes(range(32)))
        self.key.chmod(0o440)
        # Observed systemd 255 ACL: root owner, named service reader, empty
        # owning group/other entries. No key bytes are part of this fixture.
        self.entries = [(1,4,0xffffffff),(2,4,self.UID),(4,0,0xffffffff),
                        (16,4,0xffffffff),(32,0,0xffffffff)]
        self.original_fstat = os.fstat

    def run_check(self,entries=None,version=2,missing_acl=False,truncate=False,
                  privileged_capture=False,capture_uid=None):
        raw = struct.pack("<I",version)+b"".join(struct.pack("<HHI",*entry)
            for entry in (self.entries if entries is None else entries))
        if truncate:
            raw = raw[:-1]
        def native_stat(fd):
            actual = self.original_fstat(fd)
            values = {name:getattr(actual,name) for name in
                ["st_mode","st_gid","st_nlink","st_size","st_dev","st_ino","st_mtime_ns","st_ctime_ns"]}
            return SimpleNamespace(st_uid=0,**values)
        with patch.dict(os.environ,CREDENTIALS_DIRECTORY=str(self.folder)), \
                patch.object(policy.os,"geteuid",return_value=0 if privileged_capture else self.UID), \
                patch.object(policy.os,"fstat",side_effect=native_stat), \
                patch.object(policy.os,"getxattr",return_value=raw,create=True,
                    side_effect=OSError("No ACL") if missing_acl else None):
            if privileged_capture:
                store=policy.Store(self.folder,owner=0)
                self.assertEqual(store.read(self.key,private=True,owners={0},loaded_for_uid=capture_uid),bytes(range(32)))
                store.stable()
            else:
                policy.check_loaded()

    def test_upgrade_capture_uses_the_actual_service_uid_and_revalidates_it(self):
        self.run_check(privileged_capture=True,capture_uid=self.UID)
        with self.assertRaises(policy.Refused):
            self.run_check(privileged_capture=True,capture_uid=self.UID+1)

    def test_canonical_private_reads_do_not_accept_service_delegation(self):
        with self.assertRaises(policy.Refused):
            self.run_check(privileged_capture=True)

    def test_native_systemd_acl_grants_only_the_service_user(self):
        self.run_check()

    def test_plain_group_readable_key_is_still_refused(self):
        with self.assertRaises(policy.Refused):
            self.run_check(missing_acl=True)

    def test_additional_acl_reader_is_refused(self):
        with self.assertRaises(policy.Refused):
            self.run_check(entries=self.entries[:2]+[(2,4,self.UID+1)]+self.entries[2:])

    def test_owning_group_access_is_refused(self):
        entries=list(self.entries)
        entries[2]=(4,4,0xffffffff)
        with self.assertRaises(policy.Refused):
            self.run_check(entries=entries)

    def test_acl_for_another_service_uid_is_refused(self):
        entries=list(self.entries)
        entries[1]=(2,4,self.UID+1)
        with self.assertRaises(policy.Refused):
            self.run_check(entries=entries)

    def test_malformed_or_writable_acl_is_refused(self):
        writable=list(self.entries)
        writable[3]=(16,6,0xffffffff)
        public=list(self.entries)
        public[4]=(32,4,0xffffffff)
        for options in [dict(version=1),dict(truncate=True),
                        dict(entries=writable),dict(entries=public)]:
            with self.subTest(options=options),self.assertRaises(policy.Refused):
                self.run_check(**options)

if __name__=="__main__":
    unittest.main()

