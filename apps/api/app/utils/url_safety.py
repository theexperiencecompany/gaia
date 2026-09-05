"""SSRF guards for HTTP(S) URLs.

Server-side fetch/connect paths must not let a user-supplied URL reach loopback,
private, link-local (incl. cloud metadata 169.254.169.254), or otherwise reserved
addresses.

- ``assert_public_http_url`` is the full guard: it resolves DNS off the event
  loop and rejects any non-public address. Call it immediately before every
  outbound request (probe/connect/fetch) so DNS-rebinding can't slip an internal
  address past an earlier check. ``assert_public_http_url_sync`` is the same
  policy for call sites that already run off the loop and cannot await
  (Composio's synchronous hook chain).
- ``assert_safe_url_shape`` is a cheap synchronous pre-check for contexts that
  cannot await (pydantic validators). It rejects bad schemes, missing hosts, and
  literal private-IP hosts without a DNS lookup — the resolving check runs later
  on the async path.
- ``open_public_http_url`` applies the guard across a redirect chain, which is
  what every outbound fetch in the app actually needs.

This is the single source of truth for the SSRF allow/deny policy; the async
web-fetch guard delegates here rather than re-implementing the IP checks.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
import ipaddress
import socket

import httpx

from app.constants.search import MAX_HTTPX_REDIRECTS

_ALLOWED_SCHEMES = ("http", "https")

# Opens one hop and yields its response. Streaming or buffered is the caller's
# choice; ``client.stream("GET", url)`` is already this shape.
ResponseOpener = Callable[[str], AbstractAsyncContextManager[httpx.Response]]


def _parse_http_host_port(url: str) -> tuple[str, int]:
    # Parse with httpx.URL — the same parser the outbound httpx connection uses —
    # so the host we validate can't diverge from the host that's actually dialed
    # (parser-differential SSRF bypass). It also rejects malformed URLs that
    # urllib.parse silently accepts.
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as e:
        raise ValueError(f"malformed URL: {e}") from e
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.host
    if not host:
        raise ValueError("URL has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def _assert_ip_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    # ``is_global`` is the stdlib's single source of truth for "publicly
    # routable". It rejects private, loopback, link-local (incl. the cloud
    # metadata address 169.254.169.254), reserved, multicast and unspecified
    # ranges — plus ones an explicit list is easy to forget: CGNAT
    # (100.64.0.0/10) and benchmarking (198.18.0.0/15).
    if not ip.is_global:
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


def assert_public_http_url_sync(url: str) -> None:
    """Raise ``ValueError`` unless ``url`` is HTTP(S) and resolves only to public IPs.

    Blocking: the DNS lookup runs on the calling thread. Use this only from code
    that is already off the event loop; async callers want
    ``assert_public_http_url``.
    """
    host, port = _parse_http_host_port(url)
    try:
        addresses = _resolve(host, port)
    except OSError as e:
        raise ValueError(f"DNS resolution failed: {e}") from e
    for address in addresses:
        _assert_ip_public(ipaddress.ip_address(address))


async def assert_public_http_url(url: str) -> None:
    """Raise ``ValueError`` unless ``url`` is HTTP(S) and resolves only to public IPs.

    Resolves DNS off the event loop via ``asyncio.to_thread``.
    """
    await asyncio.to_thread(assert_public_http_url_sync, url)


@asynccontextmanager
async def open_public_http_url(
    url: str,
    open_response: ResponseOpener,
    *,
    max_redirects: int = MAX_HTTPX_REDIRECTS,
) -> AsyncIterator[httpx.Response]:
    """Yield the terminal response for ``url``, re-checking the guard on every hop.

    httpx's own ``follow_redirects`` would dial a redirected-to internal address
    without re-validation, so the chain is walked by hand — here, once, rather than
    in each fetch path. The terminal response is yielded inside ``open_response``'s
    context so a streamed body is still open to the caller.

    Raises ``ValueError`` on a blocked hop, a broken redirect, or an over-long
    chain; callers translate it to their own error type.
    """
    for _ in range(max_redirects + 1):
        await assert_public_http_url(url)
        async with open_response(url) as response:
            if not response.is_redirect:
                yield response
                return
            location = response.headers.get("location")
            if not location:
                raise ValueError(f"redirect missing location header for {url}")
            url = str(response.url.join(location))
    raise ValueError(f"too many redirects fetching {url}")
