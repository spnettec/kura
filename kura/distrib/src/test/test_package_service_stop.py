"""Exercise shipped maintainer scripts before any upgrade copy or removal."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


CONTROL = Path(__file__).resolve().parents[1] / "main/resources/variants/linux/unfiltered/deb/control"


class PackageServiceStop(unittest.TestCase):
    def run_script(self, name, action="upgrade", key_status=0, stop_status=0,
                   show_status=0, state="inactive", main="0", control="0"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "opt/eclipse/kura"
            for child in ("user", "data", "packages", "siblings", "log", ".data", "framework"):
                (home / child).mkdir(parents=True, exist_ok=True)
            marker = home / "user/existing-state"
            marker.write_bytes(b"existing key-associated state")
            provider = home.parent / "kura-filemove-state"
            provider.mkdir()
            (provider / "retained.receipt").write_bytes(b"retained provider state")
            unit = root / "lib/systemd/system/kura.service"
            unit.parent.mkdir(parents=True)
            unit.write_text("[Service]\nRestart=on-failure\n")
            events = root / "events"
            events.touch()
            source = (CONTROL / name).read_text()
            # Admission guards have their own acceptance. Exercise the actual
            # package lifecycle suffix, with only external commands substituted.
            source = source[source.index("INSTALL_DIR=/opt/eclipse"):]
            # preinst's helper precedes this suffix, while prerm's is inside it.
            if name == "preinst":
                self.assertIn("function stopKuraForPackage", source)
            for absolute in ("/opt/eclipse", "/lib/systemd/system/kura.service",
                             "/var/log", "/var/lib/kura-retained", "/tmp/watchdog",
                             "/var/run/kura.pid"):
                source = source.replace(absolute, str(root / absolute.lstrip("/")))
            (root / "var/log").mkdir(parents=True)
            prelude = r'''
python3() {
    echo "key:$*" >> "$EVENTS"
    [ "$KEY_STATUS" = 0 ] || return "$KEY_STATUS"
    case "$*" in
        *--prepare-upgrade-copy*) mkdir "$CAPTURE_STAGE" && printf '%s\n' "$CAPTURE_STAGE" ;;
        *--publish-upgrade-copy*) mv "$CAPTURE_STAGE" "$CAPTURE_COPY" ;;
    esac
}
checkManagedNmPolicy() { return 0; }
checkWpaPolicy() { return 0; }
checkModemCohort() { return 0; }
systemctl() {
    echo "systemctl:$*" >> "$EVENTS"
    case "$1" in
        stop) return "$STOP_STATUS" ;;
        show)
            printf 'ActiveState=%s\nMainPID=%s\nControlPID=%s\n' "$STATE" "$MAIN" "$CONTROL_PID"
            return "$SHOW_STATUS" ;;
        *) return 0 ;;
    esac
}
pgrep() { echo pgrep >> "$EVENTS"; return 1; }
kill() { echo "raw-kill:$*" >> "$EVENTS"; return 0; }
cp() { echo "copy:$*" >> "$EVENTS"; return 0; }
rm() { echo "wipe:$*" >> "$EVENTS"; return 0; }
dpkg-query() { return 0; }
sleep() { return 0; }
'''
            script = root / "entrypoint"
            script.write_text(prelude + source)
            env = dict(os.environ, EVENTS=str(events), KEY_STATUS=str(key_status),
                       CAPTURE_STAGE=str(root / "opt/eclipse/.kura-preserve.tmp"),
                       CAPTURE_COPY=str(root / "opt/eclipse/.kura-preserve"),
                       STOP_STATUS=str(stop_status), SHOW_STATUS=str(show_status),
                       STATE=state, MAIN=main, CONTROL_PID=control)
            result = subprocess.run(["bash", str(script), action], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(marker.read_bytes(), b"existing key-associated state")
            return result, events.read_text().splitlines()

    def test_upgrade_waits_for_manager_stop_after_key_capture_before_copy(self):
        for name in ("preinst", "prerm"):
            with self.subTest(name=name):
                result, events = self.run_script(name)
                self.assertEqual(result.returncode, 0, result.stderr)
                key = next(i for i, event in enumerate(events) if event.startswith("key:"))
                stop = next(i for i, event in enumerate(events) if event == "systemctl:stop kura.service")
                show = next(i for i, event in enumerate(events) if event.startswith("systemctl:show"))
                self.assertLess(key, stop)
                self.assertLess(stop, show)
                self.assertFalse(any(event.startswith("raw-kill:") for event in events))
                if name == "preinst":
                    first_change = next(i for i, event in enumerate(events) if event.startswith(("copy:", "wipe:")))
                    self.assertLess(show, first_change)
                else:
                    self.assertFalse(any(event.startswith(("copy:", "wipe:")) for event in events))

    def test_key_failure_preserves_running_service_and_files(self):
        for name in ("preinst", "prerm"):
            with self.subTest(name=name):
                result, events = self.run_script(name, key_status=42)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(event.startswith(("systemctl:", "copy:", "wipe:", "raw-kill:")) for event in events))

    def test_install_leaves_retained_provider_roots_to_their_own_package(self):
        result, events = self.run_script("preinst", "install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(event.startswith("wipe:") and "/opt/eclipse/" in event for event in events))

    def assert_stop_failure_preserves_files(self, **settings):
        for name, action in (("preinst", "upgrade"), ("preinst", "install"),
                             ("prerm", "upgrade"), ("prerm", "remove")):
            with self.subTest(name=name, action=action, **settings):
                result, events = self.run_script(name, action, **settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(event.startswith(("copy:", "wipe:", "raw-kill:")) for event in events))

    def test_stop_failure_never_falls_back_to_signal_or_wipe(self):
        self.assert_stop_failure_preserves_files(stop_status=5)

    def test_unavailable_manager_state_never_releases_upgrade(self):
        self.assert_stop_failure_preserves_files(show_status=5)

    def test_queued_restart_never_releases_upgrade(self):
        self.assert_stop_failure_preserves_files(state="activating")

    def test_reported_daemon_pid_never_releases_upgrade(self):
        self.assert_stop_failure_preserves_files(main="1234")

    def test_reported_control_pid_never_releases_upgrade(self):
        self.assert_stop_failure_preserves_files(control="1234")

    def test_missing_manager_fields_never_release_upgrade(self):
        self.assert_stop_failure_preserves_files(state="", main="", control="")

    def test_failed_upgrade_is_noop(self):
        result, events = self.run_script("prerm", "failed-upgrade")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
