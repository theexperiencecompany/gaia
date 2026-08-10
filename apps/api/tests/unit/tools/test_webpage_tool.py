"""Unit tests for app.agents.tools.webpage_tool."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.agents.templates.fetch_template import FETCH_TEMPLATE
from app.constants.log_tags import LogTag
from app.utils.search.models import SearchResultItem, WebSearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODULE = "app.agents.tools.webpage_tool"

_NO_URLS_RETRIEVED_MSG = (
    "Search failed — no URLs were retrieved. Do NOT fabricate any URLs or results."
)

_INSTRUCTIONS = (
    "Summarise the search results — do not repeat them verbatim. "
    "Do not show images in markdown. "
    "Only mention URLs that appear in the search results. "
    "These results will be shown on the frontend in an appropriate manner."
)


def _make_config() -> dict[str, Any]:
    """Return a minimal RunnableConfig-like dict (no user_id: keeps the tool's
    rate-limit decorator from injecting its own metadata into the result)."""
    return {"metadata": {}}


def _writer_mock() -> MagicMock:
    return MagicMock()


def _integrity_note(query: str, result_count: int) -> str:
    """The exact integrity note the tool builds for a successful search."""
    return (
        f"Search query: '{query}'. "
        f"Found {result_count} real results. "
        "Only reference URLs listed in `real_urls_from_search` or in the `web` results. "
        "NEVER invent or fabricate URLs. If no results were found, say so clearly."
    )


def _time_patch() -> Any:
    """Freeze the tool's clock: set ``mock.time.side_effect = [100.0, 100.875]``
    in the test to get a 0.875s elapsed (third decimal matters for the
    ``round(elapsed_time, 2)`` log argument)."""
    return patch(f"{MODULE}.time", new_callable=MagicMock)


# ---------------------------------------------------------------------------
# Tests: fetch_webpages
# ---------------------------------------------------------------------------


class TestFetchWebpages:
    """Tests for the fetch_webpages tool."""

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_webpage", new_callable=AsyncMock)
    async def test_empty_urls_returns_error(
        self,
        mock_fetch: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Empty URL list returns the exact error dict and never touches the writer."""
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.webpage_tool import fetch_webpages

        result = await fetch_webpages.coroutine(
            config=_make_config(),
            urls=[],
        )

        assert result == {"error": "No URLs were provided for fetching."}
        mock_writer_factory.assert_not_called()
        mock_fetch.assert_not_awaited()
        mock_log.set.assert_called_once_with(
            tool={"name": "fetch_webpages", "action": "fetch"}
        )

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_webpage", new_callable=AsyncMock)
    async def test_happy_path_single_url(
        self,
        mock_fetch: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Fetches a single URL: exact return, writer stream, and dependency args."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_fetch.return_value = "Page content here"

        from app.agents.tools.webpage_tool import fetch_webpages

        result = await fetch_webpages.coroutine(
            config=_make_config(),
            urls=["https://example.com"],
        )

        expected_content = FETCH_TEMPLATE.format(
            page_content="Page content here",
            urls=["https://example.com"],
        )
        assert result == {
            "webpage_data": expected_content,
            "fetched_urls": ["https://example.com"],
        }
        mock_fetch.assert_awaited_once_with("https://example.com")
        assert writer.call_args_list == [
            call({"progress": f"Processing URL: '{'https://example.com':20}'..."}),
            call({"progress": "Processing Page 1/1..."}),
            call({"progress": "Fetching Complete!"}),
            call(
                {
                    "webpage_data": expected_content,
                    "fetched_urls": ["https://example.com"],
                }
            ),
        ]
        mock_log.set.assert_called_once_with(
            tool={"name": "fetch_webpages", "action": "fetch"}
        )

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_webpage", new_callable=AsyncMock)
    async def test_multiple_urls(
        self,
        mock_fetch: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Fetches multiple URLs: content concatenated in input order, both fetched."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_fetch.side_effect = ["Content A", "Content B"]

        from app.agents.tools.webpage_tool import fetch_webpages

        result = await fetch_webpages.coroutine(
            config=_make_config(),
            urls=["https://a.com", "https://b.com"],
        )

        expected_content = (
            FETCH_TEMPLATE.format(page_content="Content A", urls=["https://a.com"])
            + FETCH_TEMPLATE.format(page_content="Content B", urls=["https://b.com"])
        )
        assert result == {
            "webpage_data": expected_content,
            "fetched_urls": ["https://a.com", "https://b.com"],
        }
        mock_fetch.assert_has_awaits([call("https://a.com"), call("https://b.com")])
        assert writer.call_args_list == [
            call({"progress": f"Processing URL: '{'https://a.com':20}'..."}),
            call({"progress": f"Processing URL: '{'https://b.com':20}'..."}),
            call({"progress": "Processing Page 1/2..."}),
            call({"progress": "Processing Page 2/2..."}),
            call({"progress": "Fetching Complete!"}),
            call(
                {
                    "webpage_data": expected_content,
                    "fetched_urls": ["https://a.com", "https://b.com"],
                }
            ),
        ]

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_webpage", new_callable=AsyncMock)
    async def test_prepends_https_to_bare_urls(
        self,
        mock_fetch: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """URLs without a scheme get https:// prepended before being fetched."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_fetch.return_value = "Page content"

        from app.agents.tools.webpage_tool import fetch_webpages

        result = await fetch_webpages.coroutine(
            config=_make_config(),
            urls=["example.com"],
        )

        expected_content = FETCH_TEMPLATE.format(
            page_content="Page content",
            urls=["https://example.com"],
        )
        assert result == {
            "webpage_data": expected_content,
            "fetched_urls": ["https://example.com"],
        }
        mock_fetch.assert_awaited_once_with("https://example.com")
        assert writer.call_args_list == [
            call({"progress": f"Processing URL: '{'example.com':20}'..."}),
            call({"progress": "Processing Page 1/1..."}),
            call({"progress": "Fetching Complete!"}),
            call(
                {
                    "webpage_data": expected_content,
                    "fetched_urls": ["https://example.com"],
                }
            ),
        ]

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_webpage", new_callable=AsyncMock)
    async def test_fetch_exception_does_not_break_others(
        self,
        mock_fetch: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """A failing fetch is reported via the writer and does not abort the rest."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_fetch.side_effect = [Exception("Timeout"), "Good content"]

        from app.agents.tools.webpage_tool import fetch_webpages

        result = await fetch_webpages.coroutine(
            config=_make_config(),
            urls=["https://bad.com", "https://good.com"],
        )

        expected_content = FETCH_TEMPLATE.format(
            page_content="Good content",
            urls=["https://good.com"],
        )
        assert result == {
            "webpage_data": expected_content,
            "fetched_urls": ["https://bad.com", "https://good.com"],
        }
        assert writer.call_args_list == [
            call({"progress": f"Processing URL: '{'https://bad.com':20}'..."}),
            call({"progress": f"Processing URL: '{'https://good.com':20}'..."}),
            call({"progress": "Error processing https://bad.com: Timeout"}),
            call({"progress": "Processing Page 2/2..."}),
            call({"progress": "Fetching Complete!"}),
            call(
                {
                    "webpage_data": expected_content,
                    "fetched_urls": ["https://bad.com", "https://good.com"],
                }
            ),
        ]

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.fetch_webpage", new_callable=AsyncMock)
    async def test_writer_failure_returns_error(
        self,
        mock_fetch: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """An unexpected failure returns the exact error dict."""
        writer = _writer_mock()
        writer.side_effect = RuntimeError("boom")
        mock_writer_factory.return_value = writer

        from app.agents.tools.webpage_tool import fetch_webpages

        result = await fetch_webpages.coroutine(
            config=_make_config(),
            urls=["https://example.com"],
        )

        assert result == {"error": "An error occurred while fetching webpages: boom"}
        mock_fetch.assert_not_awaited()
        mock_log.set.assert_called_once_with(
            tool={"name": "fetch_webpages", "action": "fetch"}
        )


# ---------------------------------------------------------------------------
# Tests: web_search_tool
# ---------------------------------------------------------------------------


class TestWebSearchTool:
    """Tests for the web_search_tool tool."""

    @_time_patch()
    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_happy_path(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
        mock_time: MagicMock,
    ) -> None:
        """Successful search: exact writer stream, log call, and return payload."""
        mock_time.time.side_effect = [100.0, 100.875]
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        result_model = WebSearchResult(
            web=[SearchResultItem(title="Result 1", url="https://r1.com")],
            images=["img1.png"],
            answer="Quick answer",
            query="test query",
        )
        mock_search.return_value = result_model

        from app.agents.tools.webpage_tool import web_search_tool

        result = await web_search_tool.coroutine(
            query_text="test query",
            config=_make_config(),
        )

        expected_web = [item.model_dump() for item in result_model.web]
        assert writer.call_args_list == [
            call({"progress": "Performing web search for 'test query'..."}),
            call(
                {
                    "progress": (
                        "Web search completed in 0.88 seconds. "
                        "Found 1 web results, 1 images, and 0 videos."
                    )
                }
            ),
            call(
                {
                    "search_results": {
                        "web": expected_web,
                        "news": [],
                        "images": ["img1.png"],
                        "videos": [],
                        "query": "test query",
                        "elapsed_time": 0.875,
                        "answer": "Quick answer",
                        "response_time": 0,
                        "request_id": "",
                        "result_count": {"web": 1, "images": 1, "videos": 0},
                    }
                }
            ),
        ]
        mock_log.set.assert_called_once_with(
            tool={"name": "web_search_tool", "action": "search"}
        )
        mock_log.info.assert_called_once_with(
            f"{LogTag.TOOL} Web search completed",
            duration_seconds=0.88,
            web_result_count=1,
            image_count=1,
            video_count=0,
        )
        assert result == {
            **result_model.model_dump(),
            "real_urls_from_search": ["https://r1.com"],
            "integrity_note": _integrity_note("test query", 1),
            "instructions": _INSTRUCTIONS,
        }
        mock_search.assert_awaited_once_with(query="test query", count=10)

    @_time_patch()
    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_empty_results(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
        mock_time: MagicMock,
    ) -> None:
        """Zero results: exact zero counts, empty URL list, and honesty note."""
        mock_time.time.side_effect = [100.0, 100.875]
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        result_model = WebSearchResult(web=[], images=[], answer="", query="no results")
        mock_search.return_value = result_model

        from app.agents.tools.webpage_tool import web_search_tool

        result = await web_search_tool.coroutine(
            query_text="no results",
            config=_make_config(),
        )

        assert writer.call_args_list == [
            call({"progress": "Performing web search for 'no results'..."}),
            call(
                {
                    "progress": (
                        "Web search completed in 0.88 seconds. "
                        "Found 0 web results, 0 images, and 0 videos."
                    )
                }
            ),
            call(
                {
                    "search_results": {
                        "web": [],
                        "news": [],
                        "images": [],
                        "videos": [],
                        "query": "no results",
                        "elapsed_time": 0.875,
                        "answer": "",
                        "response_time": 0,
                        "request_id": "",
                        "result_count": {"web": 0, "images": 0, "videos": 0},
                    }
                }
            ),
        ]
        mock_log.info.assert_called_once_with(
            f"{LogTag.TOOL} Web search completed",
            duration_seconds=0.88,
            web_result_count=0,
            image_count=0,
            video_count=0,
        )
        assert result == {
            **result_model.model_dump(),
            "real_urls_from_search": [],
            "integrity_note": _integrity_note("no results", 0),
            "instructions": _INSTRUCTIONS,
        }
        mock_search.assert_awaited_once_with(query="no results", count=10)

    @_time_patch()
    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_real_urls_excludes_empty_urls(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
        mock_time: MagicMock,
    ) -> None:
        """real_urls_from_search keeps only non-empty URLs; web keeps all results."""
        mock_time.time.side_effect = [100.0, 100.875]
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        result_model = WebSearchResult(
            web=[
                SearchResultItem(title="No URL", url=""),
                SearchResultItem(title="Real", url="https://ok.com"),
            ],
            images=[],
            answer="",
            query="filter",
        )
        mock_search.return_value = result_model

        from app.agents.tools.webpage_tool import web_search_tool

        result = await web_search_tool.coroutine(
            query_text="filter",
            config=_make_config(),
        )

        assert result["real_urls_from_search"] == ["https://ok.com"]
        assert len(result["web"]) == 2
        assert result["integrity_note"] == _integrity_note("filter", 2)
        mock_search.assert_awaited_once_with(query="filter", count=10)

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_timeout_error(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """TimeoutError returns the exact network-error payload."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_search.side_effect = TimeoutError("boom")

        from app.agents.tools.webpage_tool import web_search_tool

        result = await web_search_tool.coroutine(
            query_text="test",
            config=_make_config(),
        )

        assert result == {
            "formatted_text": (
                "\n\nConnection timed out during web search. Please try again later."
            ),
            "error": "boom",
            "real_urls_from_search": [],
            "integrity_note": _NO_URLS_RETRIEVED_MSG,
        }
        assert writer.call_args_list == [
            call({"progress": "Performing web search for 'test'..."})
        ]
        mock_log.error.assert_called_once_with(
            f"{LogTag.TOOL} Network error in web search",
            error_type="TimeoutError",
            exc_info=True,
        )
        mock_log.info.assert_not_called()
        mock_search.assert_awaited_once_with(query="test", count=10)

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_connection_error(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """ConnectionError is treated like a timeout: same network-error payload."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_search.side_effect = ConnectionError("down")

        from app.agents.tools.webpage_tool import web_search_tool

        result = await web_search_tool.coroutine(
            query_text="test",
            config=_make_config(),
        )

        assert result == {
            "formatted_text": (
                "\n\nConnection timed out during web search. Please try again later."
            ),
            "error": "down",
            "real_urls_from_search": [],
            "integrity_note": _NO_URLS_RETRIEVED_MSG,
        }
        mock_log.error.assert_called_once_with(
            f"{LogTag.TOOL} Network error in web search",
            error_type="ConnectionError",
            exc_info=True,
        )
        mock_log.info.assert_not_called()

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_value_error(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """ValueError returns the exact invalid-parameters payload."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_search.side_effect = ValueError("bad query")

        from app.agents.tools.webpage_tool import web_search_tool

        result = await web_search_tool.coroutine(
            query_text="",
            config=_make_config(),
        )

        assert result == {
            "formatted_text": "\n\nInvalid search parameters. Please try a different query.",
            "error": "bad query",
            "real_urls_from_search": [],
            "integrity_note": _NO_URLS_RETRIEVED_MSG,
        }
        assert writer.call_args_list == [
            call({"progress": "Performing web search for ''..."})
        ]
        mock_log.error.assert_called_once_with(
            f"{LogTag.TOOL} Value error in web search",
            error_type="ValueError",
            exc_info=True,
        )
        mock_log.info.assert_not_called()
        mock_search.assert_awaited_once_with(query="", count=10)

    @patch(f"{MODULE}.log")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.perform_search", new_callable=AsyncMock)
    async def test_unexpected_error(
        self,
        mock_search: AsyncMock,
        mock_writer_factory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Any other exception returns the exact generic-error payload."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_search.side_effect = RuntimeError("unexpected")

        from app.agents.tools.webpage_tool import web_search_tool

        result = await web_search_tool.coroutine(
            query_text="test",
            config=_make_config(),
        )

        assert result == {
            "formatted_text": "\n\nError performing web search. Please try again later.",
            "error": "unexpected",
            "real_urls_from_search": [],
            "integrity_note": _NO_URLS_RETRIEVED_MSG,
        }
        assert writer.call_args_list == [
            call({"progress": "Performing web search for 'test'..."})
        ]
        mock_log.error.assert_called_once_with(
            f"{LogTag.TOOL} Unexpected error in web search",
            error_type="RuntimeError",
            exc_info=True,
        )
        mock_log.info.assert_not_called()
        mock_search.assert_awaited_once_with(query="test", count=10)
