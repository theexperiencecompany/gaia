"""
Favicon fetching utilities with Redis caching.

Strategy:
1. Check Redis cache by root domain (e.g., smithery.ai)
2. If miss, try 'favicon' library (fast, simple)
3. Fallback to 'extract-favicon' library (DuckDuckGo/Google APIs)
4. Cache result in Redis for 7 days
"""

import time
from urllib.parse import urlparse

import favicon
import tldextract
from extract_favicon import get_best_favicon

from app.config.loggers import app_logger as logger
from app.db.redis import get_cache, set_cache

# Cache favicon URLs for 30 days (favicons rarely change)
FAVICON_CACHE_TTL = 30 * 24 * 3600


def _get_domain_cache_key(server_url: str) -> str:
    """
    Extract root domain for cache key.

    Examples:
        server.smithery.ai -> favicon:smithery.ai
        auth.smithery.ai -> favicon:smithery.ai
        mcp.example.com -> favicon:example.com
    """
    extracted = tldextract.extract(server_url)
    return f"favicon:{extracted.top_domain_under_public_suffix}"


def _try_favicon_library(url: str) -> str | None:
    """
    Try fetching favicon using 'favicon' library.

    Returns the largest icon URL or None if not found.
    """
    try:
        start = time.perf_counter()
        icons = favicon.get(url)
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug(f"favicon.get() took {elapsed:.1f}ms for {url}")

        if icons:
            # Sort by size (width * height), largest first
            sorted_icons = sorted(
                icons, key=lambda i: (i.width or 0) * (i.height or 0), reverse=True
            )
            if sorted_icons[0].url:
                return sorted_icons[0].url
    except Exception as e:
        logger.debug(f"favicon library failed for {url}: {e}")
    return None


def _try_extract_favicon_library(url: str) -> str | None:
    """
    Try fetching favicon using 'extract-favicon' library.

    Uses DuckDuckGo and Google APIs as fallbacks.
    """
    try:
        start = time.perf_counter()
        # Exclude 'content' and 'generate' - use only API fallbacks
        strategy = ["duckduckgo", "google"]
        favicon_obj = get_best_favicon(url, strategy=strategy)
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug(f"get_best_favicon() took {elapsed:.1f}ms for {url}")

        if favicon_obj and favicon_obj.url:
            # Skip data URLs (generated placeholders)
            favicon_url = str(favicon_obj.url)
            if not favicon_url.startswith("data:"):
                return favicon_url
    except Exception as e:
        logger.debug(f"extract-favicon library failed for {url}: {e}")
    return None


async def _fetch_favicon_impl(server_url: str) -> str | None:
    """
    Internal implementation: fetch favicon from external sources.

    Tries full domain first, then root domain as fallback.
    """
    parsed = urlparse(server_url)
    scheme = parsed.scheme or "https"

    # Extract domain parts using tldextract
    extracted = tldextract.extract(server_url)

    # Build list of URLs to try
    urls_to_try = [f"{scheme}://{extracted.fqdn}"]

    # If there's a subdomain, also try root domain as fallback
    if extracted.subdomain:
        urls_to_try.append(f"{scheme}://{extracted.top_domain_under_public_suffix}")

    for url in urls_to_try:
        logger.debug(f"Trying favicon for: {url}")

        # Try favicon library first (faster, simpler)
        result = _try_favicon_library(url)
        if result:
            return result

        # Fallback to extract-favicon (DuckDuckGo/Google APIs)
        result = _try_extract_favicon_library(url)
        if result:
            return result

    return None


async def fetch_favicon_from_url(server_url: str) -> str | None:
    """
    Fetch favicon URL with Redis caching by root domain.

    Cache key is based on root domain (e.g., smithery.ai) so all
    subdomains share the same cached favicon.

    Args:
        server_url: The URL to fetch favicon from

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
