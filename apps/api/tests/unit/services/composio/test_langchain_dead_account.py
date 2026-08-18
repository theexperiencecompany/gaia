"""Dead-connected-account reconciliation in the Composio tool wrapper.

Regression cover for GAIA-BACKEND-2ZG: a revoked Composio account made
`execute_tool` raise `NotFoundError`, which PR #932 wrapped in a blanket
`except Exception` returning `{"successful": False, "error": str(e)}`. That
stopped the 500 but left the user stuck (nothing ever recorded the connection
as dead) and swallowed timeouts, 5xx and real bugs into the same opaque string.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import composio_client
import httpx
import pytest

from app.services.composio.langchain_composio_service import (
    LangchainProvider,
    _expire_with_log_boundary,
    _is_dead_account_error,
)

MODULE = "app.services.composio.langchain_composio_service"

DEAD_ACCOUNT_BODY = {
    "error": {
        "error_code": 1810,
        "name": "ActionExecute_ConnectedAccountNotFound",
        "message": "No connected account found for user and toolkit GMAIL",
    }
}


def _not_found(body: object, message: str) -> composio_client.NotFoundError:
    request = httpx.Request("POST", "https://backend.composio.dev/api/v3/tools/execute")
    return composio_client.NotFoundError(
        message, response=httpx.Response(404, request=request, json=body), body=body
    )


def _raises(exc: Exception) -> Any:
    def execute_tool(_tool: str, _kwargs: dict[str, Any]) -> dict[str, Any]:
        raise exc

    return execute_tool


def _returns(result: dict[str, Any]) -> Any:
    def execute_tool(_tool: str, _kwargs: dict[str, Any]) -> dict[str, Any]:
        return result

    return execute_tool


def _action_func(provider: LangchainProvider, execute_tool: Any, toolkit: str = "GMAIL") -> Any:
    return provider._wrap_action(
        tool="GMAIL_FETCH_MESSAGES",
        description="Fetch messages.",
        schema_params={},
        execute_tool=execute_tool,
        keywords={},
        toolkit=toolkit,
    )


class TestDeadAccountClassifier:
    """A false positive here marks a healthy integration expired, so the
    classifier must key on the structured error and not merely on a 404."""

    def test_structured_error_code_is_recognized(self) -> None:
        assert _is_dead_account_error(_not_found(DEAD_ACCOUNT_BODY, "boom")) is True

    def test_structured_error_name_is_recognized_without_the_code(self) -> None:
        body = {"error": {"name": "ActionExecute_ConnectedAccountNotFound"}}
        assert _is_dead_account_error(_not_found(body, "boom")) is True

    def test_message_is_the_fallback_when_the_body_is_not_json(self) -> None:
        error = _not_found(None, "Composio error 1810: no active connected account")
        assert _is_dead_account_error(error) is True

    def test_an_unrelated_404_is_not_a_dead_account(self) -> None:
        body = {"error": {"error_code": 1404, "name": "ToolNotFound"}}
        assert _is_dead_account_error(_not_found(body, "Tool not found")) is False


class TestUnrelatedFailuresPropagate:
    """The blanket catch this replaces turned every failure into an opaque
    `{"successful": False}` string and hid it from Sentry."""

    @pytest.mark.regression
    @pytest.mark.parametrize(
        "exc",
        [
            composio_client.InternalServerError(
                "Service unavailable",
                response=httpx.Response(
                    503, request=httpx.Request("POST", "https://backend.composio.dev/x")
                ),
                body=None,
            ),
            httpx.TimeoutException("timed out"),
            RuntimeError("a genuine bug"),
        ],
        ids=["5xx", "timeout", "bug"],
    )
    def test_it_raises_instead_of_returning_a_failure_dict(self, exc: Exception) -> None:
        action_func = _action_func(LangchainProvider(), _raises(exc))

        with pytest.raises(type(exc)):
            action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

    @pytest.mark.regression
    def test_a_404_that_is_not_the_dead_account_error_still_raises(self) -> None:
        body = {"error": {"error_code": 1404, "name": "ToolNotFound"}}
        action_func = _action_func(LangchainProvider(), _raises(_not_found(body, "Tool not found")))

        with pytest.raises(composio_client.NotFoundError):
            action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})


class TestDeadAccountReconciles:
    @pytest.mark.regression
    def test_it_expires_the_integration_and_asks_the_user_to_reconnect(self) -> None:
        provider = LangchainProvider()
        action_func = _action_func(provider, _raises(_not_found(DEAD_ACCOUNT_BODY, "no account")))

        with (
            patch.object(provider, "_dispatch") as dispatch,
            patch.object(provider, "_run_on_loop", return_value="https://gaia.test/connect/abc"),
            patch(f"{MODULE}.emit_integration_connection_required") as emit,
            patch(f"{MODULE}._expire_with_log_boundary") as expire,
        ):
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        expire.assert_called_once_with("user-1", "gmail", "no account")
        dispatch.assert_called_once()
        dispatch.call_args.args[0].close()  # the coroutine _dispatch would have run

        emit.assert_called_once_with("gmail", "Gmail")
        assert result["successful"] is False
        assert "connect" in result["error"].lower()

    async def test_the_dispatched_transition_does_not_notify_and_is_tagged_tool_execution(
        self,
    ) -> None:
        # The user is already being handed a connect card in this same turn, so a
        # notification saying the same thing seconds later is noise.
        with patch(f"{MODULE}.expire_user_integration") as expire:
            await _expire_with_log_boundary("user-1", "gmail", "no account")

        expire.assert_called_once_with(
            "user-1", "gmail", reason="no account", trigger="tool_execution", notify=False
        )

    def test_a_toolkit_with_no_gaia_integration_surfaces_the_raw_failure(self) -> None:
        provider = LangchainProvider()
        action_func = _action_func(
            provider, _raises(_not_found(DEAD_ACCOUNT_BODY, "no account")), toolkit="NOT_A_TOOLKIT"
        )

        with (
            patch.object(provider, "_dispatch") as dispatch,
            patch(f"{MODULE}.emit_integration_connection_required") as emit,
        ):
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        # Nothing to reconnect to, so no transition and no card — just the failure.
        dispatch.assert_not_called()
        emit.assert_not_called()
        assert result == {"successful": False, "error": "no account", "data": None}

    def test_a_trigger_option_call_with_no_user_skips_the_transition(self) -> None:
        # user_id is None for trigger-option calls, which bind the user at
        # get_tool(user_id=...) time. There is no user to expire and no chat
        # stream to write to — the webhook path covers that case instead.
        provider = LangchainProvider()
        action_func = _action_func(provider, _raises(_not_found(DEAD_ACCOUNT_BODY, "no account")))

        with (
            patch.object(provider, "_dispatch") as dispatch,
            patch(f"{MODULE}.emit_integration_connection_required") as emit,
        ):
            result = action_func(__runnable_config__={"metadata": {}})

        dispatch.assert_not_called()
        emit.assert_not_called()
        assert result == {"successful": False, "error": "no account", "data": None}


class TestNonRaisingDeadAccountResult:
    """Composio also reports a dead account without raising, as a
    `{"successful": False, "error": ...}` payload. That string match is far
    looser than the structured 404, so it only logs — driving the expiry
    transition off it would mark healthy integrations dead."""

    def test_it_logs_a_warning_and_passes_the_failure_through_untouched(self) -> None:
        provider = LangchainProvider()
        failure = {
            "successful": False,
            "error": "Composio error 1810: no active connected account for GMAIL",
            "data": None,
        }
        action_func = _action_func(provider, _returns(failure))

        with (
            patch.object(provider, "_dispatch") as dispatch,
            patch(f"{MODULE}.emit_integration_connection_required") as emit,
            patch(f"{MODULE}.log") as mock_log,
        ):
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        dispatch.assert_not_called()
        emit.assert_not_called()
        assert result == failure

        mock_log.warning.assert_called_once()
        assert "dead connected account" in mock_log.warning.call_args.args[0]


class TestExpiryDispatchNeedsALoop:
    def test_without_a_captured_loop_it_warns_and_skips_rather_than_crashing(self) -> None:
        # The connect card and the agent message must still ship even when the
        # transition cannot be dispatched.
        provider = LangchainProvider()
        provider._loop = None
        coro = MagicMock()

        with patch(f"{MODULE}.log") as mock_log:
            provider._dispatch(coro)

        coro.close.assert_called_once()
        mock_log.warning.assert_called_once()
