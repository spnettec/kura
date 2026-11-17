#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Run fresh JDK21 executor artifacts in new, isolated Linux containers only.

No Kura installation, runtime, credentials, original scene or network is mounted.
Containers and immutable receipts remain for inspection after each bounded run.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid


def command(arguments, timeout=30):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(json.dumps(dict(arguments=arguments, exitCode=result.returncode,
                                           stdout=result.stdout, stderr=result.stderr)))
    return result.stdout


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='Exact local sha256 image ID; never pulled')
    parser.add_argument('--jar', required=True, type=Path)
    parser.add_argument('--api-jar', required=True, type=Path)
    parser.add_argument('--classes', required=True, type=Path)
    parser.add_argument('--dependency', action='append', default=[], type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not args.image.startswith('sha256:') or len(args.image) != 71:
        parser.error('An immutable image ID is required')
    image = json.loads(command(['docker', 'image', 'inspect', args.image]))[0]
    if image['Id'] != args.image or image['Os'] != 'linux':
        parser.error('Exact Linux image not present locally')
    if not args.classes.is_dir() or any(not path.is_file() for path in [args.jar, args.api_jar, *args.dependency]):
        parser.error('Fresh compiled Core/API/classes and explicit dependencies are required')
    args.output.mkdir(parents=True, exist_ok=False)
    payload = args.output / 'payload'
    payload.mkdir()
    shutil.copytree(args.classes, payload / 'classes')
    libraries = payload / 'lib'
    libraries.mkdir()
    inputs = []
    for index, source in enumerate([args.jar, args.api_jar, *args.dependency]):
        target = libraries / f'{index:02d}-{source.name}'
        shutil.copyfile(source, target)
        inputs.append(dict(source=str(source.resolve()), sha256=digest(target)))
    for path in [payload, *payload.rglob('*')]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    cases = [
        ('same-user-cap0-nnp1', '65534:65534', True, [], True, 'nobody', None),
        ('same-user-spoofed-user-name', '65534:65534', True, [], True, 'nobody', 'root'),
        ('root-cap0-nnp1', '0:0', True, [], False, 'root', None),
        ('root-spoofed-user-name', '0:0', True, [], False, 'nobody', 'nobody'),
        ('same-user-nnp0', '65534:65534', False, [], False, 'nobody', None),
        ('same-user-nonzero-bounding', '65534:65534', True, ['--cap-add=NET_BIND_SERVICE'], False, 'nobody', None),
        ('same-user-root-supplementary-group', '65534:65534', True, ['--group-add=0'], False, 'nobody', None),
        ('different-target-user', '65534:65534', True, [], False, 'root', None),
    ]
    classes = [dict(path=str(path.relative_to(payload)), sha256=digest(path))
               for path in sorted((payload / 'classes').rglob('*')) if path.is_file()]
    write(args.output / 'intent.json', dict(image=args.image, architecture=image['Architecture'], inputs=inputs, classes=classes,
          scope='executor only; no Core/provider boot or deployment', cases=[case[0] for case in cases]))
    # Stage test-only files without starting a process, then freeze them in a
    # local immutable image before any read-only test container is created.
    staging = command(['docker', 'create', '--name', 'kura-executor-payload-' + str(uuid.uuid4()),
                       '--network=none', '--cap-drop=ALL', args.image, '/bin/true']).strip()
    write(args.output / 'payload-staging-created.json', dict(containerId=staging))
    command(['docker', 'cp', str(payload) + '/.', staging + ':/test'])
    observed = json.loads(command(['docker', 'inspect', staging]))[0]
    if observed['State']['Status'] != 'created' or observed['State']['Running']:
        raise RuntimeError('Payload staging container must never have run')
    payload_image = command(['docker', 'commit', staging]).strip()
    write(args.output / 'payload-image.json', dict(image=payload_image, baseImage=args.image,
          stagingContainer=staging, stagingStatus=observed['State']['Status']))
    receipts = []
    for name, user, nnp, options, admitted, username, spoof in cases:
        container_name = 'kura-unprivileged-executor-' + str(uuid.uuid4())
        create = ['docker', 'create', '--name', container_name, '--network=none', '--read-only',
                  '--memory=256m', '--pids-limit=128', '--cap-drop=ALL', '--user=' + user,
                  '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m', *options]
        if nnp:
            create.append('--security-opt=no-new-privileges')
        create += ['--entrypoint=/opt/java/openjdk/bin/java', payload_image, '-Xms16m', '-Xmx64m']
        if spoof is not None:
            create.append('-Duser.name=' + spoof)
        create += ['-cp', '/test/classes:/test/lib/*',
                   'org.eclipse.kura.core.internal.linux.executor.UnprivilegedExecutorLinuxProbe',
                   str(admitted).lower(), username, user.split(':')[0]]
        write(args.output / (name + '-intent.json'), dict(create=create, expectedAdmission=admitted))
        cid = command(create).strip()
        write(args.output / (name + '-created.json'), dict(containerId=cid, containerName=container_name))
        result = subprocess.run(['docker', 'start', '--attach', cid], capture_output=True, text=True, timeout=45)
        observed = json.loads(command(['docker', 'inspect', cid]))[0]
        receipt = dict(name=name, containerId=cid, cliExit=result.returncode, exitCode=observed['State']['ExitCode'],
                       running=observed['State']['Running'], stdout=result.stdout, stderr=result.stderr)
        write(args.output / (name + '-result.json'), receipt)
        if result.returncode != 0 or receipt['exitCode'] != 0 or receipt['running']:
            raise RuntimeError('Native executor case failed: ' + name)
        fields = dict(line.split(':', 1) for line in result.stdout.splitlines() if ':' in line)
        if int(fields['NoNewPrivs'].strip()) != int(nnp):
            raise RuntimeError('NNP fixture differs: ' + name)
        if name == 'same-user-nonzero-bounding' and int(fields['CapBnd'].strip(), 16) == 0:
            raise RuntimeError('Bounding-capability fixture did not apply')
        if name == 'same-user-root-supplementary-group' and '0' not in fields['Groups'].split():
            raise RuntimeError('Supplementary-group fixture did not apply')
        receipts.append(dict(name=name, containerId=cid, exitCode=receipt['exitCode']))
        print(name + ': PASS', flush=True)
    write(args.output / 'summary.json', dict(passed=len(receipts), failed=0, cases=receipts,
          scope='same-user executor admission and commands; not privileged broker or complete Core'))


if __name__ == '__main__':
    main()
