"""The live channel by which work reaches a running executor.

Redis is real (fakeredis) so the inbox's list mechanics run for real; the drain
rule is tested as a pure function because that is what it is.

The load-bearing assertion in this file is that a drained entry is STAGED for the
model node to commit, not merely appended to the hook's returned state. A
pre-model hook's return shapes one LLM call and is then discarded, so a channel
built on the append alone would show the user's message to the executor exactly
once and then lose it — silently, and only in production.
"""

import asyncio
from unittest.mock import patch

import fakeredis.aioredis
from langchain_core.messages import AIMessage, HumanMessage
import pytest

from app.agents.core.background import executor_channel as channel
from app.agents.core.background.executor_channel import (
    ExecutorInbox,
    as_interjection,
    decide_drain,
    drain_inbox_hook,
)
from app.constants.agents import AgentTag
from app.constants.executor import INBOX_ENTRY_ID
from app.models.agent_models import InboxEntry
from app.override.langgraph_bigtool.utils import (
    INJECTED_MESSAGES_KEY,
    pop_injected_messages,
)
from app.utils.agent_utils import strip_internal_agent_tags

CONVERSATION = "conv-1"
#: A real executor run carries the WRAPPED thread id and the conversation id
#: separately. Keying the drain on thread_id silently misses the inbox.
CONFIG = {
    "configurable": {
        "thread_id": f"executor_{CONVERSATION}",
        "conversation_id": CONVERSATION,
    }
}


@pytest.fixture
async def redis() -> fakeredis.aioredis.FakeRedis:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(channel, "redis_cache") as cache:
        cache.client = client
        yield client
    await client.aclose()


@pytest.fixture
def inbox(redis) -> ExecutorInbox:
    return ExecutorInbox(CONVERSATION)


class TestInbox:
    async def test_append_then_read_round_trips(self, inbox: ExecutorInbox) -> None:
        await inbox.append("t1", "also check spam")

        assert await inbox.read() == [
            InboxEntry(id="t1", text="also check spam", tag=AgentTag.USER_INTERJECTION)
        ]

    async def test_read_is_not_destructive(self, inbox: ExecutorInbox) -> None:
        """A run may die between reading and committing; a read that consumed
        would lose the user's message with nothing left to recover it from."""
        await inbox.append("t1", "also check spam")

        await inbox.read()

        assert await inbox.count() == 1

    async def test_entries_come_back_oldest_first(self, inbox: ExecutorInbox) -> None:
        await inbox.append("t1", "first")
        await inbox.append("t2", "second")

        assert [entry.text for entry in await inbox.read()] == ["first", "second"]

    async def test_retire_removes_only_the_named_entry(self, inbox: ExecutorInbox) -> None:
        first = await inbox.append("t1", "first")
        await inbox.append("t2", "second")

        await inbox.retire(first)

        assert [entry.id for entry in await inbox.read()] == ["t2"]

    async def test_discard_removes_only_the_named_ids(self, inbox: ExecutorInbox) -> None:
        await inbox.append("t1", "first")
        await inbox.append("t2", "second")

        removed = await inbox.discard({"t2"})

        assert removed == ["t2"]
        assert [entry.id for entry in await inbox.read()] == ["t1"]

    async def test_clear_does_not_drop_a_concurrent_append(
        self, inbox: ExecutorInbox, redis
    ) -> None:
        """BUG: cancelling a run counted then deleted the inbox in two steps, so a
        steering append that landed in between was counted and swept away. clear()
        now detaches the batch atomically, so an append arriving after the detach
        lands on a fresh list and survives, and the count is only the batch."""
        await inbox.append("pending", "the task being cancelled")

        entered = asyncio.Event()
        proceed = asyncio.Event()
        real_pipeline = redis.pipeline

        def gated_pipeline(*args, **kwargs):
            pipe = real_pipeline(*args, **kwargs)
            real_execute = pipe.execute

            async def execute(*a, **k):
                entered.set()  # clear() has detached and is about to delete
                await proceed.wait()
                return await real_execute(*a, **k)

            pipe.execute = execute
            return pipe

        with patch.object(redis, "pipeline", gated_pipeline):
            clearing = asyncio.create_task(inbox.clear())
            await entered.wait()
            await inbox.append("steer", "work on billing instead")
            proceed.set()
            removed = await clearing

        assert removed == 1
        assert [entry.id for entry in await inbox.read()] == ["steer"]

    async def test_an_unreadable_entry_does_not_wedge_the_channel(
        self, inbox: ExecutorInbox, redis
    ) -> None:
        """One corrupt value must not strand every later message behind it."""
        await redis.rpush(f"executor:inbox:{CONVERSATION}", b"{not json")
        await inbox.append("t1", "also check spam")

        assert [entry.id for entry in await inbox.read()] == ["t1"]

    async def test_interruption_carries_the_redirect_as_its_own_entry(
        self, inbox: ExecutorInbox
    ) -> None:
        """BUG: the redirect used to be folded into the notice text, so the two
        were indistinguishable — and finalize, seeing pending work, started a
        fresh run for a BARE stop whose task was the stop notice itself."""
        await inbox.announce_interruption("search my calendar instead")

        notice, redirect = await inbox.read()
        assert notice.tag is AgentTag.EXECUTOR_INTERRUPTED
        assert "INTERRUPTED" in notice.text
        assert "search my calendar instead" not in notice.text
        assert redirect.tag is AgentTag.USER_INTERJECTION
        assert redirect.text == "search my calendar instead"

    async def test_interruption_without_a_redirect_is_a_notice_alone(
        self, inbox: ExecutorInbox
    ) -> None:
        await inbox.announce_interruption(None)

        (entry,) = await inbox.read()
        assert entry.tag is AgentTag.EXECUTOR_INTERRUPTED
        assert "Do not" in entry.text or "do not" in entry.text


