# SPDX-License-Identifier: EPL-2.0
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("reports", TOOLS / "collect-reports.py")
reports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reports)


class ReportCollectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.repo = self.workspace / "kura"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=CI fixture",
                        "-c", "user.email=ci@localhost", "commit", "-q", "--allow-empty", "-m", "fixture"], check=True)

    def report(self, module, name, kind, stamp, tests=1, errors=0, source=True):
        module = self.repo / module
        if source:
            path = module / "src/test/java" / Path(*name.split("$", 1)[0].split(".")).with_suffix(".java")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        path = module / "target" / kind / ("TEST-" + name + ".xml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'<testsuite name="{name}" tests="{tests}" failures="0" errors="{errors}" skipped="0"/>')
        os.utime(path, (stamp, stamp))
        return path

    def test_fresh_current_sources_and_nested_classes_are_counted_once_per_module(self):
        self.report("a", "org.Example$Nested", "surefire-reports", 101, tests=2)
        self.report("a", "org.Example$Nested", "failsafe-reports", 102, tests=3)
        self.report("b", "org.Example$Nested", "surefire-reports", 103, tests=4)
        self.report("a", "org.Stale", "surefire-reports", 99, tests=100)
        self.report("a", "org.Removed", "surefire-reports", 104, tests=200, source=False)
        result = reports.collect(self.workspace, ["kura"], 100)
        self.assertEqual(7, result["totals"]["tests"])
        self.assertEqual(2, len(result["reports"]))
        self.assertEqual(1, len(result["excluded"]))

    def test_cli_preserves_failed_reports_and_rejects_empty_current_run(self):
        self.report("a", "org.Failed", "failsafe-reports", 101, errors=1)
        output = self.workspace / "result"
        command = ["python3", str(TOOLS / "collect-reports.py"), "--workspace", str(self.workspace),
                   "--repositories", "kura", "--output", str(output), "--since"]
        failed = subprocess.run(command + ["100"], capture_output=True, text=True)
        self.assertEqual(1, failed.returncode)
        self.assertEqual(1, len(list((output / "test-reports").rglob("TEST-*.xml"))))
        empty = subprocess.run(command + ["200"], capture_output=True, text=True)
        self.assertEqual(1, empty.returncode)
        self.assertFalse(list((output / "test-reports").rglob("TEST-*.xml")))
        self.assertEqual(0, json.loads((output / "summary.json").read_text())["totals"]["tests"])


class WorkspaceEntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.root = self.workspace / "kura"
        (self.root / "tools/ci").mkdir(parents=True)
        self.entry = self.root / "tools/ci/verify-workspace.sh"
        shutil.copy2(TOOLS / "verify-workspace.sh", self.entry)
        # Collector contract is independently tested above; isolate build exit handling here.
        (self.root / "tools/ci/collect-reports.py").write_text('raise SystemExit(0)\n')
        self.marker = self.workspace / "build-called"
        build = self.root / "build-all.sh"
        build.write_text('#!/bin/sh\nprintf "%s %s %s" "$RUN_TESTS" "$RUN_IT" "$BUILD_DOCKER" > "$CI_MARKER"\nexit 7\n')
        build.chmod(0o755)
        self.mvn = self.workspace / "mvn"
        self.version("3.10.0", "21.0.12")
        self.env = {**os.environ, "MVN": str(self.mvn), "CI_MARKER": str(self.marker)}
        for repo in ("kura-position", "kura-opcua", "kura-deployment", "kura-networking", "kura-wires",
                     "kura-cloud", "kura-camel", "kura-artemis", "kura-container", "kura-triton",
                     "kura-management-ui", "kura-yofc-runtime", "yofc-iot"):
            (self.workspace / repo).mkdir()
            (self.workspace / repo / "pom.xml").touch()

    def version(self, maven, java):
        self.mvn.write_text(f"#!/bin/sh\nprintf 'Apache Maven {maven}\\nJava version: {java}, vendor: fixture\\n'\n")
        self.mvn.chmod(0o755)

    def run_entry(self, *args):
        return subprocess.run(["bash", str(self.entry), *args], env=self.env, capture_output=True, text=True)

    def test_read_only_preflight_and_missing_sibling(self):
        self.assertEqual(0, self.run_entry("--check").returncode)
        self.assertFalse(self.marker.exists())
        (self.workspace / "kura-networking/pom.xml").unlink()
        self.assertEqual(2, self.run_entry().returncode)
        self.assertFalse(self.marker.exists())

    def test_wrong_toolchain_fails_before_build(self):
        self.version("3.9.6", "21.0.12")
        self.assertEqual(2, self.run_entry().returncode)
        self.version("3.10.0", "17.0.1")
        self.assertEqual(2, self.run_entry().returncode)
        self.assertFalse(self.marker.exists())

    def test_build_failure_preserved_and_old_reports_cleared(self):
        output = self.root / "target/ci"
        (output / "test-reports").mkdir(parents=True)
        (output / "test-reports/old.xml").touch()
        (output / "summary.json").write_text('{}')
        self.assertEqual(7, self.run_entry().returncode)
        self.assertEqual("1 1 0", self.marker.read_text())
        self.assertFalse((output / "test-reports/old.xml").exists())
        self.assertFalse((output / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
