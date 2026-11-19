# SPDX-License-Identifier: EPL-2.0
"""Prepare and publish only the paired Debian BIND resolver configuration."""
import base64
from contextlib import contextmanager
import hashlib
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from kura_clock_journal import require, sync
from kura_modem_cohort import snapshot, stamp, protected

CONFIG = Path('/etc/bind/named.conf')
ENV_FILE = Path('/etc/default/named')
CHECKER = Path('/usr/bin/named-checkconf')
LIMIT = 8192
DUAL_STACK = 'enable-lan-dual'
ENABLE_MODES = ('enable', 'enable-lan', DUAL_STACK)
MODES = ('keep', 'disable', *ENABLE_MODES)
LOCAL_STUBS = ('127.0.0.1', '127.0.0.53', '127.0.0.54')
LAN_V6_RANGES = (IPv6Network('2000::/3'), IPv6Network('fc00::/7'))
INCLUDES = frozenset(('named.conf.options', 'named.conf.local', 'named.conf.root-hints', 'named.conf.default-zones'))


def typed_address(token, dual):
    if dual and re.fullmatch('[0-9a-f]{32}', token):
        address = IPv6Address(int(token, 16))
        require(address.ipv4_mapped is None, 'INVALID_BIND_CONFIGURATION')
        return address
    return IPv4Address(token)


def typed_prefix(token, dual):
    address, separator, length = token.partition('/')
    require(separator and re.fullmatch(r'0|[1-9][0-9]{0,2}', length), 'INVALID_BIND_CONFIGURATION')
    address = typed_address(address, dual)
    network_type = IPv6Network if address.version == 6 else IPv4Network
    network = network_type((address, int(length)), strict=False)
    if network.version == 6:
        require(any(network.subnet_of(scope) for scope in LAN_V6_RANGES), 'INVALID_BIND_CONFIGURATION')
    return str(network)


def decode_fields(value):
    require(len(value) <= 3500, 'INVALID_BIND_CONFIGURATION')
    fields = value.split(':')
    require(len(fields) == 4 and fields[0] == 'configure' and fields[1] in MODES, 'INVALID_BIND_CONFIGURATION')
    _, mode, forwarders, networks = fields
    addresses = forwarders.split(',') if forwarders else []
    prefixes = networks.split(',') if networks else []
    require(len(addresses) <= 16 and len(prefixes) <= 128, 'INVALID_BIND_CONFIGURATION')
    dual = mode == DUAL_STACK
    try:
        upstreams = {typed_address(address, dual) for address in addresses}
        addresses = sorted(map(str, upstreams))
        prefixes = sorted({typed_prefix(prefix, dual) for prefix in prefixes})
    except ValueError:
        require(False, 'INVALID_BIND_CONFIGURATION')
    require(mode not in ENABLE_MODES or (bool(addresses) and bool(prefixes)), 'INVALID_BIND_CONFIGURATION')
    if dual:
        require(all(not (address.is_unspecified or address.is_multicast
                         or (address.version == 6 and address.is_link_local))
                    for address in upstreams), 'INVALID_BIND_CONFIGURATION')
    if mode in ('enable-lan', DUAL_STACK) and any(address.is_loopback for address in upstreams):
        require(len(addresses) == 1 and addresses[0] in LOCAL_STUBS, 'INVALID_BIND_CONFIGURATION')
    return dict(mode=mode, forwarders=addresses, networks=prefixes)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def md5(raw):
    return hashlib.md5(raw, usedforsecurity=False).hexdigest()


def conffiles(environment):
    raw = subprocess.check_output(['/usr/bin/dpkg-query', '-W', '-f=${Conffiles}', 'bind9'],
                                  env=environment, timeout=4).decode('ascii')
    values = {}
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].startswith('/') and re.fullmatch('[0-9a-f]{32}', fields[1]):
            require(fields[0] not in values, 'UNPAIRED_BIND_CONFIGURATION')
            values[fields[0]] = fields[1]
    return values


def paired_content(path, files):
    data = snapshot(path, LIMIT, lambda stream: stream.read())
    require(files.get(str(path)) == md5(data), 'UNPAIRED_BIND_CONFIGURATION')
    return data


def get_includes(stock):
    statements = []
    for raw in stock.decode('ascii').splitlines():
        line = raw.strip()
        if not line or line.startswith('//'):
            continue
        match = re.fullmatch(r'include "/etc/bind/(named\.conf\.[a-z-]+)";', line)
        require(match and match[1] in INCLUDES and match[1] not in statements, 'UNSUPPORTED_BIND_STOCK_CONFIGURATION')
        statements.append(match[1])
    require('named.conf.options' in statements and 'named.conf.local' in statements,
            'UNSUPPORTED_BIND_STOCK_CONFIGURATION')
    return statements


