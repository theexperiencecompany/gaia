import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from fastapi import HTTPException, status
import httpx

from app.db.mongodb.collections import search_urls_collection
from app.db.redis import get_cache, set_cache
from app.db.utils import serialize_document
from app.models.search_models import URLResponse
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
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URL host resolves to an unsupported address.",
            )
        if _is_blocked_ip(ip):
            log.warning(
                "ssrf_blocked",
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


def is_valid_url(url: str) -> bool:
    """
    Lightweight sync validator used by non-fetch code paths. Only does shape/scheme
    checks — DNS-level SSRF protection happens in ``_validate_url_for_fetch``.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.hostname:
        return False
    return True


async def fetch_url_metadata(url: str) -> URLResponse:
    """Fetch metadata for a URL, with caching and database fallback."""
    log.set(url=url, operation="fetch_url_metadata")
    await _validate_url_for_fetch(url)

    cache_key = f"url_metadata:{url}"
    metadata = await get_cache(cache_key) or await search_urls_collection.find_one({"url": url})

    if metadata:
        return URLResponse(**metadata)

    metadata = await scrape_url_metadata(url)
    await search_urls_collection.insert_one(metadata)
    await set_cache(cache_key, serialize_document(metadata), 864000)

    return URLResponse(**metadata)


async def scrape_url_metadata(url: str) -> dict:
    try:
        current_url = url
        response: httpx.Response | None = None
        # Manual redirect following so each hop re-passes the SSRF guard
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=False) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                response = await client.get(current_url)
                if response.is_redirect:
                    next_location = response.headers.get("location")
                    if not next_location:
                        break
                    current_url = str(httpx.URL(current_url).join(next_location))
                    await _validate_url_for_fetch(current_url)
                    continue
                break
            else:
                log.debug("redirect_limit_exceeded", url=url)
                return _empty_metadata(url)

        if response is None:
            return _empty_metadata(url)

        response.raise_for_status()

        content = response.content[:_MAX_RESPONSE_BYTES]
        soup = BeautifulSoup(content, "html.parser")

        def to_absolute(relative_url: str) -> str | None:
            if not relative_url:
                return None
            parsed = urlparse(relative_url)
            if parsed.scheme in ["http", "https"]:
                return relative_url
            return urljoin(url, relative_url)

        def get_attr_value(tag, attr_name: str) -> str | None:
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

        title = soup.title.string.strip() if soup.title and soup.title.string else None

        description_tag = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", attrs={"property": "og:description"}
        )
        description = get_attr_value(description_tag, "content")

        website_name_tag = soup.find("meta", property="og:site_name") or soup.find(
            "meta", attrs={"name": "application-name"}
        )
        website_name = get_attr_value(website_name_tag, "content")

        # Find favicon with a more specific search
        favicon_tag = (
            soup.find("link", rel="icon")
            or soup.find("link", rel="shortcut icon")
            or soup.find("link", rel="apple-touch-icon")
        )
        favicon_href = get_attr_value(favicon_tag, "href")
        favicon = to_absolute(favicon_href) if favicon_href else None

        og_image_tag = soup.find("meta", property="og:image")
        og_image_content = get_attr_value(og_image_tag, "content")
        og_image = to_absolute(og_image_content) if og_image_content else None

        logo_tag = soup.find("meta", property="og:logo") or soup.find("link", rel="logo")
        website_image = None
        if logo_tag:
            logo_content = get_attr_value(logo_tag, "content")
            logo_href = get_attr_value(logo_tag, "href")
            logo_url = logo_content or logo_href
            if logo_url:
                website_image = to_absolute(logo_url)

        if not website_image:
            website_image = og_image

        return {
            "title": title,
            "description": description,
            "favicon": favicon or og_image,
            "website_name": website_name,
            "website_image": website_image,
            "url": url,
        }

    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        log.debug(f"Error fetching URL metadata: {exc}")
    except HTTPException:
        # Redirect chain tripped the SSRF guard — propagate
        raise
    except Exception as exc:
        log.debug(f"Unexpected error: {exc}")

    return _empty_metadata(url)


def _empty_metadata(url: str) -> dict:
    return {
        "title": None,
        "description": None,
        "favicon": None,
        "website_name": None,
        "website_image": None,
        "url": url,
    }
