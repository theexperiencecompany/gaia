"""SSRF guards for HTTP(S) URLs; the single source of truth for SSRF policy.

assert_public_http_url resolves DNS off the loop and rejects any non-public
address; call it immediately before every outbound request so DNS rebinding
cannot slip past an earlier check (assert_public_http_url_sync for callers that
cannot await, assert_safe_url_shape as the non-resolving pre-check).
open_public_http_url applies the guard across a redirect chain.

assert_endpoint_url_allowed / assert_endpoint_url_shape guard an endpoint
someone configured on purpose (an MCP server, a model provider): the caller
passes allow_private from the deployment, and link-local and metadata
addresses and URLs carrying credentials stay refused regardless.
endpoint_http_client runs that check before every request it sends.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
import ipaddress
import socket

import httpx

from app.constants.search import MAX_HTTPX_REDIRECTS

#: The schemes of pages on the web, the only ones fetched or opened.
HTTP_SCHEMES = ("http", "https")

# Opens one hop and yields its response. Streaming or buffered is the caller's
# choice; ``client.stream("GET", url)`` is already this shape.
ResponseOpener = Callable[[str], AbstractAsyncContextManager[httpx.Response]]


def _parse_http_host_port(url: str) -> tuple[str, int]:
    # Parsed with httpx.URL — the same parser the outbound connection uses —
    # so the validated host can't diverge from the dialed host (a
    # parser-differential SSRF bypass).
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as e:
        raise ValueError(f"malformed URL: {e}") from e
    if parsed.scheme not in HTTP_SCHEMES:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.host
    if not host:
        raise ValueError("URL has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def http_origin(url: str) -> str:
    """Return url's origin as scheme://host:port, the port always written out.

    Parsed as the outbound connection parses it, so an allow-list compared on
    this string matches the host and port that are actually dialed.
    """
    host, port = _parse_http_host_port(url)
    scheme = httpx.URL(url).scheme
    return f"{scheme}://{f'[{host}]' if ':' in host else host}:{port}"


def _assert_ip_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    # ``is_global`` rejects private, loopback, link-local (incl.
    # 169.254.169.254), reserved, multicast, unspecified, CGNAT
    # (100.64.0.0/10) and benchmarking (198.18.0.0/15) ranges.
    if not ip.is_global:
        raise ValueError(f"refusing to connect to non-public address {ip}")


# Resolve to the metadata service; refused before any lookup so a sync shape check sees them.
_METADATA_HOSTNAMES = frozenset({"metadata.google.internal", "metadata"})


def _assert_ip_allowed(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address, *, allow_private: bool
) -> None:
    # An IPv4-mapped IPv6 address answers these as its IPv4 address does (3.12.4+).
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise ValueError(f"refusing to connect to link-local or reserved address {ip}")
    if not allow_private:
        _assert_ip_public(ip)


def _endpoint_host_port(url: str) -> tuple[str, int]:
    host, port = _parse_http_host_port(url)
    parsed = httpx.URL(url)
    if parsed.username or parsed.password:
        raise ValueError("URL must not embed credentials")
    if host.lower().rstrip(".") in _METADATA_HOSTNAMES:
        raise ValueError(f"refusing to connect to metadata host {host}")
    return host, port


def assert_endpoint_url_shape(url: str, *, allow_private: bool) -> None:
    """Sync, non-resolving check of a configured endpoint URL; raise ValueError when refused.

    Checks scheme, host, embedded credentials, metadata hostnames and literal IP
    hosts. Hostnames are resolved and checked by assert_endpoint_url_allowed.
    """
    host, _ = _endpoint_host_port(url)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    _assert_ip_allowed(ip, allow_private=allow_private)


async def assert_endpoint_url_allowed(url: str, *, allow_private: bool) -> None:
    """Raise ValueError unless url is an http(s) endpoint this process may dial.

    Every resolved address is checked: without allow_private all must be public;
    with it private, loopback and LAN addresses pass, link-local and metadata never.
    """
    host, port = _endpoint_host_port(url)
    try:
        addresses = await asyncio.to_thread(_resolve, host, port)
    except OSError as e:
        raise ValueError(f"DNS resolution failed: {e}") from e
    for address in addresses:
        _assert_ip_allowed(ipaddress.ip_address(address), allow_private=allow_private)


def endpoint_http_client(*, allow_private: bool) -> httpx.AsyncClient:
    """Return an AsyncClient that checks every request it sends, redirect hops included.

    For URLs a remote server hands back (OAuth metadata, a page's icon links).
    A refused URL raises ValueError before anything is dialed.
    """

    async def _guard(request: httpx.Request) -> None:
        await assert_endpoint_url_allowed(str(request.url), allow_private=allow_private)

    return httpx.AsyncClient(event_hooks={"request": [_guard]})


def _resolve(host: str, port: int) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def assert_safe_url_shape(url: str) -> None:
    """Cheap, non-resolving SSRF pre-check for sync contexts (pydantic validators).

    Rejects non-HTTP(S) schemes, missing host, and literal private/reserved IP
    hosts without a DNS lookup (which would block the event loop). Hostnames are
    resolved and re-checked on the async connect/probe path via
    assert_public_http_url.
    """
    host, _ = _parse_http_host_port(url)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # a hostname, not a literal IP — resolved and checked at connect time
    _assert_ip_public(ip)


def assert_public_http_url_sync(url: str) -> None:
    """Raise ValueError unless url is HTTP(S) and resolves only to public IPs.

    Blocking: the DNS lookup runs on the calling thread. Use this only from code
    that is already off the event loop; async callers want
    assert_public_http_url.
    """
    host, port = _parse_http_host_port(url)
    try:
        addresses = _resolve(host, port)
    except OSError as e:
        raise ValueError(f"DNS resolution failed: {e}") from e
    for address in addresses:
        _assert_ip_public(ipaddress.ip_address(address))


async def assert_public_http_url(url: str) -> None:
    """Raise ValueError unless url is HTTP(S) and resolves only to public IPs.

    Resolves DNS off the event loop via asyncio.to_thread.
    """
    await asyncio.to_thread(assert_public_http_url_sync, url)


@asynccontextmanager
async def open_public_http_url(
    url: str,
    open_response: ResponseOpener,
    *,
    max_redirects: int = MAX_HTTPX_REDIRECTS,
) -> AsyncIterator[httpx.Response]:
    """Yield the terminal response for url, re-checking the guard on every hop.

    httpx's own follow_redirects would dial a redirected-to internal address
    without re-validation, so the chain is walked by hand, once, here. Raises
    ValueError on a blocked hop, a broken redirect, or an over-long chain.
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
