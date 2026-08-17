"""Tests for LangchainProvider (app/services/composio/langchain_composio_service.py)."""

from typing import Any
from unittest.mock import patch

from app.services.composio.langchain_composio_service import LangchainProvider

MODULE = "app.services.composio.langchain_composio_service"


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
