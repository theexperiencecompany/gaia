"""Tests for Notion custom tools (notion_tool.py).

These tests verify the core logic of each tool function registered by
`register_notion_custom_tools`. External HTTP calls (httpx) and Composio
SDK calls (composio.tools.execute) are mocked so no real credentials are
needed. The tests will fail if the production module is deleted or its
core behaviour changes.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Production imports – if these fail the module is gone/renamed
# ---------------------------------------------------------------------------
from app.agents.tools.integrations.notion_tool import register_notion_custom_tools
from app.models.notion_models import (
    CreateTestPageInput,
    FetchDataInput,
    FetchPageAsMarkdownInput,
    InsertMarkdownInput,
    MovePageInput,
)


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

AUTH_CREDENTIALS: Dict[str, Any] = {
    "access_token": "secret-notion-token",
    "version": "2022-06-28",
    "user_id": "user-123",
}


def _make_composio_mock() -> MagicMock:
    """Return a Composio mock that records custom_tool registrations.

    The `custom_tool` decorator is called with toolkit="NOTION" and must
    return a no-op decorator so the inner function is preserved as-is.
    """
    composio = MagicMock()

    registered_functions: Dict[str, Any] = {}

    def custom_tool_decorator(toolkit: str):
        def decorator(fn):
            registered_functions[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool.side_effect = custom_tool_decorator
    composio._registered = registered_functions
    return composio


def _register_and_extract(composio: MagicMock) -> Dict[str, Any]:
    """Call register_notion_custom_tools and return the inner functions."""
    register_notion_custom_tools(composio)
    return composio._registered


# ---------------------------------------------------------------------------
# MOVE_PAGE
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestMovePage:
    """Tests for the MOVE_PAGE Notion custom tool."""

    def _call(
        self,
        composio: MagicMock,
        page_id: str = "page-abc",
        parent_type: str = "page_id",
        parent_id: str = "parent-xyz",
        response_data: Dict[str, Any] | None = None,
    ):
        fns = _register_and_extract(composio)
        move_page_fn = fns["MOVE_PAGE"]

        # Build a fake execute_request that returns a response object
        if response_data is None:
            response_data = {"id": page_id, "url": f"https://notion.so/{page_id}"}

        mock_response = MagicMock()
        mock_response.data = response_data
        execute_request = MagicMock(return_value=mock_response)

        request = MovePageInput(
            page_id=page_id, parent_type=parent_type, parent_id=parent_id
        )
        return move_page_fn(request, execute_request, AUTH_CREDENTIALS), execute_request

    def test_move_to_page_parent_happy_path(self):
        composio = _make_composio_mock()
        result, execute_request = self._call(composio)

        # Verify execute_request was called with PATCH on the correct endpoint
        execute_request.assert_called_once()
        call_kwargs = execute_request.call_args.kwargs
        assert call_kwargs["endpoint"] == "/pages/page-abc"
        assert call_kwargs["method"] == "PATCH"
        parent_sent = call_kwargs["body"]["parent"]
        assert parent_sent == {"type": "page_id", "page_id": "parent-xyz"}

        # Verify return structure
        assert result["page_id"] == "page-abc"
        assert result["new_parent"]["type"] == "page_id"
        assert "url" in result

    def test_move_to_database_parent(self):
        composio = _make_composio_mock()
        result, execute_request = self._call(
            composio, parent_type="database_id", parent_id="db-999"
        )

        call_kwargs = execute_request.call_args.kwargs
        parent_sent = call_kwargs["body"]["parent"]
        assert parent_sent == {"type": "database_id", "database_id": "db-999"}
        assert result["new_parent"]["type"] == "database_id"

    def test_move_page_response_without_data_attribute(self):
        """When execute_request returns a plain dict (no .data attr), use it directly."""
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        move_page_fn = fns["MOVE_PAGE"]

        # Plain dict, no .data attribute
        plain_response = {"id": "page-plain", "url": "https://notion.so/page-plain"}
        execute_request = MagicMock(return_value=plain_response)

        request = MovePageInput(
            page_id="page-plain", parent_type="page_id", parent_id="parent-id"
        )
        result = move_page_fn(request, execute_request, AUTH_CREDENTIALS)
        assert result["page_id"] == "page-plain"

    def test_move_page_propagates_execute_request_error(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        move_page_fn = fns["MOVE_PAGE"]

        execute_request = MagicMock(side_effect=RuntimeError("Notion API error"))
        request = MovePageInput(page_id="p", parent_type="page_id", parent_id="par")
        with pytest.raises(RuntimeError, match="Notion API error"):
            move_page_fn(request, execute_request, AUTH_CREDENTIALS)


# ---------------------------------------------------------------------------
# FETCH_PAGE_AS_MARKDOWN
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestFetchPageAsMarkdown:
    """Tests for the FETCH_PAGE_AS_MARKDOWN Notion custom tool."""

    def _make_title_response(self, title_text: str = "My Page") -> Dict[str, Any]:
        return {
            "successful": True,
            "data": {
                "results": [{"type": "title", "title": {"plain_text": title_text}}]
            },
        }

    def _make_blocks_response(self, blocks: list) -> Dict[str, Any]:
        return {"successful": True, "data": {"results": blocks}}

    def _paragraph_block(self, text: str, block_id: str = "blk-1") -> Dict[str, Any]:
        return {
            "id": block_id,
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"plain_text": text, "annotations": {}, "type": "text"}]
            },
        }

    def test_fetch_page_happy_path_with_title(self):
        composio = _make_composio_mock()

        # Sequence: first call = title, second call = blocks
        composio.tools.execute.side_effect = [
            self._make_title_response("Hello World"),
            self._make_blocks_response([self._paragraph_block("Some content")]),
        ]

        fns = _register_and_extract(composio)
        fn = fns["FETCH_PAGE_AS_MARKDOWN"]
        request = FetchPageAsMarkdownInput(
            page_id="page-001", recursive=True, include_block_ids=False
        )
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["page_id"] == "page-001"
        assert result["title"] == "Hello World"
        assert "# Hello World" in result["markdown"]
        assert "Some content" in result["markdown"]
        assert result["block_count"] == 1

    def test_fetch_page_no_title_still_returns_markdown(self):
        composio = _make_composio_mock()

        # Title call fails
        composio.tools.execute.side_effect = [
            {"successful": False, "error": "no title"},
            self._make_blocks_response([self._paragraph_block("Body only")]),
        ]

        fns = _register_and_extract(composio)
        fn = fns["FETCH_PAGE_AS_MARKDOWN"]
        request = FetchPageAsMarkdownInput(page_id="page-002")
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["title"] == ""
        # No H1 prefix when title is missing
        assert "# " not in result["markdown"]
        assert "Body only" in result["markdown"]

    def test_fetch_page_includes_block_ids_in_markdown(self):
        composio = _make_composio_mock()

        block_id = "blk-abc-123"
        composio.tools.execute.side_effect = [
            {"successful": False, "error": "skip"},
            self._make_blocks_response(
                [self._paragraph_block("Content", block_id=block_id)]
            ),
        ]

        fns = _register_and_extract(composio)
        fn = fns["FETCH_PAGE_AS_MARKDOWN"]
        request = FetchPageAsMarkdownInput(page_id="page-003", include_block_ids=True)
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)
        assert f"<!-- block:{block_id} -->" in result["markdown"]

    def test_fetch_page_raises_when_blocks_call_fails(self):
        composio = _make_composio_mock()

        composio.tools.execute.side_effect = [
            {"successful": False, "error": "no title"},
            {"successful": False, "error": "block fetch failed"},
        ]

        fns = _register_and_extract(composio)
        fn = fns["FETCH_PAGE_AS_MARKDOWN"]
        request = FetchPageAsMarkdownInput(page_id="page-bad")
        with pytest.raises(ValueError, match="Failed to fetch blocks"):
            fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_fetch_page_title_exception_is_swallowed(self):
        """If the title fetch raises any exception it is caught and page is still returned."""
        composio = _make_composio_mock()

        # First call raises; second call returns blocks normally
        composio.tools.execute.side_effect = [
            Exception("Network timeout"),
            self._make_blocks_response([self._paragraph_block("Resilient content")]),
        ]

        fns = _register_and_extract(composio)
        fn = fns["FETCH_PAGE_AS_MARKDOWN"]
        request = FetchPageAsMarkdownInput(page_id="page-resilient")
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)
        assert result["title"] == ""
        assert "Resilient content" in result["markdown"]

    def test_fetch_page_empty_blocks_returns_empty_markdown(self):
        composio = _make_composio_mock()

        composio.tools.execute.side_effect = [
            {"successful": False, "error": "no title"},
            {"successful": True, "data": {"results": []}},
        ]

        fns = _register_and_extract(composio)
        fn = fns["FETCH_PAGE_AS_MARKDOWN"]
        request = FetchPageAsMarkdownInput(page_id="page-empty")
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)
        assert result["block_count"] == 0
        assert result["markdown"] == ""


# ---------------------------------------------------------------------------
# INSERT_MARKDOWN
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestInsertMarkdown:
    """Tests for the INSERT_MARKDOWN Notion custom tool."""

    def test_insert_markdown_happy_path(self):
        composio = _make_composio_mock()
        composio.tools.execute.return_value = {
            "successful": True,
            "data": {"results": []},
        }

        fns = _register_and_extract(composio)
        fn = fns["INSERT_MARKDOWN"]
        request = InsertMarkdownInput(
            parent_block_id="page-111",
            markdown="# Hello\n\nSome paragraph",
        )
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["parent_block_id"] == "page-111"
        # markdown_to_notion_blocks should produce at least 2 blocks for the above
        assert result["blocks_added"] >= 2
        assert result["after"] is None

    def test_insert_markdown_with_after_parameter(self):
        composio = _make_composio_mock()
        composio.tools.execute.return_value = {
            "successful": True,
            "data": {"results": []},
        }

        fns = _register_and_extract(composio)
        fn = fns["INSERT_MARKDOWN"]
        request = InsertMarkdownInput(
            parent_block_id="page-222",
            markdown="- item one\n- item two",
            after="blk-after-me",
        )
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["after"] == "blk-after-me"
        # after param must be forwarded to Composio execute (first call only)
        first_call_kwargs = composio.tools.execute.call_args_list[0].kwargs
        assert first_call_kwargs["arguments"]["after"] == "blk-after-me"

    def test_insert_markdown_raises_on_empty_markdown(self):
        composio = _make_composio_mock()

        fns = _register_and_extract(composio)
        fn = fns["INSERT_MARKDOWN"]
        # Only whitespace lines → markdown_to_notion_blocks returns []
        request = InsertMarkdownInput(
            parent_block_id="page-333",
            markdown="   \n\n   ",
        )
        with pytest.raises(ValueError, match="No content to insert"):
            fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_insert_markdown_raises_when_composio_execute_fails(self):
        composio = _make_composio_mock()
        composio.tools.execute.return_value = {
            "successful": False,
            "error": "Notion rate limit",
        }

        fns = _register_and_extract(composio)
        fn = fns["INSERT_MARKDOWN"]
        request = InsertMarkdownInput(
            parent_block_id="page-444",
            markdown="Some valid content",
        )
        with pytest.raises(ValueError, match="Failed to insert markdown"):
            fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_insert_markdown_after_param_omitted_when_none(self):
        """When after=None, the after key must NOT be sent to Composio."""
        composio = _make_composio_mock()
        composio.tools.execute.return_value = {
            "successful": True,
            "data": {},
        }

        fns = _register_and_extract(composio)
        fn = fns["INSERT_MARKDOWN"]
        request = InsertMarkdownInput(
            parent_block_id="page-555",
            markdown="Hello world",
        )
        fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_kwargs = composio.tools.execute.call_args.kwargs
        assert "after" not in call_kwargs["arguments"]


# ---------------------------------------------------------------------------
# FETCH_DATA
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestFetchData:
    """Tests for the FETCH_DATA Notion custom tool."""

    def _fake_search_response(self, items: list, has_more: bool = False):
        """Build a fake httpx Response for the Notion search endpoint."""

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": items, "has_more": has_more}
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    def _database_item(self, db_id: str, title: str) -> Dict[str, Any]:
        return {
            "id": db_id,
            "object": "database",
            "title": [{"plain_text": title}],
        }

    def _page_item(self, page_id: str, title: str) -> Dict[str, Any]:
        return {
            "id": page_id,
            "object": "page",
            "properties": {
                "title": {
                    "type": "title",
                    "title": [{"plain_text": title}],
                }
            },
        }

    def test_fetch_databases_happy_path(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["FETCH_DATA"]

        request = FetchDataInput(fetch_type="databases", page_size=10)

        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._fake_search_response(
                [
                    self._database_item("db-1", "Tasks"),
                    self._database_item("db-2", "Notes"),
                ]
            )
            result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["count"] == 2
        assert result["has_more"] is False
        titles = [v["title"] for v in result["values"]]
        assert "Tasks" in titles
        assert "Notes" in titles
        # Verify the search filter used the correct value ("database" not "databases")
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["filter"]["value"] == "database"

    def test_fetch_pages_happy_path(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["FETCH_DATA"]

        request = FetchDataInput(fetch_type="pages", page_size=5)

        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._fake_search_response(
                [self._page_item("pg-1", "Meeting Notes")]
            )
            result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["count"] == 1
        assert result["values"][0]["title"] == "Meeting Notes"
        assert result["values"][0]["type"] == "page"
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["filter"]["value"] == "page"

    def test_fetch_data_with_query_filter(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["FETCH_DATA"]

        request = FetchDataInput(fetch_type="pages", query="project")

        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._fake_search_response([])
            fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["query"] == "project"

    def test_fetch_data_no_query_does_not_send_query_key(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["FETCH_DATA"]

        request = FetchDataInput(fetch_type="databases")

        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._fake_search_response([])
            fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_kwargs = mock_post.call_args.kwargs
        assert "query" not in call_kwargs["json"]

    def test_fetch_data_page_size_capped_at_100(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["FETCH_DATA"]

        request = FetchDataInput(fetch_type="pages", page_size=999)

        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._fake_search_response([])
            fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["page_size"] == 100

    def test_fetch_data_has_more_flag_propagated(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["FETCH_DATA"]

        request = FetchDataInput(fetch_type="pages")

        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._fake_search_response(
                [self._page_item("pg-x", "First")], has_more=True
            )
            result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["has_more"] is True

    def test_fetch_data_raises_runtime_error_on_http_error(self):
        import httpx

        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["FETCH_DATA"]

        request = FetchDataInput(fetch_type="databases")

        with patch("httpx.post") as mock_post:
            error_response = MagicMock()
            error_response.status_code = 401
            error_response.text = "Unauthorized"
            mock_post.return_value = MagicMock(
                raise_for_status=MagicMock(
                    side_effect=httpx.HTTPStatusError(
                        "401", request=MagicMock(), response=error_response
                    )
                )
            )
            with pytest.raises(RuntimeError, match="Failed to fetch databases"):
                fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_fetch_data_raises_runtime_error_on_general_exception(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["FETCH_DATA"]

        request = FetchDataInput(fetch_type="pages")

        with patch("httpx.post", side_effect=ConnectionError("DNS failure")):
            with pytest.raises(RuntimeError, match="Failed to fetch pages"):
                fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_fetch_data_bearer_token_sent_in_headers(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["FETCH_DATA"]

        request = FetchDataInput(fetch_type="pages")

        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._fake_search_response([])
            fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_kwargs = mock_post.call_args.kwargs
        auth_header = call_kwargs["headers"]["Authorization"]
        assert auth_header == "Bearer secret-notion-token"

    def test_fetch_data_item_without_id_is_skipped(self):
        """Items with no 'id' field must be excluded from the returned values."""
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["FETCH_DATA"]

        request = FetchDataInput(fetch_type="pages")
        items = [
            {"object": "page", "properties": {}},  # no id
            self._page_item("pg-good", "Visible"),
        ]

        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._fake_search_response(items)
            result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["count"] == 1
        assert result["values"][0]["id"] == "pg-good"


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_TEST_PAGE
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestCustomCreateTestPage:
    """Tests for the CUSTOM_CREATE_TEST_PAGE Notion custom tool."""

    def _make_create_response(self, page_id: str = "new-page-id") -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": page_id,
            "url": f"https://notion.so/{page_id}",
        }
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    def test_create_page_with_explicit_parent(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TEST_PAGE"]

        request = CreateTestPageInput(title="Test Page", parent_page_id="parent-001")

        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._make_create_response("created-001")
            result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["page_id"] == "created-001"
        assert "url" in result
        # Only one POST call (no search needed)
        assert mock_post.call_count == 1
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["parent"] == {"page_id": "parent-001"}

    def test_create_page_without_parent_searches_for_one(self):
        """When parent_page_id is None, the tool searches for any page first."""
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TEST_PAGE"]

        request = CreateTestPageInput(title="Auto Parent Page")

        search_response = MagicMock()
        search_response.json.return_value = {"results": [{"id": "found-parent-id"}]}
        search_response.raise_for_status.return_value = None

        create_response = self._make_create_response("auto-created")

        with patch(
            "httpx.post", side_effect=[search_response, create_response]
        ) as mock_post:
            result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert mock_post.call_count == 2
        assert result["page_id"] == "auto-created"
        # Second call should use the discovered parent
        create_call_kwargs = mock_post.call_args_list[1].kwargs
        assert create_call_kwargs["json"]["parent"] == {"page_id": "found-parent-id"}

    def test_create_page_raises_when_no_parent_and_no_pages_found(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TEST_PAGE"]

        request = CreateTestPageInput(title="Orphan Page")

        search_response = MagicMock()
        search_response.json.return_value = {"results": []}
        search_response.raise_for_status.return_value = None

        with patch("httpx.post", return_value=search_response):
            with pytest.raises(ValueError, match="No parent page provided"):
                fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_create_page_raises_on_api_error(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TEST_PAGE"]

        request = CreateTestPageInput(title="Failing Page", parent_page_id="par-1")

        with patch("httpx.post", side_effect=RuntimeError("connection refused")):
            with pytest.raises(RuntimeError, match="Failed to create page"):
                fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_create_page_title_is_sent_correctly(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TEST_PAGE"]

        request = CreateTestPageInput(
            title="My Specific Title", parent_page_id="par-fixed"
        )

        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._make_create_response()
            fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_kwargs = mock_post.call_args.kwargs
        title_prop = call_kwargs["json"]["properties"]["title"]
        assert title_prop[0]["text"]["content"] == "My Specific Title"

    def test_create_page_bearer_token_in_headers(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TEST_PAGE"]

        request = CreateTestPageInput(title="Token Test", parent_page_id="par-t")

        with patch("httpx.post") as mock_post:
            mock_post.return_value = self._make_create_response()
            fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer secret-notion-token"


# ---------------------------------------------------------------------------
# register_notion_custom_tools – registration contract
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestRegisterNotionCustomTools:
    """Verify the registration function returns the correct slug list."""

    def test_returns_expected_slugs(self):
        composio = _make_composio_mock()
        slugs = register_notion_custom_tools(composio)
        assert set(slugs) == {
            "NOTION_MOVE_PAGE",
            "NOTION_FETCH_PAGE_AS_MARKDOWN",
            "NOTION_INSERT_MARKDOWN",
            "NOTION_FETCH_DATA",
            "NOTION_CUSTOM_CREATE_TEST_PAGE",
            "NOTION_CUSTOM_GATHER_CONTEXT",
        }

    def test_registers_six_tools(self):
        composio = _make_composio_mock()
        register_notion_custom_tools(composio)
        assert composio.tools.custom_tool.call_count == 6

    def test_all_tool_functions_are_callable(self):
        composio = _make_composio_mock()
        register_notion_custom_tools(composio)
        for fn in composio._registered.values():
            assert callable(fn)
