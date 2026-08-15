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
from typing import TypedDict

from app.constants.log_tags import LogTag
from app.utils.crawl4ai_utils import get_browser_semaphore, managed_crawler
from shared.py.wide_events import log


class ProfileCrawlResult(TypedDict):
    """Outcome of one profile crawl. Exactly one of ``content``/``error`` is set."""

    url: str
    platform: str
    content: str | None
    error: str | None


async def crawl_profile_url(
    url: str, platform: str, semaphore: asyncio.Semaphore
) -> ProfileCrawlResult:
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
            log.info(f"{LogTag.MEMORY} Crawling profile", platform=platform, url=url)

            # Process-wide cap on live Chromium instances (shared with
            # crawl4ai_utils) so concurrent profile crawls can't fan out into
            # dozens of browsers; managed_crawler guarantees the browser is
            # torn down even when this task is cancelled mid-crawl.
            async with (
                get_browser_semaphore(),
                managed_crawler(context_name=f"{platform} profile crawl") as crawler,
            ):
                result = await asyncio.wait_for(crawler.arun(url=url), timeout=15.0)

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
                log.info(
                    f"{LogTag.MEMORY} Successfully crawled profile",
                    url=url,
                    duration_s=round(elapsed, 2),
                    content_size=content_size,
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

            if not error_msg or error_msg == "No error message":
                error_msg = f"{error_type}: {e!r}"

            log.error(
                f"{LogTag.MEMORY} Failed to crawl profile",
                url=url,
                duration_s=round(elapsed, 2),
                error_type=error_type,
                error=error_msg,
            )
            log.debug(
                f"{LogTag.MEMORY} Full crawl failure traceback",
                url=url,
                traceback=traceback.format_exc(),
            )

            return {
                "url": url,
                "platform": platform,
                "content": None,
                "error": f"{error_type}: {error_msg}",
            }
