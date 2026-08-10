"""Unit tests for app.agents.tools.integrations.notion_tool.

The Composio-registered tool bodies are exercised for real with only the true
I/O boundaries faked: `execute_request` (the proxy seam handed in by the
framework), `composio.tools.execute`, `proxy_request_sync`, `execute_tool`,
and the markdown converters. Every assertion pins exact behavior — full return
dicts, exact call args, exact error strings.

Previously this coverage lived inside the shared smoke file
`test_integration_tools_proxy.py`; it now lives here so the mutation lane can
target the module with its own dedicated test file.
"""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.notion_models import (
    FetchDataInput,
    FetchPageAsMarkdownInput,
    InsertMarkdownInput,
    MovePageInput,
)
from app.utils.errors import AppError

MODULE = "app.agents.tools.integrations.notion_tool"
AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123"}
AUTH_CREDS_VERSIONED: dict[str, Any] = {"user_id": "user_test_123", "version": "v1"}
EXECUTE_REQUEST = MagicMock()


def _notion_tools() -> tuple[dict[str, Any], MagicMock]:
    """Register the Notion custom tools against a fake Composio and capture them."""
    from app.agents.tools.integrations.notion_tool import register_notion_custom_tools

    tools: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Callable[[Any], Any]:
        def decorator(fn: Any) -> Any:
            tools[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    register_notion_custom_tools(composio)
    return tools, composio


# --- registration ------------------------------------------------------------


def test_notion_register_returns_expected_tool_names() -> None:
    from app.agents.tools.integrations.notion_tool import register_notion_custom_tools

    assert register_notion_custom_tools(MagicMock()) == [
        "NOTION_MOVE_PAGE",
        "NOTION_FETCH_PAGE_AS_MARKDOWN",
        "NOTION_INSERT_MARKDOWN",
        "NOTION_FETCH_DATA",
        "NOTION_CUSTOM_GATHER_CONTEXT",
    ]


def test_notion_register_captures_all_five_tool_bodies() -> None:
    tools, _composio = _notion_tools()
    assert set(tools) == {
        "MOVE_PAGE",
        "FETCH_PAGE_AS_MARKDOWN",
        "INSERT_MARKDOWN",
        "FETCH_DATA",
        "CUSTOM_GATHER_CONTEXT",
    }


# --- _user_id ----------------------------------------------------------------


@pytest.mark.parametrize(
    "creds",
    [{}, {"user_id": ""}, {"user_id": None}, {"user_id": 123}],
    ids=["missing", "empty", "none", "not-a-string"],
)
def test_notion_user_id_rejects_invalid_credentials(creds: dict[str, Any]) -> None:
    from app.agents.tools.integrations.notion_tool import _user_id

    with pytest.raises(ValueError) as excinfo:
        _user_id(creds)
    assert str(excinfo.value) == "Missing user_id in auth_credentials"


def test_notion_user_id_returns_credentials_user_id() -> None:
    from app.agents.tools.integrations.notion_tool import _user_id

    assert _user_id({"user_id": "user-1"}) == "user-1"


# --- MOVE_PAGE ---------------------------------------------------------------


def test_notion_move_page_page_id_parent_exact_proxy_call() -> None:
    tools, _composio = _notion_tools()
    execute_request = MagicMock()
    execute_request.return_value.data = {"id": "page-1", "url": "https://notion.so/p1"}

    with patch(f"{MODULE}.log.set") as log_set:
        result = tools["MOVE_PAGE"](
            MovePageInput(page_id="page-1", parent_id="parent-1", parent_type="page_id"),
            execute_request,
            AUTH_CREDS_VERSIONED,
        )

    assert result == {
        "page_id": "page-1",
        "new_parent": {"type": "page_id", "page_id": "parent-1"},
        "url": "https://notion.so/p1",
    }
    execute_request.assert_called_once_with(
        endpoint="/pages/page-1",
        method="PATCH",
        body={"parent": {"type": "page_id", "page_id": "parent-1"}},
    )
    log_set.assert_called_once_with(tool={"integration": "notion", "action": "move_page"})


def test_notion_move_page_database_id_parent() -> None:
    tools, _composio = _notion_tools()
    execute_request = MagicMock()
    execute_request.return_value.data = {"id": "page-1", "url": "https://notion.so/p1"}

    result = tools["MOVE_PAGE"](
        MovePageInput(page_id="page-1", parent_id="db-1", parent_type="database_id"),
        execute_request,
        AUTH_CREDS_VERSIONED,
    )

    assert result["new_parent"] == {"type": "database_id", "database_id": "db-1"}
    execute_request.assert_called_once_with(
        endpoint="/pages/page-1",
        method="PATCH",
        body={"parent": {"type": "database_id", "database_id": "db-1"}},
    )


def test_notion_move_page_uses_plain_response_without_data_attribute() -> None:
    tools, _composio = _notion_tools()
    execute_request = MagicMock()
    execute_request.return_value = {"id": "page-1", "url": "https://notion.so/p1"}

    result = tools["MOVE_PAGE"](
        MovePageInput(page_id="page-1", parent_id="parent-1", parent_type="page_id"),
        execute_request,
        AUTH_CREDS_VERSIONED,
    )

    assert result["page_id"] == "page-1"
    assert result["url"] == "https://notion.so/p1"


def test_notion_move_page_missing_response_fields_default_to_none() -> None:
    tools, _composio = _notion_tools()
    execute_request = MagicMock()
    execute_request.return_value.data = {}

    result = tools["MOVE_PAGE"](
        MovePageInput(page_id="page-1", parent_id="parent-1", parent_type="page_id"),
        execute_request,
        AUTH_CREDS_VERSIONED,
    )

    assert result == {
        "page_id": None,
        "new_parent": {"type": "page_id", "page_id": "parent-1"},
        "url": None,
    }


def test_notion_move_page_real_response_object_with_data_attribute() -> None:
    """A real response object (not a MagicMock) must have its ``data``
    attribute read — MagicMock makes ``hasattr`` true for every name, so the
    data-vs-raw-response branch needs a concrete object to discriminate."""
    tools, _composio = _notion_tools()
    execute_request = MagicMock()
    execute_request.return_value = SimpleNamespace(
        data={"id": "page-1", "url": "https://notion.so/p1"}
    )

    result = tools["MOVE_PAGE"](
        MovePageInput(page_id="page-1", parent_id="parent-1", parent_type="page_id"),
        execute_request,
        AUTH_CREDS_VERSIONED,
    )

    assert result == {
        "page_id": "page-1",
        "new_parent": {"type": "page_id", "page_id": "parent-1"},
        "url": "https://notion.so/p1",
    }
    execute_request.assert_called_once()


# --- FETCH_PAGE_AS_MARKDOWN --------------------------------------------------


def test_notion_fetch_page_as_markdown_converts_blocks_and_prepends_title() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {
            "successful": True,
            "data": {"results": [{"type": "title", "title": {"plain_text": "My Page"}}]},
        },
        {
            "successful": True,
            "data": {"results": [{"type": "paragraph"}, {"type": "paragraph"}]},
        },
    ]

    with (
        patch(f"{MODULE}.blocks_to_markdown", return_value="converted") as to_md,
        patch(f"{MODULE}.log.set") as log_set,
    ):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1", recursive=False, include_block_ids=False),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result == {
        "page_id": "page-1",
        "title": "My Page",
        "markdown": "# My Page\n\nconverted",
        "block_count": 2,
    }
    to_md.assert_called_once_with(
        [{"type": "paragraph"}, {"type": "paragraph"}], include_block_ids=False
    )
    log_set.assert_called_once_with(
        tool={"integration": "notion", "action": "fetch_page_as_markdown"}
    )
    assert composio.tools.execute.call_args_list == [
        call(
            slug="NOTION_GET_PAGE_PROPERTY_ACTION",
            arguments={"page_id": "page-1", "property_id": "title"},
            version="v1",
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        ),
        call(
            slug="NOTION_FETCH_ALL_BLOCK_CONTENTS",
            arguments={"block_id": "page-1", "recursive": False, "page_size": 100},
            version="v1",
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        ),
    ]