class TestDecideDrain:
    """The rule itself: what gets injected, and what gets dropped."""

    def test_an_unseen_entry_is_injected(self) -> None:
        entry = InboxEntry(id="t1", text="also check spam")

        drain = decide_drain([entry], [HumanMessage(content="find my flight email")])

        assert drain.inject == [entry]
        assert drain.retire == []

    def test_an_entry_already_in_the_thread_is_retired_not_reinjected(self) -> None:
        entry = InboxEntry(id="t1", text="also check spam")
        committed = HumanMessage(content="x", additional_kwargs={INBOX_ENTRY_ID: "t1"})

        drain = decide_drain([entry], [committed])

        assert drain.inject == []
        assert drain.retire == [entry]

    def test_an_entry_is_retired_only_once_actually_committed(self) -> None:
        """Retiring on read would lose the message if the run then died."""
        entry = InboxEntry(id="t1", text="also check spam")

        drain = decide_drain([entry], [AIMessage(content="still working")])

        assert drain.retire == []

    def test_a_mixed_inbox_splits(self) -> None:
        seen = InboxEntry(id="t1", text="old")
        fresh = InboxEntry(id="t2", text="new")
        committed = HumanMessage(content="x", additional_kwargs={INBOX_ENTRY_ID: "t1"})

        drain = decide_drain([seen, fresh], [committed])

        assert drain.inject == [fresh]
        assert drain.retire == [seen]


class TestFraming:
    def test_an_interjection_reads_as_the_user_speaking(self) -> None:
        message = as_interjection(InboxEntry(id="t1", text="also check spam"))

        assert isinstance(message, HumanMessage)
        assert "<user_interjection>" in message.content
        assert message.additional_kwargs[INBOX_ENTRY_ID] == "t1"

    def test_an_interruption_uses_its_own_tag(self) -> None:
        entry = InboxEntry(id="t1", text="stopped", tag=AgentTag.EXECUTOR_INTERRUPTED)

        assert "<executor_interrupted>" in as_interjection(entry).content

    def test_the_framing_never_reaches_the_user(self) -> None:
        content = as_interjection(InboxEntry(id="t1", text="also check spam")).content

        stripped = strip_internal_agent_tags(content)
        assert "also check spam" in stripped
        assert "user_interjection" not in stripped


