"""Provider response-parsing tests.

Each provider is exercised against a representative upstream payload (mocked with
respx — no real network) to prove the JSON/HTML is mapped onto the shared
``SearchResultItem`` shape correctly.
"""

import httpx
import pytest
import respx

from app.utils.search.providers.brave import BraveProvider
from app.utils.search.providers.duckduckgo import DuckDuckGoProvider
from app.utils.search.providers.exa import ExaProvider
from app.utils.search.providers.searxng import SearxngProvider

_EXA_PAYLOAD = {
    "results": [
        {
            "url": "https://example.com/a",
            "title": "Result A",
            "text": "Body of A",
            "score": 0.91,
            "publishedDate": "2026-01-02",
            "author": "Someone",
        },
        {"title": "Missing URL is dropped", "text": "no url"},
    ]
}

_BRAVE_PAYLOAD = {
    "web": {
        "results": [
            {
                "url": "https://example.com/b",
                "title": "Result B",
                "description": "Snippet B",
                "age": "2 days ago",
            }
        ]
    }
}

_SEARXNG_PAYLOAD = {
    "results": [
        {
            "url": "https://example.com/c",
            "title": "Result C",
            "content": "Snippet C",
            "score": 1.4,
            "publishedDate": "2026-06-01",
        }
    ]
}

_DDG_HTML = """
<html><body><table>
<tr><td><a class="result-link" href="https://example.com/d">Result D</a></td></tr>
<tr><td>Snippet D</td></tr>
<tr><td><a class="result-link" href="/relative-skipped">Relative</a></td></tr>
</table></body></html>
"""


@respx.mock
async def test_exa_parses_results_and_drops_urlless() -> None:
    respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(200, json=_EXA_PAYLOAD)
    )

    response = await ExaProvider().search("query", 5)

    assert response.provider == "exa"
    assert len(response.results) == 1
    item = response.results[0]
    assert item.url == "https://example.com/a"
    assert item.title == "Result A"
    assert item.content == "Body of A"
    assert item.score == pytest.approx(0.91)
    assert item.published_date == "2026-01-02"


@respx.mock
async def test_brave_parses_nested_web_results() -> None:
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json=_BRAVE_PAYLOAD)
    )

    response = await BraveProvider().search("query", 5)

    assert response.provider == "brave"
    assert len(response.results) == 1
    item = response.results[0]
    assert item.url == "https://example.com/b"
    assert item.content == "Snippet B"
    assert item.published_date == "2 days ago"


@respx.mock
async def test_searxng_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.utils.search.providers.searxng.settings.SEARXNG_BASE_URL",
        "https://searxng.internal",
    )
    respx.get("https://searxng.internal/search").mock(
        return_value=httpx.Response(200, json=_SEARXNG_PAYLOAD)
    )

    response = await SearxngProvider().search("query", 5)

    assert response.provider == "searxng"
    assert len(response.results) == 1
    item = response.results[0]
    assert item.url == "https://example.com/c"
    assert item.content == "Snippet C"
    assert item.score == pytest.approx(1.4)


@respx.mock
async def test_duckduckgo_parses_html_and_skips_relative() -> None:
    respx.post("https://lite.duckduckgo.com/lite/").mock(
        return_value=httpx.Response(200, text=_DDG_HTML)
    )

    response = await DuckDuckGoProvider().search("query", 5)

    assert response.provider == "duckduckgo"
    urls = [item.url for item in response.results]
    assert "https://example.com/d" in urls
    assert all(url.startswith("http") for url in urls)


@respx.mock
async def test_duckduckgo_treats_bot_challenge_as_empty() -> None:
    respx.post("https://lite.duckduckgo.com/lite/").mock(
        return_value=httpx.Response(200, text="If you think bots use DuckDuckGo...")
    )

    response = await DuckDuckGoProvider().search("query", 5)

    assert response.is_empty
