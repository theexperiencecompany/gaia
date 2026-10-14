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


def _sub(
    subagent_id: str = "s1", *, thread: str = THREAD, integration_id: str = "gmail"
) -> RunningSubagent:
    return RunningSubagent(
        subagent_id=subagent_id,
        subagent_thread_id=thread,
        integration_id=integration_id,
        agent_name=f"{integration_id}_agent",
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
        assert await RunningSubagents(CONV).claim(_sub("s1"))
        out = await list_running_subagents.ainvoke({}, config=CONFIG)
        assert "s1" in out and "gmail" in out

    async def test_says_none_when_empty(self, redis) -> None:
        out = await list_running_subagents.ainvoke({}, config=CONFIG)
        assert out == "No subagents are currently running."

    async def test_lists_one_line_per_running_subagent(self, redis) -> None:
        assert await RunningSubagents(CONV).claim(_sub("s1"))
        assert await RunningSubagents(CONV).claim(
            _sub("s2", thread="slack_executor_conv-1", integration_id="slack")
        )

        out = await list_running_subagents.ainvoke({}, config=CONFIG)

        assert sorted(out.split("\n")) == ["- s1 (gmail): search mail", "- s2 (slack): search mail"]

    async def test_a_run_with_no_conversation_sees_the_subagents_it_started(self, redis) -> None:
        # A delegation with no conversation registers under "" (Delegation.conversation_id).
        assert await RunningSubagents("").claim(_sub("s1"))

        listed = await list_running_subagents.ainvoke({}, config={"configurable": {}})
        steered = await message_subagent.ainvoke(
            {"subagent_id": "s1", "message": "hurry"}, config={"configurable": {}}
        )

        assert listed == "- s1 (gmail): search mail"
        assert steered == "Steer delivered to the gmail subagent (s1)."


class TestMessageSubagent:
    async def test_steer_lands_in_the_targeted_mailbox(self, redis) -> None:
        assert await RunningSubagents(CONV).claim(_sub("s1"))
        await message_subagent.ainvoke(
            {"subagent_id": "s1", "message": "narrow to Q1 2024"}, config=CONFIG
        )
        pending = await SubagentInbox(THREAD).read()
        assert [e.text for e in pending] == ["narrow to Q1 2024"]

    async def test_each_steer_is_its_own_retirable_entry(self, redis) -> None:
        assert await RunningSubagents(CONV).claim(_sub("s1"))
        for message in ("narrow to Q1 2024", "skip drafts"):
            await message_subagent.ainvoke({"subagent_id": "s1", "message": message}, config=CONFIG)

        pending = await SubagentInbox(THREAD).read()
        ids = [e.id for e in pending]
        assert [e.text for e in pending] == ["narrow to Q1 2024", "skip drafts"]
        assert all(ids) and len(set(ids)) == 2

    async def test_unknown_id_fails_loud(self, redis) -> None:
        out = await message_subagent.ainvoke(
            {"subagent_id": "ghost", "message": "hi"}, config=CONFIG
        )
        assert "ghost" in out and "list_running_subagents" in out
        # nothing was delivered anywhere
        assert await SubagentInbox(THREAD).read() == []


class TestCancelSubagent:
    async def test_cancel_raises_the_targeted_flag(self, redis) -> None:
        assert await RunningSubagents(CONV).claim(_sub("s1"))
        await cancel_subagent.ainvoke({"subagent_id": "s1"}, config=CONFIG)
        assert await SubagentCancel(THREAD).is_requested() is True

    async def test_unknown_id_fails_loud(self, redis) -> None:
        out = await cancel_subagent.ainvoke({"subagent_id": "ghost"}, config=CONFIG)
        assert "ghost" in out
        assert await SubagentCancel(THREAD).is_requested() is False