def test_notion_fetch_page_as_markdown_takes_first_title_and_breaks() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {
            "successful": True,
            "data": {
                "results": [
                    {"type": "title", "title": {"plain_text": "First"}},
                    {"type": "title", "title": {"plain_text": "Second"}},
                ]
            },
        },
        {"successful": True, "data": {"results": []}},
    ]

    with patch(f"{MODULE}.blocks_to_markdown", return_value=""):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["title"] == "First"
    assert result["markdown"] == "# First\n\n"
    assert result["block_count"] == 0


def test_notion_fetch_page_as_markdown_skips_items_without_title_text() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {
            "successful": True,
            "data": {
                "results": [
                    {"type": "paragraph", "title": {"plain_text": "not a title"}},
                    {"type": "title", "title": {}},
                    {"type": "title", "title": {"plain_text": "Real"}},
                ]
            },
        },
        {"successful": True, "data": {"results": []}},
    ]

    with patch(f"{MODULE}.blocks_to_markdown", return_value=""):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["title"] == "Real"


def test_notion_fetch_page_as_markdown_empty_plain_text_title() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {
            "successful": True,
            "data": {"results": [{"type": "title", "title": {"plain_text": ""}}]},
        },
        {"successful": True, "data": {"results": []}},
    ]

    with patch(f"{MODULE}.blocks_to_markdown", return_value="md"):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["title"] == ""
    assert result["markdown"] == "md"


