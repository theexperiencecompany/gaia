"""
Favicon fetching utilities with Redis caching.

Strategy:
1. Check Redis cache by root domain (e.g., smithery.ai)
2. Try 'favicon' library (parses HTML for link tags) - runs in thread pool
3. Try standard /favicon.ico path
4. Parse HTML for link[rel=icon] tags
5. Cache result in Redis for 180 days
"""

import asyncio
import time
from urllib.parse import urlparse, urljoin

import httpx
import favicon
import tldextract
from bs4 import BeautifulSoup

from app.config.loggers import app_logger as logger
from app.db.redis import get_cache, set_cache

# Cache favicon URLs for 180 days (favicons rarely change)
FAVICON_CACHE_TTL = 180 * 24 * 3600

# HTTP client settings
HTTP_TIMEOUT = 3.0
FAVICON_LIB_TIMEOUT = 3

# Known favicon extensions that don't need validation
KNOWN_FAVICON_EXTENSIONS = (".ico", ".png", ".svg", ".webp")


def _get_domain_cache_key(server_url: str) -> str:
    """Extract root domain for cache key."""
    extracted = tldextract.extract(server_url)
    return f"favicon:{extracted.top_domain_under_public_suffix}"


def _get_root_domain_url(server_url: str) -> str:
    """Extract root domain URL from any URL."""
    parsed = urlparse(server_url)
    scheme = parsed.scheme or "https"
    extracted = tldextract.extract(server_url)
    return f"{scheme}://{extracted.top_domain_under_public_suffix}"


def _is_known_favicon_url(url: str) -> bool:
    """Check if URL has a known favicon extension (skip validation)."""
    url_lower = url.lower().split("?")[0]  # Remove query params
    return any(url_lower.endswith(ext) for ext in KNOWN_FAVICON_EXTENSIONS)


def _try_favicon_library_sync(url: str) -> str | None:
    """
    Sync version of favicon library fetch (runs in thread pool).

    Filters out large OG images, prefers small icons or unknown dimensions.
    """
    try:
        start = time.perf_counter()
        icons = favicon.get(url, timeout=FAVICON_LIB_TIMEOUT)
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug(f"favicon.get() took {elapsed:.1f}ms for {url}")

        if not icons:
            return None

        # Filter out large images (OG images are typically 1200px+)
        # Keep icons with unknown dimensions (0x0) or small dimensions (<= 512px)
        valid_icons = [
            i
            for i in icons
            if i.url
            and (
                (i.width or 0) == 0  # Unknown dimensions (likely favicon)
                or ((i.width or 0) <= 512 and (i.height or 0) <= 512)  # Small icons
            )
        ]

        if not valid_icons:
            return None

        # Sort: prefer known small sizes, then unknown (0x0)
        # Icons with 0x0 get size=999 so they come after known small icons
        def sort_key(icon):
            size = (icon.width or 0) * (icon.height or 0)
            return size if size > 0 else 999

        valid_icons.sort(key=sort_key)
        return valid_icons[0].url

    except Exception as e:
        logger.debug(f"favicon library failed for {url}: {e}")
    return None


async def _try_favicon_library(url: str) -> str | None:
    """Run favicon library in thread pool to avoid blocking."""
    return await asyncio.to_thread(_try_favicon_library_sync, url)


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
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.head(url, follow_redirects=True)
            if response.status_code != 200:
                return False
            content_type = response.headers.get("content-type", "").lower()
            return "image" in content_type
    except Exception as e:
        logger.debug(f"Favicon validation failed for {url}: {e}")
        return False


async def _try_standard_favicon(url: str) -> str | None:
    """Try the standard /favicon.ico path."""
    parsed = urlparse(url)
    favicon_url = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"

    if await _validate_favicon_url(favicon_url):
        return favicon_url
    return None


async def _try_html_link_parsing(url: str) -> str | None:
    """Fetch HTML and parse link[rel=icon] tags."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url, follow_redirects=True)
            if response.status_code != 200:
                return None

            icons = _parse_icons_from_html(response.text, url)
            return _select_best_icon(icons)

    except Exception as e:
        logger.debug(f"HTML link parsing failed for {url}: {e}")
    return None


async def _fetch_favicon_impl(server_url: str) -> str | None:
    """
    Fetch favicon from external sources.

    Uses root domain only. Strategy:
    1. favicon library (thread pool, with timeout)
    2. Standard /favicon.ico path
    3. Parse HTML for link[rel=icon]
    """
    url = _get_root_domain_url(server_url)
    logger.debug(f"Fetching favicon from root domain: {url}")

    # Try favicon library (runs in thread pool)
    result = await _try_favicon_library(url)
    if result:
        # Skip validation for known favicon extensions
        if _is_known_favicon_url(result):
            return result
        if await _validate_favicon_url(result):
            return result
        logger.debug(f"Favicon library result failed validation: {result}")

    # Try standard /favicon.ico path
    result = await _try_standard_favicon(url)
    if result:
        return result

    # Fallback: parse HTML for link rel=icon
    result = await _try_html_link_parsing(url)
    if result:
        # Skip validation for known favicon extensions
        if _is_known_favicon_url(result):
            return result
        # Only validate unknown extensions
        if await _validate_favicon_url(result):
            return result
        logger.debug(f"HTML parsing result failed validation: {result}")

    return None


async def fetch_favicon_from_url(server_url: str) -> str | None:
    """
    Fetch favicon URL with Redis caching by root domain.

    Returns:
        Favicon URL string or None if not found
    """
    cache_key = _get_domain_cache_key(server_url)

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
        logger.warning(f"Failed to fetch favicon for {server_url}: {e}")
        return None
