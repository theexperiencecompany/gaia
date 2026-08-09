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

from app.utils.composio_hooks.reddit_hooks import (
    process_reddit_comment,
    process_reddit_post,
    process_reddit_search_results,
    reddit_comments_after_hook,
    reddit_content_before_hook,
    reddit_content_created_after_hook,
    reddit_delete_before_hook,
    reddit_post_detail_after_hook,
    reddit_retrieve_before_hook,
    reddit_search_after_hook,
)
from app.utils.composio_hooks.registry import (
    ComposioHookRegistry,
    register_after_hook,
    register_before_hook,
    register_schema_modifier,
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


def _assert_logged_error(
    mock_log: MagicMock, message: str, error: str, error_type: str
) -> None:
    """Assert the exact message, error string and error_type of a log.error call."""
    mock_log.error.assert_called_once()
    assert message in mock_log.error.call_args.args[0]
    assert mock_log.error.call_args.kwargs["error"] == error
    assert mock_log.error.call_args.kwargs["error_type"] == error_type


_REDDIT_POST_DEFAULTS: dict[str, Any] = {
    "id": "",
    "title": "",
    "author": "",
    "subreddit": "",
    "subreddit_name_prefixed": "",
    "created_utc": 0,
    "score": 0,
    "upvote_ratio": 0,
    "num_comments": 0,
    "selftext": "",
    "url": "",
    "permalink": "",
    "is_self": False,
    "link_flair_text": None,
    "over_18": False,
    "spoiler": False,
    "locked": False,
    "stickied": False,
}

_REDDIT_COMMENT_DEFAULTS: dict[str, Any] = {
    "id": "",
    "author": "",
    "body": "",
    "created_utc": 0,
    "score": 0,
    "permalink": "",
    "parent_id": "",
    "link_id": "",
    "subreddit": "",
    "is_submitter": False,
    "stickied": False,
    "distinguished": None,
    "edited": False,
}


def _make_reddit_post_data(**overrides: Any) -> dict[str, Any]:
    """Full Reddit post ``data`` dict (every field present, truthy flags)."""
    post = {
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
        "over_18": True,
        "spoiler": True,
        "locked": True,
        "stickied": True,
    }
    post.update(overrides)
    return post


def _make_reddit_comment_data(**overrides: Any) -> dict[str, Any]:
    """Full Reddit comment ``data`` dict (every field present, truthy flags)."""
    comment = {
        "id": "cmt1",
        "author": "commenter",
        "body": "Great post!",
        "created_utc": 1704067200,
        "score": 15,
        "permalink": "/r/python/comments/abc/cmt1",
        "parent_id": "t3_abc",
        "link_id": "t3_abc",
        "subreddit": "python",
        "is_submitter": True,
        "stickied": True,
        "distinguished": "moderator",
        "edited": True,
    }
    comment.update(overrides)
    return comment


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

        with patch.object(hook_registry, "execute_before_hooks", return_value="delegated") as mock:
            result = master_before_execute_hook("T", "K", _make_params())
            mock.assert_called_once()
            assert result == "delegated"

    def test_master_after_delegates_to_registry(self) -> None:
        from app.utils.composio_hooks.registry import (
            hook_registry,
            master_after_execute_hook,
        )

        with patch.object(hook_registry, "execute_after_hooks", return_value="delegated") as mock:
            result = master_after_execute_hook("T", "K", {"data": "x"})
            mock.assert_called_once()
            assert result == "delegated"

    def test_master_schema_modifier_delegates_to_registry(self) -> None:
        from app.utils.composio_hooks.registry import (
            hook_registry,
            master_schema_modifier,
        )

        schema = _make_tool_schema()
        with patch.object(hook_registry, "execute_schema_modifiers", return_value=schema) as mock:
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

    def test_fetch_message_by_id_schema_sets_format_default(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_fetch_message_schema_modifier,
        )

        schema = _make_tool_schema(
            input_parameters={
                "properties": {
                    "format": {"type": "string"},
                },
            }
        )
        result = gmail_fetch_message_schema_modifier(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL", schema
        )
        props = result.input_parameters["properties"]
        assert props["format"]["default"] == "full"

    def test_schema_modifier_handles_non_dict_input_params(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_fetch_message_schema_modifier,
        )

        schema = _make_tool_schema(input_parameters="not_a_dict")
        # Should return schema unchanged (early return)
        result = gmail_fetch_message_schema_modifier("GMAIL_FETCH_EMAILS", "GMAIL", schema)
        assert result is schema

    def test_schema_modifier_handles_non_dict_properties(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_fetch_message_schema_modifier,
        )

        schema = _make_tool_schema(input_parameters={"properties": "not_a_dict"})
        result = gmail_fetch_message_schema_modifier("GMAIL_FETCH_EMAILS", "GMAIL", schema)
        assert result is schema

    def test_send_email_schema_appends_exact_draft_guidance(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_send_email_schema_modifier,
        )

        schema = _make_tool_schema(description="Original description")
        result = gmail_send_email_schema_modifier("GMAIL_SEND_EMAIL", "GMAIL", schema)
        assert result is schema
        assert result.description == (
            "Original description\n\nIMPORTANT WORKFLOW: Unless the user explicitly requests "
            "immediate sending, prefer creating a draft first using "
            "GMAIL_CREATE_EMAIL_DRAFT for user review. "
            "If a draft was already created in the current conversation, "
            "use GMAIL_SEND_DRAFT with the draft_id instead of this tool."
        )

    def test_fetch_message_schema_sets_format_default_exactly(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_fetch_message_schema_modifier,
        )

        schema = _make_tool_schema(
            input_parameters={"properties": {"format": {"type": "string"}}}
        )
        result = gmail_fetch_message_schema_modifier(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL", schema
        )
        assert result.input_parameters == {
            "properties": {"format": {"type": "string", "default": "full"}}
        }

    def test_fetch_message_schema_leaves_missing_format_untouched(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_fetch_message_schema_modifier,
        )

        schema = _make_tool_schema(
            input_parameters={"properties": {"message_id": {"type": "string"}}}
        )
        result = gmail_fetch_message_schema_modifier(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL", schema
        )
        assert result.input_parameters == {
            "properties": {"message_id": {"type": "string"}}
        }

    def test_fetch_message_schema_leaves_non_dict_format_untouched(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_fetch_message_schema_modifier,
        )

        schema = _make_tool_schema(input_parameters={"properties": {"format": "oops"}})
        result = gmail_fetch_message_schema_modifier(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL", schema
        )
        assert result.input_parameters == {"properties": {"format": "oops"}}


# ============================================================================
# 5b. Gmail hooks — contact flattening helpers
# ============================================================================


class TestGmailContactHelpers:
    """Tests for the People API flattening helpers (_primary, _display_name, ...)."""

    def test_primary_returns_none_for_empty_entries(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import _primary

        assert _primary([]) is None

    def test_primary_picks_the_primary_flagged_entry(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonName
        from app.utils.composio_hooks.gmail_hooks import _primary

        names = [
            GooglePersonName(display_name="First"),
            GooglePersonName(display_name="Primary", metadata={"primary": True}),
        ]
        assert _primary(names) is names[1]

    def test_primary_falls_back_to_first_entry_without_flags(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonName
        from app.utils.composio_hooks.gmail_hooks import _primary

        names = [
            GooglePersonName(display_name="First"),
            GooglePersonName(display_name="Second"),
        ]
        assert _primary(names) is names[0]

    def test_primary_ignores_entries_without_primary_metadata(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonName
        from app.utils.composio_hooks.gmail_hooks import _primary

        names = [
            GooglePersonName(display_name="No metadata"),
            GooglePersonName(display_name="Explicit false", metadata={"primary": False}),
            GooglePersonName(display_name="Flagged", metadata={"primary": True}),
        ]
        assert _primary(names) is names[2]

    def test_display_name_returns_unknown_when_missing(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonName
        from app.utils.composio_hooks.gmail_hooks import _display_name

        assert _display_name(None) == "Unknown"
        assert _display_name(GooglePersonName()) == "Unknown"

    def test_display_name_returns_explicit_null_as_none(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonName
        from app.utils.composio_hooks.gmail_hooks import _display_name

        name = GooglePersonName.model_validate({"displayName": None})
        assert _display_name(name) is None

    def test_display_name_returns_value(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonName
        from app.utils.composio_hooks.gmail_hooks import _display_name

        assert _display_name(GooglePersonName(display_name="John Doe")) == "John Doe"

    def test_entry_value_returns_empty_when_missing(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonValue
        from app.utils.composio_hooks.gmail_hooks import _entry_value

        assert _entry_value(None) == ""
        assert _entry_value(GooglePersonValue()) == ""

    def test_entry_value_returns_explicit_null_as_none(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonValue
        from app.utils.composio_hooks.gmail_hooks import _entry_value

        entry = GooglePersonValue.model_validate({"value": None})
        assert _entry_value(entry) is None

    def test_entry_value_returns_value(self) -> None:
        from app.models.composio_schemas.google_people import GooglePersonValue
        from app.utils.composio_hooks.gmail_hooks import _entry_value

        assert _entry_value(GooglePersonValue(value="john@example.com")) == "john@example.com"

    def test_contact_card_flattens_full_person(self) -> None:
        from app.models.composio_schemas.google_people import GooglePerson
        from app.utils.composio_hooks.gmail_hooks import _contact_card

        person = GooglePerson.model_validate(
            {
                "resourceName": "people/c1",
                "names": [{"displayName": "John Doe", "metadata": {"primary": True}}],
                "emailAddresses": [{"value": "john@example.com", "metadata": {"primary": True}}],
                "phoneNumbers": [{"value": "+1234567890", "metadata": {"primary": True}}],
            }
        )
        assert _contact_card(person) == {
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "+1234567890",
            "resource_name": "people/c1",
        }

    def test_contact_card_defaults_when_fields_omitted(self) -> None:
        from app.models.composio_schemas.google_people import GooglePerson
        from app.utils.composio_hooks.gmail_hooks import _contact_card

        assert _contact_card(GooglePerson.model_validate({})) == {
            "name": "Unknown",
            "email": "",
            "phone": "",
            "resource_name": "",
        }

    def test_contact_card_preserves_explicit_nulls(self) -> None:
        from app.models.composio_schemas.google_people import GooglePerson
        from app.utils.composio_hooks.gmail_hooks import _contact_card

        person = GooglePerson.model_validate(
            {
                "resourceName": None,
                "names": [{"displayName": None}],
                "emailAddresses": [{"value": None}],
                "phoneNumbers": [{"value": None}],
            }
        )
        assert _contact_card(person) == {
            "name": None,
            "email": None,
            "phone": None,
            "resource_name": None,
        }

    def test_contact_summary_omits_blank_fields(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import _contact_summary

        assert _contact_summary({"name": "John Doe", "email": "", "phone": None}) == {
            "name": "John Doe"
        }
        assert _contact_summary(
            {"name": "John Doe", "email": "john@example.com", "phone": ""}
        ) == {"name": "John Doe", "email": "john@example.com"}
        assert _contact_summary({"name": "John Doe", "email": "", "phone": "+123"}) == {
            "name": "John Doe",
            "phone": "+123",
        }


# ============================================================================
# 6. Gmail hooks — before execute
# ============================================================================


class TestGmailBeforeHooks:
    """Tests for Gmail before-execute hooks."""

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_maps_to_to_recipient_email(self, mock_writer: MagicMock) -> None:
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
    def test_compose_before_hook_sends_email_sent_data(self, mock_writer: MagicMock) -> None:
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
    def test_compose_before_hook_forward_string_recipients(self, mock_writer: MagicMock) -> None:
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
    def test_send_draft_before_hook_streams_progress(self, mock_writer: MagicMock) -> None:
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
    def test_get_contacts_before_hook_sets_page_size_default(self, mock_writer: MagicMock) -> None:
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

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html")
    @patch("app.utils.composio_hooks.gmail_hooks.log")
    def test_compose_before_hook_normalizes_body_and_streams_exact_payload(
        self, mock_log: MagicMock, mock_normalize: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        mock_normalize.return_value = "<p>Normalized body</p>"
        params = _make_params(
            {
                "recipient_email": "user@example.com",
                "extra_recipients": ["team@example.com"],
                "subject": "Hello",
                "body": "# Hi",
                "thread_id": "thread_1",
                "bcc": ["bcc@example.com"],
                "cc": ["cc@example.com"],
            }
        )
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", params)
        mock_normalize.assert_called_once_with("# Hi")
        assert result == {
            "arguments": {
                "recipient_email": "user@example.com",
                "extra_recipients": ["team@example.com"],
                "subject": "Hello",
                "body": "<p>Normalized body</p>",
                "thread_id": "thread_1",
                "bcc": ["bcc@example.com"],
                "cc": ["cc@example.com"],
                "is_html": True,
            }
        }
        writer.assert_called_once_with(
            {
                "email_sent_data": [
                    {
                        "to": ["user@example.com", "team@example.com"],
                        "subject": "Hello",
                        "body": "<p>Normalized body</p>",
                        "thread_id": "thread_1",
                        "bcc": ["bcc@example.com"],
                        "cc": ["cc@example.com"],
                        "is_html": True,
                    }
                ]
            }
        )
        mock_log.set.assert_called_once_with(gmail_tool="GMAIL_SEND_EMAIL", toolkit="GMAIL")

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html")
    def test_compose_before_hook_normalizes_alternate_body_key(
        self, mock_normalize: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        mock_normalize.side_effect = lambda value: f"<p>{value}</p>"
        params = _make_params(
            {
                "recipient_email": "user@example.com",
                "subject": "Draft",
                "message": "**markdown** body",
            }
        )
        result = gmail_compose_before_hook("GMAIL_CREATE_EMAIL_DRAFT", "GMAIL", params)
        mock_normalize.assert_called_once_with("**markdown** body")
        assert result["arguments"] == {
            "recipient_email": "user@example.com",
            "subject": "Draft",
            "message": "<p>**markdown** body</p>",
            "is_html": True,
        }
        payload = writer.call_args[0][0]
        assert payload["email_compose_data"][0]["body"] == ""

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html")
    def test_compose_before_hook_leaves_non_string_bodies_untouched(
        self, mock_normalize: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params(
            {
                "recipient_email": "user@example.com",
                "subject": "Draft",
                "body": 123,
                "message_body": "",
            }
        )
        result = gmail_compose_before_hook("GMAIL_CREATE_EMAIL_DRAFT", "GMAIL", params)
        mock_normalize.assert_not_called()
        assert result["arguments"]["body"] == 123
        assert result["arguments"]["message_body"] == ""
        assert result["arguments"]["is_html"] is True

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html")
    @patch("app.utils.composio_hooks.gmail_hooks.log")
    def test_compose_before_hook_draft_maps_to_and_streams_exact_payload(
        self, mock_log: MagicMock, mock_normalize: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        mock_normalize.return_value = "<p>Content</p>"
        params = _make_params({"to": "user@example.com", "subject": "Draft", "body": "Content"})
        result = gmail_compose_before_hook("GMAIL_CREATE_EMAIL_DRAFT", "GMAIL", params)
        assert result["arguments"]["recipient_email"] == "user@example.com"
        mock_log.info.assert_called_once()
        assert "Mapped 'to' argument to 'recipient_email'" in mock_log.info.call_args.args[0]
        assert mock_log.info.call_args.kwargs["tool"] == "GMAIL_CREATE_EMAIL_DRAFT"
        writer.assert_called_once_with(
            {
                "email_compose_data": [
                    {
                        "to": ["user@example.com"],
                        "subject": "Draft",
                        "body": "<p>Content</p>",
                        "thread_id": "",
                        "bcc": [],
                        "cc": [],
                        "is_html": True,
                    }
                ]
            }
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html")
    def test_compose_before_hook_reply_does_not_map_to(
        self, mock_normalize: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        mock_normalize.side_effect = lambda value: value
        params = _make_params(
            {"to": "user@example.com", "subject": "Re: Thread", "body": "Reply"}
        )
        result = gmail_compose_before_hook("GMAIL_REPLY_TO_THREAD", "GMAIL", params)
        assert "recipient_email" not in result["arguments"]
        writer.assert_called_once_with(
            {
                "email_sent_data": [
                    {
                        "to": [""],
                        "subject": "Re: Thread",
                        "body": "Reply",
                        "thread_id": "",
                        "bcc": [],
                        "cc": [],
                        "is_html": True,
                    }
                ]
            }
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html")
    def test_compose_before_hook_reply_without_arguments_streams_defaults(
        self, mock_normalize: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params: dict[str, Any] = {"other_key": "x"}
        result = gmail_compose_before_hook("GMAIL_REPLY_TO_THREAD", "GMAIL", params)
        mock_normalize.assert_not_called()
        assert result["arguments"] == {"is_html": True}
        writer.assert_called_once_with(
            {
                "email_sent_data": [
                    {
                        "to": [""],
                        "subject": "",
                        "body": "",
                        "thread_id": "",
                        "bcc": [],
                        "cc": [],
                        "is_html": True,
                    }
                ]
            }
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html")
    def test_compose_before_hook_forward_without_recipients_streams_empty(
        self, mock_normalize: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        mock_normalize.return_value = "<p>Forwarded</p>"
        params = _make_params({"subject": "Fwd: Something", "body": "Forwarded"})
        gmail_compose_before_hook("GMAIL_FORWARD_MESSAGE", "GMAIL", params)
        writer.assert_called_once_with(
            {
                "email_sent_data": [
                    {
                        "to": [],
                        "subject": "Fwd: Something",
                        "body": "<p>Forwarded</p>",
                        "thread_id": "",
                        "bcc": [],
                        "cc": [],
                        "is_html": True,
                    }
                ]
            }
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.log")
    def test_compose_before_hook_validation_skip_logs_exact_warnings(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()

        no_recipient = _make_params({"subject": "Hi", "body": "Hello"})
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", no_recipient)
        assert result is no_recipient

        no_content = _make_params({"recipient_email": "user@example.com"})
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", no_content)
        assert result is no_content

        assert [call.kwargs for call in mock_log.warning.call_args_list] == [
            {"tool_name": "GMAIL_SEND_EMAIL", "has_recipient": False, "has_content": True},
            {"tool_name": "GMAIL_SEND_EMAIL", "has_recipient": True, "has_content": False},
        ]
        mock_writer.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.normalize_email_body_to_html")
    @patch("app.utils.composio_hooks.gmail_hooks.log")
    def test_compose_before_hook_error_logs_and_returns_params(
        self, mock_log: MagicMock, mock_normalize: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_compose_before_hook

        mock_writer.return_value = _noop_writer()
        mock_normalize.side_effect = ValueError("bad body")
        params = _make_params(
            {"recipient_email": "user@example.com", "subject": "Hi", "body": "Hello"}
        )
        result = gmail_compose_before_hook("GMAIL_SEND_EMAIL", "GMAIL", params)
        assert result is params
        _assert_logged_error(
            mock_log, "Error in gmail_compose_before_hook", "bad body", "ValueError"
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_before_hook_streams_exact_payload(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"draft_id": "d123"})
        result = gmail_send_draft_before_hook("GMAIL_SEND_DRAFT", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Sending draft..."})

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_before_hook_no_writer_no_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_before_hook

        mock_writer.return_value = None
        params = _make_params()
        result = gmail_send_draft_before_hook("GMAIL_SEND_DRAFT", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_trash_before_hook_streams_exact_payloads(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_trash_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params()
        result = gmail_trash_before_hook("GMAIL_TRASH_MESSAGE", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Moving to trash..."})

        writer.reset_mock()
        result = gmail_trash_before_hook("GMAIL_UNTRASH_MESSAGE", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Restoring from trash..."})

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_trash_before_hook_no_writer_no_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_trash_before_hook

        mock_writer.return_value = None
        params = _make_params()
        result = gmail_trash_before_hook("GMAIL_TRASH_MESSAGE", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_label_before_hook_streams_exact_payloads(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"name": "Important"})
        result = gmail_label_before_hook("GMAIL_CREATE_LABEL", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Creating label: Important..."})

        writer.reset_mock()
        params = _make_params({})
        result = gmail_label_before_hook("GMAIL_CREATE_LABEL", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Creating label: ..."})

        writer.reset_mock()
        result = gmail_label_before_hook("GMAIL_UPDATE_LABEL", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Updating label..."})

        writer.reset_mock()
        result = gmail_label_before_hook("GMAIL_DELETE_LABEL", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Deleting label..."})

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_label_before_hook_unknown_tool_does_not_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"name": "X"})
        result = gmail_label_before_hook("GMAIL_OTHER", "GMAIL", params)
        assert result is params
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_label_before_hook_no_writer_no_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_label_before_hook

        mock_writer.return_value = None
        params = _make_params({"name": "X"})
        result = gmail_label_before_hook("GMAIL_CREATE_LABEL", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_modify_labels_before_hook_streams_exact_payloads(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"message_ids": ["m1", "m2"], "label_ids": ["STARRED"]})
        result = gmail_modify_labels_before_hook("GMAIL_ADD_LABEL_TO_EMAIL", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with(
            {"progress": "Adding labels to 2 message(s) with 1 label(s)..."}
        )

        writer.reset_mock()
        params = _make_params({"message_ids": ["m1"], "label_ids": ["A", "B"]})
        result = gmail_modify_labels_before_hook("GMAIL_REMOVE_LABEL", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with(
            {"progress": "Removing labels from 1 message(s) with 2 label(s)..."}
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_modify_labels_before_hook_non_list_args_count_as_one(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"message_ids": "m1", "label_ids": "STARRED"})
        gmail_modify_labels_before_hook("GMAIL_ADD_LABEL_TO_EMAIL", "GMAIL", params)
        writer.assert_called_once_with(
            {"progress": "Adding labels to 1 message(s) with 1 label(s)..."}
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_modify_labels_before_hook_no_writer_no_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        mock_writer.return_value = None
        params = _make_params({"message_ids": ["m1"]})
        result = gmail_modify_labels_before_hook("GMAIL_ADD_LABEL_TO_EMAIL", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_draft_management_before_hook_streams_exact_payloads(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_draft_management_before_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params()
        result = gmail_draft_management_before_hook("GMAIL_UPDATE_DRAFT", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Updating draft..."})

        writer.reset_mock()
        result = gmail_draft_management_before_hook("GMAIL_DELETE_DRAFT", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Deleting draft..."})

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_draft_management_before_hook_no_writer_no_stream(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_draft_management_before_hook,
        )

        mock_writer.return_value = None
        params = _make_params()
        result = gmail_draft_management_before_hook("GMAIL_UPDATE_DRAFT", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_list_drafts_before_hook_streams_exact_payloads(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_list_drafts_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"max_results": 15})
        result = gmail_list_drafts_before_hook("GMAIL_LIST_DRAFTS", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Fetching drafts (max 15 results)..."})

        writer.reset_mock()
        params = _make_params({})
        result = gmail_list_drafts_before_hook("GMAIL_LIST_DRAFTS", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Fetching drafts (max 20 results)..."})

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_list_drafts_before_hook_no_writer_no_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_list_drafts_before_hook

        mock_writer.return_value = None
        params = _make_params({})
        result = gmail_list_drafts_before_hook("GMAIL_LIST_DRAFTS", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_draft_before_hook_streams_exact_payload(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_draft_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"draft_id": "d1"})
        result = gmail_get_draft_before_hook("GMAIL_GET_DRAFT", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Fetching draft details..."})

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_draft_before_hook_no_writer_no_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_draft_before_hook

        mock_writer.return_value = None
        params = _make_params()
        result = gmail_get_draft_before_hook("GMAIL_GET_DRAFT", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_before_hook_streams_exact_payload(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"page_size": 100})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "GMAIL", params)
        assert result["arguments"] == {"page_size": 100}
        writer.assert_called_once_with({"progress": "Fetching contacts..."})

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_before_hook_falsy_page_size_uses_default(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        mock_writer.return_value = _noop_writer()
        params = _make_params({"page_size": 0})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "GMAIL", params)
        assert result["arguments"] == {"page_size": 50}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_before_hook_no_writer_still_sets_page_size(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        mock_writer.return_value = None
        params = _make_params({})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "GMAIL", params)
        assert result["arguments"] == {"page_size": 50}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_before_hook_without_arguments_creates_them(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params: dict[str, Any] = {"custom": "x"}
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "GMAIL", params)
        assert result["arguments"] == {"page_size": 50}
        writer.assert_called_once_with({"progress": "Fetching contacts..."})

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_before_hook_streams_exact_payload(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"query": "John Doe"})
        result = gmail_search_people_before_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", params)
        assert result is params
        writer.assert_called_once_with(
            {"progress": "Searching for people matching 'John Doe'..."}
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_before_hook_default_query(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        gmail_search_people_before_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", params)
        writer.assert_called_once_with({"progress": "Searching for people matching ''..."})

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_before_hook_no_writer_no_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_before_hook

        mock_writer.return_value = None
        params = _make_params({"query": "John"})
        result = gmail_search_people_before_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", params)
        assert result is params


# ============================================================================
# 7. Gmail hooks — after execute
# ============================================================================


class TestGmailAfterHooks:
    """Tests for Gmail after-execute hooks."""

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
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response)
        assert result["id"] == "thread1"
        writer.assert_called_once()
        payload = writer.call_args[0][0]
        assert "email_thread_data" in payload
        assert payload["email_thread_data"]["thread_id"] == "thread1"

    def test_thread_after_hook_error_response(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        response = _make_response({"error": "Not found"})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response)
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
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "GMAIL", response)
        assert result["attachmentId"] == "att1"
        assert result["filename"] == "report.pdf"
        assert result["size"] == 1024
        assert "data" not in result
        assert "message" in result

    def test_attachment_after_hook_unsuccessful(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response = _make_response({"error": "Not found"}, successful=False)
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "GMAIL", response)
        assert result == {"error": "Not found"}

    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_fetch_by_id_after_hook(self, mock_template: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_by_id_after_hook

        mock_template.return_value = {"id": "m1", "subject": "Test"}
        response = _make_response({"id": "m1", "payload": {}})
        result = gmail_fetch_by_id_after_hook("GMAIL_FETCH_EMAIL_BY_ID", "GMAIL", response)
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
    def test_get_contacts_after_hook_processes_contacts(self, mock_writer: MagicMock) -> None:
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
    def test_get_contacts_after_hook_missing_fields(self, mock_writer: MagicMock) -> None:
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
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", response)
        assert result["people"][0]["name"] == "Jane Doe"
        assert result["result_count"] == 1
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_message_detail_after_hook_returns_template_exactly(
        self, mock_template: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_message_detail_after_hook

        processed = {"id": "m1", "from": "a@b.com", "body": "text"}
        mock_template.return_value = processed
        response = _make_response({"id": "m1", "raw": True})
        result = gmail_message_detail_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL", response
        )
        assert result == processed
        mock_template.assert_called_once_with(response["data"])

    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_message_detail_after_hook_error_skips_template(
        self, mock_template: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_message_detail_after_hook

        response = _make_response({"error": "Not found"})
        result = gmail_message_detail_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL", response
        )
        assert result == {"error": "Not found"}
        mock_template.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.log")
    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_message_detail_after_hook_template_error_logs_and_returns_raw(
        self, mock_template: MagicMock, mock_log: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_message_detail_after_hook

        mock_template.side_effect = KeyError("bad key")
        response = _make_response({"raw": "data"})
        result = gmail_message_detail_after_hook(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL", response
        )
        assert result == {"raw": "data"}
        _assert_logged_error(
            mock_log, "Error in gmail_message_detail_after_hook", "'bad key'", "KeyError"
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_get_thread_response")
    def test_thread_after_hook_streams_exact_payload(
        self, mock_process: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        processed = {
            "id": "thread1",
            "messages": [
                {
                    "id": "m1",
                    "from": "a@b.com",
                    "subject": "Thread",
                    "time": "12:00",
                    "snippet": "snip",
                    "body": "body",
                    "content": "content",
                },
                {"extra_only": True},
            ],
            "messageCount": 2,
        }
        mock_process.return_value = processed
        response = _make_response({"id": "raw_thread"})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response)
        assert result == processed
        mock_process.assert_called_once_with(response["data"])
        writer.assert_called_once_with(
            {
                "email_thread_data": {
                    "thread_id": "thread1",
                    "messages": [
                        {
                            "id": "m1",
                            "from": "a@b.com",
                            "subject": "Thread",
                            "time": "12:00",
                            "snippet": "snip",
                            "body": "body",
                            "content": "content",
                        },
                        {
                            "id": "",
                            "from": "",
                            "subject": "",
                            "time": "",
                            "snippet": "",
                            "body": "",
                            "content": "",
                        },
                    ],
                    "messages_count": 2,
                }
            }
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_get_thread_response")
    def test_thread_after_hook_missing_message_count_defaults_to_zero(
        self, mock_process: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        mock_process.return_value = {"id": "t1", "messages": [{"id": "m1"}]}
        response = _make_response({"id": "raw"})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response)
        assert result == {"id": "t1", "messages": [{"id": "m1"}]}
        payload = writer.call_args[0][0]
        assert payload["email_thread_data"] == {
            "thread_id": "t1",
            "messages": [
                {
                    "id": "m1",
                    "from": "",
                    "subject": "",
                    "time": "",
                    "snippet": "",
                    "body": "",
                    "content": "",
                }
            ],
            "messages_count": 0,
        }

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_get_thread_response")
    def test_thread_after_hook_no_messages_no_stream(
        self, mock_process: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        processed = {"id": "t1", "messages": [], "messageCount": 0}
        mock_process.return_value = processed
        response = _make_response({"id": "raw"})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response)
        assert result == processed
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_get_thread_response")
    def test_thread_after_hook_no_writer_still_returns_processed(
        self, mock_process: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        mock_writer.return_value = None
        processed = {"id": "t1", "messages": [{"id": "m1"}], "messageCount": 1}
        mock_process.return_value = processed
        response = _make_response({"id": "raw"})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response)
        assert result == processed

    @patch("app.utils.composio_hooks.gmail_hooks.process_get_thread_response")
    def test_thread_after_hook_error_skips_processor(self, mock_process: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        response = _make_response({"error": "Not found"})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response)
        assert result == {"error": "Not found"}
        mock_process.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.log")
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.gmail_hooks.process_get_thread_response")
    def test_thread_after_hook_processor_error_logs_and_returns_raw(
        self, mock_process: MagicMock, mock_writer: MagicMock, mock_log: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_thread_after_hook

        mock_writer.return_value = _noop_writer()
        mock_process.side_effect = ValueError("bad thread")
        response = _make_response({"raw": "thread"})
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response)
        assert result == {"raw": "thread"}
        _assert_logged_error(
            mock_log, "Error in gmail_thread_after_hook", "bad thread", "ValueError"
        )

    @patch("app.utils.composio_hooks.gmail_hooks.process_list_drafts_response")
    def test_drafts_after_hook_returns_processor_output_exactly(
        self, mock_process: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_drafts_after_hook

        processed = {"drafts": [{"id": "d1"}], "resultSize": 1}
        mock_process.return_value = processed
        response = _make_response({"drafts": [{"id": "d1"}]})
        result = gmail_drafts_after_hook("GMAIL_LIST_DRAFTS", "GMAIL", response)
        assert result == processed
        mock_process.assert_called_once_with(response["data"])

    @patch("app.utils.composio_hooks.gmail_hooks.process_list_drafts_response")
    def test_drafts_after_hook_error_skips_processor(self, mock_process: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_drafts_after_hook

        response = _make_response({"error": "Not found"})
        result = gmail_drafts_after_hook("GMAIL_LIST_DRAFTS", "GMAIL", response)
        assert result == {"error": "Not found"}
        mock_process.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.log")
    @patch("app.utils.composio_hooks.gmail_hooks.process_list_drafts_response")
    def test_drafts_after_hook_processor_error_logs_and_returns_raw(
        self, mock_process: MagicMock, mock_log: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_drafts_after_hook

        mock_process.side_effect = ValueError("bad drafts")
        response = _make_response({"raw": "drafts"})
        result = gmail_drafts_after_hook("GMAIL_LIST_DRAFTS", "GMAIL", response)
        assert result == {"raw": "drafts"}
        _assert_logged_error(
            mock_log, "Error in gmail_drafts_after_hook", "bad drafts", "ValueError"
        )

    @patch("app.utils.composio_hooks.gmail_hooks.draft_template")
    def test_draft_detail_after_hook_returns_template_exactly(
        self, mock_template: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_detail_after_hook

        processed = {"id": "d1", "message": {"to": "a@b.com"}}
        mock_template.return_value = processed
        response = _make_response({"id": "raw"})
        result = gmail_draft_detail_after_hook("GMAIL_GET_DRAFT", "GMAIL", response)
        assert result == processed
        mock_template.assert_called_once_with(response["data"])

    @patch("app.utils.composio_hooks.gmail_hooks.draft_template")
    def test_draft_detail_after_hook_error_skips_template(
        self, mock_template: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_detail_after_hook

        response = _make_response({"error": "Not found"})
        result = gmail_draft_detail_after_hook("GMAIL_GET_DRAFT", "GMAIL", response)
        assert result == {"error": "Not found"}
        mock_template.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.log")
    @patch("app.utils.composio_hooks.gmail_hooks.draft_template")
    def test_draft_detail_after_hook_template_error_logs_and_returns_raw(
        self, mock_template: MagicMock, mock_log: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_draft_detail_after_hook

        mock_template.side_effect = RuntimeError("parse fail")
        response = _make_response({"raw": "draft"})
        result = gmail_draft_detail_after_hook("GMAIL_GET_DRAFT", "GMAIL", response)
        assert result == {"raw": "draft"}
        _assert_logged_error(
            mock_log, "Error in gmail_draft_detail_after_hook", "parse fail", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_fetch_by_id_after_hook_returns_template_exactly(
        self, mock_template: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_by_id_after_hook

        processed = {"id": "m1", "subject": "Test"}
        mock_template.return_value = processed
        response = _make_response({"id": "raw"})
        result = gmail_fetch_by_id_after_hook("GMAIL_FETCH_EMAIL_BY_ID", "GMAIL", response)
        assert result == processed
        mock_template.assert_called_once_with(response["data"])

    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_fetch_by_id_after_hook_error_skips_template(
        self, mock_template: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_by_id_after_hook

        response = _make_response({"error": "Not found"})
        result = gmail_fetch_by_id_after_hook("GMAIL_FETCH_EMAIL_BY_ID", "GMAIL", response)
        assert result == {"error": "Not found"}
        mock_template.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.log")
    @patch("app.utils.composio_hooks.gmail_hooks.detailed_message_template")
    def test_fetch_by_id_after_hook_template_error_logs_and_returns_raw(
        self, mock_template: MagicMock, mock_log: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_fetch_by_id_after_hook

        mock_template.side_effect = KeyError("bad key")
        response = _make_response({"raw": "email"})
        result = gmail_fetch_by_id_after_hook("GMAIL_FETCH_EMAIL_BY_ID", "GMAIL", response)
        assert result == {"raw": "email"}
        _assert_logged_error(
            mock_log, "Error in gmail_fetch_by_id_after_hook", "'bad key'", "KeyError"
        )

    def test_attachment_after_hook_returns_exact_metadata(self) -> None:
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
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "GMAIL", response)
        assert result == {
            "attachmentId": "att1",
            "filename": "report.pdf",
            "mimeType": "application/pdf",
            "size": 1024,
            "message": "Attachment content available but not displayed to preserve context",
        }

    def test_attachment_after_hook_defaults_missing_keys(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response = _make_response({}, successful=True)
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "GMAIL", response)
        assert result == {
            "attachmentId": "",
            "filename": "",
            "mimeType": "",
            "size": 0,
            "message": "Attachment content available but not displayed to preserve context",
        }

    def test_attachment_after_hook_unsuccessful_returns_data_unchanged(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        data = {"error": "Not found"}
        response = _make_response(data, successful=False)
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "GMAIL", response)
        assert result is data

    def test_attachment_after_hook_non_dict_data_passthrough(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response = _make_response("plain string", successful=True)
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "GMAIL", response)
        assert result == "plain string"

    @patch("app.utils.composio_hooks.gmail_hooks.log")
    def test_attachment_after_hook_missing_data_key_propagates_key_error(
        self, mock_log: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response: dict[str, Any] = {"successful": True}
        with pytest.raises(KeyError):
            gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "GMAIL", response)
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["error_type"] == "KeyError"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_after_hook_streams_exact_payload_and_minimal_return(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "successful": True,
                "id": "sent_1",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"to": ["a@b.com", "c@d.com"], "subject": "Sent draft"},
            }
        )
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "GMAIL", response)
        assert result == {
            "id": "sent_1",
            "successful": True,
            "message": "Draft sent successfully",
        }
        writer.assert_called_once_with(
            {
                "email_sent_data": [
                    {
                        "message_id": "sent_1",
                        "message": "Draft sent successfully!",
                        "timestamp": "2024-01-01T00:00:00Z",
                        "recipients": ["a@b.com", "c@d.com"],
                        "subject": "Sent draft",
                    }
                ]
            }
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_after_hook_defaults_missing_fields(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"successful": True})
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "GMAIL", response)
        assert result == {"id": "", "successful": True, "message": "Draft sent successfully"}
        writer.assert_called_once_with(
            {
                "email_sent_data": [
                    {
                        "message_id": "",
                        "message": "Draft sent successfully!",
                        "timestamp": "",
                        "recipients": [],
                        "subject": "",
                    }
                ]
            }
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_after_hook_without_successful_key_streams_but_returns_raw(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        data = {"id": "x", "message": {"to": ["a@b.com"]}}
        response = _make_response(data)
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "GMAIL", response)
        assert result == data
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_after_hook_no_writer_returns_minimal(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        mock_writer.return_value = None
        response = _make_response({"successful": True, "id": "sent_1"})
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "GMAIL", response)
        assert result == {
            "id": "sent_1",
            "successful": True,
            "message": "Draft sent successfully",
        }

    @patch("app.utils.composio_hooks.gmail_hooks.log")
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_after_hook_writer_error_logs_and_returns_raw(
        self, mock_writer: MagicMock, mock_log: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        writer = _noop_writer()
        writer.side_effect = RuntimeError("no stream")
        mock_writer.return_value = writer
        data = {"successful": True, "id": "x"}
        response = _make_response(data)
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "GMAIL", response)
        assert result == data
        _assert_logged_error(
            mock_log, "Error in gmail_send_draft_after_hook", "no stream", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_after_hook_streams_exact_payload_and_return(
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
                                {"displayName": "John Doe", "metadata": {"primary": True}}
                            ],
                            "emailAddresses": [
                                {"value": "john@example.com", "metadata": {"primary": True}}
                            ],
                            "phoneNumbers": [
                                {"value": "+1234567890", "metadata": {"primary": True}}
                            ],
                        },
                        {
                            "resourceName": "people/c2",
                            "names": [],
                            "emailAddresses": [],
                            "phoneNumbers": [],
                        },
                    ]
                },
                "totalPeople": 3,
                "nextPageToken": "tok_1",
            }
        )
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "GMAIL", response)
        assert result == {
            "contacts": [
                {"name": "John Doe", "email": "john@example.com", "phone": "+1234567890"},
                {"name": "Unknown"},
            ],
            "total_count": 3,
            "has_more": True,
        }
        writer.assert_called_once_with(
            {
                "contacts_data": [
                    {
                        "name": "John Doe",
                        "email": "john@example.com",
                        "phone": "+1234567890",
                        "resource_name": "people/c1",
                    },
                    {"name": "Unknown", "email": "", "phone": "", "resource_name": "people/c2"},
                ],
                "total_count": 3,
                "next_page_token": "tok_1",
            }
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_after_hook_missing_totals_use_defaults(
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
                            "names": [
                                {"displayName": "Ada", "metadata": {"primary": True}}
                            ]
                        }
                    ]
                }
            }
        )
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "GMAIL", response)
        assert result == {"contacts": [{"name": "Ada"}], "total_count": 1, "has_more": False}
        payload = writer.call_args[0][0]
        assert payload["total_count"] == 1
        assert payload["next_page_token"] is None

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_after_hook_no_connections_no_stream(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"response_data": {"connections": []}})
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "GMAIL", response)
        assert result == {"contacts": [], "total_count": 0, "has_more": False}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_after_hook_error_returns_raw(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"error": "Not found"})
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "GMAIL", response)
        assert result == {"error": "Not found"}

    @patch("app.utils.composio_hooks.gmail_hooks.log")
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_after_hook_invalid_response_data_logs_and_returns_raw(
        self, mock_writer: MagicMock, mock_log: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"response_data": "not a dict"})
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "GMAIL", response)
        assert result == response["data"]
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["error_type"] == "ValidationError"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_after_hook_streams_exact_payload_and_return(
        self, mock_writer: MagicMock
    ) -> None:
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
                                    {"displayName": "Jane Doe", "metadata": {"primary": True}}
                                ],
                                "emailAddresses": [
                                    {"value": "jane@example.com", "metadata": {"primary": True}}
                                ],
                                "phoneNumbers": [],
                            }
                        }
                    ]
                }
            }
        )
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", response)
        assert result == {
            "people": [{"name": "Jane Doe", "email": "jane@example.com"}],
            "result_count": 1,
        }
        writer.assert_called_once_with(
            {
                "people_search_data": [
                    {
                        "name": "Jane Doe",
                        "email": "jane@example.com",
                        "phone": "",
                        "resource_name": "people/c1",
                    }
                ],
                "result_count": 1,
            }
        )

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_after_hook_no_results_no_stream(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"response_data": {"results": []}})
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", response)
        assert result == {"people": [], "result_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.gmail_hooks.log")
    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_after_hook_invalid_response_data_logs_and_returns_raw(
        self, mock_writer: MagicMock, mock_log: MagicMock
    ) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"response_data": "not a dict"})
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", response)
        assert result == response["data"]
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["error_type"] == "ValidationError"


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

# ---------------------------------------------------------------------------
# Twitter test data — exact expected values for hook outputs
# ---------------------------------------------------------------------------

_TWITTER_SEARCH_TIPS = (
    "\n\n📝 X SEARCH SYNTAX (use in 'query' parameter):\n"
    "• from:username - tweets from specific user\n"
    "• to:username - tweets replying to user\n"
    "• @username - tweets mentioning user\n"
    "• #hashtag - tweets with specific hashtag\n"
    '• "exact phrase" - exact phrase match\n'
    "• -keyword - exclude keyword\n"
    "• is:retweet / -is:retweet - include/exclude retweets\n"
    "• is:reply / -is:reply - include/exclude replies\n"
    "• has:media / has:images / has:videos - filter by media\n"
    "• has:links - tweets with links\n"
    "• lang:en - filter by language\n"
    "• min_retweets:10 / min_faves:50 - engagement filters\n"
    "• since:2024-01-01 until:2024-12-31 - date range\n\n"
    "Example: 'from:elonmusk -is:retweet -is:reply' for original tweets only"
)

_TWITTER_FOLLOW_GUIDANCE = (
    "\n\n💡 USER DISCOVERY TIP: If the user doesn't provide a username:\n"
    "1. Use TWITTER_RECENT_SEARCH with the person's name to find their tweets\n"
    "2. Extract the author's user_id from search results\n"
    "3. Present matching users to the user for selection\n"
    "4. Then use this tool with the selected target_user_id"
)

_TWITTER_POSTING_TIPS = (
    "\n\n📱 POSTING TIPS:\n"
    "• For media: Upload first with TWITTER_UPLOAD_MEDIA, then use media_media_ids\n"
    "• For threads: Create first tweet, then reply with reply_in_reply_to_tweet_id\n"
    "• For quotes: Use quote_tweet_id to quote another tweet\n"
    "• Use polls: Provide poll_options (2-4 options) and poll_duration_minutes"
)


def _twitter_user(**overrides: Any) -> dict[str, Any]:
    """Full Twitter ``includes.users`` entry (every field present, truthy flags)."""
    return {
        "id": "u1",
        "username": "testuser",
        "name": "Test User",
        "description": "Bio",
        "profile_image_url": "https://img.com/pic.jpg",
        "verified": True,
        "public_metrics": {"followers_count": 100, "following_count": 10},
        **overrides,
    }


def _twitter_tweet(**overrides: Any) -> dict[str, Any]:
    """Full Twitter search ``data`` entry (every field present)."""
    return {
        "id": "tw1",
        "text": "Hello world",
        "created_at": "2024-01-01T00:00:00Z",
        "author_id": "u1",
        "public_metrics": {"like_count": 10, "retweet_count": 5},
        "conversation_id": "conv1",
        **overrides,
    }


def _twitter_search_response(**overrides: Any) -> dict[str, Any]:
    """TWITTER_RECENT_SEARCH response with one tweet by a known author."""
    return _make_response(
        {
            "data": [_twitter_tweet()],
            "includes": {"users": [_twitter_user()]},
            "meta": {"result_count": 1, "next_token": "tok123"},
            **overrides,
        }
    )


def _twitter_processed_tweet(**overrides: Any) -> dict[str, Any]:
    """Expected frontend tweet dict for the search after-hook stream payload."""
    return {
        "id": "tw1",
        "text": "Hello world",
        "created_at": "2024-01-01T00:00:00Z",
        "author": {
            "id": "u1",
            "username": "testuser",
            "name": "Test User",
            "profile_image_url": "https://img.com/pic.jpg",
            "verified": True,
            "description": "Bio",
            "public_metrics": {"followers_count": 100, "following_count": 10},
        },
        "public_metrics": {"like_count": 10, "retweet_count": 5},
        "conversation_id": "conv1",
        **overrides,
    }


class TestTwitterSchemaModifiers:
    """Tests for Twitter schema modifier hooks."""

    def test_twitter_search_schema_adds_tips(self) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_search_schema_modifier,
        )

        schema = _make_tool_schema()
        result = twitter_search_schema_modifier("TWITTER_RECENT_SEARCH", "TWITTER", schema)
        assert result is schema
        assert result.description == "Original description" + _TWITTER_SEARCH_TIPS

    def test_twitter_follow_schema_adds_guidance(self) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_follow_schema_modifier,
        )

        schema = _make_tool_schema()
        result = twitter_follow_schema_modifier("TWITTER_FOLLOW_USER", "TWITTER", schema)
        assert result is schema
        assert result.description == "Original description" + _TWITTER_FOLLOW_GUIDANCE

    def test_twitter_create_post_schema_adds_tips(self) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_create_post_schema_modifier,
        )

        schema = _make_tool_schema()
        result = twitter_create_post_schema_modifier(
            "TWITTER_CREATION_OF_A_POST", "TWITTER", schema
        )
        assert result is schema
        assert result.description == "Original description" + _TWITTER_POSTING_TIPS

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
        assert result is schema
        assert result.input_parameters["properties"]["max_results"]["default"] == 20

    def test_twitter_timeline_schema_max_results_not_dict_unchanged(self) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_timeline_schema_modifier,
        )

        schema = _make_tool_schema(
            input_parameters={"properties": {"max_results": "not_a_dict"}}
        )
        result = twitter_timeline_schema_modifier(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", schema
        )
        assert result is schema
        assert result.input_parameters["properties"]["max_results"] == "not_a_dict"

    def test_twitter_timeline_schema_no_properties_unchanged(self) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_timeline_schema_modifier,
        )

        schema = _make_tool_schema(input_parameters={"required": []})
        result = twitter_timeline_schema_modifier(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", schema
        )
        assert result is schema

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
    def test_create_post_before_hook_streams_preview(self, mock_writer: MagicMock) -> None:
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
        result = twitter_create_post_before_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", params)
        assert result is params
        writer.assert_called_once_with(
            {
                "twitter_post_preview": {
                    "text": "Hello Twitter!",
                    "quote_tweet_id": "qt123",
                    "reply_to_tweet_id": "rt456",
                    "media_ids": ["media1"],
                    "poll_options": ["Yes", "No"],
                }
            }
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_create_post_before_hook_no_writer(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_create_post_before_hook,
        )

        mock_writer.return_value = None
        params = _make_params({"text": "Hello"})
        result = twitter_create_post_before_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", params)
        assert result is params
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_create_post_before_hook_defaults_for_missing_arguments(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_create_post_before_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"text": "Just text"})
        twitter_create_post_before_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", params)
        writer.assert_called_once_with(
            {
                "twitter_post_preview": {
                    "text": "Just text",
                    "quote_tweet_id": None,
                    "reply_to_tweet_id": None,
                    "media_ids": [],
                    "poll_options": [],
                }
            }
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_create_post_before_hook_without_arguments_key_streams_defaults(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_create_post_before_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        params: dict[str, Any] = {"tool_used": "x"}
        result = twitter_create_post_before_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", params)
        assert result is params
        writer.assert_called_once_with(
            {
                "twitter_post_preview": {
                    "text": "",
                    "quote_tweet_id": None,
                    "reply_to_tweet_id": None,
                    "media_ids": [],
                    "poll_options": [],
                }
            }
        )
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_before_hook_streams_progress(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"query": "AI news"})
        twitter_search_before_hook("TWITTER_RECENT_SEARCH", "TWITTER", params)
        writer.assert_called_once_with({"progress": "Searching tweets for: AI news..."})

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_before_hook_missing_query(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        twitter_search_before_hook("TWITTER_FULL_ARCHIVE_SEARCH", "TWITTER", params)
        writer.assert_called_once_with({"progress": "Searching tweets for: ..."})

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_search_before_hook_without_arguments_key_streams_defaults(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_before_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        params: dict[str, Any] = {"tool_used": "x"}
        result = twitter_search_before_hook("TWITTER_RECENT_SEARCH", "TWITTER", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Searching tweets for: ..."})
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_search_before_hook_no_writer_does_not_log(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_before_hook

        mock_writer.return_value = None
        params = _make_params({"query": "x"})
        result = twitter_search_before_hook("TWITTER_RECENT_SEARCH", "TWITTER", params)
        assert result is params
        mock_log.error.assert_not_called()


# ============================================================================
# 11. Twitter hooks — after execute
# ============================================================================


class TestTwitterAfterHooks:
    """Tests for Twitter after-execute hooks."""

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_search_after_hook_processes_tweets(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _twitter_search_response()
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result == {
            "tweets": [
                {
                    "id": "tw1",
                    "text": "Hello world",
                    "author_username": "testuser",
                    "author_name": "Test User",
                    "likes": 10,
                    "retweets": 5,
                }
            ],
            "result_count": 1,
            "has_more": True,
        }
        writer.assert_called_once_with(
            {
                "twitter_search_data": {
                    "tweets": [_twitter_processed_tweet()],
                    "result_count": 1,
                    "next_token": "tok123",
                }
            }
        )
        mock_log.set.assert_called_once_with(
            twitter_tool="TWITTER_RECENT_SEARCH", toolkit="TWITTER"
        )
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_search_after_hook_error_response(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Rate limited"})
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result == {"error": "Rate limited"}
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_search_after_hook_empty_response_logs_key_error(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {}
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result == {}
        _assert_logged_error(
            mock_log, "Error in twitter_search_after_hook", "'data'", "KeyError"
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_no_writer_returns_processed(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        mock_writer.return_value = None
        result = twitter_search_after_hook(
            "TWITTER_RECENT_SEARCH", "TWITTER", _twitter_search_response()
        )
        assert result == {
            "tweets": [
                {
                    "id": "tw1",
                    "text": "Hello world",
                    "author_username": "testuser",
                    "author_name": "Test User",
                    "likes": 10,
                    "retweets": 5,
                }
            ],
            "result_count": 1,
            "has_more": True,
        }

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_empty_tweets_does_not_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _twitter_search_response(data=[], includes={"users": []})
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result == {"tweets": [], "result_count": 1, "has_more": True}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_missing_meta_falls_back_to_count(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response(
            {
                "data": [_twitter_tweet(id="tw1"), _twitter_tweet(id="tw2", text="Two")],
                "includes": {"users": []},
            }
        )
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result["result_count"] == 2
        assert result["has_more"] is False
        assert len(result["tweets"]) == 2

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_unknown_author_fallback(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _twitter_search_response(data=[_twitter_tweet(author_id="ghost")])
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result["tweets"][0]["author_username"] == "unknown"
        assert result["tweets"][0]["author_name"] == "Unknown"
        payload = writer.call_args[0][0]
        assert payload["twitter_search_data"]["tweets"][0]["author"] == {
            "username": "unknown",
            "name": "Unknown",
        }

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_sparse_user_defaults(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _twitter_search_response(
            includes={"users": [{"id": "u1", "username": "min", "name": "Min"}]}
        )
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result["tweets"][0]["author_username"] == "min"
        payload = writer.call_args[0][0]
        assert payload["twitter_search_data"]["tweets"][0]["author"] == {
            "id": "u1",
            "username": "min",
            "name": "Min",
            "profile_image_url": None,
            "verified": False,
            "description": "",
            "public_metrics": {},
        }

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_truncates_long_tweets(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        mock_writer.return_value = _noop_writer()
        response = _twitter_search_response(data=[_twitter_tweet(text="x" * 201)])
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result["tweets"][0]["text"] == "x" * 200 + "..."

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_keeps_200_char_tweets(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        mock_writer.return_value = _noop_writer()
        response = _twitter_search_response(data=[_twitter_tweet(text="x" * 200)])
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result["tweets"][0]["text"] == "x" * 200

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_llm_tweets_capped_at_10(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        mock_writer.return_value = _noop_writer()
        tweets = [_twitter_tweet(id=f"tw{i}", text=f"tweet {i}") for i in range(11)]
        response = _twitter_search_response(data=tweets, meta={"result_count": 11})
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert len(result["tweets"]) == 10
        assert result["tweets"][0]["id"] == "tw0"
        assert result["tweets"][9]["id"] == "tw9"
        assert result["result_count"] == 11

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_search_after_hook_missing_data_key_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {"successful": True}
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result == {"tweets": [], "result_count": 0, "has_more": False}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_uses_meta_result_count(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _twitter_search_response(
            data=[_twitter_tweet(id="tw1"), _twitter_tweet(id="tw2", text="Two")],
            meta={"result_count": 5},
        )
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result["result_count"] == 5
        assert len(result["tweets"]) == 2
        payload = writer.call_args[0][0]
        assert payload["twitter_search_data"]["result_count"] == 5

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_meta_without_result_count_falls_back(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _twitter_search_response(
            data=[_twitter_tweet(id="tw1"), _twitter_tweet(id="tw2", text="Two")],
            meta={"next_token": "tok"},
        )
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result["result_count"] == 2
        assert result["has_more"] is True
        payload = writer.call_args[0][0]
        assert payload["twitter_search_data"]["result_count"] == 2

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_search_after_hook_sparse_tweet_defaults(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _twitter_search_response(
            data=[{"id": "tw1", "text": "Sparse", "author_id": "ghost"}],
            includes={"users": []},
        )
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result == {
            "tweets": [
                {
                    "id": "tw1",
                    "text": "Sparse",
                    "author_username": "unknown",
                    "author_name": "Unknown",
                    "likes": 0,
                    "retweets": 0,
                }
            ],
            "result_count": 1,
            "has_more": True,
        }
        payload = writer.call_args[0][0]
        assert payload["twitter_search_data"]["tweets"][0]["public_metrics"] == {}
        assert payload["twitter_search_data"]["tweets"][0]["created_at"] is None
        assert payload["twitter_search_data"]["tweets"][0]["conversation_id"] is None

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
        assert result == {
            "users": [
                {
                    "id": "u1",
                    "username": "johndoe",
                    "name": "John Doe",
                    "followers": 1000,
                    "following": 200,
                    "verified": True,
                }
            ]
        }
        writer.assert_called_once_with(
            {
                "twitter_user_data": [
                    {
                        "id": "u1",
                        "username": "johndoe",
                        "name": "John Doe",
                        "description": "Dev",
                        "profile_image_url": "https://img.com/pic.jpg",
                        "verified": True,
                        "public_metrics": {"followers_count": 1000, "following_count": 200},
                        "created_at": "2020-01-01",
                        "location": "NYC",
                        "url": "https://example.com",
                    }
                ]
            }
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_user_lookup_after_hook_defaults_for_sparse_user(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_user_lookup_after_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"data": {"id": "u9", "username": "min"}})
        result = twitter_user_lookup_after_hook(
            "TWITTER_USER_LOOKUP_BY_USERNAME", "TWITTER", response
        )
        assert result == {
            "users": [
                {
                    "id": "u9",
                    "username": "min",
                    "name": None,
                    "followers": 0,
                    "following": 0,
                    "verified": False,
                }
            ]
        }
        writer.assert_called_once_with(
            {
                "twitter_user_data": [
                    {
                        "id": "u9",
                        "username": "min",
                        "name": None,
                        "description": "",
                        "profile_image_url": None,
                        "verified": False,
                        "public_metrics": {},
                        "created_at": None,
                        "location": None,
                        "url": None,
                    }
                ]
            }
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_user_lookup_after_hook_multiple_users(self, mock_writer: MagicMock) -> None:
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
        assert result == {
            "users": [
                {
                    "id": "u1",
                    "username": "a",
                    "name": "A",
                    "followers": 0,
                    "following": 0,
                    "verified": False,
                },
                {
                    "id": "u2",
                    "username": "b",
                    "name": "B",
                    "followers": 0,
                    "following": 0,
                    "verified": True,
                },
            ]
        }

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_user_lookup_after_hook_empty_data_does_not_stream(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_user_lookup_after_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"data": None})
        result = twitter_user_lookup_after_hook(
            "TWITTER_USER_LOOKUP_BY_USERNAMES", "TWITTER", response
        )
        assert result == {"users": []}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_user_lookup_after_hook_no_writer(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_user_lookup_after_hook,
        )

        mock_writer.return_value = None
        response = _make_response({"data": {"id": "u1", "username": "a"}})
        result = twitter_user_lookup_after_hook(
            "TWITTER_USER_LOOKUP_BY_USERNAME", "TWITTER", response
        )
        assert result == {
            "users": [
                {
                    "id": "u1",
                    "username": "a",
                    "name": None,
                    "followers": 0,
                    "following": 0,
                    "verified": False,
                }
            ]
        }

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_user_lookup_after_hook_empty_response_logs_key_error(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_user_lookup_after_hook,
        )

        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {}
        result = twitter_user_lookup_after_hook(
            "TWITTER_USER_LOOKUP_BY_USERNAME", "TWITTER", response
        )
        assert result == {}
        _assert_logged_error(
            mock_log, "Error in twitter_user_lookup_after_hook", "'data'", "KeyError"
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_user_lookup_after_hook_error_response_does_not_log(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_user_lookup_after_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Not found"})
        result = twitter_user_lookup_after_hook(
            "TWITTER_USER_LOOKUP_BY_USERNAME", "TWITTER", response
        )
        assert result == {"error": "Not found"}
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_user_lookup_after_hook_missing_data_key_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_user_lookup_after_hook,
        )

        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {"successful": True}
        result = twitter_user_lookup_after_hook(
            "TWITTER_USER_LOOKUP_BY_USERNAME", "TWITTER", response
        )
        assert result == {"users": []}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_user_lookup_after_hook_flat_data_dict(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_user_lookup_after_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"id": "u1", "username": "flat", "name": "Flat"})
        result = twitter_user_lookup_after_hook(
            "TWITTER_USER_LOOKUP_BY_USERNAME", "TWITTER", response
        )
        assert result == {
            "users": [
                {
                    "id": "u1",
                    "username": "flat",
                    "name": "Flat",
                    "followers": 0,
                    "following": 0,
                    "verified": False,
                }
            ]
        }
        writer.assert_called_once_with(
            {
                "twitter_user_data": [
                    {
                        "id": "u1",
                        "username": "flat",
                        "name": "Flat",
                        "description": "",
                        "profile_image_url": None,
                        "verified": False,
                        "public_metrics": {},
                        "created_at": None,
                        "location": None,
                        "url": None,
                    }
                ]
            }
        )

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
                            "verified": True,
                        }
                    ]
                },
            }
        )
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result == {
            "tweets": [
                {"id": "tw1", "text": "Timeline tweet", "author": "testuser", "likes": 5}
            ],
            "count": 1,
        }
        writer.assert_called_once_with(
            {
                "twitter_timeline_data": {
                    "tweets": [
                        {
                            "id": "tw1",
                            "text": "Timeline tweet",
                            "created_at": "2024-01-01",
                            "author": {
                                "id": "u1",
                                "username": "testuser",
                                "name": "Test",
                                "profile_image_url": "https://img.com",
                                "verified": True,
                            },
                            "public_metrics": {"like_count": 5},
                        }
                    ]
                }
            }
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_timeline_after_hook_sparse_user_defaults(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "data": [_twitter_tweet(author_id="u1")],
                "includes": {"users": [{"id": "u1", "username": "min", "name": "Min"}]},
            }
        )
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result["tweets"][0]["author"] == "min"
        payload = writer.call_args[0][0]
        assert payload["twitter_timeline_data"]["tweets"][0]["author"] == {
            "id": "u1",
            "username": "min",
            "name": "Min",
            "profile_image_url": None,
            "verified": False,
        }

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_timeline_after_hook_missing_data_key_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {"successful": True}
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result == {"tweets": [], "count": 0}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_timeline_after_hook_defaults_for_sparse_tweet(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "data": [
                    {
                        "id": "tw1",
                        "text": "Sparse",
                        "author_id": "ghost",
                    }
                ],
                "includes": {"users": []},
            }
        )
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result == {
            "tweets": [
                {"id": "tw1", "text": "Sparse", "author": "unknown", "likes": 0}
            ],
            "count": 1,
        }
        payload = writer.call_args[0][0]
        assert payload["twitter_timeline_data"]["tweets"][0]["author"] == {
            "username": "unknown",
            "name": "Unknown",
        }
        assert payload["twitter_timeline_data"]["tweets"][0]["public_metrics"] == {}

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_timeline_after_hook_empty_tweets_does_not_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"data": [], "includes": {"users": []}})
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result == {"tweets": [], "count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_timeline_after_hook_truncates_long_tweets(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response(
            {
                "data": [_twitter_tweet(text="x" * 201)],
                "includes": {"users": []},
            }
        )
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result["tweets"][0]["text"] == "x" * 200 + "..."

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_timeline_after_hook_keeps_200_char_tweets(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response(
            {
                "data": [_twitter_tweet(text="x" * 200)],
                "includes": {"users": []},
            }
        )
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result["tweets"][0]["text"] == "x" * 200

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_timeline_after_hook_llm_tweets_capped_at_10(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        mock_writer.return_value = _noop_writer()
        tweets = [_twitter_tweet(id=f"tw{i}", text=f"tweet {i}") for i in range(11)]
        response = _make_response({"data": tweets, "includes": {"users": []}})
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert len(result["tweets"]) == 10
        assert result["tweets"][0]["id"] == "tw0"
        assert result["tweets"][9]["id"] == "tw9"
        assert result["count"] == 11

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_timeline_after_hook_no_writer(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        mock_writer.return_value = None
        response = _make_response(
            {
                "data": [_twitter_tweet()],
                "includes": {"users": []},
            }
        )
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result == {
            "tweets": [
                {"id": "tw1", "text": "Hello world", "author": "unknown", "likes": 10}
            ],
            "count": 1,
        }

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_timeline_after_hook_empty_response_logs_key_error(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {}
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result == {}
        _assert_logged_error(
            mock_log, "Error in twitter_timeline_after_hook", "'data'", "KeyError"
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_timeline_after_hook_error_response_does_not_log(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Not found"})
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result == {"error": "Not found"}
        writer.assert_not_called()
        mock_log.error.assert_not_called()

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
                        "verified": True,
                        "description": "Bio",
                        "public_metrics": {"followers_count": 50},
                    }
                ],
                "meta": {"next_token": "next"},
            }
        )
        result = twitter_followers_after_hook("TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response)
        assert result == {
            "users": [
                {"id": "u1", "username": "follower1", "name": "Follower 1", "followers": 50}
            ],
            "count": 1,
            "has_more": True,
        }
        writer.assert_called_once_with(
            {
                "twitter_followers_data": [
                    {
                        "id": "u1",
                        "username": "follower1",
                        "name": "Follower 1",
                        "profile_image_url": "https://img.com",
                        "verified": True,
                        "description": "Bio",
                        "public_metrics": {"followers_count": 50},
                    }
                ]
            }
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_followers_after_hook_defaults_for_sparse_user(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {
                "data": [{"id": "u9", "username": "min"}],
                "meta": {},
            }
        )
        result = twitter_followers_after_hook("TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response)
        assert result == {
            "users": [
                {"id": "u9", "username": "min", "name": None, "followers": 0}
            ],
            "count": 1,
            "has_more": False,
        }
        writer.assert_called_once_with(
            {
                "twitter_followers_data": [
                    {
                        "id": "u9",
                        "username": "min",
                        "name": None,
                        "profile_image_url": None,
                        "verified": False,
                        "description": "",
                        "public_metrics": {},
                    }
                ]
            }
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_followers_after_hook_missing_data_key_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {"successful": True}
        result = twitter_followers_after_hook("TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response)
        assert result == {"users": [], "count": 0, "has_more": False}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_followers_after_hook_missing_meta_has_more_false(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"data": [_twitter_user()]})
        result = twitter_followers_after_hook("TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response)
        assert result["count"] == 1
        assert result["has_more"] is False

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_following_after_hook_uses_following_key(self, mock_writer: MagicMock) -> None:
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
        result = twitter_followers_after_hook("TWITTER_FOLLOWING_BY_USER_ID", "TWITTER", response)
        assert result == {
            "users": [
                {"id": "u1", "username": "following1", "name": "Following 1", "followers": 100}
            ],
            "count": 1,
            "has_more": False,
        }
        writer.assert_called_once_with(
            {
                "twitter_following_data": [
                    {
                        "id": "u1",
                        "username": "following1",
                        "name": "Following 1",
                        "profile_image_url": None,
                        "verified": False,
                        "description": "",
                        "public_metrics": {"followers_count": 100},
                    }
                ]
            }
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_followers_after_hook_empty_does_not_stream(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"data": [], "meta": {}})
        result = twitter_followers_after_hook("TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response)
        assert result == {"users": [], "count": 0, "has_more": False}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_followers_after_hook_llm_users_capped_at_20(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        mock_writer.return_value = _noop_writer()
        users = [
            _twitter_user(id=f"u{i}", username=f"user{i}", name=f"User {i}")
            for i in range(21)
        ]
        response = _make_response({"data": users, "meta": {"next_token": "more"}})
        result = twitter_followers_after_hook("TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response)
        assert len(result["users"]) == 20
        assert result["users"][0]["id"] == "u0"
        assert result["users"][19]["id"] == "u19"
        assert result["count"] == 21
        assert result["has_more"] is True

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_followers_after_hook_no_writer(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        mock_writer.return_value = None
        response = _make_response({"data": [_twitter_user()], "meta": {}})
        result = twitter_followers_after_hook("TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response)
        assert result == {
            "users": [
                {
                    "id": "u1",
                    "username": "testuser",
                    "name": "Test User",
                    "followers": 100,
                }
            ],
            "count": 1,
            "has_more": False,
        }

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_followers_after_hook_empty_response_logs_key_error(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {}
        result = twitter_followers_after_hook("TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response)
        assert result == {}
        _assert_logged_error(
            mock_log, "Error in twitter_followers_after_hook", "'data'", "KeyError"
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_followers_after_hook_error_response_does_not_log(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Not found"})
        result = twitter_followers_after_hook("TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response)
        assert result == {"error": "Not found"}
        writer.assert_not_called()
        mock_log.error.assert_not_called()

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
        result = twitter_post_created_after_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", response)
        assert result == {
            "success": True,
            "id": "post123",
            "text": "My new tweet",
            "url": "https://twitter.com/i/status/post123",
        }
        writer.assert_called_once_with(
            {
                "twitter_post_created": {
                    "id": "post123",
                    "text": "My new tweet",
                    "url": "https://twitter.com/i/status/post123",
                }
            }
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_post_created_after_hook_empty_post_data_does_not_stream(
        self, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_post_created_after_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"data": {}})
        result = twitter_post_created_after_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", response)
        assert result == {
            "success": True,
            "id": None,
            "text": None,
            "url": "https://twitter.com/i/status/None",
        }
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    def test_post_created_after_hook_no_writer(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_post_created_after_hook,
        )

        mock_writer.return_value = None
        response = _make_response({"data": {"id": "post123", "text": "My new tweet"}})
        result = twitter_post_created_after_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", response)
        assert result == {
            "success": True,
            "id": "post123",
            "text": "My new tweet",
            "url": "https://twitter.com/i/status/post123",
        }

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_post_created_after_hook_empty_response_logs_key_error(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_post_created_after_hook,
        )

        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {}
        result = twitter_post_created_after_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", response)
        assert result == {}
        _assert_logged_error(
            mock_log, "Error in twitter_post_created_after_hook", "'data'", "KeyError"
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_post_created_after_hook_missing_data_key_returns_defaults(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_post_created_after_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        response: dict[str, Any] = {"successful": True}
        result = twitter_post_created_after_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", response)
        assert result == {
            "success": True,
            "id": None,
            "text": None,
            "url": "https://twitter.com/i/status/None",
        }
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_post_created_after_hook_error_response_does_not_log(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_post_created_after_hook,
        )

        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Duplicate"})
        result = twitter_post_created_after_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", response)
        assert result == {"error": "Duplicate"}
        writer.assert_not_called()
        mock_log.error.assert_not_called()


# ============================================================================
# 12. Reddit hooks — helper functions
# ============================================================================


class TestRedditHelpers:
    """Tests for Reddit helper functions (process_reddit_post, etc.)."""

    def test_process_reddit_post_extracts_fields(self) -> None:
        post_data = _make_reddit_post_data()
        result = process_reddit_post({"data": post_data})
        assert result == post_data

    def test_process_reddit_post_empty_data_uses_defaults(self) -> None:
        result = process_reddit_post({})
        assert result == _REDDIT_POST_DEFAULTS

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_process_reddit_post_non_dict_data_logs_and_returns_empty(
        self, mock_log: MagicMock
    ) -> None:
        result = process_reddit_post({"data": "not a dict"})
        assert result == {}
        _assert_logged_error(
            mock_log,
            "Error processing Reddit post",
            "'str' object has no attribute 'get'",
            "AttributeError",
        )

    def test_process_reddit_comment_extracts_fields(self) -> None:
        comment_data = _make_reddit_comment_data()
        result = process_reddit_comment({"data": comment_data})
        assert result == comment_data

    def test_process_reddit_comment_empty_data_uses_defaults(self) -> None:
        result = process_reddit_comment({})
        assert result == _REDDIT_COMMENT_DEFAULTS

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_process_reddit_comment_non_dict_data_logs_and_returns_empty(
        self, mock_log: MagicMock
    ) -> None:
        result = process_reddit_comment({"data": 123})
        assert result == {}
        _assert_logged_error(
            mock_log,
            "Error processing Reddit comment",
            "'int' object has no attribute 'get'",
            "AttributeError",
        )

    def test_process_reddit_search_results_extracts_posts(self) -> None:
        post_data = _make_reddit_post_data(id="p1", title="Post 1")
        response = {
            "search_results": {
                "data": {
                    "children": [
                        {"kind": "t3", "data": post_data},
                        {"kind": "t1", "data": _make_reddit_comment_data()},
                        {"kind": "more", "data": {"id": "more1"}},
                    ],
                    "after": "cursor123",
                    "before": "prev_123",
                }
            }
        }
        result = process_reddit_search_results(response)
        assert result == {
            "posts": [post_data],
            "after": "cursor123",
            "before": "prev_123",
            "result_count": 1,
        }

    def test_process_reddit_search_results_missing_keys_use_defaults(self) -> None:
        result = process_reddit_search_results({})
        assert result == {"posts": [], "after": None, "before": None, "result_count": 0}

    def test_process_reddit_search_results_empty_children(self) -> None:
        result = process_reddit_search_results({"search_results": {"data": {"children": []}}})
        assert result == {"posts": [], "after": None, "before": None, "result_count": 0}

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_process_reddit_search_results_skips_t3_with_invalid_data(
        self, mock_log: MagicMock
    ) -> None:
        response = {
            "search_results": {
                "data": {"children": [{"kind": "t3", "data": "not a dict"}]}
            }
        }
        result = process_reddit_search_results(response)
        assert result == {"posts": [], "after": None, "before": None, "result_count": 0}
        mock_log.error.assert_called_once()

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_process_reddit_search_results_non_dict_search_results_returns_original(
        self, mock_log: MagicMock
    ) -> None:
        response: dict[str, Any] = {"search_results": "not a dict"}
        result = process_reddit_search_results(response)
        assert result is response
        _assert_logged_error(
            mock_log,
            "Error processing Reddit search results",
            "'str' object has no attribute 'get'",
            "AttributeError",
        )


# ============================================================================
# 13. Reddit hooks — before execute
# ============================================================================


class TestRedditBeforeHooks:
    """Tests for Reddit before-execute hooks."""

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_create_post(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({"subreddit": "python"})
        result = reddit_content_before_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Creating post in r/python..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_create_post_without_subreddit(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_content_before_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", params)
        writer.assert_called_once_with({"progress": "Creating post in r/..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_create_post_without_arguments_key(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params: dict[str, Any] = {"custom_key": "x"}
        reddit_content_before_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", params)
        writer.assert_called_once_with({"progress": "Creating post in r/..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_post_comment(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_content_before_hook("REDDIT_POST_REDDIT_COMMENT", "REDDIT", params)
        writer.assert_called_once_with({"progress": "Posting comment..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_edit(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        reddit_content_before_hook("REDDIT_EDIT_REDDIT_COMMENT_OR_POST", "REDDIT", params)
        writer.assert_called_once_with({"progress": "Editing content..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_content_before_hook_unknown_tool_does_not_write(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_content_before_hook("REDDIT_OTHER_TOOL", "REDDIT", params)
        assert result is params
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_before_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        params = _make_params({})
        result = reddit_content_before_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", params)
        assert result is params

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_delete_before_hook_post(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_delete_before_hook("REDDIT_DELETE_REDDIT_POST", "REDDIT", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Deleting post..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_delete_before_hook_comment(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_delete_before_hook("REDDIT_DELETE_REDDIT_COMMENT", "REDDIT", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Deleting comment..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_delete_before_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        params = _make_params({})
        result = reddit_delete_before_hook("REDDIT_DELETE_REDDIT_POST", "REDDIT", params)
        assert result is params

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_retrieve_before_hook_post(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_retrieve_before_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Fetching post details..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_retrieve_before_hook_comments(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_retrieve_before_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", params)
        assert result is params
        writer.assert_called_once_with({"progress": "Fetching post comments..."})

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_retrieve_before_hook_unknown_tool_does_not_write(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        params = _make_params({})
        result = reddit_retrieve_before_hook("REDDIT_OTHER_TOOL", "REDDIT", params)
        assert result is params
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_retrieve_before_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        params = _make_params({})
        result = reddit_retrieve_before_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", params)
        assert result is params


# ============================================================================
# 14. Reddit hooks — after execute
# ============================================================================


class TestRedditAfterHooks:
    """Tests for Reddit after-execute hooks."""

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_search_after_hook_sets_log_context(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = None
        response = _make_response({"search_results": {"data": {"children": []}}})
        reddit_search_after_hook("REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response)
        mock_log.set.assert_called_once_with(
            reddit_tool="REDDIT_SEARCH_ACROSS_SUBREDDITS", toolkit="REDDIT"
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_processes_results(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        post_data = _make_reddit_post_data(
            id="p1",
            title="Python Tips",
            author="dev",
            permalink="/r/python/p1",
            url="https://reddit.com/r/python/p1",
            selftext="Short text",
        )
        response = _make_response(
            {
                "search_results": {
                    "data": {
                        "children": [{"kind": "t3", "data": post_data}],
                        "after": "cur123",
                        "before": None,
                    }
                }
            }
        )
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {
            "posts": [post_data],
            "after": "cur123",
            "before": None,
            "result_count": 1,
        }
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "search",
                    "posts": [
                        {
                            "id": "p1",
                            "title": "Python Tips",
                            "author": "dev",
                            "subreddit": "r/python",
                            "score": 42,
                            "num_comments": 10,
                            "created_utc": 1704067200,
                            "permalink": "/r/python/p1",
                            "url": "https://reddit.com/r/python/p1",
                            "selftext": "Short text",
                        }
                    ],
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_truncates_long_selftext(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        long_text = "x" * 250
        post_data = _make_reddit_post_data(id="p1", selftext=long_text)
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t3", "data": post_data}]}}}
        )
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result["posts"][0]["selftext"] == long_text
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["posts"][0]["selftext"] == "x" * 200 + "..."

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_selftext_at_200_chars_is_not_truncated(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        exact_text = "x" * 200
        post_data = _make_reddit_post_data(id="p1", selftext=exact_text)
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t3", "data": post_data}]}}}
        )
        reddit_search_after_hook("REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response)
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["posts"][0]["selftext"] == exact_text

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_selftext_at_201_chars_is_truncated(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        post_data = _make_reddit_post_data(id="p1", selftext="x" * 201)
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t3", "data": post_data}]}}}
        )
        reddit_search_after_hook("REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response)
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["posts"][0]["selftext"] == "x" * 200 + "..."

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_streams_default_fields(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t3", "data": {}}]}}}
        )
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {
            "posts": [_REDDIT_POST_DEFAULTS],
            "after": None,
            "before": None,
            "result_count": 1,
        }
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "search",
                    "posts": [
                        {
                            "id": "",
                            "title": "",
                            "author": "",
                            "subreddit": "",
                            "score": 0,
                            "num_comments": 0,
                            "created_utc": 0,
                            "permalink": "",
                            "url": "",
                            "selftext": "",
                        }
                    ],
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_no_posts_does_not_stream(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t1", "data": {"id": "c1"}}]}}}
        )
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {"posts": [], "after": None, "before": None, "result_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_no_writer_returns_processed(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        post_data = _make_reddit_post_data()
        response = _make_response(
            {"search_results": {"data": {"children": [{"kind": "t3", "data": post_data}]}}}
        )
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {"posts": [post_data], "after": None, "before": None, "result_count": 1}

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_search_after_hook_error_response(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Rate limited"})
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {"error": "Rate limited"}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_search_after_hook_empty_response_returns_empty_without_error_log(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = None
        response: dict[str, Any] = {}
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_search_after_hook_missing_data_key_logs_and_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {"successful": True}
        result = reddit_search_after_hook(
            "REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response
        )
        assert result == {}
        mock_log.error.assert_called_once()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_post_detail_after_hook(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        post_data = _make_reddit_post_data(id="p1", title="Detail Post")
        response = _make_response({"data": post_data})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == post_data
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "post",
                    "post": {
                        "id": "p1",
                        "title": "Detail Post",
                        "author": "testuser",
                        "subreddit": "r/python",
                        "score": 42,
                        "upvote_ratio": 0.95,
                        "num_comments": 10,
                        "created_utc": 1704067200,
                        "selftext": "Hello world",
                        "url": "https://reddit.com/r/python/abc",
                        "permalink": "/r/python/comments/abc",
                        "is_self": True,
                        "link_flair_text": "Discussion",
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_post_detail_after_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        post_data = _make_reddit_post_data()
        response = _make_response({"data": post_data})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == post_data

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_post_detail_after_hook_streams_default_fields(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"data": {}})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == _REDDIT_POST_DEFAULTS
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "post",
                    "post": {
                        "id": "",
                        "title": "",
                        "author": "",
                        "subreddit": "",
                        "score": 0,
                        "upvote_ratio": 0,
                        "num_comments": 0,
                        "created_utc": 0,
                        "selftext": "",
                        "url": "",
                        "permalink": "",
                        "is_self": False,
                        "link_flair_text": None,
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_post_detail_after_hook_invalid_post_data_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = _noop_writer()
        response = _make_response({"data": "not a dict"})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == {}
        mock_log.error.assert_called_once()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_post_detail_after_hook_missing_data_key_uses_defaults(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = _noop_writer()
        response: dict[str, Any] = {"successful": True}
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == _REDDIT_POST_DEFAULTS
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_post_detail_after_hook_empty_response_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = None
        response: dict[str, Any] = {}
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == {}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_post_detail_after_hook_error_response(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Not found"})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == {"error": "Not found"}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_array_format(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        comment_data = _make_reddit_comment_data(id="c1", body="Nice post!")
        response = _make_response(
            [
                {"data": {"children": []}},
                {
                    "data": {
                        "children": [
                            {"kind": "t1", "data": comment_data},
                            {"kind": "more", "data": {"id": "more1"}},
                        ]
                    }
                },
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [comment_data], "comment_count": 1}
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "comments",
                    "comments": [
                        {
                            "id": "c1",
                            "author": "commenter",
                            "body": "Nice post!",
                            "score": 15,
                            "created_utc": 1704067200,
                            "permalink": "/r/python/comments/abc/cmt1",
                            "is_submitter": True,
                        }
                    ],
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_dict_format(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        comment_data = _make_reddit_comment_data(id="c1", body="Comment body")
        response = _make_response(
            {"comments": {"data": {"children": [{"kind": "t1", "data": comment_data}]}}}
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [comment_data], "comment_count": 1}
        writer.assert_called_once()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_streams_default_fields(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [
                {"data": {"children": []}},
                {"data": {"children": [{"kind": "t1", "data": {"body": "x"}}]}},
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result["comment_count"] == 1
        assert result["comments"][0] == {**_REDDIT_COMMENT_DEFAULTS, "body": "x"}
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "comments",
                    "comments": [
                        {
                            "id": "",
                            "author": "",
                            "body": "x",
                            "score": 0,
                            "created_utc": 0,
                            "permalink": "",
                            "is_submitter": False,
                        }
                    ],
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_streams_truthy_is_submitter(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [
                {"data": {"children": []}},
                {
                    "data": {
                        "children": [
                            {"kind": "t1", "data": {"body": "x", "is_submitter": True}}
                        ]
                    }
                },
            ]
        )
        reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        payload = writer.call_args[0][0]
        assert payload["reddit_data"]["comments"][0]["is_submitter"] is True

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_response_without_data_key(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response: dict[str, Any] = {"successful": True}
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_listing_missing_children(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [{"data": {"children": []}}, {"data": {}}]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.log")
    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_listing_missing_data(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response([{"data": {"children": []}}, {}])
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_missing_comments_key_returns_empty(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({})
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_single_element_array_returns_empty(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [{"data": {"children": [{"kind": "t1", "data": _make_reddit_comment_data()}]}}]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_non_dict_comments_listing_returns_empty(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response([{"data": {"children": []}}, "not a listing"])
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_skips_non_t1(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [
                {"data": {"children": []}},
                {"data": {"children": [{"kind": "more", "data": {"id": "more1"}}]}},
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_skips_empty_body(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        comment_data = _make_reddit_comment_data(id="c1", body="")
        response = _make_response(
            [
                {"data": {"children": []}},
                {"data": {"children": [{"kind": "t1", "data": comment_data}]}},
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_comments_after_hook_skips_invalid_comment_data(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            [
                {"data": {"children": []}},
                {"data": {"children": [{"kind": "t1", "data": "oops"}]}},
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [], "comment_count": 0}
        writer.assert_not_called()
        mock_log.error.assert_called_once()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_streams_at_most_50_comments(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        comments = [
            {"kind": "t1", "data": _make_reddit_comment_data(id=f"c{i}", body=f"body {i}")}
            for i in range(51)
        ]
        response = _make_response(
            [{"data": {"children": []}}, {"data": {"children": comments}}]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result["comment_count"] == 51
        assert len(result["comments"]) == 51
        payload = writer.call_args[0][0]
        assert len(payload["reddit_data"]["comments"]) == 50
        assert payload["reddit_data"]["comments"][0]["id"] == "c0"
        assert payload["reddit_data"]["comments"][49]["id"] == "c49"

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        comment_data = _make_reddit_comment_data()
        response = _make_response(
            [
                {"data": {"children": []}},
                {"data": {"children": [{"kind": "t1", "data": comment_data}]}},
            ]
        )
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"comments": [comment_data], "comment_count": 1}

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_comments_after_hook_error_response(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Not found"})
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {"error": "Not found"}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_comments_after_hook_empty_response_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = None
        response: dict[str, Any] = {}
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_post(self, mock_writer: MagicMock) -> None:
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
        assert result == {
            "id": "new_post",
            "success": True,
            "message": "Content created successfully",
        }
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "post_created",
                    "data": {
                        "id": "new_post",
                        "url": "https://reddit.com/r/python/new_post",
                        "message": "Post created successfully!",
                        "permalink": "/r/python/new_post",
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_comment(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response(
            {"id": "new_comment", "permalink": "/r/python/p1/new_comment"}
        )
        result = reddit_content_created_after_hook(
            "REDDIT_POST_REDDIT_COMMENT", "REDDIT", response
        )
        assert result == {
            "id": "new_comment",
            "success": True,
            "message": "Content created successfully",
        }
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "comment_created",
                    "data": {
                        "id": "new_comment",
                        "message": "Comment posted successfully!",
                        "permalink": "/r/python/p1/new_comment",
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_unknown_tool_does_not_stream(
        self, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"id": "x"})
        result = reddit_content_created_after_hook(
            "REDDIT_EDIT_REDDIT_COMMENT_OR_POST", "REDDIT", response
        )
        assert result == {"id": "x", "success": True, "message": "Content created successfully"}
        writer.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_no_writer(self, mock_writer: MagicMock) -> None:
        mock_writer.return_value = None
        response = _make_response({"id": "new_post", "permalink": "/r/python/new_post"})
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert result == {
            "id": "new_post",
            "success": True,
            "message": "Content created successfully",
        }

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_content_created_after_hook_missing_data_key_uses_defaults(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response: dict[str, Any] = {"successful": True}
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert result == {"id": "", "success": True, "message": "Content created successfully"}
        mock_log.error.assert_not_called()
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "post_created",
                    "data": {
                        "id": "",
                        "url": "",
                        "message": "Post created successfully!",
                        "permalink": "",
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_content_created_after_hook_comment_missing_data_key_streams_defaults(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response: dict[str, Any] = {"successful": True}
        result = reddit_content_created_after_hook(
            "REDDIT_POST_REDDIT_COMMENT", "REDDIT", response
        )
        assert result == {"id": "", "success": True, "message": "Content created successfully"}
        mock_log.error.assert_not_called()
        writer.assert_called_once_with(
            {
                "reddit_data": {
                    "type": "comment_created",
                    "data": {
                        "id": "",
                        "message": "Comment posted successfully!",
                        "permalink": "",
                    },
                }
            }
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_content_created_after_hook_empty_response_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_writer.return_value = None
        response: dict[str, Any] = {}
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert result == {}
        mock_log.error.assert_not_called()

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    def test_content_created_after_hook_error_response(self, mock_writer: MagicMock) -> None:
        writer = _noop_writer()
        mock_writer.return_value = writer
        response = _make_response({"error": "Forbidden"})
        result = reddit_content_created_after_hook(
            "REDDIT_CREATE_REDDIT_POST", "REDDIT", response
        )
        assert result == {"error": "Forbidden"}
        writer.assert_not_called()


# ============================================================================
# 15. Edge cases and error resilience
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling across the hook system."""

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_hook_exception_returns_params(self, mock_writer: MagicMock) -> None:
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

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_twitter_search_after_hook_exception_returns_data(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_after_hook

        mock_writer.side_effect = RuntimeError("No writer")
        response = _make_response({"data": [], "includes": {}, "meta": {}})
        result = twitter_search_after_hook("TWITTER_RECENT_SEARCH", "TWITTER", response)
        assert result == {"data": [], "includes": {}, "meta": {}}
        _assert_logged_error(
            mock_log, "Error in twitter_search_after_hook", "No writer", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_search_after_hook_exception_returns_data(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_search_after_hook

        mock_writer.side_effect = RuntimeError("No writer")
        response = _make_response({"search_results": {}})
        result = reddit_search_after_hook("REDDIT_SEARCH_ACROSS_SUBREDDITS", "REDDIT", response)
        assert result == {"search_results": {}}
        _assert_logged_error(mock_log, "Error in reddit_search_after_hook", "No writer", "RuntimeError")

    def test_gmail_attachment_non_dict_data(self) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_attachment_after_hook

        response: dict[str, Any] = {"data": "plain_string", "successful": True}
        result = gmail_attachment_after_hook("GMAIL_FETCH_ATTACHMENT", "GMAIL", response)
        assert result == "plain_string"

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_gmail_before_hook_no_writer_skips_streaming(self, mock_writer: MagicMock) -> None:
        """Before hooks that check writer truthy-ness skip streaming gracefully."""
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_before_hook

        mock_writer.return_value = None
        params = _make_params({})
        result = gmail_send_draft_before_hook("GMAIL_SEND_DRAFT", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_compose_before_hook_extra_recipients_non_list(self, mock_writer: MagicMock) -> None:
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
    def test_modify_labels_before_hook_writer_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_modify_labels_before_hook

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_modify_labels_before_hook("GMAIL_ADD_LABEL_TO_EMAIL", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_draft_management_before_hook_writer_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import (
            gmail_draft_management_before_hook,
        )

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_draft_management_before_hook("GMAIL_UPDATE_DRAFT", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_list_drafts_before_hook_writer_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_list_drafts_before_hook

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_list_drafts_before_hook("GMAIL_LIST_DRAFTS", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_draft_before_hook_writer_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_draft_before_hook

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_get_draft_before_hook("GMAIL_GET_DRAFT", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_before_hook_writer_exception(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_before_hook

        mock_writer.side_effect = RuntimeError("no context")
        params = _make_params({})
        result = gmail_get_contacts_before_hook("GMAIL_GET_CONTACTS", "GMAIL", params)
        assert result is params

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_before_hook_writer_exception(self, mock_writer: MagicMock) -> None:
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
    def test_message_detail_exception_returns_raw(self, mock_template: MagicMock) -> None:
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
        result = gmail_thread_after_hook("GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL", response)
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
        result = gmail_fetch_by_id_after_hook("GMAIL_FETCH_EMAIL_BY_ID", "GMAIL", response)
        assert result == {"raw": "email"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_send_draft_after_exception_returns_raw(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_send_draft_after_hook

        mock_writer.side_effect = RuntimeError("no writer")
        response = _make_response({"successful": True, "id": "x"})
        result = gmail_send_draft_after_hook("GMAIL_SEND_DRAFT", "GMAIL", response)
        assert result == {"successful": True, "id": "x"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_get_contacts_after_exception_returns_raw(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_get_contacts_after_hook

        mock_writer.side_effect = RuntimeError("no writer")
        response = _make_response({"response_data": {"connections": []}})
        result = gmail_get_contacts_after_hook("GMAIL_GET_CONTACTS", "GMAIL", response)
        assert result == {"response_data": {"connections": []}}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_after_hook_error_response(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        mock_writer.return_value = _noop_writer()
        response = _make_response({"error": "Not found"})
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", response)
        assert result == {"error": "Not found"}

    @patch("app.utils.composio_hooks.gmail_hooks.get_stream_writer")
    def test_search_people_after_exception_returns_raw(self, mock_writer: MagicMock) -> None:
        from app.utils.composio_hooks.gmail_hooks import gmail_search_people_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"response_data": {"results": []}})
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", response)
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
                                "phoneNumbers": [{"value": "+1111", "metadata": {"primary": True}}],
                            }
                        }
                    ],
                },
            }
        )
        result = gmail_search_people_after_hook("GMAIL_SEARCH_PEOPLE", "GMAIL", response)
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
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_post_detail_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_post_detail_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"data": {"id": "p1"}})
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == {"data": {"id": "p1"}}
        _assert_logged_error(mock_log, "Error in reddit_post_detail_after_hook", "broken", "RuntimeError")

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_post_detail_exception_without_data_key_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_post_detail_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response: dict[str, Any] = {"successful": True}
        result = reddit_post_detail_after_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", response)
        assert result == {}
        _assert_logged_error(mock_log, "Error in reddit_post_detail_after_hook", "broken", "RuntimeError")

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_comments_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_comments_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response([{}, {"data": {"children": []}}])
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == [{}, {"data": {"children": []}}]
        _assert_logged_error(mock_log, "Error in reddit_comments_after_hook", "broken", "RuntimeError")

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_comments_exception_without_data_key_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_comments_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response: dict[str, Any] = {"successful": True}
        result = reddit_comments_after_hook("REDDIT_RETRIEVE_POST_COMMENTS", "REDDIT", response)
        assert result == {}
        _assert_logged_error(mock_log, "Error in reddit_comments_after_hook", "broken", "RuntimeError")

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_content_created_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import (
            reddit_content_created_after_hook,
        )

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"id": "new"})
        result = reddit_content_created_after_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", response)
        assert result == {"id": "new"}
        _assert_logged_error(
            mock_log, "Error in reddit_content_created_after_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_content_created_exception_without_data_key_returns_empty(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import (
            reddit_content_created_after_hook,
        )

        mock_writer.side_effect = RuntimeError("broken")
        response: dict[str, Any] = {"successful": True}
        result = reddit_content_created_after_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", response)
        assert result == {}
        _assert_logged_error(
            mock_log, "Error in reddit_content_created_after_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_content_before_hook_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_content_before_hook

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({"subreddit": "test"})
        result = reddit_content_before_hook("REDDIT_CREATE_REDDIT_POST", "REDDIT", params)
        assert result is params
        _assert_logged_error(
            mock_log, "Error in reddit_content_before_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_delete_before_hook_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_delete_before_hook

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({})
        result = reddit_delete_before_hook("REDDIT_DELETE_REDDIT_POST", "REDDIT", params)
        assert result is params
        _assert_logged_error(mock_log, "Error in reddit_delete_before_hook", "broken", "RuntimeError")

    @patch("app.utils.composio_hooks.reddit_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.reddit_hooks.log")
    def test_reddit_retrieve_before_hook_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.reddit_hooks import reddit_retrieve_before_hook

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({})
        result = reddit_retrieve_before_hook("REDDIT_RETRIEVE_REDDIT_POST", "REDDIT", params)
        assert result is params
        _assert_logged_error(
            mock_log, "Error in reddit_retrieve_before_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_twitter_create_post_before_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_create_post_before_hook,
        )

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({"text": "Test"})
        result = twitter_create_post_before_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", params)
        assert result is params
        _assert_logged_error(
            mock_log, "Error in twitter_create_post_before_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_twitter_search_before_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_search_before_hook

        mock_writer.side_effect = RuntimeError("broken")
        params = _make_params({"query": "test"})
        result = twitter_search_before_hook("TWITTER_RECENT_SEARCH", "TWITTER", params)
        assert result is params
        _assert_logged_error(
            mock_log, "Error in twitter_search_before_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_twitter_user_lookup_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_user_lookup_after_hook,
        )

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"id": "u1"})
        result = twitter_user_lookup_after_hook(
            "TWITTER_USER_LOOKUP_BY_USERNAME", "TWITTER", response
        )
        assert result == {"id": "u1"}
        _assert_logged_error(
            mock_log, "Error in twitter_user_lookup_after_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_twitter_timeline_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_timeline_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"data": [], "includes": {}})
        result = twitter_timeline_after_hook(
            "TWITTER_USER_HOME_TIMELINE_BY_USER_ID", "TWITTER", response
        )
        assert result == {"data": [], "includes": {}}
        _assert_logged_error(
            mock_log, "Error in twitter_timeline_after_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_twitter_followers_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import twitter_followers_after_hook

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"data": []})
        result = twitter_followers_after_hook("TWITTER_FOLLOWERS_BY_USER_ID", "TWITTER", response)
        assert result == {"data": []}
        _assert_logged_error(
            mock_log, "Error in twitter_followers_after_hook", "broken", "RuntimeError"
        )

    @patch("app.utils.composio_hooks.twitter_hooks.get_stream_writer")
    @patch("app.utils.composio_hooks.twitter_hooks.log")
    def test_twitter_post_created_exception(
        self, mock_log: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.utils.composio_hooks.twitter_hooks import (
            twitter_post_created_after_hook,
        )

        mock_writer.side_effect = RuntimeError("broken")
        response = _make_response({"id": "p1"})
        result = twitter_post_created_after_hook("TWITTER_CREATION_OF_A_POST", "TWITTER", response)
        assert result == {"id": "p1"}
        _assert_logged_error(
            mock_log, "Error in twitter_post_created_after_hook", "broken", "RuntimeError"
        )
