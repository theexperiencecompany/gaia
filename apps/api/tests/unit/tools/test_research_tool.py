"""Unit tests for app/agents/tools/research_tool.py — deep_research tool.

Covers:
- User auth check (no user_id)
- Invalid depth
- Cache hit path
- No sources found
- Successful research with fetch fallback chains
- Exception in main try block
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.agents.tools.research_tool import ResearchSource, _fetch_source_contents
from app.constants.cache import ONE_HOUR_TTL
from app.constants.log_tags import LogTag
from app.constants.search import (
    CRAWL4AI_PAGE_TIMEOUT_MS,
    DEEP_RESEARCH_CRAWL4AI_BATCH_TIMEOUT_SECONDS,
    DEEP_RESEARCH_CRAWL4AI_SEMAPHORE_COUNT,
)
from app.utils.crawl4ai_utils import CrawlBatchParams
from app.utils.research_utils import RankedUrl
from app.utils.search.models import ResearchSearchResult, SearchResultItem

MODULE = "app.agents.tools.research_tool"


def _make_config(user_id: str | None = "user-123") -> dict[str, Any]:
    """Build a minimal RunnableConfig-like dict."""
    return {"configurable": {"user_id": user_id}}


def _no_user_config() -> dict[str, Any]:
    return {"configurable": {}}


class _Clock:
    """Stands in for the module's time module with a scripted wall clock."""

    def __init__(self, *ticks: float) -> None:
        self._ticks = iter(ticks)

    def time(self) -> float:
        return next(self._ticks)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_stream_writer():
    """Patch get_stream_writer so the tool can call writer() without LangGraph context."""
    writer = MagicMock()
    with patch(f"{MODULE}.get_stream_writer", return_value=writer):
        yield writer


