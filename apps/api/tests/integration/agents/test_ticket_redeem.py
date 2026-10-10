"""Redeeming an approved ticket through the real execute dispatch, inside a real LangGraph run.

The ledger repository and the card settlement are the mocked seams; the ticket
routing, the redeem and the tool invocation are production code.
"""

from typing import TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
import pytest

from app.agents.tools.execute import dispatch as dispatch_module
from app.agents.tools.execute.dispatch import ToolExecutionResult, dispatch_tool
from app.agents.tools.execute.resolver import ResolvedTool
from app.models.hil_models import LedgerState
from app.services.hil import ledger_decide

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
CARD_FRAME = {"integration_connection_required": {"integration_id": "gmail"}}


@tool
async def show_card() -> str:
    """Stream a card to the user, as connect_integration does."""
    get_stream_writer()(CARD_FRAME)
    return "card shown"


class _State(TypedDict):
    result: ToolExecutionResult | None


async def _redeem_node(state: _State, config: RunnableConfig) -> _State:
    del state
    result = await dispatch_tool(
        user_id=USER_ID, tool_name="approve", data={"id": "ap_card"}, config=config
    )
    return {"result": result}


def _approved_row() -> MagicMock:
    row = MagicMock()
    row.approval_id = "ap_card"
    row.conversation_id = "conv-1"
    row.user_id = USER_ID
    row.tool_name = "show_card"
    row.args = {}
    row.account = None
    row.state = LedgerState.APPROVED
    row.owner_agent = "executor_conv-1"
    return row


@pytest.mark.integration
@pytest.mark.regression
async def test_an_approved_tool_streams_its_card_on_the_run_that_redeems_it() -> None:
    """Regression: the redeem rebuilt a bare config, so get_stream_writer raised '__pregel_runtime'."""
    repo = MagicMock()
    repo.get_by_approval_id = AsyncMock(return_value=_approved_row())
    repo.claim_executing = AsyncMock(return_value=True)
    repo.transition = AsyncMock(return_value=True)
    graph = (
        StateGraph(_State)
        .add_node("redeem", _redeem_node)
        .add_edge(START, "redeem")
        .add_edge("redeem", END)
        .compile()
    )
    config: RunnableConfig = {
        "configurable": {
            "thread_id": "executor_conv-1",
            "user_id": USER_ID,
            "conversation_id": "conv-1",
        }
    }

    with (
        patch.object(ledger_decide, "approval_ledger_repository", new=repo),
        patch.object(ledger_decide, "_settle_terminal", new=AsyncMock()),
        patch.object(ledger_decide, "sync_conversation_approval_flag", new=AsyncMock()),
        patch.object(
            dispatch_module,
            "resolve_tool",
            new=AsyncMock(return_value=ResolvedTool("show_card", show_card, is_integration=False)),
        ),
    ):
        chunks = [
            c
            async for c in graph.astream({"result": None}, config, stream_mode=["custom", "values"])
        ]

    assert ("custom", CARD_FRAME) in chunks
    final = chunks[-1][1]["result"]
    assert final.output == "Executed 'ap_card' (executed): card shown"
    repo.transition.assert_awaited_once_with("ap_card", LedgerState.EXECUTING, LedgerState.EXECUTED)
