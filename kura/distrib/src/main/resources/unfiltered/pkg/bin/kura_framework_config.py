#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Publish the installed Equinox configuration before starting a JVM."""
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys


def publish(home, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # All three launchers share this directory. Only the lock holder may
        # discard a previous process's incomplete configuration.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pending = directory / '.config.ini.pending'
        pending.unlink(missing_ok=True)
        try:
            fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as output:
                with (home / 'framework/config.ini').open('rb') as template:
                    shutil.copyfileobj(template, output)
                output.flush()
                # The independently paired loader appends its normal bundle
                # list. Template read errors above must reach the launcher.
                subprocess.run([home / 'bin/gen_config_ini.sh', os.devnull,
                                home / 'plugins', home / 'siblings'], stdout=output, check=True)
            os.replace(pending, directory / 'config.ini')
        finally:
            pending.unlink(missing_ok=True)
    finally:
        os.close(lock)


if __name__ == '__main__':
    try:
        publish(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(f'Cannot publish Equinox configuration: {error}')
