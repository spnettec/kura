# SPDX-License-Identifier: EPL-2.0
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main/resources/unfiltered/pkg/bin"))
from kura_framework_pid import prepare_pid


@unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0, "requires a Linux runtime directory owned by root")
class FrameworkPidTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.file = Path(directory.name) / "kura.pid"
        self.run = os.open(directory.name, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.run)
        self.account = pwd.getpwnam("nobody")

    def prepare(self):
        prepare_pid(self.run, self.account)

    def test_new_interrupted_and_stale_files(self):
        self.prepare()
        self.assertEqual((self.file.stat().st_uid, stat.S_IMODE(self.file.stat().st_mode)), (self.account.pw_uid, 0o600))
        self.file.unlink()
        self.file.touch(mode=0o600)
        self.prepare()
        self.assertEqual(self.file.stat().st_uid, self.account.pw_uid)
        self.file.unlink()
        with subprocess.Popen(["/bin/true"]) as child:
            self.assertEqual(child.wait(), 0)
        record = f"{child.pid}\n".encode()
        self.file.write_bytes(record)
        self.file.chmod(0o644)
        inode = self.file.stat().st_ino
        self.prepare()
        current = self.file.stat()
        self.assertEqual((current.st_ino, current.st_uid, current.st_gid, stat.S_IMODE(current.st_mode)),
                         (inode, self.account.pw_uid, self.account.pw_gid, 0o600))
        self.prepare()
        self.assertEqual(self.file.stat().st_ctime_ns, current.st_ctime_ns)

    def test_live_or_unrecognized_record_keeps_ownership_and_contents(self):
        for record in (f"{os.getpid()}\n".encode(), b"unfinished", b"1\n", b"2147483648\n"):
            self.file.write_bytes(record)
            self.file.chmod(0o600)
            before = self.file.stat()
            with self.assertRaises(ValueError):
                self.prepare()
            self.assertEqual(self.file.stat().st_ctime_ns, before.st_ctime_ns)
            self.assertEqual(self.file.read_bytes(), record)


if __name__ == "__main__":
    unittest.main()
