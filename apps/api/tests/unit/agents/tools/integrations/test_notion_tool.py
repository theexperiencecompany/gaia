"""Unit tests for the Notion custom tools (app/agents/tools/integrations/notion_tool.py).

Each tool is a Composio custom tool registered by `register_notion_custom_tools`.
Tests register them on a mock Composio client and mock only the seams below the
tools: `composio.tools.execute`, `proxy_request_sync`, the notion_md converters,
and `execute_tool`. The tools themselves run for real.
"""

from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from app.agents.tools.integrations import notion_tool
from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.notion_models import (
    FetchDataInput,
    FetchPageAsMarkdownInput,
    InsertMarkdownInput,
    MovePageInput,
)
from app.utils.errors import AppError

AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123"}


def _register_and_get_tools() -> tuple[list[str], dict[str, Any], MagicMock]:
    """Register tools on a mock Composio client; return (names, tools, mock_composio)."""
    tools: dict[str, Any] = {}
    mock_composio = MagicMock()

    def custom_tool_decorator(**_kwargs):
        def decorator(fn):
            tools[fn.__name__] = fn
            return fn

        return decorator

    mock_composio.tools.custom_tool = MagicMock(side_effect=custom_tool_decorator)
    names = notion_tool.register_notion_custom_tools(mock_composio)
    return names, tools, mock_composio


def _recording_execute_request(response: object) -> tuple[list[dict[str, Any]], Any]:
    """Return (calls, fn) where fn records its kwargs and returns `response`."""
    calls: list[dict[str, Any]] = []

    def execute_request(endpoint: str, method: str, body: dict[str, Any]) -> Any:
        calls.append({"endpoint": endpoint, "method": method, "body": body})
        return response

    return calls, execute_request


@pytest.fixture
def mock_proxy():
    with patch.object(notion_tool, "proxy_request_sync") as proxy:
        proxy.return_value = {}
        yield proxy


@pytest.fixture
def mock_logs():
    """Patch the wide-event log methods the tools call; yields (set, warning, error)."""
    with (
        patch.object(notion_tool.log, "set") as set_mock,
        patch.object(notion_tool.log, "warning") as warning_mock,
        patch.object(notion_tool.log, "error") as error_mock,
    ):
        yield set_mock, warning_mock, error_mock


class TestUserId:
    def test_returns_user_id(self):
        assert notion_tool._user_id({"user_id": "u1"}) == "u1"

    def test_missing_user_id_raises(self):
        with pytest.raises(ValueError) as exc_info:
            notion_tool._user_id({})
        assert str(exc_info.value) == "Missing user_id in auth_credentials"

    def test_empty_user_id_raises(self):
        with pytest.raises(ValueError) as exc_info:
            notion_tool._user_id({"user_id": ""})
        assert str(exc_info.value) == "Missing user_id in auth_credentials"

    def test_none_user_id_raises(self):
        with pytest.raises(ValueError) as exc_info:
            notion_tool._user_id({"user_id": None})
        assert str(exc_info.value) == "Missing user_id in auth_credentials"

    def test_non_string_user_id_raises(self):
        with pytest.raises(ValueError) as exc_info:
            notion_tool._user_id({"user_id": 123})
        assert str(exc_info.value) == "Missing user_id in auth_credentials"


class TestRegistration:
    def test_returns_expected_tool_names(self):
        names, _, _ = _register_and_get_tools()
        assert names == [
            "NOTION_MOVE_PAGE",
            "NOTION_FETCH_PAGE_AS_MARKDOWN",
            "NOTION_INSERT_MARKDOWN",
            "NOTION_FETCH_DATA",
            "NOTION_CUSTOM_GATHER_CONTEXT",
        ]

    def test_registers_each_tool_with_notion_toolkit(self):
        _, _, mock_composio = _register_and_get_tools()
        assert mock_composio.tools.custom_tool.call_count == 5
        for call in mock_composio.tools.custom_tool.call_args_list:
            assert call.kwargs == {"toolkit": "NOTION"}


