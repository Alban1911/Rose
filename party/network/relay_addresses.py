#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Addresses to reach the party relay at.

A network can block the relay at only some of its addresses: Spanish ISPs
drop whole Cloudflare IP ranges during LaLiga matches, while the relay's
other Cloudflare addresses keep working. The relay's hostname resolves to
several addresses, and every one of them serves it (Cloudflare routes by the
TLS server name), so Rose tries each in turn. When none of the addresses the
system resolver gives connects, it asks DNS-over-HTTPS resolvers too: a
stale DNS cache or an ISP resolver can hold only the blocked ones.
"""

import asyncio
import ipaddress
import json
import socket
import ssl
import urllib.parse
import urllib.request
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from utils.core.logging import get_logger

log = get_logger()

# JSON DNS-over-HTTPS endpoints, asked only when no system address connects
DOH_RESOLVERS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)
DOH_TIMEOUT = 4.0
_DOH_MAX_RESPONSE = 64 * 1024
_RECORD_TYPES = {"A": 1, "AAAA": 28}

# The address that last connected, per relay host and port: tried first next time
_preferred: Dict[Tuple[str, int], str] = {}


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _unique(addresses: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for address in addresses:
        if address not in seen:
            seen.add(address)
            result.append(address)
    return result


def preferred_address(host: str, port: int) -> Optional[str]:
    return _preferred.get((host, port))


def remember_address(host: str, port: int, address: str) -> None:
    _preferred[(host, port)] = address


def forget_address(host: str, port: int, address: str) -> None:
    if _preferred.get((host, port)) == address:
        del _preferred[(host, port)]


async def system_addresses(host: str, port: int) -> List[str]:
    """Addresses from the system resolver (hosts file included), in its order.
    Raises OSError (socket.gaierror) when the name does not resolve."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return _unique(info[4][0] for info in infos)


def _parse_doh_answer(payload: bytes, record_type: int) -> List[str]:
    """Global addresses of the given type in a JSON DNS answer.

    A blocking resolver can answer with 0.0.0.0, a loopback or a private
    address: none of those can be the relay."""
    try:
        answer = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return []
    if not isinstance(answer, dict) or answer.get("Status") != 0:
        return []
    records = answer.get("Answer")
    if not isinstance(records, list):
        return []
    addresses = []
    for record in records:
        if not isinstance(record, dict) or record.get("type") != record_type:
            continue
        data = record.get("data")
        if not isinstance(data, str):
            continue
        try:
            address = ipaddress.ip_address(data)
        except ValueError:
            continue
        if address.is_global:
            addresses.append(str(address))
    return addresses


def _doh_query(resolver: str, host: str, record: str, contexts: Sequence[ssl.SSLContext]) -> List[str]:
    query = urllib.parse.urlencode({"name": host, "type": record})
    request = urllib.request.Request(f"{resolver}?{query}", headers={"Accept": "application/dns-json"})
    error: Optional[BaseException] = None
    for context in contexts:
        try:
            with urllib.request.urlopen(request, timeout=DOH_TIMEOUT, context=context) as response:
                return _parse_doh_answer(response.read(_DOH_MAX_RESPONSE), _RECORD_TYPES[record])
        except ssl.SSLCertVerificationError as e:
            error = e
            continue  # try the next trust store
        except Exception as e:
            error = e
            break
    log.debug(f"[RELAY] DNS-over-HTTPS lookup at {resolver} failed: {error}")
    return []


async def doh_addresses(host: str, contexts: Sequence[ssl.SSLContext]) -> List[str]:
    """IPv4 then IPv6 addresses for host from every DoH resolver, merged."""
    queries = [(resolver, record) for record in ("A", "AAAA") for resolver in DOH_RESOLVERS]
    results = await asyncio.gather(
        *(asyncio.to_thread(_doh_query, resolver, host, record, contexts) for resolver, record in queries),
        return_exceptions=True,
    )
    addresses: List[str] = []
    for result in results:
        if isinstance(result, list):
            addresses.extend(result)
    return _unique(addresses)


async def open_socket(address: str, port: int, timeout: float) -> socket.socket:
    """A connected, non-blocking TCP socket to address. Raises OSError or
    asyncio.TimeoutError."""
    loop = asyncio.get_running_loop()
    family = socket.AF_INET6 if ipaddress.ip_address(address).version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.setblocking(False)
        await asyncio.wait_for(loop.sock_connect(sock, (address, port)), timeout)
    except BaseException:
        sock.close()
        raise
    return sock
