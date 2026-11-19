#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""The paired systemd ExecStop signals the original Main once, then waits."""
import os
from pathlib import Path
import pwd
import re
import select
import signal
import subprocess
import sys

GROUP = '0::/system.slice/kura.service\n'
PROPERTIES = ('Id', 'ControlPID', 'MainPID', 'ActiveState', 'ControlGroup')
STOP_TIMEOUT_MS = 40_000


def stop_state():
    raw = subprocess.check_output(
        ['/usr/bin/systemctl', '--system', '--no-ask-password', 'show', '--property=' + ','.join(PROPERTIES),
         'kura.service'],
        env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}, timeout=2, text=True)
    lines = raw.splitlines()
    if len(lines) != len(PROPERTIES):
        raise ValueError('Unpaired systemd stop observation')
    state = dict(line.split('=', 1) for line in lines)
    if (set(state) != set(PROPERTIES) or state['Id'] != 'kura.service'
            or state['ControlPID'] != str(os.getpid()) or state['ActiveState'] != 'deactivating'
            or state['ControlGroup'] != '/system.slice/kura.service'):
        raise ValueError('Caller is not the original Kura systemd stop process')
    return state


def stop_main(expected):
    account = pwd.getpwnam('kurad')
    if not (os.getuid() == os.geteuid() == account.pw_uid > 0
            and os.getgid() == os.getegid() == account.pw_gid > 0
            and Path('/proc/self/cgroup').read_text() == GROUP):
        raise ValueError('Unpaired Kura stop identity')
    main = stop_state()['MainPID']
    if main == '0':
        return
    if expected != main or re.fullmatch(r'[1-9][0-9]{0,9}', main) is None or main == '1':
        raise ValueError('The expected Kura Main process differs from systemd')
    pid = int(main)
    fd = os.pidfd_open(pid)
    try:
        proc = Path('/proc') / main
        if (proc.stat().st_uid != account.pw_uid or (proc / 'cgroup').read_text() != GROUP
                or stop_state()['MainPID'] != main):
            raise ValueError('The original Kura Main process changed')
        wait = select.poll()
        wait.register(fd, select.POLLIN)
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        if not any(events & select.POLLIN for _, events in wait.poll(STOP_TIMEOUT_MS)):
            raise TimeoutError('Kura OSGi shutdown timed out')
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('Expected the systemd Main PID')
        stop_main(sys.argv[1])
    except (OSError, KeyError, ValueError, subprocess.SubprocessError) as error:
        print('Kura Main graceful stop failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
