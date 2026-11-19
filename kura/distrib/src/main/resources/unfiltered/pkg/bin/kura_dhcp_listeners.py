# SPDX-License-Identifier: EPL-2.0
"""Observe the kernel's UDP/67 ownership in the local network namespace."""
from ipaddress import IPv4Address, IPv6Address
import socket
import struct
import time
from typing import NamedTuple

from kura_clock_journal import require

NETLINK_SOCK_DIAG = 4
SOCK_DIAG_BY_FAMILY = 20
NLM_F_REQUEST = 1
NLM_F_DUMP = 0x300
NLM_F_DUMP_INTR = 0x10
NLMSG_DONE = 3
NETLINK_HEADER = struct.Struct('=IHHII')
ATTRIBUTE_HEADER = struct.Struct('=HH')
INET_DIAG_SKV6ONLY = 11
INET_DIAG_CGROUP_ID = 21
DHCP_PORT = 67
UNAVAILABLE = 'DHCP_SOCKET_OWNERSHIP_UNAVAILABLE'


class Listener(NamedTuple):
    interface: int
    address: IPv4Address
    cgroup: int | None


class Link(NamedTuple):
    interface: int
    addresses: frozenset[IPv4Address]
    master: int | None = None


def aligned(size):
    return (size + 3) & ~3


def listen_record(data, family):
    # inet_diag_msg is a 72-byte fixed header followed by NETLINK attributes.
    require(len(data) >= 72 and data[0] == family, UNAVAILABLE)
    if struct.unpack_from('!H', data, 4)[0] != DHCP_PORT:
        return None
    ifindex, = struct.unpack_from('=I', data, 40)
    cgroup = None
    v6_only = False
    offset = 72
    while offset < len(data):
        require(offset + ATTRIBUTE_HEADER.size <= len(data), UNAVAILABLE)
        length, kind = ATTRIBUTE_HEADER.unpack_from(data, offset)
        end = offset + aligned(length)
        require(ATTRIBUTE_HEADER.size <= length and end <= len(data), UNAVAILABLE)
        attribute = data[offset + ATTRIBUTE_HEADER.size:offset + length]
        if kind == INET_DIAG_CGROUP_ID:
            require(len(attribute) == 8 and cgroup is None, UNAVAILABLE)
            cgroup, = struct.unpack('=Q', attribute)
        if kind == INET_DIAG_SKV6ONLY:
            require(attribute in (b'\0', b'\1'), UNAVAILABLE)
            v6_only = attribute == b'\1'
        offset = end
    if family == socket.AF_INET6:
        address = IPv6Address(data[8:24])
        if v6_only or (not address.is_unspecified and address.ipv4_mapped is None):
            return None
        address = address.ipv4_mapped or IPv4Address(0)
    else:
        address = IPv4Address(data[8:12])
    return Listener(ifindex, address, cgroup)


def read_dump(stream, port_id, sequence, family, deadline):
    # inet_diag_req_v2 with all socket states and no address or device filter.
    request = struct.pack('=BBBBI', family, socket.IPPROTO_UDP, 0, 0, 0xffffffff) + bytes(48)
    header = NETLINK_HEADER.pack(NETLINK_HEADER.size + len(request), SOCK_DIAG_BY_FAMILY,
                                 NLM_F_REQUEST | NLM_F_DUMP, sequence, port_id)
    stream.sendto(header + request, (0, 0))
    total = 0
    result = []
    while True:
        remaining = deadline - time.monotonic()
        require(remaining > 0, UNAVAILABLE)
        stream.settimeout(remaining)
        data, _, flags, peer = stream.recvmsg(65536)
        total += len(data)
        require(peer == (0, 0) and not flags & socket.MSG_TRUNC and 0 < len(data)
                and total <= 2 * 1024 * 1024, UNAVAILABLE)
        offset = 0
        while offset < len(data):
            require(offset + NETLINK_HEADER.size <= len(data), UNAVAILABLE)
            length, kind, flags, reply_sequence, destination = NETLINK_HEADER.unpack_from(data, offset)
            end = offset + aligned(length)
            require(NETLINK_HEADER.size <= length and end <= len(data) and reply_sequence == sequence
                    and destination == port_id and not flags & NLM_F_DUMP_INTR, UNAVAILABLE)
            payload = data[offset + NETLINK_HEADER.size:offset + length]
            if kind == NLMSG_DONE:
                require(end == len(data) and (not payload or payload[:4] == bytes(4)), UNAVAILABLE)
                return result
            require(kind == SOCK_DIAG_BY_FAMILY, UNAVAILABLE)
            observed = listen_record(payload, family)
            if observed is not None:
                result.append(observed)
            offset = end


def snapshot():
    deadline = time.monotonic() + 2
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_SOCK_DIAG) as stream:
        stream.settimeout(2)
        stream.bind((0, 0))
        port_id, _ = stream.getsockname()
        return (read_dump(stream, port_id, 1, socket.AF_INET, deadline)
                + read_dump(stream, port_id, 2, socket.AF_INET6, deadline))


def overlaps(listener, links):
    if listener.interface:
        return any(listener.interface in (link.interface, link.master) for link in links)
    return (listener.address.is_unspecified or listener.address == IPv4Address('255.255.255.255')
            or any(listener.address in link.addresses for link in links))


def check(links, cgroup, *, ready=False):
    if not links:
        return
    local = []
    for listener in snapshot():
        if cgroup is not None and listener.cgroup == cgroup:
            local.append(listener.interface)
        else:
            require(not overlaps(listener, links), 'DHCP_PORT_IN_USE')
    if ready:
        require(cgroup is not None and sorted(local) == sorted(link.interface for link in links),
                'DHCP_SOCKET_OWNERSHIP_UNVERIFIED')
