import asyncio
from collections import defaultdict, deque
from typing import Dict, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

from shared.py.wide_events import log
from app.constants.search import CRAWL4AI_WAIT_UNTIL


def _normalize_url(url: str) -> str:
    """Normalize URL for tolerant matching across redirects/canonicalization."""
    parts = urlsplit(url)
    path = parts.path or ""
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            parts.query,
            "",
        )
    )


def _pop_available_index(
    bucket: deque[int],
    remaining_indices: set[int],
) -> Optional[int]:
    while bucket:
        idx = bucket.popleft()
        if idx in remaining_indices:
            return idx
    return None


def _match_result_to_request_index(
    result: object,
    *,
    remaining_indices: set[int],
    requested_by_exact: dict[str, deque[int]],
    requested_by_normalized: dict[str, deque[int]],
) -> Optional[int]:
    candidate_urls = []
    result_url = getattr(result, "url", None)
    redirected_url = getattr(result, "redirected_url", None)
    if isinstance(result_url, str) and result_url:
        candidate_urls.append(result_url)
    if isinstance(redirected_url, str) and redirected_url:
        candidate_urls.append(redirected_url)

    # Prefer exact match first.
    for candidate in candidate_urls:
        index = _pop_available_index(
            requested_by_exact[candidate],
            remaining_indices,
        )
        if index is not None:
            return index

    # Fall back to normalized URL matching.
    for candidate in candidate_urls:
        normalized = _normalize_url(candidate)
        index = _pop_available_index(
            requested_by_normalized[normalized],
            remaining_indices,
        )
        if index is not None:
            return index

    return None


def _extract_content_or_error(
    *,
    result: object,
    context_name: str,
    max_content_chars: Optional[int],
) -> tuple[Optional[str], Optional[str]]:
    markdown = getattr(result, "markdown", None)
    if (
        getattr(result, "success", False)
        and isinstance(markdown, str)
        and markdown.strip()
    ):
        if max_content_chars is not None:
            return markdown[:max_content_chars], None
        return markdown, None

    error_message = getattr(result, "error_message", None)
    return None, str(error_message or f"{context_name} returned empty content")


async def _recover_with_single_url_crawls(
    urls: Sequence[str],
    *,
    page_timeout_ms: int,
    total_timeout_seconds: float,
    context_name: str,
    max_content_chars: Optional[int],
) -> tuple[Dict[str, str], Dict[str, str]]:
    """Best-effort recovery path after batch timeout to avoid all-or-nothing failures."""
    recovery_timeout = max(
        10.0, min(total_timeout_seconds, page_timeout_ms / 1000 + 10.0)
    )

    run_config = CrawlerRunConfig(
        page_timeout=page_timeout_ms,
        wait_until=CRAWL4AI_WAIT_UNTIL,
        semaphore_count=1,
        verbose=False,
    )
    browser_config = BrowserConfig(
        headless=True, browser_mode="dedicated", verbose=False
    )

    contents: Dict[str, str] = {}
    errors: Dict[str, str] = {}

    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            for url in urls:
                try:
                    single_results = await asyncio.wait_for(
                        crawler.arun_many(urls=[url], config=run_config),
                        timeout=recovery_timeout,
                    )
                except asyncio.TimeoutError:
                    errors[url] = (
                        f"{context_name} timed out after {total_timeout_seconds:.0f}s "
                        "(recovery: single URL timeout)"
                    )
                    continue
                except Exception as e:
                    errors[url] = f"{context_name} recovery error: {e}"
                    continue

                if not single_results:
                    errors[url] = f"{context_name} returned no result"
                    continue

                content, error = _extract_content_or_error(
                    result=single_results[0],
                    context_name=context_name,
                    max_content_chars=max_content_chars,
                )
                if content is not None:
                    contents[url] = content
                elif error is not None:
                    errors[url] = error
    except Exception as e:
        fallback_error = f"{context_name} timed out after {total_timeout_seconds:.0f}s and recovery failed: {e}"
        return {}, {url: fallback_error for url in urls}

    return contents, errors


async def batch_fetch_with_crawl4ai(
    urls: Sequence[str],
    *,
    page_timeout_ms: int,
    total_timeout_seconds: float,
    semaphore_count: int,
    max_content_chars: Optional[int] = None,
    context_name: str = "crawl4ai",
) -> tuple[Dict[str, str], Dict[str, str]]:
    """Fetch multiple URLs with a single crawl4ai crawler via arun_many."""
    if not urls:
        return {}, {}

    run_config = CrawlerRunConfig(
        page_timeout=page_timeout_ms,
        wait_until=CRAWL4AI_WAIT_UNTIL,
        semaphore_count=semaphore_count,
        verbose=False,
    )
    browser_config = BrowserConfig(
        headless=True, browser_mode="dedicated", verbose=False
    )

    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            results = await asyncio.wait_for(
                crawler.arun_many(urls=list(urls), config=run_config),
                timeout=total_timeout_seconds,
            )
    except asyncio.TimeoutError:
        log.warning(
            f"{context_name} batch timed out after {total_timeout_seconds:.0f}s; "
            "retrying URLs individually"
        )
        return await _recover_with_single_url_crawls(
            urls,
            page_timeout_ms=page_timeout_ms,
            total_timeout_seconds=total_timeout_seconds,
            context_name=context_name,
            max_content_chars=max_content_chars,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        error = f"{context_name} batch error: {e}"
        log.warning(error)
        return {}, {url: error for url in urls}

    requested_by_exact: dict[str, deque[int]] = defaultdict(deque)
    requested_by_normalized: dict[str, deque[int]] = defaultdict(deque)
    for idx, requested_url in enumerate(urls):
        requested_by_exact[requested_url].append(idx)
        requested_by_normalized[_normalize_url(requested_url)].append(idx)

    remaining_indices: set[int] = set(range(len(urls)))
    matched_results: dict[int, object] = {}
    unmatched_results: list[object] = []

    for result in results:
        index = _match_result_to_request_index(
            result,
            remaining_indices=remaining_indices,
            requested_by_exact=requested_by_exact,
            requested_by_normalized=requested_by_normalized,
        )
        if index is None:
            unmatched_results.append(result)
            continue

        matched_results[index] = result
        remaining_indices.discard(index)

    if unmatched_results and remaining_indices:
        # Best-effort fallback when crawl4ai returns result objects without matchable URL fields.
        for index, result in zip(sorted(remaining_indices), unmatched_results):
            matched_results[index] = result
            remaining_indices.discard(index)

    contents: Dict[str, str] = {}
    errors: Dict[str, str] = {}

    for index, requested_url in enumerate(urls):
        result = matched_results.get(index)
        if result is None:
            continue

        extracted_content, extracted_error = _extract_content_or_error(
            result=result,
            context_name=context_name,
            max_content_chars=max_content_chars,
        )
        if extracted_content is not None:
            contents[requested_url] = extracted_content
        elif extracted_error is not None:
            errors[requested_url] = extracted_error

    if len(results) > len(urls):
        log.warning(
            f"{context_name} returned {len(results)} results for {len(urls)} URLs; ignoring extras"
        )

    unmatched_count = max(len(unmatched_results) - len(matched_results), 0)
    if unmatched_count:
        log.warning(
            f"{context_name} could not map {unmatched_count} results to requested URLs"
        )

    for url in urls:
        if url not in contents and url not in errors:
            errors[url] = f"{context_name} returned no result"

    return contents, errors
