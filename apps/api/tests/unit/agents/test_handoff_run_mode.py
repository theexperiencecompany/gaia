"""Where a handoff runs and what it says when it cannot — driven through a real graph node.

The handoff tool is invoked from inside a compiled LangGraph node (its stream writer
only exists there), against a fake subagent graph and fakeredis. Nothing of the
dispatch path itself is patched, only the subagent's resolution and the executor
run a landing would start.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, TypedDict
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
import pytest

from app.agents.core.background import executor_runner
from app.agents.core.subagents import handoff_tools
from app.agents.core.subagents.handoff_tools import handoff
from app.agents.core.subagents.subagent_runner import SubagentExecutionContext
from app.db.redis import redis_cache
from app.utils import background_tasks

pytestmark = pytest.mark.unit

CONVERSATION = "conv-run-mode"
SUBAGENT_THREAD = f"my-mcp_executor_{CONVERSATION}"


class _SubagentGraph:
    """A compiled subagent graph's surface: runs one tool, then answers — optionally held open."""

    def __init__(self, hold: asyncio.Event | None = None) -> None:
        self._hold = hold

    async def astream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[tuple[str, object]]:
        if self._hold is not None:
            await self._hold.wait()
        yield ("messages", (ToolMessage(content="3 rows", tool_call_id="t1", name="query"), {}))
        yield ("messages", (AIMessageChunk(content="the rows"), {}))


def _ctx(configurable: dict[str, Any], graph: _SubagentGraph) -> SubagentExecutionContext:
    subagent_configurable = {**configurable, "thread_id": SUBAGENT_THREAD}
    return SubagentExecutionContext(
        subagent_graph=graph,  # type: ignore[arg-type]  # the compiled-graph surface this run touches
        agent_name="custom_mcp_my-mcp",
        config={"configurable": subagent_configurable},
        configurable=subagent_configurable,
        integration_id="my-mcp",
        initial_state={"messages": [], "intent": "fetch the rows"},
        user_id="u1",
        stream_id=configurable.get("stream_id"),
    )


class _NodeState(TypedDict):
    out: str


async def _handoff_in_a_graph(configurable: dict[str, Any], tool_call_id: str) -> str:
    """Invoke handoff from inside a real node, the only place its stream writer exists."""

    async def node(state: _NodeState, config: RunnableConfig) -> _NodeState:
        message = await handoff.ainvoke(
            {
                "name": "handoff",
                "type": "tool_call",
                "id": tool_call_id,
                "args": {"subagent_id": "my-mcp", "task": "fetch the rows"},
            },
            config=config,
        )
        return {"out": str(message.content)}

    builder = StateGraph(_NodeState)
    builder.add_node("node", node)
    builder.set_entry_point("node")
    builder.add_edge("node", END)
    result = await builder.compile().ainvoke({"out": ""}, config={"configurable": configurable})
    return result["out"]


async def _drain_background() -> None:
    while pending := [
        t for t in background_tasks._background_tasks if t.get_name() == "background-subagent-run"
    ]:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture
async def world() -> AsyncIterator[None]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with (
        patch.object(redis_cache, "redis", client),
        patch.object(handoff_tools, "_has_parked_subagent", new=AsyncMock(return_value=False)),
        patch.object(executor_runner, "_start_executor_run", new=AsyncMock(return_value=True)),
    ):
        yield
        await _drain_background()
    await client.aclose()


def _configurable(**overrides: Any) -> dict[str, Any]:
    return {
        "user_id": "u1",
        "conversation_id": CONVERSATION,
        "thread_id": f"executor_{CONVERSATION}",
        "stream_id": "stream-run-mode",
        "execution_mode": "interactive",
        **overrides,
    }


class TestAHeadlessRunWaitsForItsSubagent:
    async def test_a_workflow_handoff_returns_the_subagents_answer(self, world: None) -> None:
        # A headless run delivers once: a result landing after it ends reaches nobody.
        configurable = _configurable(execution_mode="background", workflow_id="")
        with patch.object(
            handoff_tools,
            "prepare_subagent_execution",
            new=AsyncMock(return_value=(_ctx(configurable, _SubagentGraph()), None, None)),
        ):
            result = await _handoff_in_a_graph(configurable, "tc-headless")

        assert result == "the rows"


class TestABusyIntegrationRefusesInWholeSentences:
    async def test_a_second_handoff_while_the_first_runs_names_how_to_reach_it(
        self, world: None
    ) -> None:
        configurable = _configurable()
        hold = asyncio.Event()
        with patch.object(
            handoff_tools,
            "prepare_subagent_execution",
            new=AsyncMock(
                side_effect=lambda **_kw: (_ctx(configurable, _SubagentGraph(hold)), None, None)
            ),
        ):
            first = await _handoff_in_a_graph(configurable, "tc-first")
            second = await _handoff_in_a_graph(configurable, "tc-second")
            hold.set()

        assert "background" in first
        assert "Call Its" not in second
        assert "message_subagent" in second
        assert "cancel_subagent" in second