def render(configuration, stock):
    includes = get_includes(stock)
    if configuration['mode'] == 'disable' or not (configuration['forwarders'] and configuration['networks']):
        return stock
    forwarders = ''.join(address + ';' for address in configuration['forwarders'])
    networks = ''.join(prefix + ';' for prefix in configuration['networks'])
    lan_only = configuration['mode'] in ('enable-lan', DUAL_STACK)
    listen = f'\tlisten-on {{!127.0.0.0/8;{networks}}};\n' if lan_only else ''
    listen_v6 = '\tlisten-on-v6 { none; };\n'
    if configuration['mode'] == DUAL_STACK:
        v4 = ''.join(prefix + ';' for prefix in configuration['networks'] if ':' not in prefix)
        v6 = ''.join(prefix + ';' for prefix in configuration['networks'] if ':' in prefix)
        listen = f'\tlisten-on {{!127.0.0.0/8;{v4}}};\n' if v4 else '\tlisten-on { none; };\n'
        if v6:
            listen_v6 = f'\tlisten-on-v6 {{!::1;{v6}}};\n'
    clients = '!localhost;' + networks if lan_only else networks
    template = (
        '// Managed by Kura through the paired BIND configuration broker.\n'
        'options {\n'
        '\tdirectory "/var/cache/bind";\n'
        '\tversion "not currently available";\n'
        f'{listen}'
        f'{listen_v6}'
        f'\tforwarders {{{forwarders}}};\n'
        '\tforward only;\n'
        '\tallow-transfer { none; };\n'
        f'\tallow-query {{{clients}}};\n'
        f'\tallow-recursion {{{clients}}};\n'
        f'\tallow-query-cache {{{clients}}};\n'
        '\trecursion yes;\n'
        '\tmax-cache-ttl 30;\n'
        '\tmax-ncache-ttl 30;\n'
        '\tdnssec-validation no;\n'
        '};\n'
    )
    return (template + ''.join(f'include "/etc/bind/{name}";\n' for name in includes
                               if name != 'named.conf.options')).encode('ascii')


def read_current():
    parent = protected(CONFIG.parent, directory=True)
    metadata = protected(CONFIG)
    require(parent.st_gid == metadata.st_gid and parent.st_mode & stat.S_ISGID
            and metadata.st_mode & 0o7000 == 0 and not os.listxattr(CONFIG, follow_symlinks=False),
            'UNPAIRED_BIND_CONFIGURATION')
    data = snapshot(CONFIG, LIMIT, lambda stream: stream.read())
    require(stamp(metadata) == stamp(CONFIG.lstat()), 'BIND_CONFIGURATION_CHANGED')
    return stamp(metadata), data


def paired_stock(raw, records, files):
    if not records:
        require(files.get(str(CONFIG)) == md5(raw), 'UNOWNED_BIND_CONFIGURATION')
        return raw
    stock = base64.b64decode(records[0]['stock'], validate=True)
    require(0 < len(stock) <= LIMIT and files.get(str(CONFIG)) == md5(stock), 'UNPAIRED_BIND_CONFIGURATION')
    original = sha(stock)
    previous = original
    for sequence, record in enumerate(records, 1):
        require(record['revision'] == sequence and record['before'] == previous and record['stockSha256'] == original,
                'UNPAIRED_BIND_CONFIGURATION_HISTORY')
        previous = record['published']
    require(sha(raw) == previous, 'UNOWNED_BIND_CONFIGURATION')
    return stock


def prepare(configuration, history, environment):
    files = conffiles(environment)
    launch = paired_content(ENV_FILE, files)
    # The supported Debian service must load the canonical file as user bind.
    options = [line.strip() for line in launch.splitlines() if line.strip().startswith(b'OPTIONS')]
    require(options == [b'OPTIONS="-u bind"'], 'UNPAIRED_BIND_CONFIGURATION')
    file_identity, raw = read_current()
    records = sorted((entry['publication'] for entry in history if 'publication' in entry),
                     key=lambda entry: entry['revision'])
    stock = paired_stock(raw, records, files)
    includes = get_includes(stock)
    for name in includes:
        # Preserve site zones. Only the replaced stock options must be
        # unmodified. Every retained include is protected from the caller.
        path = CONFIG.parent / name
        if name == 'named.conf.options':
            paired_content(path, files)
        else:
            protected(path)
    candidate = render(configuration, stock)
    require(0 < len(candidate) <= LIMIT, 'INVALID_BIND_CONFIGURATION')
    publication = dict(revision=len(records) + 1, before=sha(raw), published=sha(candidate), stockSha256=sha(stock))
    if not records:
        publication['stock'] = base64.b64encode(stock).decode('ascii')
    return file_identity, candidate, publication


def publication_identity(identity):
    # rename changes ctime. Device, inode, permissions and mtime still identify
    # the exact file fsynced and validated before the mutation was admitted.
    return [*identity[:-2], identity[-1]]


@contextmanager
def stage(expected, candidate, verify, environment):
    with tempfile.NamedTemporaryFile(dir=CONFIG.parent, prefix='.kura-bind-release-', delete=False) as stream:
        path = Path(stream.name)
        try:
            require(os.fstat(stream.fileno()).st_gid == expected[3], 'UNPAIRED_BIND_CONFIGURATION')
            os.fchmod(stream.fileno(), stat.S_IMODE(expected[4]))
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
            validated = stamp(os.fstat(stream.fileno()))
            verify()
            subprocess.run([str(CHECKER), '-z', str(path)], env=environment, check=True, timeout=8,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            require(stamp(path.lstat()) == validated, 'BIND_STAGING_CHANGED')
            yield path, publication_identity(validated)
        finally:
            path.unlink(missing_ok=True)


def publish(expected, candidate, staged, prepared):
    identity, current = read_current()
    require(identity == expected, 'BIND_CONFIGURATION_CHANGED')
    if candidate == current:
        return
    require(publication_identity(stamp(staged.lstat())) == prepared
            and snapshot(staged, LIMIT, lambda stream: stream.read()) == candidate, 'BIND_STAGING_CHANGED')
    os.replace(staged, CONFIG)
    sync(CONFIG.parent)
    require(published(prepared, sha(candidate)), 'BIND_CONFIGURATION_UNVERIFIED')


def published(expected, expected_sha):
    identity, contents = read_current()
    return publication_identity(identity) == expected and sha(contents) == expected_sha


def sync_publication():
    # Bytes were fsynced in the staged inode before rename. Ensure the file
    # name is durable as well if the original worker exited before that step.
    sync(CONFIG.parent)
