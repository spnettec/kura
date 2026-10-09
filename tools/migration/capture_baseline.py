#!/usr/bin/env python3
"""Freeze repository revisions, handwritten metadata and existing artifacts before migration.

This captures evidence, not a claim that the old build/runtime passes. Artifact copies live
outside the checkout so subsequent clean/install cannot overwrite the rollback baseline.
"""
import argparse
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from bundle_audit import inspect, sha256

REPOSITORIES = ['kura', 'kura-position', 'kura-opcua', 'kura-deployment', 'kura-networking',
                'kura-wires', 'kura-cloud', 'kura-camel', 'kura-artemis', 'kura-container',
                'kura-triton', 'kura-management-ui', 'kura-yofc-runtime', 'yofc-iot',
                'kura-docker', 'plc4x-yofc']
NS = {'m': 'http://maven.apache.org/POM/4.0.0'}


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def coordinates(path):
    root = ET.parse(path).getroot()
    def value(name):
        return root.findtext('m:' + name, namespaces=NS)
    parent = root.find('m:parent', NS)
    properties = {}
    current = Path(path).resolve()
    visited = set()
    chain = []
    while current.is_file() and current not in visited:
        visited.add(current)
        model = ET.parse(current).getroot()
        chain.append(model)
        model_parent = model.find('m:parent', NS)
        if model_parent is None:
            break
        relative = model_parent.findtext('m:relativePath', default='../pom.xml', namespaces=NS)
        if not relative:
            break
        current = (current.parent / relative).resolve()
    for model in reversed(chain):
        element = model.find('m:properties', NS)
        if element is not None:
            properties.update({e.tag.split('}')[-1]: e.text or '' for e in element})
    group = value('groupId') or (parent.findtext('m:groupId', namespaces=NS) if parent is not None else None)
    version = value('version') or (parent.findtext('m:version', namespaces=NS) if parent is not None else None)
    for _ in range(10):
        if version:
            for key, replacement in properties.items():
                version = version.replace('${' + key + '}', replacement)
    return {'groupId': group, 'artifactId': value('artifactId'), 'version': version,
            'packaging': value('packaging') or 'jar'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--repository', type=Path, default=Path.home() / '.m2/repository')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'capturedAt': datetime.now(timezone.utc).isoformat(), 'repositories': [],
              'artifacts': [], 'missingArtifacts': [], 'validation': 'inventory only; no build/run implied'}
    for name in REPOSITORIES:
        repo = args.workspace / name
        item = {'name': name, 'revision': git(repo, 'rev-parse', 'HEAD'),
                'branch': git(repo, 'branch', '--show-current'), 'status': git(repo, 'status', '--porcelain'),
                'metadata': {}}
        files = git(repo, 'ls-files').splitlines()
        for relative in files:
            source = repo / relative
            if not source.is_file():
                continue
            if source.name in ('pom.xml', 'MANIFEST.MF', 'build.properties') or relative.endswith(('.target', '.launch')) or '/OSGI-INF/' in '/' + relative:
                item['metadata'][relative] = sha256(source)
                dest = args.output / 'sources' / name / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
            if source.name != 'pom.xml' or name == 'plc4x-yofc' or 'archetype-resources' in relative:
                continue
            gav = coordinates(source)
            if gav['packaging'] not in ('eclipse-plugin', 'eclipse-test-plugin', 'bundle'):
                continue
            aid, version, group = gav['artifactId'], gav['version'], gav['groupId']
            if not all((aid, version, group)) or '${' in version:
                continue
            jar = source.parent / 'target' / f'{aid}-{version}.jar'
            origin = 'target'
            if not jar.is_file():
                jar = args.repository / group.replace('.', '/') / aid / version / f'{aid}-{version}.jar'
                origin = 'local-repository'
            artifact = {'repo': name, 'module': str(source.parent.relative_to(repo)), **gav}
            if not jar.is_file():
                report['missingArtifacts'].append(artifact)
                continue
            dest = args.output / 'artifacts' / name / artifact['module'] / jar.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(jar, dest)
            artifact.update(inspect(jar))
            artifact['origin'] = origin
            artifact['baselinePath'] = str(dest.relative_to(args.output))
            report['artifacts'].append(artifact)
        report['repositories'].append(item)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    shutil.copy2(args.report, args.output / 'baseline.json')
    print(json.dumps({'repositories': len(report['repositories']), 'artifacts': len(report['artifacts']),
                      'missing': len(report['missingArtifacts']), 'archive': str(args.output)}))


if __name__ == '__main__':
    main()
