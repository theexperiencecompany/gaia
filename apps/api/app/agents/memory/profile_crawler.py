"""Crawl social media profile pages and extract content.

Flow:
1. Takes dictionary of platform -> profile URLs
2. Spawns concurrent crawl tasks (up to max_concurrent limit)
3. Uses AsyncWebCrawler to fetch each profile page
4. Extracts markdown content, cleans and truncates to 50KB
5. Returns list of results with content, platform, URL, and error status
6. Handles timeouts (30s) and network errors gracefully
"""

import asyncio
import time
import traceback
from typing import Dict, List, Set

from app.config.loggers import memory_logger as logger
from crawl4ai import AsyncWebCrawler


async def crawl_profile_url(
    url: str, platform: str, semaphore: asyncio.Semaphore
) -> Dict:
    """
    Crawl a single profile URL using crawl4ai.

    Args:
        url: Profile URL to crawl
        platform: Platform name (e.g., 'twitter', 'github')
        semaphore: Concurrency control semaphore

    Returns:
        Dict with url, platform, content (markdown), and error if failed
    """
    async with semaphore:
        start_time = time.time()
        try:
            logger.info(f"Crawling {platform} profile: {url}")

            async with AsyncWebCrawler(verbose=False) as crawler:
                # Add timeout to prevent hanging
                result = await asyncio.wait_for(crawler.arun(url=url), timeout=30.0)

                if not result:
                    raise ValueError("Crawler returned None")

                if not hasattr(result, "markdown"):
                    raise ValueError(
                        f"Result missing markdown attribute. Result type: {type(result)}"
                    )

                if not result.markdown:
                    raise ValueError("No markdown content returned (empty string)")

                elapsed = time.time() - start_time
                content_size = len(result.markdown)
                logger.info(
                    f"Successfully crawled {url} in {elapsed:.2f}s ({content_size:,} chars)"
                )
                return {
                    "url": url,
                    "platform": platform,
                    "content": result.markdown,
                    "error": None,
                }
        except Exception as e:
            elapsed = time.time() - start_time
            error_type = type(e).__name__
            error_msg = str(e) if str(e) else "No error message"

            # Get more detailed error info
            if not error_msg or error_msg == "No error message":
                error_msg = f"{error_type}: {repr(e)}"

            # Log full traceback for debugging
            logger.error(
                f"Failed to crawl {url} after {elapsed:.2f}s: {error_type}: {error_msg}"
            )
            logger.debug(f"Full traceback for {url}:\n{traceback.format_exc()}")

            return {
                "url": url,
                "platform": platform,
                "content": None,
                "error": f"{error_type}: {error_msg}",
            }


async def crawl_profiles_batch(
    profile_urls: Dict[str, Set[str]], max_concurrent: int = 10
) -> List[Dict]:
    """
    Crawl multiple profile URLs concurrently.

    Args:
        profile_urls: Dict mapping platform names to sets of URLs
        max_concurrent: Maximum number of concurrent crawls

    Returns:
        List of crawl results (dicts with url, platform, content, error)
    """
    if not profile_urls:
        return []

    batch_start_time = time.time()
    semaphore = asyncio.Semaphore(max_concurrent)
    tasks = []

    for platform, urls in profile_urls.items():
        for url in urls:
            task = crawl_profile_url(url, platform, semaphore)
            tasks.append(task)

    logger.info(
        f"Starting to crawl {len(tasks)} profile URLs (max {max_concurrent} concurrent)"
    )
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out exceptions and convert to list
    valid_results = [r for r in results if isinstance(r, dict)]

    successful = sum(1 for r in valid_results if r["content"] is not None)
    failed = len(valid_results) - successful

    batch_elapsed = time.time() - batch_start_time
    avg_time = batch_elapsed / len(tasks) if tasks else 0
    logger.info(
        f"Crawl batch completed in {batch_elapsed:.2f}s: {successful} succeeded, {failed} failed "
        f"(avg {avg_time:.2f}s per URL)"
    )

    return valid_results
