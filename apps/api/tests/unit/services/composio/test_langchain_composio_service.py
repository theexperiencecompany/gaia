"""Tests for LangchainProvider (app/services/composio/langchain_composio_service.py)."""

from typing import Any
from unittest.mock import patch

import pytest

from app.services.composio.langchain_composio_service import (
    LangchainProvider,
    _reinstate_reserved_python_keywords,
    _RenamedProperty,
    _substitute_reserved_python_keywords,
)

MODULE = "app.services.composio.langchain_composio_service"


class TestReservedKeywordRoundTrip:
    """Composio schemas may name a property after a Python keyword (`from`, `as`),
    which cannot be a function parameter — the schema is rewritten to `from_rs`
    before the tool signature is built, and the model's arguments must be rewritten
    back before they reach Composio. A key that fails to travel back is silently
    dropped from the API call, so the round trip is the contract.
    """

    def _keywords(self, schema: dict[str, object]) -> dict[str, _RenamedProperty]:
        # Build the keyword map with the real producer, never by hand: the two
        # halves are only correct if they agree on its layout.
        return _substitute_reserved_python_keywords(schema=schema)[1]

    def test_a_reserved_property_is_renamed_in_the_schema_and_back_in_the_request(self) -> None:
        # `to` comes first so a substitution that stops at the first non-reserved
        # property would never reach `from`.
        schema: dict[str, object] = {
            "properties": {"to": {"type": "string"}, "from": {"type": "string"}}
        }

        rewritten, keywords = _substitute_reserved_python_keywords(schema=schema)

        assert rewritten["properties"] == {
            "to": {"type": "string"},
            "from_rs": {"type": "string"},
        }
        assert keywords == {"from_rs": _RenamedProperty(original_name="from", nested={})}

        request = _reinstate_reserved_python_keywords(
            request={"from_rs": "a@b.com", "to": "c@d.com"}, keywords=keywords
        )
        assert request == {"from": "a@b.com", "to": "c@d.com"}

    def test_a_reserved_property_nested_in_an_object_is_reinstated_too(self) -> None:
        schema: dict[str, object] = {
            "properties": {
                "from": {
                    "type": "object",
                    "properties": {"as": {"type": "string"}, "name": {"type": "string"}},
                }
            }
        }

        rewritten, keywords = _substitute_reserved_python_keywords(schema=schema)

        assert rewritten["properties"] == {
            "from_rs": {
                "type": "object",
                "properties": {"as_rs": {"type": "string"}, "name": {"type": "string"}},
            }
        }
        assert keywords == {
            "from_rs": _RenamedProperty(
                original_name="from",
                nested={"as_rs": _RenamedProperty(original_name="as", nested={})},
            )
        }

        request = _reinstate_reserved_python_keywords(
            request={"from_rs": {"as_rs": "alias", "name": "Ada"}}, keywords=keywords
        )
        assert request == {"from": {"as": "alias", "name": "Ada"}}

    def test_reinstatement_recurses_through_every_level_of_nesting(self) -> None:
        schema: dict[str, object] = {
            "properties": {
                "from": {
                    "type": "object",
                    "properties": {
                        "as": {"type": "object", "properties": {"pass": {"type": "string"}}}
                    },
                }
            }
        }
        keywords = self._keywords(schema)

        request = _reinstate_reserved_python_keywords(
            request={"from_rs": {"as_rs": {"pass_rs": "secret"}}}, keywords=keywords
        )
        assert request == {"from": {"as": {"pass": "secret"}}}

    def test_an_argument_the_model_omitted_does_not_stop_the_remaining_ones(self) -> None:
        # `from_rs` is absent, `as_rs` is not: skipping the first must not abandon
        # the rest of the map.
        keywords = self._keywords(
            {"properties": {"from": {"type": "string"}, "as": {"type": "string"}}}
        )

        request = _reinstate_reserved_python_keywords(
            request={"as_rs": "alias", "to": "c@d.com"}, keywords=keywords
        )
        assert request == {"as": "alias", "to": "c@d.com"}

    def test_a_schema_without_properties_is_returned_untouched(self) -> None:
        schema: dict[str, object] = {"title": "NoParams"}

        assert _substitute_reserved_python_keywords(schema=schema) == ({"title": "NoParams"}, {})

    def test_a_scalar_where_the_schema_declares_an_object_is_rejected_loudly(self) -> None:
        # The arguments come from the model, so a wrong-typed value is a real
        # possibility — it must not be silently passed through to Composio.
        keywords = self._keywords(
            {"properties": {"from": {"type": "object", "properties": {"as": {"type": "string"}}}}}
        )

        with pytest.raises(ValueError) as excinfo:
            _reinstate_reserved_python_keywords(
                request={"from_rs": "not-an-object"}, keywords=keywords
            )
        assert (
            str(excinfo.value)
            == "Expected 'from_rs' value to be a dict for keyword reinstatement, got str"
        )

    def test_a_malformed_properties_block_is_rejected_loudly(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            _substitute_reserved_python_keywords(schema={"properties": ["from"]})
        assert str(excinfo.value) == "Expected 'properties' to be a dict, got list"

    def test_a_malformed_property_schema_is_rejected_loudly(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            _substitute_reserved_python_keywords(schema={"properties": {"from": "string"}})
        assert str(excinfo.value) == "Expected property 'from' schema to be a dict, got str"


class TestObservabilityFailureDoesNotBreakTheToolCall:
    """The invocation-observability log call is wrapped in its own try/except so a
    logging failure can never take down the actual Composio tool call it is reporting
    on — the tool's real result must still reach the caller.
    """

    def _action_func(self, execute_tool: Any) -> Any:
        return LangchainProvider()._wrap_action(
            tool="GMAIL_SEND_EMAIL",
            description="Send an email.",
            schema_params={},
            execute_tool=execute_tool,
            keywords={},
            toolkit="gmail",
        )

    def test_a_logging_failure_is_swallowed_and_the_tool_result_still_returns(self) -> None:
        tool_result = {"successful": False, "error": "invalid recipient", "data": None}
        action_func = self._action_func(execute_tool=lambda _tool, _kwargs: tool_result)

        with patch(f"{MODULE}.log") as mock_log:
            mock_log.set.side_effect = RuntimeError("log sink unreachable")
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        # The observability failure must not surface as an exception, and must not
        # swap out the real tool result for anything else.
        assert result == tool_result

    def test_the_failure_is_reported_via_log_debug_with_the_original_error(self) -> None:
        action_func = self._action_func(
            execute_tool=lambda _tool, _kwargs: {"successful": True, "data": {"id": "msg-1"}}
        )

        with patch(f"{MODULE}.log") as mock_log:
            mock_log.set.side_effect = RuntimeError("log sink unreachable")
            action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        mock_log.debug.assert_called_once()
        _, kwargs = mock_log.debug.call_args
        assert kwargs["tool"] == "GMAIL_SEND_EMAIL"
        assert kwargs["error"] == "log sink unreachable"
        assert kwargs["error_type"] == "RuntimeError"

    def test_a_successful_invocation_never_touches_the_debug_fallback(self) -> None:
        # Positive control: observability succeeding must not also emit the
        # failure-path debug log — only the caught failure does.
        action_func = self._action_func(
            execute_tool=lambda _tool, _kwargs: {"successful": True, "data": {"id": "msg-1"}}
        )

        with patch(f"{MODULE}.log") as mock_log:
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        assert result == {"successful": True, "data": {"id": "msg-1"}}
        mock_log.debug.assert_not_called()
