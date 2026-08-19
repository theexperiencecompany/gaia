"""Dead-connected-account reconciliation in the Composio tool wrapper.

Regression cover for GAIA-BACKEND-2ZG: a revoked Composio account made
`execute_tool` raise `NotFoundError`, which PR #932 wrapped in a blanket
`except Exception` returning `{"successful": False, "error": str(e)}`. That
stopped the 500 but left the user stuck (nothing ever recorded the connection
as dead) and swallowed timeouts, 5xx and real bugs into the same opaque string.

The wrapper is imported as a module rather than by symbol: the regression lane
replays marked tests against the base revision, where the private helpers below
do not exist yet. ``from ... import _helper`` would break at collection and prove
nothing; attribute access fails inside the test body, where it counts as a real
failure.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import composio_client
import httpx
import pytest

from app.db.repositories.user_integrations import user_integration_repository
from app.services.composio import langchain_composio_service as wrapper
from app.services.composio.langchain_composio_service import LangchainProvider

MODULE = "app.services.composio.langchain_composio_service"
CHECKER = "app.utils.integration_checker"

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


@contextmanager
def _ui_chat_turn(writer: MagicMock, *, expired: bool = True) -> Iterator[None]:
    """Stand in for the graph run the wrapper's connect prompt writes into."""
    with (
        patch(f"{CHECKER}.get_config", return_value={"configurable": {"source_category": "ui"}}),
        patch(f"{CHECKER}.get_stream_writer", return_value=writer),
        patch(f"{CHECKER}.build_connect_link_url", AsyncMock(return_value=None)),
        patch.object(user_integration_repository, "is_expired", AsyncMock(return_value=expired)),
    ):
        yield


class TestDeadAccountClassifier:
    """A false positive here marks a healthy integration expired, so the
    classifier must key on the structured error and not merely on a 404."""

    def test_structured_error_code_is_recognized(self) -> None:
        assert wrapper._is_dead_account_error(_not_found(DEAD_ACCOUNT_BODY, "boom")) is True

    def test_structured_error_name_is_recognized_without_the_code(self) -> None:
        body = {"error": {"name": "ActionExecute_ConnectedAccountNotFound"}}
        assert wrapper._is_dead_account_error(_not_found(body, "boom")) is True

    def test_message_is_the_fallback_when_the_body_is_not_json(self) -> None:
        error = _not_found(None, "Composio error 1810: no active connected account")
        assert wrapper._is_dead_account_error(error) is True

    def test_an_unrelated_404_is_not_a_dead_account(self) -> None:
        body = {"error": {"error_code": 1404, "name": "ToolNotFound"}}
        assert wrapper._is_dead_account_error(_not_found(body, "Tool not found")) is False


class TestUnrelatedFailuresPropagate:
    """The blanket catch this replaces turned every failure into an opaque
    `{"successful": False}` string and hid it from Sentry.

    Unmarked on purpose: that catch only ever existed in the PR #932 diff, never
    on master, so these pass on the base revision. They guard the narrow catch
    from widening again rather than pinning a shipped bug.
    """

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

    def test_a_404_that_is_not_the_dead_account_error_still_raises(self) -> None:
        body = {"error": {"error_code": 1404, "name": "ToolNotFound"}}
        action_func = _action_func(LangchainProvider(), _raises(_not_found(body, "Tool not found")))

        with pytest.raises(composio_client.NotFoundError):
            action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})


