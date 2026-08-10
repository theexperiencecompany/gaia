"""Unit tests for app/agents/tools/research_tool.py — deep_research tool.

Covers:
- User auth check (no user_id)
- Invalid depth (exact error payload)
- Cache hit path (exact payload, writer frames, cache key args)
- Default-argument values when scope/depth/focus_areas are omitted
- No sources found (exact error payload, searched queries, cache key args)
- Successful research with exact dep args, writer frames and result payload
- crawl4ai -> httpx -> snippet fallback chains (incl. no-snippet)
- Failed-source accounting and cache-skip when no content is fetched
- Exception in main try block (exact log.error frame)
- Depth -> max_urls mapping (1/2/3)
- Partial search failure accounting (per-search exceptions via return_exceptions)
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.cache import ONE_HOUR_TTL
from app.constants.log_tags import LogTag
from app.constants.search import (
    CRAWL4AI_PAGE_TIMEOUT_MS,
    DEEP_RESEARCH_CRAWL4AI_BATCH_TIMEOUT_SECONDS,
    DEEP_RESEARCH_CRAWL4AI_SEMAPHORE_COUNT,
)
from app.templates.docstrings.research_tool_docs import RESEARCH_INSTRUCTIONS

MODULE = "app.agents.tools.research_tool"

SNIPPET_HEADER = "[Snippet only — full page unavailable]"


def _make_config(user_id: str | None = "user-123") -> dict[str, Any]:
    """Build a minimal RunnableConfig-like dict."""
    return {"configurable": {"user_id": user_id}}


def _no_user_config() -> dict[str, Any]:
    return {"configurable": {}}


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
    log = MagicMock()
    with patch(f"{MODULE}.log", log):
        yield log


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDeepResearch:
    """Tests for the deep_research tool function."""

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value=None)
    async def test_no_user_returns_error(self, _mock_uid: MagicMock) -> None:
        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 2, "focus_areas": None},
            config=_no_user_config(),
        )
        assert result == {"error": "User authentication required", "data": None}

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    async def test_invalid_depth_returns_exact_error_payload(
        self, _mock_uid: MagicMock
    ) -> None:
        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 5, "focus_areas": None},
            config=_make_config(),
        )
        assert result == {
            "error": "Invalid depth. Use 1 (quick), 2 (standard), or 3 (deep).",
            "query": "test",
            "data": None,
        }

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache")
    async def test_cache_hit_returns_cached_payload(
        self,
        mock_get_cache: AsyncMock,
        mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
        _patch_stream_writer: MagicMock,
        _patch_log: MagicMock,
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
        assert result == {
            **cached,
            "cached": True,
            "instructions": RESEARCH_INSTRUCTIONS,
        }
        # No search/fetch work happens on a cache hit.
        mock_get_cache.assert_awaited_once_with("cache:key")
        mock_cache_key.assert_called_once_with("test", "", [], 2)
        _patch_stream_writer.assert_any_call({"progress": "Loaded research from cache!"})
        _patch_stream_writer.assert_any_call({"research_data": cached})
        _patch_log.set.assert_called_once_with(
            tool={"name": "deep_research", "action": "research"}
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
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
    async def test_successful_research_exact_args_and_payload(
        self,
        mock_httpx: AsyncMock,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        mock_cache_key: MagicMock,
        mock_uid: MagicMock,
        _patch_stream_writer: MagicMock,
    ) -> None:
        mock_decompose.return_value = ["sub-q1", "sub-q2"]
        mock_ddg.side_effect = [
            {"results": [{"url": "https://example.com"}]},
            {"results": [{"url": "https://example2.com"}]},
        ]
        mock_rank.return_value = [
            {"url": "https://example.com", "snippet": "A snippet"},
            {"url": "https://example2.com", "snippet": "Another snippet"},
        ]
        mock_batch_crawl4ai.return_value = (
            {
                "https://example.com": "Full page content",
                "https://example2.com": "Full page content",
            },
            {},
        )
        mock_httpx.return_value = "unused httpx content"

        from app.agents.tools.research_tool import deep_research

        with patch(f"{MODULE}.time.time", side_effect=[1000.0, 1004.567]):
            result = await deep_research.ainvoke(
                {
                    "query": "AI trends",
                    "scope": "technical",
                    "depth": 1,
                    "focus_areas": ["performance", "cost"],
                },
                config=_make_config(),
            )

        expected_result: dict[str, Any] = {
            "query": "AI trends",
            "scope": "technical",
            "focus_areas": ["performance", "cost"],
            "sub_queries": ["sub-q1", "sub-q2"],
            "sources": [
                {
                    "url": "https://example.com",
                    "snippet": "A snippet",
                    "content": "Full page content",
                    "fetch_error": None,
                },
                {
                    "url": "https://example2.com",
                    "snippet": "Another snippet",
                    "content": "Full page content",
                    "fetch_error": None,
                },
            ],
            "source_count": 2,
            "authoritative_urls": ["https://example.com", "https://example2.com"],
            "depth": 1,
            "elapsed_seconds": 4.57,
            "failed_sources": 0,
            "error": None,
            "integrity_note": (
                "All URLs in `sources` and `authoritative_urls` were returned by real search "
                "queries. Only cite URLs from this list — never invent or guess URLs."
            ),
        }
        assert result == {**expected_result, "cached": False, "instructions": RESEARCH_INSTRUCTIONS}

        # Every dependency is called with the exact values derived from the inputs.
        assert mock_uid.call_args.args[0]["configurable"] == {"user_id": "user-123"}
        mock_cache_key.assert_called_once_with(
            "AI trends", "technical", ["performance", "cost"], 1
        )
        mock_decompose.assert_awaited_once_with("AI trends", "technical", "performance | cost", 1)
        mock_ddg.assert_any_await("sub-q1", count=5)
        mock_ddg.assert_any_await("sub-q2", count=5)
        assert mock_ddg.await_count == 2
        mock_rank.assert_called_once_with(
            [
                {"results": [{"url": "https://example.com"}]},
                {"results": [{"url": "https://example2.com"}]},
            ],
            max_urls=5,
        )
        mock_batch_crawl4ai.assert_awaited_once_with(
            ["https://example.com", "https://example2.com"],
            page_timeout_ms=CRAWL4AI_PAGE_TIMEOUT_MS,
            total_timeout_seconds=DEEP_RESEARCH_CRAWL4AI_BATCH_TIMEOUT_SECONDS,
            semaphore_count=DEEP_RESEARCH_CRAWL4AI_SEMAPHORE_COUNT,
            context_name="crawl4ai",
            content_query="AI trends",
        )
        # crawl4ai content is used verbatim — httpx must never run.
        mock_httpx.assert_not_awaited()
        mock_set_cache.assert_awaited_once_with("cache:key", expected_result, ttl=ONE_HOUR_TTL)

        # The writer stream reports each phase with exact counts.
        for frame in [
            {"progress": "Planning research strategy..."},
            {
                "progress": "Generated 2 targeted search queries",
                "research_queries": ["sub-q1", "sub-q2"],
            },
            {"progress": "Running 2 parallel searches..."},
            {"progress": "2/2 searches returned results (2 total URLs before deduplication)"},
            {
                "progress": "Found 2 unique sources — fetching full content...",
                "found_urls": ["https://example.com", "https://example2.com"],
            },
            {"progress": "Fetching sources..."},
            {"progress": "Fetched source 1/2..."},
            {"progress": "Fetched source 2/2..."},
            {"progress": "Research complete! 2 sources fetched (0 failed) in 4.57s"},
            {"research_data": expected_result},
        ]:
            _patch_stream_writer.assert_any_call(frame)

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
    async def test_no_sources_found_returns_exact_error_payload(
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
    ) -> None:
        mock_decompose.return_value = ["sub-q1"]
        mock_ddg.return_value = {"results": []}
        mock_rank.return_value = []
        mock_batch_crawl4ai.return_value = ({}, {})
        mock_httpx.return_value = "unused"

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "obscure topic", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result == {
            "error": (
                "Search returned no results for the given query. "
                "No URLs were found — do not fabricate links. "
                "Try broadening the search or inform the user that no sources were found."
            ),
            "query": "obscure topic",
            "searched_queries": ["sub-q1"],
            "source_count": 0,
            "data": None,
        }
        mock_decompose.assert_awaited_once_with("obscure topic", "", "", 1)
        mock_ddg.assert_awaited_once_with("sub-q1", count=5)
        mock_rank.assert_called_once_with([{"results": []}], max_urls=5)
        # Nothing to fetch or cache when no URLs were ranked.
        mock_batch_crawl4ai.assert_not_awaited()
        mock_set_cache.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
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
        """The httpx fallback only runs for sources crawl4ai missed, and the fetch
        counter is shared: the second source is fetch 2/2, not 1/2."""
        mock_decompose.return_value = ["sub-q1"]
        mock_ddg.return_value = {
            "results": [{"url": "https://a.com"}, {"url": "https://b.com"}]
        }
        mock_rank.return_value = [
            {"url": "https://a.com", "snippet": "snip"},
            {"url": "https://b.com", "snippet": "snip"},
        ]
        mock_batch_crawl4ai.return_value = (
            {"https://a.com": "crawl content"},
            {"https://b.com": "crawl fail"},
        )
        mock_httpx.return_value = "httpx content"

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] is None
        assert result["sources"] == [
            {
                "url": "https://a.com",
                "snippet": "snip",
                "content": "crawl content",
                "fetch_error": None,
            },
            {
                "url": "https://b.com",
                "snippet": "snip",
                "content": "httpx content",
                "fetch_error": None,
            },
        ]
        assert result["source_count"] == 2
        assert result["failed_sources"] == 0
        mock_httpx.assert_awaited_once_with("https://b.com")
        mock_set_cache.assert_awaited_once()
        _patch_stream_writer.assert_any_call({"progress": "Fetched source 1/2..."})
        _patch_stream_writer.assert_any_call({"progress": "Fetched source 2/2..."})

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
    async def test_all_fetchers_fail_uses_snippet(
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
        mock_ddg.return_value = {"results": [{"url": "https://a.com"}]}
        mock_rank.return_value = [{"url": "https://a.com", "snippet": "Search snippet text"}]
        mock_batch_crawl4ai.return_value = ({}, {"https://a.com": "fail"})
        mock_httpx.side_effect = Exception("fail")

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] is None
        assert result["sources"] == [
            {
                "url": "https://a.com",
                "snippet": "Search snippet text",
                "content": f"{SNIPPET_HEADER}\n\nSearch snippet text",
                "fetch_error": "crawl4ai: fail; httpx: fail",
            }
        ]
        assert result["source_count"] == 1
        assert result["failed_sources"] == 0
        _patch_log.warning.assert_called_once_with(
            f"{LogTag.TOOL} All fetchers failed, using search snippet", url="https://a.com"
        )
        mock_set_cache.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
    async def test_mixed_fetch_paths_progress_counter(
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
        """The fetch counter is shared across crawl4ai/httpx/snippet paths: a source
        that lands in the snippet path still counts, and later success frames show it."""
        mock_decompose.return_value = ["sub-q1"]
        mock_ddg.return_value = {
            "results": [{"url": "https://a.com"}, {"url": "https://b.com"}, {"url": "https://c.com"}]
        }
        mock_rank.return_value = [
            {"url": "https://a.com", "snippet": "s"},
            {"url": "https://b.com", "snippet": "snippet for b"},
            {"url": "https://c.com", "snippet": "s"},
        ]
        mock_batch_crawl4ai.return_value = (
            {"https://a.com": "content a", "https://c.com": "content c"},
            {"https://b.com": "fail"},
        )
        mock_httpx.side_effect = Exception("fail")

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] is None
        assert [s["url"] for s in result["sources"]] == [
            "https://a.com",
            "https://b.com",
            "https://c.com",
        ]
        assert result["sources"][1]["fetch_error"] == "crawl4ai: fail; httpx: fail"
        assert result["source_count"] == 3
        assert result["failed_sources"] == 0
        # Source a is fetch 1/3, source b (snippet path) is 2/3 but emits no frame,
        # source c is the final 3/3.
        _patch_stream_writer.assert_any_call({"progress": "Fetched source 1/3..."})
        _patch_stream_writer.assert_any_call({"progress": "Fetched source 3/3..."})
        mock_set_cache.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
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
    ) -> None:
        mock_decompose.return_value = ["sub-q1"]
        mock_ddg.return_value = {"results": [{"url": "https://a.com"}]}
        # No "snippet" key at all — the empty-string default must kick in. The
        # entry also carries a truthy "content" field: the no-snippet branch
        # must STILL force content=None (overriding anything the ranked entry
        # carried), so the source is dropped either way.
        mock_rank.return_value = [{"url": "https://a.com", "content": "provider content"}]
        mock_batch_crawl4ai.return_value = ({}, {"https://a.com": "fail"})
        mock_httpx.side_effect = Exception("fail")

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] is None
        # No valid sources (content is None — the entry's own "content" field
        # was overridden), so source_count = 0, the entry is filtered out of
        # `sources`, and nothing is cached.
        assert result["sources"] == []
        assert result["source_count"] == 0
        assert result["failed_sources"] == 1
        mock_set_cache.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
    async def test_defaults_used_when_scope_depth_focus_omitted(
        self,
        mock_httpx: AsyncMock,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
    ) -> None:
        """Omitting scope/depth/focus_areas must use the defaults (scope "", depth 2).

        Called through ``deep_research.coroutine`` directly (not ainvoke) because
        the tool's pydantic schema fills the original defaults before the function
        runs — the function's own defaults are only exercised on direct calls.
        """
        mock_decompose.return_value = ["q"]
        mock_ddg.return_value = {"results": [{"url": "https://x.com"}]}
        mock_rank.return_value = [{"url": "https://x.com", "snippet": "s"}]
        # crawl4ai returns neither content nor an error -> "returned no content".
        mock_batch_crawl4ai.return_value = ({}, {})
        mock_httpx.side_effect = Exception("fail")

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.coroutine(config=_make_config(), query="test")
        assert result["error"] is None
        assert result["depth"] == 2
        assert result["focus_areas"] == []
        mock_cache_key.assert_called_once_with("test", "", [], 2)
        mock_decompose.assert_awaited_once_with("test", "", "", 2)
        mock_rank.assert_called_once_with([{"results": [{"url": "https://x.com"}]}], max_urls=10)
        assert result["sources"] == [
            {
                "url": "https://x.com",
                "snippet": "s",
                "content": f"{SNIPPET_HEADER}\n\ns",
                "fetch_error": "crawl4ai: returned no content; httpx: fail",
            }
        ]
        mock_set_cache.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
    async def test_fetch_gather_does_not_swallow_exceptions(
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
    ) -> None:
        """Search failures are swallowed (return_exceptions=True) but fetch failures
        are NOT — a broken fetch must fail the whole tool, not hide in the results."""
        from unittest.mock import patch as _patch

        from app.agents.tools.research_tool import deep_research

        class _RecordingAsyncIO:
            def __init__(self) -> None:
                self.gather_kwargs: list[dict[str, Any]] = []

            def __getattr__(self, name: str) -> Any:
                return getattr(asyncio, name)

            async def gather(self, *coros: Any, **kwargs: Any) -> Any:
                self.gather_kwargs.append(kwargs)
                return await asyncio.gather(*coros, **kwargs)

        recording = _RecordingAsyncIO()
        mock_decompose.return_value = ["sub-q1"]
        mock_ddg.return_value = {"results": [{"url": "https://a.com"}]}
        mock_rank.return_value = [{"url": "https://a.com", "snippet": "s"}]
        mock_batch_crawl4ai.return_value = ({"https://a.com": "content"}, {})
        mock_httpx.return_value = "unused"

        with _patch(f"{MODULE}.asyncio", recording):
            result = await deep_research.ainvoke(
                {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
                config=_make_config(),
            )
        assert result["error"] is None
        assert recording.gather_kwargs == [
            {"return_exceptions": True},
            {"return_exceptions": False},
        ]
        mock_set_cache.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_for_research", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.batch_fetch_with_crawl4ai", new_callable=AsyncMock)
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
    async def test_fetch_error_propagates_from_bounded_fetch(
        self,
        mock_httpx: AsyncMock,
        mock_batch_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        _mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
    ) -> None:
        """A malformed ranked entry (non-string snippet) raises inside _bounded_fetch
        and the error propagates out of the fetch gather (return_exceptions=False)."""
        mock_decompose.return_value = ["sub-q1"]
        mock_ddg.return_value = {"results": [{"url": "https://a.com"}]}
        mock_rank.return_value = [{"url": "https://a.com", "snippet": None}]
        mock_batch_crawl4ai.return_value = ({}, {"https://a.com": "fail"})
        mock_httpx.side_effect = Exception("fail")

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] == "'NoneType' object has no attribute 'strip'"
        assert result["query"] == "test"
        assert result["data"] is None

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
        _patch_log: MagicMock,
    ) -> None:
        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 2, "focus_areas": None},
            config=_make_config(),
        )
        assert result == {"error": "boom", "query": "test", "data": None}
        _patch_log.error.assert_called_once_with(
            f"{LogTag.TOOL} Deep research error", error_type="RuntimeError", exc_info=True
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
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
    async def test_depth_3_max_sources(
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
    ) -> None:
        """Depth 3 should pass max_urls=20 to rank_and_deduplicate_urls."""
        mock_decompose.return_value = ["q1"]
        mock_ddg.return_value = {"results": [{"url": "https://a.com"}]}
        mock_rank.return_value = [{"url": "https://a.com", "snippet": "s"}]
        mock_batch_crawl4ai.return_value = ({"https://a.com": "content"}, {})
        mock_httpx.return_value = "unused"

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 3, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] is None
        assert result["depth"] == 3
        mock_rank.assert_called_once_with(
            [{"results": [{"url": "https://a.com"}]}], max_urls=20
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
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
    async def test_search_exceptions_counted_correctly(
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
        """When some searches raise exceptions, successful_searches count is correct."""
        mock_decompose.return_value = ["q1", "q2", "q3"]
        mock_ddg.side_effect = [
            {"results": [{"url": "https://a.com"}]},
            RuntimeError("search failed"),
            {"results": []},
        ]
        mock_rank.return_value = [{"url": "https://a.com", "snippet": "s"}]
        mock_batch_crawl4ai.return_value = ({"https://a.com": "content"}, {})
        mock_httpx.return_value = "unused"

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] is None
        # The failed search (RuntimeError) is passed through to ranking as-is
        # (exceptions don't support value equality, so compare element-wise).
        rank_args = mock_rank.call_args.args[0]
        assert rank_args[0] == {"results": [{"url": "https://a.com"}]}
        assert isinstance(rank_args[1], RuntimeError)
        assert rank_args[1].args == ("search failed",)
        assert rank_args[2] == {"results": []}
        assert mock_rank.call_args.kwargs == {"max_urls": 5}
        _patch_stream_writer.assert_any_call(
            {
                "progress": (
                    "1/3 searches returned results "
                    "(1 total URLs before deduplication)"
                )
            }
        )
        mock_set_cache.assert_awaited_once()
