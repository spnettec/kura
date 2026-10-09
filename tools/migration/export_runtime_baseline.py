#!/usr/bin/env python3
"""One-time conversion of a known PDE config into a portable Maven runtime specification.

Only used to freeze migration evidence. Runtime assembly never calls this or reads PDE.
"""
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from capture_baseline import coordinates
from bundle_audit import manifest
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--repository', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    config = dict(line.split('=', 1) for line in args.config.read_text().replace('\\:', ':').splitlines()
                  if '=' in line and not line.startswith('#'))
    bundles = []
    for location in config['osgi.bundles'].split(','):
        url, _, suffix = location.partition('@')
        path = Path(url.removeprefix('reference:file:'))
        item = {'startLevel': int(suffix.split(':')[0]) if ':' in suffix else 5,
                'start': suffix.endswith('start')}
        if path.is_relative_to(args.repository):
            parts = path.relative_to(args.repository).parts
            group, artifact, version = '.'.join(parts[:-3]), parts[-3], parts[-2]
            classifier = parts[-1][len(artifact + '-' + version):-4].lstrip('-')
            item['coordinates'] = ':'.join([group, artifact, version] + ([classifier] if classifier else []))
            with zipfile.ZipFile(path) as jar:
                headers = manifest(jar.read('META-INF/MANIFEST.MF'))
        else:
            if path.name == 'classes' and path.parent.name == 'target':
                path = path.parent.parent
            gav = coordinates(path / 'pom.xml')
            item['coordinates'] = ':'.join(gav[key] for key in ('groupId', 'artifactId', 'version'))
            item['module'] = str(path.relative_to(args.workspace))
            mf = path / 'META-INF/MANIFEST.MF'
            if not mf.exists():
                mf = path / 'target/classes/META-INF/MANIFEST.MF'
            headers = manifest(mf.read_bytes())
        item['symbolicName'] = headers['Bundle-SymbolicName'].split(';')[0]
        if 'Fragment-Host' in headers:
            item['start'] = False
        bundles.append(item)
    spec = {'schemaVersion': 1, 'framework': 'org.eclipse.platform:org.eclipse.osgi:3.24.100',
            'launcher': 'org.eclipse.platform:org.eclipse.equinox.launcher:1.7.100',
            'defaultStartLevel': 5, 'frameworkStartLevel': 6,
            'bundles': sorted(bundles, key=lambda x: x['symbolicName'])}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(spec, indent=2) + '\n')
    print(f'Exported {len(bundles)} bundle coordinates')


if __name__ == '__main__':
    main()
