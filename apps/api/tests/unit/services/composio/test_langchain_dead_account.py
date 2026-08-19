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

from composio.types import Tool
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


def _composio_tool(slug: str = "GMAIL_FETCH_MESSAGES") -> Tool:
    """The minimum Composio tool descriptor `wrap_tool` needs."""
    return Tool(
        slug=slug,
        name=slug,
        description="Fetch messages.",
        # `title` is load-bearing: the wrapper builds a pydantic model class from
        # each schema and uses it as the class name.
        input_parameters={"type": "object", "title": "GmailFetchMessagesRequest", "properties": {}},
        output_parameters={
            "type": "object",
            "title": "GmailFetchMessagesResponse",
            "properties": {},
        },
        toolkit={"slug": "gmail", "name": "Gmail", "logo": ""},
        tags=[],
        scopes=[],
        version="latest",
        available_versions=["latest"],
        # Mixed casing is the SDK's, not a typo: `displayName` is aliased while its
        # siblings are not.
        deprecated={
            "available_versions": ["latest"],
            "displayName": "Fetch messages",
            "is_deprecated": False,
            "toolkit": {"slug": "gmail", "name": "Gmail", "logo": ""},
            "version": "latest",
        },
        is_deprecated=False,
        no_auth=False,
    )


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
        # Answers from its arguments: a fixed value cannot tell the real lookup
        # from one asked about the wrong user, which is how the prompt would
        # offer a first-time connect for a connection that plainly died.
        patch.object(
            user_integration_repository,
            "is_expired",
            AsyncMock(side_effect=lambda uid, iid: expired and (uid, iid) == ("user-1", "gmail")),
        ),
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

    @pytest.mark.parametrize(
        "detail",
        [
            {"error_code": 1810},
            {"code": 1810},
            {"name": "ActionExecute_ConnectedAccountNotFound"},
            {"type": "ActionExecute_ConnectedAccountNotFound"},
        ],
        ids=["error_code", "code", "name", "type"],
    )
    def test_either_spelling_of_the_code_and_the_name_is_recognised(self, detail: dict) -> None:
        """Composio's error envelope is not versioned and has shipped both
        spellings of each field. The message here carries NO marker, so only the
        structured field under test can classify it — recognising just one
        spelling would let a dead account through as an unhandled 404."""
        assert wrapper._is_dead_account_error(_not_found({"error": detail}, "boom")) is True

    def test_a_dead_account_message_is_recognised_whatever_its_casing(self) -> None:
        """The fallback matches lowercase markers, so it has to normalise first —
        and this sentence carries no 1810 to be rescued by."""
        error = _not_found(None, "No Active Connected Account for GMAIL")
        assert wrapper._is_dead_account_error(error) is True


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

    async def test_the_transition_runs_under_its_own_named_wide_event_boundary(self) -> None:
        """The dispatch arrives from an executor thread with no boundary of its own,
        so without this one every `log.set()` inside the transition is discarded."""
        with (
            patch(f"{MODULE}.expire_user_integration", AsyncMock()),
            patch(f"{MODULE}.log_context") as boundary,
        ):
            await wrapper._expire_with_log_boundary("user-1", "gmail", "no account")

        boundary.assert_called_once_with("composio_tool_integration_expiry", user_id="user-1")

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


class TestASuccessfulCallIsNeverReportedDead:
    def test_dead_account_wording_inside_a_successful_payload_is_not_a_dead_account(self) -> None:
        """Tool payloads echo arbitrary provider text — a successful search whose
        results mention "no active connected account" is a result, not a failure.
        Reporting it would put a false dead-account warning on a healthy run."""
        provider = LangchainProvider()
        action_func = _action_func(
            provider,
            _returns(
                {
                    "successful": True,
                    "error": "no active connected account",
                    "data": {"messages": []},
                }
            ),
        )

        with patch(f"{MODULE}.log") as mock_log:
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        assert result["successful"] is True
        assert mock_log.warning.call_args_list == []


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