def test_notion_fetch_page_as_markdown_title_without_plain_text_key() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {
            "successful": True,
            "data": {"results": [{"type": "title", "title": {"type": "text"}}]},
        },
        {"successful": True, "data": {"results": []}},
    ]

    with patch(f"{MODULE}.blocks_to_markdown", return_value="md"):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result == {
        "page_id": "page-1",
        "title": "",
        "markdown": "md",
        "block_count": 0,
    }


def test_notion_fetch_page_as_markdown_title_data_not_a_dict() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": "unexpected"},
        {"successful": True, "data": {"results": []}},
    ]

    with (
        patch(f"{MODULE}.blocks_to_markdown", return_value=""),
        patch(f"{MODULE}.log.warning") as warn,
    ):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["title"] == ""
    warn.assert_not_called()


def test_notion_fetch_page_as_markdown_title_response_without_results() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {}},
        {"successful": True, "data": {"results": []}},
    ]

    with (
        patch(f"{MODULE}.blocks_to_markdown", return_value=""),
        patch(f"{MODULE}.log.warning") as warn,
    ):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["title"] == ""
    warn.assert_not_called()


def test_notion_fetch_page_as_markdown_title_failure_logs_and_continues() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": False, "error": "boom"},
        {"successful": True, "data": {"results": []}},
    ]

    with (
        patch(f"{MODULE}.blocks_to_markdown", return_value=""),
        patch(f"{MODULE}.log.warning") as warn,
    ):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["title"] == ""
    assert result["markdown"] == ""
    warn.assert_called_once_with(f"{LogTag.TOOL} Failed to fetch title", error="boom")


def test_notion_fetch_page_as_markdown_title_exception_logged_blocks_still_fetched() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        RuntimeError("title api down"),
        {"successful": True, "data": {"results": []}},
    ]

    with (
        patch(f"{MODULE}.blocks_to_markdown", return_value=""),
        patch(f"{MODULE}.log.warning") as warn,
    ):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["title"] == ""
    assert composio.tools.execute.call_count == 2
    warn.assert_called_once_with(f"{LogTag.TOOL} Could not fetch title", error_type="RuntimeError")


def test_notion_fetch_page_as_markdown_blocks_failure_raises() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {"results": []}},
        {"successful": False, "error": "blocks boom"},
    ]

    with patch(f"{MODULE}.blocks_to_markdown", return_value=""):
        with pytest.raises(ValueError, match="Failed to fetch blocks: blocks boom"):
            tools["FETCH_PAGE_AS_MARKDOWN"](
                FetchPageAsMarkdownInput(page_id="page-1"),
                EXECUTE_REQUEST,
                AUTH_CREDS_VERSIONED,
            )


def test_notion_fetch_page_as_markdown_blocks_fallback_key() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {"results": []}},
        {"successful": True, "data": {"blocks": [{"type": "paragraph"}]}},
    ]

    with patch(f"{MODULE}.blocks_to_markdown", return_value="md") as to_md:
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["block_count"] == 1
    to_md.assert_called_once_with([{"type": "paragraph"}], include_block_ids=True)


def test_notion_fetch_page_as_markdown_blocks_data_not_a_dict() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {"results": []}},
        {"successful": True, "data": "unexpected"},
    ]

    with patch(f"{MODULE}.blocks_to_markdown", return_value="md") as to_md:
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["markdown"] == "md"
    assert result["block_count"] == 0
    to_md.assert_called_once_with([], include_block_ids=True)


