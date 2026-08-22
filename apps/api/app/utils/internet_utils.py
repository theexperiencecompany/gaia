import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag
from fastapi import HTTPException, status
import httpx

from app.constants.log_tags import LogTag
from app.db.redis import get_cache, set_cache
from app.db.repositories.search_urls import search_url_repository
from app.models.search_models import SearchUrlDocument, URLResponse
from shared.py.wide_events import log

# Cap scraped HTML to 2 MiB so a single URL cannot exhaust memory
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_MAX_REDIRECTS = 5

# Hostnames that always point at internal services — reject pre-DNS
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "broadcasthost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "metadata.packet.net",
        "instance-data",
    }
)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if the IP is anything other than a globally-routable address."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


async def _resolve_and_validate(hostname: str) -> None:
    """
    Resolve hostname via DNS and reject if any resolved address is not globally
    routable. This is the core SSRF guard — blocks RFC1918, loopback, link-local,
    multicast, IPv6 ULA, cloud metadata IPs, etc.
    """
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL host could not be resolved.",
        ) from exc

    if not infos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL host could not be resolved.",
        )

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URL host resolves to an unsupported address.",
            ) from e
        if _is_blocked_ip(ip):
            log.warning(
                f"{LogTag.TOOL} ssrf_blocked",
                hostname=hostname,
                resolved_ip=ip_str,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URL host is not allowed.",
            )


async def _validate_url_for_fetch(url: str) -> None:
    """
    SSRF guard. Raises HTTPException(400) on anything that could reach an
    internal service. Safe to call multiple times (e.g. per redirect hop).
    """
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL.",
        ) from exc

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only http(s) URLs are allowed.",
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL host is missing.",
        )

    hostname = hostname.lower()

    # Block hostnames that always map to internal resources
    if hostname in _BLOCKED_HOSTNAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL host is not allowed.",
        )

    # Single-label hostnames (e.g. "rabbitmq", "grafana") are docker service
    # DNS inside swarm networks — never valid for an external URL
    if "." not in hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL host is not a valid public domain.",
        )

    # Detect IP-literal hosts (including bracketed IPv6) and check directly —
    # skip the DNS step so the error message is consistent
    candidate = hostname[1:-1] if hostname.startswith("[") and hostname.endswith("]") else hostname
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        # Not an IP literal — resolve via DNS
        await _resolve_and_validate(hostname)
        return

    if _is_blocked_ip(ip):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL host is not allowed.",
        )


async def fetch_url_metadata(url: str) -> URLResponse:
    """Fetch metadata for a URL, with caching and database fallback."""
    log.set(url=url, operation="fetch_url_metadata")
    await _validate_url_for_fetch(url)

    cache_key = f"url_metadata:{url}"
    cached = await get_cache(cache_key)
    if cached:
        return URLResponse(**cached)

    stored = await search_url_repository.get_by_url(url)
    if stored is not None:
        return URLResponse(**stored.model_dump())

    metadata = await scrape_url_metadata(url)
    await search_url_repository.create(SearchUrlDocument(**metadata.model_dump()))
    await set_cache(cache_key, metadata.model_dump(), 864000)

    return metadata


def _attr_value(tag: Tag | NavigableString | None, attr_name: str) -> str | None:
    """Safely get attribute value from a BeautifulSoup tag."""
    if not tag or not hasattr(tag, "attrs"):
        return None
    if attr_name not in tag.attrs:
        return None
    attr_value = tag.attrs[attr_name]
    if isinstance(attr_value, str):
        return attr_value.strip()
    if isinstance(attr_value, list) and attr_value:
        return str(attr_value[0]).strip()
    return None


def _absolute_url(base_url: str, relative_url: str | None) -> str | None:
    if not relative_url:
        return None
    if urlparse(relative_url).scheme in ["http", "https"]:
        return relative_url
    return urljoin(base_url, relative_url)


async def _fetch_following_redirects(url: str) -> httpx.Response | None:
    """Fetch ``url``, following redirects by hand so every hop re-passes the SSRF
    guard. Returns None once the redirect budget is exhausted."""
    current_url = url
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            response = await client.get(current_url)
            if not response.is_redirect:
                return response
            next_location = response.headers.get("location")
            if not next_location:
                return response
            current_url = str(httpx.URL(current_url).join(next_location))
            await _validate_url_for_fetch(current_url)

    log.debug("redirect_limit_exceeded", url=url)
    return None


def _parse_url_metadata(url: str, content: bytes) -> URLResponse:
    soup = BeautifulSoup(content, "html.parser")

    description_tag = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    website_name_tag = soup.find("meta", property="og:site_name") or soup.find(
        "meta", attrs={"name": "application-name"}
    )
    favicon_tag = (
        soup.find("link", rel="icon")
        or soup.find("link", rel="shortcut icon")
        or soup.find("link", rel="apple-touch-icon")
    )
    logo_tag = soup.find("meta", property="og:logo") or soup.find("link", rel="logo")

    og_image = _absolute_url(url, _attr_value(soup.find("meta", property="og:image"), "content"))
    logo_url = _attr_value(logo_tag, "content") or _attr_value(logo_tag, "href")

    return URLResponse(
        title=soup.title.string.strip() if soup.title and soup.title.string else None,
        description=_attr_value(description_tag, "content"),
        favicon=_absolute_url(url, _attr_value(favicon_tag, "href")) or og_image,
        website_name=_attr_value(website_name_tag, "content"),
        website_image=_absolute_url(url, logo_url) or og_image,
        url=url,
    )


async def scrape_url_metadata(url: str) -> URLResponse:
    try:
        response = await _fetch_following_redirects(url)
        if response is None:
            return _empty_metadata(url)

        response.raise_for_status()
        return _parse_url_metadata(url, response.content[:_MAX_RESPONSE_BYTES])

    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        log.debug("Error fetching URL metadata", error=str(exc), error_type=type(exc).__name__)
    except HTTPException:
        # Redirect chain tripped the SSRF guard — propagate
        raise
    except Exception as exc:
        log.debug("Unexpected error", error=str(exc), error_type=type(exc).__name__)

    return _empty_metadata(url)


def _empty_metadata(url: str) -> URLResponse:
    return URLResponse(url=url)
