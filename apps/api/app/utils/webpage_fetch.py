"""Webpage fetching with automatic engine failover.

A URL is rendered to markdown by the first engine that succeeds:
    Crawl4AI (free headless render) -> Firecrawl (managed, free credits) -> httpx
httpx has no external dependency, so it is always the final backstop. The chain
result is cached, so repeated fetches of the same URL never re-hit any engine.
"""

from abc import ABC, abstractmethod
import asyncio

from bs4 import BeautifulSoup
from firecrawl import FirecrawlApp
import html2text
import httpx

from app.config.settings import settings
from app.constants.cache import WEBPAGE_FETCH_CACHE_TTL
from app.constants.search import (
    CRAWL4AI_PAGE_TIMEOUT_MS,
    CRAWL4AI_SINGLE_TOTAL_TIMEOUT_SECONDS,
)
from app.decorators.caching import Cacheable
from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai
from app.utils.exceptions import FetchError
from shared.py.wide_events import log

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
_HTTPX_TIMEOUT = 15.0
_MAX_HTTPX_CHARS = 60_000
_FIRECRAWL_BLOCK_MARKERS = ("401", "403", "500", "blocked", "bot", "timeout")
_NON_CONTENT_TAGS = ["script", "style", "nav", "footer", "aside", "iframe", "noscript", "head"]


class WebpageFetcher(ABC):
    """One webpage-fetching engine. ``fetch`` returns markdown or raises ``FetchError``."""

    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether this engine has what it needs to run."""

    @abstractmethod
    async def fetch(self, url: str) -> str:
        """Render ``url`` to markdown, raising ``FetchError`` on failure."""


class Crawl4aiFetcher(WebpageFetcher):
    name = "crawl4ai"

    def is_configured(self) -> bool:
        return True

    async def fetch(self, url: str) -> str:
        contents, errors = await batch_fetch_with_crawl4ai(
            [url],
            page_timeout_ms=CRAWL4AI_PAGE_TIMEOUT_MS,
            total_timeout_seconds=CRAWL4AI_SINGLE_TOTAL_TIMEOUT_SECONDS,
            semaphore_count=1,
            context_name="webpage_fetch",
        )
        content = contents.get(url, "")
        if content.strip():
            return content
        raise FetchError(errors.get(url, "crawl4ai returned no content"), url=url)


class FirecrawlFetcher(WebpageFetcher):
    name = "firecrawl"
    _client: FirecrawlApp | None = None

    def is_configured(self) -> bool:
        return bool(settings.FIRECRAWL_API_KEY)

    def _get_client(self) -> FirecrawlApp:
        if FirecrawlFetcher._client is None:
            FirecrawlFetcher._client = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)
        return FirecrawlFetcher._client

    async def fetch(self, url: str) -> str:
        client = self._get_client()
        try:
            document = await asyncio.to_thread(client.scrape, url, formats=["markdown"])
        except Exception as e:
            # Retry once through the stealth proxy when the failure looks like a block.
            if not any(marker in str(e).lower() for marker in _FIRECRAWL_BLOCK_MARKERS):
                raise FetchError(f"firecrawl error: {e}", url=url) from e
            document = await asyncio.to_thread(
                client.scrape, url, formats=["markdown"], proxy="stealth"
            )
        markdown = getattr(document, "markdown", None)
        if markdown:
            return markdown
        raise FetchError("firecrawl returned no markdown", url=url)


class HttpxFetcher(WebpageFetcher):
    name = "httpx"

    def is_configured(self) -> bool:
        return True

    async def fetch(self, url: str) -> str:
        async with httpx.AsyncClient(
            timeout=_HTTPX_TIMEOUT, follow_redirects=True, headers=_BROWSER_HEADERS
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        for tag in soup(_NON_CONTENT_TAGS):
            tag.decompose()
        node = (
            soup.find("main")
            or soup.find("article")
            or soup.find(id="content")
            or soup.find(id="main-content")
            or soup.find(class_="content")
            or soup.body
        )

        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.body_width = 0
        markdown = converter.handle(str(node) if node else str(soup)).strip()
        if not markdown:
            raise FetchError("httpx returned empty content", url=url)
        return markdown[:_MAX_HTTPX_CHARS]


_FETCHERS: list[WebpageFetcher] = [Crawl4aiFetcher(), FirecrawlFetcher(), HttpxFetcher()]


async def _fetch_first_success(url: str) -> str:
    """Try each configured engine in order, returning the first success."""
    errors: list[str] = []
    for fetcher in _FETCHERS:
        if not fetcher.is_configured():
            continue
        try:
            return await fetcher.fetch(url)
        except Exception as e:
            errors.append(f"{fetcher.name}: {e}")
            log.warning(f"{fetcher.name} fetch failed for {url[:60]}: {e}")
    raise FetchError("; ".join(errors) or "all fetchers failed", url=url)


@Cacheable(key_pattern="webpage:{url}", ttl=WEBPAGE_FETCH_CACHE_TTL, namespace="web")
async def fetch_webpage(url: str) -> str:
    """Fetch one URL to markdown, failing over across engines (cached)."""
    return await _fetch_first_success(url)


async def fetch_with_httpx(url: str) -> str:
    """Fetch a URL using only the httpx engine (deep-research fallback path)."""
    return await HttpxFetcher().fetch(url)
