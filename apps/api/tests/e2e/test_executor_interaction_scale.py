"""Comms<->executor interaction at scale, without a model in the loop.

The matrix file proves one hand-over in depth. This file proves the interaction
*over time*: hand-overs at every depth of a run, several in one run, across
consecutive turns on one thread, across two interleaved conversations, and the
entries that arrive too late — all against the real compiled executor graph
with a scripted model, asserting on the recorded prompts and the thread.

What this still does not prove (and nothing here can): whether a real model
*acts well* on a hint. Placement, survival, ordering, isolation and exactly-once
are plumbing; judgment needs a live model.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import fakeredis.aioredis
from langchain_core.messages import HumanMessage, ToolMessage
import pytest

from app.agents.core.background import executor_channel as channel
from app.agents.core.background.executor_channel import INBOX_ENTRY_ID, ExecutorInbox
from app.constants.agents import AgentTag
from app.constants.general import EXECUTOR_THREAD_PREFIX
from tests.e2e._harness.graph_run import AGENT_NODE, call, executor_graph, scripted_model_of

pytestmark = pytest.mark.e2e

CONVERSATION = "conv-interaction-scale"
OTHER = "conv-interaction-other"


def plan(*contents: str) -> dict[str, Any]:
    return call("plan_tasks", {"tasks": [{"content": c} for c in contents]}, "p1")


def _config(conversation: str = CONVERSATION) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": f"{EXECUTOR_THREAD_PREFIX}{conversation}",
            "conversation_id": conversation,
            "user_id": "u-1",
        },
        "metadata": {"user_id": "u-1"},
        "recursion_limit": 30,
    }


@pytest.fixture
async def inbox():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(channel, "redis_cache") as cache:
        cache.client = client
        yield ExecutorInbox(CONVERSATION)
    await client.aclose()


async def _drive(
    graph: Any,
    prompt: str,
    handovers: dict[int, list[tuple[str, str]]],
    conversation: str = CONVERSATION,
) -> tuple[dict[str, Any], list[list[Any]]]:
    """Run one turn, appending inbox entries after the given agent steps.

    ``handovers`` maps the 1-based agent-step count to entries appended right
    after that step's update — the production shape, where ``call_executor``
    writes from another task mid-astream.
    """
    inbox = ExecutorInbox(conversation)
    config = _config(conversation)
    steps = 0
    seen_prompts = len(scripted_model_of(graph).chat_messages_log)
    async for _mode, payload in graph.astream(
        {"messages": [HumanMessage(content=prompt)], "todos": []},
        stream_mode=["updates"],
        config=config,
    ):
        if AGENT_NODE in payload:
            steps += 1
            for entry_id, text in handovers.get(steps, []):
                await inbox.append(entry_id, text)
    return config, scripted_model_of(graph).chat_messages_log[seen_prompts:]


def _texts(prompt: list[Any]) -> str:
    return "".join(str(m.content) for m in prompt)


def _stamped(prompt: list[Any], entry_id: str) -> list[Any]:
    return [
        m for m in prompt if getattr(m, "additional_kwargs", {}).get(INBOX_ENTRY_ID) == entry_id
    ]


class TestHandoverAtEveryDepth:
    @pytest.mark.parametrize("steps", [2, 3, 4, 5])
    async def test_handover_after_first_step(self, inbox, steps: int) -> None:
        script: list[Any] = [plan(f"job-{i}") for i in range(steps - 1)] + ["done"]
        async with executor_graph(script) as graph:
            _, calls = await _drive(graph, "go", {1: [("e-1", "steer-left")]})

        assert "steer-left" not in _texts(calls[0])
        assert "steer-left" in _texts(calls[1])

    @pytest.mark.parametrize(
        ("steps", "at"),
        [(3, 2), (4, 2), (4, 3), (5, 2), (5, 3), (5, 4)],
        ids=["3-at-2", "4-at-2", "4-at-3", "5-at-2", "5-at-3", "5-at-4"],
    )
    async def test_handover_after_later_step(self, inbox, steps: int, at: int) -> None:
        script = [plan(f"job-{i}") for i in range(steps - 1)] + ["done"]
        async with executor_graph(script) as graph:
            _, calls = await _drive(graph, "go", {at: [("e-1", "late-steer")]})

        for i in range(at):
            assert "late-steer" not in _texts(calls[i]), f"visible too early (call {i})"
        assert any("late-steer" in _texts(c) for c in calls[at:])

    @pytest.mark.parametrize("at", [1, 2, 3])
    async def test_thread_holds_one_copy_whatever_the_depth(self, inbox, at: int) -> None:
        async with executor_graph([plan("a"), plan("b"), plan("c"), "done"]) as graph:
            config, _ = await _drive(graph, "go", {at: [("e-1", "deep-note")]})
            state = await graph.aget_state(config)

        stamped = [
            m
            for m in state.values["messages"]
            if getattr(m, "additional_kwargs", None)
            and m.additional_kwargs.get(INBOX_ENTRY_ID) == "e-1"
        ]
        assert len(stamped) == 1


class TestBursts:
    @pytest.mark.parametrize("n", [2, 3, 5])
    async def test_burst_lands_in_fifo_order(self, inbox, n: int) -> None:
        entries = [(f"e-{i}", f"burst-note-{i}") for i in range(n)]
        async with executor_graph([plan("work"), "done"]) as graph:
            _, calls = await _drive(graph, "go", {1: entries})

        second = _texts(calls[1])
        positions = [second.index(f"burst-note-{i}") for i in range(n)]
        assert positions == sorted(positions)

    async def test_burst_of_five_all_survive(self, inbox) -> None:
        entries = [(f"e-{i}", f"burst-note-{i}") for i in range(5)]
        async with executor_graph([plan("work"), "done"]) as graph:
            config, _ = await _drive(graph, "go", {1: entries})
            state = await graph.aget_state(config)

        for i in range(5):
            stamped = [
                m
                for m in state.values["messages"]
                if getattr(m, "additional_kwargs", None)
                and m.additional_kwargs.get(INBOX_ENTRY_ID) == f"e-{i}"
            ]
            assert len(stamped) == 1, f"entry e-{i} lost or duplicated"

    async def test_two_waves_land_in_wave_order(self, inbox) -> None:
        async with executor_graph([plan("a"), plan("b"), "done"]) as graph:
            _, calls = await _drive(graph, "go", {1: [("w1", "wave-one")], 2: [("w2", "wave-two")]})

        assert "wave-one" in _texts(calls[1])
        assert "wave-two" not in _texts(calls[1])
        tail = _texts(calls[-1])
        assert tail.index("wave-one") < tail.index("wave-two")

    async def test_inbox_drains_fully_after_burst(self, inbox) -> None:
        entries = [(f"e-{i}", f"note-{i}") for i in range(3)]
        async with executor_graph([plan("work"), "done"]) as graph:
            await _drive(graph, "go", {1: entries})

        assert await inbox.read() == []


class TestAcrossTurns:
    async def test_second_turn_sees_first_turns_interjection(self, inbox) -> None:
        async with executor_graph([plan("a"), "done", plan("b"), "done"]) as graph:
            await _drive(graph, "first", {1: [("e-1", "remember-this")]})
            config, calls = await _drive(graph, "second", {})

        assert "remember-this" in _texts(calls[0])
        state = await graph.aget_state(config)
        assert any(
            getattr(m, "additional_kwargs", {}).get(INBOX_ENTRY_ID) == "e-1"
            for m in state.values["messages"]
        )

    async def test_each_turns_handover_stays_distinct(self, inbox) -> None:
        async with executor_graph([plan("a"), "done", plan("b"), "done"]) as graph:
            await _drive(graph, "first", {1: [("e-1", "first-note")]})
            config, calls = await _drive(graph, "second", {1: [("e-2", "second-note")]})
            state = await graph.aget_state(config)

        stamped_ids = {
            m.additional_kwargs[INBOX_ENTRY_ID]
            for m in state.values["messages"]
            if getattr(m, "additional_kwargs", None) and m.additional_kwargs.get(INBOX_ENTRY_ID)
        }
        assert {"e-1", "e-2"} <= stamped_ids
        assert "second-note" in _texts(calls[1])

    async def test_quiet_second_turn_reinjects_nothing(self, inbox) -> None:
        async with executor_graph([plan("a"), "done", "fine"]) as graph:
            await _drive(graph, "first", {1: [("e-1", "first-note")]})
            _, calls = await _drive(graph, "second", {})

        for prompt in calls:
            assert not _stamped(prompt, "e-1") or _texts(prompt).count("first-note") <= 1


class TestConversationIsolation:
    async def test_entries_do_not_cross_conversations(self, inbox) -> None:
        other_inbox = ExecutorInbox(OTHER)
        await other_inbox.append("other-1", "other-work")
        async with executor_graph([plan("work"), "done"]) as graph:
            _, calls = await _drive(graph, "go", {1: [("mine", "my-work")]})

        assert "other-work" not in _texts(calls[1])
        assert "my-work" in _texts(calls[1])
        assert [e.id for e in await other_inbox.read()] == ["other-1"]

    async def test_interleaved_turns_keep_their_own_notes(self, inbox) -> None:
        async with executor_graph(
            [plan("a"), "done", plan("b"), "done", plan("c"), "done"]
        ) as graph:
            await _drive(graph, "mine", {1: [("mine", "my-note")]}, CONVERSATION)
            _, other_calls = await _drive(graph, "theirs", {}, OTHER)
            _, my_calls = await _drive(graph, "mine-again", {}, CONVERSATION)

        assert all("my-note" not in _texts(c) for c in other_calls)
        assert "my-note" in _texts(my_calls[0])


class TestTooLateEntries:
    async def test_entry_after_the_last_step_stays_pending(self, inbox) -> None:
        """Nothing left to drain into: the entry must sit pending, absent from
        the thread, so finalize carries it instead of losing it."""
        async with executor_graph(["done"]) as graph:
            config = _config()
            async for _mode, payload in graph.astream(
                {"messages": [HumanMessage(content="go")], "todos": []},
                stream_mode=["updates"],
                config=config,
            ):
                if AGENT_NODE in payload:
                    await inbox.append("too-late", "arrived at the end")

        assert [e.id for e in await inbox.read()] == ["too-late"]

    async def test_an_absorbed_entry_is_retired_not_carried(self, inbox) -> None:
        """Committed to the thread on an earlier pass, so a later pass retires
        it — there is nothing left for finalize to carry into a second run."""
        async with executor_graph([plan("work"), "done"]) as graph:
            await _drive(graph, "go", {1: [("e-1", "absorbed")]})

        assert await inbox.read() == []


class TestDiscardThenDrain:
    async def test_discarded_entry_never_reaches_the_model(self, inbox) -> None:
        async with executor_graph([plan("work"), "done"]) as graph:
            config = _config()
            handed_over = False
            async for _mode, payload in graph.astream(
                {"messages": [HumanMessage(content="go")], "todos": []},
                stream_mode=["updates"],
                config=config,
            ):
                if not handed_over and AGENT_NODE in payload:
                    await inbox.append("drop-me", "cancelled thought")
                    await inbox.discard({"drop-me"})
                    handed_over = True
            calls = scripted_model_of(graph).chat_messages_log

        assert all("cancelled thought" not in _texts(c) for c in calls)

    async def test_discard_one_keeps_the_other(self, inbox) -> None:
        async with executor_graph([plan("work"), "done"]) as graph:
            config = _config()
            handed_over = False
            async for _mode, payload in graph.astream(
                {"messages": [HumanMessage(content="go")], "todos": []},
                stream_mode=["updates"],
                config=config,
            ):
                if not handed_over and AGENT_NODE in payload:
                    await inbox.append("drop", "gone")
                    await inbox.append("keep", "stays")
                    await inbox.discard({"drop"})
                    handed_over = True
            calls = scripted_model_of(graph).chat_messages_log

        assert "stays" in _texts(calls[1])
        assert all("gone" not in _texts(c) for c in calls)


class TestInterruptionCommitted:
    async def test_interrupt_note_lands_with_its_tag_and_stamp(self, inbox) -> None:
        async with executor_graph([plan("work"), "done"]) as graph:
            config = _config()
            handed_over = False
            async for _mode, payload in graph.astream(
                {"messages": [HumanMessage(content="go")], "todos": []},
                stream_mode=["updates"],
                config=config,
            ):
                if not handed_over and AGENT_NODE in payload:
                    await inbox.announce_interruption("do billing instead")
                    handed_over = True
            calls = scripted_model_of(graph).chat_messages_log
            state = await graph.aget_state(config)

        assert "<executor_interrupted>" in _texts(calls[1])
        stamped = [
            m
            for m in state.values["messages"]
            if getattr(m, "additional_kwargs", None) and m.additional_kwargs.get(INBOX_ENTRY_ID)
        ]
        # Two, not one: the stop and the redirect are separate entries, so a
        # BARE stop can never look like work and start a run of its own.
        notice, redirect = stamped
        assert f"<{AgentTag.EXECUTOR_INTERRUPTED}>" in str(notice.content)
        assert "do billing instead" not in str(notice.content)
        assert f"<{AgentTag.USER_INTERJECTION}>" in str(redirect.content)
        assert "do billing instead" in str(redirect.content)

    async def test_interrupt_clears_with_clear(self, inbox) -> None:
        await inbox.append("e-1", "work")
        assert await inbox.clear() == 1
        async with executor_graph(["done"]) as graph:
            _, calls = await _drive(graph, "go", {})

        assert calls, "the turn must still run"
        assert all(not _stamped(c, "e-1") for c in calls)


class TestPlacementInvariants:
    async def test_interjection_never_precedes_its_tool_result(self, inbox) -> None:
        async with executor_graph([plan("a"), plan("b"), "done"]) as graph:
            _, calls = await _drive(graph, "go", {1: [("e-1", "steer")]})
            second = calls[1]

        tool_positions = [i for i, m in enumerate(second) if isinstance(m, ToolMessage)]
        steer_positions = [
            i
            for i, m in enumerate(second)
            if getattr(m, "additional_kwargs", {}).get(INBOX_ENTRY_ID) == "e-1"
        ]
        assert tool_positions and steer_positions
        assert min(tool_positions) < min(steer_positions)

    async def test_original_request_stays_first(self, inbox) -> None:
        async with executor_graph([plan("work"), "done"]) as graph:
            _, calls = await _drive(graph, "go", {1: [("e-1", "steer")]})

        human_texts = [str(m.content) for m in calls[1] if isinstance(m, HumanMessage)]
        assert human_texts[0] == "go"