class TestDeadAccountReconciles:
    @pytest.mark.regression
    async def test_it_expires_the_integration_and_asks_the_user_to_reconnect(self) -> None:
        """Driven through the real executor-thread -> event-loop bridge the wrapper
        uses in production, because that hop is what carries the graph's stream
        context to the connect prompt. Mocking it away proves nothing about it."""
        provider = LangchainProvider()
        provider._loop = asyncio.get_running_loop()
        action_func = _action_func(provider, _raises(_not_found(DEAD_ACCOUNT_BODY, "no account")))
        writer = MagicMock()

        with (
            patch(f"{MODULE}.expire_user_integration", AsyncMock()) as expire,
            _ui_chat_turn(writer),
        ):
            result = await asyncio.to_thread(
                action_func, __runnable_config__={"metadata": {"user_id": "user-1"}}
            )

        expire.assert_awaited_once_with(
            "user-1", "gmail", reason="no account", trigger="tool_execution", notify=False
        )

        # The transition runs in this very turn, so the card and the agent copy
        # both say expired — not "you never connected this".
        card = writer.call_args.args[0]["integration_connection_required"]
        assert card == {
            "integration_id": "gmail",
            "expired": True,
            "message": "Your Gmail connection expired. Sign in again to keep using it.",
        }
        assert result["successful"] is False
        assert "EXPIRED" in result["error"]
        assert "sign in again" in result["error"]

    async def test_the_expiry_is_persisted_before_the_prompt_reads_the_status(self) -> None:
        """Racing the write would show first-time-connect copy for a connection
        that plainly died, so the order is the contract."""
        provider = LangchainProvider()
        provider._loop = asyncio.get_running_loop()
        action_func = _action_func(provider, _raises(_not_found(DEAD_ACCOUNT_BODY, "no account")))
        calls: list[str] = []

        async def _expire(*_a: object, **_k: object) -> None:
            calls.append("expire")

        async def _is_expired(*_a: object, **_k: object) -> bool:
            calls.append("read_status")
            return True

        with (
            patch(f"{MODULE}.expire_user_integration", AsyncMock(side_effect=_expire)),
            patch(
                f"{CHECKER}.get_config", return_value={"configurable": {"source_category": "ui"}}
            ),
            patch(f"{CHECKER}.get_stream_writer", return_value=MagicMock()),
            patch.object(
                user_integration_repository, "is_expired", AsyncMock(side_effect=_is_expired)
            ),
        ):
            await asyncio.to_thread(
                action_func, __runnable_config__={"metadata": {"user_id": "user-1"}}
            )

        assert calls == ["expire", "read_status"]

    async def test_the_dispatched_transition_does_not_notify_and_is_tagged_tool_execution(
        self,
    ) -> None:
        # The user is already being handed a connect card in this same turn, so a
        # notification saying the same thing seconds later is noise.
        with patch(f"{MODULE}.expire_user_integration") as expire:
            await wrapper._expire_with_log_boundary("user-1", "gmail", "no account")

        expire.assert_called_once_with(
            "user-1", "gmail", reason="no account", trigger="tool_execution", notify=False
        )

    def test_a_toolkit_with_no_gaia_integration_surfaces_the_raw_failure(self) -> None:
        provider = LangchainProvider()
        action_func = _action_func(
            provider, _raises(_not_found(DEAD_ACCOUNT_BODY, "no account")), toolkit="NOT_A_TOOLKIT"
        )

        with patch.object(provider, "_run_on_loop") as bridge:
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        # Nothing to reconnect to, so no transition and no card — just the failure.
        bridge.assert_not_called()
        assert result == {"successful": False, "error": "no account", "data": None}

    def test_a_trigger_option_call_with_no_user_skips_the_transition(self) -> None:
        # user_id is None for trigger-option calls, which bind the user at
        # get_tool(user_id=...) time. There is no user to expire and no chat
        # stream to write to — the webhook path covers that case instead.
        provider = LangchainProvider()
        action_func = _action_func(provider, _raises(_not_found(DEAD_ACCOUNT_BODY, "no account")))

        with patch.object(provider, "_run_on_loop") as bridge:
            result = action_func(__runnable_config__={"metadata": {}})

        bridge.assert_not_called()
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
            patch.object(provider, "_run_on_loop") as bridge,
            patch(f"{MODULE}.log") as mock_log,
        ):
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        bridge.assert_not_called()
        assert result == failure

        mock_log.warning.assert_called_once()
        assert "dead connected account" in mock_log.warning.call_args.args[0]


class TestReconnectPromptNeedsALoop:
    def test_without_a_captured_loop_it_degrades_to_the_raw_error(self) -> None:
        """No loop means no expiry and no prompt — the tool must still return the
        underlying failure rather than a None error the agent cannot read."""
        provider = LangchainProvider()
        provider._loop = None
        action_func = _action_func(provider, _raises(_not_found(DEAD_ACCOUNT_BODY, "no account")))

        with patch(f"{MODULE}.log") as mock_log:
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        assert result == {"successful": False, "error": "no account", "data": None}
        assert any(
            "No event loop captured" in call.args[0] for call in mock_log.warning.call_args_list
        )
