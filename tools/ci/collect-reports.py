#!/usr/bin/env python3
"""Publish fresh reports with an exact current Java source, once per nested class."""
# SPDX-License-Identifier: EPL-2.0
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


def collect(workspace, repositories, since):
    reports, excluded, revisions = {}, [], []
    for name in repositories:
        repo = workspace / name
        revision = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                               capture_output=True, text=True, check=True).stdout.strip()
        revisions.append({"repository": name, "revision": revision, "dirty": bool(dirty)})
        for root, dirs, _ in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in {".git", ".idea", "node_modules", ".obsidian-knowledge"}]
            if "target" not in dirs:
                continue
            dirs.remove("target")
            module = Path(root)
            for kind in ("surefire-reports", "failsafe-reports"):
                for report in (module / "target" / kind).glob("TEST-*.xml"):
                    if report.stat().st_mtime < since:
                        continue
                    suite = ET.parse(report).getroot()
                    class_name = suite.attrib["name"]
                    source_path = Path(*class_name.split("$", 1)[0].split(".")).with_suffix(".java")
                    source = next((p for source_set in ("test", "main")
                                   if (p := module / "src" / source_set / "java" / source_path).is_file()), None)
                    relative = str(report.relative_to(workspace))
                    if source is None:
                        excluded.append({"report": relative, "reason": "No exact current Java source"})
                        continue
                    row = {"repository": name, "module": str(module.relative_to(repo)), "class": class_name,
                           "source": str(source.relative_to(workspace)), "report": relative,
                           "sha256": hashlib.sha256(report.read_bytes()).hexdigest(), "mtime": report.stat().st_mtime,
                           **{k: int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")}}
                    key = (name, row["module"], class_name)
                    if key not in reports or reports[key]["mtime"] < row["mtime"]:
                        reports[key] = row
    rows = sorted(reports.values(), key=lambda r: (r["repository"], r["module"], r["class"]))
    return {"since": since, "sourceRevisions": revisions, "reports": rows, "excluded": excluded,
            "totals": {k: sum(row[k] for row in rows) for k in ("tests", "failures", "errors", "skipped")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--repositories", nargs="+", required=True)
    parser.add_argument("--since", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if any(Path(name).name != name or name in {".", ".."} for name in args.repositories):
        parser.error("Repository names must be immediate workspace children")
    result = collect(workspace, args.repositories, args.since)
    report_dir = args.output / "test-reports"
    if report_dir.exists():
        shutil.rmtree(report_dir)
    report_dir.mkdir(parents=True)
    for row in result["reports"]:
        destination = report_dir / row["report"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workspace / row["report"], destination)
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["totals"]))
    totals = result["totals"]
    return int(not totals["tests"] or bool(totals["failures"] or totals["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
