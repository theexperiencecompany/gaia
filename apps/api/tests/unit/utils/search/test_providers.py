"""Provider response-parsing tests.

Each provider is exercised against a representative upstream payload (mocked with
respx — no real network) to prove the JSON/HTML is mapped onto the shared
SearchResultItem shape correctly.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.config.settings import settings
from app.services.providers import provider_credentials_service
from app.services.providers.provider_credentials_service import ProviderConfig, resolve
from app.utils.log_identifiers import user_text_shape
from app.utils.search.providers.brave import BraveProvider
from app.utils.search.providers.duckduckgo import DuckDuckGoProvider
from app.utils.search.providers.exa import ExaProvider
from app.utils.search.providers.searxng import SearxngProvider
from tests.helpers import InMemoryCredentialStore

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

_ENV_EXA_KEY = "env-exa-key"
_ENV_BRAVE_KEY = "env-brave-key"
_EXA_ENDPOINT = "https://api.exa.ai/search"
_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


@pytest.fixture(autouse=True)
def _env_search_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure Exa and Brave from the environment; tests that need a stored key override it."""
    monkeypatch.setattr(settings, "EXA_API_KEY", _ENV_EXA_KEY)
    monkeypatch.setattr(settings, "BRAVE_API_KEY", _ENV_BRAVE_KEY)


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
    assert item.favicon == ""


@respx.mock
async def test_exa_null_fields_fall_back_to_defaults() -> None:
    """Exa documents every field but url as nullable; each null maps to its default."""
    payload = {
        "results": [
            {
                "url": "https://example.com/n",
                "title": None,
                "text": None,
                "score": None,
                "publishedDate": None,
                "favicon": None,
            },
            {"url": "", "title": "empty url is dropped"},
        ]
    }
    respx.post("https://api.exa.ai/search").mock(return_value=httpx.Response(200, json=payload))

    response = await ExaProvider().search("query", 5)

    assert [item.model_dump() for item in response.results] == [
        {
            "url": "https://example.com/n",
            "title": "",
            "content": "",
            "score": 0.5,
            "published_date": "",
            "favicon": "",
        }
    ]


@respx.mock
async def test_exa_zero_score_is_kept() -> None:
    """A real 0.0 score is a value, not an absence — it must not become 0.5."""
    payload = {"results": [{"url": "https://example.com/z", "score": 0.0}]}
    respx.post("https://api.exa.ai/search").mock(return_value=httpx.Response(200, json=payload))

    response = await ExaProvider().search("query", 5)

    assert response.results[0].score == 0.0


@respx.mock
async def test_brave_parses_nested_web_results() -> None:
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json=_BRAVE_PAYLOAD)
    )

    response = await BraveProvider().search("query", 5)

    assert response.provider == "brave"
    assert len(response.results) == 1
    item = response.results[0]
    assert item.model_dump() == {
        "url": "https://example.com/b",
        "title": "Result B",
        "content": "Snippet B",
        "score": 0.5,
        "published_date": "2 days ago",
        "favicon": "",
    }


@respx.mock
async def test_brave_favicon_and_null_fields() -> None:
    """The meta_url favicon is read; null title/description/age/meta_url map to empty strings."""
    payload = {
        "web": {
            "results": [
                {
                    "url": "https://example.com/f",
                    "title": "F",
                    "meta_url": {"favicon": "https://example.com/fav.ico", "scheme": "https"},
                },
                {
                    "url": "https://example.com/n",
                    "title": None,
                    "description": None,
                    "age": None,
                    "meta_url": None,
                },
                {"title": "no url is dropped"},
            ]
        }
    }
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json=payload)
    )

    response = await BraveProvider().search("query", 5)

    assert [item.model_dump() for item in response.results] == [
        {
            "url": "https://example.com/f",
            "title": "F",
            "content": "",
            "score": 0.5,
            "published_date": "",
            "favicon": "https://example.com/fav.ico",
        },
        {
            "url": "https://example.com/n",
            "title": "",
            "content": "",
            "score": 0.5,
            "published_date": "",
            "favicon": "",
        },
    ]


@respx.mock
async def test_brave_without_web_section_is_empty() -> None:
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json={"query": {"original": "q"}})
    )

    response = await BraveProvider().search("query", 5)

    assert response.is_empty
    assert response.provider == "brave"


@respx.mock
async def test_searxng_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "https://searxng.internal")
    respx.get("https://searxng.internal/search").mock(
        return_value=httpx.Response(200, json=_SEARXNG_PAYLOAD)
    )

    response = await SearxngProvider().search("query", 5)

    assert response.provider == "searxng"
    assert len(response.results) == 1
    item = response.results[0]
    assert item.model_dump() == {
        "url": "https://example.com/c",
        "title": "Result C",
        "content": "Snippet C",
        "score": pytest.approx(1.4),
        "published_date": "2026-06-01",
        "favicon": "",
    }


@respx.mock
async def test_searxng_under_a_path_with_a_trailing_slash_searches_that_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "https://tools.example/searX/")
    route = respx.get("https://tools.example/searX/search").mock(
        return_value=httpx.Response(200, json=_SEARXNG_PAYLOAD)
    )

    await SearxngProvider().search("query", 5)

    assert route.called


