#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Build the private Linux worker from its locked Cargo source distribution."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

NAME = 'kura-firewall-policy-0.1.15'
SOURCE = Path(__file__).resolve().parent / 'src/firewall-policy' / (NAME + '.crate')
SHA = '70ca07cf1e6f5082d1d9ac385fe289ca2724d3103214b5772187e90f43015919'
REVISION = 'c09b059d29b3f6a4596a615b7a2e7014b210b165'
BINARY = 'kura-firewall-publish'
PLATFORMS = {'arm64': ('aarch64', 183), 'amd64': ('x86_64', 62)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(arch, target, offline):
    machine, elf = PLATFORMS[arch]
    if digest(SOURCE) != SHA:
        raise RuntimeError('Unexpected firewall worker source archive')
    target.mkdir(parents=True, exist_ok=True)
    worker = target / ('worker-' + arch)
    record = target / (worker.name + '.json')
    source = dict(source=SHA, revision=REVISION, architecture=arch, sourceVerifiedByExecutable=True)
    cache = Path(os.environ.get('KURA_NATIVE_BUILD_CACHE', Path.home() / '.cache/kura-native-build')).resolve()
    outputs = Path(os.environ.get('KURA_LINUX_CARGO_TARGET', cache)).resolve() / ('firewall-worker-' + arch)
    outputs.mkdir(parents=True, exist_ok=True)
    flags = ['build', '--release', '--locked', '--bin', BINARY]
    if offline:
        flags.append('--offline')
    with tempfile.TemporaryDirectory(dir=target) as temp:
        base = Path(temp)
        with tarfile.open(SOURCE) as archive:
            archive.extractall(base, filter='data')
        crate = base / NAME
        vcs = json.loads((crate / '.cargo_vcs_info.json').read_bytes())
        if vcs['git'] != {'sha1': REVISION} or vcs['path_in_vcs'] != 'crates/firewall-policy':
            raise RuntimeError('Unexpected firewall worker revision')
        # The maintainer hooks must remain executable after dpkg removes the installed worker.
        guard = target / 'package-maintenance.py'
        (crate / 'package-maintenance.py').replace(guard)
        if worker.is_file() and record.is_file() and json.loads(record.read_bytes()) == dict(source, sha256=digest(worker)):
            return
        native = platform.system() == 'Linux' and platform.machine() == machine and shutil.which('cargo')
        if native:
            subprocess.run(['cargo', *flags, '--target-dir', str(outputs)], cwd=crate, check=True,
                           env=dict(os.environ, KURA_FIREWALL_SOURCE_ARCHIVE_SHA256=SHA))
            identity = subprocess.check_output([outputs / 'release' / BINARY, '--build-source'], text=True)
        else:
            registry = Path(os.environ.get('KURA_LINUX_CARGO_HOME', cache / 'cargo')).resolve()
            registry.mkdir(parents=True, exist_ok=True)
            command = ['docker', 'run', '--rm', '--platform', 'linux/' + arch, '--read-only',
                       '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:exec',
                       '-v', f'{crate}:/src/{SHA}:ro', '-v', f'{registry}:/cache', '-v', f'{outputs}:/target',
                       '-w', '/src/' + SHA, '-e', 'KURA_FIREWALL_SOURCE_ARCHIVE_SHA256=' + SHA, '-e', 'CARGO_HOME=/cache', '-e', 'CARGO_TARGET_DIR=/target']
            if offline:
                command.extend(['--pull=never', '--network', 'none'])
            # Use the toolchain directly so changing CARGO_HOME does not run the rustup proxy.
            toolchain = '/usr/local/rustup/toolchains/1.95.0-' + machine + '-unknown-linux-gnu/bin'
            command.extend(['-e', 'PATH=' + toolchain + ':/usr/local/bin:/usr/bin:/bin', 'rust:1.95-bookworm'])
            subprocess.run([*command, toolchain + '/cargo', *flags], check=True)
            identity = subprocess.check_output([*command, '/target/release/' + BINARY, '--build-source'], text=True)
        if identity.strip() != SHA:
            raise RuntimeError('Cargo output does not match the firewall worker source archive')
        built = outputs / 'release' / BINARY
        staging = base / 'worker'
        shutil.copyfile(built, staging)
        staging.chmod(0o755)
        with staging.open('rb') as f:
            header = f.read(64)
        if header[:7] != b'\x7fELF\x02\x01\x01' or int.from_bytes(header[18:20], 'little') != elf:
            raise RuntimeError('Unexpected firewall worker architecture')
        staging.replace(worker)
        proof = base / 'provenance.json'
        proof.write_text(json.dumps(dict(source, sha256=digest(worker))) + '\n')
        proof.replace(record)


if __name__ == '__main__':
    build(sys.argv[1], Path(sys.argv[2]).resolve(), sys.argv[3].lower() == 'true')
