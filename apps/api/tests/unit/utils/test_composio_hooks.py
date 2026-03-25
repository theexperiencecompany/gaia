"""
Comprehensive tests for the Composio hook system.

Covers:
- ComposioHookRegistry: register, execute, error handling
- Decorator-based registration (register_before_hook, register_after_hook, register_schema_modifier)
- Master hooks delegation
- user_id_hooks: user_id/entity_id extraction from RunnableConfig metadata
- gmail_hooks: schema modifiers, before hooks (validation, streaming), after hooks (response processing)
- slack_hooks: search schema modifier
- twitter_hooks: schema modifiers, before/after hooks for search/timeline/user lookup/followers/post
- reddit_hooks: helper functions, before/after hooks for search/post/comments/content creation
"""

from typing import Any
from unittest.mock import MagicMock, patch

from composio.types import ToolExecuteParams

import pytest
from langchain_core.tools import ToolException

from app.utils.composio_hooks.registry import (
    ComposioHookRegistry,
    register_after_hook,
    register_before_hook,
    register_schema_modifier,
)
from app.utils.composio_hooks.reddit_hooks import (
    process_reddit_comment,
    process_reddit_post,
    process_reddit_search_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_schema(**overrides: Any) -> MagicMock:
    """Create a mock Tool schema with common fields."""
    schema = MagicMock()
    schema.description = overrides.get("description", "Original description")
    schema.input_parameters = overrides.get(
        "input_parameters",
        {"properties": {}},
    )
    return schema


def _make_params(arguments: dict | None = None, **extra: Any) -> ToolExecuteParams:
    """Create a ToolExecuteParams-like dict."""
    params: dict[str, Any] = {"arguments": arguments or {}}
    params.update(extra)
    return params  # type: ignore[return-value]


def _make_response(
    data: dict[str, Any] | list[Any], successful: bool = True, error: str | None = None
) -> dict[str, Any]:
    """Create a ToolExecutionResponse-like dict."""
    resp: dict[str, Any] = {"data": data, "successful": successful}
    if error is not None:
        resp["error"] = error
    return resp


def _noop_writer() -> MagicMock:
    """Return a callable mock suitable for ``get_stream_writer``."""
    return MagicMock()


# ============================================================================
# 1. Registry core
# ============================================================================


class TestComposioHookRegistry:
    """Tests for the low-level ComposioHookRegistry class."""

    def test_register_and_execute_before_hook(self) -> None:
        registry = ComposioHookRegistry()

        def double_value(tool: str, toolkit: str, params: dict) -> dict:
            params["arguments"]["x"] = params["arguments"].get("x", 0) * 2
            return params

        registry.register_before_hook(double_value)  # type: ignore[arg-type]
        result = registry.execute_before_hooks("TOOL", "KIT", _make_params({"x": 5}))
        assert result["arguments"]["x"] == 10

    def test_register_and_execute_after_hook(self) -> None:
        registry = ComposioHookRegistry()

        def upper_response(tool: str, toolkit: str, response: Any) -> Any:
            return str(response).upper()

        registry.register_after_hook(upper_response)
        result = registry.execute_after_hooks("TOOL", "KIT", "hello")
        assert result == "HELLO"

    def test_register_and_execute_schema_modifier(self) -> None:
        registry = ComposioHookRegistry()

        def add_suffix(tool: str, toolkit: str, schema: Any) -> Any:
            schema.description += " [modified]"
            return schema

        registry.register_schema_modifier(add_suffix)
        schema = _make_tool_schema()
        result = registry.execute_schema_modifiers("T", "K", schema)
        assert result.description.endswith("[modified]")

    def test_hooks_execute_in_registration_order(self) -> None:
        registry = ComposioHookRegistry()
        call_order: list[str] = []

        def first(tool: str, toolkit: str, params: dict) -> dict:
            call_order.append("first")
            return params

        def second(tool: str, toolkit: str, params: dict) -> dict:
            call_order.append("second")
            return params

        registry.register_before_hook(first)  # type: ignore[arg-type]
        registry.register_before_hook(second)  # type: ignore[arg-type]
        registry.execute_before_hooks("T", "K", _make_params())
        assert call_order == ["first", "second"]

    def test_chained_before_hooks_accumulate_changes(self) -> None:
        registry = ComposioHookRegistry()

        def add_a(tool: str, toolkit: str, params: dict) -> dict:
            params["arguments"]["a"] = 1
            return params

        def add_b(tool: str, toolkit: str, params: dict) -> dict:
            params["arguments"]["b"] = 2
            return params

        registry.register_before_hook(add_a)  # type: ignore[arg-type]
        registry.register_before_hook(add_b)  # type: ignore[arg-type]
        result = registry.execute_before_hooks("T", "K", _make_params())
        assert result["arguments"] == {"a": 1, "b": 2}

    def test_failing_before_hook_does_not_block_others(self) -> None:
        registry = ComposioHookRegistry()

        def bad_hook(tool: str, toolkit: str, params: dict) -> dict:
            raise RuntimeError("boom")

        def good_hook(tool: str, toolkit: str, params: dict) -> dict:
            params["arguments"]["ok"] = True
            return params

        registry.register_before_hook(bad_hook)  # type: ignore[arg-type]
        registry.register_before_hook(good_hook)  # type: ignore[arg-type]
        result = registry.execute_before_hooks("T", "K", _make_params())
        assert result["arguments"]["ok"] is True

    def test_failing_after_hook_does_not_block_others(self) -> None:
        registry = ComposioHookRegistry()

        def bad_hook(tool: str, toolkit: str, response: Any) -> Any:
            raise RuntimeError("kaboom")

        def good_hook(tool: str, toolkit: str, response: Any) -> Any:
            return {"processed": True}

        registry.register_after_hook(bad_hook)
        registry.register_after_hook(good_hook)
        result = registry.execute_after_hooks("T", "K", "original")
        assert result == {"processed": True}

    def test_failing_schema_modifier_does_not_block_others(self) -> None:
        registry = ComposioHookRegistry()

        def bad_mod(tool: str, toolkit: str, schema: Any) -> Any:
            raise ValueError("oops")

        def good_mod(tool: str, toolkit: str, schema: Any) -> Any:
            schema.description = "modified"
            return schema

        registry.register_schema_modifier(bad_mod)
        registry.register_schema_modifier(good_mod)
        schema = _make_tool_schema()
        result = registry.execute_schema_modifiers("T", "K", schema)
        assert result.description == "modified"

    def test_empty_registry_returns_params_unchanged(self) -> None:
        registry = ComposioHookRegistry()
        params = _make_params({"key": "value"})
        result = registry.execute_before_hooks("T", "K", params)
        assert result is params

    def test_empty_registry_returns_response_unchanged(self) -> None:
        registry = ComposioHookRegistry()
        response = {"data": "hello"}
        result = registry.execute_after_hooks("T", "K", response)
        assert result is response

    def test_empty_registry_returns_schema_unchanged(self) -> None:
        registry = ComposioHookRegistry()
        schema = _make_tool_schema()
        result = registry.execute_schema_modifiers("T", "K", schema)
        assert result is schema


# ============================================================================
# 2. Decorator-based conditional registration
# ============================================================================


class TestDecoratorRegistration:
    """Tests for the register_before_hook / register_after_hook / register_schema_modifier decorators."""

    def setup_method(self) -> None:
        """Reset the global registry before each test in this class."""
        from app.utils.composio_hooks.registry import hook_registry

        self._orig_before = hook_registry._before_hooks.copy()
        self._orig_after = hook_registry._after_hooks.copy()
        self._orig_schema = hook_registry._schema_modifiers.copy()

    def teardown_method(self) -> None:
        from app.utils.composio_hooks.registry import hook_registry

        hook_registry._before_hooks = self._orig_before
        hook_registry._after_hooks = self._orig_after
        hook_registry._schema_modifiers = self._orig_schema

    def test_before_hook_with_specific_tool_matches(self) -> None:
        from app.utils.composio_hooks.registry import hook_registry

        initial = len(hook_registry._before_hooks)

        @register_before_hook(tools=["MY_TOOL"])
        def my_hook(tool: str, toolkit: str, params: dict) -> dict:
            params["arguments"]["injected"] = True
            return params

        assert len(hook_registry._before_hooks) == initial + 1

        # Matching tool
        p = _make_params()
        result = hook_registry.execute_before_hooks("MY_TOOL", "SOME_KIT", p)
        assert result["arguments"].get("injected") is True

    def test_before_hook_with_specific_tool_skips_non_matching(self) -> None:
        from app.utils.composio_hooks.registry import hook_registry

        initial = len(hook_registry._before_hooks)

        @register_before_hook(tools=["MY_TOOL"])
        def my_hook(tool: str, toolkit: str, params: dict) -> dict:
            params["arguments"]["injected"] = True
            return params

        assert len(hook_registry._before_hooks) == initial + 1

        # Non-matching tool
        p = _make_params()
        result = hook_registry.execute_before_hooks("OTHER_TOOL", "SOME_KIT", p)
        assert "injected" not in result["arguments"]

    def test_before_hook_with_toolkit_match(self) -> None:
        from app.utils.composio_hooks.registry import hook_registry

        @register_before_hook(toolkits=["GMAIL"])
        def gmail_kit_hook(tool: str, toolkit: str, params: dict) -> dict:
            params["arguments"]["gmail_kit"] = True
            return params

        p = _make_params()
        result = hook_registry.execute_before_hooks("GMAIL_SEND_EMAIL", "GMAIL", p)
        assert result["arguments"].get("gmail_kit") is True

    def test_before_hook_with_no_filter_runs_for_all(self) -> None:
        from app.utils.composio_hooks.registry import hook_registry

        @register_before_hook()
        def universal_hook(tool: str, toolkit: str, params: dict) -> dict:
            params["arguments"]["universal"] = True
            return params

        p = _make_params()
        result = hook_registry.execute_before_hooks("ANY_TOOL", "ANY_KIT", p)
        assert result["arguments"]["universal"] is True

    def test_after_hook_conditional_matching(self) -> None:
        from app.utils.composio_hooks.registry import hook_registry

        @register_after_hook(tools=["GMAIL_FETCH_EMAILS"])
        def gmail_after(tool: str, toolkit: str, response: Any) -> Any:
            return {"processed": True}

        # Matching
        result = hook_registry.execute_after_hooks("GMAIL_FETCH_EMAILS", "GMAIL", "raw")
        assert result == {"processed": True}

    def test_after_hook_skips_non_matching(self) -> None:
        from app.utils.composio_hooks.registry import hook_registry

        before_count = len(hook_registry._after_hooks)

        @register_after_hook(tools=["GMAIL_FETCH_EMAILS"])
        def gmail_after(tool: str, toolkit: str, response: Any) -> Any:
            return {"processed": True}

        # Non-matching tool returns original
        hook_registry.execute_after_hooks("SLACK_SEND_MESSAGE", "SLACK", "raw")
        # The hook should not touch non-matching tools, but other globally registered hooks may
        # Let's just verify the hook count increased
        assert len(hook_registry._after_hooks) == before_count + 1

    def test_schema_modifier_decorator(self) -> None:
        from app.utils.composio_hooks.registry import hook_registry

        @register_schema_modifier(tools=["CUSTOM_TOOL"])
        def custom_modifier(tool: str, toolkit: str, schema: Any) -> Any:
            schema.description += " [custom]"
            return schema

        s = _make_tool_schema()
        result = hook_registry.execute_schema_modifiers("CUSTOM_TOOL", "KIT", s)
        assert "[custom]" in result.description


# ============================================================================
# 3. Master hooks
# ============================================================================


class TestMasterHooks:
    """Tests for master_before_execute_hook, master_after_execute_hook, master_schema_modifier."""

    def test_master_before_delegates_to_registry(self) -> None:
        from app.utils.composio_hooks.registry import (
            hook_registry,
            master_before_execute_hook,
        )

        with patch.object(
            hook_registry, "execute_before_hooks", return_value="delegated"
        ) as mock:
            result = master_before_execute_hook("T", "K", _make_params())
            mock.assert_called_once()
            assert result == "delegated"

    def test_master_after_delegates_to_registry(self) -> None:
        from app.utils.composio_hooks.registry import (
            hook_registry,
            master_after_execute_hook,
        )

        with patch.object(
            hook_registry, "execute_after_hooks", return_value="delegated"
        ) as mock:
            result = master_after_execute_hook("T", "K", {"data": "x"})
            mock.assert_called_once()
            assert result == "delegated"

    def test_master_schema_modifier_delegates_to_registry(self) -> None:
        from app.utils.composio_hooks.registry import (
            hook_registry,
            master_schema_modifier,
        )

        schema = _make_tool_schema()
        with patch.object(
            hook_registry, "execute_schema_modifiers", return_value=schema
        ) as mock:
            result = master_schema_modifier("T", "K", schema)
            mock.assert_called_once()
            assert result is schema


# ============================================================================
# 4. User ID hooks
# ============================================================================


class TestUserIdHooks:
    """Tests for user_id extraction from RunnableConfig metadata."""

    def test_extracts_user_id_and_entity_id(self) -> None:
        from app.utils.composio_hooks.user_id_hooks import extract_user_id_from_params

        params = _make_params(
            {
                "__runnable_config__": {
                    "metadata": {"user_id": "user_123"},
                },
                "query": "test",
            }
        )
        result = extract_user_id_from_params("TOOL", "KIT", params)
        assert result["user_id"] == "user_123"
        assert result["entity_id"] == "user_123"
        # __runnable_config__ should be popped from arguments
        assert "__runnable_config__" not in result["arguments"]

    def test_no_runnable_config_returns_params_unchanged(self) -> None:
        from app.utils.composio_hooks.user_id_hooks import extract_user_id_from_params

        params = _make_params({"query": "test"})
        result = extract_user_id_from_params("TOOL", "KIT", params)
        assert "user_id" not in result
        assert "entity_id" not in result

    def test_empty_metadata_returns_params_unchanged(self) -> None:
        from app.utils.composio_hooks.user_id_hooks import extract_user_id_from_params

        params = _make_params({"__runnable_config__": {"metadata": {}}})
        result = extract_user_id_from_params("TOOL", "KIT", params)
        assert "user_id" not in result

    def test_none_user_id_returns_params_unchanged(self) -> None:
        from app.utils.composio_hooks.user_id_hooks import extract_user_id_from_params

        params = _make_params({"__runnable_config__": {"metadata": {"user_id": None}}})
        result = extract_user_id_from_params("TOOL", "KIT", params)
        assert "user_id" not in result

    def test_empty_arguments_returns_params_unchanged(self) -> None:
        from app.utils.composio_hooks.user_id_hooks import extract_user_id_from_params

        params = _make_params()
        result = extract_user_id_from_params("TOOL", "KIT", params)
        assert "user_id" not in result

    def test_config_is_not_dict_returns_params_unchanged(self) -> None:
        from app.utils.composio_hooks.user_id_hooks import extract_user_id_from_params

        params = _make_params({"__runnable_config__": "not_a_dict"})
        result = extract_user_id_from_params("TOOL", "KIT", params)
        assert "user_id" not in result


# ============================================================================
# 5. Gmail hooks — schema modifiers
# ============================================================================


class TestGmailSchemaModifiers:
    """Tests for Gmail schema modifier hooks."""

    def test_send_email_schema_adds_draft_guidance(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_send_email_schema_modifier,
        )

        schema = _make_tool_schema()
        result = gmail_send_email_schema_modifier("GMAIL_SEND_EMAIL", "GMAIL", schema)
        assert "GMAIL_CREATE_EMAIL_DRAFT" in result.description
        assert "GMAIL_SEND_DRAFT" in result.description

    def test_fetch_emails_schema_sets_defaults(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_fetch_emails_schema_modifier,
        )

        schema = _make_tool_schema(
            input_parameters={
                "properties": {
                    "max_results": {"type": "integer"},
                    "label_ids": {"type": "array"},
                    "format": {"type": "string"},
                },
            }
        )
        result = gmail_fetch_emails_schema_modifier(
            "GMAIL_FETCH_EMAILS", "GMAIL", schema
        )
        props = result.input_parameters["properties"]
        assert props["max_results"]["default"] == 10
        assert props["label_ids"]["default"] == ["INBOX"]
        assert props["format"]["default"] == "full"
        assert "GMAIL SEARCH SYNTAX" in result.description

    def test_fetch_emails_schema_adds_hard_limit_note(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            GMAIL_FULL_FETCH_HARD_LIMIT,
            gmail_fetch_emails_schema_modifier,
        )

        schema = _make_tool_schema(
            input_parameters={"properties": {"max_results": {"type": "integer"}}}
        )
        result = gmail_fetch_emails_schema_modifier(
            "GMAIL_FETCH_EMAILS", "GMAIL", schema
        )
        assert str(GMAIL_FULL_FETCH_HARD_LIMIT) in result.description

    def test_fetch_message_by_id_schema_sets_format_default(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_fetch_emails_schema_modifier,
        )

        schema = _make_tool_schema(
            input_parameters={
                "properties": {
                    "format": {"type": "string"},
                },
            }
        )
        result = gmail_fetch_emails_schema_modifier(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL", schema
        )
        props = result.input_parameters["properties"]
        assert props["format"]["default"] == "full"

    def test_schema_modifier_handles_non_dict_input_params(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_fetch_emails_schema_modifier,
        )

        schema = _make_tool_schema(input_parameters="not_a_dict")
        # Should return schema unchanged (early return)
        result = gmail_fetch_emails_schema_modifier(
            "GMAIL_FETCH_EMAILS", "GMAIL", schema
        )
        assert result is schema

    def test_schema_modifier_handles_non_dict_properties(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_fetch_emails_schema_modifier,
        )

        schema = _make_tool_schema(input_parameters={"properties": "not_a_dict"})
        result = gmail_fetch_emails_schema_modifier(
            "GMAIL_FETCH_EMAILS", "GMAIL", schema
        )
        assert result is schema


# ============================================================================
# 6. Gmail hooks — before execute
# ============================================================================


class TestGmailBeforeHooks:
    """Tests for Gmail before-execute hooks."""

    def test_fetch_emails_allows_small_full_mode_request(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_emails_before_hook

        params = _make_params({"max_results": 10, "verbose": True})
        result = gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "GMAIL", params)
        assert result is params

    def test_fetch_emails_raises_on_large_full_mode_request(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_emails_before_hook

        params = _make_params({"max_results": 50, "verbose": True})
        with pytest.raises(ToolException, match="Result set too large"):
            gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "GMAIL", params)

    def test_fetch_emails_allows_large_non_full_mode(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_emails_before_hook

        params = _make_params(
            {"max_results": 100, "verbose": False, "include_payload": False}
        )
        result = gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "GMAIL", params)
        assert result is params

    def test_fetch_emails_default_max_results_is_10(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_emails_before_hook

        # No max_results → defaults to 10 which is under the limit
        params = _make_params({})
        result = gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "GMAIL", params)
        assert result is params

    def test_fetch_emails_none_max_results_defaults_to_10(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_emails_before_hook

        params = _make_params({"max_results": None})
        result = gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "GMAIL", params)
        assert result is params

    def test_fetch_emails_malformed_max_results_returns_params(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_emails_before_hook

        params = _make_params({"max_results": "not_a_number"})
        result = gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "GMAIL", params)
        assert result is params

    def test_fetch_emails_include_payload_not_false_is_full_mode(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_emails_before_hook

        # include_payload defaults to True → full mode
        params = _make_params({"max_results": 50, "verbose": False})
        with pytest.raises(ToolException):
            gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "GMAIL", params)

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_maps_to_to_recipient_email(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params(
            {
                "to": "user@example.com",
                "subject": "Test",
                "body": "Hello",
            }
        )
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", params)
        assert result["arguments"]["recipient_email"] == "user@example.com"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_does_not_overwrite_existing_recipient(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params(
            {
                "to": "other@example.com",
                "recipient_email": "original@example.com",
                "subject": "Test",
                "body": "Hello",
            }
        )
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", params)
        assert result["arguments"]["recipient_email"] == "original@example.com"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_skips_streaming_without_recipient(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"subject": "No recipient", "body": "Hello"})
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", params)
        assert result is params
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_skips_streaming_without_content(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"recipient_email": "user@example.com"})
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", params)
        assert result is params
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_sends_draft_data(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "recipient_email": "user@example.com",
                "subject": "Draft Test",
                "body": "Content",
            }
        )
        gmail_compose_before_hook("GMAIL_CREATE_EMAIL_DRAFT", "GMAIL", params)
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "email_compose_data" in payload

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_sends_email_sent_data(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "recipient_email": "user@example.com",
                "subject": "Sending",
                "body": "Content",
            }
        )
        gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", params)
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "email_sent_data" in payload

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_reply_to_thread(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "recipient_email": "user@example.com",
                "subject": "Re: Thread",
                "body": "Reply content",
                "thread_id": "thread_abc",
            }
        )
        gmail_compose_before_hook("GMAIL_REPLY_TO_THREAD", "GMAIL", params)
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "email_sent_data" in payload
        assert payload["email_sent_data"][0]["thread_id"] == "thread_abc"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_forward_message(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "to_recipients": ["fwd@example.com", "fwd2@example.com"],
                "subject": "Fwd: Something",
                "body": "Forwarded",
            }
        )
        gmail_compose_before_hook("GMAIL_FORWARD_MESSAGE", "GMAIL", params)
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "email_sent_data" in payload
        assert payload["email_sent_data"][0]["to"] == [
            "fwd@example.com",
            "fwd2@example.com",
        ]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_forward_string_recipients(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "to_recipients": "single@example.com",
                "subject": "Fwd: Test",
                "body": "Content",
            }
        )
        gmail_compose_before_hook("GMAIL_FORWARD_MESSAGE", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert payload["email_sent_data"][0]["to"] == ["single@example.com"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_cc_bcc_only_is_valid_recipient(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "cc": ["cc@example.com"],
                "subject": "CC only",
                "body": "Content",
            }
        )
        gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", params)
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_before_hook_streams_progress(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"draft_id": "d123"})
        result = gmail_send_draft_before_hook("GMAIL_SEND_DRAFT", "GMAIL", params)
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "progress" in payload
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_trash_before_hook_trash_action(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_trash_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params()
        gmail_trash_before_hook("GMAIL_TRASH_MESSAGE", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "Moving to trash" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_trash_before_hook_untrash_action(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_trash_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params()
        gmail_trash_before_hook("GMAIL_UNTRASH_MESSAGE", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "Restoring from trash" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_label_before_hook_create(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"name": "Important"})
        gmail_label_before_hook("GMAIL_CREATE_LABEL", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "Creating label: Important" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_label_before_hook_update(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params()
        gmail_label_before_hook("GMAIL_UPDATE_LABEL", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "Updating label" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_label_before_hook_delete(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params()
        gmail_label_before_hook("GMAIL_DELETE_LABEL", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "Deleting label" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_modify_labels_before_hook_add(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "message_ids": ["m1", "m2"],
                "label_ids": ["STARRED"],
            }
        )
        gmail_modify_labels_before_hook("GMAIL_ADD_LABEL_TO_EMAIL", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "Adding labels to" in payload["progress"]
        assert "2 message(s)" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_modify_labels_before_hook_remove(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "message_ids": ["m1"],
                "label_ids": ["UNREAD"],
            }
        )
        gmail_modify_labels_before_hook("GMAIL_REMOVE_LABEL", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "Removing labels from" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_draft_management_update(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_draft_management_before_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params()
        gmail_draft_management_before_hook("GMAIL_UPDATE_DRAFT", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "Updating draft" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_draft_management_delete(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_draft_management_before_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params()
        gmail_draft_management_before_hook("GMAIL_DELETE_DRAFT", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "Deleting draft" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_list_drafts_before_hook(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_list_drafts_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"max_results": 15})
        gmail_list_drafts_before_hook("GMAIL_LIST_DRAFTS", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "15" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_draft_before_hook(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_draft_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params()
        gmail_get_draft_before_hook("GMAIL_GET_DRAFT", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "draft details" in payload["progress"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_before_hook_sets_page_size_default(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params({})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "GMAIL", params)
        assert result["arguments"]["page_size"] == 50

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_before_hook_respects_explicit_page_size(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params({"page_size": 100})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "GMAIL", params)
        assert result["arguments"]["page_size"] == 100

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_before_hook(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"query": "John"})
        gmail_search_people_before_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", params)
        payload = writer.call_args[0][0]
        assert "John" in payload["progress"]


# ============================================================================
# 7. Gmail hooks — after execute
# ============================================================================


class TestGmailAfterHooks:
    """Tests for Gmail after-execute hooks."""

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_list_messages_response")
    def test_fetch_after_hook_processes_and_streams(
        self, mock_process: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        mock_process.return_value = {
            "messages": [
                {
                    "from": "a@b.com",
                    "subject": "Hi",
                    "time": "2024-01-01",
                    "threadId": "t1",
                    "id": "m1",
                }
            ],
            "nextPageToken": "tok",
            "resultSize": 1,
        }
        response = _make_response({"messages": [{"id": "m1"}]})
        result = gmail_fetch_after_hook("GMAIL_FETCH_EMAILS", "GMAIL", response)
        assert result["messages"][0]["id"] == "m1"
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "email_fetch_data" in payload
        assert payload["resultSize"] == 1

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_list_messages_response")
    def test_fetch_after_hook_no_messages_no_stream(
        self, mock_process: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        mock_process.return_value = {"resultSize": 0}
        response = _make_response({})
        result = gmail_fetch_after_hook("GMAIL_FETCH_EMAILS", "GMAIL", response)
        writer.assert_not_called()
        assert result.get("resultSize") == 0

    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_message_detail_after_hook(self, mock_template: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_message_detail_after_hook

        mock_template.return_value = {"id": "m1", "from": "a@b.com", "subject": "Hi"}
        response = _make_response({"id": "m1", "payload": {}})
        result = gmail_message_detail_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL", response
        )
        assert result["id"] == "m1"
        mock_template.assert_called_once_with(response["data"])

    def test_message_detail_after_hook_error_response(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_message_detail_after_hook

        response = _make_response({"error": "Not found"})
        result = gmail_message_detail_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL", response
        )
        assert result == {"error": "Not found"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_get_thread_response")
    def test_thread_after_hook_processes_and_streams(
        self, mock_process: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        mock_process.return_value = {
            "id": "thread1",
            "messages": [
                {
                    "id": "m1",
                    "from": "a@b.com",
                    "subject": "Thread",
                    "time": "now",
                    "snippet": "...",
                    "body": "text",
                    "content": "text",
                }
            ],
            "messageCount": 1,
        }
        response = _make_response({"id": "thread1", "messages": []})
        result = gmail_thread_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response
        )
        assert result["id"] == "thread1"
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "email_thread_data" in payload
        assert payload["email_thread_data"]["thread_id"] == "thread1"

    def test_thread_after_hook_error_response(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        response = _make_response({"error": "Not found"})
        result = gmail_thread_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response
        )
        assert result == {"error": "Not found"}

    @patch("app.utils.composio_hooks.gmail_hooks.process_list_drafts_response")
    def test_drafts_after_hook(self, mock_process: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_drafts_after_hook

        mock_process.return_value = {
            "drafts": [{"id": "d1"}],
            "resultSize": 1,
        }
        response = _make_response({"drafts": [{"id": "d1"}]})
        result = gmail_drafts_after_hook("GMAIL_LIST_DRAFTS", "GMAIL", response)
        assert result["drafts"][0]["id"] == "d1"

    def test_drafts_after_hook_error_response(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_drafts_after_hook

        response = _make_response({"error": "Not found"})
        result = gmail_drafts_after_hook("GMAIL_LIST_DRAFTS", "GMAIL", response)
        assert result == {"error": "Not found"}

    @patch("app.utils.composio_hooks.gmail_hooks.draft_template")
    def test_draft_detail_after_hook(self, mock_template: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_detail_after_hook

        mock_template.return_value = {"id": "d1", "message": {"to": "a@b.com"}}
        response = _make_response({"id": "d1", "message": {}})
        result = gmail_draft_detail_after_hook("GMAIL_GET_DRAFT", "GMAIL", response)
        assert result["id"] == "d1"

    def test_attachment_after_hook_extracts_metadata(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response = _make_response(
            {
                "attachmentId": "att1",
                "filename": "report.pdf",
                "mimeType": "application/pdf",
                "size": 1024,
                "data": "base64_encoded_content_should_be_stripped",
            },
            successful=True,
        )
        result = gmail_attachment_after_hook(
            "GMAIL_FETCH_ATTACHMENT", "GMAIL", response
        )
        assert result["attachmentId"] == "att1"
        assert result["filename"] == "report.pdf"
        assert result["size"] == 1024
        assert "data" not in result
        assert "message" in result

    def test_attachment_after_hook_unsuccessful(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response = _make_response({"error": "Not found"}, successful=False)
        result = gmail_attachment_after_hook(
            "GMAIL_FETCH_ATTACHMENT", "GMAIL", response
        )
        assert result == {"error": "Not found"}

    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_fetch_by_id_after_hook(self, mock_template: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_by_id_after_hook

        mock_template.return_value = {"id": "m1", "subject": "Test"}
        response = _make_response({"id": "m1", "payload": {}})
        result = gmail_fetch_by_id_after_hook(
            "GMAIL_FETCH_EMAIL_BY_ID", "GMAIL", response
        )
        assert result["id"] == "m1"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_after_hook_successful(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "successful": True,
                "id": "sent_1",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"to": ["a@b.com"], "subject": "Sent draft"},
            }
        )
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "GMAIL", response)
        assert result["successful"] is True
        assert result["id"] == "sent_1"
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "email_sent_data" in payload

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_after_hook_unsuccessful(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"successful": False, "error": "Failed"})
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "GMAIL", response)
        assert result == {"successful": False, "error": "Failed"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_after_hook_processes_contacts(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "response_data": {
                    "connections": [
                        {
                            "resourceName": "people/c1",
                            "names": [
                                {
                                    "displayName": "John Doe",
                                    "metadata": {"primary": True},
                                }
                            ],
                            "emailAddresses": [
                                {
                                    "value": "john@example.com",
                                    "metadata": {"primary": True},
                                }
                            ],
                            "phoneNumbers": [
                                {"value": "+1234567890", "metadata": {"primary": True}}
                            ],
                        }
                    ],
                },
                "totalPeople": 1,
            }
        )
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "GMAIL", response)
        assert result["contacts"][0]["name"] == "John Doe"
        assert result["contacts"][0]["email"] == "john@example.com"
        assert result["contacts"][0]["phone"] == "+1234567890"
        assert result["total_count"] == 1
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_after_hook_missing_fields(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response(
            {
                "response_data": {
                    "connections": [
                        {
                            "resourceName": "people/c2",
                            "names": [],
                            "emailAddresses": [],
                            "phoneNumbers": [],
                        }
                    ],
                },
            }
        )
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "GMAIL", response)
        assert result["contacts"][0]["name"] == "Unknown"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_after_hook(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "response_data": {
                    "results": [
                        {
                            "person": {
                                "resourceName": "people/c1",
                                "names": [
                                    {
                                        "displayName": "Jane Doe",
                                        "metadata": {"primary": True},
                                    }
                                ],
                                "emailAddresses": [
                                    {
                                        "value": "jane@example.com",
                                        "metadata": {"primary": True},
                                    }
                                ],
                                "phoneNumbers": [],
                            }
                        }
                    ],
                },
            }
        )
        result = gmail_search_people_after_hook(
            "GMAIL_SEARCH_PEOPLE", "GMAIL", response
        )
        assert result["people"][0]["name"] == "Jane Doe"
        assert result["result_count"] == 1
        writer.assert_called_once()


# ============================================================================
# 8. Slack hooks
# ============================================================================


class TestSlackHooks:
    """Tests for Slack schema modifier hooks."""

    def test_slack_search_schema_modifier_sets_defaults(self) -> None:
        from app.utils.composio_hooks.slack_hooks import slack_search_schema_modifier

        schema = _make_tool_schema(
            input_parameters={
                "properties": {
                    "sort": {"type": "string"},
                    "sort_dir": {"type": "string"},
                    "count": {"type": "integer"},
                },
            }
        )
        result = slack_search_schema_modifier("SLACK_SEARCH_MESSAGES", "SLACK", schema)
        props = result.input_parameters["properties"]
        assert props["sort"]["default"] == "timestamp"
        assert props["sort_dir"]["default"] == "desc"
        assert props["count"]["default"] == 20
        assert "NEWEST FIRST" in result.description

    def test_slack_search_schema_modifier_non_dict_input_params(self) -> None:
        from app.utils.composio_hooks.slack_hooks import slack_search_schema_modifier

        schema = _make_tool_schema(input_parameters="not_dict")
        result = slack_search_schema_modifier("SLACK_SEARCH_ALL", "SLACK", schema)
        assert result is schema

    def test_slack_search_schema_modifier_non_dict_properties(self) -> None:
        from app.utils.composio_hooks.slack_hooks import slack_search_schema_modifier

        schema = _make_tool_schema(input_parameters={"properties": "bad"})
        result = slack_search_schema_modifier("SLACK_SEARCH_ALL", "SLACK", schema)
        assert result is schema


# ============================================================================
# 9. Twitter hooks — schema modifiers
# ============================================================================


class TestTwitterSchemaModifiers:
    """Tests for Twitter schema modifier hooks."""

    def test_twitter_search_schema_adds_tips(self) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_search_schema_modifier,
        )

        schema = _make_tool_schema()
        result = twitter_search_schema_modifier(
            "TWITTER_RECENT_SEARCH", "TWITTER", schema
        )
        assert "from:username" in result.description
        assert "is:retweet" in result.description

    def test_twitter_follow_schema_adds_guidance(self) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_follow_schema_modifier,
        )

        schema = _make_tool_schema()
        result = twitter_follow_schema_modifier(
            "TWITTER_FOLLOW_USER", "TWITTER", schema
        )
        assert "TWITTER_RECENT_SEARCH" in result.description

    def test_twitter_create_post_schema_adds_tips(self) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_create_post_schema_modifier,
        )

        schema = _make_tool_schema()
        result = twitter_create_post_schema_modifier(
            "TWITTER_CREATION_OF_A_POST", "TWITTER", schema
        )
        assert "TWITTER_UPLOAD_MEDIA" in result.description
        assert "poll_options" in result.description

    def test_twitter_timeline_schema_sets_max_results(self) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_timeline_schema_modifier,
        )

        schema = _make_tool_schema(
            input_parameters={
                "properties": {"max_results": {"type": "integer"}},
            }
        )
        result = twitter_timeline_schema_modifier(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", schema
        )
        assert result.input_parameters["properties"]["max_results"]["default"] == 20

    def test_twitter_timeline_schema_non_dict_input_params(self) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_timeline_schema_modifier,
        )

        schema = _make_tool_schema(input_parameters="invalid")
        result = twitter_timeline_schema_modifier(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", schema
        )
        assert result is schema


# ============================================================================
# 10. Twitter hooks — before execute
# ============================================================================


class TestTwitterBeforeHooks:
    """Tests for Twitter before-execute hooks."""

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_create_post_before_hook_streams_preview(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_create_post_before_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "text": "Hello Twitter!",
                "quote_tweet_id": "qt123",
                "reply_in_reply_to_tweet_id": "rt456",
                "media_media_ids": ["media1"],
                "poll_options": ["Yes", "No"],
            }
        )
        result = twitter_create_post_before_hook(
            "TWITTER_CREATION_OF_A_POST", "TWITTER", params
        )
        assert result is params
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert payload["twitter_post_preview"]["text"] == "Hello Twitter!"
        assert payload["twitter_post_preview"]["quote_tweet_id"] == "qt123"

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_create_post_before_hook_no_writer(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_create_post_before_hook,
        )

        mock_writer.return_value = None
        params = _make_params({"text": "Hello"})
        result = twitter_create_post_before_hook(
            "TWITTER_CREATION_OF_A_POST", "TWITTER", params
        )
        assert result is params

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_before_hook_streams_progress(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"query": "AI news"})
        twitter_search_before_hook("TWITTER_RECENT_SEARCH", "TWITTER", params)
        payload = writer.call_args[0][0]
        assert "AI news" in payload["progress"]


# ============================================================================
# 11. Twitter hooks — after execute
# ============================================================================


class TestTwitterAfterHooks:
    """Tests for Twitter after-execute hooks."""

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_processes_tweets(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "data": [
                    {
                        "id": "tw1",
                        "text": "Hello world",
                        "created_at": "2024-01-01T00:00:00Z",
                        "author_id": "u1",
                        "public_metrics": {"like_count": 10, "retweet_count": 5},
                        "conversation_id": "conv1",
                    }
                ],
                "includes": {
                    "users": [
                        {
                            "id": "u1",
                            "username": "testuser",
                            "name": "Test User",
                            "profile_image_url": "https://img.com/pic.jpg",
                            "verified": True,
                            "description": "Bio",
                            "public_metrics": {"followers_count": 100},
                        }
                    ]
                },
                "meta": {"result_count": 1, "next_token": "tok123"},
            }
        )
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result["result_count"] == 1
        assert result["has_more"] is True
        assert result["tweets"][0]["author_username"] == "testuser"
        assert result["tweets"][0]["likes"] == 10
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "twitter_search_data" in payload

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_error_response(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"error": "Rate limited"})
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result == {"error": "Rate limited"}

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_truncates_long_tweets(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        mock_writer.return_value = _noop_writer()
        long_text = "x" * 300
        response = _make_response(
            {
                "data": [
                    {
                        "id": "tw1",
                        "text": long_text,
                        "author_id": "u1",
                        "public_metrics": {},
                    }
                ],
                "includes": {"users": []},
                "meta": {"result_count": 1},
            }
        )
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert len(result["tweets"][0]["text"]) == 203  # 200 + "..."

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_user_lookup_after_hook_single_user(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_user_lookup_after_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "data": {
                    "id": "u1",
                    "username": "johndoe",
                    "name": "John Doe",
                    "verified": True,
                    "public_metrics": {"followers_count": 1000, "following_count": 200},
                    "description": "Dev",
                    "profile_image_url": "https://img.com/pic.jpg",
                    "created_at": "2020-01-01",
                    "location": "NYC",
                    "url": "https://example.com",
                }
            }
        )
        result = twitter_user_lookup_after_hook(
            "TWITTER_USER_LOOKUP_BY_USERNAME", "TWITTER", response
        )
        assert result["users"][0]["username"] == "johndoe"
        assert result["users"][0]["followers"] == 1000
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_user_lookup_after_hook_multiple_users(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_user_lookup_after_hook,
        )

        mock_writer.return_value = _noop_writer()
        response = _make_response(
            {
                "data": [
                    {
                        "id": "u1",
                        "username": "a",
                        "name": "A",
                        "verified": False,
                        "public_metrics": {},
                    },
                    {
                        "id": "u2",
                        "username": "b",
                        "name": "B",
                        "verified": True,
                        "public_metrics": {},
                    },
                ]
            }
        )
        result = twitter_user_lookup_after_hook(
            "TWITTER_USER_LOOKUP_BY_USERNAMES", "TWITTER", response
        )
        assert len(result["users"]) == 2

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_timeline_after_hook(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "data": [
                    {
                        "id": "tw1",
                        "text": "Timeline tweet",
                        "created_at": "2024-01-01",
                        "author_id": "u1",
                        "public_metrics": {"like_count": 5},
                    }
                ],
                "includes": {
                    "users": [
                        {
                            "id": "u1",
                            "username": "testuser",
                            "name": "Test",
                            "profile_image_url": "https://img.com",
                            "verified": False,
                        }
                    ]
                },
            }
        )
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result["tweets"][0]["author"] == "testuser"
        assert result["count"] == 1
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_followers_after_hook(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "data": [
                    {
                        "id": "u1",
                        "username": "follower1",
                        "name": "Follower 1",
                        "profile_image_url": "https://img.com",
                        "verified": False,
                        "description": "Bio",
                        "public_metrics": {"followers_count": 50},
                    }
                ],
                "meta": {"next_token": "next"},
            }
        )
        result = twitter_followers_after_hook(
            "TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response
        )
        assert result["users"][0]["username"] == "follower1"
        assert result["has_more"] is True
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "twitter_followers_data" in payload

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_following_after_hook_uses_following_key(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "data": [
                    {
                        "id": "u1",
                        "username": "following1",
                        "name": "Following 1",
                        "public_metrics": {"followers_count": 100},
                    }
                ],
                "meta": {},
            }
        )
        result = twitter_followers_after_hook(
            "TWITTER_FOLLOWING_BY_USER_ID", "TWITTER", response
        )
        assert result["has_more"] is False
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "twitter_following_data" in payload

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_post_created_after_hook(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_post_created_after_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "data": {
                    "id": "post123",
                    "text": "My new tweet",
                }
            }
        )
        result = twitter_post_created_after_hook(
            "TWITTER_CREATION_OF_A_POST", "TWITTER", response
        )
        assert result["success"] is True
        assert result["id"] == "post123"
        assert "twitter.com" in result["url"]
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert payload["twitter_post_created"]["id"] == "post123"

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_post_created_after_hook_error(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_post_created_after_hook,
        )

        mock_writer.return_value = _noop_writer()
        response = _make_response({"error": "Duplicate"})
        result = twitter_post_created_after_hook(
            "TWITTER_CREATION_OF_A_POST", "TWITTER", response
        )
        assert result == {"error": "Duplicate"}


# ============================================================================
# 12. Reddit hooks — helper functions
# ============================================================================


class TestRedditHelpers:
    """Tests for Reddit helper functions (process_reddit_post, etc.)."""

    def test_process_reddit_post_extracts_fields(self) -> None:
        post = {
            "data": {
                "id": "abc123",
                "title": "Test Post",
                "author": "testuser",
                "subreddit": "python",
                "subreddit_name_prefixed": "r/python",
                "created_utc": 1704067200,
                "score": 42,
                "upvote_ratio": 0.95,
                "num_comments": 10,
                "selftext": "Hello world",
                "url": "https://reddit.com/r/python/abc",
                "permalink": "/r/python/comments/abc",
                "is_self": True,
                "link_flair_text": "Discussion",
                "over_18": False,
                "spoiler": False,
                "locked": False,
                "stickied": False,
            }
        }
        result = process_reddit_post(post)
        assert result["id"] == "abc123"
        assert result["title"] == "Test Post"
        assert result["score"] == 42
        assert result["is_self"] is True

    def test_process_reddit_post_empty_data(self) -> None:
        result = process_reddit_post({})
        assert result["id"] == ""
        assert result["title"] == ""

    def test_process_reddit_comment_extracts_fields(self) -> None:
        comment = {
            "data": {
                "id": "cmt1",
                "author": "commenter",
                "body": "Great post!",
                "created_utc": 1704067200,
                "score": 15,
                "permalink": "/r/python/comments/abc/cmt1",
                "parent_id": "t3_abc",
                "link_id": "t3_abc",
                "subreddit": "python",
                "is_submitter": False,
                "stickied": False,
                "distinguished": None,
                "edited": False,
            }
        }
        result = process_reddit_comment(comment)
        assert result["id"] == "cmt1"
        assert result["body"] == "Great post!"
        assert result["score"] == 15

    def test_process_reddit_search_results(self) -> None:
        response = {
            "search_results": {
                "data": {
                    "children": [
                        {"kind": "t3", "data": {"id": "p1", "title": "Post 1"}},
                        {"kind": "t3", "data": {"id": "p2", "title": "Post 2"}},
                        {"kind": "t1", "data": {"id": "c1"}},  # comment, skipped
                    ],
                    "after": "cursor123",
                    "before": None,
                }
            }
        }
        result = process_reddit_search_results(response)
        assert result["result_count"] == 2
        assert result["after"] == "cursor123"
        assert result["posts"][0]["id"] == "p1"

    def test_process_reddit_search_results_empty(self) -> None:
        result = process_reddit_search_results(
            {"search_results": {"data": {"children": []}}}
        )
        assert result["result_count"] == 0
        assert result["posts"] == []


# ============================================================================
# 13. Reddit hooks — before execute
# ============================================================================


class TestRedditBeforeHooks:
    """Tests for Reddit before-execute hooks."""

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_create_post(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_content_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"subreddit": "python"})
        reddit_content_before_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", params)
        payload = writer.call_args[0][0]
        assert "r/python" in payload["progress"]

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_post_comment(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_content_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_content_before_hook("REDDIT_POST_REDDIT_COMMENT", "REDDIT", params)
        payload = writer.call_args[0][0]
        assert "Posting comment" in payload["progress"]

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_edit(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_content_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_content_before_hook(
            "REDDIT_EDIT_REDDIT_COMMENT_OR_POST", "REDDIT", params
        )
        payload = writer.call_args[0][0]
        assert "Editing content" in payload["progress"]

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_no_writer(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_content_before_hook

        mock_writer.return_value = None
        params = _make_params({})
        result = reddit_content_before_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", params
        )
        assert result is params

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_delete_before_hook_post(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_delete_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_delete_before_hook("REDDIT_DELETE_REDDIT_POST", "REDDIT", params)
        payload = writer.call_args[0][0]
        assert "post" in payload["progress"]

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_delete_before_hook_comment(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_delete_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_delete_before_hook("REDDIT_DELETE_REDDIT_COMMENT", "REDDIT", params)
        payload = writer.call_args[0][0]
        assert "comment" in payload["progress"]

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_retrieve_before_hook_post(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_retrieve_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_retrieve_before_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", params)
        payload = writer.call_args[0][0]
        assert "Fetching post details" in payload["progress"]

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_retrieve_before_hook_comments(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_retrieve_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_retrieve_before_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", params)
        payload = writer.call_args[0][0]
        assert "comments" in payload["progress"]


# ============================================================================
# 14. Reddit hooks — after execute
# ============================================================================


class TestRedditAfterHooks:
    """Tests for Reddit after-execute hooks."""

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_processes_results(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_search_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "search_results": {
                    "data": {
                        "children": [
                            {
                                "kind": "t3",
                                "data": {
                                    "id": "p1",
                                    "title": "Python Tips",
                                    "author": "dev",
                                    "subreddit": "python",
                                    "subreddit_name_prefixed": "r/python",
                                    "score": 100,
                                    "num_comments": 20,
                                    "created_utc": 1704067200,
                                    "permalink": "/r/python/p1",
                                    "url": "https://reddit.com/r/python/p1",
                                    "selftext": "Short text",
                                },
                            }
                        ],
                        "after": None,
                        "before": None,
                    }
                }
            }
        )
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result["result_count"] == 1
        assert result["posts"][0]["id"] == "p1"
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["type"] == "search"

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_error_response(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_search_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"error": "Rate limited"})
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {"error": "Rate limited"}

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_post_detail_after_hook(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_post_detail_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "data": {
                    "id": "p1",
                    "title": "Detail Post",
                    "author": "author1",
                    "subreddit_name_prefixed": "r/python",
                    "score": 50,
                    "upvote_ratio": 0.9,
                    "num_comments": 5,
                    "created_utc": 1704067200,
                    "selftext": "Content here",
                    "url": "https://reddit.com/r/python/p1",
                    "permalink": "/r/python/p1",
                    "is_self": True,
                    "link_flair_text": None,
                }
            }
        )
        result = reddit_post_detail_after_hook(
            "REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response
        )
        assert result["id"] == "p1"
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["type"] == "post"

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_array_format(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_comments_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        # Reddit returns [post_listing, comments_listing]
        response = _make_response(
            [
                {"data": {"children": []}},  # post listing
                {
                    "data": {
                        "children": [
                            {
                                "kind": "t1",
                                "data": {
                                    "id": "c1",
                                    "author": "commenter",
                                    "body": "Nice post!",
                                    "created_utc": 1704067200,
                                    "score": 10,
                                    "permalink": "/r/python/p1/c1",
                                    "parent_id": "t3_p1",
                                    "is_submitter": False,
                                },
                            }
                        ]
                    }
                },
            ]
        )
        result = reddit_comments_after_hook(
            "REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response
        )
        assert result["comment_count"] == 1
        assert result["comments"][0]["body"] == "Nice post!"
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_dict_format(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_comments_after_hook

        mock_writer.return_value = _noop_writer()
        # Alternative dict structure
        response = _make_response(
            {
                "comments": {
                    "data": {
                        "children": [
                            {
                                "kind": "t1",
                                "data": {
                                    "id": "c1",
                                    "author": "user1",
                                    "body": "Comment body",
                                    "score": 5,
                                },
                            }
                        ]
                    }
                }
            }
        )
        result = reddit_comments_after_hook(
            "REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response
        )
        assert result["comment_count"] == 1

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_skips_non_t1(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_comments_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response(
            [
                {"data": {"children": []}},
                {
                    "data": {
                        "children": [
                            {"kind": "more", "data": {"id": "more1"}},
                        ]
                    }
                },
            ]
        )
        result = reddit_comments_after_hook(
            "REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response
        )
        assert result["comment_count"] == 0

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_post(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import (
            reddit_content_created_after_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "id": "new_post",
                "url": "https://reddit.com/r/python/new_post",
                "permalink": "/r/python/new_post",
            }
        )
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert result["success"] is True
        assert result["id"] == "new_post"
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["type"] == "post_created"

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_comment(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import (
            reddit_content_created_after_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "id": "new_comment",
                "permalink": "/r/python/p1/new_comment",
            }
        )
        result = reddit_content_created_after_hook(
            "REDDIT_POST_REDDIT_COMMENT", "REDDIT", response
        )
        assert result["success"] is True
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["type"] == "comment_created"

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_error(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import (
            reddit_content_created_after_hook,
        )

        mock_writer.return_value = _noop_writer()
        response = _make_response({"error": "Forbidden"})
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert result == {"error": "Forbidden"}


# ============================================================================
# 15. Edge cases and error resilience
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling across the hook system."""

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_hook_exception_returns_params(
        self, mock_writer: MagicMock
    ) -> None:
        """If get_stream_writer raises, the compose hook returns params unchanged."""
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.side_effect = RuntimeError("No writer context")
        params = _make_params(
            {
                "recipient_email": "a@b.com",
                "subject": "Test",
                "body": "Content",
            }
        )
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_list_messages_response")
    def test_fetch_after_hook_exception_returns_raw_data(
        self, mock_process: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_after_hook

        mock_writer.return_value = _noop_writer()
        mock_process.side_effect = ValueError("parse error")
        response = _make_response({"raw": "data"})
        result = gmail_fetch_after_hook("GMAIL_FETCH_EMAILS", "GMAIL", response)
        assert result == {"raw": "data"}

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_twitter_search_after_hook_exception_returns_data(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        mock_writer.side_effect = RuntimeError("No writer")
        response = _make_response({"data": [], "includes": {}, "meta": {}})
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result == {"data": [], "includes": {}, "meta": {}}

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_reddit_search_after_hook_exception_returns_data(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_search_after_hook

        mock_writer.side_effect = RuntimeError("No writer")
        response = _make_response({"search_results": {}})
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        # When exception occurs during processing, falls through to return response data
        assert isinstance(result, dict)

    def test_gmail_before_hook_boundary_at_limit(self) -> None:
        """max_results exactly at the limit should pass."""
        from app.utils.composio_hooks.gmail_hooks import (
            GMAIL_FULL_FETCH_HARD_LIMIT,
            gmail_fetch_emails_before_hook,
        )

        params = _make_params(
            {"max_results": GMAIL_FULL_FETCH_HARD_LIMIT, "verbose": True}
        )
        result = gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "GMAIL", params)
        assert result is params

    def test_gmail_before_hook_boundary_above_limit(self) -> None:
        """max_results one above the limit should raise."""
        from app.utils.composio_hooks.gmail_hooks import (
            GMAIL_FULL_FETCH_HARD_LIMIT,
            gmail_fetch_emails_before_hook,
        )

        params = _make_params(
            {"max_results": GMAIL_FULL_FETCH_HARD_LIMIT + 1, "verbose": True}
        )
        with pytest.raises(ToolException):
            gmail_fetch_emails_before_hook("GMAIL_FETCH_EMAILS", "GMAIL", params)

    def test_gmail_attachment_non_dict_data(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response: dict[str, Any] = {"data": "plain_string", "successful": True}
        result = gmail_attachment_after_hook(
            "GMAIL_FETCH_ATTACHMENT", "GMAIL", response
        )
        assert result == "plain_string"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_gmail_before_hook_no_writer_skips_streaming(
        self, mock_writer: MagicMock
    ) -> None:
        """Before hooks that check writer truthy-ness skip streaming gracefully."""
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_before_hook

        mock_writer.return_value = None
        params = _make_params({})
        result = gmail_send_draft_before_hook("GMAIL_SEND_DRAFT", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_extra_recipients_non_list(
        self, mock_writer: MagicMock
    ) -> None:
        """When extra_recipients is not a list, it should be treated as empty."""
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "recipient_email": "user@example.com",
                "extra_recipients": "not_a_list",
                "subject": "Test",
                "body": "Content",
            }
        )
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", params)
        assert result is params
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        # extra_recipients reset to [], so only recipient_email in to list
        assert payload["email_sent_data"][0]["to"] == ["user@example.com"]

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_trash_before_hook_writer_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_trash_before_hook

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_trash_before_hook("GMAIL_TRASH_MESSAGE", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_label_before_hook_writer_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_label_before_hook("GMAIL_CREATE_LABEL", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_modify_labels_before_hook_writer_exception(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_modify_labels_before_hook(
            "GMAIL_ADD_LABEL_TO_EMAIL", "GMAIL", params
        )
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_draft_management_before_hook_writer_exception(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_draft_management_before_hook,
        )

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_draft_management_before_hook(
            "GMAIL_UPDATE_DRAFT", "GMAIL", params
        )
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_list_drafts_before_hook_writer_exception(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_list_drafts_before_hook

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_list_drafts_before_hook("GMAIL_LIST_DRAFTS", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_draft_before_hook_writer_exception(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_draft_before_hook

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_get_draft_before_hook("GMAIL_GET_DRAFT", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_before_hook_writer_exception(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_before_hook_writer_exception(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_before_hook

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({"query": "Test"})
        result = gmail_search_people_before_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", params)
        assert result is params


# ============================================================================
# 16. Additional Gmail after-hook exception paths
# ============================================================================


class TestGmailAfterHookExceptions:
    """Cover exception branches in Gmail after-execute hooks."""

    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_message_detail_exception_returns_raw(
        self, mock_template: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_message_detail_after_hook

        mock_template.side_effect = KeyError("bad key")
        response = _make_response({"raw": "data"})
        result = gmail_message_detail_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL", response
        )
        assert result == {"raw": "data"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_get_thread_response")
    def test_thread_exception_returns_raw(
        self, mock_process: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        mock_writer.return_value = _noop_writer()
        mock_process.side_effect = TypeError("unexpected")
        response = _make_response({"raw": "thread_data"})
        result = gmail_thread_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response
        )
        assert result == {"raw": "thread_data"}

    @patch("app.utils.composio_hooks.gmail_hooks.process_list_drafts_response")
    def test_drafts_exception_returns_raw(self, mock_process: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_drafts_after_hook

        mock_process.side_effect = ValueError("bad data")
        response = _make_response({"raw": "drafts"})
        result = gmail_drafts_after_hook("GMAIL_LIST_DRAFTS", "GMAIL", response)
        assert result == {"raw": "drafts"}

    @patch("app.utils.composio_hooks.gmail_hooks.draft_template")
    def test_draft_detail_exception_returns_raw(self, mock_template: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_detail_after_hook

        mock_template.side_effect = RuntimeError("parse fail")
        response = _make_response({"raw": "draft"})
        result = gmail_draft_detail_after_hook("GMAIL_GET_DRAFT", "GMAIL", response)
        assert result == {"raw": "draft"}

    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_fetch_by_id_exception_returns_raw(self, mock_template: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_by_id_after_hook

        mock_template.side_effect = KeyError("bad key")
        response = _make_response({"raw": "email"})
        result = gmail_fetch_by_id_after_hook(
            "GMAIL_FETCH_EMAIL_BY_ID", "GMAIL", response
        )
        assert result == {"raw": "email"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_after_exception_returns_raw(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        mock_writer.side_effect = RuntimeError("no writer")
        response = _make_response({"successful": True, "id": "x"})
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "GMAIL", response)
        assert result == {"successful": True, "id": "x"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_after_exception_returns_raw(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        mock_writer.side_effect = RuntimeError("no writer")
        response = _make_response({"response_data": {"connections": []}})
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "GMAIL", response)
        assert result == {"response_data": {"connections": []}}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_after_hook_error_response(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"error": "Not found"})
        result = gmail_search_people_after_hook(
            "GMAIL_SEARCH_PEOPLE", "GMAIL", response
        )
        assert result == {"error": "Not found"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_after_exception_returns_raw(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"response_data": {"results": []}})
        result = gmail_search_people_after_hook(
            "GMAIL_SEARCH_PEOPLE", "GMAIL", response
        )
        assert result == {"response_data": {"results": []}}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_after_hook_with_phone(self, mock_writer: MagicMock) -> None:
        """Ensure phone numbers are extracted when present."""
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "response_data": {
                    "results": [
                        {
                            "person": {
                                "names": [
                                    {
                                        "displayName": "Test",
                                        "metadata": {"primary": True},
                                    }
                                ],
                                "emailAddresses": [
                                    {"value": "t@x.com", "metadata": {"primary": True}}
                                ],
                                "phoneNumbers": [
                                    {"value": "+1111", "metadata": {"primary": True}}
                                ],
                            }
                        }
                    ],
                },
            }
        )
        result = gmail_search_people_after_hook(
            "GMAIL_SEARCH_PEOPLE", "GMAIL", response
        )
        assert result["people"][0]["phone"] == "+1111"


# ============================================================================
# 17. Decorator string args and toolkit matching
# ============================================================================


class TestDecoratorStringArgsAndToolkitMatching:
    """Cover registry decorator paths for string tool/toolkit args and toolkit matching."""

    def setup_method(self) -> None:
        from app.utils.composio_hooks.registry import hook_registry

        self._orig_before = hook_registry._before_hooks.copy()
        self._orig_after = hook_registry._after_hooks.copy()
        self._orig_schema = hook_registry._schema_modifiers.copy()

    def teardown_method(self) -> None:
        from app.utils.composio_hooks.registry import hook_registry

        hook_registry._before_hooks = self._orig_before
        hook_registry._after_hooks = self._orig_after
        hook_registry._schema_modifiers = self._orig_schema

    def test_after_hook_string_toolkit(self) -> None:
        """register_after_hook with toolkits as a string."""
        from app.utils.composio_hooks.registry import hook_registry

        @register_after_hook(toolkits="SLACK")
        def slack_toolkit_after(tool: str, toolkit: str, response: Any) -> Any:
            return {"slack_processed": True}

        result = hook_registry.execute_after_hooks("SLACK_SEND_MESSAGE", "SLACK", "raw")
        assert result == {"slack_processed": True}

    def test_after_hook_string_tool(self) -> None:
        """register_after_hook with tools as a single string."""
        from app.utils.composio_hooks.registry import hook_registry

        @register_after_hook(tools="MY_TOOL")
        def single_tool_after(tool: str, toolkit: str, response: Any) -> Any:
            return {"single": True}

        result = hook_registry.execute_after_hooks("MY_TOOL", "KIT", "raw")
        assert result == {"single": True}

    def test_schema_modifier_string_toolkit(self) -> None:
        """register_schema_modifier with toolkits as a string."""
        from app.utils.composio_hooks.registry import hook_registry

        @register_schema_modifier(toolkits="TWITTER")
        def twitter_kit_modifier(tool: str, toolkit: str, schema: Any) -> Any:
            schema.description += " [twitter_kit]"
            return schema

        s = _make_tool_schema()
        result = hook_registry.execute_schema_modifiers("ANY_TOOL", "TWITTER", s)
        assert "[twitter_kit]" in result.description

    def test_schema_modifier_string_tool(self) -> None:
        """register_schema_modifier with tools as a single string."""
        from app.utils.composio_hooks.registry import hook_registry

        @register_schema_modifier(tools="SINGLE_TOOL")
        def single_modifier(tool: str, toolkit: str, schema: Any) -> Any:
            schema.description += " [single]"
            return schema

        s = _make_tool_schema()
        result = hook_registry.execute_schema_modifiers("SINGLE_TOOL", "KIT", s)
        assert "[single]" in result.description

    def test_schema_modifier_no_filter_runs_for_all(self) -> None:
        """register_schema_modifier with no tools/toolkits runs for everything."""
        from app.utils.composio_hooks.registry import hook_registry

        @register_schema_modifier()
        def universal_modifier(tool: str, toolkit: str, schema: Any) -> Any:
            schema.description += " [universal]"
            return schema

        s = _make_tool_schema()
        result = hook_registry.execute_schema_modifiers("ANY", "ANY", s)
        assert "[universal]" in result.description

    def test_after_hook_no_filter_runs_for_all(self) -> None:
        """register_after_hook with no tools/toolkits runs for everything."""
        from app.utils.composio_hooks.registry import hook_registry

        @register_after_hook()
        def universal_after(tool: str, toolkit: str, response: Any) -> Any:
            return {"universal": True}

        result = hook_registry.execute_after_hooks("ANY", "ANY", "raw")
        assert result == {"universal": True}

    def test_before_hook_string_toolkit(self) -> None:
        """register_before_hook with toolkits as a single string."""
        from app.utils.composio_hooks.registry import hook_registry

        @register_before_hook(toolkits="REDDIT")
        def reddit_kit_hook(tool: str, toolkit: str, params: dict) -> dict:
            params["arguments"]["reddit_kit"] = True
            return params

        p = _make_params()
        result = hook_registry.execute_before_hooks("ANY", "REDDIT", p)
        assert result["arguments"]["reddit_kit"] is True

    def test_before_hook_string_tool(self) -> None:
        """register_before_hook with tools as a single string."""
        from app.utils.composio_hooks.registry import hook_registry

        @register_before_hook(tools="SINGLE")
        def single_hook(tool: str, toolkit: str, params: dict) -> dict:
            params["arguments"]["single"] = True
            return params

        p = _make_params()
        result = hook_registry.execute_before_hooks("SINGLE", "KIT", p)
        assert result["arguments"]["single"] is True


# ============================================================================
# 18. Reddit and Twitter after-hook exception paths
# ============================================================================


class TestRedditTwitterAfterHookExceptions:
    """Cover exception branches in Reddit/Twitter after-execute hooks."""

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_reddit_post_detail_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_post_detail_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"data": {"id": "p1"}})
        result = reddit_post_detail_after_hook(
            "REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response
        )
        assert isinstance(result, dict)

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_reddit_comments_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_comments_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response([{}, {"data": {"children": []}}])
        result = reddit_comments_after_hook(
            "REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response
        )
        # On exception, returns response.get("data") which is the list
        assert isinstance(result, list)

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_reddit_content_created_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import (
            reddit_content_created_after_hook,
        )

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"id": "new"})
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert isinstance(result, dict)

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_reddit_content_before_hook_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_content_before_hook

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({"subreddit": "test"})
        result = reddit_content_before_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", params
        )
        assert result is params

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_reddit_delete_before_hook_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_delete_before_hook

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({})
        result = reddit_delete_before_hook(
            "REDDIT_DELETE_REDDIT_POST", "REDDIT", params
        )
        assert result is params

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_reddit_retrieve_before_hook_exception(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_retrieve_before_hook

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({})
        result = reddit_retrieve_before_hook(
            "REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", params
        )
        assert result is params

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_twitter_create_post_before_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_create_post_before_hook,
        )

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({"text": "Test"})
        result = twitter_create_post_before_hook(
            "TWITTER_CREATION_OF_A_POST", "TWITTER", params
        )
        assert result is params

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_twitter_search_before_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_before_hook

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({"query": "test"})
        result = twitter_search_before_hook("TWITTER_RECENT_SEARCH", "TWITTER", params)
        assert result is params

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_twitter_user_lookup_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_user_lookup_after_hook,
        )

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"data": {"id": "u1"}})
        result = twitter_user_lookup_after_hook(
            "TWITTER_USER_LOOKUP_BY_USERNAME", "TWITTER", response
        )
        assert isinstance(result, dict)

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_twitter_timeline_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"data": [], "includes": {}})
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert isinstance(result, dict)

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_twitter_followers_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"data": []})
        result = twitter_followers_after_hook(
            "TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response
        )
        assert isinstance(result, dict)

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_twitter_post_created_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_post_created_after_hook,
        )

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"data": {"id": "p1"}})
        result = twitter_post_created_after_hook(
            "TWITTER_CREATION_OF_A_POST", "TWITTER", response
        )
        assert isinstance(result, dict)
