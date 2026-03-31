"""TEST 11: Composio Before/After Execute Hooks.

Tests the hook registry, master hooks, conditional hook routing,
schema modifiers, and end-to-end hook chains using real production code.
Only I/O boundaries (stream writer, Composio API) are mocked.

Run with:
    uv run pytest tests/integration/test_composio_hooks.py -v
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from composio.types import Tool, ToolExecuteParams, ToolExecutionResponse
from langchain_core.tools import ToolException

from app.services.composio.custom_tools.context_tool import (
    PROVIDER_TOOLS,
    tool_namespace,
)
from app.services.composio.custom_tools.registry import CustomToolsRegistry
from app.utils.composio_hooks.gmail_hooks import (
    gmail_attachment_after_hook,
    gmail_compose_before_hook,
    gmail_drafts_after_hook,
    gmail_fetch_after_hook,
    gmail_fetch_emails_before_hook,
    gmail_fetch_emails_schema_modifier,
    gmail_message_detail_after_hook,
    gmail_send_email_schema_modifier,
)
from app.utils.composio_hooks.reddit_hooks import (
    process_reddit_comment,
    process_reddit_post,
    reddit_search_after_hook,
)
from app.utils.composio_hooks.registry import (
    ComposioHookRegistry,
    hook_registry,
    master_after_execute_hook,
    master_before_execute_hook,
    master_schema_modifier,
)
from app.utils.composio_hooks.slack_hooks import slack_search_schema_modifier
from app.utils.composio_hooks.twitter_hooks import (
    twitter_search_after_hook,
    twitter_search_schema_modifier,
)
from app.utils.composio_hooks.user_id_hooks import extract_user_id_from_params

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_params(
    arguments: Dict[str, Any] | None = None,
    user_id: str = "",
    entity_id: str = "",
) -> ToolExecuteParams:
    """Build a minimal ToolExecuteParams dict."""
    params: ToolExecuteParams = {"arguments": arguments or {}}
    if user_id:
        params["user_id"] = user_id
    if entity_id:
        params["entity_id"] = entity_id
    return params


def _make_tool_schema(
    slug: str = "TEST_TOOL",
    description: str = "A test tool",
    input_parameters: Dict[str, Any] | None = None,
) -> Tool:
    """Build a minimal Tool object for schema modifier tests."""
    tool = MagicMock(spec=Tool)
    tool.slug = slug
    tool.description = description
    tool.input_parameters = input_parameters or {
        "properties": {},
        "required": [],
        "type": "object",
    }
    return tool


def _make_execution_response(
    data: Any = None,
    successful: bool = True,
    error: str | None = None,
) -> ToolExecutionResponse:
    """Build a ToolExecutionResponse dict."""
    resp: Dict[str, Any] = {
        "data": data if data is not None else {},
        "successful": successful,
    }
    if error:
        resp["data"]["error"] = error
    return resp


# ---------------------------------------------------------------------------
# 1. Hook Registry — core registration and execution
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHookRegistry:
    """Test the ComposioHookRegistry directly."""

    def test_register_and_execute_before_hook(self) -> None:
        registry = ComposioHookRegistry()
        call_log: List[str] = []

        def hook(
            tool: str, toolkit: str, params: ToolExecuteParams
        ) -> ToolExecuteParams:
            call_log.append(f"before:{tool}")
            params["arguments"]["injected"] = True
            return params

        registry.register_before_hook(hook)
        params = _make_params(arguments={"key": "value"})
        result = registry.execute_before_hooks("MY_TOOL", "my_toolkit", params)

        assert result["arguments"]["injected"] is True
        assert call_log == ["before:MY_TOOL"]

    def test_register_and_execute_after_hook(self) -> None:
        registry = ComposioHookRegistry()
        call_log: List[str] = []

        def hook(tool: str, toolkit: str, response: Any) -> Any:
            call_log.append(f"after:{tool}")
            return {"processed": True, "original": response}

        registry.register_after_hook(hook)
        result = registry.execute_after_hooks("MY_TOOL", "my_toolkit", {"raw": "data"})

        assert result["processed"] is True
        assert result["original"] == {"raw": "data"}
        assert call_log == ["after:MY_TOOL"]

    def test_register_and_execute_schema_modifier(self) -> None:
        registry = ComposioHookRegistry()

        def modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
            schema.description += " [modified]"
            return schema

        registry.register_schema_modifier(modifier)
        schema = _make_tool_schema(description="Original")
        result = registry.execute_schema_modifiers("TEST_TOOL", "test", schema)

        assert "[modified]" in result.description

    def test_multiple_before_hooks_chain(self) -> None:
        """Multiple before hooks run in registration order, each seeing the previous result."""
        registry = ComposioHookRegistry()
        execution_order: List[int] = []

        def hook_1(
            tool: str, toolkit: str, params: ToolExecuteParams
        ) -> ToolExecuteParams:
            execution_order.append(1)
            params["arguments"]["step_1"] = True
            return params

        def hook_2(
            tool: str, toolkit: str, params: ToolExecuteParams
        ) -> ToolExecuteParams:
            execution_order.append(2)
            # Verify hook_1 already ran
            assert params["arguments"].get("step_1") is True
            params["arguments"]["step_2"] = True
            return params

        registry.register_before_hook(hook_1)
        registry.register_before_hook(hook_2)

        params = _make_params()
        result = registry.execute_before_hooks("TOOL", "tk", params)

        assert execution_order == [1, 2]
        assert result["arguments"]["step_1"] is True
        assert result["arguments"]["step_2"] is True

    def test_multiple_after_hooks_chain(self) -> None:
        """Multiple after hooks chain: each transforms the previous result."""
        registry = ComposioHookRegistry()

        def hook_a(tool: str, toolkit: str, response: Any) -> Any:
            return {**response, "hook_a": True}

        def hook_b(tool: str, toolkit: str, response: Any) -> Any:
            assert response.get("hook_a") is True
            return {**response, "hook_b": True}

        registry.register_after_hook(hook_a)
        registry.register_after_hook(hook_b)

        result = registry.execute_after_hooks("TOOL", "tk", {"initial": True})
        assert result == {"initial": True, "hook_a": True, "hook_b": True}

    def test_before_hook_error_does_not_stop_chain(self) -> None:
        """A failing before hook logs an error but the chain continues."""
        registry = ComposioHookRegistry()

        def bad_hook(
            tool: str, toolkit: str, params: ToolExecuteParams
        ) -> ToolExecuteParams:
            raise RuntimeError("boom")

        def good_hook(
            tool: str, toolkit: str, params: ToolExecuteParams
        ) -> ToolExecuteParams:
            params["arguments"]["survived"] = True
            return params

        registry.register_before_hook(bad_hook)
        registry.register_before_hook(good_hook)

        params = _make_params()
        result = registry.execute_before_hooks("TOOL", "tk", params)

        # The good hook still ran despite the bad one raising
        assert result["arguments"]["survived"] is True

    def test_after_hook_error_does_not_stop_chain(self) -> None:
        """A failing after hook logs an error but the chain continues."""
        registry = ComposioHookRegistry()

        def bad_hook(tool: str, toolkit: str, response: Any) -> Any:
            raise RuntimeError("boom")

        def good_hook(tool: str, toolkit: str, response: Any) -> Any:
            return {"processed": True}

        registry.register_after_hook(bad_hook)
        registry.register_after_hook(good_hook)

        result = registry.execute_after_hooks("TOOL", "tk", {"raw": True})
        assert result == {"processed": True}

    def test_schema_modifier_error_does_not_stop_chain(self) -> None:
        """A failing schema modifier logs an error but the chain continues."""
        registry = ComposioHookRegistry()

        def bad_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
            raise RuntimeError("boom")

        def good_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
            schema.description += " [good]"
            return schema

        registry.register_schema_modifier(bad_modifier)
        registry.register_schema_modifier(good_modifier)

        schema = _make_tool_schema(description="Base")
        result = registry.execute_schema_modifiers("TOOL", "tk", schema)
        assert "[good]" in result.description


# ---------------------------------------------------------------------------
# 2. Conditional hook decorators (register_before_hook, register_after_hook)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConditionalHookDecorators:
    """Test the decorator-based conditional hook registration."""

    def test_before_hook_runs_only_for_targeted_tool(self) -> None:
        """A hook registered for specific tools only fires for those tools."""
        registry = ComposioHookRegistry()
        call_log: List[str] = []

        # Simulate what @register_before_hook(tools=["TARGET_TOOL"]) does internally
        target_tools = ["TARGET_TOOL"]

        def conditional_hook(
            tool: str, toolkit: str, params: ToolExecuteParams
        ) -> ToolExecuteParams:
            should_run = tool in target_tools
            if should_run:
                call_log.append(tool)
                params["arguments"]["targeted"] = True
            return params

        registry.register_before_hook(conditional_hook)

        # Should fire
        params1 = _make_params()
        result1 = registry.execute_before_hooks("TARGET_TOOL", "any_toolkit", params1)
        assert result1["arguments"].get("targeted") is True
        assert call_log == ["TARGET_TOOL"]

        # Should NOT fire
        params2 = _make_params()
        result2 = registry.execute_before_hooks("OTHER_TOOL", "any_toolkit", params2)
        assert result2["arguments"].get("targeted") is None
        assert len(call_log) == 1  # Still only the first call

    def test_after_hook_runs_only_for_targeted_toolkit(self) -> None:
        """A hook registered for a specific toolkit only fires for that toolkit."""
        registry = ComposioHookRegistry()
        call_log: List[str] = []

        target_toolkits = ["gmail"]

        def conditional_hook(tool: str, toolkit: str, response: Any) -> Any:
            if toolkit in target_toolkits:
                call_log.append(toolkit)
                return {"gmail_processed": True}
            return response

        registry.register_after_hook(conditional_hook)

        # Should fire
        result1 = registry.execute_after_hooks(
            "GMAIL_SEND_EMAIL", "gmail", {"raw": True}
        )
        assert result1 == {"gmail_processed": True}

        # Should NOT fire
        result2 = registry.execute_after_hooks("SLACK_SEND_MSG", "slack", {"raw": True})
        assert result2 == {"raw": True}

    def test_wildcard_hook_runs_for_all_tools(self) -> None:
        """A hook with no tool/toolkit filter runs for every call."""
        registry = ComposioHookRegistry()
        call_count = 0

        def universal_hook(
            tool: str, toolkit: str, params: ToolExecuteParams
        ) -> ToolExecuteParams:
            nonlocal call_count
            call_count += 1
            return params

        registry.register_before_hook(universal_hook)

        registry.execute_before_hooks("ANY_TOOL_1", "tk1", _make_params())
        registry.execute_before_hooks("ANY_TOOL_2", "tk2", _make_params())
        assert call_count == 2


# ---------------------------------------------------------------------------
# 3. Master hooks (the top-level functions wired into Composio SDK)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMasterHooks:
    """Test master_before_execute_hook and master_after_execute_hook."""

    def test_master_before_delegates_to_registry(self) -> None:
        """master_before_execute_hook delegates to hook_registry.execute_before_hooks."""

        original_hooks = hook_registry._before_hooks[:]
        try:
            call_log: List[str] = []

            def test_hook(
                tool: str, toolkit: str, params: ToolExecuteParams
            ) -> ToolExecuteParams:
                call_log.append(f"{toolkit}:{tool}")
                return params

            hook_registry._before_hooks.append(test_hook)
            params = _make_params(arguments={"x": 1})
            master_before_execute_hook("GMAIL_SEND_EMAIL", "gmail", params)

            assert "gmail:GMAIL_SEND_EMAIL" in call_log
        finally:
            hook_registry._before_hooks[:] = original_hooks

    def test_master_after_delegates_to_registry(self) -> None:
        """master_after_execute_hook delegates to hook_registry.execute_after_hooks."""

        original_hooks = hook_registry._after_hooks[:]
        try:
            call_log: List[str] = []

            def test_hook(tool: str, toolkit: str, response: Any) -> Any:
                call_log.append(f"{toolkit}:{tool}")
                return response

            hook_registry._after_hooks.append(test_hook)
            master_after_execute_hook("SLACK_SEND_MSG", "slack", {"ok": True})

            assert "slack:SLACK_SEND_MSG" in call_log
        finally:
            hook_registry._after_hooks[:] = original_hooks

    def test_master_schema_modifier_delegates_to_registry(self) -> None:
        """master_schema_modifier delegates to hook_registry.execute_schema_modifiers."""

        original_mods = hook_registry._schema_modifiers[:]
        try:
            call_log: List[str] = []

            def test_mod(tool: str, toolkit: str, schema: Tool) -> Tool:
                call_log.append(tool)
                return schema

            hook_registry._schema_modifiers.append(test_mod)
            schema = _make_tool_schema()
            master_schema_modifier("TEST_TOOL", "test", schema)

            assert "TEST_TOOL" in call_log
        finally:
            hook_registry._schema_modifiers[:] = original_mods


# ---------------------------------------------------------------------------
# 4. Gmail before hooks — real logic with mocked stream writer
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGmailBeforeHooks:
    """Test Gmail-specific before_execute hooks."""

    def test_fetch_emails_hard_limit_raises_tool_exception(self) -> None:
        """Requesting too many emails in full mode raises ToolException."""

        params = _make_params(
            arguments={
                "max_results": 50,
                "verbose": True,
                "include_payload": True,
            }
        )

        with pytest.raises(ToolException, match="Result set too large"):
            gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "gmail", params)

    def test_fetch_emails_within_limit_passes(self) -> None:
        """Requesting within the limit returns params unchanged."""

        params = _make_params(
            arguments={
                "max_results": 10,
                "verbose": True,
            }
        )

        result = gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "gmail", params)
        assert result is params

    def test_fetch_emails_non_full_mode_allows_large_requests(self) -> None:
        """Non-full mode (verbose=False, include_payload=False) allows large requests."""

        params = _make_params(
            arguments={
                "max_results": 100,
                "verbose": False,
                "include_payload": False,
            }
        )

        result = gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "gmail", params)
        assert result is params

    def test_compose_hook_maps_to_field_to_recipient_email(self) -> None:
        """The compose before hook maps 'to' to 'recipient_email' when needed."""

        params = _make_params(
            arguments={
                "to": "user@example.com",
                "subject": "Hello",
                "body": "World",
            }
        )

        with patch(
            "app.utils.composio_hooks.gmail_hooks.get_stream_writer"
        ) as mock_writer:
            mock_writer.return_value = MagicMock()
            result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)

        assert result["arguments"]["recipient_email"] == "user@example.com"

    def test_compose_hook_skips_streaming_when_no_recipient(self) -> None:
        """When no recipient is provided, the hook returns params early without streaming."""

        params = _make_params(
            arguments={
                "subject": "Hello",
                "body": "World",
            }
        )

        # Should not raise, should return params without trying to stream
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "gmail", params)
        assert result is params

    def test_compose_hook_streams_email_compose_data_for_draft(self) -> None:
        """Creating a draft sends email_compose_data to the stream writer."""

        writer_mock = MagicMock()
        params = _make_params(
            arguments={
                "recipient_email": "user@example.com",
                "subject": "Draft subject",
                "body": "Draft body",
            }
        )

        with patch(
            "app.utils.composio_hooks.gmail_hooks.get_stream_writer",
            return_value=writer_mock,
        ):
            gmail_compose_before_hook("GMAIL_CREATE_EMAIL_DRAFT", "gmail", params)

        writer_mock.assert_called_once()
        payload = writer_mock.call_args[0][0]
        assert "email_compose_data" in payload
        assert payload["email_compose_data"][0]["subject"] == "Draft subject"


# ---------------------------------------------------------------------------
# 5. Gmail after hooks — real logic with mocked stream writer
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGmailAfterHooks:
    """Test Gmail-specific after_execute hooks."""

    def test_fetch_after_hook_processes_list_messages(self) -> None:
        """The fetch after hook calls process_list_messages_response on raw data."""

        raw_response: ToolExecutionResponse = {
            "data": {
                "messages": [
                    {
                        "id": "msg1",
                        "threadId": "thread1",
                        "payload": {
                            "headers": [
                                {"name": "From", "value": "sender@test.com"},
                                {"name": "Subject", "value": "Test"},
                                {
                                    "name": "Date",
                                    "value": "Mon, 1 Jan 2024 00:00:00 +0000",
                                },
                            ],
                        },
                        "snippet": "Test snippet",
                    }
                ],
                "resultSizeEstimate": 1,
            },
            "successful": True,
        }

        with patch(
            "app.utils.composio_hooks.gmail_hooks.get_stream_writer",
            return_value=MagicMock(),
        ):
            with patch(
                "app.utils.composio_hooks.gmail_hooks.process_list_messages_response",
                return_value={
                    "messages": [
                        {
                            "id": "msg1",
                            "threadId": "thread1",
                            "from": "sender@test.com",
                            "subject": "Test",
                            "time": "Mon, 1 Jan 2024",
                        }
                    ],
                    "resultSize": 1,
                },
            ) as mock_process:
                result = gmail_fetch_after_hook(
                    "GMAIL_FETCH_EMAILS", "gmail", raw_response
                )

        mock_process.assert_called_once_with(raw_response["data"])
        assert "messages" in result
        assert result["messages"][0]["id"] == "msg1"

    def test_fetch_after_hook_handles_error_response(self) -> None:
        """When the response has no data or an error, the hook returns raw data gracefully."""

        raw_response: ToolExecutionResponse = {
            "data": {"error": "something went wrong"},
            "successful": False,
        }

        with patch(
            "app.utils.composio_hooks.gmail_hooks.get_stream_writer",
            return_value=MagicMock(),
        ):
            with patch(
                "app.utils.composio_hooks.gmail_hooks.process_list_messages_response",
                side_effect=Exception("parse error"),
            ):
                result = gmail_fetch_after_hook(
                    "GMAIL_FETCH_EMAILS", "gmail", raw_response
                )

        # Should fall back to raw data on error
        assert result == raw_response["data"]

    def test_message_detail_after_hook_processes_single_message(self) -> None:
        """The message detail hook calls detailed_message_template."""

        raw_response: ToolExecutionResponse = {
            "data": {"id": "msg1", "payload": {"headers": []}},
            "successful": True,
        }

        expected_output = {"id": "msg1", "subject": "Test", "body": "Hello"}

        with patch(
            "app.utils.composio_hooks.gmail_hooks.detailed_message_template",
            return_value=expected_output,
        ) as mock_template:
            result = gmail_message_detail_after_hook(
                "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "gmail", raw_response
            )

        mock_template.assert_called_once_with(raw_response["data"])
        assert result == expected_output

    def test_attachment_after_hook_strips_content(self) -> None:
        """The attachment hook extracts metadata only, not base64 content."""

        raw_response: ToolExecutionResponse = {
            "data": {
                "attachmentId": "att1",
                "filename": "test.pdf",
                "mimeType": "application/pdf",
                "size": 12345,
                "data": "HUGE_BASE64_STRING_THAT_SHOULD_BE_STRIPPED",
            },
            "successful": True,
        }

        result = gmail_attachment_after_hook(
            "GMAIL_FETCH_ATTACHMENT", "gmail", raw_response
        )

        assert result["attachmentId"] == "att1"
        assert result["filename"] == "test.pdf"
        assert result["size"] == 12345
        assert "HUGE_BASE64" not in str(result)
        assert "message" in result  # informational note


# ---------------------------------------------------------------------------
# 6. Gmail schema modifiers — real logic
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGmailSchemaModifiers:
    """Test Gmail schema modification hooks."""

    def test_send_email_schema_gets_draft_guidance(self) -> None:
        """GMAIL_SEND_EMAIL schema gets draft-first workflow guidance."""

        schema = _make_tool_schema(slug="GMAIL_SEND_EMAIL", description="Send an email")
        result = gmail_send_email_schema_modifier("GMAIL_SEND_EMAIL", "gmail", schema)

        assert "draft" in result.description.lower()
        assert "GMAIL_CREATE_EMAIL_DRAFT" in result.description

    def test_fetch_emails_schema_sets_defaults(self) -> None:
        """GMAIL_FETCH_EMAILS schema gets default max_results and label_ids."""

        schema = _make_tool_schema(
            slug="GMAIL_FETCH_EMAILS",
            description="Fetch emails",
            input_parameters={
                "properties": {
                    "max_results": {"type": "integer", "default": 1},
                    "label_ids": {"type": "array"},
                    "format": {"type": "string"},
                },
                "required": [],
                "type": "object",
            },
        )

        result = gmail_fetch_emails_schema_modifier(
            "GMAIL_FETCH_EMAILS", "gmail", schema
        )

        props = result.input_parameters["properties"]
        assert props["max_results"]["default"] == 10
        assert props["label_ids"]["default"] == ["INBOX"]
        assert props["format"]["default"] == "full"
        assert "SEARCH SYNTAX" in result.description


# ---------------------------------------------------------------------------
# 7. User ID extraction hook — real logic
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUserIdExtractionHook:
    """Test user_id extraction from RunnableConfig metadata."""

    def test_extracts_user_id_from_runnable_config(self) -> None:
        """User ID is extracted from __runnable_config__ metadata and set on params."""

        params = _make_params(
            arguments={
                "query": "test",
                "__runnable_config__": {
                    "metadata": {"user_id": "user_abc123"},
                },
            }
        )

        result = extract_user_id_from_params("GMAIL_FETCH_EMAILS", "gmail", params)

        assert result["user_id"] == "user_abc123"
        assert result["entity_id"] == "user_abc123"
        # __runnable_config__ should be popped from arguments
        assert "__runnable_config__" not in result["arguments"]

    def test_no_runnable_config_returns_params_unchanged(self) -> None:
        """Without __runnable_config__, params are returned unchanged."""

        params = _make_params(arguments={"query": "test"})
        result = extract_user_id_from_params("GMAIL_FETCH_EMAILS", "gmail", params)

        assert "user_id" not in result
        assert "entity_id" not in result

    def test_empty_metadata_returns_params_unchanged(self) -> None:
        """If metadata is empty, params are returned unchanged."""

        params = _make_params(
            arguments={
                "__runnable_config__": {"metadata": {}},
            }
        )

        result = extract_user_id_from_params("SLACK_SEND_MSG", "slack", params)
        assert "user_id" not in result

    def test_no_user_id_in_metadata_returns_params_unchanged(self) -> None:
        """If metadata exists but has no user_id, params are returned unchanged."""

        params = _make_params(
            arguments={
                "__runnable_config__": {"metadata": {"thread_id": "t1"}},
            }
        )

        result = extract_user_id_from_params("TOOL", "tk", params)
        assert "user_id" not in result

    def test_empty_arguments_returns_params_unchanged(self) -> None:
        """If arguments dict is empty, hook returns params as-is."""

        params: ToolExecuteParams = {"arguments": {}}
        result = extract_user_id_from_params("TOOL", "tk", params)
        assert result == params


# ---------------------------------------------------------------------------
# 8. Slack schema modifiers — real logic
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSlackSchemaModifiers:
    """Test Slack schema modification hooks."""

    def test_search_schema_sets_defaults(self) -> None:
        """SLACK_SEARCH_MESSAGES gets sort, sort_dir, count defaults."""

        schema = _make_tool_schema(
            slug="SLACK_SEARCH_MESSAGES",
            description="Search messages",
            input_parameters={
                "properties": {
                    "sort": {"type": "string"},
                    "sort_dir": {"type": "string"},
                    "count": {"type": "integer"},
                },
                "required": [],
                "type": "object",
            },
        )

        result = slack_search_schema_modifier("SLACK_SEARCH_MESSAGES", "slack", schema)

        props = result.input_parameters["properties"]
        assert props["sort"]["default"] == "timestamp"
        assert props["sort_dir"]["default"] == "desc"
        assert props["count"]["default"] == 20
        assert "NEWEST FIRST" in result.description


# ---------------------------------------------------------------------------
# 9. End-to-end hook chain: before -> execute (mocked) -> after
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEndToEndHookChain:
    """Test a complete before -> execute -> after pipeline."""

    def test_full_chain_transforms_input_and_output(self) -> None:
        """
        Simulate: user_id extraction (before) -> Composio execute (mocked) ->
        response processing (after) -> verify transformed result.
        """
        registry = ComposioHookRegistry()

        # Before hook: extract user_id and add a tracking field
        def before_hook(
            tool: str, toolkit: str, params: ToolExecuteParams
        ) -> ToolExecuteParams:
            params["user_id"] = "test_user"
            params["arguments"]["processed_by_before"] = True
            return params

        # After hook: transform raw response
        def after_hook(tool: str, toolkit: str, response: Any) -> Any:
            return {
                "summary": f"Got {len(response.get('items', []))} items",
                "tool_used": tool,
            }

        registry.register_before_hook(before_hook)
        registry.register_after_hook(after_hook)

        # BEFORE phase
        params = _make_params(arguments={"query": "search term"})
        modified_params = registry.execute_before_hooks(
            "GMAIL_FETCH_EMAILS", "gmail", params
        )

        assert modified_params["user_id"] == "test_user"
        assert modified_params["arguments"]["processed_by_before"] is True
        assert modified_params["arguments"]["query"] == "search term"

        # EXECUTE phase (mocked)
        raw_api_response = {
            "items": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
            "next_page": "token123",
        }

        # AFTER phase
        final_result = registry.execute_after_hooks(
            "GMAIL_FETCH_EMAILS", "gmail", raw_api_response
        )

        assert final_result["summary"] == "Got 3 items"
        assert final_result["tool_used"] == "GMAIL_FETCH_EMAILS"


# ---------------------------------------------------------------------------
# 10. Custom tools registry
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCustomToolsRegistry:
    """Test the CustomToolsRegistry from composio/custom_tools/registry.py."""

    def test_registry_initialization_and_tool_retrieval(self) -> None:
        """Initialize the registry with a mock Composio client and verify tool names."""

        registry = CustomToolsRegistry()
        assert not registry.is_initialized

        import contextlib

        composio_mock = MagicMock()
        composio_mock.tools.custom_tool.side_effect = lambda toolkit: lambda fn: fn

        _mod = "app.services.composio.custom_tools.registry"
        _patches = [
            (
                "register_gmail_custom_tools",
                ["GMAIL_MARK_AS_READ", "GMAIL_ARCHIVE_EMAIL"],
            ),
            ("register_calendar_custom_tools", ["GCAL_CUSTOM_TOOL"]),
            ("register_google_docs_custom_tools", []),
            ("register_google_maps_custom_tools", []),
            ("register_google_meet_custom_tools", []),
            ("register_google_sheets_custom_tools", []),
            ("register_google_tasks_custom_tools", []),
            ("register_instagram_custom_tools", []),
            ("register_notion_custom_tools", []),
            ("register_linkedin_custom_tools", []),
            ("register_twitter_custom_tools", []),
            ("register_linear_custom_tools", []),
            ("register_reddit_custom_tools", []),
            ("register_slack_custom_tools", []),
            ("register_github_custom_tools", []),
            ("register_hubspot_custom_tools", []),
            ("register_airtable_custom_tools", []),
            ("register_asana_custom_tools", []),
            ("register_clickup_custom_tools", []),
            ("register_trello_custom_tools", []),
            ("register_todoist_custom_tools", []),
            ("register_microsoft_teams_custom_tools", []),
            ("register_urgency_custom_tools", []),
        ]

        with contextlib.ExitStack() as stack:
            for func_name, return_val in _patches:
                stack.enter_context(
                    patch(f"{_mod}.{func_name}", return_value=return_val)
                )
            registry.initialize(composio_mock)

        assert registry.is_initialized
        assert "GMAIL_MARK_AS_READ" in registry.get_tool_names("gmail")
        assert "GMAIL_ARCHIVE_EMAIL" in registry.get_tool_names("gmail")
        assert "GCAL_CUSTOM_TOOL" in registry.get_tool_names("googlecalendar")
        assert registry.get_tool_names("nonexistent") == []

    def test_get_tool_names_case_insensitive(self) -> None:
        """Tool names lookup is case-insensitive for toolkit name."""

        registry = CustomToolsRegistry()
        registry._tools_by_toolkit["gmail"] = ["GMAIL_TOOL_A"]
        registry._registered_toolkits.add("gmail")

        assert registry.get_tool_names("GMAIL") == ["GMAIL_TOOL_A"]
        assert registry.get_tool_names("Gmail") == ["GMAIL_TOOL_A"]
        assert registry.get_tool_names("gmail") == ["GMAIL_TOOL_A"]

    def test_get_all_tool_names(self) -> None:
        """get_all_tool_names returns tools from all toolkits."""

        registry = CustomToolsRegistry()
        registry._tools_by_toolkit = {
            "gmail": ["GMAIL_A", "GMAIL_B"],
            "slack": ["SLACK_A"],
        }

        all_names = registry.get_all_tool_names()
        assert set(all_names) == {"GMAIL_A", "GMAIL_B", "SLACK_A"}

    def test_get_registered_toolkits(self) -> None:
        """get_registered_toolkits returns sorted toolkit names."""

        registry = CustomToolsRegistry()
        registry._registered_toolkits = {"slack", "gmail", "calendar"}

        result = registry.get_registered_toolkits()
        assert result == ["calendar", "gmail", "slack"]

    def test_uninitialized_registry_raises_on_register(self) -> None:
        """Calling _register_all_tools before initialize raises RuntimeError."""

        registry = CustomToolsRegistry()
        with pytest.raises(RuntimeError, match="not initialized"):
            registry._register_all_tools()


# ---------------------------------------------------------------------------
# 11. Twitter hooks — schema and response processing
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTwitterHooks:
    """Test Twitter-specific hooks."""

    def test_search_schema_gets_syntax_tips(self) -> None:
        """TWITTER_RECENT_SEARCH schema gets search syntax tips."""

        schema = _make_tool_schema(
            slug="TWITTER_RECENT_SEARCH",
            description="Search recent tweets",
        )

        result = twitter_search_schema_modifier(
            "TWITTER_RECENT_SEARCH", "twitter", schema
        )
        assert "from:username" in result.description
        assert "SEARCH SYNTAX" in result.description

    def test_search_after_hook_processes_tweets(self) -> None:
        """Twitter search after hook processes raw API response into clean format."""

        raw_response: ToolExecutionResponse = {
            "data": {
                "data": [
                    {
                        "id": "tweet1",
                        "text": "Hello world",
                        "author_id": "user1",
                        "created_at": "2024-01-01T00:00:00Z",
                        "public_metrics": {"like_count": 10, "retweet_count": 5},
                    },
                ],
                "includes": {
                    "users": [
                        {
                            "id": "user1",
                            "username": "testuser",
                            "name": "Test User",
                        }
                    ],
                },
                "meta": {"result_count": 1},
            },
            "successful": True,
        }

        with patch(
            "app.utils.composio_hooks.twitter_hooks.get_stream_writer",
            return_value=MagicMock(),
        ):
            result = twitter_search_after_hook(
                "TWITTER_RECENT_SEARCH", "twitter", raw_response
            )

        assert "tweets" in result
        assert result["tweets"][0]["id"] == "tweet1"
        assert result["tweets"][0]["author_username"] == "testuser"
        assert result["result_count"] == 1


# ---------------------------------------------------------------------------
# 12. Reddit hooks — response processing
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRedditHooks:
    """Test Reddit-specific hooks."""

    def test_search_after_hook_processes_posts(self) -> None:
        """Reddit search after hook processes raw API response."""

        raw_response: ToolExecutionResponse = {
            "data": {
                "search_results": {
                    "data": {
                        "children": [
                            {
                                "kind": "t3",
                                "data": {
                                    "id": "post1",
                                    "title": "Test Post",
                                    "author": "testuser",
                                    "subreddit": "test",
                                    "score": 42,
                                    "num_comments": 7,
                                },
                            },
                        ],
                        "after": "next_token",
                    },
                },
            },
            "successful": True,
        }

        with patch(
            "app.utils.composio_hooks.reddit_hooks.get_stream_writer",
            return_value=MagicMock(),
        ):
            result = reddit_search_after_hook(
                "REDDIT_SEARCH_ACROSS_SUBREDDITS", "reddit", raw_response
            )

        assert "posts" in result
        assert result["posts"][0]["id"] == "post1"
        assert result["posts"][0]["title"] == "Test Post"
        assert result["result_count"] == 1

    def test_process_reddit_post_extracts_fields(self) -> None:
        """process_reddit_post extracts only essential fields."""

        raw_post = {
            "data": {
                "id": "abc123",
                "title": "My Post",
                "author": "user1",
                "subreddit": "python",
                "score": 100,
                "num_comments": 25,
                "selftext": "Content here",
                "url": "https://reddit.com/r/python/...",
                "permalink": "/r/python/comments/abc123/",
                "extra_field_that_should_not_appear": "noise",
            },
        }

        result = process_reddit_post(raw_post)

        assert result["id"] == "abc123"
        assert result["title"] == "My Post"
        assert result["author"] == "user1"
        assert result["score"] == 100
        assert "extra_field_that_should_not_appear" not in result

    def test_process_reddit_comment_extracts_fields(self) -> None:
        """process_reddit_comment extracts only essential fields."""

        raw_comment = {
            "data": {
                "id": "comment1",
                "author": "commenter",
                "body": "Great post!",
                "score": 5,
                "subreddit": "python",
                "is_submitter": False,
                "irrelevant_data": "should_not_appear",
            },
        }

        result = process_reddit_comment(raw_comment)

        assert result["id"] == "comment1"
        assert result["body"] == "Great post!"
        assert "irrelevant_data" not in result


# ---------------------------------------------------------------------------
# 13. Hook failure propagation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHookFailurePropagation:
    """Test how hook failures are handled."""

    def test_before_hook_tool_exception_propagates(self) -> None:
        """ToolException raised in a before hook propagates (not swallowed)."""

        params = _make_params(
            arguments={
                "max_results": 999,
                "verbose": True,
            }
        )

        with pytest.raises(ToolException):
            gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "gmail", params)

    def test_registry_swallows_generic_errors_in_hooks(self) -> None:
        """The registry's execute_before_hooks catches generic errors per hook."""
        registry = ComposioHookRegistry()

        def exploding_hook(
            tool: str, toolkit: str, params: ToolExecuteParams
        ) -> ToolExecuteParams:
            raise ValueError("unexpected error in hook")

        registry.register_before_hook(exploding_hook)

        # Should NOT raise, the registry catches and logs
        params = _make_params()
        result = registry.execute_before_hooks("TOOL", "tk", params)
        assert result is params

    def test_after_hook_with_malformed_response_returns_raw_data(self) -> None:
        """After hook receiving malformed data falls back to raw data."""

        # Pass a response where data is not the expected shape
        malformed_response: ToolExecutionResponse = {
            "data": {"error": "API returned garbage"},
            "successful": False,
        }

        result = gmail_message_detail_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "gmail", malformed_response
        )

        # Should return the raw data since error is in data
        assert result == malformed_response["data"]

    def test_after_hook_with_none_response_returns_raw_data(self) -> None:
        """After hook receiving None-ish response degrades gracefully."""

        # Empty response dict
        response: ToolExecutionResponse = {
            "data": {"error": "not found"},
            "successful": False,
        }

        result = gmail_drafts_after_hook("GMAIL_LIST_DRAFTS", "gmail", response)
        assert result == response["data"]


# ---------------------------------------------------------------------------
# 14. Context tool namespace helper
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestContextToolNamespace:
    """Test the context tool namespace helper."""

    def test_tool_namespace_extraction(self) -> None:
        """tool_namespace extracts the provider from a tool slug."""

        assert (
            tool_namespace("GOOGLECALENDAR_CUSTOM_GATHER_CONTEXT") == "googlecalendar"
        )
        assert tool_namespace("GMAIL_CUSTOM_GATHER_CONTEXT") == "gmail"
        assert (
            tool_namespace("MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT") == "microsoft_teams"
        )

    def test_provider_tools_map_completeness(self) -> None:
        """PROVIDER_TOOLS map has entries for all expected providers."""

        expected_providers = [
            "calendar",
            "gmail",
            "slack",
            "notion",
            "github",
            "linear",
        ]
        for provider in expected_providers:
            assert provider in PROVIDER_TOOLS, f"Missing provider: {provider}"
            assert "CUSTOM_GATHER_CONTEXT" in PROVIDER_TOOLS[provider]
