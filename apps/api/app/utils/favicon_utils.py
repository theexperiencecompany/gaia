"""
Favicon fetching utilities with Redis caching.

Resolution (per full host, cached in Redis by host):
1. Smithery hosts: the Smithery registry's per-server iconUrl.
2. The host's explicit <link rel="icon">.
3. Google's favicon service for the registered domain (default fallback).

Each override is HEAD-validated to be a live image before use, so a server never
loses its working icon to a broken or missing one.
"""

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx
import tldextract

from app.constants.cache import FAVICON_CACHE_TTL
from app.constants.log_tags import LogTag
from app.db.redis import get_cache, set_cache
from shared.py.wide_events import log

# HTTP client settings
HTTP_TIMEOUT = 3.0

# Present a normal browser UA — several hosts (e.g. the Smithery API) reject
# default library user agents with a 403.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Google Favicon Service - fast and reliable
GOOGLE_FAVICON_URL = "https://www.google.com/s2/favicons?domain={domain}&sz=256"

# Smithery hosts every server under one host but the Smithery registry exposes a
# per-server icon (its source varies: a CDN logo, a Google S2 favicon, or a
# Smithery-hosted image), so resolve that instead of the shared host favicon.
SMITHERY_SUFFIX = "smithery.ai"
SMITHERY_REGISTRY_URL = "https://registry.smithery.ai/servers/{qualified_name}"
SMITHERY_TRANSPORT_SUFFIXES = ("/mcp", "/sse", "/stdio")


def _get_host_url(server_url: str) -> str:
    """Scheme + full host (subdomain included), e.g. 'https://whoop.run.mcp-use.com'.

    MCP servers commonly live on a subdomain and serve their own icon there, so
    favicon resolution keys off the full host rather than the registered domain.
    """
    parsed = urlparse(server_url if "://" in server_url else f"https://{server_url}")
    scheme = parsed.scheme or "https"
    return f"{scheme}://{parsed.netloc}"


def _get_domain_cache_key(server_url: str) -> str:
    """Cache key by scheme + full host so each MCP server resolves its own icon."""
    return f"favicon:{_get_host_url(server_url)}"


def _smithery_qualified_name(server_url: str) -> str | None:
    """Smithery server qualified name from its URL, or None if not a Smithery host.

    URLs look like ``https://server.smithery.ai/@owner/name`` or a bare ``/slug``,
    optionally with a transport suffix (``/mcp``, ``/sse``, ``/stdio``).
    """
    parsed = urlparse(server_url if "://" in server_url else f"https://{server_url}")
    hostname = parsed.hostname or ""
    if hostname != SMITHERY_SUFFIX and not hostname.endswith(f".{SMITHERY_SUFFIX}"):
        return None
    qualified_name = parsed.path.strip("/")
    for suffix in SMITHERY_TRANSPORT_SUFFIXES:
        qualified_name = qualified_name.removesuffix(suffix)
    return qualified_name or None


async def _fetch_smithery_icon(server_url: str) -> str | None:
    """The Smithery registry's authoritative per-server iconUrl, or None.

    The icon source varies per server (a CDN logo, a Google S2 favicon, or a
    Smithery-hosted image), so we use whatever the registry reports rather than
    constructing a URL.
    """
    qualified_name = _smithery_qualified_name(server_url)
    if not qualified_name:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": BROWSER_UA}
        ) as client:
            response = await client.get(
                SMITHERY_REGISTRY_URL.format(qualified_name=qualified_name),
                follow_redirects=True,
            )
            if response.status_code != 200:
                return None
            icon_url = response.json().get("iconUrl")
            return icon_url if isinstance(icon_url, str) and icon_url else None
    except Exception as e:
        log.debug(f"Smithery icon lookup failed for {qualified_name}: {e}")
        return None


def legacy_favicon_url(server_url: str) -> str:
    """Google's favicon service keyed by the registered domain (the default fallback)."""
    extracted = tldextract.extract(server_url)
    return GOOGLE_FAVICON_URL.format(domain=extracted.top_domain_under_public_suffix)


def _make_absolute_url(href: str, base_url: str) -> str:
    """Convert relative URL to absolute."""
    if href.startswith("data:"):
        return ""
    return urljoin(base_url, href)


def _parse_favicon_size(sizes_attr: str) -> int:
    """Extract largest dimension from sizes attribute."""
    if not sizes_attr:
        return 0
    max_size = 0
    for size in sizes_attr.split():
        if "x" in size.lower():
            parts = size.lower().split("x")
            if len(parts) == 2:
                try:
                    max_size = max(max_size, int(parts[0]), int(parts[1]))
                except ValueError:
                    pass
    return max_size


