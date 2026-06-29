"""Unit tests for app.utils.search — multi-provider search waterfall.

The flat ``app.utils.search_utils`` module was replaced by the
``app.utils.search`` package (engine, models, providers, budget).

These tests cover the public surface exported from ``app.utils.search``:
  - ``perform_search``        — cached entry point; returns web/images/answer dict
  - ``search_for_research``   — cached entry point; returns {"results": [...]}

Provider-level unit tests live in ``tests/unit/utils/search/``.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.search import perform_search, search_for_research
from app.utils.search.models import SearchResponse, SearchResultItem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bypass_cache(cached: Any) -> Any:
    """Return the undecorated coroutine behind the @Cacheable wrapper, so tests
    exercise the real function rather than a cached result."""
    return cached.__wrapped__


def _make_response(
    results: list[dict] | None = None,
    answer: str = "",
    images: list[str] | None = None,
    provider: str = "tavily",
) -> SearchResponse:
    """Build a SearchResponse from plain dicts (mirrors what providers return)."""
    items = [SearchResultItem(**r) for r in (results or [])]
    return SearchResponse(
        results=items,
        answer=answer,
        images=images or [],
        provider=provider,
    )


# ---------------------------------------------------------------------------
# perform_search
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPerformSearch:
    """Tests for perform_search (the waterfall entry point, cache bypassed)."""

    @patch("app.utils.search.SearchEngine")
    async def test_returns_correct_shape(self, mock_engine_cls: MagicMock) -> None:
        """perform_search maps SearchResponse to the wire dict consumed by the agent."""
        response = _make_response(
            results=[{"url": "https://a.com", "title": "A"}],
            answer="42",
            images=["https://img.example.com/1.png"],
            provider="tavily",
        )
        mock_engine_cls.return_value.search = AsyncMock(return_value=response)

        fn = _bypass_cache(perform_search)
        result = await fn(query="hello", count=5)

        assert result["query"] == "hello"
        assert result["answer"] == "42"
        assert result["images"] == ["https://img.example.com/1.png"]
        assert result["provider"] == "tavily"
        assert len(result["web"]) == 1
        assert result["web"][0]["url"] == "https://a.com"

    @patch("app.utils.search.SearchEngine")
    async def test_empty_response_returns_empty_lists(self, mock_engine_cls: MagicMock) -> None:
        """When all providers fail/skip, perform_search returns empty collections."""
        mock_engine_cls.return_value.search = AsyncMock(return_value=SearchResponse())

        fn = _bypass_cache(perform_search)
        result = await fn(query="empty", count=3)

        assert result["web"] == []
        assert result["images"] == []
        assert result["answer"] == ""
        assert result["query"] == "empty"
        assert result["provider"] is None

    @patch("app.utils.search.SearchEngine")
    async def test_web_items_are_model_dumpd(self, mock_engine_cls: MagicMock) -> None:
        """Each web result is a dict (model_dump), not a SearchResultItem."""
        response = _make_response(
            results=[{"url": "https://b.com", "title": "B", "content": "Some text"}],
        )
        mock_engine_cls.return_value.search = AsyncMock(return_value=response)

        fn = _bypass_cache(perform_search)
        result = await fn(query="q", count=1)

        item = result["web"][0]
        assert isinstance(item, dict)
        assert item["url"] == "https://b.com"
        assert item["content"] == "Some text"

    @patch("app.utils.search.SearchEngine")
    async def test_engine_called_with_query_and_count(self, mock_engine_cls: MagicMock) -> None:
        """SearchEngine.search is called with the exact query and count."""
        mock_engine_cls.return_value.search = AsyncMock(return_value=SearchResponse())

        fn = _bypass_cache(perform_search)
        await fn(query="pytest rocks", count=7)

        mock_engine_cls.return_value.search.assert_awaited_once_with("pytest rocks", 7)

    @patch("app.utils.search.SearchEngine")
    async def test_multiple_results_all_returned(self, mock_engine_cls: MagicMock) -> None:
        """All results from the provider are included, not just the first."""
        response = _make_response(
            results=[
                {"url": "https://one.com", "title": "One"},
                {"url": "https://two.com", "title": "Two"},
                {"url": "https://three.com", "title": "Three"},
            ],
        )
        mock_engine_cls.return_value.search = AsyncMock(return_value=response)

        fn = _bypass_cache(perform_search)
        result = await fn(query="many", count=3)

        assert len(result["web"]) == 3
        urls = [item["url"] for item in result["web"]]
        assert "https://one.com" in urls
        assert "https://three.com" in urls


# ---------------------------------------------------------------------------
# search_for_research
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchForResearch:
    """Tests for search_for_research (deep-research entry point, cache bypassed)."""

    @patch("app.utils.search.SearchEngine")
    async def test_returns_results_key(self, mock_engine_cls: MagicMock) -> None:
        """search_for_research returns {results: [...]} — the shape research tools expect."""
        response = _make_response(
            results=[{"url": "https://r.com", "title": "R"}],
        )
        mock_engine_cls.return_value.search = AsyncMock(return_value=response)

        fn = _bypass_cache(search_for_research)
        result = await fn(query="deep", count=5)

        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["url"] == "https://r.com"

    @patch("app.utils.search.SearchEngine")
    async def test_empty_response_returns_empty_results(self, mock_engine_cls: MagicMock) -> None:
        mock_engine_cls.return_value.search = AsyncMock(return_value=SearchResponse())

        fn = _bypass_cache(search_for_research)
        result = await fn(query="nothing", count=5)

        assert result == {"results": []}

    @patch("app.utils.search.SearchEngine")
    async def test_does_not_include_answer_or_images(self, mock_engine_cls: MagicMock) -> None:
        """search_for_research only exposes results, not answer/images/provider."""
        response = _make_response(
            results=[{"url": "https://x.com"}],
            answer="irrelevant",
            images=["https://img.com/1.png"],
        )
        mock_engine_cls.return_value.search = AsyncMock(return_value=response)

        fn = _bypass_cache(search_for_research)
        result = await fn(query="x", count=1)

        assert set(result.keys()) == {"results"}

    @patch("app.utils.search.SearchEngine")
    async def test_default_count_is_five(self, mock_engine_cls: MagicMock) -> None:
        """search_for_research defaults count to 5 when not supplied."""
        mock_engine_cls.return_value.search = AsyncMock(return_value=SearchResponse())

        fn = _bypass_cache(search_for_research)
        await fn(query="default")

        mock_engine_cls.return_value.search.assert_awaited_once_with("default", 5)


# ---------------------------------------------------------------------------
# TavilyProvider
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTavilyProvider:
    """Unit tests for TavilyProvider (is_configured + search mapping)."""

    def test_is_configured_true_when_key_present(self) -> None:
        from app.utils.search.providers.tavily import TavilyProvider

        with patch("app.utils.search.providers.tavily.settings") as mock_settings:
            mock_settings.TAVILY_API_KEY = "tvly-key"  # pragma: allowlist secret
            assert TavilyProvider().is_configured() is True

    def test_is_configured_false_when_key_empty(self) -> None:
        from app.utils.search.providers.tavily import TavilyProvider

        with patch("app.utils.search.providers.tavily.settings") as mock_settings:
            mock_settings.TAVILY_API_KEY = ""
            assert TavilyProvider().is_configured() is False

    async def test_search_maps_payload_to_search_response(self) -> None:
        from app.utils.search.providers.tavily import TavilyProvider

        payload = {
            "results": [
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "content": "Some content",
                    "score": 0.9,
                    "favicon": "https://example.com/fav.ico",
                }
            ],
            "answer": "The answer",
            "images": ["https://img.example.com/1.png"],
        }
        provider = TavilyProvider()
        # Bypass asyncio.to_thread and client creation
        with (
            patch(
                "app.utils.search.providers.tavily.asyncio.to_thread", new_callable=AsyncMock
            ) as mock_thread,
            patch("app.utils.search.providers.tavily.settings") as mock_settings,
        ):
            mock_settings.TAVILY_API_KEY = "tvly-key"  # pragma: allowlist secret
            mock_thread.return_value = payload
            result = await provider.search("test query", 5)

        assert result.provider == "tavily"
        assert result.answer == "The answer"
        assert result.images == ["https://img.example.com/1.png"]
        assert len(result.results) == 1
        assert result.results[0].url == "https://example.com"
        assert result.results[0].score == 0.9

    async def test_search_filters_items_without_url(self) -> None:
        from app.utils.search.providers.tavily import TavilyProvider

        payload = {
            "results": [
                {"url": "https://good.com", "title": "Good"},
                {"url": "", "title": "No URL"},  # should be filtered
                {"title": "Missing URL key"},  # should be filtered
            ],
            "answer": "",
            "images": [],
        }
        with (
            patch(
                "app.utils.search.providers.tavily.asyncio.to_thread", new_callable=AsyncMock
            ) as mock_thread,
            patch("app.utils.search.providers.tavily.settings") as mock_settings,
        ):
            mock_settings.TAVILY_API_KEY = "tvly-key"  # pragma: allowlist secret
            mock_thread.return_value = payload
            result = await TavilyProvider().search("q", 3)

        assert len(result.results) == 1
        assert result.results[0].url == "https://good.com"


# ---------------------------------------------------------------------------
# DuckDuckGoProvider
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDuckDuckGoProvider:
    """Unit tests for DuckDuckGoProvider (always available, HTML scrape)."""

    def test_is_configured_always_true(self) -> None:
        from app.utils.search.providers.duckduckgo import DuckDuckGoProvider

        assert DuckDuckGoProvider().is_configured() is True

    @patch("app.utils.search.providers.duckduckgo.httpx.AsyncClient")
    async def test_search_returns_parsed_results(self, mock_client_cls: MagicMock) -> None:
        from app.utils.search.providers.duckduckgo import DuckDuckGoProvider

        html = """
        <html><body><table>
        <tr class="result-sponsored">
            <td><a class="result-link" href="https://example.com">Example Title</a></td>
        </tr>
        <tr><td class="result-snippet">A snippet about example</td></tr>
        </table></body></html>
        """
        response = MagicMock()
        response.text = html
        response.status_code = 200
        response.raise_for_status = MagicMock()

        client_inst = AsyncMock()
        client_inst.post = AsyncMock(return_value=response)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=client_inst)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = ctx

        result = await DuckDuckGoProvider().search("test", 5)

        assert result.provider == "duckduckgo"
        assert len(result.results) >= 1
        assert result.results[0].url == "https://example.com"

    @patch("app.utils.search.providers.duckduckgo.httpx.AsyncClient")
    async def test_search_skips_non_http_links(self, mock_client_cls: MagicMock) -> None:
        from app.utils.search.providers.duckduckgo import DuckDuckGoProvider

        html = """
        <html><body><table>
        <tr class="result-sponsored">
            <td><a class="result-link" href="javascript:void(0)">Bad Link</a></td>
        </tr>
        </table></body></html>
        """
        response = MagicMock()
        response.text = html
        response.status_code = 200
        response.raise_for_status = MagicMock()

        client_inst = AsyncMock()
        client_inst.post = AsyncMock(return_value=response)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=client_inst)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = ctx

        result = await DuckDuckGoProvider().search("test", 5)
        assert result.results == []
