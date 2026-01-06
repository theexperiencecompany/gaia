"""
Favicon fetching utilities using multiple libraries for robustness.

Strategy:
1. Try 'favicon' library (fast, simple)
2. Fallback to 'extract-favicon' library (comprehensive with DuckDuckGo/Google APIs)

For each library, tries both full domain (with subdomain) and root domain.
"""

from urllib.parse import urlparse

import favicon
import tldextract
from extract_favicon import get_best_favicon

from app.config.loggers import app_logger as logger


async def _try_favicon_library(url: str) -> str | None:
    """
    Try fetching favicon using 'favicon' library.

    Returns the largest icon URL or None if not found.
    """
    try:
        icons = favicon.get(url)
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


async def _try_extract_favicon_library(url: str) -> str | None:
    """
    Try fetching favicon using 'extract-favicon' library.

    Uses DuckDuckGo and Google APIs as fallbacks.
    """
    try:
        # Exclude 'content' and 'generate' - use only API fallbacks
        strategy = ["duckduckgo", "google"]
        favicon_obj = get_best_favicon(url, strategy=strategy)
        if favicon_obj and favicon_obj.url:
            # Skip data URLs (generated placeholders)
            favicon_url = str(favicon_obj.url)
            if not favicon_url.startswith("data:"):
                return favicon_url
    except Exception as e:
        logger.debug(f"extract-favicon library failed for {url}: {e}")
    return None


async def fetch_favicon_from_url(server_url: str) -> str | None:
    """
    Fetch favicon URL using multiple libraries and strategies.

    Tries the full URL first (with subdomain), then falls back to root domain.
    For example, server.smithery.ai will try:
    1. server.smithery.ai
    2. smithery.ai (if subdomain exists)

    For each URL, tries:
    1. 'favicon' library (fast, parses HTML)
    2. 'extract-favicon' library (DuckDuckGo + Google APIs)

    Args:
        server_url: The URL to fetch favicon from

    Returns:
        Favicon URL string or None if not found
    """
    try:
        parsed = urlparse(server_url)
        scheme = parsed.scheme or "https"

        # Extract domain parts using tldextract
        extracted = tldextract.extract(server_url)

        # Build list of URLs to try
        urls_to_try = []

        # 1. Try full domain first (with subdomain if present)
        if extracted.subdomain:
            full_domain = f"{extracted.subdomain}.{extracted.domain}.{extracted.suffix}"
        else:
            full_domain = f"{extracted.domain}.{extracted.suffix}"
        urls_to_try.append(f"{scheme}://{full_domain}")

        # 2. If there's a subdomain, also try root domain as fallback
        if extracted.subdomain:
            root_domain = f"{extracted.domain}.{extracted.suffix}"
            urls_to_try.append(f"{scheme}://{root_domain}")

        for url in urls_to_try:
            print(f"Trying favicon for: {url}")
            logger.info(f"Trying favicon for: {url}")

            # Try favicon library first (faster, simpler)
            result = await _try_favicon_library(url)
            if result:
                print(f"Found favicon via 'favicon' library: {result}")
                logger.info(
                    f"Found favicon for {server_url} via favicon library at {url}: {result}"
                )
                return result

            # Fallback to extract-favicon (DuckDuckGo/Google APIs)
            result = await _try_extract_favicon_library(url)
            if result:
                print(f"Found favicon via 'extract-favicon' library: {result}")
                logger.info(
                    f"Found favicon for {server_url} via extract-favicon library at {url}: {result}"
                )
                return result

            print(f"No favicon found at {url}, trying next...")

        logger.info(f"No favicon found for {server_url}")
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch favicon for {server_url}: {e}")
        return None