@respx.mock
async def test_searxng_null_fields_count_cap_and_null_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Null fields map to defaults, count caps results, and null results is empty."""
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "https://searxng.internal/")
    payload = {
        "results": [
            {
                "url": "https://example.com/1",
                "title": None,
                "content": None,
                "score": None,
                "publishedDate": None,
            },
            {"url": "https://example.com/2", "title": "Two"},
            {"url": "https://example.com/3", "title": "Beyond count"},
        ]
    }
    route = respx.get("https://searxng.internal/search").mock(
        side_effect=[
            httpx.Response(200, json=payload),
            httpx.Response(200, json={"results": None}),
        ]
    )

    response = await SearxngProvider().search("query", 2)

    assert route.calls[0].request.url.params["format"] == "json"
    assert [item.model_dump() for item in response.results] == [
        {
            "url": "https://example.com/1",
            "title": "",
            "content": "",
            "score": 0.5,
            "published_date": "",
            "favicon": "",
        },
        {
            "url": "https://example.com/2",
            "title": "Two",
            "content": "",
            "score": 0.5,
            "published_date": "",
            "favicon": "",
        },
    ]
    assert (await SearxngProvider().search("query", 2)).is_empty


@respx.mock
async def test_duckduckgo_parses_html_and_skips_relative() -> None:
    respx.post("https://lite.duckduckgo.com/lite/").mock(
        return_value=httpx.Response(200, text=_DDG_HTML)
    )

    response = await DuckDuckGoProvider().search("query", 5)

    assert response.provider == "duckduckgo"
    assert [item.model_dump() for item in response.results] == [
        {
            "url": "https://example.com/d",
            "title": "Result D",
            "content": "Snippet D",
            "score": 0.5,
            "published_date": "",
            "favicon": "",
        }
    ]


@respx.mock
async def test_duckduckgo_treats_bot_challenge_as_empty() -> None:
    respx.post("https://lite.duckduckgo.com/lite/").mock(
        return_value=httpx.Response(200, text="If you think bots use DuckDuckGo...")
    )

    response = await DuckDuckGoProvider().search("query", 5)

    assert response.is_empty


@respx.mock
async def test_duckduckgo_bot_challenge_logs_the_query_shape_not_its_words() -> None:
    respx.post("https://lite.duckduckgo.com/lite/").mock(
        return_value=httpx.Response(202, text="challenge")
    )

    with patch("app.utils.search.providers.duckduckgo.log") as log:
        await DuckDuckGoProvider().search("my divorce papers", 5)

    log.warning.assert_called_once_with(
        "DuckDuckGo served a bot-challenge page", query=user_text_shape("my divorce papers")
    )


# ---------------------------------------------------------------------------
# Credentials: the store on self-host, the environment alone in production
# ---------------------------------------------------------------------------


@respx.mock
async def test_selfhost_exa_and_brave_search_with_the_stored_key_over_env(
    selfhost_credential_store: InMemoryCredentialStore,
) -> None:
    selfhost_credential_store.save("exa", api_key="stored-exa-key")
    selfhost_credential_store.save("brave", api_key="stored-brave-key")
    exa_route = respx.post(_EXA_ENDPOINT).mock(return_value=httpx.Response(200, json=_EXA_PAYLOAD))
    brave_route = respx.get(_BRAVE_ENDPOINT).mock(
        return_value=httpx.Response(200, json=_BRAVE_PAYLOAD)
    )

    await ExaProvider().search("query", 5)
    await BraveProvider().search("query", 5)

    assert exa_route.calls.last.request.headers["x-api-key"] == "stored-exa-key"
    assert brave_route.calls.last.request.headers["X-Subscription-Token"] == "stored-brave-key"


async def test_selfhost_search_providers_report_a_stored_credential_as_configured(
    selfhost_credential_store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    for field in ("EXA_API_KEY", "BRAVE_API_KEY", "SEARXNG_BASE_URL"):
        monkeypatch.setattr(settings, field, None)
    providers = (ExaProvider(), BraveProvider(), SearxngProvider())
    assert not any(p.is_configured() for p in providers)

    selfhost_credential_store.save("exa", api_key="stored-exa-key")
    selfhost_credential_store.save("brave", api_key="stored-brave-key")
    selfhost_credential_store.save("searxng", base_url="http://searxng:8080")
    for provider in providers:
        await resolve(provider.name)

    assert all(p.is_configured() for p in providers)


@respx.mock
async def test_selfhost_searxng_queries_the_stored_server(
    selfhost_credential_store: InMemoryCredentialStore,
) -> None:
    selfhost_credential_store.save("searxng", base_url="http://searxng.lan:8080/")
    route = respx.get("http://searxng.lan:8080/search").mock(
        return_value=httpx.Response(200, json=_SEARXNG_PAYLOAD)
    )

    response = await SearxngProvider().search("query", 5)

    assert route.called
    assert response.results[0].url == "https://example.com/c"


@respx.mock
async def test_production_exa_and_brave_use_env_keys_and_never_read_the_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "workos")
    store_read = AsyncMock(side_effect=AssertionError("production read the credential store"))
    monkeypatch.setattr(
        provider_credentials_service.provider_credentials_repository, "find_by_provider", store_read
    )
    for name in ("exa", "brave"):
        monkeypatch.setitem(
            provider_credentials_service.resolved_configs,
            name,
            ProviderConfig(api_key="stored-key", base_url=None, model=None, preset=None),
        )
    exa_route = respx.post(_EXA_ENDPOINT).mock(return_value=httpx.Response(200, json=_EXA_PAYLOAD))
    brave_route = respx.get(_BRAVE_ENDPOINT).mock(
        return_value=httpx.Response(200, json=_BRAVE_PAYLOAD)
    )

    assert ExaProvider().is_configured() and BraveProvider().is_configured()
    await ExaProvider().search("query", 5)
    await BraveProvider().search("query", 5)

    assert exa_route.calls.last.request.headers["x-api-key"] == _ENV_EXA_KEY
    assert brave_route.calls.last.request.headers["X-Subscription-Token"] == _ENV_BRAVE_KEY
    store_read.assert_not_awaited()