class TestDrainHook:
    async def test_pending_work_is_injected_into_the_model_input(
        self, inbox: ExecutorInbox
    ) -> None:
        await inbox.append("t1", "also check spam")
        state = {"messages": [HumanMessage(content="find my flight email")]}

        result = await drain_inbox_hook(state, CONFIG, None)

        assert "also check spam" in result["messages"][-1].content

    async def test_pending_work_is_staged_for_the_model_node_to_commit(
        self, inbox: ExecutorInbox
    ) -> None:
        """Without the staging the message reaches ONE model call and is then
        gone from the thread — the whole bug this channel exists to avoid."""
        await inbox.append("t1", "also check spam")

        result = await drain_inbox_hook({"messages": []}, CONFIG, None)

        staged = pop_injected_messages(result)
        assert [m.additional_kwargs[INBOX_ENTRY_ID] for m in staged] == ["t1"]

    async def test_an_already_committed_entry_is_not_injected_twice(
        self, inbox: ExecutorInbox
    ) -> None:
        await inbox.append("t1", "also check spam")
        committed = HumanMessage(content="x", additional_kwargs={INBOX_ENTRY_ID: "t1"})

        result = await drain_inbox_hook({"messages": [committed]}, CONFIG, None)

        assert result.get(INJECTED_MESSAGES_KEY, []) == []

    async def test_injecting_does_not_remove_the_entry(self, inbox: ExecutorInbox) -> None:
        """Staging is not committing: a run that dies at the model call must
        leave the entry pending, so the thread stays the only record of what
        was actually delivered."""
        await inbox.append("t1", "also check spam")

        await drain_inbox_hook({"messages": []}, CONFIG, None)

        assert [entry.id for entry in await inbox.read()] == ["t1"]

    async def test_a_committed_entry_is_retired_from_redis(self, inbox: ExecutorInbox) -> None:
        await inbox.append("t1", "also check spam")
        committed = HumanMessage(content="x", additional_kwargs={INBOX_ENTRY_ID: "t1"})

        await drain_inbox_hook({"messages": [committed]}, CONFIG, None)

        assert await inbox.count() == 0

    async def test_an_empty_inbox_leaves_the_turn_untouched(self, inbox: ExecutorInbox) -> None:
        state = {"messages": [AIMessage(content="working")]}

        assert await drain_inbox_hook(state, CONFIG, None) is state

    async def test_a_turn_with_no_conversation_is_left_alone(self, inbox: ExecutorInbox) -> None:
        await inbox.append("t1", "also check spam")
        state = {"messages": []}

        assert await drain_inbox_hook(state, {"configurable": {}}, None) is state

    async def test_the_wrapped_thread_id_is_not_mistaken_for_the_conversation(
        self, inbox: ExecutorInbox
    ) -> None:
        """The executor runs on ``executor_<conversation>``. A drain keyed on
        thread_id looks in ``executor:inbox:executor_<conv>``, which nothing
        writes to, so the channel silently does nothing at all."""
        await inbox.append("t1", "also check spam")
        thread_only = {"configurable": {"thread_id": f"executor_{CONVERSATION}"}}

        assert await drain_inbox_hook({"messages": []}, thread_only, None) == {"messages": []}

    async def test_a_redis_failure_never_breaks_the_turn(self, inbox: ExecutorInbox) -> None:
        """Reading the inbox is enrichment; failing it must not fail the run."""
        state = {"messages": [HumanMessage(content="find my flight email")]}
        with patch.object(ExecutorInbox, "read", side_effect=RuntimeError("redis down")):
            assert await drain_inbox_hook(state, CONFIG, None) is state

    async def test_entries_are_injected_in_the_order_they_arrived(
        self, inbox: ExecutorInbox
    ) -> None:
        await inbox.append("t1", "first thing")
        await inbox.append("t2", "second thing")

        result = await drain_inbox_hook({"messages": []}, CONFIG, None)

        injected = [m.content for m in result[INJECTED_MESSAGES_KEY]]
        assert "first thing" in injected[0]
        assert "second thing" in injected[1]
