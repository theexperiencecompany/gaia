import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from shared.py.wide_events import log
from app.db.mongodb.collections import search_urls_collection
from app.db.redis import get_cache, set_cache
from app.db.utils import serialize_document
from app.models.search_models import URLResponse
from bs4 import BeautifulSoup
from fastapi import HTTPException

# SSRF hardening: reject URLs whose DNS resolution points to these address
# classes. Without this, an authenticated user can point the metadata fetcher
# at AWS/GCP metadata endpoints, localhost services, or RFC 1918 networks.
_BLOCKED_IP_ATTRS = (
    "is_private",
    "is_loopback",
    "is_link_local",
    "is_multicast",
    "is_reserved",
    "is_unspecified",
)

# Cap scraped body to avoid OOM on a malicious target returning gigabytes.
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
# Follow at most this many redirects so we can re-check each hop.
_MAX_REDIRECTS = 5
_REQUEST_TIMEOUT_SECONDS = 10.0


def _is_public_address(host: str) -> bool:
    """Return True iff every resolved IP for ``host`` is public."""
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    seen = False
    for info in addr_infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if any(getattr(ip, attr) for attr in _BLOCKED_IP_ATTRS):
            return False
        seen = True
    return seen


def _validate_external_url(url: str) -> None:
    """Raise HTTPException unless ``url`` is safe to fetch.

    Blocks non-http(s) schemes, IP literals that resolve to private ranges,
    and hostnames whose DNS points at loopback / link-local / metadata IPs.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid URL") from None

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http/https URLs allowed")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="URL missing host")

    host = parsed.hostname
    # IP literals (v4, v6, bracketed) — reject anything private/loopback/etc.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if any(getattr(ip, attr) for attr in _BLOCKED_IP_ATTRS):
            raise HTTPException(status_code=400, detail="URL resolves to a blocked IP")
        return

    if not _is_public_address(host):
        raise HTTPException(status_code=400, detail="URL resolves to a blocked host")


def is_valid_url(url: str) -> bool:
    """
    Validate if a URL is well-formed, uses http(s), and resolves to a public IP.
    """
    try:
        _validate_external_url(url)
        return True
    except HTTPException as exc:
        log.warning("URL rejected by SSRF filter", url=url, reason=exc.detail)
        return False
    except Exception:
        return False


async def fetch_url_metadata(url: str) -> URLResponse:
    """Fetch metadata for a URL, with caching and database fallback."""
    log.set(url=url, operation="fetch_url_metadata")
    _validate_external_url(url)

    cache_key = f"url_metadata:{url}"
    metadata = await get_cache(cache_key) or await search_urls_collection.find_one(
        {"url": url}
    )

    if metadata:
        return URLResponse(**metadata)

    metadata = await scrape_url_metadata(url)
    await search_urls_collection.insert_one(metadata)
    await set_cache(cache_key, serialize_document(metadata), 864000)

    return URLResponse(**metadata)


async def _safe_get(url: str) -> httpx.Response:
    """Fetch ``url`` following redirects manually, re-validating each hop.

    This defeats a redirect from a public host to a private one, and keeps
    DNS resolution in our hands so `_is_public_address` actually applies.
    """
    current = url
    async with httpx.AsyncClient(
        timeout=_REQUEST_TIMEOUT_SECONDS, follow_redirects=False
    ) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            _validate_external_url(current)
            response = await client.get(current)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return response
                current = urljoin(current, location)
                continue
            return response
    raise HTTPException(status_code=400, detail="Too many redirects")


async def scrape_url_metadata(url: str) -> dict:
    try:
        response = await _safe_get(url)
        response.raise_for_status()

        # Cap the body we parse to avoid OOM from a hostile upstream.
        raw = response.content[:_MAX_RESPONSE_BYTES]
        soup = BeautifulSoup(raw, "html.parser")

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
            elif isinstance(attr_value, list) and attr_value:
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

        logo_tag = soup.find("meta", property="og:logo") or soup.find(
            "link", rel="logo"
        )
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

    except HTTPException:
        raise
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        log.debug(f"Error fetching URL metadata: {exc}")
    except Exception as exc:
        log.debug(f"Unexpected error: {exc}")

    return {
        "title": None,
        "description": None,
        "favicon": None,
        "website_name": None,
        "website_image": None,
        "url": url,
    }
