#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Read-only observations for the new installed-Main/archive fixture only.

Run through docker exec with this source on stdin. The `before` stage saves a
private hash/stat baseline while Main and all operation journals are still empty.
No key bytes, backup passwords, cookies or HMAC secrets enter the report.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess


def identity(path):
    meta = path.stat()
    return dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), dev=meta.st_dev,
        ino=meta.st_ino, uid=meta.st_uid, gid=meta.st_gid, mode=meta.st_mode,
        size=meta.st_size, mtimeNs=meta.st_mtime_ns, ctimeNs=meta.st_ctime_ns)


def observe(stage):
    assert os.geteuid() == 0 and Path('/.dockerenv').exists()
    assert Path('/proc/1/comm').read_text().strip() == 'systemd'
    saved = Path('/run/kura-installed-main-archive-baseline.json')
    root = Path('/var/lib/kura-key-service')
    credentials = Path('/etc/kura/credentials')
    key = credentials / 'kura_encryption_key'
    assert key.stat().st_size == 32
    unit = subprocess.check_output(['systemctl', 'show', 'kura.service',
        '--property=MainPID', '--property=ControlPID', '--property=ExecMainStartTimestampMonotonic'], text=True)
    process = dict(row.split('=', 1) for row in unit.splitlines() if '=' in row)
    paths = list(credentials.iterdir()) + [root / 'journal.key']
    tls = Path('/etc/kura/recovery-tls')
    if tls.exists():
        paths += list(tls.iterdir())
    private = {str(path): identity(path) for path in paths if path.is_file()}
    journals = {}
    for name in ('operations', 'archives', 'startups'):
        directory = root / name
        journals[name] = {path.name: identity(path) for path in directory.iterdir() if path.is_file()} if directory.exists() else {}
    if stage == 'before':
        assert not saved.exists(), 'Never replace the original baseline'
        assert process == dict(MainPID='0', ControlPID='0', ExecMainStartTimestampMonotonic='0'), process
        assert not any(journals.values()), 'Never adopt an old key workflow'
        value = dict(private=private, journals=journals, main=process)
        fd = os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
        return dict(stage=stage, baselineCreated=True, privateFiles=len(private), main=process, journals=journals)
    baseline = json.loads(saved.read_bytes())
    assert private == baseline['private'], 'Canonical credentials/TLS/HMAC metadata changed'
    pid = int(process['MainPID'])
    assert pid > 1
    status = dict(row.split(':', 1) for row in Path('/proc', str(pid), 'status').read_text().splitlines() if ':' in row)
    assert list(map(int, status['Uid'].split())) == [pwd.getpwnam('kurad').pw_uid] * 4
    loaded = Path('/proc', str(pid), 'root/run/credentials/kura.service/kura_encryption_key')
    assert hashlib.sha256(loaded.read_bytes()).hexdigest() == private[str(key)]['sha256']
    result = dict(stage=stage, privateFilesUnchanged=len(private), canonicalAndLoadedKeyMatch=True,
        main=process, mainUid=pwd.getpwnam('kurad').pw_uid,
        capabilities={name: status[name].strip() for name in ('CapAmb', 'CapBnd', 'NoNewPrivs')},
        journals=journals, originalGatewayDataUsed=False)
    if stage == 'before-backup':
        assert not any(journals.values()), 'Read-only phase dispatched a native key operation'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('before', 'before-backup', 'after'), required=True)
    args = parser.parse_args()
    print(json.dumps(observe(args.stage), indent=2))
