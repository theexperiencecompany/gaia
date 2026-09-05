"""The executor's subagent-control tools: list, steer, cancel.

Proves the executor can reach a specific running subagent by id — a steer lands
in that subagent's mailbox, a cancel raises its flag — and that a stale id fails
loud rather than silently no-op'ing.
"""

from typing import Any
from unittest.mock import patch

import fakeredis.aioredis
import pytest

from app.agents.core.background import (
    executor_channel as channel,
    running_registry as reg_mod,
    subagent_channel as sub_channel,
)
from app.agents.core.background.running_registry import RunningSubagents
from app.agents.core.background.subagent_channel import SubagentCancel, SubagentInbox
from app.agents.tools.subagent_control_tool import (
    cancel_subagent,
    list_running_subagents,
    message_subagent,
)
from app.models.agent_models import RunningSubagent

pytestmark = pytest.mark.unit

CONV = "conv-1"
THREAD = f"gmail_executor_{CONV}"
CONFIG: dict[str, Any] = {"configurable": {"conversation_id": CONV}}


def _sub(subagent_id: str = "s1") -> RunningSubagent:
    return RunningSubagent(
        subagent_id=subagent_id,
        subagent_thread_id=THREAD,
        integration_id="gmail",
        agent_name="gmail_agent",
        task_summary="search mail",
        started_at="2026-09-05T10:00:00Z",
    )


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with (
        patch.object(channel, "redis_cache") as c1,
        patch.object(sub_channel, "redis_cache") as c2,
        patch.object(reg_mod, "redis_cache") as c3,
    ):
        c1.client = c2.client = c3.client = client
        yield client
    await client.aclose()


class TestListRunningSubagents:
    async def test_lists_a_running_subagent(self, redis) -> None:
        await RunningSubagents(CONV).register(_sub("s1"))
        out = await list_running_subagents.ainvoke({}, config=CONFIG)
        assert "s1" in out and "gmail" in out

    async def test_says_none_when_empty(self, redis) -> None:
        out = await list_running_subagents.ainvoke({}, config=CONFIG)
        assert "No subagents" in out


class TestMessageSubagent:
    async def test_steer_lands_in_the_targeted_mailbox(self, redis) -> None:
        await RunningSubagents(CONV).register(_sub("s1"))
        await message_subagent.ainvoke(
            {"subagent_id": "s1", "message": "narrow to Q1 2024"}, config=CONFIG
        )
        pending = await SubagentInbox(THREAD).read()
        assert [e.text for e in pending] == ["narrow to Q1 2024"]

    async def test_unknown_id_fails_loud(self, redis) -> None:
        out = await message_subagent.ainvoke(
            {"subagent_id": "ghost", "message": "hi"}, config=CONFIG
        )
        assert "ghost" in out and "list_running_subagents" in out
        # nothing was delivered anywhere
        assert await SubagentInbox(THREAD).read() == []


class TestCancelSubagent:
    async def test_cancel_raises_the_targeted_flag(self, redis) -> None:
        await RunningSubagents(CONV).register(_sub("s1"))
        await cancel_subagent.ainvoke({"subagent_id": "s1"}, config=CONFIG)
        assert await SubagentCancel(THREAD).is_requested() is True

    async def test_unknown_id_fails_loud(self, redis) -> None:
        out = await cancel_subagent.ainvoke({"subagent_id": "ghost"}, config=CONFIG)
        assert "ghost" in out
        assert await SubagentCancel(THREAD).is_requested() is False
