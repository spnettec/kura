#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh no-network Linux container only. Never invokes clock/key operations."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest import mock

assert sys.platform == 'linux' and os.geteuid() == 0 and Path('/.dockerenv').is_file()
assert not os.path.lexists('/opt/eclipse/kura') and not Path('/var/lib/kura-clock-broker').exists()
sys.path.insert(0, '/fixtures/payload/bin')
import kura_clock_broker as broker

home = Path('/opt/eclipse/kura')
target = home.parent / 'kura_6.0.0-SNAPSHOT_linux'
assert not target.exists()
home.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree('/fixtures/payload', target)
for path in [target, *target.rglob('*')]:
    assert not path.is_symlink()
    path.chmod(0o755 if path.is_dir() else 0o644)


def alias(value):
    if os.path.lexists(home):
        home.unlink()
    home.symlink_to(value, target_is_directory=True)


def accepted(label):
    broker.Policy().check(installed=False)
    print(label + ': PASS', flush=True)


def refused(label):
    try:
        broker.Policy().check(installed=False)
    except broker.Refused as error:
        assert error.reason == 'UNPAIRED_CODE'
        print(label + ': PASS', flush=True)
    else:
        raise AssertionError('Unpaired alias accepted: ' + label)


alias(str(target)); accepted('root-absolute-one-hop-alias')
alias(target.name); accepted('root-relative-one-hop-alias')
alias('/fixtures/unpaired'); refused('foreign-target')
alias(str(target)); os.lchown(home, 65534, 65534)
refused('non-root-alias'); os.lchown(home, 0, 0)
target.chmod(0o775); refused('writable-package-target'); target.chmod(0o755)
chain = home.parent / 'kura_chain_linux'; chain.symlink_to(target, target_is_directory=True)
alias(str(chain)); refused('chained-package-target')
alias(str(target))
original = target / 'bin/kura_clock_journal.py'
saved = target / 'bin/kura_clock_journal.saved'
original.rename(saved); original.symlink_to(saved.name)
refused('linked-code-leaf'); original.unlink(); saved.rename(original)

with mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as called:
    code = Path('/fixtures/clock-maintenance-guard.py').read_text()
    exec(compile(code, 'embedded-clock-guard', 'exec'), {'__name__': 'clock_guard_fixture'})
    called.assert_called_once()
    assert called.call_args.args[0] == ['/usr/bin/python3', '-I', '-B', '/opt/eclipse/kura/bin/kura_clock_setup.py', 'quiesce']
print('embedded-guard-validates-alias-before-fixed-quiesce: PASS', flush=True)
assert not Path('/var/lib/kura-clock-broker').exists()
print('No clock namespace, clock syscall or key operation created', flush=True)
