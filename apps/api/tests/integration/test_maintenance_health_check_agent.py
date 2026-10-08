"""The maintenance sweep's health check, driven through the real comms entry point.

Real: _call_health_check_agent, call_agent_silent, _core_agent_logic,
construct_langchain_messages, build_initial_state, execute_graph_silent.
Faked: the compiled graph, and the I/O boundaries around the turn (user load,
context assembly, onboarding lookup).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from unittest.mock import AsyncMock, patch

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    HumanMessage,
    SystemMessage,
)
import pytest

from app.agents.context.assemble import AssembledContext
from app.models.user_models import AuthenticatedUser
from app.workers.tasks.maintenance_sweep_tasks import _call_health_check_agent

PROMPT = "A tracked todo has been dormant for 7 days. Title: Daily Inbox Briefing"
VERDICT = "EXECUTE: draft the briefing from today's inbox"


class _RecordingGraph:
    """A compiled-graph stand-in: records the state it was run with and answers once."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.initial_state: Mapping[str, object] | None = None

    async def astream(
        self, initial_state: Mapping[str, object], **_kwargs: object
    ) -> AsyncIterator[tuple[tuple[str, ...], str, object]]:
        self.initial_state = initial_state
        yield ((), "messages", (AIMessageChunk(content=self.reply, id="ai-1"), {}))
        yield ((), "updates", {"agent": {"messages": [AIMessage(content=self.reply, id="ai-1")]}})


@pytest.fixture
def graph() -> Iterator[_RecordingGraph]:
    recording = _RecordingGraph(VERDICT)
    stable = SystemMessage(content="identity", additional_kwargs={"dynamic_context": True})
    with (
        patch(
            "app.agents.core.agent.GraphManager.get_graph",
            new=AsyncMock(return_value=recording),
        ),
        patch(
            "app.workers.tasks.maintenance_sweep_tasks.load_user_context",
            new=AsyncMock(return_value=AuthenticatedUser(user_id="user-1", name="Ada")),
        ),
        patch(
            "app.agents.core.messages.assemble_context",
            new=AsyncMock(return_value=AssembledContext(stable=stable, volatile=None)),
        ),
        patch(
            "app.agents.core.messages.get_onboarding_system_prompt_if_applicable",
            new=AsyncMock(return_value=None),
        ),
    ):
        yield recording


@pytest.mark.integration
@pytest.mark.regression
async def test_the_health_check_prompt_reaches_the_model_as_the_users_turn(
    graph: _RecordingGraph,
) -> None:
    verdict = await _call_health_check_agent("todo-1", "user-1", PROMPT)

    assert graph.initial_state is not None
    messages = graph.initial_state["messages"]
    assert isinstance(messages, list)
    turns: list[AnyMessage] = [
        m
        for m in messages
        if isinstance(m, HumanMessage) and not m.additional_kwargs.get("time_context")
    ]
    assert [m.content for m in turns] == [PROMPT]
    assert verdict == VERDICT
