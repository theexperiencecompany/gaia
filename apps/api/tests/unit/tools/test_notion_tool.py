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
    _build_parent,
    _fetch_data,
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
) -> tuple[list[str], dict[str, tuple[Callable[..., Any], dict[str, Any]]]]:
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
    return registered, captured


def test_register_returns_exact_tool_names_and_toolkits() -> None:
    registered, captured = _capture_tools(register_notion_custom_tools)

    assert registered == EXPECTED_TOOL_NAMES
    assert sorted(captured) == sorted(EXPECTED_TOOL_NAMES)
    assert all(kwargs == {"toolkit": "NOTION"} for _, kwargs in captured.values())


def test_fetch_data_app_error_raises_runtime_error_with_message() -> None:
    _, tools = _capture_tools(register_notion_custom_tools)
    fetch_data, _ = tools["NOTION_FETCH_DATA"]
    error = AppError(message="Notion API error (500)", status_code=500)

    with patch(f"{MODULE}.proxy_request_sync", side_effect=error):
        with pytest.raises(RuntimeError) as excinfo:
            fetch_data(FetchDataInput(fetch_type="pages"), MagicMock(), AUTH_CREDS)

    assert str(excinfo.value) == "Failed to fetch pages: Notion API error (500)"
    assert excinfo.value.__cause__ is error


def test_fetch_data_unexpected_error_raises_runtime_error_with_str() -> None:
    _, tools = _capture_tools(register_notion_custom_tools)
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
    _, tools = _capture_tools(register_notion_custom_tools)
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


def test_fetch_page_as_markdown_wrapper_logs_action_and_returns_delegate_result() -> None:
    _, tools = _capture_tools(register_notion_custom_tools)
    fetch_page_as_markdown, _ = tools["NOTION_FETCH_PAGE_AS_MARKDOWN"]
    delegate_result = {"page_id": "pg-11", "title": "Hello", "markdown": "# Hello"}

    with (
        patch(f"{MODULE}.log") as log_mock,
        patch(f"{MODULE}._fetch_page_as_markdown", return_value=delegate_result),
    ):
        result = fetch_page_as_markdown(
            FetchPageAsMarkdownInput(page_id="pg-11"), MagicMock(), AUTH_CREDS
        )

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "notion", "action": "fetch_page_as_markdown"})
    ]
    assert result == delegate_result


def test_insert_markdown_wrapper_logs_action_and_returns_delegate_result() -> None:
    _, tools = _capture_tools(register_notion_custom_tools)
    insert_markdown, _ = tools["NOTION_INSERT_MARKDOWN"]
    request = InsertMarkdownInput(parent_block_id="blk-1", markdown="# Hello")
    delegate_result = {"parent_block_id": "blk-1", "blocks_added": 1, "tables_added": 0}

    with (
        patch(f"{MODULE}.log") as log_mock,
        patch(f"{MODULE}._insert_markdown", return_value=delegate_result),
    ):
        result = insert_markdown(request, MagicMock(), AUTH_CREDS)

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "notion", "action": "insert_markdown"})
    ]
    assert result == delegate_result


def test_fetch_data_wrapper_logs_action_and_returns_delegate_result() -> None:
    _, tools = _capture_tools(register_notion_custom_tools)
    fetch_data, _ = tools["NOTION_FETCH_DATA"]
    delegate_result = {"values": [], "count": 0, "has_more": False}

    with (
        patch(f"{MODULE}.log") as log_mock,
        patch(f"{MODULE}._fetch_data", return_value=delegate_result),
    ):
        result = fetch_data(FetchDataInput(fetch_type="pages"), MagicMock(), AUTH_CREDS)

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "notion", "action": "fetch_data"})
    ]
    assert result == delegate_result


def test_custom_gather_context_wrapper_logs_action_and_queries_recent_pages() -> None:
    _, tools = _capture_tools(register_notion_custom_tools)
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
