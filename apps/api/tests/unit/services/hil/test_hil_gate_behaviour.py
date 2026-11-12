"""Who the gate resolves an execute-proxied MCP tool for: the run's user and the live request.

An execute call reaches the real tool only through the resolver, scoped to the user. A
gate that resolves for the wrong user (or no request) files the card, the stored rule and
the auto judge's deny list under the wrong key and integration name.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.tools import BaseTool
import pytest

from app.models.hil_models import ApprovalProposal, HILApprovalStatus
from app.services.hil import gate
from app.services.hil.intent import AutoContext, IntentDecision, JudgedCall
from app.services.hil.utils import GatedCall, unpack_tool_call

from .conftest import (
    CONVERSATION_ID,
    STREAM_ID,
    USER_ID,
    make_record,
    make_request,
    make_tool,
    registered_row,
    resolver_returning,
)

MODULE = "app.services.hil.gate"
POLICY = "app.services.hil.policy"
TOOL_NAME = "delete_item"
SERVER_KEY = "mcp:srv_a:delete_item"
INTEGRATION_NAME = "Alpha Docs"
SUMMARY = "Delete item in Alpha Docs: i1"


def _mcp_tool() -> BaseTool:
    return make_tool(
        name=TOOL_NAME,
        description="Delete an item.",
        metadata={"integration_id": "srv_a", "mcp_server_name": TOOL_NAME},
    )


def _execute_request() -> ToolCallRequest:
    return make_request(
        name="execute",
        args={"task_description": "tidy up", "tool_name": TOOL_NAME, "data": {"id": "i1"}},
        tool=make_tool(name="execute", description="Run an integration tool by name."),
    )


def _context() -> gate.GateContext:
    return gate.GateContext(
        stream_id=STREAM_ID,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        user_messages=["delete the item"],
        pausable=True,
    )


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
        yield


@pytest.fixture
def resolves_the_mcp_tool() -> Iterator[None]:
    """Make the live MCP tool reachable only through the user-scoped resolver."""
    registry = MagicMock()
    registry.get_category_of_tool.return_value = None
    registry.get_category.return_value = None
    with (
        patch(f"{POLICY}.resolve_tool", new=resolver_returning(_mcp_tool())),
        patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
        patch(
            f"{MODULE}.IntegrationResolver.resolve",
            new=AsyncMock(return_value=SimpleNamespace(name=INTEGRATION_NAME)),
        ),
    ):
        yield


def _ledger() -> MagicMock:
    ledger = MagicMock()
    ledger.find_live = AsyncMock(return_value=None)
    ledger.find_latest_denied = AsyncMock(return_value=None)
    ledger.register = AsyncMock(return_value=registered_row())
    return ledger


@pytest.mark.unit
@pytest.mark.usefixtures("resolves_the_mcp_tool")
class TestLedgerPathResolvesForTheRunsUser:
    async def test_the_ledger_row_and_card_carry_the_servers_key_and_integration_name(
        self,
    ) -> None:
        ledger = _ledger()
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()) as publish,
        ):
            result = await gate.decide_tool_call(_execute_request())

        assert result is not None
        assert str(result.content).startswith(f"PENDING ap_abc1234567: {SUMMARY} queued")
        proposal: ApprovalProposal = ledger.register.await_args.args[0]
        assert proposal.tool_key == SERVER_KEY
        assert proposal.summary == SUMMARY
        card = publish.await_args.args[0]
        assert card.integration_name == INTEGRATION_NAME
        assert card.summary == SUMMARY

    async def test_auto_mode_hands_the_judge_the_summary_naming_the_integration(self) -> None:
        judged = AsyncMock(return_value=IntentDecision(outcome="accept", reason="asked for"))
        with (
            patch(f"{MODULE}._judge", new=judged),
        ):
            verdict = await gate._auto_ledger_verdict(
                _execute_request(), _context(), _call(), "auto"
            )

        assert verdict.runs is True
        assert judged.await_args.args[4] == SUMMARY


def _call() -> GatedCall:
    return unpack_tool_call(_execute_request())


@pytest.mark.unit
@pytest.mark.usefixtures("resolves_the_mcp_tool")
class TestLivePathResolvesForTheRunsUser:
    async def test_the_pending_card_names_the_integration_of_the_servers_tool(self) -> None:
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()) as publish,
        ):
            pending = await gate._decide(_execute_request(), _context(), "ask", _call())

        assert isinstance(pending, gate._Pending)
        assert pending.summary == SUMMARY
        assert pending.integration_name == INTEGRATION_NAME
        assert publish.await_args.args[0].integration_name == INTEGRATION_NAME

    async def test_always_allow_stores_the_rule_under_the_servers_key(self) -> None:
        record = make_record(status=HILApprovalStatus.APPROVED, scope="always_tool")
        with (
            patch(f"{MODULE}.publish_decision", new=AsyncMock()),
            patch(f"{MODULE}.set_tool_override", new=AsyncMock()) as store,
        ):
            cleared = await gate._apply(record, _execute_request(), _context(), _call())

        assert cleared is None
        store.assert_awaited_once_with(USER_ID, SERVER_KEY, False)

    @pytest.mark.parametrize(
        ("never_auto", "expected"),
        [(frozenset({SERVER_KEY}), True), (frozenset({TOOL_NAME}), False)],
    )
    async def test_the_judge_is_told_whether_the_servers_key_is_on_the_deny_list(
        self, never_auto: frozenset[str], expected: bool
    ) -> None:
        judge = AsyncMock(return_value=IntentDecision(outcome="ask", reason="unsure"))

        async def deny_list_of(user_id: str) -> frozenset[str]:
            return never_auto if user_id == USER_ID else frozenset()

        with (
            patch(f"{MODULE}.has_pausing_sibling", new=AsyncMock(return_value=False)),
            patch(f"{MODULE}._auto_history", new=AsyncMock(return_value=MagicMock())),
            patch(f"{MODULE}._never_auto_tools", new=deny_list_of),
            patch(f"{MODULE}.is_jev_judge_enabled", new=AsyncMock(return_value=False)),
            patch(f"{MODULE}.judge_intent", new=judge),
        ):
            await gate._judge(_execute_request(), _context(), _call(), None, SUMMARY)

        auto_context: AutoContext = judge.await_args.args[0]
        assert auto_context.never_auto is expected
        judged: JudgedCall = judge.await_args.kwargs["call"]
        assert judged.description == "Delete an item."