class TestTheProviderCapturesItsLoop:
    async def test_a_provider_built_on_the_loop_holds_it_for_the_executor_threads(self) -> None:
        """The wrapped tool callables are sync and run in an executor thread; the
        loop captured here is the only way back to async work from there."""
        assert LangchainProvider()._loop is asyncio.get_running_loop()

    def test_a_provider_built_off_the_loop_captures_nothing_yet(self) -> None:
        assert LangchainProvider()._loop is None

    async def test_wrapping_a_tool_tops_up_a_capture_the_constructor_missed(self) -> None:
        """The provider is a lazy singleton, so whichever caller builds it first may
        be off-loop — but tools are fetched per request from the running loop.
        Without this second chance the reconnect prompt is skipped for the whole
        process, which is how it failed the first time."""
        provider = await asyncio.to_thread(LangchainProvider)
        assert provider._loop is None

        provider.wrap_tool(_composio_tool(), _returns({"successful": True}))

        assert provider._loop is asyncio.get_running_loop()

    async def test_wrapping_does_not_steal_an_already_captured_loop(self) -> None:
        provider = LangchainProvider()
        captured = provider._loop

        await asyncio.to_thread(
            provider.wrap_tool, _composio_tool(), _returns({"successful": True})
        )

        assert provider._loop is captured


class TestTheDeadAccountWideEvent:
    """A dead account is invisible to the user beyond one failed tool call, so
    this event is what says which tool, which account and why."""

    async def test_it_records_the_invocation_and_the_reason_it_was_classified_dead(self) -> None:
        provider = LangchainProvider()
        provider._loop = asyncio.get_running_loop()
        long_reason = "no connected account " + "x" * 300
        action_func = _action_func(provider, _raises(_not_found(DEAD_ACCOUNT_BODY, long_reason)))

        with (
            patch(f"{MODULE}.expire_user_integration", AsyncMock()),
            patch(f"{MODULE}.log") as mock_log,
            _ui_chat_turn(MagicMock()),
        ):
            await asyncio.to_thread(
                action_func, __runnable_config__={"metadata": {"user_id": "user-1"}}
            )

        assert mock_log.set.call_args.kwargs["composio_tool_invocation"] == {
            "tool": "GMAIL_FETCH_MESSAGES",
            "toolkit": "GMAIL",
            "user_id": "user-1",
            "successful": False,
            "outcome": "dead_connected_account",
        }
        mock_log.warning.assert_called_once()
        assert "dead connected account" in mock_log.warning.call_args.args[0]
        kwargs = mock_log.warning.call_args.kwargs
        assert kwargs["tool"] == "GMAIL_FETCH_MESSAGES"
        assert kwargs["toolkit"] == "GMAIL"
        assert kwargs["user_id"] == "user-1"
        assert kwargs["integration_id"] == "gmail"
        # Bounded: the raw Composio sentence can be arbitrarily long and this
        # field is carried on every dead-account event.
        assert kwargs["reason"] == long_reason[:200]
        assert len(kwargs["reason"]) == 200


class TestTheReconnectPromptIsBounded:
    async def test_a_prompt_that_overruns_its_budget_degrades_to_the_raw_error(self) -> None:
        """The wait blocks an executor thread inside the user's turn, so it cannot
        be unbounded — on timeout the agent gets the underlying failure instead."""
        provider = LangchainProvider()
        provider._loop = asyncio.get_running_loop()
        action_func = _action_func(provider, _raises(_not_found(DEAD_ACCOUNT_BODY, "no account")))

        async def _slow(*_a: object, **_k: object) -> str:
            await asyncio.sleep(1)
            return "the reconnect prompt"

        with (
            patch(f"{MODULE}._expire_and_request_reconnect", _slow),
            patch(f"{MODULE}._RECONNECT_PROMPT_TIMEOUT_S", 0.01),
            patch(f"{MODULE}.log") as mock_log,
        ):
            result = await asyncio.to_thread(
                action_func, __runnable_config__={"metadata": {"user_id": "user-1"}}
            )

        assert result == {"successful": False, "error": "no account", "data": None}
        timeouts = [c for c in mock_log.warning.call_args_list if "Timed out" in str(c.args[0])]
        assert len(timeouts) == 1
        assert timeouts[0].kwargs == {"timeout_s": 0.01}


class TestTheToolCallItselfIsForwarded:
    async def test_the_named_tool_and_its_arguments_reach_composio(self) -> None:
        """A dropped tool name or argument bag would execute the wrong call — and
        every stub that answers with a fixed value looks identical to that."""
        seen: dict[str, object] = {}

        def execute_tool(tool: str, kwargs: dict[str, Any]) -> dict[str, Any]:
            seen["tool"] = tool
            seen["kwargs"] = kwargs
            return {"successful": True, "data": {}, "error": None}

        action_func = _action_func(LangchainProvider(), execute_tool)
        action_func(subject="hello", __runnable_config__={"metadata": {"user_id": "user-1"}})

        assert seen["tool"] == "GMAIL_FETCH_MESSAGES"
        assert seen["kwargs"]["subject"] == "hello"
