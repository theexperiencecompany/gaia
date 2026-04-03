"""Unit tests for app/agents/tools/research_tool.py — deep_research tool.

Covers:
- User auth check (no user_id)
- Invalid depth
- Cache hit path
- No sources found
- Successful research with fetch fallback chains
- Exception in main try block
"""

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MODULE = "app.agents.tools.research_tool"


def _make_config(user_id: Optional[str] = "user-123") -> Dict[str, Any]:
    """Build a minimal RunnableConfig-like dict."""
    return {"configurable": {"user_id": user_id}}


def _no_user_config() -> Dict[str, Any]:
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
    with patch(f"{MODULE}.log"):
        yield


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
        assert result["error"] == "User authentication required"
        assert result["data"] is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    async def test_invalid_depth_returns_error(self, _mock_uid: MagicMock) -> None:
        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 5, "focus_areas": None},
            config=_make_config(),
        )
        assert "Invalid depth" in result["error"]
        assert result["data"] is None

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
        _patch_stream_writer.assert_any_call(
            {"progress": "Loaded research from cache!"}
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_with_duckduckgo", new_callable=AsyncMock)
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
        mock_ddg.return_value = {"results": []}
        mock_rank.return_value = []

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "obscure topic", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert "No sources found" in result["error"]
        assert result["data"] is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_with_duckduckgo", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.fetch_with_crawl4ai", new_callable=AsyncMock)
    async def test_successful_research_crawl4ai(
        self,
        mock_crawl4ai: AsyncMock,
        mock_rank: MagicMock,
        mock_ddg: AsyncMock,
        mock_decompose: AsyncMock,
        mock_set_cache: AsyncMock,
        _mock_cache: AsyncMock,
        _mock_cache_key: MagicMock,
        _mock_uid: MagicMock,
    ) -> None:
        mock_decompose.return_value = ["sub-q1", "sub-q2"]
        mock_ddg.return_value = {"results": [{"url": "https://example.com"}]}
        mock_rank.return_value = [
            {"url": "https://example.com", "snippet": "A snippet"},
            {"url": "https://example2.com", "snippet": "Another snippet"},
        ]
        mock_crawl4ai.return_value = "Full page content"

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
        mock_set_cache.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_with_duckduckgo", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(
        f"{MODULE}.fetch_with_crawl4ai",
        new_callable=AsyncMock,
        side_effect=Exception("crawl fail"),
    )
    @patch(f"{MODULE}.fetch_with_httpx", new_callable=AsyncMock)
    async def test_crawl4ai_fails_falls_back_to_httpx(
        self,
        mock_httpx: AsyncMock,
        mock_crawl4ai: AsyncMock,
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
        mock_rank.return_value = [{"url": "https://a.com", "snippet": "snip"}]
        mock_httpx.return_value = "httpx content"

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] is None
        assert result["sources"][0]["content"] == "httpx content"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_with_duckduckgo", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(
        f"{MODULE}.fetch_with_crawl4ai",
        new_callable=AsyncMock,
        side_effect=Exception("fail"),
    )
    @patch(
        f"{MODULE}.fetch_with_httpx",
        new_callable=AsyncMock,
        side_effect=Exception("fail"),
    )
    async def test_all_fetchers_fail_uses_snippet(
        self,
        mock_httpx: AsyncMock,
        mock_crawl4ai: AsyncMock,
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
        mock_rank.return_value = [
            {"url": "https://a.com", "snippet": "Search snippet text"}
        ]

        from app.agents.tools.research_tool import deep_research

        result = await deep_research.ainvoke(
            {"query": "test", "scope": "", "depth": 1, "focus_areas": None},
            config=_make_config(),
        )
        assert result["error"] is None
        assert "Snippet only" in result["sources"][0]["content"]
        assert result["sources"][0]["fetch_error"] is not None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_id_from_config", return_value="user-123")
    @patch(f"{MODULE}.build_research_cache_key", return_value="cache:key")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.decompose_research_queries", new_callable=AsyncMock)
    @patch(f"{MODULE}.search_with_duckduckgo", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(
        f"{MODULE}.fetch_with_crawl4ai",
        new_callable=AsyncMock,
        side_effect=Exception("fail"),
    )
    @patch(
        f"{MODULE}.fetch_with_httpx",
        new_callable=AsyncMock,
        side_effect=Exception("fail"),
    )
    async def test_all_fetchers_fail_no_snippet_returns_null_content(
        self,
        mock_httpx: AsyncMock,
        mock_crawl4ai: AsyncMock,
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
        mock_rank.return_value = [{"url": "https://a.com", "snippet": ""}]

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
    @patch(f"{MODULE}.search_with_duckduckgo", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.fetch_with_crawl4ai", new_callable=AsyncMock)
    async def test_depth_3_max_sources(
        self,
        mock_crawl4ai: AsyncMock,
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
        mock_crawl4ai.return_value = "content"

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
    @patch(f"{MODULE}.search_with_duckduckgo", new_callable=AsyncMock)
    @patch(f"{MODULE}.rank_and_deduplicate_urls")
    @patch(f"{MODULE}.fetch_with_crawl4ai", new_callable=AsyncMock)
    async def test_search_exceptions_counted_correctly(
        self,
        mock_crawl4ai: AsyncMock,
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
        mock_crawl4ai.return_value = "content"

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
