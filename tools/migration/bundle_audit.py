#!/usr/bin/env python3
"""Inventory/compare packaged bundles without resolving through PDE or Tycho."""
import argparse
import fnmatch
import hashlib
import json
import re
import zipfile
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def manifest(data):
    text = data.decode('utf-8').replace('\r\n', '\n')
    text = re.sub(r'\n ', '', text).split('\n\n', 1)[0]
    return dict(line.split(': ', 1) for line in text.splitlines() if ': ' in line)


def inspect(path):
    with zipfile.ZipFile(path) as jar:
        headers = manifest(jar.read('META-INF/MANIFEST.MF'))
        entries = {name: hashlib.sha256(jar.read(name)).hexdigest()
                   for name in sorted(jar.namelist()) if not name.endswith('/')}
        errors = []
        for entry in headers.get('Bundle-ClassPath', '.').split(','):
            entry = entry.strip().strip('"')
            if entry != '.' and entry not in entries and not any(
                    name.startswith(entry.rstrip('/') + '/') for name in entries):
                errors.append('Missing Bundle-ClassPath entry: ' + entry)
        for descriptor in headers.get('Service-Component', '').split(','):
            descriptor = descriptor.strip()
            if descriptor and not any(fnmatch.fnmatchcase(name, descriptor) for name in entries):
                errors.append('Missing Service-Component descriptor: ' + descriptor)
    return {'sha256': sha256(path), 'manifest': headers, 'entries': entries, 'errors': errors}


BUILD_HEADERS = {'Build-Jdk', 'Build-Jdk-Spec', 'Built-By', 'Created-By', 'Bnd-LastModified',
                 'Tool', 'Eclipse-SourceReferences', 'Originally-Created-By', 'Java-Version'}


def clauses(value, delimiter=','):
    return re.split(delimiter + r'(?=(?:[^"]*"[^"]*")*[^"]*$)', value)


def semantic_headers(headers):
    result = {k: v for k, v in headers.items() if k not in BUILD_HEADERS}
    if 'Bundle-Version' in result:
        result['Bundle-Version'] = '.'.join(result['Bundle-Version'].split('.')[:3])
    if result.get('Bundle-ClassPath', '.') == '.':
        result.pop('Bundle-ClassPath', None)
    for header in ('Import-Package', 'Export-Package'):
        if header in result:
            result[header] = ','.join(sorted(';'.join(part.strip() for part in clauses(item, ';'))
                                              for item in clauses(result[header])))
    return result


def compare(before, after):
    a, b = semantic_headers(before['manifest']), semantic_headers(after['manifest'])
    changes = {'headers': {key: [a.get(key), b.get(key)] for key in sorted(a.keys() | b.keys())
                           if a.get(key) != b.get(key)}, 'resources': {}}
    # Bytecode can differ between ECJ and javac; metadata, embedded jars and resources cannot.
    def resources(item):
        return {k: v for k, v in item['entries'].items()
                if not k.endswith('.class') and k != 'META-INF/MANIFEST.MF'
                and not k.startswith('META-INF/maven/')}
    a, b = resources(before), resources(after)
    changes['resources'] = {key: [a.get(key), b.get(key)] for key in sorted(a.keys() | b.keys())
                            if a.get(key) != b.get(key)}
    def named_classes(item):
        # javac and ECJ number anonymous implementation classes differently.
        return {name for name in item['entries'] if name.endswith('.class')
                and not re.search(r'\$\d+', name)}
    old_classes, new_classes = named_classes(before), named_classes(after)
    changes['classes'] = {'removed': sorted(old_classes - new_classes), 'added': sorted(new_classes - old_classes)}
    if not any(changes['classes'].values()):
        changes['classes'] = {}
    changes['errors'] = after['errors']
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('jar', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--qualifier', help='Require this exact qualifier in the packaged Bundle-Version')
    args = parser.parse_args()
    result = inspect(args.jar)
    if args.qualifier and result['manifest'].get('Bundle-Version', '').split('.', 3)[-1] != args.qualifier:
        result['errors'].append('Unexpected Bundle-Version qualifier: ' + result['manifest'].get('Bundle-Version', '<missing>'))
    if args.baseline:
        result = compare(inspect(args.baseline), result)
    text = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')
    if result.get('errors') or result.get('headers') or result.get('resources') or result.get('classes'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
