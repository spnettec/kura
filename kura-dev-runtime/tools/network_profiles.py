"""Explicit network-owner selections shared by the collector and runtime assembler."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ('none', 'netplan')


def profile_spec(provider, root=ROOT):
    if provider not in PROVIDERS:
        raise ValueError('Supported network providers: none, netplan')
    spec = json.loads((root / 'runtime.json').read_text())
    properties = {}
    if provider != 'none':
        profiles = json.loads((root / 'network-providers.json').read_text())
        if profiles.get('schemaVersion') != 1:
            raise ValueError('Unsupported network profile schema')
        selection = profiles[provider]
        spec['bundles'] += selection['bundles']
        properties = selection['frameworkProperties']
        forbidden = set(selection['forbiddenSymbolicNames'])
        conflicts = sorted(forbidden.intersection(b['symbolicName'] for b in spec['bundles']))
        if conflicts:
            raise ValueError('Conflicting network writer bundles: ' + ', '.join(conflicts))
    names = [b['symbolicName'] for b in spec['bundles']]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate symbolic names in network profile')
    return spec, properties


def collection_spec(root=ROOT):
    """Collect all explicit variants without activating them in the default runtime."""
    spec, _ = profile_spec('none', root)
    known = {b['coordinates'] for b in spec['bundles']}
    for provider in PROVIDERS[1:]:
        selected, _ = profile_spec(provider, root)
        for bundle in selected['bundles']:
            if bundle['coordinates'] not in known:
                spec['bundles'].append(bundle)
                known.add(bundle['coordinates'])
    return spec
