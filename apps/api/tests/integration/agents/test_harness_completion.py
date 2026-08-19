"""Harness-owned completion: the executor cannot silently quit early.

Exercises the real create_agent graph (should_continue + the nudge_continue
node) with a scripted fake model, so no LLM key or DB is needed. Proves:

- an executor (require_finish_to_end=True) that replies in plain text while work
  is demonstrably unfinished (a pending todo, or no tool ever used) is nudged
  once and loops instead of ending;
- the nudge is bounded (MAX_COMPLETION_NUDGES) so it cannot loop forever;
- a normal completed run (tool used, no pending todos) is NOT taxed with a nudge;
- comms-style agents (require_finish_to_end=False) end on plain text as before.
"""

from __future__ import annotations

from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
import pytest

from app.constants.llm import COMPLETION_NUDGE_MESSAGE, MAX_COMPLETION_NUDGES
from app.override.langgraph_bigtool.create_agent import create_agent
from tests.helpers import create_fake_llm, create_fake_llm_with_tool_calls


@tool
def lookup(query: str) -> str:
    """Look up a value."""
    return f"result for {query}"


def _compile(llm, *, require_finish_to_end: bool):
    builder = create_agent(
        llm=llm,
        tool_registry={"lookup": lookup},
        agent_name="executor_agent",
        disable_retrieve_tools=True,
        initial_tool_ids=["lookup"],
        require_finish_to_end=require_finish_to_end,
    )
    return builder.compile(checkpointer=MemorySaver(), store=InMemoryStore())


def _nudges(messages) -> list:
    return [
        m for m in messages if isinstance(m, HumanMessage) and m.content == COMPLETION_NUDGE_MESSAGE
    ]


@pytest.mark.integration
class TestHarnessCompletion:
    async def test_pending_todo_triggers_nudge_then_terminates(self):
        """Plain-text stop with a pending todo → exactly one nudge, then ends."""
        # Turn 1: bare deferral. Turn 2 (after nudge): the real result.
        llm = create_fake_llm(["On it.", "Final result: triaged 3 emails."])
        graph = _compile(llm, require_finish_to_end=True)

        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content="triage my inbox")],
                "todos": [
                    {
                        "id": "t1",
                        "content": "archive promos",
                        "status": "pending",
                        "created_at": "2026-01-01T00:00:00",
                    }
                ],
            },
            config={"configurable": {"thread_id": str(uuid4())}},
        )

        nudges = _nudges(result["messages"])
        assert len(nudges) == MAX_COMPLETION_NUDGES, (
            f"expected exactly {MAX_COMPLETION_NUDGES} completion nudge(s), got {len(nudges)}"
        )
        # The run terminated (did not spin forever) and the last message is the
        # model's real answer produced after the nudge.
        final = result["messages"][-1]
        assert isinstance(final, AIMessage)
        assert "Final result" in final.content

    async def test_no_nudge_when_enough_tools_used(self):
        """Real completed tool work + no pending todos →
        normal completion, no nudge tax."""
        c1 = {"name": "lookup", "args": {"query": "a"}, "id": "c1", "type": "tool_call"}
        c2 = {"name": "lookup", "args": {"query": "b"}, "id": "c2", "type": "tool_call"}
        llm = create_fake_llm_with_tool_calls([c1, c2, "Done."])
        graph = _compile(llm, require_finish_to_end=True)

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="look up a and b")]},
            config={"configurable": {"thread_id": str(uuid4())}},
        )

        assert _nudges(result["messages"]) == [], "a thorough run must not be nudged"
        assert result["messages"][-1].content == "Done."

    async def test_stopping_with_no_real_work_is_nudged(self):
        """A plain-text stop with NO completed tool call is the 'assert a
        conclusion from thin air' failure. One successful call is deliberately
        NOT nudged anymore: for a one-call task the old floor's "do it now"
        goaded a duplicate send."""
        # The model quits immediately; after the nudge it works and finishes.
        c2 = {"name": "lookup", "args": {"query": "y"}, "id": "c2", "type": "tool_call"}
        c3 = {"name": "lookup", "args": {"query": "z"}, "id": "c3", "type": "tool_call"}
        llm = create_fake_llm_with_tool_calls(["All set.", c2, c3, "Done thoroughly."])
        graph = _compile(llm, require_finish_to_end=True)

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="dig into x")]},
            config={"configurable": {"thread_id": str(uuid4())}},
        )

        assert len(_nudges(result["messages"])) == MAX_COMPLETION_NUDGES
        assert result["messages"][-1].content == "Done thoroughly."
        assert sum(1 for m in result["messages"] if isinstance(m, ToolMessage)) >= 2, (
            "after the nudge the model should have dug further"
        )

    async def test_reply_promising_future_work_is_nudged(self):
        """A stop that PROMISES more work ("hang tight") is never a valid ending:
        the run is over when the reply ends, so the loop nudges instead."""
        c1 = {"name": "lookup", "args": {"query": "mail"}, "id": "c1", "type": "tool_call"}
        c2 = {"name": "lookup", "args": {"query": "more"}, "id": "c2", "type": "tool_call"}
        llm = create_fake_llm_with_tool_calls(
            [
                c1,
                c2,
                "Got 29 messages so far, still digging for the earlier ones, hang tight.",
                "Here is everything I could get; the older range failed to fetch.",
            ]
        )
        graph = _compile(llm, require_finish_to_end=True)

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="this week's emails")]},
            config={"configurable": {"thread_id": str(uuid4())}},
        )

        assert len(_nudges(result["messages"])) == MAX_COMPLETION_NUDGES
        assert "hang tight" not in result["messages"][-1].content

    async def test_comms_style_agent_ends_on_plain_text(self):
        """require_finish_to_end=False (comms) ends on plain text even with a
        pending todo — the gate is executor-only."""
        llm = create_fake_llm(["hey, what's up?"])
        graph = _compile(llm, require_finish_to_end=False)

        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content="hi")],
                "todos": [
                    {
                        "id": "t1",
                        "content": "x",
                        "status": "pending",
                        "created_at": "2026-01-01T00:00:00",
                    }
                ],
            },
            config={"configurable": {"thread_id": str(uuid4())}},
        )

        assert _nudges(result["messages"]) == []
        assert result["messages"][-1].content == "hey, what's up?"