def test_notion_fetch_page_as_markdown_blocks_results_not_a_list() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {"results": []}},
        {"successful": True, "data": {"results": "nope"}},
    ]

    with patch(f"{MODULE}.blocks_to_markdown", return_value="md") as to_md:
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["markdown"] == ""
    assert result["block_count"] == 0
    to_md.assert_not_called()


def test_notion_fetch_page_as_markdown_blocks_data_without_keys() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {"results": []}},
        {"successful": True, "data": {}},
    ]

    with patch(f"{MODULE}.blocks_to_markdown", return_value="md") as to_md:
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result == {
        "page_id": "page-1",
        "title": "",
        "markdown": "md",
        "block_count": 0,
    }
    to_md.assert_called_once_with([], include_block_ids=True)


# --- INSERT_MARKDOWN ---------------------------------------------------------


def test_notion_insert_markdown_empty_conversion_raises() -> None:
    tools, _composio = _notion_tools()

    with patch(f"{MODULE}.markdown_to_notion_blocks", return_value=[]):
        with pytest.raises(ValueError) as excinfo:
            tools["INSERT_MARKDOWN"](
                InsertMarkdownInput(parent_block_id="parent-1", markdown="# hi"),
                EXECUTE_REQUEST,
                AUTH_CREDS_VERSIONED,
            )
    assert str(excinfo.value) == "No content to insert - markdown conversion produced no blocks"


def test_notion_insert_markdown_passes_exact_markdown_to_conversion() -> None:
    tools, composio = _notion_tools()
    blocks = [{"type": "paragraph", "content": "a"}]
    composio.tools.execute.side_effect = [{"successful": True}]

    def _convert(markdown: str) -> list[dict[str, Any]]:
        assert markdown == "exact markdown", f"conversion got {markdown!r}"
        return blocks

    with patch(f"{MODULE}.markdown_to_notion_blocks", side_effect=_convert):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="exact markdown"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )


def test_notion_insert_markdown_mixed_table_and_blocks_with_after() -> None:
    tools, composio = _notion_tools()
    blocks = [
        {"type": "table", "table_width": 2, "has_column_header": False, "rows": [["a", "b"]]},
        {"type": "paragraph", "rich_text": [{"type": "text", "text": {"content": "hi"}}]},
    ]
    composio.tools.execute.side_effect = [{"successful": True}, {"successful": True}]

    with (
        patch(f"{MODULE}.markdown_to_notion_blocks", return_value=blocks),
        patch(f"{MODULE}.log.set") as log_set,
    ):
        result = tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md", after="after-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result == {
        "parent_block_id": "parent-1",
        "blocks_added": 2,
        "tables_added": 1,
        "after": "after-1",
    }
    log_set.assert_called_once_with(tool={"integration": "notion", "action": "insert_markdown"})
    assert composio.tools.execute.call_args_list == [
        call(
            slug="NOTION_APPEND_TABLE_BLOCKS",
            arguments={
                "block_id": "parent-1",
                "table_width": 2,
                "has_column_header": False,
                "rows": [["a", "b"]],
            },
            version="v1",
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        ),
        call(
            slug="NOTION_ADD_MULTIPLE_PAGE_CONTENT",
            arguments={
                "parent_block_id": "parent-1",
                "content_blocks": [blocks[1]],
                "after": "after-1",
            },
            version="v1",
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        ),
    ]


def test_notion_insert_markdown_after_applies_to_first_content_block_only() -> None:
    tools, composio = _notion_tools()
    blocks = [
        {"type": "paragraph", "content": "a"},
        {"type": "paragraph", "content": "b"},
    ]
    composio.tools.execute.side_effect = [{"successful": True}, {"successful": True}]

    with patch(f"{MODULE}.markdown_to_notion_blocks", return_value=blocks):
        result = tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md", after="after-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["blocks_added"] == 2
    first, second = composio.tools.execute.call_args_list
    assert first.kwargs["arguments"]["after"] == "after-1"
    assert "after" not in second.kwargs["arguments"]


