# SPDX-License-Identifier: EPL-2.0
"""Pair the installed Kura Main to one private, single-use Netfilter worker."""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kura_clock_broker import public_file
from kura_clock_journal import Refused, decode, encode, require
from kura_journal_export import package_cohort as build_cohort, paired_unit
from kura_ownership_markers import SOURCES as MARKER_SOURCES, verify_main
from kura_reboot_broker import ENVIRONMENT, proc_status, socket_peer, verify_identity

NAME = 'kura-firewall-publish'
HOME = Path('/usr/libexec') / NAME
SOCKET = NAME + '.socket'
ACTOR = NAME + '@.service'
WORKER = HOME / 'worker'
SOURCES = tuple(name for name in MARKER_SOURCES if name.startswith('bin/')) + (
    'bin/kura_firewall_publish.py', 'install/' + SOCKET, 'install/' + ACTOR)
MAX_REQUEST = 8 * 1024 * 1024
TOKEN = ('operationId', 'rootScope', 'requestSha256', 'wireSha256')


def package_cohort(home, worker, architecture):
    raw = worker.read_bytes()
    require(64 <= len(raw) <= MAX_REQUEST and raw[:7] == b'\x7fELF\x02\x01\x01'
            and int.from_bytes(raw[18:20], 'little') == {'arm64': 183, 'amd64': 62}[architecture],
            'WRONG_FIREWALL_WORKER_ARCHITECTURE')
    directory = Path('libexec/firewall-publish')
    build_cohort(home, pair_directory=directory, sources=SOURCES)
    manifest = home / directory / 'cohort.json'
    value = decode(manifest.read_bytes())
    value['files']['worker'] = hashlib.sha256(raw).hexdigest()
    manifest.write_bytes(encode(value) + b'\n')


def verify_actor(unit):
    require(re.fullmatch(r'kura-firewall-publish@[A-Za-z0-9_.:\\-]{1,128}\.service', unit),
            'UNPAIRED_FIREWALL_ACTOR')
    status = proc_status(os.getpid())
    verify_identity(status, 0, 0)
    require(status['NoNewPrivs'].strip() == '1' and all(int(status[field], 16) == 1 << 12
            for field in ('CapPrm', 'CapEff', 'CapBnd', 'CapAmb', 'CapInh')), 'UNPAIRED_FIREWALL_ACTOR')
    cohort = decode(public_file(HOME / 'cohort.json'))
    require(set(cohort) == {'schema', 'files', 'mainUnitSha256'} and type(cohort['schema']) is int
            and cohort['schema'] == 1 and re.fullmatch(r'[0-9a-f]{64}', cohort['mainUnitSha256'])
            and set(cohort['files']) == {Path(path).name for path in SOURCES} | {'worker'}, 'UNPAIRED_FIREWALL_ACTOR')
    for name, digest in cohort['files'].items():
        raw = public_file(HOME / name, MAX_REQUEST if name == 'worker' else 1024 * 1024)
        require(hashlib.sha256(raw).hexdigest() == digest, 'UNPAIRED_FIREWALL_ACTOR')
    paired_unit(SOCKET, SOCKET, cohort['files'][SOCKET])
    paired_unit(unit, ACTOR, cohort['files'][ACTOR])
    return cohort['mainUnitSha256']


def frame(stream, maximum):
    deadline = time.monotonic() + 10

    def read(size):
        data = bytearray()
        while len(data) < size:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'INVALID_FIREWALL_FRAME')
            stream.settimeout(remaining)
            part = stream.recv(size - len(data))
            require(part, 'INVALID_FIREWALL_FRAME')
            data.extend(part)
        return bytes(data)

    size, = struct.unpack('>I', read(4))
    require(0 < size <= maximum, 'INVALID_FIREWALL_FRAME')
    raw = read(size)
    require(b'\n' not in raw and b'\r' not in raw, 'INVALID_FIREWALL_FRAME')
    return raw


def send(stream, value):
    raw = encode(value)
    stream.settimeout(3)
    stream.sendall(struct.pack('>I', len(raw)) + raw)


def worker_reply(worker):
    raw = worker.stdout.readline(2 * 1024 * 1024 + 1)
    require(0 < len(raw) <= 2 * 1024 * 1024 and raw.endswith(b'\n'), 'NO_FIREWALL_RESULT')
    value = json.loads(raw)
    require(type(value) is dict, 'INVALID_FIREWALL_RESULT')
    # The original kernel ACK is kept in the Root journal.
    value.pop('ack', None)
    return value


def serve(stream, unit):
    require(stream.family == socket.AF_UNIX and stream.type == socket.SOCK_STREAM
            and stream.getsockname() == '/run/' + NAME + '.sock', 'UNPAIRED_FIREWALL_SOCKET')
    main = verify_actor(unit)
    with socket_peer(stream) as peer:
        verify_main(peer, main)
        request = frame(stream, MAX_REQUEST)
        with subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=ENVIRONMENT) as worker:
            try:
                worker.stdin.write(request + b'\n')
                worker.stdin.flush()
                value = worker_reply(worker)
                if value.get('state') == 'PREPARED':
                    require(value['requestSha256'] == hashlib.sha256(request).hexdigest(), 'UNPAIRED_FIREWALL_PLAN')
                    token = {key: value[key] for key in TOKEN}
                    send(stream, value)
                    require(decode(frame(stream, 1024)) == token, 'INVALID_FIREWALL_APPROVAL')
                    verify_main(peer, main)
                    worker.stdin.write(encode(token) + b'\n')
                    worker.stdin.flush()
                    value = worker_reply(worker)
                require(value.get('state') in {'SCOPE', 'UNKNOWN', 'NOT_FOUND', 'APPLIED', 'REJECTED', 'UNCHANGED'},
                        'INVALID_FIREWALL_RESULT')
                worker.stdin.close()
                require(worker.wait(timeout=3) == 0, 'NO_FIREWALL_RESULT')
                send(stream, value)
            finally:
                if worker.poll() is None:
                    worker.kill()


def main():
    try:
        require(len(sys.argv) == 2, 'UNPAIRED_FIREWALL_ACTOR')
        with socket.socket(fileno=0) as stream:
            serve(stream, sys.argv[1])
    # An incomplete response still requires original-ID reconciliation. Close
    # the connection and keep routine refusals inside the service memory limit.
    except Refused as error:
        print(f'Kura firewall publication refused: {error.reason}', file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('Kura firewall publication failed: transport or invalid reply', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
