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

from app.models.hil_models import ApprovalProposal
from app.services.hil import gate
from app.services.hil.intent import IntentDecision
from app.services.hil.utils import GatedCall, unpack_tool_call

from .conftest import (
    CONVERSATION_ID,
    STREAM_ID,
    USER_ID,
    make_request,
    make_tool,
    resolver_returning,
)

MODULE = "app.services.hil.gate"
POLICY = "app.services.hil.policy"
TOOL_NAME = "delete_item"
SERVER_KEY = "mcp:srv_a:delete_item"
INTEGRATION_NAME = "Alpha Docs"
SUMMARY = "Delete item (Alpha Docs); id: i1"


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
        background=False,
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
    ledger.register = AsyncMock(return_value="ap_abc1234567")
    return ledger


@pytest.mark.unit
@pytest.mark.usefixtures("resolves_the_mcp_tool")
class TestLedgerPathResolvesForTheRunsUser:
    async def test_the_ledger_row_and_card_carry_the_servers_key_and_integration_name(
        self,
    ) -> None:
        ledger = _ledger()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()) as publish,
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

        assert verdict.settled is True
        assert judged.await_args.args[3] == SUMMARY


def _call() -> GatedCall:
    return unpack_tool_call(_execute_request())
