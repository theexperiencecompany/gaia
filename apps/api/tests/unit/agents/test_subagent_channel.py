"""The per-subagent mailbox — the executor steering ONE running subagent.

Mirrors ``test_executor_channel`` one tier down. The point these prove that the
executor-inbox tests cannot: a steer the executor addressed to a specific
subagent thread reaches that subagent and NO sibling, and the inject/retire rule
is the shared one — so a subagent absorbs only what the executor sent it.
"""

from typing import Any
from unittest.mock import patch

import fakeredis.aioredis
from langchain_core.messages import HumanMessage
import pytest

from app.agents.core.background import executor_channel as channel, subagent_channel as sub_channel
from app.agents.core.background.subagent_channel import (
    SubagentCancel,
    SubagentInbox,
    drain_subagent_inbox_hook,
)
from app.constants.agents import AgentTag
from app.constants.executor import INBOX_ENTRY_ID

pytestmark = pytest.mark.unit

THREAD_A = "gmail_executor_conv-1"
THREAD_B = "slack_executor_conv-1"


@pytest.fixture
async def redis():
    # SubagentInbox's list ops live in executor_channel (via RedisInbox);
    # SubagentCancel uses subagent_channel's own client — patch both to one fake.
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with (
        patch.object(channel, "redis_cache") as cache,
        patch.object(sub_channel, "redis_cache") as sub_cache,
    ):
        cache.client = client
        sub_cache.client = client
        yield client
    await client.aclose()


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "conversation_id": "conv-1", "user_id": "u-1"}}


class TestSubagentInbox:
    async def test_append_defaults_to_the_subagent_interjection_tag(self, redis) -> None:
        inbox = SubagentInbox(THREAD_A)
        entry = await inbox.append("m1", "narrow to Q1 2024")
        assert entry.tag == AgentTag.SUBAGENT_INTERJECTION
        assert (await inbox.read())[0].text == "narrow to Q1 2024"


class TestDrainHook:
    async def test_a_steer_reaches_the_addressed_subagent(self, redis) -> None:
        await SubagentInbox(THREAD_A).append("m1", "narrow to Q1 2024")
        state = await drain_subagent_inbox_hook({"messages": []}, _config(THREAD_A), store=None)
        injected = "".join(str(m.content) for m in state["messages"])
        assert "narrow to Q1 2024" in injected
        assert f"<{AgentTag.SUBAGENT_INTERJECTION}>" in injected

    async def test_a_steer_never_reaches_a_sibling_subagent(self, redis) -> None:
        await SubagentInbox(THREAD_A).append("m1", "for gmail only")
        state = await drain_subagent_inbox_hook({"messages": []}, _config(THREAD_B), store=None)
        assert state["messages"] == []
        # still pending for its true addressee, untouched
        assert len(await SubagentInbox(THREAD_A).read()) == 1

    async def test_a_committed_steer_is_retired_not_reinjected(self, redis) -> None:
        inbox = SubagentInbox(THREAD_A)
        await inbox.append("m1", "narrow to Q1 2024")
        committed = HumanMessage(content="prior", additional_kwargs={INBOX_ENTRY_ID: "m1"})
        state = await drain_subagent_inbox_hook(
            {"messages": [committed]}, _config(THREAD_A), store=None
        )
        assert state["messages"] == [committed]  # not injected a second time
        assert await inbox.read() == []  # dropped from the mailbox


class TestSubagentCancel:
    async def test_flag_round_trips(self, redis) -> None:
        cancel = SubagentCancel(THREAD_A)
        assert await cancel.is_requested() is False
        await cancel.request()
        assert await cancel.is_requested() is True
        await cancel.clear()
        assert await cancel.is_requested() is False

    async def test_cancel_is_isolated_per_subagent(self, redis) -> None:
        await SubagentCancel(THREAD_A).request()
        assert await SubagentCancel(THREAD_B).is_requested() is False
