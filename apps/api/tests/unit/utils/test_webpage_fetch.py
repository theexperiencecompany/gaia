"""Webpage fetch failover behaviour and the httpx engine's HTML->markdown parse."""

from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.constants.search import (
    CRAWL4AI_PAGE_TIMEOUT_MS,
    CRAWL4AI_SINGLE_TOTAL_TIMEOUT_SECONDS,
)
from app.utils.crawl4ai_utils import CrawlBatchParams
from app.utils.exceptions import FetchError
from app.utils.webpage_fetch import (
    Crawl4aiFetcher,
    HttpxFetcher,
    WebpageFetcher,
    _fetch_first_success,
)


def _resolver(host_to_ip: dict[str, str]) -> Callable[[str, int], list[str]]:
    """Build a fake DNS resolver that maps host -> single IP for the SSRF guard."""

    def _fake(host: str, port: int) -> list[str]:
        return [host_to_ip[host]]

    return _fake


class FakeFetcher(WebpageFetcher):
    def __init__(self, name: str, *, configured: bool = True, result: str | None = None) -> None:
        self.name = name
        self._configured = configured
        self._result = result
        self.called = False

    def is_configured(self) -> bool:
        return self._configured

    async def fetch(self, url: str) -> str:
        self.called = True
        if self._result is None:
            raise FetchError(f"{self.name} failed", url=url)
        return self._result


async def test_returns_first_successful_engine() -> None:
    primary = FakeFetcher("primary", result="# content")
    secondary = FakeFetcher("secondary", result="should not run")

    result = await _fetch_first_success("https://example.com", fetchers=[primary, secondary])

    assert result == "# content"
    assert secondary.called is False


async def test_fails_over_to_next_engine() -> None:
    broken = FakeFetcher("broken", result=None)
    backup = FakeFetcher("backup", result="recovered")

    result = await _fetch_first_success("https://example.com", fetchers=[broken, backup])

    assert broken.called is True
    assert result == "recovered"


async def test_skips_unconfigured_engine() -> None:
    disabled = FakeFetcher("disabled", configured=False, result="never")
    backup = FakeFetcher("backup", result="ok")

    result = await _fetch_first_success("https://example.com", fetchers=[disabled, backup])

    assert disabled.called is False
    assert result == "ok"


async def test_raises_when_all_engines_fail() -> None:
    fetchers = [FakeFetcher("a", result=None), FakeFetcher("b", result=None)]

    with pytest.raises(FetchError):
        await _fetch_first_success("https://example.com", fetchers=fetchers)


async def test_crawl4ai_fetcher_returns_content_and_passes_exact_batch_params() -> None:
    url = "https://example.com/page"
    mock_batch = AsyncMock(return_value=({url: "# content"}, {}))
    fetcher = Crawl4aiFetcher()

    assert fetcher.is_configured() is True

    with patch("app.utils.webpage_fetch.batch_fetch_with_crawl4ai", mock_batch):
        result = await fetcher.fetch(url)

    assert result == "# content"
    mock_batch.assert_awaited_once()
    call_args = mock_batch.call_args
    assert call_args.args[0] == [url]
    params = call_args.args[1]
    assert isinstance(params, CrawlBatchParams)
    assert params == CrawlBatchParams(
        page_timeout_ms=CRAWL4AI_PAGE_TIMEOUT_MS,
        total_timeout_seconds=CRAWL4AI_SINGLE_TOTAL_TIMEOUT_SECONDS,
        semaphore_count=1,
        context_name="webpage_fetch",
        thorough=True,
    )


async def test_crawl4ai_fetcher_raises_the_engines_own_error_on_empty_content() -> None:
    url = "https://example.com/empty"
    mock_batch = AsyncMock(return_value=({url: "   "}, {url: "blocked by robots.txt"}))
    fetcher = Crawl4aiFetcher()

    with (
        patch("app.utils.webpage_fetch.batch_fetch_with_crawl4ai", mock_batch),
        pytest.raises(FetchError) as exc_info,
    ):
        await fetcher.fetch(url)

    assert exc_info.value.message == "blocked by robots.txt"
    assert exc_info.value.url == url


async def test_crawl4ai_fetcher_raises_default_message_when_url_missing_from_errors() -> None:
    url = "https://example.com/missing"
    mock_batch = AsyncMock(return_value=({}, {}))
    fetcher = Crawl4aiFetcher()

    with (
        patch("app.utils.webpage_fetch.batch_fetch_with_crawl4ai", mock_batch),
        pytest.raises(FetchError) as exc_info,
    ):
        await fetcher.fetch(url)

    assert exc_info.value.message == "crawl4ai returned no content"
    assert exc_info.value.url == url


@respx.mock
async def test_httpx_fetcher_extracts_main_content_to_markdown() -> None:
    html = """
    <html><body>
      <nav>navigation menu</nav>
      <main><h1>Heading</h1><p>Hello world body text.</p></main>
      <footer>footer junk</footer>
    </body></html>
    """
    respx.get("https://example.com/page").mock(return_value=httpx.Response(200, text=html))

    markdown = await HttpxFetcher().fetch("https://example.com/page")

    assert "Hello world body text." in markdown
    assert "navigation menu" not in markdown
    assert "footer junk" not in markdown


@respx.mock
async def test_httpx_fetcher_blocks_private_first_url() -> None:
    # The entry URL itself resolves to loopback: the fetch must be refused
    # before any outbound request is made (no SSRF to an internal service).
    route = respx.get("https://internal.test/").mock(return_value=httpx.Response(200, text="x"))

    with patch("app.utils.url_safety._resolve", _resolver({"internal.test": "127.0.0.1"})):
        with pytest.raises(FetchError):
            await HttpxFetcher().fetch("https://internal.test/")

    assert route.called is False


@respx.mock
async def test_httpx_fetcher_blocks_redirect_to_private_address() -> None:
    # A public entry URL that 302s to an internal address must be refused at
    # the redirect hop, not followed. httpx's own follow_redirects is disabled;
    # each hop is re-validated by the SSRF guard.
    respx.get("https://public.test/").mock(
        return_value=httpx.Response(302, headers={"location": "https://internal.test/secret"})
    )
    internal = respx.get("https://internal.test/secret").mock(
        return_value=httpx.Response(200, text="secret")
    )

    resolver = _resolver({"public.test": "93.184.216.34", "internal.test": "127.0.0.1"})
    with patch("app.utils.url_safety._resolve", resolver):
        with pytest.raises(FetchError):
            await HttpxFetcher().fetch("https://public.test/")

    assert internal.called is False


@respx.mock
async def test_httpx_fetcher_follows_public_redirect() -> None:
    # Control case: a redirect to another public host is followed normally.
    respx.get("https://public.test/").mock(
        return_value=httpx.Response(302, headers={"location": "https://other-public.test/page"})
    )
    respx.get("https://other-public.test/page").mock(
        return_value=httpx.Response(200, text="<html><body><main>ok</main></body></html>")
    )

    resolver = _resolver({"public.test": "93.184.216.34", "other-public.test": "93.184.216.35"})
    with patch("app.utils.url_safety._resolve", resolver):
        markdown = await HttpxFetcher().fetch("https://public.test/")

    assert "ok" in markdown