def test_notion_insert_markdown_after_not_consumed_by_tables() -> None:
    tools, composio = _notion_tools()
    blocks = [
        {"type": "table", "table_width": 1, "rows": [["x"]]},
        {"type": "paragraph", "content": "a"},
        {"type": "paragraph", "content": "b"},
    ]
    composio.tools.execute.side_effect = [{"successful": True}] * 3

    with patch(f"{MODULE}.markdown_to_notion_blocks", return_value=blocks):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md", after="after-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    table_call, para_a, para_b = composio.tools.execute.call_args_list
    assert "after" not in table_call.kwargs["arguments"]
    assert para_a.kwargs["arguments"]["after"] == "after-1"
    assert "after" not in para_b.kwargs["arguments"]


def test_notion_insert_markdown_without_after_omits_key() -> None:
    tools, composio = _notion_tools()
    blocks = [{"type": "paragraph", "content": "a"}]
    composio.tools.execute.side_effect = [{"successful": True}]

    with patch(f"{MODULE}.markdown_to_notion_blocks", return_value=blocks):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    call_args = composio.tools.execute.call_args_list[0]
    assert "after" not in call_args.kwargs["arguments"]


def test_notion_insert_markdown_table_defaults_has_column_header_true() -> None:
    tools, composio = _notion_tools()
    blocks = [{"type": "table", "table_width": 1, "rows": [["x"]]}]
    composio.tools.execute.side_effect = [{"successful": True}]

    with patch(f"{MODULE}.markdown_to_notion_blocks", return_value=blocks):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    args = composio.tools.execute.call_args_list[0].kwargs["arguments"]
    assert args["has_column_header"] is True


def test_notion_insert_markdown_tables_added_counts_all_tables() -> None:
    tools, composio = _notion_tools()
    blocks = [
        {"type": "table", "table_width": 1, "rows": [["a"]]},
        {"type": "table", "table_width": 2, "rows": [["b", "c"]]},
    ]
    composio.tools.execute.side_effect = [{"successful": True}, {"successful": True}]

    with patch(f"{MODULE}.markdown_to_notion_blocks", return_value=blocks):
        result = tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["blocks_added"] == 2
    assert result["tables_added"] == 2
    assert [c.kwargs["slug"] for c in composio.tools.execute.call_args_list] == [
        "NOTION_APPEND_TABLE_BLOCKS",
        "NOTION_APPEND_TABLE_BLOCKS",
    ]


def test_notion_insert_markdown_table_failure_raises() -> None:
    tools, composio = _notion_tools()
    blocks = [{"type": "table", "table_width": 1, "rows": [["x"]]}]
    composio.tools.execute.side_effect = [{"successful": False, "error": "table boom"}]

    with (
        patch(f"{MODULE}.markdown_to_notion_blocks", return_value=blocks),
        pytest.raises(ValueError, match="Failed to insert table: table boom"),
    ):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )


def test_notion_insert_markdown_content_failure_raises() -> None:
    tools, composio = _notion_tools()
    blocks = [{"type": "paragraph", "content": "a"}]
    composio.tools.execute.side_effect = [{"successful": False, "error": "content boom"}]

    with (
        patch(f"{MODULE}.markdown_to_notion_blocks", return_value=blocks),
        pytest.raises(ValueError, match="Failed to insert markdown: content boom"),
    ):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )


# --- FETCH_DATA --------------------------------------------------------------


def test_notion_fetch_data_exact_proxy_call_and_empty_result() -> None:
    with (
        patch(f"{MODULE}.proxy_request_sync") as proxy,
        patch(f"{MODULE}.log.set") as log_set,
    ):
        proxy.return_value = {"results": [], "has_more": False}
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages", page_size=100),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result == {"values": [], "count": 0, "has_more": False}
    log_set.assert_called_once_with(tool={"integration": "notion", "action": "fetch_data"})
    proxy.assert_called_once_with(
        user_id="user_test_123",
        toolkit="NOTION",
        endpoint="https://api.notion.com/v1/search",
        method="POST",
        body={
            "filter": {"property": "object", "value": "page"},
            "page_size": 100,
        },
        headers={"Notion-Version": "2022-06-28"},
    )


