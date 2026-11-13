"""Harness-owned completion: the executor cannot silently quit early."""

from __future__ import annotations

from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
import pytest

from app.constants.agents import (
    MAX_PLAYBOOK_DECISION_NUDGES,
    PLAYBOOK_CHECK_TAG,
    PLAYBOOK_DECISION_NUDGE_MESSAGE,
)
from app.constants.llm import COMPLETION_NUDGE_MESSAGE, MAX_COMPLETION_NUDGES
from app.override.langgraph_bigtool.create_agent import (
    AgentConfig,
    HookConfig,
    ToolRetrievalConfig,
    create_agent,
)
from tests.helpers import create_fake_llm, create_fake_llm_with_tool_calls


@tool
def lookup(query: str) -> str:
    """Look up a value."""
    return f"result for {query}"


def _compile(llm, *, require_finish_to_end: bool):
    builder = create_agent(
        llm=llm,
        tool_registry={"lookup": lookup},
        tools_config=ToolRetrievalConfig(
            disable_retrieve_tools=True,
            initial_tool_ids=["lookup"],
        ),
        hooks_config=HookConfig(require_finish_to_end=require_finish_to_end),
        agent_config=AgentConfig(agent_name="executor_agent"),
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
        """Real completed tool work with no pending todos ends normally, no nudge tax."""
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
        """A plain-text stop with no completed tool call must be nudged, not accepted verbatim."""
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
        """A stop that promises more work ("hang tight") is never a valid ending."""
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
        """require_finish_to_end=False (comms) ends on plain text even with a pending todo."""
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


@tool
def decline_playbook(reason: str) -> dict:
    """Decline to freeze this run as a playbook."""
    return {"success": True, "data": {"declined": True, "reason": reason}}


def _compile_with_playbook_tools(llm):
    builder = create_agent(
        llm=llm,
        tool_registry={"lookup": lookup, "decline_playbook": decline_playbook},
        tools_config=ToolRetrievalConfig(
            disable_retrieve_tools=True,
            initial_tool_ids=["lookup", "decline_playbook"],
        ),
        hooks_config=HookConfig(require_finish_to_end=True),
        agent_config=AgentConfig(agent_name="executor_agent"),
    )
    return builder.compile(checkpointer=MemorySaver(), store=InMemoryStore())


def _decision_nudges(messages) -> list:
    return [
        m
        for m in messages
        if isinstance(m, HumanMessage) and m.content == PLAYBOOK_DECISION_NUDGE_MESSAGE
    ]


@pytest.mark.integration
class TestHarnessPlaybookDecision:
    """A workflow run whose brief asks for a playbook decision cannot end in plain text without one.

    Seen live in 2 of 6 heal runs on the PR branch.
    """

    async def test_a_plain_text_stop_without_a_decision_is_nudged_until_it_decides(self):
        c1 = {"name": "lookup", "args": {"query": "inbox"}, "id": "c1", "type": "tool_call"}
        d1 = {
            "name": "decline_playbook",
            "args": {"reason": "order varies"},
            "id": "d1",
            "type": "tool_call",
        }
        llm = create_fake_llm_with_tool_calls([c1, "Triaged 3 emails.", d1, "Triaged 3 emails."])
        graph = _compile_with_playbook_tools(llm)

        result = await graph.ainvoke(
            {
                "messages": [
                    HumanMessage(content=f"triage\n\n{PLAYBOOK_CHECK_TAG}\n</playbook_check>")
                ]
            },
            config={"configurable": {"thread_id": str(uuid4())}},
        )

        assert len(_decision_nudges(result["messages"])) == 1
        assert [m.name for m in result["messages"] if isinstance(m, ToolMessage)] == [
            "lookup",
            "decline_playbook",
        ]
        assert result["messages"][-1].content == "Triaged 3 emails."

    async def test_the_decision_nudge_is_bounded(self):
        c1 = {"name": "lookup", "args": {"query": "inbox"}, "id": "c1", "type": "tool_call"}
        llm = create_fake_llm_with_tool_calls([c1, "Done.", "Still done.", "Really done."])
        graph = _compile_with_playbook_tools(llm)

        result = await graph.ainvoke(
            {
                "messages": [
                    HumanMessage(content=f"triage\n\n{PLAYBOOK_CHECK_TAG}\n</playbook_check>")
                ]
            },
            config={"configurable": {"thread_id": str(uuid4())}},
        )

        assert len(_decision_nudges(result["messages"])) == MAX_PLAYBOOK_DECISION_NUDGES
        assert result["messages"][-1].content == "Still done."

    async def test_a_run_that_was_not_asked_is_not_nudged_for_a_decision(self):
        c1 = {"name": "lookup", "args": {"query": "inbox"}, "id": "c1", "type": "tool_call"}
        llm = create_fake_llm_with_tool_calls([c1, "Triaged 3 emails."])
        graph = _compile_with_playbook_tools(llm)

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="triage")]},
            config={"configurable": {"thread_id": str(uuid4())}},
        )

        assert _decision_nudges(result["messages"]) == []
        assert result["messages"][-1].content == "Triaged 3 emails."
