# SPDX-License-Identifier: EPL-2.0
"""Check whether the paired Main's firewall provider can read the three kernel tables."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kura_ownership_markers as markers
from kura_clock_journal import require
from kura_journal_export import package_cohort as build_cohort
from kura_reboot_broker import ENVIRONMENT

NAME = 'kura-firewall-tables'
SOCKET = '/run/' + NAME + '.sock'
HOME = Path('/usr/libexec') / NAME
SOCKET_UNIT = NAME + '.socket'
SERVICE = NAME + '.service'
SOURCES = tuple(path for path in markers.SOURCES if path.startswith('bin/')) + (
    'bin/kura_firewall_tables.py', f'install/{SOCKET_UNIT}', f'install/{SERVICE}')
FAMILIES = {b'4': '/usr/sbin/iptables', b'6': '/usr/sbin/ip6tables'}
TABLES = ((b'F', 'filter'), (b'N', 'nat'), (b'M', 'mangle'))


def package_cohort(home):
    build_cohort(home, pair_directory=Path('libexec/firewall-tables'), sources=SOURCES)


def verify_actor():
    return markers.verify_actor(home=HOME, sources=SOURCES, socket_unit=SOCKET_UNIT,
                                service=SERVICE, capability=1 << 12)


def check_tables(family):
    require(family in FAMILIES, 'INVALID_REQUEST')
    # Only a status byte crosses the socket. Neither rules nor command arguments come from the caller.
    for failure, table in TABLES:
        result = subprocess.run([FAMILIES[family], '-t', table, '-S'], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENVIRONMENT,
                                timeout=1)
        if result.returncode:
            return failure
    return b'1'


if __name__ == '__main__':
    markers.serve(SOCKET, FAMILIES, verify_actor, check_tables)