@pytest.mark.parametrize(
    "fetch_type, filter_value",
    [("pages", "page"), ("databases", "database")],
    ids=["pages", "databases"],
)
def test_notion_fetch_data_filter_value_derived_from_fetch_type(
    fetch_type: str, filter_value: str
) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"results": [], "has_more": False}
        tools, _composio = _notion_tools()
        tools["FETCH_DATA"](
            FetchDataInput(fetch_type=fetch_type),  # type: ignore[arg-type]
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert proxy.call_args.kwargs["body"]["filter"] == {
        "property": "object",
        "value": filter_value,
    }


@pytest.mark.parametrize(
    "page_size, expected",
    [(50, 50), (100, 100), (500, 100), (0, 0)],
    ids=["under-cap", "at-cap", "over-cap", "zero"],
)
def test_notion_fetch_data_page_size_capped_at_100(page_size: int, expected: int) -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"results": [], "has_more": False}
        tools, _composio = _notion_tools()
        tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages", page_size=page_size),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert proxy.call_args.kwargs["body"]["page_size"] == expected


def test_notion_fetch_data_with_query() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"results": [], "has_more": False}
        tools, _composio = _notion_tools()
        tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages", query="roadmap"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert proxy.call_args.kwargs["body"] == {
        "filter": {"property": "object", "value": "page"},
        "page_size": 100,
        "query": "roadmap",
    }


def test_notion_fetch_data_without_query() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"results": [{"id": "page-1", "object": "page", "properties": {}}]}
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert proxy.call_args.kwargs["body"] == {
        "filter": {"property": "object", "value": "page"},
        "page_size": 100,
    }
    assert result == {
        "values": [{"id": "page-1", "title": "Untitled", "type": "page"}],
        "count": 1,
        "has_more": False,
    }


def test_notion_fetch_data_extracts_database_title_and_has_more() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {"id": "db-1", "object": "database", "title": [{"plain_text": "Roadmap"}]},
                {"id": "db-2", "object": "database", "title": []},
            ],
            "has_more": True,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="databases"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result == {
        "values": [
            {"id": "db-1", "title": "Roadmap", "type": "database"},
            {"id": "db-2", "title": "Untitled", "type": "database"},
        ],
        "count": 2,
        "has_more": True,
    }


def test_notion_fetch_data_database_title_missing_plain_text_defaults() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [{"id": "db-1", "object": "database", "title": [{}]}],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="databases"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["values"] == [{"id": "db-1", "title": "Untitled", "type": "database"}]


def test_notion_fetch_data_database_null_title_defaults_to_untitled() -> None:
    """A database search hit whose ``title`` key is null must not crash —
    the truthiness guard skips it and the row reports Untitled."""
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [{"id": "db-1", "object": "database", "title": None}],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="databases"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result == {
        "values": [{"id": "db-1", "title": "Untitled", "type": "database"}],
        "count": 1,
        "has_more": False,
    }


def test_notion_fetch_data_extracts_page_title_from_properties() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "object": "page",
                    "properties": {
                        "Status": {"type": "select", "select": {"name": "Done"}},
                        "Name": {"type": "title", "title": [{"plain_text": "Deep dive"}]},
                    },
                }
            ],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["values"] == [{"id": "page-1", "title": "Deep dive", "type": "page"}]
    assert result["count"] == 1


def test_notion_fetch_data_uses_first_title_property_only() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "object": "page",
                    "properties": {
                        "Name": {"type": "title", "title": [{"plain_text": "First"}]},
                        "Other": {"type": "title", "title": [{"plain_text": "Second"}]},
                    },
                }
            ],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["values"][0]["title"] == "First"


def test_notion_fetch_data_untitled_page_without_title_property() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "object": "page",
                    "properties": {
                        "Status": {"type": "select", "select": {"name": "Done"}},
                        "Tags": {"type": "multi_select", "multi_select": []},
                    },
                }
            ],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["values"][0]["title"] == "Untitled"


def test_notion_fetch_data_page_without_properties_key() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [{"id": "page-1", "object": "page"}],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["values"] == [{"id": "page-1", "title": "Untitled", "type": "page"}]


def test_notion_fetch_data_page_title_missing_plain_text_defaults() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "object": "page",
                    "properties": {"Name": {"type": "title", "title": [{}]}},
                }
            ],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result["values"] == [{"id": "page-1", "title": "Untitled", "type": "page"}]


def test_notion_fetch_data_page_null_title_property_defaults_to_untitled() -> None:
    """A title-typed property whose ``title`` value is null must not crash —
    the truthiness guard skips it and the row reports Untitled."""
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "object": "page",
                    "properties": {"Name": {"type": "title", "title": None}},
                }
            ],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result == {
        "values": [{"id": "page-1", "title": "Untitled", "type": "page"}],
        "count": 1,
        "has_more": False,
    }


