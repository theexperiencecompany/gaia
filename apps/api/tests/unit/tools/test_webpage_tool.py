"""Unit tests for app.agents.tools.webpage_tool."""

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.webpage_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    """Return a minimal RunnableConfig-like dict."""
    return {"metadata": {"user_id": user_id}}


def _writer_mock() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests: fetch_webpages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchWebpages:
    """Tests for the fetch_webpages tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_with_firecrawl", new_callable=AsyncMock)
    async def test_happy_path_single_url(
        self,
        mock_firecrawl: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Successfully fetches a single URL."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_firecrawl.return_value = "Page content here"

        from app.agents.tools.webpage_tool import fetch_webpages

        result = await fetch_webpages.coroutine(
            config=_make_config(),
            urls=["https://example.com"],
        )

        assert "webpage_data" in result
        assert "Page content here" in result["webpage_data"]
        assert result["fetched_urls"] == ["https://example.com"]

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_with_firecrawl", new_callable=AsyncMock)
    async def test_multiple_urls(
        self,
        mock_firecrawl: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Fetches multiple URLs in parallel."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_firecrawl.side_effect = ["Content A", "Content B"]

        from app.agents.tools.webpage_tool import fetch_webpages

        result = await fetch_webpages.coroutine(
            config=_make_config(),
            urls=["https://a.com", "https://b.com"],
        )

        assert len(result["fetched_urls"]) == 2
        assert "Content A" in result["webpage_data"]
        assert "Content B" in result["webpage_data"]

    @patch(f"{MODULE}.get_stream_writer")
    async def test_empty_urls_returns_error(
        self,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Empty URL list returns an error."""
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.webpage_tool import fetch_webpages

        result = await fetch_webpages.coroutine(
            config=_make_config(),
            urls=[],
        )

        assert "error" in result
        assert "No URLs" in result["error"]

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_with_firecrawl", new_callable=AsyncMock)
    async def test_prepends_https_to_bare_urls(
        self,
        mock_firecrawl: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """URLs without protocol get https:// prepended."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_firecrawl.return_value = "Page content"

        from app.agents.tools.webpage_tool import fetch_webpages

        result = await fetch_webpages.coroutine(
            config=_make_config(),
            urls=["example.com"],
        )

        assert result["fetched_urls"] == ["https://example.com"]

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_with_firecrawl", new_callable=AsyncMock)
    async def test_fetch_exception_does_not_break_others(
        self,
        mock_firecrawl: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """One fetch failing doesn't prevent other URLs from being processed."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_firecrawl.side_effect = [
            Exception("Timeout"),
            "Good content",
        ]

        from app.agents.tools.webpage_tool import fetch_webpages

        result = await fetch_webpages.coroutine(
            config=_make_config(),
            urls=["https://bad.com", "https://good.com"],
        )

        assert "Good content" in result["webpage_data"]
        assert len(result["fetched_urls"]) == 2

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_with_firecrawl", new_callable=AsyncMock)
    async def test_streams_progress_updates(
        self,
        mock_firecrawl: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Writer receives progress updates during fetching."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_firecrawl.return_value = "content"

        from app.agents.tools.webpage_tool import fetch_webpages

        await fetch_webpages.coroutine(
            config=_make_config(),
            urls=["https://example.com"],
        )

        # Writer should have been called multiple times (progress + final data)
        assert writer.call_count >= 3


# ---------------------------------------------------------------------------
# Tests: web_search_tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWebSearchTool:
    """Tests for the web_search_tool tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_happy_path(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Successful web search returns structured results."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_search.return_value = {
            "web": [{"title": "Result 1", "url": "https://r1.com"}],
            "images": [],
            "videos": [],
            "answer": "Quick answer",
            "response_time": 0.5,
            "request_id": "req-123",
        }

        from app.agents.tools.webpage_tool import web_search_tool

        result = await web_search_tool.coroutine(
            query_text="test query",
            config=_make_config(),
        )

        assert result["web"] == [{"title": "Result 1", "url": "https://r1.com"}]
        assert "instructions" in result
        mock_search.assert_awaited_once_with(query="test query", count=10)

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_timeout_error(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Timeout error returns user-friendly message."""
        mock_writer_factory.return_value = _writer_mock()
        mock_search.side_effect = asyncio.TimeoutError()

        from app.agents.tools.webpage_tool import web_search_tool

        result = await web_search_tool.coroutine(
            query_text="test",
            config=_make_config(),
        )

        assert "error" in result
        assert "timed out" in result["formatted_text"]

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_value_error(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """ValueError returns invalid parameters message."""
        mock_writer_factory.return_value = _writer_mock()
        mock_search.side_effect = ValueError("bad query")

        from app.agents.tools.webpage_tool import web_search_tool

        result = await web_search_tool.coroutine(
            query_text="",
            config=_make_config(),
        )

        assert "error" in result
        assert "Invalid search parameters" in result["formatted_text"]

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_unexpected_error(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Generic exception returns general error message."""
        mock_writer_factory.return_value = _writer_mock()
        mock_search.side_effect = RuntimeError("unexpected")

        from app.agents.tools.webpage_tool import web_search_tool

        result = await web_search_tool.coroutine(
            query_text="test",
            config=_make_config(),
        )

        assert "error" in result
        assert "Error performing web search" in result["formatted_text"]

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_streams_search_results_to_writer(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Verifies search_results are streamed to the frontend."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_search.return_value = {
            "web": [{"title": "R1"}],
            "images": [{"url": "img.png"}],
            "videos": [],
            "answer": "",
            "response_time": 0.3,
            "request_id": "r1",
        }

        from app.agents.tools.webpage_tool import web_search_tool

        await web_search_tool.coroutine(
            query_text="hello",
            config=_make_config(),
        )

        # Find the search_results call
        search_calls = [c for c in writer.call_args_list if "search_results" in c[0][0]]
        assert len(search_calls) == 1
        payload = search_calls[0][0][0]["search_results"]
        assert payload["query"] == "hello"
        assert payload["result_count"]["web"] == 1
        assert payload["result_count"]["images"] == 1
