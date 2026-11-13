"""A background subagent's landing must reach an executor run, every time, as a fresh run.

Driven through the real busy lock, inbox and detached-run preparation on fakeredis;
only the stream/websocket edges and the task spawn itself are doubled.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.agents.core.background import (
    executor_channel as ec,
    executor_queue as eq,
    executor_runner as er,
)
from app.agents.core.background.executor_queue import release_lock_if_owned
from app.agents.core.subagents import delegation as landing
from app.agents.core.subagents.delegation import Delegation, SubagentDisplay
from app.agents.core.subagents.subagent_runner import SubagentExecutionContext
from app.models.agent_models import AgentConfigurable, SubagentKind

pytestmark = pytest.mark.unit

CONVERSATION = "conv-1"

#: A subagent's own configurable, as the landing code holds it: its thread, its
#: row id, and the turn-scoped hints of the turn that dispatched it.
SUBAGENT_CONFIGURABLE: AgentConfigurable = {
    "user_id": "u1",
    "email": "u1@example.com",
    "user_name": "Ada",
    "user_timezone": "Europe/London",
    "conversation_id": CONVERSATION,
    "thread_id": f"spawn_{CONVERSATION}_call-1",
    "subagent_id": "row-1",
    "tool_category": "gmail",
    "selected_tool": "GMAIL_SEND_EMAIL",
    "execution_mode": "interactive",
}


@pytest.fixture
async def spawned() -> AsyncIterator[AsyncMock]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with (
        patch.object(eq.redis_cache, "redis", client),
        patch.object(ec.redis_cache, "redis", client),
        patch.object(eq, "StreamManager", AsyncMock()),
        patch.object(eq, "websocket_manager", AsyncMock()),
        patch.object(er, "_spawn_detached_run") as spawn,
    ):
        yield spawn
    await client.aclose()


def _delegation() -> Delegation:
    """Build a delegation whose own AND parent configurables carry every leakable key."""
    return Delegation(
        ctx=SubagentExecutionContext(
            subagent_graph=MagicMock(),
            agent_name="spawned_subagent",
            config={"configurable": dict(SUBAGENT_CONFIGURABLE)},
            configurable=dict(SUBAGENT_CONFIGURABLE),
            integration_id="spawn",
            initial_state={},
            user_id="u1",
        ),
        kind=SubagentKind.SPAWN,
        subagent_id="row-1",
        tool_call_id="call-1",
        task="summarize",
        display=SubagentDisplay(name="summarize", agent_type="spawned"),
        parent_configurable=dict(SUBAGENT_CONFIGURABLE),
    )


async def _land(result: str) -> None:
    await landing._land(_delegation(), result)


async def _finish_run(spawn: AsyncMock) -> None:
    """Finish the collection run the last landing started, freeing the conversation."""
    run = spawn.call_args.args[0].run
    await release_lock_if_owned(CONVERSATION, run.stream_id, run.task_id)


class TestEveryLandingIsCollected:
    async def test_a_second_landing_after_the_collection_run_finished_starts_another(
        self, spawned: AsyncMock
    ) -> None:
        await _land("first result")
        await _finish_run(spawned)
        await _land("second result")

        assert spawned.call_count == 2

    async def test_landings_while_the_collection_run_is_live_start_nothing_more(
        self, spawned: AsyncMock
    ) -> None:
        await _land("first result")
        await _land("second result")

        assert spawned.call_count == 1


class TestTheCollectionRunIsFresh:
    async def test_it_carries_the_user_but_nothing_of_the_subagents_run(
        self, spawned: AsyncMock
    ) -> None:
        await _land("result")

        configurable = spawned.call_args.args[0].configurable
        assert configurable["user_id"] == "u1"
        assert configurable["user_timezone"] == "Europe/London"
        assert configurable["thread_id"] == CONVERSATION
        for leaked in ("subagent_id", "tool_category", "selected_tool"):
            assert leaked not in configurable