def test_notion_fetch_data_skips_items_without_id() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {"object": "page", "properties": {}},
                {"id": "page-1", "object": "page", "properties": {}},
            ],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result == {
        "values": [{"id": "page-1", "title": "Untitled", "type": "page"}],
        "count": 1,
        "has_more": False,
    }


def test_notion_fetch_data_none_response_becomes_empty() -> None:
    with patch(f"{MODULE}.proxy_request_sync", return_value=None) as proxy:
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            AUTH_CREDS_VERSIONED,
        )

    assert result == {"values": [], "count": 0, "has_more": False}
    proxy.assert_called_once()


def test_notion_fetch_data_app_error_wrapped_in_runtime_error() -> None:
    with (
        patch(
            f"{MODULE}.proxy_request_sync",
            side_effect=AppError(message="notion 429"),
        ),
        patch(f"{MODULE}.log.error") as err_log,
    ):
        tools, _composio = _notion_tools()
        with pytest.raises(RuntimeError, match="Failed to fetch pages: notion 429"):
            tools["FETCH_DATA"](
                FetchDataInput(fetch_type="pages"),
                EXECUTE_REQUEST,
                AUTH_CREDS_VERSIONED,
            )

    err_log.assert_called_once_with(f"{LogTag.TOOL} Notion API error", error_type="AppError")


def test_notion_fetch_data_generic_error_wrapped_in_runtime_error() -> None:
    with (
        patch(
            f"{MODULE}.proxy_request_sync",
            side_effect=RuntimeError("api down"),
        ),
        patch(f"{MODULE}.log.error") as err_log,
    ):
        tools, _composio = _notion_tools()
        with pytest.raises(RuntimeError, match="Failed to fetch pages: api down"):
            tools["FETCH_DATA"](
                FetchDataInput(fetch_type="pages"),
                EXECUTE_REQUEST,
                AUTH_CREDS_VERSIONED,
            )

    err_log.assert_called_once_with(
        f"{LogTag.TOOL} Error fetching from Notion",
        fetch_type="pages",
        error_type="RuntimeError",
    )


def test_notion_fetch_data_missing_user_id_rejected_before_proxy() -> None:
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        tools, _composio = _notion_tools()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            tools["FETCH_DATA"](
                FetchDataInput(fetch_type="pages"),
                EXECUTE_REQUEST,
                {},
            )

    proxy.assert_not_called()


# --- CUSTOM_GATHER_CONTEXT ---------------------------------------------------


def test_notion_gather_context_returns_results_key() -> None:
    with (
        patch(
            f"{MODULE}.execute_tool",
            return_value={"results": [{"id": "page-1"}]},
        ) as execute,
        patch(f"{MODULE}.log.set") as log_set,
    ):
        tools, _composio = _notion_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_VERSIONED
        )

    assert result == {"relevant_pages": [{"id": "page-1"}]}
    log_set.assert_called_once_with(tool={"integration": "notion", "action": "gather_context"})
    execute.assert_called_once_with(
        "NOTION_SEARCH_NOTION_PAGE", {"query": "", "page_size": 10}, "user_test_123"
    )


def test_notion_gather_context_falls_back_to_pages_key() -> None:
    with patch(
        f"{MODULE}.execute_tool",
        return_value={"pages": [{"id": "page-1"}]},
    ):
        tools, _composio = _notion_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_VERSIONED
        )

    assert result == {"relevant_pages": [{"id": "page-1"}]}


def test_notion_gather_context_missing_both_keys_returns_empty_list() -> None:
    """execute_tool returning neither ``results`` nor ``pages`` must yield an
    empty relevant_pages list — not None."""
    with patch(f"{MODULE}.execute_tool", return_value={}) as execute:
        tools, _composio = _notion_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_VERSIONED
        )

    assert result == {"relevant_pages": []}
    execute.assert_called_once_with(
        "NOTION_SEARCH_NOTION_PAGE", {"query": "", "page_size": 10}, "user_test_123"
    )


def test_notion_gather_context_missing_user_id_rejected() -> None:
    with patch(f"{MODULE}.execute_tool") as execute:
        tools, _composio = _notion_tools()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})

    execute.assert_not_called()
