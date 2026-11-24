# SPDX-License-Identifier: EPL-2.0
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


BIN = Path(__file__).resolve().parents[1] / "main/resources/unfiltered/pkg/bin"
sys.path.insert(0, str(BIN))
import kura_watchdog_maintenance as watchdog
import kura_key_cohort as cohort


class WatchdogMaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.marker = Path(self.directory.name) / "marker"

    def make_marker(self, value):
        self.marker.write_bytes(value)
        self.marker.chmod(0o600)

    def test_absent_marker_does_not_resolve_a_device(self):
        with patch.object(watchdog, "verified_device") as device:
            for action in ("check", "pulse", "disarm"):
                watchdog.maintain(action, marker=self.marker)
            device.assert_not_called()

    def test_admission_refuses_nondevice_paths_and_unsafe_markers(self):
        for value in (b"relative", b"/etc/kura/credentials", b"/dev/../tmp/marker", b"/dev/watchdog\0"):
            with self.subTest(value=value):
                self.make_marker(value)
                with self.assertRaises(ValueError):
                    watchdog.request_path(self.marker, {os.getuid()})
        self.make_marker(b"/dev/watchdog")
        alias = self.marker.with_name("alias")
        alias.symlink_to(self.marker)
        with self.assertRaises(OSError):
            watchdog.request_path(alias, {os.getuid()})
        self.marker.chmod(0o622)
        with self.assertRaises(ValueError):
            watchdog.request_path(self.marker, {os.getuid()})

    def test_only_exact_device_identity_receives_fixed_actions(self):
        path = Path("/dev/watchdog0")
        sampled = SimpleNamespace(st_dev=1, st_ino=3, st_ctime_ns=5, st_mode=stat.S_IFCHR | 0o660,
                                  st_rdev=os.makedev(250, 0))
        with patch.object(watchdog, "request_path", return_value=path), \
                patch.object(watchdog, "verified_device", return_value=(path, sampled)), \
                patch.object(watchdog, "watchdog_setting", return_value=None), \
                patch.object(os, "open", return_value=9) as opened, patch.object(os, "close") as closed, \
                patch.object(os, "fstat", return_value=sampled) as current, patch.object(os, "write", return_value=1) as write:
            watchdog.maintain("check")
            opened.assert_not_called()
            watchdog.maintain("pulse")
            write.assert_called_once_with(9, b"w")
            closed.assert_called_once_with(9)
            write.reset_mock()
            watchdog.maintain("disarm")
            write.assert_called_once_with(9, b"V")
            write.reset_mock()
            current.return_value = SimpleNamespace(**(vars(sampled) | {"st_ino": 7}))
            with self.assertRaises(ValueError):
                watchdog.maintain("pulse")
            write.assert_not_called()

    def test_nowayout_refuses_maintenance_without_opening_the_device(self):
        path = Path("/dev/watchdog0")
        with patch.object(watchdog, "request_path", return_value=path), \
                patch.object(watchdog, "verified_device", return_value=(path, None)), \
                patch.object(watchdog, "watchdog_setting", side_effect=lambda info, rows, name:
                             {"nowayout": "1", "state": "inactive"}[name]), patch.object(os, "open") as opened:
            for action in ("check", "pulse", "disarm"):
                with self.subTest(action=action), self.assertRaises(watchdog.HandoffUnavailable):
                    watchdog.maintain(action)
            opened.assert_not_called()

    def test_active_nowayout_can_still_be_fed(self):
        path = Path("/dev/watchdog0")
        sampled = SimpleNamespace(st_dev=1, st_ino=3, st_ctime_ns=5, st_mode=stat.S_IFCHR | 0o660,
                                  st_rdev=os.makedev(250, 0))
        with patch.object(watchdog, "request_path", return_value=path), \
                patch.object(watchdog, "verified_device", return_value=(path, sampled)), \
                patch.object(watchdog, "watchdog_setting", side_effect=["1", "active"]), \
                patch.object(os, "open", return_value=9), patch.object(os, "close"), \
                patch.object(os, "fstat", return_value=sampled), patch.object(os, "write", return_value=1) as write:
            watchdog.maintain("pulse")
            write.assert_called_once_with(9, b"w")

    def test_registered_device_must_belong_to_watchdog_subsystem(self):
        with patch.object(Path, "read_text", return_value="250:0\n"), patch.object(
                Path, "resolve", side_effect=[Path("/sys/devices/virtual/watchdog/watchdog0"),
                                             Path("/sys/class/watchdog")]):
            self.assertTrue(watchdog.registered_watchdog(os.makedev(250, 0), watchdog.SYSTEM_DEVICES))
        with patch.object(Path, "read_text", return_value="1:3\n"), patch.object(
                Path, "resolve", side_effect=[Path("/sys/devices/virtual/mem/null"), Path("/sys/class/mem")]):
            self.assertFalse(watchdog.registered_watchdog(os.makedev(1, 3), watchdog.SYSTEM_DEVICES))

    def test_packaged_unit_binds_typed_handoff_in_manifest(self):
        template = BIN.parents[2] / "filtered/pkg/install/kura.service"
        unit = template.read_bytes().replace(b"INSTALL_DIR", b"/opt/eclipse")
        self.assertEqual(cohort.managed_unit(unit),
                         {cohort.FRAMEWORK_PID, cohort.FRAMEWORK_STOP, cohort.WATCHDOG_MAINTENANCE,
                          "bin/kura_modem_cohort.py", "bin/kura_recovery_launch.py"})
        with self.assertRaises(cohort.Refused):
            cohort.managed_unit(unit.replace(b"kura_watchdog_maintenance.py pulse",
                                            b"kura_watchdog_maintenance.py disarm"))


if __name__ == "__main__":
    unittest.main()
