# SPDX-License-Identifier: EPL-2.0
"""Validate the Kura IPv4 DHCP model and render only fixed dnsmasq directives."""
from ipaddress import IPv4Address, IPv4Network
import re

from kura_clock_journal import Refused, require

DEFAULT = b'# Kura managed DHCP.\nport=0\nbind-dynamic\nno-resolv\nno-hosts\n'
LIMIT = 16384


def parse(value):
    require(len(value) <= 7800, 'INVALID_DHCP_CONFIGURATION')
    rows = value.split(';') if value else []
    require(len(rows) <= 48, 'INVALID_DHCP_CONFIGURATION')
    records = []
    seen = set()
    networks = []
    for row in rows:
        fields = row.split(',')
        require(len(fields) == 8, 'INVALID_DHCP_CONFIGURATION')
        name, host, prefix, lower, upper, router, lease, dns = fields
        require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,14}', name) and name != 'lo'
                and name not in seen and re.fullmatch(r'(?:[1-9]|[12][0-9]|30)', prefix)
                and re.fullmatch(r'[1-9][0-9]{0,9}', lease) and 120 <= int(lease) <= 2147483647
                and dns in ('0', '1'), 'INVALID_DHCP_CONFIGURATION')
        try:
            host, lower, upper = map(IPv4Address, (host, lower, upper))
            mask = int(prefix)
            network = IPv4Network((host, mask), strict=False)
            gateway = IPv4Address(router) if router else None
        except ValueError as error:
            raise Refused('INVALID_DHCP_CONFIGURATION') from error
        minimum, maximum = network.network_address, network.broadcast_address
        require(minimum < lower <= upper < maximum and minimum < host < maximum and not lower <= host <= upper
                and (gateway is None or (minimum < gateway < maximum and not lower <= gateway <= upper))
                and (dns == '0' or gateway is not None)
                and not any(network.overlaps(prior) for prior in networks), 'INVALID_DHCP_CONFIGURATION')
        seen.add(name)
        networks.append(network)
        records.append(dict(interface=name, address=str(host), prefix=mask, start=str(lower), end=str(upper),
                            router=str(gateway) if gateway else '', leaseSeconds=int(lease), passDns=dns == '1'))
    return sorted(records, key=lambda item: item['interface'])


def render(records):
    lines = []
    for item in records:
        name = item['interface']
        # The interface tag is set by dnsmasq. Match it before allocating
        # from this pool, including when a request arrives via another link.
        prefix = f'tag:{name}'
        mask = IPv4Network('0.0.0.0/' + str(item['prefix'])).netmask
        router = ',' + item['router'] if item['router'] else ''
        dns = ',' + item['address'] if item['passDns'] else ''
        lines.extend((f'interface={name}',
                      f"dhcp-range={prefix},set:{name},{item['start']},{item['end']},{mask},{item['leaseSeconds']}s",
                      f'dhcp-option={prefix},1,{mask}',
                      f'dhcp-option={prefix},3{router}',
                      f'dhcp-option={prefix},6{dns}',
                      f'dhcp-option={prefix},27,1'))
        if not item['passDns']:
            lines.append(f'dhcp-ignore-names={prefix}')
    body = DEFAULT + ''.join(line + '\n' for line in lines).encode('ascii')
    require(len(body) <= LIMIT, 'INVALID_DHCP_CONFIGURATION')
    return body
