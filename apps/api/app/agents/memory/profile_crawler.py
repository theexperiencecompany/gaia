"""Crawl social media profile pages and extract content.

Flow:
1. Takes dictionary of platform -> profile URLs
2. Uses one crawl4ai crawler + arun_many for batched crawling
3. Extracts markdown content and truncates to max content size
4. Returns result dicts keyed by URL with content/error status
"""

from typing import Dict, Sequence

from shared.py.wide_events import log
from app.constants.search import (
    CRAWL4AI_PAGE_TIMEOUT_MS,
    PROFILE_CRAWL4AI_BATCH_TIMEOUT_SECONDS,
    PROFILE_CRAWL4AI_SEMAPHORE_COUNT,
    PROFILE_CRAWL_CONTENT_MAX_CHARS,
    PROFILE_CRAWL4AI_SINGLE_TIMEOUT_SECONDS,
)
from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai


async def crawl_profile_url(url: str, platform: str) -> Dict:
    """
    Crawl a single profile URL using crawl4ai.

    Args:
        url: Profile URL to crawl
        platform: Platform name (e.g., 'twitter', 'github')

    Returns:
        Dict with url, platform, content (markdown), and error if failed
    """
    results = await crawl_profile_urls_batch(
        [(url, platform)],
        total_timeout_seconds=PROFILE_CRAWL4AI_SINGLE_TIMEOUT_SECONDS,
        semaphore_count=1,
    )
    return (
        results[0]
        if results
        else {
            "url": url,
            "platform": platform,
            "content": None,
            "error": "crawl_profile_urls_batch returned no results",
        }
    )


async def crawl_profile_urls_batch(
    url_platform_pairs: Sequence[tuple[str, str]],
    *,
    total_timeout_seconds: float = PROFILE_CRAWL4AI_BATCH_TIMEOUT_SECONDS,
    semaphore_count: int = PROFILE_CRAWL4AI_SEMAPHORE_COUNT,
) -> list[Dict]:
    """Crawl profile URLs with one crawler instance and return normalized results."""
    if not url_platform_pairs:
        return []

    urls = [url for url, _ in url_platform_pairs]
    contents, errors = await batch_fetch_with_crawl4ai(
        urls,
        page_timeout_ms=CRAWL4AI_PAGE_TIMEOUT_MS,
        total_timeout_seconds=total_timeout_seconds,
        semaphore_count=semaphore_count,
        max_content_chars=PROFILE_CRAWL_CONTENT_MAX_CHARS,
        context_name="profile crawl",
    )

    results: list[Dict] = []
    for url, platform in url_platform_pairs:
        content = contents.get(url)
        error = errors.get(url)
        if content:
            log.info(
                f"Successfully crawled {platform} profile: {url} ({len(content):,} chars)"
            )
            results.append(
                {
                    "url": url,
                    "platform": platform,
                    "content": content,
                    "error": None,
                }
            )
        else:
            results.append(
                {
                    "url": url,
                    "platform": platform,
                    "content": None,
                    "error": error or "profile crawl returned empty content",
                }
            )

    return results
