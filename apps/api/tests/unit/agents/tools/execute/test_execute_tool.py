"""The execute proxy tool — and the tool space it is confined to.

execute sits in EVERY subagent's tool set and resolves names globally, so it
is the one tool that can reach outside its agent's space. The factory is what
stops that: the unscoped instance is the executor's (its space IS the registry),
and a subagent builds one bound to its own dict.
"""

from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, patch

from langchain_core.tools import StructuredTool
import pytest

from app.agents.tools.execute.dispatch import (
    DispatchError,
    DispatchErrorKind,
    ToolExecutionResult,
    _dispatch_ticket,
    dispatch_tool,
)
from app.agents.tools.execute.execute_tool import build_execute_tool, execute
from app.constants.execute import EXECUTE_TOOL_NAME

MODULE = "app.agents.tools.execute.execute_tool"
CONFIG = {"configurable": {"user_id": "u1"}}


def _ok() -> ToolExecutionResult:
    return ToolExecutionResult(ok=True, resolved_name="GMAIL_SEND_EMAIL", output={"status": "sent"})


async def _invoke(tool, tool_name: str = "GMAIL_SEND_EMAIL") -> str:
    return await tool.ainvoke(
        {"task_description": "d", "tool_name": tool_name, "data": {}}, config=CONFIG
    )


@pytest.mark.unit
class TestDispatchTicketNames:
    """Ticket operations ride the proxy under reserved names — no bound tool, no schema; the branch runs before resolution, space checks, and validation."""

    def _config(self) -> dict[str, object]:
        return {
            "configurable": {
                "thread_id": "executor_conv-1",
                "user_id": "u1",
                "conversation_id": "conv-1",
            }
        }

    async def test_approve_routes_to_redeem_not_resolve(self) -> None:
        from app.agents.tools.execute import dispatch as dispatch_module
        from app.agents.tools.execute.dispatch import dispatch_tool
        from app.models.hil_models import LedgerState
        from app.services.hil.ledger_decide import RedeemResult

        redeemed = RedeemResult(
            ok=True, approval_id="ap_1", state=LedgerState.EXECUTED, detail="sent"
        )
        with (
            patch.object(dispatch_module, "resolve_tool", new=AsyncMock()) as resolve,
            patch(
                "app.services.hil.ledger_decide.redeem_approved",
                new=AsyncMock(return_value=redeemed),
            ) as redeem,
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="approve",
                data={"id": "ap_1"},
                config=self._config(),
            )

        resolve.assert_not_awaited()
        redeem.assert_awaited_once_with(
            "ap_1", user_id="u1", conversation_id="conv-1", caller="executor_conv-1"
        )
        assert result.ok is True
        assert "Executed 'ap_1'" in str(result.output)

    async def test_revoke_routes_to_revoke_ticket(self) -> None:
        from app.agents.tools.execute import dispatch as dispatch_module
        from app.agents.tools.execute.dispatch import dispatch_tool

        with (
            patch.object(dispatch_module, "resolve_tool", new=AsyncMock()) as resolve,
            patch(
                "app.services.hil.ledger_decide.revoke_ticket",
                new=AsyncMock(return_value="Revoked 'ap_1'."),
            ) as revoke,
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="revoke",
                data={"id": "ap_1"},
                config=self._config(),
            )

        resolve.assert_not_awaited()
        revoke.assert_awaited_once_with(
            "ap_1", user_id="u1", conversation_id="conv-1", caller="executor_conv-1"
        )
        assert result.ok is True
        assert "Revoked" in str(result.output)

    async def test_missing_id_is_guidance_not_failure(self) -> None:
        """A ticket call without an id answers with the shape, not an error — refusals are read by the model, not counted as failures."""
        from app.agents.tools.execute.dispatch import dispatch_tool

        result = await dispatch_tool(
            user_id="u1",
            tool_name="approve",
            data={},
            config=self._config(),
        )

        assert result.ok is True
        assert '{"id"' in str(result.output)

    async def test_ticket_names_never_resolve(self) -> None:
        """Fail closed: even if a provider catalog one day contains 'approve', resolution refuses it — tickets dispatch before resolution, always."""
        from app.agents.tools.execute.resolver import resolve_tool

        assert await resolve_tool("u1", "approve") is None
        assert await resolve_tool("u1", "revoke") is None

    async def test_tickets_refused_on_integration_only_surface(self) -> None:
        """Sandbox scripts carry no conversation identity, so every ticket check would miss — refuse loudly instead."""
        from app.agents.tools.execute import dispatch as dispatch_module
        from app.agents.tools.execute.dispatch import dispatch_tool

        with (
            patch.object(dispatch_module, "resolve_tool", new=AsyncMock()),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="approve",
                data={"id": "ap_1"},
                config=self._config(),
                integration_only=True,
            )

        assert result.ok is False
        assert result.error is not None
        assert "conversation ticket" in result.error.detail

    async def test_ticket_bypasses_caller_tool_space(self) -> None:
        """Control-plane ops belong to no provider space: a scoped subagent redeems its own ticket even though 'approve' is in no registry."""
        from app.agents.tools.execute import dispatch as dispatch_module
        from app.agents.tools.execute.dispatch import dispatch_tool
        from app.models.hil_models import LedgerState
        from app.services.hil.ledger_decide import RedeemResult

        redeemed = RedeemResult(
            ok=True, approval_id="ap_1", state=LedgerState.EXECUTED, detail="sent"
        )
        with (
            patch(
                "app.services.hil.ledger_decide.redeem_approved",
                new=AsyncMock(return_value=redeemed),
            ) as redeem,
        ):
            with patch.object(dispatch_module, "resolve_tool", new=AsyncMock()):
                result = await dispatch_tool(
                    user_id="u1",
                    tool_name="approve",
                    data={"id": "ap_1"},
                    config=self._config(),
                    scoped_tool_names={"GMAIL_SEND_EMAIL"},
                )

        redeem.assert_awaited_once()
        assert result.ok is True