class TestMovePage:
    def test_page_id_parent(self, mock_logs):
        set_mock, _, _ = mock_logs
        _, tools, _ = _register_and_get_tools()
        calls, execute_request = _recording_execute_request(
            {"id": "pg1", "url": "https://notion.so/1"}
        )
        result = tools["MOVE_PAGE"](
            request=MovePageInput(page_id="pg1", parent_type="page_id", parent_id="parent1"),
            execute_request=execute_request,
            auth_credentials=AUTH_CREDS,
        )
        assert calls == [
            {
                "endpoint": "/pages/pg1",
                "method": "PATCH",
                "body": {"parent": {"type": "page_id", "page_id": "parent1"}},
            }
        ]
        assert result == {
            "page_id": "pg1",
            "new_parent": {"type": "page_id", "page_id": "parent1"},
            "url": "https://notion.so/1",
        }
        set_mock.assert_called_once_with(tool={"integration": "notion", "action": "move_page"})

    def test_database_id_parent(self):
        _, tools, _ = _register_and_get_tools()
        calls, execute_request = _recording_execute_request({"id": "pg2"})
        result = tools["MOVE_PAGE"](
            request=MovePageInput(page_id="pg2", parent_type="database_id", parent_id="db1"),
            execute_request=execute_request,
            auth_credentials=AUTH_CREDS,
        )
        assert calls == [
            {
                "endpoint": "/pages/pg2",
                "method": "PATCH",
                "body": {"parent": {"type": "database_id", "database_id": "db1"}},
            }
        ]
        assert result == {
            "page_id": "pg2",
            "new_parent": {"type": "database_id", "database_id": "db1"},
            "url": None,
        }

    def test_response_with_data_attribute(self):
        _, tools, _ = _register_and_get_tools()
        response = SimpleNamespace(data={"id": "pg3", "url": "https://notion.so/3"})
        result = tools["MOVE_PAGE"](
            request=MovePageInput(page_id="pg3", parent_type="page_id", parent_id="p"),
            execute_request=lambda **_: response,
            auth_credentials=AUTH_CREDS,
        )
        assert result == {
            "page_id": "pg3",
            "new_parent": {"type": "page_id", "page_id": "p"},
            "url": "https://notion.so/3",
        }

    def test_missing_id_and_url_in_response(self):
        _, tools, _ = _register_and_get_tools()
        result = tools["MOVE_PAGE"](
            request=MovePageInput(page_id="pg4", parent_type="page_id", parent_id="p"),
            execute_request=lambda **_: {"unrelated": 1},
            auth_credentials=AUTH_CREDS,
        )
        assert result == {
            "page_id": None,
            "new_parent": {"type": "page_id", "page_id": "p"},
            "url": None,
        }