def _parse_icons_from_html(html: str, base_url: str) -> list[dict]:
    """Parse HTML to extract all link[rel=icon] entries using BeautifulSoup."""
    soup = BeautifulSoup(html, "lxml")
    icons = []

    # Find all link tags with rel containing "icon"
    for link in soup.find_all("link", rel=lambda x: x and "icon" in x.lower()):
        href = link.get("href")
        if not href:
            continue

        href = _make_absolute_url(href, base_url)
        if not href:
            continue

        sizes = link.get("sizes", "")
        size = _parse_favicon_size(sizes)

        href_lower = href.lower()
        if ".png" in href_lower:
            fmt = "png"
        elif ".svg" in href_lower:
            fmt = "svg"
        elif ".ico" in href_lower:
            fmt = "ico"
        else:
            fmt = "other"

        icons.append({"href": href, "size": size, "format": fmt})

    return icons


def _select_best_icon(icons: list[dict]) -> str | None:
    """Select best favicon: PNG > ICO > other > SVG, then by size."""
    if not icons:
        return None

    format_priority = {"png": 0, "ico": 1, "other": 2, "svg": 3}
    icons.sort(key=lambda x: (format_priority.get(x["format"], 2), -x["size"]))
    return icons[0]["href"]


async def _validate_favicon_url(url: str) -> bool:
    """Verify favicon URL returns an image (HEAD request)."""
    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": BROWSER_UA}
        ) as client:
            response = await client.head(url, follow_redirects=True)
            if response.status_code != 200:
                return False
            content_type = response.headers.get("content-type", "").lower()
            return "image" in content_type
    except Exception as e:
        log.debug(f"Favicon validation failed for {url}: {e}")
        return False


async def _try_html_link_parsing(url: str) -> str | None:
    """Fetch HTML and parse link[rel=icon] tags."""
    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": BROWSER_UA}
        ) as client:
            response = await client.get(url, follow_redirects=True)
            if response.status_code != 200:
                return None

            icons = _parse_icons_from_html(response.text, url)
            return _select_best_icon(icons)

    except Exception as e:
        log.debug(f"HTML link parsing failed for {url}: {e}")
    return None


async def _fetch_favicon_impl(server_url: str) -> str | None:
    """
    Resolve a favicon for an MCP server.

    Order of preference, each validated to be a live image before use:
    1. The per-server Smithery icon (Smithery hosts many servers behind one host).
    2. An explicit ``<link rel="icon">`` the host declares in its root HTML — the
       intentional signal a self-hosted MCP server uses to declare its own icon.
    3. Google's favicon service for the registered domain (the default fallback).

    Each override is validated (HEAD -> must be a live image) so we never replace
    the working default with a broken or missing icon. Probing ``/favicon.ico`` or
    the favicon library is deliberately avoided — it picks up a framework's generic
    placeholder (or nothing) for servers that don't customise their icon.
    """
    host_url = _get_host_url(server_url)
    log.debug(f"Fetching favicon for host: {host_url}")

    smithery_icon = await _fetch_smithery_icon(server_url)
    if smithery_icon and await _validate_favicon_url(smithery_icon):
        return smithery_icon

    declared = await _try_html_link_parsing(host_url)
    if declared and await _validate_favicon_url(declared):
        return declared

    return legacy_favicon_url(server_url)


async def fetch_favicon_from_url(server_url: str) -> str | None:
    """
    Fetch favicon URL with Redis caching by root domain.

    Returns:
        Favicon URL string or None if not found
    """
    cache_key = _get_domain_cache_key(server_url)
    log.set(server_url=server_url, favicon_cache_key=cache_key)

    try:
        # Check Redis cache first
        cached = await get_cache(cache_key)
        if cached:
            return cached

        # Cache miss - fetch from external sources
        result = await _fetch_favicon_impl(server_url)

        if result:
            await set_cache(cache_key, result, ttl=FAVICON_CACHE_TTL)

        return result

    except Exception as e:
        log.warning(f"{LogTag.TOOL} Failed to fetch favicon for {server_url}: {e}")
        return None


async def fetch_favicon_uncached(server_url: str) -> str | None:
    """Resolve a favicon bypassing the cache (for diagnostics / dev tooling)."""
    return await _fetch_favicon_impl(server_url)
