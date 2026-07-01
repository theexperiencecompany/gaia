"""SSRF guards for HTTP(S) URLs.

Server-side fetch/connect paths must not let a user-supplied URL reach loopback,
private, link-local (incl. cloud metadata 169.254.169.254), or otherwise reserved
addresses.

- ``assert_public_http_url`` is the full guard: it resolves DNS off the event
  loop and rejects any non-public address. Call it immediately before every
  outbound request (probe/connect/fetch) so DNS-rebinding can't slip an internal
  address past an earlier check.
- ``assert_safe_url_shape`` is a cheap synchronous pre-check for contexts that
  cannot await (pydantic validators). It rejects bad schemes, missing hosts, and
  literal private-IP hosts without a DNS lookup — the resolving check runs later
  on the async path.

This is the single source of truth for the SSRF allow/deny policy; the async
web-fetch guard delegates here rather than re-implementing the IP checks.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = ("http", "https")


def _parse_http_host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def _assert_ip_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise ValueError(f"refusing to connect to non-public address {ip}")


def _resolve(host: str, port: int) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def assert_safe_url_shape(url: str) -> None:
    """Cheap, non-resolving SSRF pre-check for sync contexts (pydantic validators).

    Rejects non-HTTP(S) schemes, missing host, and literal private/reserved IP
    hosts without a DNS lookup (which would block the event loop). Hostnames are
    resolved and re-checked on the async connect/probe path via
    ``assert_public_http_url``.
    """
    host, _ = _parse_http_host_port(url)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # a hostname, not a literal IP — resolved and checked at connect time
    _assert_ip_public(ip)


async def assert_public_http_url(url: str) -> None:
    """Raise ``ValueError`` unless ``url`` is HTTP(S) and resolves only to public IPs.

    Resolves DNS off the event loop via ``asyncio.to_thread``.
    """
    host, port = _parse_http_host_port(url)
    try:
        addresses = await asyncio.to_thread(_resolve, host, port)
    except OSError as e:
        raise ValueError(f"DNS resolution failed: {e}") from e
    for address in addresses:
        _assert_ip_public(ipaddress.ip_address(address))
