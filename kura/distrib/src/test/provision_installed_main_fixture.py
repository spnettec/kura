#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Install supplied Core/GWT debs once in a new, retained systemd fixture.

This does not run any crypto, restore, rotation or startup-lease acceptance.
The normal package provisioning creates this fixture's own new key. Main stays
stopped until the caller has reviewed installation and isolated the network.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('core', 'ui', 'results'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('core-sha256', 'ui-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--image', default='yofc-kura-main-archive-tests:ubuntu24.04')
    parser.add_argument('--extra-packages-manifest', type=Path,
                        help='Explicit inspected .deb path/SHA256 rows, installed with their real dependencies')
    parser.add_argument('--purpose', choices=('installed-main-archive', 'sibling-package-matrix'),
                        default='installed-main-archive')
    parser.add_argument('--disposable-fixture', action='store_true', required=True)
    args = parser.parse_args()
    output = args.results.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)

    def save(name, value):
        path = output / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')

    def command(argv, *, timeout=60, check=True):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError(str(argv[:4]) + ': ' + result.stderr[-2000:])
        return result

    packages = []
    for path, expected, target in ((args.core, args.core_sha256, '/candidate-core.deb'),
                                  (args.ui, args.ui_sha256, '/candidate-ui.deb')):
        path = path.resolve(strict=True)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('Package hash mismatch: ' + str(path))
        packages.append(dict(path=str(path), sha256=actual, target=target))
    if args.extra_packages_manifest:
        rows = json.loads(args.extra_packages_manifest.read_text())
        assert isinstance(rows, list) and 0 < len(rows) <= 16
        seen = {item['path'] for item in packages}
        for index, row in enumerate(rows):
            path = Path(row['path']).resolve(strict=True)
            assert path.suffix == '.deb' and str(path) not in seen
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            assert actual == row['sha256'], str(path)
            seen.add(str(path))
            packages.append(dict(path=str(path), sha256=actual,
                                 target='/candidate-addon-' + str(index) + '.deb'))
    name = 'yofc-' + args.purpose + '-' + uuid.uuid4().hex[:10]
    image = json.loads(command(['docker', 'image', 'inspect', args.image]).stdout)[0]
    argv = ['docker', 'run', '--detach', '--pull=never', '--name', name,
            '--label', 'yofc.purpose=' + args.purpose, '--privileged',
            '--cgroupns=private', '--memory=1536m', '--cpus=2',
            '--tmpfs', '/run:rw,nosuid,nodev,mode=755,size=96m',
            '--tmpfs', '/run/lock:rw,nosuid,nodev,mode=755,size=2m',
            '--env', 'PYTHONDONTWRITEBYTECODE=1']
    for package in packages:
        argv += ['--mount', 'type=bind,src=' + package['path'] + ',dst=' + package['target'] + ',readonly']
    argv += ['--entrypoint', '/bin/sh', args.image, '-c', 'mount --make-rshared /run && exec /sbin/init']
    cid = command(argv).stdout.strip()
    save('owned-fixture.json', dict(containerId=cid, name=name, imageId=image['Id'],
         packages=packages, adoptExistingForbidden=True, automaticReplayForbidden=True))
    print('OWNED_FIXTURE ' + cid, flush=True)
    for _ in range(40):
        if command(['docker', 'exec', cid, 'systemctl', 'show-environment'], check=False).returncode == 0:
            break
        time.sleep(0.5)
    else:
        raise RuntimeError('PID 1 not ready; retain original fixture')
    guard = """from pathlib import Path
import os
assert Path('/.dockerenv').exists()
assert Path('/proc/1/comm').read_text().strip() == 'systemd'
for value in ('/opt/eclipse/kura', '/etc/kura', '/var/lib/kura-key-service'):
 assert not os.path.lexists(value), 'Never adopt a previous environment'
p=Path('/usr/sbin/policy-rc.d');p.write_text('#!/bin/sh\\nexit 101\\n');p.chmod(0o755)
"""
    command(['docker', 'exec', cid, 'python3', '-B', '-c', guard])
    for label, install in (('apt-update', ['apt-get', 'update']),
                           ('apt-install', ['apt-get', '-y', '--no-install-recommends', 'install',
                            'openjdk-21-jre-headless', 'locales',
                            *[package['target'] for package in packages]])):
        with (output / (label + '.log')).open('xb') as log:
            result = subprocess.run(['docker', 'exec', '--env', 'DEBIAN_FRONTEND=noninteractive',
                '--env', 'LC_ALL=C', cid, *install], stdout=log, stderr=subprocess.STDOUT, timeout=900)
        if result.returncode:
            raise RuntimeError(label + ' failed; retain original fixture and inspect log')
        print(label + ' OK', flush=True)
    status = command(['docker', 'exec', cid, 'systemctl', 'show', 'kura.service',
        '--property=MainPID', '--property=ControlPID', '--property=ExecMainStartTimestampMonotonic']).stdout
    values = dict(row.split('=', 1) for row in status.splitlines() if '=' in row)
    assert values == dict(MainPID='0', ControlPID='0', ExecMainStartTimestampMonotonic='0'), values
    command(['docker', 'network', 'disconnect', 'bridge', cid])
    # Docker removes the container-IP hosts entry when disconnecting. Keep normal
    # local hostname resolution without restoring any external interface.
    command(['docker', 'exec', cid, 'python3', '-B', '-c',
        "from pathlib import Path;import socket;p=Path('/etc/hosts');p.write_text(p.read_text()+'\\n127.0.1.1 '+socket.gethostname()+'\\n')"])
    interfaces = json.loads(command(['docker', 'exec', cid, 'python3', '-B', '-c',
        "from pathlib import Path;import json;print(json.dumps(sorted(p.name for p in Path('/sys/class/net').iterdir())))"]).stdout)
    assert interfaces == ['lo'], interfaces
    save('installed.json', dict(containerId=cid, declaredDependenciesInstalled=True,
         mainStarts=0, explicitKeyRequests=0, modeledOriginalRows=0, interfaces=interfaces,
         next='Review installed package/key baseline before one explicit normal Main start'))
    print('INSTALLATION_READY ' + cid, flush=True)


if __name__ == '__main__':
    main()