class TestFetchPageAsMarkdown:
    TITLE_RESPONSE: ClassVar[dict[str, Any]] = {
        "successful": True,
        "data": {"results": [{"type": "title", "title": {"plain_text": "My Title"}}]},
    }
    BLOCKS_RESPONSE: ClassVar[dict[str, Any]] = {
        "successful": True,
        "data": {"results": [{"id": "b1"}, {"id": "b2"}]},
    }

    @staticmethod
    def _tool_and_execute() -> tuple[Any, MagicMock]:
        _, tools, mock_composio = _register_and_get_tools()
        return tools["FETCH_PAGE_AS_MARKDOWN"], mock_composio.tools.execute

    def test_extracts_title_and_converts_blocks(self, mock_logs):
        set_mock, _, _ = mock_logs
        tool, execute = self._tool_and_execute()
        execute.side_effect = [self.TITLE_RESPONSE, self.BLOCKS_RESPONSE]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted") as to_md:
            result = tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result == {
            "page_id": "pg1",
            "title": "My Title",
            "markdown": "# My Title\n\nconverted",
            "block_count": 2,
        }
        to_md.assert_called_once_with([{"id": "b1"}, {"id": "b2"}], include_block_ids=True)
        execute.assert_any_call(
            slug="NOTION_GET_PAGE_PROPERTY_ACTION",
            arguments={"page_id": "pg1", "property_id": "title"},
            version=None,
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        )
        execute.assert_any_call(
            slug="NOTION_FETCH_ALL_BLOCK_CONTENTS",
            arguments={"block_id": "pg1", "recursive": True, "page_size": 100},
            version=None,
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        )
        set_mock.assert_called_once_with(
            tool={"integration": "notion", "action": "fetch_page_as_markdown"}
        )

    def test_forward_recursive_and_include_block_ids_flags(self, mock_logs):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [self.TITLE_RESPONSE, self.BLOCKS_RESPONSE]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted") as to_md:
            tool(
                request=FetchPageAsMarkdownInput(
                    page_id="pg1", recursive=False, include_block_ids=False
                ),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        to_md.assert_called_once_with([{"id": "b1"}, {"id": "b2"}], include_block_ids=False)
        execute.assert_any_call(
            slug="NOTION_FETCH_ALL_BLOCK_CONTENTS",
            arguments={"block_id": "pg1", "recursive": False, "page_size": 100},
            version=None,
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        )

    def test_title_fetch_failure_logs_warning_and_leaves_title_empty(self, mock_logs):
        _, warning_mock, _ = mock_logs
        tool, execute = self._tool_and_execute()
        execute.side_effect = [
            {"successful": False, "error": "title err"},
            self.BLOCKS_RESPONSE,
        ]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted"):
            result = tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result["title"] == ""
        assert result["markdown"] == "converted"
        warning_mock.assert_called_once_with(
            f"{LogTag.TOOL} Failed to fetch title", error="title err"
        )

    def test_title_fetch_exception_logs_warning_and_leaves_title_empty(self, mock_logs):
        _, warning_mock, _ = mock_logs
        tool, execute = self._tool_and_execute()
        execute.side_effect = [RuntimeError("boom"), self.BLOCKS_RESPONSE]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted"):
            result = tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result["title"] == ""
        assert result["markdown"] == "converted"
        warning_mock.assert_called_once_with(
            f"{LogTag.TOOL} Could not fetch title", error_type="RuntimeError"
        )

    def test_non_title_items_are_not_extracted(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [
            {
                "successful": True,
                "data": {"results": [{"type": "rich_text", "title": {"plain_text": "Not Me"}}]},
            },
            self.BLOCKS_RESPONSE,
        ]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted"):
            result = tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result["title"] == ""
        assert result["markdown"] == "converted"

    def test_title_without_plain_text_defaults_to_empty(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [
            {"successful": True, "data": {"results": [{"type": "title", "title": {"other": 1}}]}},
            self.BLOCKS_RESPONSE,
        ]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted"):
            result = tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result["title"] == ""

    def test_title_data_without_results_key_leaves_title_empty(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [
            {"successful": True, "data": {"other": 1}},
            self.BLOCKS_RESPONSE,
        ]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted"):
            result = tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result["title"] == ""
        assert result["markdown"] == "converted"

    def test_first_title_item_wins(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [
            {
                "successful": True,
                "data": {
                    "results": [
                        {"type": "title", "title": {"plain_text": "First"}},
                        {"type": "title", "title": {"plain_text": "Second"}},
                    ]
                },
            },
            self.BLOCKS_RESPONSE,
        ]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted"):
            result = tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result["title"] == "First"
        assert result["markdown"] == "# First\n\nconverted"

    def test_title_fetch_failure_without_error_key_logs_none(self, mock_logs):
        _, warning_mock, _ = mock_logs
        tool, execute = self._tool_and_execute()
        execute.side_effect = [{"successful": False}, self.BLOCKS_RESPONSE]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted"):
            tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert warning_mock.call_args.kwargs["error"] is None

    def test_blocks_fetch_failure_without_error_key(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [self.TITLE_RESPONSE, {"successful": False}]
        with pytest.raises(ValueError) as exc_info:
            tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert str(exc_info.value) == "Failed to fetch blocks: None"

    def test_blocks_data_without_keys_yields_empty_blocks(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [self.TITLE_RESPONSE, {"successful": True, "data": {}}]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted") as to_md:
            result = tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        to_md.assert_called_once_with([], include_block_ids=True)
        assert result["block_count"] == 0

    def test_blocks_fetch_failure_raises(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [
            self.TITLE_RESPONSE,
            {"successful": False, "error": "blocks err"},
        ]
        with pytest.raises(ValueError, match="Failed to fetch blocks: blocks err"):
            tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

    def test_blocks_under_blocks_key(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [
            self.TITLE_RESPONSE,
            {"successful": True, "data": {"blocks": [{"id": "b9"}]}},
        ]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted") as to_md:
            result = tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        to_md.assert_called_once_with([{"id": "b9"}], include_block_ids=True)
        assert result["block_count"] == 1
        assert result["markdown"] == "# My Title\n\nconverted"

    def test_blocks_data_not_a_dict_yields_empty_blocks(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [self.TITLE_RESPONSE, {"successful": True, "data": [{"id": "b1"}]}]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted") as to_md:
            result = tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        to_md.assert_called_once_with([], include_block_ids=True)
        assert result["block_count"] == 0
        assert result["markdown"] == "# My Title\n\nconverted"

    def test_blocks_not_a_list_yields_empty_markdown(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [
            {"successful": True, "data": {"results": []}},
            {"successful": True, "data": {"results": "not-a-list"}},
        ]
        with patch.object(notion_tool, "blocks_to_markdown") as to_md:
            result = tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        to_md.assert_not_called()
        assert result == {
            "page_id": "pg1",
            "title": "",
            "markdown": "",
            "block_count": 0,
        }

    def test_missing_credentials_pass_none_to_composio(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [self.TITLE_RESPONSE, self.BLOCKS_RESPONSE]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted"):
            tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials={},
            )
        for call in execute.call_args_list:
            assert call.kwargs["user_id"] is None
            assert call.kwargs["version"] is None

    def test_credentials_version_forwarded_to_composio(self):
        tool, execute = self._tool_and_execute()
        execute.side_effect = [self.TITLE_RESPONSE, self.BLOCKS_RESPONSE]
        with patch.object(notion_tool, "blocks_to_markdown", return_value="converted"):
            tool(
                request=FetchPageAsMarkdownInput(page_id="pg1"),
                execute_request=MagicMock(),
                auth_credentials={"user_id": "user_test_123", "version": "v1.0"},
            )
        assert execute.call_count == 2
        for call in execute.call_args_list:
            assert call.kwargs["version"] == "v1.0"


class TestInsertMarkdown:
    @staticmethod
    def _tool_and_execute() -> tuple[Any, MagicMock]:
        _, tools, mock_composio = _register_and_get_tools()
        return tools["INSERT_MARKDOWN"], mock_composio.tools.execute

    def test_empty_conversion_raises(self, mock_logs):
        set_mock, _, _ = mock_logs
        tool, execute = self._tool_and_execute()
        with patch.object(notion_tool, "markdown_to_notion_blocks", return_value=[]) as to_blocks:
            with pytest.raises(ValueError) as exc_info:
                tool(
                    request=InsertMarkdownInput(parent_block_id="parent1", markdown="# Hi"),
                    execute_request=MagicMock(),
                    auth_credentials=AUTH_CREDS,
                )
        assert (
            str(exc_info.value) == "No content to insert - markdown conversion produced no blocks"
        )
        to_blocks.assert_called_once_with("# Hi")
        execute.assert_not_called()
        set_mock.assert_called_once_with(
            tool={"integration": "notion", "action": "insert_markdown"}
        )

    def test_content_blocks_after_only_on_first_insert(self, mock_logs):
        tool, execute = self._tool_and_execute()
        blocks = [
            {"type": "paragraph", "content": "one"},
            {"type": "paragraph", "content": "two"},
        ]
        execute.return_value = {"successful": True, "data": {}}
        with patch.object(notion_tool, "markdown_to_notion_blocks", return_value=blocks):
            result = tool(
                request=InsertMarkdownInput(
                    parent_block_id="parent1", markdown="m", after="block9"
                ),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result == {
            "parent_block_id": "parent1",
            "blocks_added": 2,
            "tables_added": 0,
            "after": "block9",
        }
        assert execute.call_count == 2
        assert all(
            c.kwargs["slug"] == "NOTION_ADD_MULTIPLE_PAGE_CONTENT" for c in execute.call_args_list
        )
        execute.assert_any_call(
            slug="NOTION_ADD_MULTIPLE_PAGE_CONTENT",
            arguments={
                "parent_block_id": "parent1",
                "content_blocks": [blocks[0]],
                "after": "block9",
            },
            version=None,
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        )
        execute.assert_any_call(
            slug="NOTION_ADD_MULTIPLE_PAGE_CONTENT",
            arguments={"parent_block_id": "parent1", "content_blocks": [blocks[1]]},
            version=None,
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        )

    def test_no_after_omits_key_from_arguments(self):
        tool, execute = self._tool_and_execute()
        block = {"type": "paragraph", "content": "solo"}
        execute.return_value = {"successful": True, "data": {}}
        with patch.object(notion_tool, "markdown_to_notion_blocks", return_value=[block]):
            result = tool(
                request=InsertMarkdownInput(parent_block_id="parent1", markdown="m"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert execute.call_args.kwargs["arguments"] == {
            "parent_block_id": "parent1",
            "content_blocks": [block],
        }
        assert result["blocks_added"] == 1
        assert result["tables_added"] == 0
        assert result["after"] is None

    def test_table_block_uses_append_table_tool(self):
        tool, execute = self._tool_and_execute()
        table = {"type": "table", "table_width": 3, "rows": [{"cells": [["a"]]}]}
        execute.return_value = {"successful": True, "data": {}}
        with patch.object(notion_tool, "markdown_to_notion_blocks", return_value=[table]):
            result = tool(
                request=InsertMarkdownInput(parent_block_id="parent1", markdown="t"),
                execute_request=MagicMock(),
                auth_credentials={"user_id": "user_test_123", "version": "v1.0"},
            )
        assert result == {
            "parent_block_id": "parent1",
            "blocks_added": 1,
            "tables_added": 1,
            "after": None,
        }
        execute.assert_called_once_with(
            slug="NOTION_APPEND_TABLE_BLOCKS",
            arguments={
                "block_id": "parent1",
                "table_width": 3,
                "has_column_header": True,
                "rows": [{"cells": [["a"]]}],
            },
            version="v1.0",
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        )

    def test_table_without_has_column_header_defaults_true(self):
        tool, execute = self._tool_and_execute()
        table = {"type": "table", "table_width": 2, "rows": []}
        execute.return_value = {"successful": True, "data": {}}
        with patch.object(notion_tool, "markdown_to_notion_blocks", return_value=[table]):
            tool(
                request=InsertMarkdownInput(parent_block_id="parent1", markdown="t"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert execute.call_args.kwargs["arguments"]["has_column_header"] is True

    def test_table_with_has_column_header_false_forwarded(self):
        tool, execute = self._tool_and_execute()
        table = {"type": "table", "table_width": 2, "has_column_header": False, "rows": []}
        execute.return_value = {"successful": True, "data": {}}
        with patch.object(notion_tool, "markdown_to_notion_blocks", return_value=[table]):
            tool(
                request=InsertMarkdownInput(parent_block_id="parent1", markdown="t"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert execute.call_args.kwargs["arguments"]["has_column_header"] is False

    def test_table_response_failure_raises(self):
        tool, execute = self._tool_and_execute()
        table = {"type": "table", "table_width": 2, "rows": []}
        execute.return_value = {"successful": False, "error": "table err"}
        with patch.object(notion_tool, "markdown_to_notion_blocks", return_value=[table]):
            with pytest.raises(ValueError, match="Failed to insert table: table err"):
                tool(
                    request=InsertMarkdownInput(parent_block_id="parent1", markdown="t"),
                    execute_request=MagicMock(),
                    auth_credentials=AUTH_CREDS,
                )

    def test_content_response_failure_raises(self):
        tool, execute = self._tool_and_execute()
        execute.return_value = {"successful": False, "error": "content err"}
        with patch.object(
            notion_tool, "markdown_to_notion_blocks", return_value=[{"type": "paragraph"}]
        ):
            with pytest.raises(ValueError, match="Failed to insert markdown: content err"):
                tool(
                    request=InsertMarkdownInput(parent_block_id="parent1", markdown="m"),
                    execute_request=MagicMock(),
                    auth_credentials=AUTH_CREDS,
                )

    def test_mixed_blocks_route_to_correct_slugs_and_count(self):
        tool, execute = self._tool_and_execute()
        table = {"type": "table", "table_width": 2, "rows": []}
        blocks = [
            table,
            {"type": "paragraph", "content": "x"},
            {"type": "paragraph", "content": "y"},
        ]
        execute.side_effect = [
            {"successful": True, "data": {}},
            {"successful": True, "data": {}},
            {"successful": True, "data": {}},
        ]
        with patch.object(notion_tool, "markdown_to_notion_blocks", return_value=blocks):
            result = tool(
                request=InsertMarkdownInput(parent_block_id="parent1", markdown="m"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result["blocks_added"] == 3
        assert result["tables_added"] == 1
        assert [c.kwargs["slug"] for c in execute.call_args_list] == [
            "NOTION_APPEND_TABLE_BLOCKS",
            "NOTION_ADD_MULTIPLE_PAGE_CONTENT",
            "NOTION_ADD_MULTIPLE_PAGE_CONTENT",
        ]

    def test_content_block_before_table_counts_correctly(self):
        tool, execute = self._tool_and_execute()
        blocks = [
            {"type": "paragraph", "content": "x"},
            {"type": "table", "table_width": 2, "rows": []},
        ]
        execute.side_effect = [{"successful": True, "data": {}}, {"successful": True, "data": {}}]
        with patch.object(notion_tool, "markdown_to_notion_blocks", return_value=blocks):
            result = tool(
                request=InsertMarkdownInput(parent_block_id="parent1", markdown="m"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result["blocks_added"] == 2
        assert result["tables_added"] == 1

    def test_credentials_version_forwarded_to_composio(self):
        tool, execute = self._tool_and_execute()
        execute.return_value = {"successful": True, "data": {}}
        with patch.object(
            notion_tool, "markdown_to_notion_blocks", return_value=[{"type": "paragraph"}]
        ):
            tool(
                request=InsertMarkdownInput(parent_block_id="parent1", markdown="m"),
                execute_request=MagicMock(),
                auth_credentials={"user_id": "user_test_123", "version": "v1.0"},
            )
        assert execute.call_count == 1
        assert execute.call_args.kwargs["version"] == "v1.0"


class TestFetchData:
    @staticmethod
    def _tool() -> Any:
        _, tools, _ = _register_and_get_tools()
        return tools["FETCH_DATA"]

    def test_fetches_databases_with_exact_proxy_request(self, mock_proxy, mock_logs):
        set_mock, _, _ = mock_logs
        mock_proxy.return_value = {"results": [], "has_more": False}
        result = self._tool()(
            request=FetchDataInput(fetch_type="databases"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result == {"values": [], "count": 0, "has_more": False}
        mock_proxy.assert_called_once_with(
            user_id="user_test_123",
            toolkit="NOTION",
            endpoint="https://api.notion.com/v1/search",
            method="POST",
            body={"filter": {"property": "object", "value": "database"}, "page_size": 100},
            headers={"Notion-Version": "2022-06-28"},
        )
        set_mock.assert_called_once_with(tool={"integration": "notion", "action": "fetch_data"})

    def test_pages_fetch_strips_suffix(self, mock_proxy):
        mock_proxy.return_value = {"results": []}
        self._tool()(
            request=FetchDataInput(fetch_type="pages"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert mock_proxy.call_args.kwargs["body"]["filter"]["value"] == "page"

    def test_page_size_capped_at_100(self, mock_proxy):
        mock_proxy.return_value = {"results": []}
        self._tool()(
            request=FetchDataInput(fetch_type="databases", page_size=250),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert mock_proxy.call_args.kwargs["body"]["page_size"] == 100

    def test_page_size_under_cap_passed_through(self, mock_proxy):
        mock_proxy.return_value = {"results": []}
        self._tool()(
            request=FetchDataInput(fetch_type="databases", page_size=50),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert mock_proxy.call_args.kwargs["body"]["page_size"] == 50

    def test_query_included_when_set(self, mock_proxy):
        mock_proxy.return_value = {"results": []}
        self._tool()(
            request=FetchDataInput(fetch_type="databases", query="roadmap"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert mock_proxy.call_args.kwargs["body"]["query"] == "roadmap"

    def test_query_omitted_when_unset(self, mock_proxy):
        mock_proxy.return_value = {"results": []}
        self._tool()(
            request=FetchDataInput(fetch_type="databases"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert "query" not in mock_proxy.call_args.kwargs["body"]

    def test_none_proxy_response_yields_empty_result(self, mock_proxy):
        mock_proxy.return_value = None
        result = self._tool()(
            request=FetchDataInput(fetch_type="databases"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result == {"values": [], "count": 0, "has_more": False}

    def test_database_title_extracted(self, mock_proxy):
        mock_proxy.return_value = {
            "results": [{"id": "db1", "object": "database", "title": [{"plain_text": "My DB"}]}]
        }
        result = self._tool()(
            request=FetchDataInput(fetch_type="databases"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["values"] == [{"id": "db1", "title": "My DB", "type": "database"}]
        assert result["count"] == 1

    def test_database_empty_title_array_untitled(self, mock_proxy):
        mock_proxy.return_value = {"results": [{"id": "db1", "object": "database", "title": []}]}
        result = self._tool()(
            request=FetchDataInput(fetch_type="databases"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["values"][0]["title"] == "Untitled"

    def test_database_title_entry_without_plain_text_untitled(self, mock_proxy):
        mock_proxy.return_value = {
            "results": [{"id": "db1", "object": "database", "title": [{"other": 1}]}]
        }
        result = self._tool()(
            request=FetchDataInput(fetch_type="databases"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["values"][0]["title"] == "Untitled"

    def test_page_title_extracted_from_properties(self, mock_proxy):
        mock_proxy.return_value = {
            "results": [
                {
                    "id": "pg1",
                    "object": "page",
                    "properties": {
                        "Name": {"type": "title", "title": [{"plain_text": "Page One"}]}
                    },
                }
            ]
        }
        result = self._tool()(
            request=FetchDataInput(fetch_type="pages"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["values"] == [{"id": "pg1", "title": "Page One", "type": "page"}]

    def test_page_title_entry_without_plain_text_untitled(self, mock_proxy):
        mock_proxy.return_value = {
            "results": [
                {
                    "id": "pg1",
                    "object": "page",
                    "properties": {"Name": {"type": "title", "title": [{"other": 1}]}},
                }
            ]
        }
        result = self._tool()(
            request=FetchDataInput(fetch_type="pages"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["values"][0]["title"] == "Untitled"

    def test_page_first_title_property_wins(self, mock_proxy):
        mock_proxy.return_value = {
            "results": [
                {
                    "id": "pg1",
                    "object": "page",
                    "properties": {
                        "A": {"type": "title", "title": [{"plain_text": "First"}]},
                        "B": {"type": "title", "title": [{"plain_text": "Second"}]},
                    },
                }
            ]
        }
        result = self._tool()(
            request=FetchDataInput(fetch_type="pages"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["values"][0]["title"] == "First"

    def test_page_without_title_property_untitled(self, mock_proxy):
        mock_proxy.return_value = {
            "results": [
                {
                    "id": "pg1",
                    "object": "page",
                    "properties": {"Body": {"type": "rich_text", "rich_text": []}},
                },
                {"id": "pg2", "object": "page"},
            ]
        }
        result = self._tool()(
            request=FetchDataInput(fetch_type="pages"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert [v["title"] for v in result["values"]] == ["Untitled", "Untitled"]

    def test_items_without_id_skipped(self, mock_proxy):
        mock_proxy.return_value = {
            "results": [{"object": "database", "title": [{"plain_text": "No ID"}]}]
        }
        result = self._tool()(
            request=FetchDataInput(fetch_type="databases"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["values"] == []
        assert result["count"] == 0

    def test_has_more_true_reported(self, mock_proxy):
        mock_proxy.return_value = {"results": [], "has_more": True}
        result = self._tool()(
            request=FetchDataInput(fetch_type="databases"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["has_more"] is True

    def test_mixed_results_preserve_order(self, mock_proxy):
        mock_proxy.return_value = {
            "results": [
                {"id": "db1", "object": "database", "title": [{"plain_text": "DB"}]},
                {"id": "pg1", "object": "page", "properties": {}},
                {"id": "db2", "object": "database"},
            ]
        }
        result = self._tool()(
            request=FetchDataInput(fetch_type="databases"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["values"] == [
            {"id": "db1", "title": "DB", "type": "database"},
            {"id": "pg1", "title": "Untitled", "type": "page"},
            {"id": "db2", "title": "Untitled", "type": "database"},
        ]
        assert result["count"] == 3

    def test_app_error_wrapped_as_runtime_error(self, mock_proxy, mock_logs):
        _, _, error_mock = mock_logs
        mock_proxy.side_effect = AppError("proxy rejected")
        with pytest.raises(RuntimeError, match="Failed to fetch databases: proxy rejected"):
            self._tool()(
                request=FetchDataInput(fetch_type="databases"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        error_mock.assert_called_once_with(f"{LogTag.TOOL} Notion API error", error_type="AppError")

    def test_generic_error_wrapped_as_runtime_error(self, mock_proxy, mock_logs):
        _, _, error_mock = mock_logs
        mock_proxy.side_effect = RuntimeError("kaboom")
        with pytest.raises(RuntimeError, match="Failed to fetch pages: kaboom"):
            self._tool()(
                request=FetchDataInput(fetch_type="pages"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        error_mock.assert_called_once_with(
            f"{LogTag.TOOL} Error fetching from Notion",
            fetch_type="pages",
            error_type="RuntimeError",
        )

    def test_missing_user_id_propagates_value_error(self, mock_proxy):
        with pytest.raises(ValueError):
            self._tool()(
                request=FetchDataInput(fetch_type="databases"),
                execute_request=MagicMock(),
                auth_credentials={},
            )
        mock_proxy.assert_not_called()


class TestGatherContext:
    @staticmethod
    def _tool() -> Any:
        _, tools, _ = _register_and_get_tools()
        return tools["CUSTOM_GATHER_CONTEXT"]

    def test_returns_results_from_execute_tool(self, mock_logs):
        set_mock, _, _ = mock_logs
        with patch.object(
            notion_tool, "execute_tool", return_value={"results": [{"id": "r1"}]}
        ) as exec_tool:
            result = self._tool()(
                request=GatherContextInput(),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result == {"relevant_pages": [{"id": "r1"}]}
        exec_tool.assert_called_once_with(
            "NOTION_SEARCH_NOTION_PAGE", {"query": "", "page_size": 10}, "user_test_123"
        )
        set_mock.assert_called_once_with(tool={"integration": "notion", "action": "gather_context"})

    def test_pages_key_fallback(self):
        with patch.object(notion_tool, "execute_tool", return_value={"pages": [{"id": "p1"}]}):
            result = self._tool()(
                request=GatherContextInput(),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result == {"relevant_pages": [{"id": "p1"}]}

    def test_results_key_wins_over_pages(self):
        with patch.object(
            notion_tool,
            "execute_tool",
            return_value={"results": [{"id": "r"}], "pages": [{"id": "p"}]},
        ):
            result = self._tool()(
                request=GatherContextInput(),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result == {"relevant_pages": [{"id": "r"}]}

    def test_no_keys_returns_empty(self):
        with patch.object(notion_tool, "execute_tool", return_value={}):
            result = self._tool()(
                request=GatherContextInput(),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result == {"relevant_pages": []}

    def test_missing_user_id_raises(self):
        with pytest.raises(ValueError):
            self._tool()(
                request=GatherContextInput(),
                execute_request=MagicMock(),
                auth_credentials={},
            )
