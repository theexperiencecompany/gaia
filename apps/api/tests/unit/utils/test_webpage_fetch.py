"""Webpage fetch failover behaviour and the httpx engine's HTML→markdown parse."""

import httpx
import pytest
import respx

from app.utils import webpage_fetch
from app.utils.exceptions import FetchError
from app.utils.webpage_fetch import HttpxFetcher, WebpageFetcher


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


async def test_returns_first_successful_engine(monkeypatch):
    primary = FakeFetcher("primary", result="# content")
    secondary = FakeFetcher("secondary", result="should not run")
    monkeypatch.setattr(webpage_fetch, "_FETCHERS", [primary, secondary])

    result = await webpage_fetch._fetch_first_success("https://example.com")

    assert result == "# content"
    assert secondary.called is False


async def test_fails_over_to_next_engine(monkeypatch):
    broken = FakeFetcher("broken", result=None)
    backup = FakeFetcher("backup", result="recovered")
    monkeypatch.setattr(webpage_fetch, "_FETCHERS", [broken, backup])

    result = await webpage_fetch._fetch_first_success("https://example.com")

    assert broken.called is True
    assert result == "recovered"


async def test_skips_unconfigured_engine(monkeypatch):
    disabled = FakeFetcher("disabled", configured=False, result="never")
    backup = FakeFetcher("backup", result="ok")
    monkeypatch.setattr(webpage_fetch, "_FETCHERS", [disabled, backup])

    result = await webpage_fetch._fetch_first_success("https://example.com")

    assert disabled.called is False
    assert result == "ok"


async def test_raises_when_all_engines_fail(monkeypatch):
    monkeypatch.setattr(
        webpage_fetch,
        "_FETCHERS",
        [FakeFetcher("a", result=None), FakeFetcher("b", result=None)],
    )

    with pytest.raises(FetchError):
        await webpage_fetch._fetch_first_success("https://example.com")


@respx.mock
async def test_httpx_fetcher_extracts_main_content_to_markdown():
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
