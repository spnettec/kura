#!/usr/bin/env python3
"""Run restored configuration assertions in fresh complete macOS applications."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ports_available():
    for port in (18480, 18443, 18444):
        with socket.socket() as handle:
            handle.bind(("127.0.0.1", port))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--template-profile", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--scenario", help="Run one named scenario; no automatic retry")
    args = parser.parse_args()
    for key in ("runtime", "template_profile", "fixtures", "repository", "archive", "java"):
        setattr(args, key, getattr(args, key).resolve())
    protected = Path.home() / ".kura-dev"
    if args.archive == protected or protected in args.archive.parents:
        parser.error("The archive must be outside the personal profile")
    args.archive.mkdir(parents=True, exist_ok=False)
    source = args.repository / "kura-osgi-tests/src/test/java/org/eclipse/kura/testing/ConfigurationServiceRuntimeIT.java"
    scenario_source = args.repository / "build-support/kura-configuration-test-fixtures/src/main/java/org/eclipse/kura/testing/configuration/fixture/ConfigurationServiceScenarios.java"
    block = re.search(r"@ValueSource\(strings = \{(.*?)\}\)", source.read_text(), re.S).group(1)
    names = re.findall(r'"(test[^" ]+)"', block)
    if len(names) != 47 or len(set(names)) != 47:
        parser.error("Expected the exact current 47-scenario controller")
    if args.scenario:
        if args.scenario not in names:
            parser.error("Unknown scenario")
        names = [args.scenario]
    fixture_files = ["apiguardian-api.jar", "opentest4j.jar", "junit-platform-commons.jar",
                     "junit-jupiter-api.jar", "kura-configuration-test-fixtures.jar"]
    helpers = args.archive / "helpers"
    helpers.mkdir()
    for file in fixture_files:
        shutil.copy2(args.fixtures / file, helpers / file)
    helper = args.repository / "kura-dev-runtime/acceptance/full-runtime-probe/target/kura-full-runtime-acceptance-fixture-1.0.0-SNAPSHOT.jar"
    shutil.copy2(helper, helpers / "full-runtime-probe.jar")
    metadata = {"startedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "runtime": str(args.runtime), "templateProfile": str(args.template_profile),
                "coreRevision": subprocess.check_output(["git", "-C", str(args.repository), "rev-parse", "HEAD"], text=True).strip(),
                "sources": {str(p.relative_to(args.repository)): digest(p) for p in (source, scenario_source)},
                "helpers": {p.name: digest(p) for p in helpers.iterdir()}, "scenarios": names, "results": []}
    summary = args.archive / "summary.json"
    for index, name in enumerate(names, 1):
        ports_available()
        case = args.archive / name
        case.mkdir()
        home = case / "profile"
        shutil.copytree(args.template_profile, home, ignore=shutil.ignore_patterns("logs", "tmp", "*-result.json"))
        (home / "logs").mkdir()
        (home / "tmp").mkdir()
        # Snapshot/bootstrap files can contain absolute filesystem keystore paths.
        # Relocate those references as well as JVM properties to the owned copy.
        relocated = []
        for copied in home.rglob("*"):
            if copied.is_file() and copied.suffix in (".xml", ".properties", ".json"):
                raw = copied.read_bytes()
                original = str(args.template_profile).encode()
                if original in raw:
                    copied.write_bytes(raw.replace(original, str(home).encode()))
                    relocated.append(str(copied.relative_to(home)))
        (case / "relocated-profile-files.json").write_text(json.dumps(relocated, indent=2) + "\n")
        (home / ".configuration-acceptance-owned").write_text(name + "\n")
        configuration = case / "configuration"
        configuration.mkdir()
        for file in (args.runtime / "configuration").iterdir():
            if file.is_file():
                text = file.read_text().replace(str(args.template_profile), str(home))
                text = text.replace(str(args.runtime / "configuration"), str(configuration))
                if file.name == "kura.properties":
                    encrypted = name != "testPlaintextSnapshotRetainsEmbeddedXml"
                    text = re.sub(r"(?m)^kura.snapshots.encrypt=.*$", "kura.snapshots.encrypt=" + str(encrypted).lower(), text)
                if file.name == "config.ini":
                    extra = ["reference:" + (helpers / f).as_uri() + "@5:start" for f in fixture_files]
                    extra.append("reference:" + (helpers / "full-runtime-probe.jar").as_uri() + "@6:start")
                    text = re.sub(r"(?m)^osgi.bundles=(.*)$", lambda m: m.group(0) + "," + ",".join(extra), text)
                (configuration / file.name).write_text(text)
        options = [x.replace(str(args.template_profile), str(home)).replace(str(args.runtime / "configuration"), str(configuration))
                   for x in shlex.split((args.runtime / "jvm.args").read_text())]
        command = [str(args.java), *options, "-Dkura.acceptance.root=" + str(args.archive),
                   "-Dkura.acceptance.configuration.scenario=" + name, "-jar", str(args.runtime / "launcher.jar"),
                   "-configuration", str(configuration), "-install", str(args.runtime), "-console", "-consoleLog"]
        (case / "command.json").write_text(json.dumps(command, indent=2) + "\n")
        started = time.monotonic()
        result_file = home / "configuration-scenario-result.json"
        with (case / "console.log").open("w") as log:
            process = subprocess.Popen(command, cwd=args.runtime, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = started + 90
                while process.poll() is None and not result_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.25)
                result = json.loads(result_file.read_text()) if result_file.exists() else {
                    "scenario": name, "passed": False, "error": "No probe result before exit/90-second deadline"}
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=15)
                        forced = False
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
                        forced = True
                else:
                    forced = False
                process.stdin.close()
        ports_available()
        result.update(pid=process.pid, elapsedSeconds=round(time.monotonic() - started, 3),
                      exitCode=process.returncode, forcedShutdown=forced, portsReleased=True,
                      consoleSha256=digest(case / "console.log"))
        if forced:
            result["passed"] = False
            result["error"] = "Application required forced shutdown"
        metadata["results"].append(result)
        summary.write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"{index}/{len(names)} {name}: {'PASS' if result['passed'] else 'FAIL'} ({result['elapsedSeconds']}s)", flush=True)
        if not result["passed"]:
            raise SystemExit(1)
    metadata["completedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata["passed"] = True
    summary.write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
