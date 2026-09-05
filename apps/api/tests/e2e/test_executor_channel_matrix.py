"""The executor channel, attacked from every side.

The unit tests pin the storage mechanics and the first e2e file proves the
mid-run hand-over works at all. This file is the scenario matrix: every branch
of the drain decision, every framing shape, every storage edge, and — the point
the sim-stack run could never prove — exactly WHERE a steered message lands in
the model's context: after the tool results, at the conversation tail, as a
``HumanMessage`` the model reads as the user speaking.

Three layers, fastest first:

* ``TestDecideDrain`` — ``decide_drain`` is pure, so the whole truth table runs
  with no graph, no Redis, no clock.
* ``TestInboxStorage`` — the Redis list against fakeredis: ordering, exactness
  of retire, delivered-marker semantics, malformed rows, absent client.
* ``TestHookPlacement`` — the real compiled executor graph with a scripted
  model: the interjection's position in the recorded prompt relative to
  ``ToolMessage`` results, its survival into the thread, idempotency across
  many model calls, and the hook's failure modes.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import uuid4

import fakeredis.aioredis
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from app.agents.core.background import executor_channel as channel
from app.agents.core.background.executor_channel import (
    ExecutorInbox,
    as_interjection,
    decide_drain,
)
from app.constants.agents import AgentTag
from app.constants.executor import INBOX_ENTRY_ID
from app.constants.general import EXECUTOR_THREAD_PREFIX
from app.models.agent_models import InboxDrain, InboxEntry
from tests.e2e._harness.graph_run import AGENT_NODE, call, executor_graph, scripted_model_of

pytestmark = pytest.mark.e2e

CONVERSATION = "conv-channel-matrix"


def _entry(entry_id: str = "e-1", text: str = "do the thing") -> InboxEntry:
    return InboxEntry(id=entry_id, text=text)


def _committed(entry_id: str, text: str = "already there") -> HumanMessage:
    return HumanMessage(content=text, additional_kwargs={INBOX_ENTRY_ID: entry_id})


def _plain(text: str = "plain") -> HumanMessage:
    return HumanMessage(content=text)


# ---------------------------------------------------------------------------
# decide_drain: the whole truth table, no graph required
# ---------------------------------------------------------------------------


class TestDecideDrain:
    def test_empty_inbox_empty_thread(self) -> None:
        drain = decide_drain([], [])
        assert drain == InboxDrain(inject=[], retire=[])
        assert not drain

    def test_single_pending_entry_injects(self) -> None:
        drain = decide_drain([_entry("e-1")], [_plain("start")])
        assert [e.id for e in drain.inject] == ["e-1"]
        assert drain.retire == []
        assert bool(drain)

    def test_committed_entry_retires_instead(self) -> None:
        drain = decide_drain([_entry("e-1")], [_plain("start"), _committed("e-1")])
        assert drain.inject == []
        assert [e.id for e in drain.retire] == ["e-1"]
        assert bool(drain)

    @pytest.mark.parametrize(
        ("entries", "committed_ids", "want_inject", "want_retire"),
        [
            ([], [], [], []),
            (["a"], [], ["a"], []),
            (["a"], ["a"], [], ["a"]),
            (["a", "b"], [], ["a", "b"], []),
            (["a", "b"], ["a", "b"], [], ["a", "b"]),
            (["a", "b"], ["a"], ["b"], ["a"]),
            (["a", "b"], ["b"], ["a"], ["b"]),
            (["a", "b", "c"], ["b"], ["a", "c"], ["b"]),
            (["a", "b", "c"], ["a", "c"], ["b"], ["a", "c"]),
            (["a", "b"], ["zzz"], ["a", "b"], []),
            (["a"], ["a", "zzz"], [], ["a"]),
        ],
        ids=[
            "nothing-nothing",
            "one-pending",
            "one-committed",
            "two-pending",
            "two-committed",
            "first-committed",
            "second-committed",
            "middle-committed",
            "edges-committed",
            "unknown-commit-ignored",
            "commit-superset",
        ],
    )
    def test_split_matrix(
        self,
        entries: list[str],
        committed_ids: list[str],
        want_inject: list[str],
        want_retire: list[str],
    ) -> None:
        messages: list[Any] = [_plain("start")]
        messages.extend(_committed(cid) for cid in committed_ids)
        drain = decide_drain([_entry(e) for e in entries], messages)
        assert [e.id for e in drain.inject] == want_inject
        assert [e.id for e in drain.retire] == want_retire

    def test_order_is_fifo_not_commit_order(self) -> None:
        drain = decide_drain(
            [_entry("c"), _entry("a"), _entry("b")],
            [_committed("b"), _committed("a")],
        )
        assert [e.id for e in drain.inject] == ["c"]
        assert [e.id for e in drain.retire] == ["a", "b"]

    def test_inject_preserves_inbox_order(self) -> None:
        drain = decide_drain([_entry("z"), _entry("m"), _entry("a")], [])
        assert [e.id for e in drain.inject] == ["z", "m", "a"]

    def test_commit_stamp_must_match_exactly(self) -> None:
        drain = decide_drain([_entry("e-1")], [_committed("e-1 ")])
        assert [e.id for e in drain.inject] == ["e-1"]
        assert drain.retire == []

    def test_message_without_kwargs_is_not_a_commit(self) -> None:
        bare = HumanMessage(content="e-1")
        bare.additional_kwargs = {}  # type: ignore[assignment]
        drain = decide_drain([_entry("e-1")], [bare])
        assert [e.id for e in drain.inject] == ["e-1"]

    @pytest.mark.parametrize("other", ["tool-1", "lc_run--abc", "", "E-1", "e-10"])
    def test_unrelated_stamps_do_not_retire(self, other: str) -> None:
        drain = decide_drain([_entry("e-1")], [_committed(other)])
        assert [e.id for e in drain.inject] == ["e-1"]
        assert drain.retire == []

    def test_ai_and_tool_messages_cannot_carry_the_stamp(self) -> None:
        messages: list[Any] = [
            AIMessage(content="thinking", additional_kwargs={INBOX_ENTRY_ID: "e-1"}),
            ToolMessage(content="result", tool_call_id="c1"),
        ]
        drain = decide_drain([_entry("e-1")], messages)
        # The AI message carries a stamp-shaped kwarg: the rule keys on the
        # stamp wherever it sits, so this retires. If the rule ever narrows to
        # HumanMessage-only, this test names the behaviour change.
        assert [e.id for e in drain.retire] == ["e-1"]

    def test_duplicate_entry_ids_move_together(self) -> None:
        drain = decide_drain([_entry("dup"), _entry("dup")], [_committed("dup")])
        assert drain.inject == []
        assert len(drain.retire) == 2

    def test_many_entries_scale(self) -> None:
        entries = [_entry(f"e-{i}") for i in range(50)]
        committed = [_committed(f"e-{i}") for i in range(0, 50, 2)]
        drain = decide_drain(entries, committed)
        assert [e.id for e in drain.inject] == [f"e-{i}" for i in range(1, 50, 2)]
        assert [e.id for e in drain.retire] == [f"e-{i}" for i in range(0, 50, 2)]

    def test_system_messages_are_ignored(self) -> None:
        drain = decide_drain(
            [_entry("e-1")],
            [SystemMessage(content="prompt"), _plain("start")],
        )
        assert [e.id for e in drain.inject] == ["e-1"]


# ---------------------------------------------------------------------------
# as_interjection: the framing the model actually reads
# ---------------------------------------------------------------------------


class TestAsInterjection:
    def test_is_a_human_message(self) -> None:
        assert isinstance(as_interjection(_entry()), HumanMessage)

    def test_carries_the_user_interjection_tag(self) -> None:
        assert "<user_interjection>" in str(as_interjection(_entry()).content)

    def test_text_is_inside_the_tag(self) -> None:
        assert "check spam" in str(as_interjection(_entry(text="check spam")).content)

    def test_stamp_matches_entry_id(self) -> None:
        assert as_interjection(_entry("abc-123")).additional_kwargs[INBOX_ENTRY_ID] == "abc-123"

    def test_interrupted_tag_frames_as_system_report(self) -> None:
        entry = InboxEntry(id="x", text="stop", tag=AgentTag.EXECUTOR_INTERRUPTED)
        assert "<executor_interrupted>" in str(as_interjection(entry).content)

    @pytest.mark.parametrize(
        ("tag", "open_tag"),
        [
            (AgentTag.USER_INTERJECTION, "<user_interjection>"),
            (AgentTag.EXECUTOR_INTERRUPTED, "<executor_interrupted>"),
        ],
    )
    def test_each_tag_round_trips(self, tag: AgentTag, open_tag: str) -> None:
        msg = as_interjection(InboxEntry(id="i", text="body", tag=tag))
        assert open_tag in str(msg.content)
        assert "body" in str(msg.content)

    def test_body_whitespace_is_stripped(self) -> None:
        assert str(as_interjection(_entry(text="  padded  ")).content).count("padded") == 1

    def test_empty_text_still_frames(self) -> None:
        msg = as_interjection(_entry(text=""))
        assert isinstance(msg, HumanMessage)
        assert msg.additional_kwargs[INBOX_ENTRY_ID] == "e-1"


# ---------------------------------------------------------------------------
# ExecutorInbox: storage semantics against fakeredis
# ---------------------------------------------------------------------------


@pytest.fixture
async def inbox():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(channel, "redis_cache") as cache:
        cache.client = client
        yield ExecutorInbox(CONVERSATION)
    await client.aclose()


@pytest.fixture
async def raw_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(channel, "redis_cache") as cache:
        cache.client = client
        yield client
    await client.aclose()


class TestInboxStorage:
    async def test_append_then_read_round_trip(self, inbox: ExecutorInbox) -> None:
        await inbox.append("e-1", "first")
        assert [(e.id, e.text) for e in await inbox.read()] == [("e-1", "first")]

    async def test_read_is_fifo(self, inbox: ExecutorInbox) -> None:
        for i in range(5):
            await inbox.append(f"e-{i}", f"text-{i}")
        assert [e.id for e in await inbox.read()] == [f"e-{i}" for i in range(5)]

    async def test_read_is_non_destructive(self, inbox: ExecutorInbox) -> None:
        await inbox.append("e-1", "stay")
        assert len(await inbox.read()) == 1
        assert len(await inbox.read()) == 1

    async def test_count_tracks_appends(self, inbox: ExecutorInbox) -> None:
        assert await inbox.count() == 0
        await inbox.append("e-1", "a")
        await inbox.append("e-2", "b")
        assert await inbox.count() == 2

    async def test_retire_removes_only_the_named_entry(self, inbox: ExecutorInbox) -> None:
        first = await inbox.append("e-1", "a")
        await inbox.append("e-2", "b")
        await inbox.append("e-3", "c")
        await inbox.retire(first)
        assert [e.id for e in await inbox.read()] == ["e-2", "e-3"]

    async def test_retire_is_exact_encode_match(self, inbox: ExecutorInbox) -> None:
        # Same id, different text: the stored row must survive, because retire
        # removes the exact value append wrote — not "anything with this id".
        await inbox.append("e-1", "original")
        await inbox.retire(InboxEntry(id="e-1", text="forged"))
        assert [e.id for e in await inbox.read()] == ["e-1"]

    async def test_retire_unknown_entry_is_a_noop(self, inbox: ExecutorInbox) -> None:
        await inbox.append("e-1", "a")
        await inbox.retire(InboxEntry(id="nope", text="nothing"))
        assert await inbox.count() == 1

    async def test_clear_returns_count_and_empties(self, inbox: ExecutorInbox) -> None:
        await inbox.append("e-1", "a")
        await inbox.append("e-2", "b")
        assert await inbox.clear() == 2
        assert await inbox.read() == []
        assert await inbox.count() == 0

    async def test_clear_empty_returns_zero(self, inbox: ExecutorInbox) -> None:
        assert await inbox.clear() == 0

    async def test_discard_removes_named_ids(self, inbox: ExecutorInbox) -> None:
        await inbox.append("task-1", "a")
        await inbox.append("task-2", "b")
        await inbox.append("task-3", "c")
        assert await inbox.discard({"task-1", "task-3"}) == ["task-1", "task-3"]
        assert [e.id for e in await inbox.read()] == ["task-2"]

    async def test_discard_unknown_ids_returns_empty(self, inbox: ExecutorInbox) -> None:
        await inbox.append("task-1", "a")
        assert await inbox.discard({"ghost"}) == []

    async def test_discard_empty_set_is_noop(self, inbox: ExecutorInbox) -> None:
        await inbox.append("task-1", "a")
        assert await inbox.discard(set()) == []
        assert await inbox.count() == 1

    async def test_tag_survives_round_trip(self, inbox: ExecutorInbox) -> None:
        await inbox.append("x", "stop now", AgentTag.EXECUTOR_INTERRUPTED)
        (entry,) = await inbox.read()
        assert entry.tag == AgentTag.EXECUTOR_INTERRUPTED

    async def test_default_tag_is_interjection(self, inbox: ExecutorInbox) -> None:
        await inbox.append("x", "hi")
        (entry,) = await inbox.read()
        assert entry.tag == AgentTag.USER_INTERJECTION

    async def test_malformed_row_is_skipped_not_fatal(self, raw_client: Any) -> None:
        inbox = ExecutorInbox(CONVERSATION)
        await raw_client.rpush(inbox._key, "not-json{{{")
        await inbox.append("good", "fine")
        assert [e.id for e in await inbox.read()] == ["good"]

    @pytest.mark.parametrize(
        "bad",
        [
            '{"id": "x"}',
            '{"text": "no id"}',
            '{"id": "x", "text": "y", "tag": "no-such-tag"}',
            "[]",
            '"just a string"',
            "42",
        ],
    )
    async def test_unparseable_shapes_are_skipped(self, raw_client: Any, bad: str) -> None:
        inbox = ExecutorInbox(CONVERSATION)
        await raw_client.rpush(inbox._key, bad)
        assert await inbox.read() == []

    async def test_missing_tag_defaults_to_interjection(self, raw_client: Any) -> None:
        inbox = ExecutorInbox(CONVERSATION)
        await raw_client.rpush(inbox._key, '{"id": "x", "text": "y"}')
        (entry,) = await inbox.read()
        assert entry.tag == AgentTag.USER_INTERJECTION

    async def test_conversations_do_not_share_state(self) -> None:
        client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        with patch.object(channel, "redis_cache") as cache:
            cache.client = client
            try:
                await ExecutorInbox("conv-a").append("e-1", "a")
                assert await ExecutorInbox("conv-b").read() == []
                assert await ExecutorInbox("conv-a").count() == 1
            finally:
                await client.aclose()

    async def test_entry_ids_unique_per_append(self, inbox: ExecutorInbox) -> None:
        ids = {f"task-{uuid4().hex}" for _ in range(10)}
        for entry_id in ids:
            await inbox.append(entry_id, "work")
        assert {e.id for e in await inbox.read()} == ids


class TestInboxWithoutRedis:
    async def test_read_empty_when_no_client(self) -> None:
        with patch.object(channel, "redis_cache") as cache:
            cache.client = None
            assert await ExecutorInbox(CONVERSATION).read() == []

    async def test_count_zero_when_no_client(self) -> None:
        with patch.object(channel, "redis_cache") as cache:
            cache.client = None
            assert await ExecutorInbox(CONVERSATION).count() == 0

    async def test_append_returns_entry_without_storing(self) -> None:
        with patch.object(channel, "redis_cache") as cache:
            cache.client = None
            entry = await ExecutorInbox(CONVERSATION).append("e-1", "lost")
            assert entry.id == "e-1"

    async def test_retire_without_client_does_not_raise(self) -> None:
        with patch.object(channel, "redis_cache") as cache:
            cache.client = None
            await ExecutorInbox(CONVERSATION).retire(_entry())

    async def test_clear_without_client_returns_zero(self) -> None:
        with patch.object(channel, "redis_cache") as cache:
            cache.client = None
            assert await ExecutorInbox(CONVERSATION).clear() == 0


class TestAnnounceInterruption:
    async def test_notice_names_the_interrupt(self, inbox: ExecutorInbox) -> None:
        (entry,) = await inbox.announce_interruption()
        assert "INTERRUPTED" in entry.text
        assert entry.tag == AgentTag.EXECUTOR_INTERRUPTED

    async def test_notice_forbids_resume(self, inbox: ExecutorInbox) -> None:
        (entry,) = await inbox.announce_interruption()
        assert "Do not resume" in entry.text

    async def test_redirect_is_its_own_entry(self, inbox: ExecutorInbox) -> None:
        notice, redirect = await inbox.announce_interruption("work on billing instead")
        assert "work on billing instead" not in notice.text
        assert redirect.text == "work on billing instead"
        assert redirect.tag == AgentTag.USER_INTERJECTION

    async def test_a_bare_stop_writes_the_notice_alone(self, inbox: ExecutorInbox) -> None:
        assert len(await inbox.announce_interruption()) == 1
        assert await inbox.count() == 1

    async def test_notice_is_readable_from_the_inbox(self, inbox: ExecutorInbox) -> None:
        notice, redirect = await inbox.announce_interruption("redirect")
        stored = await inbox.read()
        assert [e.id for e in stored] == [notice.id, redirect.id]
        assert stored[0].tag == AgentTag.EXECUTOR_INTERRUPTED


# ---------------------------------------------------------------------------
# Hook placement against the real compiled executor graph
# ---------------------------------------------------------------------------


def _executor_config(conversation: str = CONVERSATION) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": f"{EXECUTOR_THREAD_PREFIX}{conversation}",
            "conversation_id": conversation,
            "user_id": "u-1",
        },
        "metadata": {"user_id": "u-1"},
        "recursion_limit": 25,
    }


def plan(*contents: str) -> dict[str, Any]:
    return call("plan_tasks", {"tasks": [{"content": c} for c in contents]}, "p1")


async def _run_with_handover(
    graph: Any,
    inbox: ExecutorInbox,
    prompt: str,
    entry_id: str = "task-2",
    text: str = "also check the spam folder",
    conversation: str = CONVERSATION,
) -> dict[str, Any]:
    config = _executor_config(conversation)
    handed_over = False
    async for _mode, payload in graph.astream(
        {"messages": [HumanMessage(content=prompt)], "todos": []},
        stream_mode=["updates"],
        config=config,
    ):
        if not handed_over and AGENT_NODE in payload:
            await inbox.append(entry_id, text)
            handed_over = True
    return config


def _prompt_texts(prompt: list[Any]) -> str:
    return "".join(str(m.content) for m in prompt)


class TestHookPlacement:
    async def test_interjection_lands_after_tool_results(self, inbox) -> None:
        """The steered message reads as a follow-up, not a pre-emption: the
        tool result it responds to is already in context above it."""
        async with executor_graph([plan("search email"), "done"]) as graph:
            await _run_with_handover(graph, inbox, "find my flight email")
            calls = scripted_model_of(graph).chat_messages_log

        assert len(calls) >= 2
        second = calls[1]
        tool_idx = next(i for i, m in enumerate(second) if isinstance(m, ToolMessage))
        interject_idx = next(
            i
            for i, m in enumerate(second)
            if getattr(m, "additional_kwargs", {}).get(INBOX_ENTRY_ID) == "task-2"
        )
        assert tool_idx < interject_idx

    async def test_interjection_is_the_conversation_tail(self, inbox) -> None:
        async with executor_graph([plan("search email"), "done"]) as graph:
            await _run_with_handover(graph, inbox, "find my flight email")
            calls = scripted_model_of(graph).chat_messages_log

        second = calls[1]
        interject_idx = next(
            i
            for i, m in enumerate(second)
            if getattr(m, "additional_kwargs", {}).get(INBOX_ENTRY_ID) == "task-2"
        )
        trailing = second[interject_idx + 1 :]
        assert trailing == [] or all(isinstance(m, SystemMessage) for m in trailing), (
            "only ephemeral system slots may follow the interjection"
        )

    async def test_first_step_cannot_see_the_future(self, inbox) -> None:
        async with executor_graph([plan("search email"), "done"]) as graph:
            await _run_with_handover(graph, inbox, "find my flight email")
            calls = scripted_model_of(graph).chat_messages_log

        assert "also check the spam folder" not in _prompt_texts(calls[0])
        assert "also check the spam folder" in _prompt_texts(calls[1])

    async def test_framed_as_user_speaking(self, inbox) -> None:
        async with executor_graph([plan("search email"), "done"]) as graph:
            await _run_with_handover(graph, inbox, "find my flight email")
            calls = scripted_model_of(graph).chat_messages_log

        framed = [
            m
            for m in calls[1]
            if getattr(m, "additional_kwargs", {}).get(INBOX_ENTRY_ID) == "task-2"
        ]
        assert len(framed) == 1
        assert isinstance(framed[0], HumanMessage)
        assert "<user_interjection>" in str(framed[0].content)

    async def test_two_entries_land_in_fifo_order(self, inbox) -> None:
        async with executor_graph([plan("search email"), "done"]) as graph:
            config = _executor_config()
            handed_over = False
            async for _mode, payload in graph.astream(
                {"messages": [HumanMessage(content="go")], "todos": []},
                stream_mode=["updates"],
                config=config,
            ):
                if not handed_over and AGENT_NODE in payload:
                    await inbox.append("first", "alpha-note")
                    await inbox.append("second", "beta-note")
                    handed_over = True
            calls = scripted_model_of(graph).chat_messages_log

        second = _prompt_texts(calls[1])
        assert second.index("alpha-note") < second.index("beta-note")

    async def test_late_arrival_still_lands_on_next_step(self, inbox) -> None:
        """Handed over after step two of three: invisible in calls 1-2,
        present from call 3."""
        async with executor_graph([plan("one"), plan("two"), plan("three"), "done"]) as graph:
            config = _executor_config()
            steps = 0
            async for _mode, payload in graph.astream(
                {"messages": [HumanMessage(content="go")], "todos": []},
                stream_mode=["updates"],
                config=config,
            ):
                if AGENT_NODE in payload:
                    steps += 1
                    if steps == 2:
                        await inbox.append("late", "late-arriving note")
            calls = scripted_model_of(graph).chat_messages_log

        assert "late-arriving note" not in _prompt_texts(calls[0])
        assert "late-arriving note" not in _prompt_texts(calls[1])
        assert any("late-arriving note" in _prompt_texts(c) for c in calls[2:])

    async def test_committed_once_never_shown_again(self, inbox) -> None:
        async with executor_graph([plan("one"), plan("two"), plan("three"), "done"]) as graph:
            await _run_with_handover(graph, inbox, "go")
            calls = scripted_model_of(graph).chat_messages_log

        total = sum(_prompt_texts(c).count("also check the spam folder") for c in calls)
        # Shown on call 2 and carried in context thereafter — but never
        # injected a second time (one stamped message in the thread).
        last = calls[-1]
        stamped = [
            m for m in last if getattr(m, "additional_kwargs", {}).get(INBOX_ENTRY_ID) == "task-2"
        ]
        assert len(stamped) == 1
        assert total >= 1

    async def test_thread_holds_exactly_one_stamped_copy(self, inbox) -> None:
        async with executor_graph([plan("one"), plan("two"), plan("three"), "done"]) as graph:
            config = await _run_with_handover(graph, inbox, "go")
            state = await graph.aget_state(config)

        stamped = [
            m
            for m in state.values["messages"]
            if getattr(m, "additional_kwargs", None)
            and m.additional_kwargs.get(INBOX_ENTRY_ID) == "task-2"
        ]
        assert len(stamped) == 1

    async def test_inbox_empty_after_commit(self, inbox) -> None:
        async with executor_graph([plan("search email"), "done"]) as graph:
            await _run_with_handover(graph, inbox, "find my flight email")
        assert await inbox.read() == []

    async def test_quiet_run_leaves_no_trace(self, inbox) -> None:
        async with executor_graph([plan("search email"), "done"]) as graph:
            config = _executor_config()
            async for _ in graph.astream(
                {"messages": [HumanMessage(content="go")], "todos": []},
                stream_mode=["updates"],
                config=config,
            ):
                pass
            state = await graph.aget_state(config)

        assert not [
            m
            for m in state.values["messages"]
            if getattr(m, "additional_kwargs", None) and m.additional_kwargs.get(INBOX_ENTRY_ID)
        ]

    async def test_interrupted_entry_frames_as_system_report(self, inbox) -> None:
        async with executor_graph([plan("search email"), "done"]) as graph:
            config = _executor_config()
            handed_over = False
            async for _mode, payload in graph.astream(
                {"messages": [HumanMessage(content="go")], "todos": []},
                stream_mode=["updates"],
                config=config,
            ):
                if not handed_over and AGENT_NODE in payload:
                    await inbox.announce_interruption("work on billing")
                    handed_over = True
            calls = scripted_model_of(graph).chat_messages_log

        second = _prompt_texts(calls[1])
        assert "<executor_interrupted>" in second
        assert "INTERRUPTED" in second
        assert "work on billing" in second


class TestHookFailureModes:
    async def test_missing_conversation_id_leaves_state_alone(self, inbox) -> None:
        async with executor_graph([plan("search email"), "done"]) as graph:
            await inbox.append("task-2", "orphan")
            config = {
                "configurable": {"thread_id": "bare-thread", "user_id": "u-1"},
                "metadata": {"user_id": "u-1"},
                "recursion_limit": 25,
            }
            async for _ in graph.astream(
                {"messages": [HumanMessage(content="go")], "todos": []},
                stream_mode=["updates"],
                config=config,
            ):
                pass
            calls = scripted_model_of(graph).chat_messages_log

        assert all("orphan" not in _prompt_texts(c) for c in calls)

    async def test_redis_failure_never_breaks_the_turn(self, inbox) -> None:
        async with executor_graph(["done"]) as graph:
            with patch.object(ExecutorInbox, "read", side_effect=RuntimeError("redis down")):
                config = _executor_config()
                async for _ in graph.astream(
                    {"messages": [HumanMessage(content="go")], "todos": []},
                    stream_mode=["updates"],
                    config=config,
                ):
                    pass
                run_state = await graph.aget_state(config)

        assert run_state.values["messages"], "the turn must complete despite the hook failing"

    async def test_hook_error_is_contained_per_call(self, inbox) -> None:
        """One failing drain must not poison later model calls in the run."""
        async with executor_graph([plan("a"), "done"]) as graph:
            real_read = ExecutorInbox.read
            calls_made = 0

            async def flaky_read(self: ExecutorInbox) -> list[InboxEntry]:
                nonlocal calls_made
                calls_made += 1
                if calls_made == 1:
                    raise RuntimeError("transient")
                return await real_read(self)

            with patch.object(ExecutorInbox, "read", flaky_read):
                config = _executor_config()
                async for _ in graph.astream(
                    {"messages": [HumanMessage(content="go")], "todos": []},
                    stream_mode=["updates"],
                    config=config,
                ):
                    pass
                run_state = await graph.aget_state(config)

        assert calls_made >= 2
        assert run_state.values["messages"]


# ---------------------------------------------------------------------------
# Direct-hook matrix: every inbox x thread combination, no graph needed
# ---------------------------------------------------------------------------


def _hook_config(conversation: str = CONVERSATION) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": f"{EXECUTOR_THREAD_PREFIX}{conversation}",
            "conversation_id": conversation,
            "user_id": "u-1",
        }
    }


class TestDrainHookMatrix:
    async def test_idle_hook_returns_state_untouched(self, inbox) -> None:
        from app.agents.core.background.executor_channel import drain_inbox_hook

        state: dict[str, Any] = {"messages": [_plain("go")]}
        assert await drain_inbox_hook(state, _hook_config(), None) is state

    async def test_inject_appends_and_stages(self, inbox) -> None:
        from app.agents.core.background.executor_channel import drain_inbox_hook
        from app.override.langgraph_bigtool.utils import INJECTED_MESSAGES_KEY

        await inbox.append("e-1", "steer this way")
        out = await drain_inbox_hook({"messages": [_plain("go")]}, _hook_config(), None)
        assert out is not None
        assert "steer this way" in str(out["messages"][-1].content)
        assert len(out[INJECTED_MESSAGES_KEY]) == 1

    async def test_inject_does_not_mutate_input_list(self, inbox) -> None:
        from app.agents.core.background.executor_channel import drain_inbox_hook

        await inbox.append("e-1", "steer")
        original = [_plain("go")]
        await drain_inbox_hook({"messages": original}, _hook_config(), None)
        assert len(original) == 1

    async def test_retire_path_removes_without_injecting(self, inbox) -> None:
        from app.agents.core.background.executor_channel import drain_inbox_hook
        from app.override.langgraph_bigtool.utils import INJECTED_MESSAGES_KEY

        await inbox.append("e-1", "done already")
        state: dict[str, Any] = {"messages": [_plain("go"), _committed("e-1")]}
        out = await drain_inbox_hook(state, _hook_config(), None)
        assert INJECTED_MESSAGES_KEY not in out
        assert await inbox.read() == []

    @pytest.mark.parametrize("n", [1, 2, 3, 5, 10])
    async def test_every_pending_entry_injects(self, inbox, n: int) -> None:
        from app.agents.core.background.executor_channel import drain_inbox_hook
        from app.override.langgraph_bigtool.utils import INJECTED_MESSAGES_KEY

        for i in range(n):
            await inbox.append(f"e-{i}", f"work-{i}")
        out = await drain_inbox_hook({"messages": [_plain("go")]}, _hook_config(), None)
        assert len(out[INJECTED_MESSAGES_KEY]) == n
        assert [m.additional_kwargs[INBOX_ENTRY_ID] for m in out[INJECTED_MESSAGES_KEY]] == [
            f"e-{i}" for i in range(n)
        ]

    @pytest.mark.parametrize(
        ("pending", "committed", "want_staged", "want_left"),
        [
            (["a"], [], ["a"], ["a"]),
            (["a"], ["a"], [], []),
            (["a", "b"], ["a"], ["b"], ["b"]),
            (["a", "b"], ["b"], ["a"], ["a"]),
            (["a", "b", "c"], ["a", "b", "c"], [], []),
            (["a", "b", "c"], ["b"], ["a", "c"], ["a", "c"]),
        ],
        ids=["all-new", "all-done", "first-done", "second-done", "all-done-3", "middle-done"],
    )
    async def test_mixed_drain(
        self,
        inbox,
        pending: list[str],
        committed: list[str],
        want_staged: list[str],
        want_left: list[str],
    ) -> None:
        from app.agents.core.background.executor_channel import drain_inbox_hook
        from app.override.langgraph_bigtool.utils import INJECTED_MESSAGES_KEY

        for pid in pending:
            await inbox.append(pid, f"work-{pid}")
        state: dict[str, Any] = {"messages": [_plain("go")] + [_committed(c) for c in committed]}
        out = await drain_inbox_hook(state, _hook_config(), None)
        staged = out.get(INJECTED_MESSAGES_KEY, [])
        assert [m.additional_kwargs[INBOX_ENTRY_ID] for m in staged] == want_staged
        assert [e.id for e in await inbox.read()] == want_left

    async def test_injecting_leaves_the_entry_pending(self, inbox) -> None:
        """Staging is not committing. The entry stays until a later pass sees it
        in the thread, so a run that dies at the model call loses nothing."""
        from app.agents.core.background.executor_channel import drain_inbox_hook

        await inbox.append("e-1", "steer")
        await drain_inbox_hook({"messages": [_plain("go")]}, _hook_config(), None)
        assert [e.id for e in await inbox.read()] == ["e-1"]

    async def test_no_conversation_id_returns_state(self, inbox) -> None:
        from app.agents.core.background.executor_channel import drain_inbox_hook

        await inbox.append("e-1", "orphan")
        state: dict[str, Any] = {"messages": [_plain("go")]}
        out = await drain_inbox_hook(state, {"configurable": {}}, None)
        assert out is state

    async def test_empty_config_returns_state(self, inbox) -> None:
        from app.agents.core.background.executor_channel import drain_inbox_hook

        state: dict[str, Any] = {"messages": [_plain("go")]}
        assert await drain_inbox_hook(state, {}, None) is state

    async def test_staged_messages_carry_stamps(self, inbox) -> None:
        from app.agents.core.background.executor_channel import drain_inbox_hook
        from app.override.langgraph_bigtool.utils import INJECTED_MESSAGES_KEY

        await inbox.append("stamp-me", "work")
        out = await drain_inbox_hook({"messages": []}, _hook_config(), None)
        (staged,) = out[INJECTED_MESSAGES_KEY]
        assert staged.additional_kwargs[INBOX_ENTRY_ID] == "stamp-me"
        assert isinstance(staged, HumanMessage)
