"""Behavior tests for Notion custom tool registration and error paths.

The proxy smoke test (test_integration_tools_proxy.py) proves routing; these
tests pin the exact registration contract (tool names + toolkit kwarg) and
the FETCH_DATA failure paths.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.agents.tools.integrations.notion_tool import (
    _append_content_block,
    _append_table_block,
    _build_parent,
    _execute_notion_action,
    _fetch_data,
    _fetch_page_as_markdown,
    _fetch_page_blocks,
    _fetch_page_title,
    _insert_markdown,
    _item_title,
    _move_page,
    register_notion_custom_tools,
)
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

EXPECTED_TOOL_NAMES = [
    "NOTION_MOVE_PAGE",
    "NOTION_FETCH_PAGE_AS_MARKDOWN",
    "NOTION_INSERT_MARKDOWN",
    "NOTION_FETCH_DATA",
    "NOTION_CUSTOM_GATHER_CONTEXT",
]


def _capture_tools(
    register_fn: Callable[..., list[str]],
) -> tuple[
    list[str],
    dict[str, tuple[Callable[..., Any], dict[str, Any]]],
    MagicMock,
]:
    captured: dict[str, tuple[Callable[..., Any], dict[str, Any]]] = {}
    composio = MagicMock()

    def custom_tool(**kwargs: Any) -> Callable[[Any], Any]:
        def decorator(fn: Any) -> Any:
            # Composio registers custom tools under "<TOOLKIT>_<fn name>".
            registered_name = f"{kwargs.get('toolkit', '')}_{fn.__name__}"
            captured[registered_name] = (fn, kwargs)
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    registered = register_fn(composio)
    return registered, captured, composio


def test_register_returns_exact_tool_names_and_toolkits() -> None:
    registered, captured, _ = _capture_tools(register_notion_custom_tools)

    assert registered == EXPECTED_TOOL_NAMES
    assert sorted(captured) == sorted(EXPECTED_TOOL_NAMES)
    assert all(kwargs == {"toolkit": "NOTION"} for _, kwargs in captured.values())


def test_register_docstring_pins_tool_description() -> None:
    assert register_notion_custom_tools.__doc__ == (
        "Register Notion tools as Composio custom tools."
    )


def test_fetch_data_app_error_raises_runtime_error_with_message() -> None:
    _, tools, _ = _capture_tools(register_notion_custom_tools)
    fetch_data, _ = tools["NOTION_FETCH_DATA"]
    error = AppError(message="Notion API error (500)", status_code=500)

    with patch(f"{MODULE}.proxy_request_sync", side_effect=error):
        with pytest.raises(RuntimeError) as excinfo:
            fetch_data(FetchDataInput(fetch_type="pages"), MagicMock(), AUTH_CREDS)

    assert str(excinfo.value) == "Failed to fetch pages: Notion API error (500)"
    assert excinfo.value.__cause__ is error


def test_fetch_data_unexpected_error_raises_runtime_error_with_str() -> None:
    _, tools, _ = _capture_tools(register_notion_custom_tools)
    fetch_data, _ = tools["NOTION_FETCH_DATA"]
    error = ValueError("connection reset")

    with patch(f"{MODULE}.proxy_request_sync", side_effect=error):
        with pytest.raises(RuntimeError) as excinfo:
            fetch_data(FetchDataInput(fetch_type="databases"), MagicMock(), AUTH_CREDS)

    assert str(excinfo.value) == "Failed to fetch databases: connection reset"
    assert excinfo.value.__cause__ is error


class _ProxyResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


def test_build_parent_page_branch() -> None:
    assert _build_parent("page_id", "par-123") == {"type": "page_id", "page_id": "par-123"}


def test_build_parent_database_branch() -> None:
    assert _build_parent("database_id", "db-456") == {
        "type": "database_id",
        "database_id": "db-456",
    }


def test_move_page_sends_exact_patch_and_returns_data_fields() -> None:
    request = MovePageInput(page_id="pg-9", parent_type="page_id", parent_id="par-1")
    execute_request = MagicMock(
        return_value=_ProxyResponse({"id": "moved-1", "url": "https://notion.so/moved-1"})
    )

    result = _move_page(request, execute_request)

    execute_request.assert_called_once_with(
        endpoint="/pages/pg-9",
        method="PATCH",
        body={"parent": {"type": "page_id", "page_id": "par-1"}},
    )
    assert result == {
        "page_id": "moved-1",
        "new_parent": {"type": "page_id", "page_id": "par-1"},
        "url": "https://notion.so/moved-1",
    }


def test_move_page_reads_response_directly_when_it_has_no_data_attribute() -> None:
    request = MovePageInput(page_id="pg-10", parent_type="database_id", parent_id="db-2")
    execute_request = MagicMock(return_value={"id": "id-2"})

    result = _move_page(request, execute_request)

    execute_request.assert_called_once_with(
        endpoint="/pages/pg-10",
        method="PATCH",
        body={"parent": {"type": "database_id", "database_id": "db-2"}},
    )
    assert result == {
        "page_id": "id-2",
        "new_parent": {"type": "database_id", "database_id": "db-2"},
        "url": None,
    }


def test_fetch_data_sends_exact_search_request_and_maps_results() -> None:
    request = FetchDataInput(fetch_type="pages", page_size=250, query="meeting notes")
    proxy = MagicMock(
        return_value={
            "results": [
                {
                    "id": "p1",
                    "object": "page",
                    "properties": {"Name": {"type": "title", "title": [{"plain_text": "Meeting"}]}},
                },
                {"object": "page"},
                {"id": "d1", "object": "database", "title": [{"plain_text": "Tasks DB"}]},
            ],
            "has_more": True,
        }
    )

    with patch(f"{MODULE}.proxy_request_sync", proxy):
        result = _fetch_data(request, AUTH_CREDS)

    proxy.assert_called_once_with(
        user_id="user_test_123",
        toolkit="NOTION",
        endpoint="https://api.notion.com/v1/search",
        method="POST",
        body={
            "filter": {"property": "object", "value": "page"},
            "page_size": 100,
            "query": "meeting notes",
        },
        headers={"Notion-Version": "2022-06-28"},
    )
    assert result == {
        "values": [
            {"id": "p1", "title": "Meeting", "type": "page"},
            {"id": "d1", "title": "Tasks DB", "type": "database"},
        ],
        "count": 2,
        "has_more": True,
    }


def test_fetch_data_databases_without_query_omits_query_and_defaults_has_more() -> None:
    request = FetchDataInput(fetch_type="databases", page_size=5)
    proxy = MagicMock(return_value={"results": []})

    with patch(f"{MODULE}.proxy_request_sync", proxy):
        result = _fetch_data(request, AUTH_CREDS)

    proxy.assert_called_once_with(
        user_id="user_test_123",
        toolkit="NOTION",
        endpoint="https://api.notion.com/v1/search",
        method="POST",
        body={"filter": {"property": "object", "value": "database"}, "page_size": 5},
        headers={"Notion-Version": "2022-06-28"},
    )
    assert result == {"values": [], "count": 0, "has_more": False}


def test_fetch_data_none_proxy_response_is_treated_as_empty() -> None:
    proxy = MagicMock(return_value=None)

    with patch(f"{MODULE}.proxy_request_sync", proxy):
        result = _fetch_data(FetchDataInput(fetch_type="pages"), AUTH_CREDS)

    assert result == {"values": [], "count": 0, "has_more": False}


def test_fetch_data_app_error_logs_and_raises_runtime_error_from_cause() -> None:
    error = AppError(message="Notion API error (500)", status_code=500)

    with (
        patch(f"{MODULE}.proxy_request_sync", side_effect=error),
        patch(f"{MODULE}.log") as log_mock,
    ):
        with pytest.raises(RuntimeError) as excinfo:
            _fetch_data(FetchDataInput(fetch_type="pages"), AUTH_CREDS)

    assert str(excinfo.value) == "Failed to fetch pages: Notion API error (500)"
    assert excinfo.value.__cause__ is error
    assert log_mock.error.call_args_list == [
        call(f"{LogTag.TOOL} Notion API error", error_type="AppError")
    ]


def test_fetch_data_unexpected_error_logs_fetch_type_and_raises_runtime_error() -> None:
    error = ValueError("connection reset")

    with (
        patch(f"{MODULE}.proxy_request_sync", side_effect=error),
        patch(f"{MODULE}.log") as log_mock,
    ):
        with pytest.raises(RuntimeError) as excinfo:
            _fetch_data(FetchDataInput(fetch_type="databases"), AUTH_CREDS)

    assert str(excinfo.value) == "Failed to fetch databases: connection reset"
    assert excinfo.value.__cause__ is error
    assert log_mock.error.call_args_list == [
        call(
            f"{LogTag.TOOL} Error fetching from Notion",
            fetch_type="databases",
            error_type="ValueError",
        ),
    ]


# --- registered tool wrappers: log.set contract -----------------------------


def test_move_page_wrapper_logs_action_and_delegates() -> None:
    _, tools, _ = _capture_tools(register_notion_custom_tools)
    move_page, _ = tools["NOTION_MOVE_PAGE"]
    execute_request = MagicMock(
        return_value=_ProxyResponse({"id": "moved-1", "url": "https://notion.so/moved-1"})
    )

    with patch(f"{MODULE}.log") as log_mock:
        result = move_page(
            MovePageInput(page_id="pg-9", parent_type="page_id", parent_id="par-1"),
            execute_request,
            AUTH_CREDS,
        )

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "notion", "action": "move_page"})
    ]
    assert result == {
        "page_id": "moved-1",
        "new_parent": {"type": "page_id", "page_id": "par-1"},
        "url": "https://notion.so/moved-1",
    }


def test_fetch_page_as_markdown_wrapper_logs_action_and_delegates() -> None:
    _, tools, composio = _capture_tools(register_notion_custom_tools)
    fetch_page_as_markdown, _ = tools["NOTION_FETCH_PAGE_AS_MARKDOWN"]
    request = FetchPageAsMarkdownInput(page_id="pg-11")
    delegate_result = {"page_id": "pg-11", "title": "Hello", "markdown": "# Hello"}

    with (
        patch(f"{MODULE}.log") as log_mock,
        patch(f"{MODULE}._fetch_page_as_markdown", return_value=delegate_result) as delegate,
    ):
        result = fetch_page_as_markdown(request, MagicMock(), AUTH_CREDS)

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "notion", "action": "fetch_page_as_markdown"})
    ]
    delegate.assert_called_once_with(composio, request, AUTH_CREDS)
    assert result == delegate_result


def test_insert_markdown_wrapper_logs_action_and_delegates() -> None:
    _, tools, composio = _capture_tools(register_notion_custom_tools)
    insert_markdown, _ = tools["NOTION_INSERT_MARKDOWN"]
    request = InsertMarkdownInput(parent_block_id="blk-1", markdown="# Hello")
    delegate_result = {"parent_block_id": "blk-1", "blocks_added": 1, "tables_added": 0}

    with (
        patch(f"{MODULE}.log") as log_mock,
        patch(f"{MODULE}._insert_markdown", return_value=delegate_result) as delegate,
    ):
        result = insert_markdown(request, MagicMock(), AUTH_CREDS)

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "notion", "action": "insert_markdown"})
    ]
    delegate.assert_called_once_with(composio, request, AUTH_CREDS)
    assert result == delegate_result


def test_fetch_data_wrapper_logs_action_and_delegates() -> None:
    _, tools, _ = _capture_tools(register_notion_custom_tools)
    fetch_data, _ = tools["NOTION_FETCH_DATA"]
    request = FetchDataInput(fetch_type="pages")
    delegate_result = {"values": [], "count": 0, "has_more": False}

    with (
        patch(f"{MODULE}.log") as log_mock,
        patch(f"{MODULE}._fetch_data", return_value=delegate_result) as delegate,
    ):
        result = fetch_data(request, MagicMock(), AUTH_CREDS)

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "notion", "action": "fetch_data"})
    ]
    delegate.assert_called_once_with(request, AUTH_CREDS)
    assert result == delegate_result


def test_custom_gather_context_wrapper_logs_action_and_queries_recent_pages() -> None:
    _, tools, _ = _capture_tools(register_notion_custom_tools)
    gather_context, _ = tools["NOTION_CUSTOM_GATHER_CONTEXT"]
    execute_tool_mock = MagicMock(return_value={"results": [{"id": "p1"}]})

    with patch(f"{MODULE}.log") as log_mock:
        with patch(f"{MODULE}.execute_tool", execute_tool_mock):
            result = gather_context(GatherContextInput(), MagicMock(), AUTH_CREDS)

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "notion", "action": "gather_context"})
    ]
    execute_tool_mock.assert_called_once_with(
        "NOTION_SEARCH_NOTION_PAGE", {"query": "", "page_size": 10}, "user_test_123"
    )
    assert result == {"relevant_pages": [{"id": "p1"}]}


def test_custom_gather_context_falls_back_to_pages_key() -> None:
    _, tools, _ = _capture_tools(register_notion_custom_tools)
    gather_context, _ = tools["NOTION_CUSTOM_GATHER_CONTEXT"]
    execute_tool_mock = MagicMock(return_value={"pages": [{"id": "p9"}]})

    with patch(f"{MODULE}.log"), patch(f"{MODULE}.execute_tool", execute_tool_mock):
        result = gather_context(GatherContextInput(), MagicMock(), AUTH_CREDS)

    assert result == {"relevant_pages": [{"id": "p9"}]}


def test_custom_gather_context_defaults_to_empty_list_when_neither_key_present() -> None:
    _, tools, _ = _capture_tools(register_notion_custom_tools)
    gather_context, _ = tools["NOTION_CUSTOM_GATHER_CONTEXT"]
    execute_tool_mock = MagicMock(return_value={})

    with patch(f"{MODULE}.log"), patch(f"{MODULE}.execute_tool", execute_tool_mock):
        result = gather_context(GatherContextInput(), MagicMock(), AUTH_CREDS)

    assert result == {"relevant_pages": []}


def test_wrapper_docstrings_are_pinned() -> None:
    _, captured, _ = _capture_tools(register_notion_custom_tools)

    # The other wrappers get their docstrings from @with_doc templates; this
    # one carries its own source docstring through to Composio registration.
    gather_fn, _ = captured["NOTION_CUSTOM_GATHER_CONTEXT"]
    assert gather_fn.__doc__ == (
        "Get Notion workspace context: recently edited pages and databases.\n"
        "\n"
        "        Zero required parameters. Returns recently modified content for situational awareness.\n"
        "        "
    )


def test_fetch_data_empty_string_query_is_omitted_from_search_body() -> None:
    request = FetchDataInput(fetch_type="pages", query="")
    proxy = MagicMock(return_value={"results": []})

    with patch(f"{MODULE}.proxy_request_sync", proxy):
        result = _fetch_data(request, AUTH_CREDS)

    assert "query" not in proxy.call_args.kwargs["body"]
    assert result == {"values": [], "count": 0, "has_more": False}


def test_fetch_data_strips_only_trailing_s_from_fetch_type() -> None:
    # Neither valid literal ("pages"/"databases") can tell an over-broad strip
    # set apart from rstrip("s"), so bypass validation to pin the exact filter.
    request = FetchDataInput.model_construct(fetch_type="pagesX", page_size=5)
    proxy = MagicMock(return_value={"results": []})

    with patch(f"{MODULE}.proxy_request_sync", proxy):
        _fetch_data(request, AUTH_CREDS)

    assert proxy.call_args.kwargs["body"]["filter"] == {
        "property": "object",
        "value": "pagesX",
    }


# --- extracted composio helpers: title / blocks / insert paths ----------------


def _composio_returning(result: dict[str, Any]) -> MagicMock:
    composio = MagicMock()
    composio.tools.execute.return_value = result
    return composio


def test_execute_notion_action_passes_version_through_from_credentials() -> None:
    composio = _composio_returning({"successful": True})
    creds: dict[str, Any] = {"user_id": "user_test_123", "version": "2024-01-01"}

    _execute_notion_action(composio, "SLUG_UNDER_TEST", {"arg": 1}, creds)

    composio.tools.execute.assert_called_once_with(
        slug="SLUG_UNDER_TEST",
        arguments={"arg": 1},
        version="2024-01-01",
        dangerously_skip_version_check=True,
        user_id="user_test_123",
    )


def test_fetch_page_blocks_returns_results_list_and_sends_exact_execute_call() -> None:
    composio = _composio_returning(
        {"successful": True, "data": {"results": [{"type": "paragraph"}]}}
    )
    request = FetchPageAsMarkdownInput(page_id="pg-7", recursive=True)

    blocks = _fetch_page_blocks(composio, request, AUTH_CREDS)

    assert blocks == [{"type": "paragraph"}]
    composio.tools.execute.assert_called_once_with(
        slug="NOTION_FETCH_ALL_BLOCK_CONTENTS",
        arguments={"block_id": "pg-7", "recursive": True, "page_size": 100},
        version=None,
        dangerously_skip_version_check=True,
        user_id="user_test_123",
    )


def test_fetch_page_blocks_falls_back_to_blocks_key_when_results_missing() -> None:
    composio = _composio_returning(
        {"successful": True, "data": {"blocks": [{"type": "paragraph"}]}}
    )

    blocks = _fetch_page_blocks(composio, FetchPageAsMarkdownInput(page_id="pg-8"), AUTH_CREDS)

    assert blocks == [{"type": "paragraph"}]


@patch(f"{MODULE}.blocks_to_markdown", return_value="# Body")
@patch(f"{MODULE}._fetch_page_blocks")
@patch(f"{MODULE}._fetch_page_title", return_value="Page Title")
def test_fetch_page_as_markdown_wires_helpers_and_pins_result_shape(
    mock_title: MagicMock,
    mock_blocks: MagicMock,
    mock_md: MagicMock,
) -> None:
    blocks = [{"type": "paragraph"}, {"type": "bulleted_list_item"}]
    mock_blocks.return_value = blocks
    composio = MagicMock()
    request = FetchPageAsMarkdownInput(page_id="pg-12", include_block_ids=False)

    result = _fetch_page_as_markdown(composio, request, AUTH_CREDS)

    mock_title.assert_called_once_with(composio, "pg-12", AUTH_CREDS)
    mock_blocks.assert_called_once_with(composio, request, AUTH_CREDS)
    mock_md.assert_called_once_with(blocks, include_block_ids=False)
    assert result == {
        "page_id": "pg-12",
        "title": "Page Title",
        "markdown": "# Page Title\n\n# Body",
        "block_count": 2,
    }


def test_fetch_page_title_unsuccessful_raises_app_error_with_502() -> None:
    composio = _composio_returning({"successful": False, "error": "upstream down"})

    with pytest.raises(AppError) as excinfo:
        _fetch_page_title(composio, "pg-1", AUTH_CREDS)

    assert excinfo.value.status_code == 502
    assert excinfo.value.message == "Failed to fetch Notion page title: upstream down"
    assert composio.tools.execute.call_args.kwargs["slug"] == "NOTION_GET_PAGE_PROPERTY_ACTION"
    assert composio.tools.execute.call_args.kwargs["arguments"] == {
        "page_id": "pg-1",
        "property_id": "title",
    }


def test_fetch_page_blocks_unsuccessful_raises_value_error() -> None:
    composio = _composio_returning({"successful": False, "error": "no blocks for you"})

    with pytest.raises(ValueError) as excinfo:
        _fetch_page_blocks(composio, FetchPageAsMarkdownInput(page_id="pg-1"), AUTH_CREDS)

    assert str(excinfo.value) == "Failed to fetch blocks: no blocks for you"


def test_append_table_block_sends_exact_table_args_and_raises_on_failure() -> None:
    request = InsertMarkdownInput(parent_block_id="blk-9", markdown="irrelevant")
    block: dict[str, Any] = {
        "type": "table",
        "table_width": 2,
        "rows": [["a", "b"]],
        "has_column_header": True,
    }
    composio = _composio_returning({"successful": True})

    _append_table_block(composio, request, block, AUTH_CREDS)

    composio.tools.execute.assert_called_once_with(
        slug="NOTION_APPEND_TABLE_BLOCKS",
        arguments={
            "block_id": "blk-9",
            "table_width": 2,
            "has_column_header": True,
            "rows": [["a", "b"]],
        },
        version=None,
        dangerously_skip_version_check=True,
        user_id="user_test_123",
    )

    failing = _composio_returning({"successful": False, "error": "table refused"})
    with pytest.raises(ValueError) as excinfo:
        _append_table_block(failing, request, block, AUTH_CREDS)
    assert str(excinfo.value) == "Failed to insert table: table refused"


def test_append_table_block_defaults_has_column_header_true_when_key_missing() -> None:
    request = InsertMarkdownInput(parent_block_id="blk-9", markdown="irrelevant")
    block: dict[str, Any] = {"type": "table", "table_width": 3, "rows": [["a", "b"]]}
    composio = _composio_returning({"successful": True})

    _append_table_block(composio, request, block, AUTH_CREDS)

    assert composio.tools.execute.call_args.kwargs["arguments"]["has_column_header"] is True


def test_append_table_block_honors_explicit_false_column_header() -> None:
    request = InsertMarkdownInput(parent_block_id="blk-9", markdown="irrelevant")
    block: dict[str, Any] = {
        "type": "table",
        "table_width": 2,
        "rows": [["a"]],
        "has_column_header": False,
    }
    composio = _composio_returning({"successful": True})

    _append_table_block(composio, request, block, AUTH_CREDS)

    assert composio.tools.execute.call_args.kwargs["arguments"]["has_column_header"] is False


def test_append_content_block_includes_after_only_when_set_and_raises_on_failure() -> None:
    request = InsertMarkdownInput(
        parent_block_id="blk-9", markdown="irrelevant", after="blk-anchor"
    )
    block: dict[str, Any] = {"type": "paragraph", "paragraph": {}}
    composio = _composio_returning({"successful": True})

    _append_content_block(composio, request, block, request.after, AUTH_CREDS)

    composio.tools.execute.assert_called_once_with(
        slug="NOTION_ADD_MULTIPLE_PAGE_CONTENT",
        arguments={
            "parent_block_id": "blk-9",
            "content_blocks": [block],
            "after": "blk-anchor",
        },
        version=None,
        dangerously_skip_version_check=True,
        user_id="user_test_123",
    )

    failing = _composio_returning({"successful": False, "error": "insert refused"})
    with pytest.raises(ValueError) as excinfo:
        _append_content_block(failing, request, block, None, AUTH_CREDS)
    assert str(excinfo.value) == "Failed to insert markdown: insert refused"
    assert "after" not in failing.tools.execute.call_args.kwargs["arguments"]


@patch(f"{MODULE}.markdown_to_notion_blocks")
def test_insert_markdown_without_blocks_raises_value_error(mock_convert: MagicMock) -> None:
    mock_convert.return_value = []

    with pytest.raises(ValueError) as excinfo:
        _insert_markdown(
            MagicMock(),
            InsertMarkdownInput(parent_block_id="blk-1", markdown=""),
            AUTH_CREDS,
        )

    assert str(excinfo.value) == "No content to insert - markdown conversion produced no blocks"
    mock_convert.assert_called_once_with("")


@patch(f"{MODULE}.markdown_to_notion_blocks")
def test_insert_markdown_routes_tables_and_positions_after_anchor(
    mock_convert: MagicMock,
) -> None:
    mock_convert.return_value = [
        {"type": "paragraph", "paragraph": {}},
        {"type": "table", "table_width": 1, "rows": [["a"]]},
        {"type": "heading_1", "heading_1": {}},
    ]
    request = InsertMarkdownInput(parent_block_id="blk-1", markdown="x", after="anchor")
    composio = _composio_returning({"successful": True})

    result = _insert_markdown(composio, request, AUTH_CREDS)

    slugs = [c.kwargs["slug"] for c in composio.tools.execute.call_args_list]
    assert slugs == [
        "NOTION_ADD_MULTIPLE_PAGE_CONTENT",
        "NOTION_APPEND_TABLE_BLOCKS",
        "NOTION_ADD_MULTIPLE_PAGE_CONTENT",
    ]
    mock_convert.assert_called_once_with("x")
    first_content, _, last_content = composio.tools.execute.call_args_list
    assert first_content.kwargs["arguments"]["after"] == "anchor"
    assert "after" not in last_content.kwargs["arguments"]
    assert first_content.kwargs["arguments"]["content_blocks"] == [
        {"type": "paragraph", "paragraph": {}}
    ]
    assert last_content.kwargs["arguments"]["content_blocks"] == [
        {"type": "heading_1", "heading_1": {}}
    ]
    assert result == {
        "parent_block_id": "blk-1",
        "blocks_added": 3,
        "tables_added": 1,
        "after": "anchor",
    }


@patch(f"{MODULE}.markdown_to_notion_blocks")
def test_insert_markdown_anchor_applies_only_to_first_content_block(
    mock_convert: MagicMock,
) -> None:
    mock_convert.return_value = [
        {"type": "paragraph", "paragraph": {}},
        {"type": "paragraph", "paragraph": {}},
    ]
    request = InsertMarkdownInput(parent_block_id="blk-2", markdown="x", after="anchor")
    composio = _composio_returning({"successful": True})

    result = _insert_markdown(composio, request, AUTH_CREDS)

    calls = composio.tools.execute.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["arguments"]["after"] == "anchor"
    assert "after" not in calls[1].kwargs["arguments"]
    assert result == {
        "parent_block_id": "blk-2",
        "blocks_added": 2,
        "tables_added": 0,
        "after": "anchor",
    }


@patch(f"{MODULE}.markdown_to_notion_blocks")
def test_insert_markdown_anchor_applies_to_first_content_after_leading_table(
    mock_convert: MagicMock,
) -> None:
    mock_convert.return_value = [
        {"type": "table", "table_width": 1, "rows": [["a"]]},
        {"type": "paragraph", "paragraph": {}},
    ]
    request = InsertMarkdownInput(parent_block_id="blk-3", markdown="x", after="anchor")
    composio = _composio_returning({"successful": True})

    result = _insert_markdown(composio, request, AUTH_CREDS)

    calls = composio.tools.execute.call_args_list
    assert [c.kwargs["slug"] for c in calls] == [
        "NOTION_APPEND_TABLE_BLOCKS",
        "NOTION_ADD_MULTIPLE_PAGE_CONTENT",
    ]
    assert calls[1].kwargs["arguments"]["after"] == "anchor"
    assert result == {
        "parent_block_id": "blk-3",
        "blocks_added": 2,
        "tables_added": 1,
        "after": "anchor",
    }


@patch(f"{MODULE}.markdown_to_notion_blocks")
def test_insert_markdown_all_tables_succeeds_without_content_call(
    mock_convert: MagicMock,
) -> None:
    mock_convert.return_value = [{"type": "table", "table_width": 1, "rows": [["a"]]}]
    request = InsertMarkdownInput(parent_block_id="blk-4", markdown="x", after="anchor")
    composio = _composio_returning({"successful": True})

    result = _insert_markdown(composio, request, AUTH_CREDS)

    slugs = [c.kwargs["slug"] for c in composio.tools.execute.call_args_list]
    assert slugs == ["NOTION_APPEND_TABLE_BLOCKS"]
    assert result == {
        "parent_block_id": "blk-4",
        "blocks_added": 1,
        "tables_added": 1,
        "after": "anchor",
    }


def test_item_title_page_with_empty_title_property_falls_back_to_untitled() -> None:
    item = {
        "object": "page",
        "properties": {"Name": {"type": "title", "title": []}},
    }

    assert _item_title(item) == "Untitled"


def test_item_title_database_entry_without_plain_text_falls_back_to_untitled() -> None:
    item = {"object": "database", "title": [{}]}

    assert _item_title(item) == "Untitled"


def test_item_title_page_title_entry_without_plain_text_falls_back_to_untitled() -> None:
    item = {
        "object": "page",
        "properties": {"Name": {"type": "title", "title": [{"id": 1}]}},
    }

    assert _item_title(item) == "Untitled"


def test_item_title_page_without_properties_key_falls_back_to_untitled() -> None:
    assert _item_title({"object": "page"}) == "Untitled"
