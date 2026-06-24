"""Webpage fetch failover behaviour and the httpx engine's HTML->markdown parse."""

import httpx
import pytest
import respx

from app.utils.exceptions import FetchError
from app.utils.webpage_fetch import HttpxFetcher, WebpageFetcher, _fetch_first_success


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
