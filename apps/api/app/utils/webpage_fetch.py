"""Webpage fetching with automatic engine failover.

A URL is rendered to markdown by the first engine that succeeds:
    Crawl4AI (free headless render) -> Firecrawl (managed, free credits) -> httpx
httpx has no external dependency, so it is always the final backstop. The chain
result is cached, so repeated fetches of the same URL never re-hit any engine.

Full page content is returned untruncated; callers decide on any length limits.
"""

from abc import ABC, abstractmethod
import asyncio
import ipaddress
import socket
import time
from typing import Any
from urllib.parse import urlparse

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
_FIRECRAWL_BLOCK_MARKERS = ("401", "403", "500", "blocked", "bot", "timeout")
_NON_CONTENT_TAGS = ["script", "style", "nav", "footer", "aside", "iframe", "noscript", "head"]


def _resolve_addresses(host: str, port: int) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


async def _ensure_url_allowed(url: str) -> None:
    """Reject non-HTTP(S) schemes and hosts that resolve to non-public addresses.

    Guards against SSRF — the agent can pass arbitrary URLs, so a request must not
    be able to reach loopback, private, link-local (incl. cloud metadata), or
    otherwise reserved ranges.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"unsupported URL scheme: {parsed.scheme!r}", url=url)
    host = parsed.hostname
    if not host:
        raise FetchError("URL has no host", url=url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = await asyncio.to_thread(_resolve_addresses, host, port)
    except OSError as e:
        raise FetchError(f"DNS resolution failed: {e}", url=url) from e
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise FetchError(f"refusing to fetch non-public address {ip}", url=url)


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
    """Headless-Chromium fetcher (primary; free, renders JS)."""

    name = "crawl4ai"

    def is_configured(self) -> bool:
        """Always available — no external credentials required."""
        return True

    async def fetch(self, url: str) -> str:
        """Render the page with crawl4ai and return its markdown."""
        contents, errors = await batch_fetch_with_crawl4ai(
            [url],
            page_timeout_ms=CRAWL4AI_PAGE_TIMEOUT_MS,
            total_timeout_seconds=CRAWL4AI_SINGLE_TOTAL_TIMEOUT_SECONDS,
            semaphore_count=1,
            context_name="webpage_fetch",
            thorough=True,
        )
        content = contents.get(url, "")
        if content.strip():
            return content
        raise FetchError(errors.get(url, "crawl4ai returned no content"), url=url)


class FirecrawlFetcher(WebpageFetcher):
    """Managed scraper fallback (free credits; good against bot-walls)."""

    name = "firecrawl"

    def __init__(self) -> None:
        self._client: FirecrawlApp | None = None

    def is_configured(self) -> bool:
        """True when a Firecrawl API key is configured."""
        return bool(settings.FIRECRAWL_API_KEY)

    def _get_client(self) -> FirecrawlApp:
        if self._client is None:
            self._client = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)
        return self._client

    async def fetch(self, url: str) -> str:
        """Scrape the page via Firecrawl, retrying once through the stealth proxy."""
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
    """Keyless last-resort fetcher (httpx + BeautifulSoup + html2text)."""

    name = "httpx"

    def is_configured(self) -> bool:
        """Always available — pure-Python, no external service."""
        return True

    async def fetch(self, url: str) -> str:
        """Fetch the page over HTTP and convert its main content to markdown."""
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
        return markdown


def _default_fetchers() -> list[WebpageFetcher]:
    """The fetch waterfall, cheapest/most-capable first."""
    return [Crawl4aiFetcher(), FirecrawlFetcher(), HttpxFetcher()]


async def _fetch_first_success(url: str, fetchers: list[WebpageFetcher] | None = None) -> str:
    """Try each configured engine in order, returning the first success.

    Records every engine attempt (outcome, latency, content length) in a single
    ``webpage_fetch`` wide-event field, keyed by host for high-cardinality drill-down.
    """
    fetchers = fetchers if fetchers is not None else _default_fetchers()
    host = urlparse(url).hostname or ""
    attempts: list[dict[str, Any]] = []
    errors: list[str] = []

    for fetcher in fetchers:
        if not fetcher.is_configured():
            attempts.append({"engine": fetcher.name, "outcome": "unconfigured"})
            continue
        start = time.monotonic()
        try:
            content = await fetcher.fetch(url)
        except Exception as e:
            attempts.append(
                {
                    "engine": fetcher.name,
                    "outcome": "error",
                    "error_type": type(e).__name__,
                    "latency_ms": _elapsed_ms(start),
                }
            )
            errors.append(f"{fetcher.name}: {e}")
            log.warning(f"{fetcher.name} fetch failed: {e}")
            continue
        attempts.append(
            {
                "engine": fetcher.name,
                "outcome": "hit",
                "content_length": len(content),
                "latency_ms": _elapsed_ms(start),
            }
        )
        log.set(webpage_fetch={"host": host, "engine_used": fetcher.name, "attempts": attempts})
        return content

    log.set(webpage_fetch={"host": host, "engine_used": None, "attempts": attempts})
    raise FetchError("; ".join(errors) or "all fetchers failed", url=url)


@Cacheable(key_pattern="webpage:{url}", ttl=WEBPAGE_FETCH_CACHE_TTL, namespace="web")
async def fetch_webpage(url: str) -> str:
    """Fetch one URL to markdown, failing over across engines (cached)."""
    await _ensure_url_allowed(url)
    return await _fetch_first_success(url)


async def fetch_with_httpx(url: str) -> str:
    """Fetch a URL using only the httpx engine (deep-research fallback path)."""
    await _ensure_url_allowed(url)
    return await HttpxFetcher().fetch(url)