@pytest.fixture(autouse=True)
def _patch_log():
    with patch(f"{MODULE}.log") as mock_log:
        yield mock_log


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDeepResearch:
    """Tests for the deep_research tool function."""

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value=None)
    async def test_no_user_returns_error(self, _mock_uid: MagicMock, _patch_log: MagicMock) -> None:
        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 2, "focus_areas": None},
            config=_no_user_config(),
        )
        assert result["error"] == "User authentication required"
        assert result["data"] is None
        # Every run stamps the wide event with the tool and the action it ran under.
        _patch_log.set.assert_any_call(tool={"name": "deep_research", "action": "research"})

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    async def test_invalid_depth_returns_error(self, mock_uid: MagicMock) -> None:
        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 5, "focus_areas": None},
            config=_make_config(),
        )
        assert "Invalid depth" in result["error"]
        assert result["data"] is None
        # The caller's user is read from the runnable config the tool was handed.
        assert mock_uid.call_args.args[0]["configurable"]["user_id"] == "user-123"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache")
    async def test_cache_hit(
        self,
        mock_get_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
        _patch_stream_writer: MagicMock,
    ) -> None:
        cached = {
            "query": "test",
            "sources": [{"url": "https://a.com"}],
            "source_count": 1,
        }
        mock_get_cache.return_value = cached

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 2, "focus_areas": None},
            config=_make_config(),
        )
        assert result["cached"] is True
        assert result["query"] == "test"
        _patch_stream_writer.assert_any_call({"progress": "Loaded research from cache!"})

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    async def test_no_sources_found(
        self,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
    ) -> None:
        mock_decompose.return_value = ["sub-q1"]
        mock_ddg.return_value = ResearchSearchResult(results=[])
        mock_rank.return_value = []

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "obscure topic", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        # Pinned whole: an empty search is exactly when a model invents links,
        # so the refusal has to name the ban rather than only report the miss.
        assert result["error"] == (
            "Search returned no results for the given query. "
            "No URLs were found: do not fabricate links. "
            "Try broadening the search or inform the user that no sources were found."
        )
        assert result["data"] is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    async def test_successful_research_crawl4ai(
        self,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
        _patch_stream_writer: MagicMock,
    ) -> None:
        mock_decompose.return_value = ["sub-q1", "sub-q2"]
        mock_ddg.return_value = ResearchSearchResult(
            results=[SearchResultItem(url="https://example.com")]
        )
        mock_rank.return_value = [
            RankedUrl(
                url="https://example.com", title="", snippet="A snippet", score=1.0, appearances=1
            ),
            RankedUrl(
                url="https://example2.com",
                title="",
                snippet="Another snippet",
                score=1.0,
                appearances=1,
            ),
        ]
        mock_batch_crawl4ai.return_value = (
            {
                "https://example.com": "Full page content",
                "https://example2.com": "Full page content",
            },
            {},
        )

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {
                "query": "AI trends",
                "scope": "technical",
                "depth": 1,
                "focus_areas": ["performance"],
            },
            config=_make_config(),
        )
        assert result["error"] is None
        assert result["cached"] is False
        assert result["source_count"] == 2
        assert len(result["sources"]) == 2
        assert result["query"] == "AI trends"
        assert result["scope"] == "technical"
        # The integrity note is what stops a research answer citing plausible
        # URLs the search never returned — the whole reason the source list is
        # handed over separately.
        assert result["integrity_note"] == (
            "All URLs in `sources` and `authoritative_urls` were returned by real search "
            "queries. Only cite URLs from this list; never invent or guess URLs."
        )
        # The progress frame is keyed "progress"; the UI reads that key and
        # nothing else, so a renamed key is a silently blank progress line.
        progress = [
            call.args[0]["progress"]
            for call in _patch_stream_writer.call_args_list
            if isinstance(call.args[0], dict) and "progress" in call.args[0]
        ]
        assert "Found 2 unique sources, fetching full content..." in progress
        # What is cached and what is streamed is the frame itself, minus the two
        # per-call-site keys — a wrong key, payload or TTL is a silent miss.
        frame = {k: v for k, v in result.items() if k not in ("cached", "instructions")}
        mock_set_cache.assert_awaited_once_with("cache:key", frame, ttl=ONE_HOUR_TTL)
        _patch_stream_writer.assert_any_call({"research_data": frame})
        mock_get_cache.assert_awaited_once_with("cache:key")
        assert [s["content"] for s in result["sources"]] == ["Full page content"] * 2
        # The research-queries card renders found_urls; the fetch bar counts off
        # each source against the ranked total.
        _patch_stream_writer.assert_any_call(
            {
                "progress": "Found 2 unique sources, fetching full content...",
                "found_urls": ["https://example.com", "https://example2.com"],
            }
        )
        for frame in (
            "Fetching sources...",
            "Fetched source 1/2...",
            "Fetched source 2/2...",
        ):
            _patch_stream_writer.assert_any_call({"progress": frame})
        mock_batch_crawl4ai.assert_awaited_once_with(
            ["https://example.com", "https://example2.com"],
            CrawlBatchParams(
                page_timeout_ms=CRAWL4AI_PAGE_TIMEOUT_MS,
                total_timeout_seconds=DEEP_RESEARCH_CRAWL4AI_BATCH_TIMEOUT_SECONDS,
                semaphore_count=DEEP_RESEARCH_CRAWL4AI_SEMAPHORE_COUNT,
                context_name="crawl4ai",
                content_query="AI trends",
            ),
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    async def test_elapsed_seconds_is_the_measured_wall_time_to_two_decimals(
        self,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        _mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
        _patch_stream_writer: MagicMock,
    ) -> None:
        mock_decompose.return_value = ["sub-q1"]
        mock_ddg.return_value = ResearchSearchResult(
            results=[SearchResultItem(url="https://a.com")]
        )
        mock_rank.return_value = [
            RankedUrl(url="https://a.com", title="", snippet="s", score=1.0, appearances=1)
        ]
        mock_batch_crawl4ai.return_value = ({"https://a.com": "content"}, {})

        from app.agents.tools.research_tool import deep_research

        with patch(f"{MODULE}.time", _Clock(1000.0, 1002.3456)):
            result = await deep_research.ainvoke(
                {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
                config=_make_config(),
            )

        assert result["elapsed_seconds"] == 2.35
        _patch_stream_writer.assert_any_call(
            {"progress": "Research complete! 1 sources fetched (0 failed) in 2.35s"}
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(
        f"{MODULE}.batch_fetch_with_crawl4ai",
        new_callable=AsyncMock,
    )
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
    async def test_crawl4ai_fails_falls_back_to_httpx(
        self,
        mock_httpx: AsyncMock,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
        _patch_stream_writer: MagicMock,
    ) -> None:
        mock_decompose.return_value = ["sub-q1"]
        mock_ddg.return_value = ResearchSearchResult(
            results=[SearchResultItem(url="https://a.com")]
        )
        mock_rank.return_value = [
            RankedUrl(url="https://a.com", title="", snippet="snip", score=1.0, appearances=1)
        ]
        mock_batch_crawl4ai.return_value = ({}, {"https://a.com": "crawl fail"})
        mock_httpx.return_value = "httpx content"

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] is None
        assert result["sources"][0]["content"] == "httpx content"
        mock_httpx.assert_awaited_once_with("https://a.com")
        _patch_stream_writer.assert_any_call({"progress": "Fetched source 1/1..."})

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(
        f"{MODULE}.batch_fetch_with_crawl4ai",
        new_callable=AsyncMock,
    )
    @patch(
        f"{MODULE}.fetch_with_httpx",
        new_callable=AsyncMock,
        side_effect=Exception("fail"),
    )
    @pytest.mark.parametrize(
        ("crawl_errors", "expected_fetch_error"),
        [
            ({"https://a.com": "fail"}, "crawl4ai: fail; httpx: fail"),
            ({}, "crawl4ai: returned no content; httpx: fail"),
        ],
    )
    async def test_all_fetchers_fail_uses_snippet(
        self,
        _mock_httpx: AsyncMock,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        _mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
        _patch_log: MagicMock,
        crawl_errors: dict[str, str],
        expected_fetch_error: str,
    ) -> None:
        mock_decompose.return_value = ["sub-q1"]
        mock_ddg.return_value = ResearchSearchResult(
            results=[SearchResultItem(url="https://a.com")]
        )
        mock_rank.return_value = [
            RankedUrl(
                url="https://a.com",
                title="",
                snippet="Search snippet text",
                score=1.0,
                appearances=1,
            )
        ]
        mock_batch_crawl4ai.return_value = ({}, crawl_errors)

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] is None
        assert "Snippet only" in result["sources"][0]["content"]
        assert result["sources"][0]["fetch_error"] is not None
        assert result["sources"][0]["fetch_error"] == expected_fetch_error
        _patch_log.warning.assert_called_once_with(
            f"{LogTag.TOOL} All fetchers failed, using search snippet", url="https://a.com"
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(
        f"{MODULE}.batch_fetch_with_crawl4ai",
        new_callable=AsyncMock,
    )
    @patch(
        f"{MODULE}.fetch_with_httpx",
        new_callable=AsyncMock,
        side_effect=Exception("fail"),
    )
    async def test_all_fetchers_fail_no_snippet_returns_null_content(
        self,
        mock_httpx: AsyncMock,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
        _patch_log: MagicMock,
    ) -> None:
        mock_decompose.return_value = ["sub-q1"]
        mock_ddg.return_value = ResearchSearchResult(
            results=[SearchResultItem(url="https://a.com")]
        )
        mock_rank.return_value = [
            RankedUrl(url="https://a.com", title="", snippet="", score=1.0, appearances=1)
        ]
        mock_batch_crawl4ai.return_value = ({}, {"https://a.com": "fail"})

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        # No valid sources (content is None), so source_count = 0
        assert result["error"] is None
        assert result["source_count"] == 0
        # No valid sources means cache is NOT set
        mock_set_cache.assert_not_awaited()
        _patch_log.warning.assert_called_once_with(
            f"{LogTag.TOOL} All fetchers failed and no snippet to fall back on",
            url="https://a.com",
            error="crawl4ai: fail; httpx: fail",
        )

    @patch(
        f"{MODULE}.batch_fetch_with_crawl4ai",
        new_callable=AsyncMock,
        return_value=({}, {"https://a.com": "fail"}),
    )
    @patch(
        f"{MODULE}.fetch_with_httpx",
        new_callable=AsyncMock,
        side_effect=Exception("fail"),
    )
    async def test_a_source_with_no_content_carries_every_fetcher_error(
        self,
        _mock_httpx: AsyncMock,
        _mock_batch_crawl4ai: AsyncMock,
        _patch_log: MagicMock,
    ) -> None:
        """deep_research drops contentless sources, so the joined error is only visible on the fetch itself."""
        from app.agents.tools.research_tool import _fetch_sources

        ranked = [RankedUrl(url="https://a.com", title="", snippet="", score=1.0, appearances=1)]

        sources = await _fetch_sources(ranked, "test", MagicMock())

        assert sources[0].content is None
        assert sources[0].fetch_error == "crawl4ai: fail; httpx: fail"

    @patch(
        f"{MODULE}.batch_fetch_with_crawl4ai",
        new_callable=AsyncMock,
        return_value=({}, {"https://a.com": "fail", "https://b.com": "fail"}),
    )
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock, return_value="page")
    async def test_every_httpx_fallback_advances_the_fetch_counter(
        self,
        _mock_httpx: AsyncMock,
        _mock_batch_crawl4ai: AsyncMock,
    ) -> None:
        """Progress counts sources fetched so far, so the second httpx fallback reports 2/2."""
        from app.agents.tools.research_tool import _fetch_sources

        writer = MagicMock()
        ranked = [
            RankedUrl(url="https://a.com", title="", snippet="", score=1.0, appearances=1),
            RankedUrl(url="https://b.com", title="", snippet="", score=1.0, appearances=1),
        ]

        await _fetch_sources(ranked, "test", writer)

        writer.assert_any_call({"progress": "Fetched source 2/2..."})

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(
        f"{MODULE}.decompose_research_queries",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    )
    async def test_exception_in_main_try_block(
        self,
        mock_decompose: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
    ) -> None:
        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 2, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] == "boom"
        assert result["data"] is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    async def test_depth_3_max_sources(
        self,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
    ) -> None:
        """Depth 3 should pass max_urls=20 to rank_and_deduplicate_urls."""
        mock_decompose.return_value = ["q1"]
        mock_ddg.return_value = ResearchSearchResult(
            results=[SearchResultItem(url="https://a.com")]
        )
        mock_rank.return_value = [
            RankedUrl(url="https://a.com", title="", snippet="s", score=1.0, appearances=1)
        ]
        mock_batch_crawl4ai.return_value = ({"https://a.com": "content"}, {})

        from app.agents.tools.research_tool import deep_research

        await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 3, "focus_areas": None},
            config=_make_config(),
        )
        mock_rank.assert_called_once()
        _, kwargs = mock_rank.call_args
        assert kwargs.get("max_urls") == 20 or mock_rank.call_args[0][1] == 20

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    async def test_search_exceptions_counted_correctly(
        self,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
        _patch_stream_writer: MagicMock,
    ) -> None:
        """When some searches raise exceptions, successful_searches count is correct."""
        mock_decompose.return_value = ["q1", "q2", "q3"]
        mock_ddg.side_effect = [
            ResearchSearchResult(results=[SearchResultItem(url="https://a.com")]),
            RuntimeError("search failed"),
            ResearchSearchResult(results=[]),
        ]
        mock_rank.return_value = [
            RankedUrl(url="https://a.com", title="", snippet="s", score=1.0, appearances=1)
        ]
        mock_batch_crawl4ai.return_value = ({"https://a.com": "content"}, {})

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] is None
        # Check progress message: 1/3 searches returned results
        progress_calls = [
            call.args[0]
            for call in _patch_stream_writer.call_args_list
            if isinstance(call.args[0], dict) and "progress" in call.args[0]
        ]
        found = any("1/3" in p.get("progress", "") for p in progress_calls)
        assert found, (
            f"Expected '1/3 searches returned results' in progress calls: {progress_calls}"
        )
        assert {"progress": "Running 3 parallel searches..."} in progress_calls
        assert {
            "progress": "1/3 searches returned results (1 total URLs before deduplication)"
        } in progress_calls
        assert mock_ddg.await_args_list == [
            call("q1", count=5),
            call("q2", count=5),
            call("q3", count=5),
        ]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock, side_effect=Exception("fail"))
    async def test_snippet_fallback_counts_toward_fetch_progress(
        self,
        _mock_httpx: AsyncMock,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        _mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
        _patch_stream_writer: MagicMock,
    ) -> None:
        mock_decompose.return_value = ["q1"]
        mock_ddg.return_value = ResearchSearchResult(
            results=[SearchResultItem(url="https://a.com")]
        )
        mock_rank.return_value = [
            RankedUrl(url="https://a.com", title="", snippet="s", score=1.0, appearances=1),
            RankedUrl(url="https://b.com", title="", snippet="s", score=1.0, appearances=1),
            RankedUrl(url="https://c.com", title="", snippet="s", score=1.0, appearances=1),
        ]
        # a and c fetch; b falls back to its snippet between them.
        mock_batch_crawl4ai.return_value = (
            {"https://a.com": "content", "https://c.com": "content"},
            {},
        )

        from app.agents.tools.research_tool import deep_research

        await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )

        _patch_stream_writer.assert_any_call({"progress": "Fetched source 3/3..."})

    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    async def test_batch_crawl_is_tuned_for_deep_research_and_scoped_to_the_query(
        self,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        _mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
        _patch_stream_writer: MagicMock,
    ) -> None:
        """Deep research fetches its own way: its batch timeouts and concurrency come."""
        from app.agents.tools.research_tool import deep_research

        mock_decompose.return_value = ["q1"]
        mock_ddg.return_value = ResearchSearchResult(
            results=[SearchResultItem(url="https://a.com")]
        )
        mock_rank.return_value = [_ranked("https://a.com")]
        mock_batch_crawl4ai.return_value = ({"https://a.com": "content"}, {})

        await deep_research.ainvoke(
            {"query": "AI trends", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )

        urls, params = mock_batch_crawl4ai.await_args.args
        assert urls == ["https://a.com"]
        assert params == CrawlBatchParams(
            page_timeout_ms=CRAWL4AI_PAGE_TIMEOUT_MS,
            total_timeout_seconds=DEEP_RESEARCH_CRAWL4AI_BATCH_TIMEOUT_SECONDS,
            semaphore_count=DEEP_RESEARCH_CRAWL4AI_SEMAPHORE_COUNT,
            context_name="crawl4ai",
            content_query="AI trends",
        )


def _ranked(url: str, snippet: str = "s") -> RankedUrl:
    return RankedUrl(url=url, title="", snippet=snippet, score=1.0, appearances=1)


def _source(
    url: str, content: str | None, fetch_error: str | None, snippet: str = "s"
) -> ResearchSource:
    return ResearchSource(
        url=url,
        title="",
        snippet=snippet,
        score=1.0,
        appearances=1,
        content=content,
        fetch_error=fetch_error,
    )


class TestFetchSourceContents:
    """The tiering itself: crawl4ai batch -> httpx -> search snippet, and the.

    progress frames the UI counts sources with."""

    @staticmethod
    def _writer_frames(writer: MagicMock) -> list[dict[str, Any]]:
        return [call.args[0] for call in writer.call_args_list]

    async def test_batch_content_wins_and_reports_progress(self) -> None:
        writer = MagicMock()
        with patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock) as httpx:
            sources = await _fetch_source_contents(
                [_ranked("https://a.com")], {"https://a.com": "page body"}, {}, writer
            )

        httpx.assert_not_awaited()
        assert sources == [_source("https://a.com", "page body", None)]
        assert self._writer_frames(writer) == [{"progress": "Fetched source 1/1..."}]

    async def test_blank_batch_content_falls_through_to_httpx(self) -> None:
        """crawl4ai returning whitespace is a miss, not a hit -- a blank page."""
        writer = MagicMock()
        with patch(
            f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock, return_value="real body"
        ) as httpx:
            sources = await _fetch_source_contents(
                [_ranked("https://a.com")], {"https://a.com": "   "}, {}, writer
            )

        httpx.assert_awaited_once_with("https://a.com")
        assert sources[0].content == "real body"
        assert sources[0].fetch_error is None
        assert self._writer_frames(writer) == [{"progress": "Fetched source 1/1..."}]

    async def test_progress_counts_each_source_once_over_the_total(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The counter is what the UI renders as "2/3 fetched" -- it has to."""
        monkeypatch.setattr(f"{MODULE}.DEEP_RESEARCH_FALLBACK_SEMAPHORE_COUNT", 1)
        writer = MagicMock()
        ranked = [_ranked(f"https://{n}.com") for n in "abc"]
        with patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock, return_value="via httpx"):
            await _fetch_source_contents(
                ranked, {"https://a.com": "batched"}, {"https://c.com": "boom"}, writer
            )

        assert self._writer_frames(writer) == [
            {"progress": "Fetched source 1/3..."},
            {"progress": "Fetched source 2/3..."},
            {"progress": "Fetched source 3/3..."},
        ]

    async def test_snippet_fallback_still_advances_the_counter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A source that only yields a snippet is still a resolved source: it."""
        monkeypatch.setattr(f"{MODULE}.DEEP_RESEARCH_FALLBACK_SEMAPHORE_COUNT", 1)
        writer = MagicMock()
        with patch(
            f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock, side_effect=Exception("down")
        ):
            await _fetch_source_contents(
                [
                    _ranked("https://a.com", snippet=""),
                    _ranked("https://b.com", snippet="only a snippet"),
                    _ranked("https://c.com", snippet=""),
                ],
                {"https://a.com": "batched", "https://c.com": "batched"},
                {},
                writer,
            )

        assert self._writer_frames(writer) == [
            {"progress": "Fetched source 1/3..."},
            {"progress": "Fetched source 3/3..."},
        ]

    async def test_snippet_fallback_reports_every_tier_that_failed(self) -> None:
        """fetch_error is the only record of why the full page is missing --."""
        with patch(
            f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock, side_effect=Exception("timeout")
        ):
            (source,) = await _fetch_source_contents(
                [_ranked("https://a.com", snippet="the snippet")],
                {},
                {"https://a.com": "403 blocked"},
                MagicMock(),
            )

        assert source.content == "[Snippet only: full page unavailable]\n\nthe snippet"
        assert source.fetch_error == "crawl4ai: 403 blocked; httpx: timeout"

    async def test_missing_crawl_error_is_reported_as_no_content(self) -> None:
        with patch(
            f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock, side_effect=Exception("timeout")
        ):
            (source,) = await _fetch_source_contents(
                [_ranked("https://a.com", snippet="the snippet")], {}, {}, MagicMock()
            )

        assert source.fetch_error == "crawl4ai: returned no content; httpx: timeout"

    @pytest.mark.parametrize("snippet", ["", "   "])
    async def test_no_usable_snippet_yields_null_content(self, snippet: str) -> None:
        """A source with nothing to fall back on resolves to content None -- the."""
        with patch(
            f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock, side_effect=Exception("timeout")
        ):
            (source,) = await _fetch_source_contents(
                [_ranked("https://a.com", snippet=snippet)],
                {},
                {"https://a.com": "403"},
                MagicMock(),
            )

        assert source == _source(
            "https://a.com", None, "crawl4ai: 403; httpx: timeout", snippet=snippet
        )

    async def test_snippet_fallback_is_logged_against_the_url(self) -> None:
        """The wide event is the only place a degraded source shows up, so the."""
        with (
            patch(f"{MODULE}.log") as mock_log,
            patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock, side_effect=Exception("x")),
        ):
            await _fetch_source_contents([_ranked("https://a.com")], {}, {}, MagicMock())

        mock_log.warning.assert_called_once()
        message, kwargs = mock_log.warning.call_args
        assert "All fetchers failed, using search snippet" in message[0]
        assert kwargs == {"url": "https://a.com"}

    async def test_a_failure_outside_the_tiers_propagates_instead_of_becoming_a_source(
        self,
    ) -> None:
        """Only the three fetch tiers are recoverable."""
        writer = MagicMock(side_effect=RuntimeError("stream closed"))
        with pytest.raises(RuntimeError, match="stream closed"):
            await _fetch_source_contents(
                [_ranked("https://a.com")], {"https://a.com": "page body"}, {}, writer
            )