@pytest.mark.unit
class TestExecuteToolScope:
    async def test_the_registry_instance_is_unscoped(self) -> None:
        """The executor's space is the whole registry — scoping it would refuse every tool it is supposed to run."""
        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=_ok())) as dispatch:
            await _invoke(execute)
        assert dispatch.await_args.kwargs["scoped_tool_names"] is None

    async def test_a_scoped_instance_passes_its_live_tool_set(self) -> None:
        """Read at CALL time, not build time: a subagent keeps adding to its dict (todo tools, finish_task) after execute is put in it, and a snapshot taken then would refuse every tool added afterwards."""
        scoped_tools: dict[str, StructuredTool] = {}
        proxy = build_execute_tool(scoped_tools)
        scoped_tools["GMAIL_SEND_EMAIL"] = StructuredTool.from_function(
            func=lambda: None, name="GMAIL_SEND_EMAIL", description="Send."
        )
        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=_ok())) as dispatch:
            await _invoke(proxy)
        assert dispatch.await_args.kwargs["scoped_tool_names"] == {"GMAIL_SEND_EMAIL"}

    async def test_a_scoped_instance_keeps_the_proxy_name(self) -> None:
        """The name is a constant five other seams key on (HIL unwrap, the stream formatter, the analytics dedupe) — a per-agent instance must not rename it."""
        assert build_execute_tool({}).name == EXECUTE_TOOL_NAME == execute.name

    async def test_a_refusal_comes_back_as_a_structured_error(self) -> None:
        refusal = ToolExecutionResult(
            ok=False,
            resolved_name="SLACK_SEND_MESSAGE",
            error=DispatchError(
                kind=DispatchErrorKind.OUT_OF_SCOPE, detail="not here", hint="ask the executor"
            ),
        )
        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=refusal)):
            body = json.loads(await _invoke(build_execute_tool({}), "SLACK_SEND_MESSAGE"))
        assert body == {
            "ok": False,
            "error": "out_of_scope",
            "detail": "not here",
            "next": "ask the executor",
        }


