"""Checkpointed threads must not accumulate per-run prompt framing.

Every run injects a fresh system-prompt stack (static + dynamic context + time
clock), exactly as _core_agent_logic does. Pre-model hooks filter those per
call, but for months the filtering was request-only — the checkpointed
messages channel kept every run's copy, and the end-of-graph hook echoed the
whole accumulated list back through the reducer as a fresh write each run. On
one production workflow thread this reached 39 retained prompt copies, ~4.8 MB
per run, 19 GB of Postgres total.

Pinned here: stale slot messages are tombstoned out of the checkpoint, not
just hidden from the model, and the end-graph hook node never re-emits the
message list as a channel write.
"""

from __future__ import annotations

from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from tests.e2e._harness.graph_run import comms_graph, run_graph

pytestmark = pytest.mark.e2e

END_HOOKS_NODE = "end_graph_hooks"


def _run_input(run_no: int) -> dict:
    """Build a graph input shaped like construct_langchain_messages output.

    Fresh message objects per run (new ids), same slots: one static system
    prompt, one dynamic-context system message, one time-context clock line,
    then the user turn.
    """
    return {
        "messages": [
            SystemMessage(content=f"You are GAIA. (static prompt, run {run_no})"),
            SystemMessage(
                content=f"[dynamic context for run {run_no}]",
                additional_kwargs={"dynamic_context": True},
            ),
            HumanMessage(
                content=f"[current time: 2026-08-11T0{run_no}:00:00]",
                additional_kwargs={"time_context": True},
            ),
            HumanMessage(content=f"user message {run_no}"),
        ],
        "todos": [],
    }


class TestPromptFramingIsPrunedFromCheckpointState:
    @pytest.mark.regression
    async def test_stale_system_prompts_are_tombstoned_out_of_the_thread(self):
        """Without durable pruning, each prompt slot would accumulate one message per run (production reached 39 static-prompt copies on one thread)."""
        thread_id = f"prune-{uuid4()}"
        async with comms_graph(["ok one", "ok two", "ok three"]) as graph:
            for run_no in (1, 2, 3):
                await run_graph(graph, "", thread_id=thread_id, state=_run_input(run_no))
            config = {"configurable": {"thread_id": thread_id, "user_id": "u-1"}}
            snapshot = await graph.aget_state(config)

        messages = snapshot.values["messages"]
        statics = [
            m
            for m in messages
            if m.type == "system"
            and not m.additional_kwargs.get("dynamic_context")
            and not m.additional_kwargs.get("memory_recall")
        ]
        dynamics = [
            m for m in messages if m.type == "system" and m.additional_kwargs.get("dynamic_context")
        ]
        clocks = [m for m in messages if m.additional_kwargs.get("time_context")]

        assert len(statics) == 1, f"expected 1 static prompt in state, found {len(statics)}"
        assert "run 3" in str(statics[0].content), "kept static prompt is not the latest run's"
        assert len(dynamics) == 1, f"expected 1 dynamic-context message, found {len(dynamics)}"
        assert "run 3" in str(dynamics[0].content), "kept dynamic context is not the latest run's"
        assert len(clocks) == 1, f"expected 1 time-context message, found {len(clocks)}"
        assert "T03:" in str(clocks[0].content), "kept clock is not the latest run's"

    async def test_conversation_itself_survives_pruning(self):
        """Deliberately NOT @regression: guards against over-pruning and legitimately passes on base, where nothing is pruned."""
        thread_id = f"keep-{uuid4()}"
        async with comms_graph(["reply one", "reply two"]) as graph:
            for run_no in (1, 2):
                await run_graph(graph, "", thread_id=thread_id, state=_run_input(run_no))
            config = {"configurable": {"thread_id": thread_id, "user_id": "u-1"}}
            snapshot = await graph.aget_state(config)

        messages = snapshot.values["messages"]
        user_turns = [
            m for m in messages if m.type == "human" and not m.additional_kwargs.get("time_context")
        ]
        ai_turns = [m for m in messages if m.type == "ai"]
        assert [str(m.content) for m in user_turns] == ["user message 1", "user message 2"]
        assert len(ai_turns) == 2


class TestEndGraphHooksWriteNothing:
    @pytest.mark.regression
    async def test_end_hooks_node_does_not_rewrite_the_message_list(self):
        """Its hooks (follow-up streaming, memory ingestion) never modify messages — echoing the state back would re-serialize the whole thread every run."""
        async with comms_graph(["done"]) as graph:
            run = await run_graph(graph, "", thread_id=f"echo-{uuid4()}", state=_run_input(1))

        echoed = [e for e in run.events if e.node == END_HOOKS_NODE]
        assert echoed == [], (
            f"end_graph_hooks re-emitted {len(echoed)} messages as a channel write; "
            "it must return only the keys its hooks actually changed"
        )