@pytest.mark.unit
class TestTicketIdentity:
    """A ticket is checked against the caller's own identity; missing parts are blank, never another run's."""

    @pytest.mark.parametrize(
        ("user_id", "configurable", "expected"),
        [
            (
                "u-param",
                {"user_id": "u-cfg", "thread_id": "t1", "conversation_id": "c1"},
                {"user_id": "u-cfg", "conversation_id": "c1", "caller": "t1"},
            ),
            ("u-param", {}, {"user_id": "u-param", "conversation_id": "", "caller": ""}),
            (None, {}, {"user_id": "", "conversation_id": "", "caller": ""}),
        ],
        ids=["configurable_wins", "falls_back_to_the_dispatch_user", "nobody"],
    )
    async def test_a_revoke_carries_the_callers_identity(
        self, user_id: str | None, configurable: dict[str, str], expected: dict[str, str]
    ) -> None:
        with patch(
            "app.services.hil.ledger_decide.revoke_ticket",
            new=AsyncMock(return_value="Revoked 'ap_1'."),
        ) as revoke:
            await dispatch_tool(
                user_id=user_id,
                tool_name="revoke",
                data={"id": "ap_1"},
                config={"configurable": configurable},
            )
        revoke.assert_awaited_once_with("ap_1", **expected)

    @pytest.mark.parametrize("ticket_id", ["", 7], ids=["blank", "not_a_string"])
    async def test_an_unusable_id_is_answered_with_the_expected_shape(
        self, ticket_id: object
    ) -> None:
        with patch("app.services.hil.ledger_decide.revoke_ticket", new=AsyncMock()) as revoke:
            result = await dispatch_tool(
                user_id="u1", tool_name="revoke", data={"id": ticket_id}, config=CONFIG
            )
        revoke.assert_not_awaited()
        assert result.output == 'Name the ticket: revoke needs data {"id": "<approval_id>"}.'

    async def test_a_ticket_name_with_no_handler_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="Unknown ticket operation 'redeem'."):
            await _dispatch_ticket(
                user_id="u1", tool_name="redeem", data={"id": "ap_1"}, config=CONFIG
            )


@pytest.mark.unit
class TestExecuteToolCall:
    """What a freshly built proxy hands dispatch, and how it renders the answer back to the model."""

    @pytest.mark.parametrize("space", [None, {}], ids=["executor", "subagent"])
    async def test_the_call_is_dispatched_as_the_calling_user(
        self, space: dict[str, StructuredTool] | None
    ) -> None:
        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=_ok())) as dispatch:
            await build_execute_tool(space).ainvoke(
                {"task_description": "d", "tool_name": "GMAIL_SEND_EMAIL", "data": {"to": "a"}},
                config=CONFIG,
            )
        kwargs = dispatch.await_args.kwargs
        assert kwargs["user_id"] == "u1"
        assert kwargs["tool_name"] == "GMAIL_SEND_EMAIL"
        assert kwargs["data"] == {"to": "a"}
        assert kwargs["config"]["configurable"]["user_id"] == "u1"

    @pytest.mark.parametrize(
        ("output", "rendered"),
        [
            ("already text", "already text"),
            (
                {"at": datetime(2026, 1, 2, tzinfo=UTC)},
                json.dumps({"at": "2026-01-02 00:00:00+00:00"}),
            ),
        ],
        ids=["text", "structured"],
    )
    async def test_a_tools_output_reaches_the_model_as_text(
        self, output: object, rendered: str
    ) -> None:
        result = ToolExecutionResult(ok=True, resolved_name="GMAIL_SEND_EMAIL", output=output)
        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=result)):
            assert await _invoke(build_execute_tool()) == rendered
