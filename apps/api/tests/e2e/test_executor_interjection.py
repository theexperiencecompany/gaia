"""Work handed to an executor that is already running.

The unit tests prove the drain rule and the inbox mechanics in isolation. This
proves the thing they cannot: that a message appended to the inbox WHILE a real
compiled executor graph is mid-run reaches its next reasoning step, and survives
into the thread afterwards.

The survival assertion is the point. A pre-model hook's return is handed to the
model and then discarded, so a channel built on the hook alone passes "the model
saw it" and fails "the executor still knows it" — which is the difference between
a working feature and one that silently forgets the user five seconds later.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import fakeredis.aioredis
from langchain_core.messages import HumanMessage
import pytest

from app.agents.core.background import executor_channel as channel
from app.agents.core.background.executor_channel import ExecutorInbox
from app.constants.executor import INBOX_ENTRY_ID
from app.constants.general import EXECUTOR_THREAD_PREFIX
from tests.e2e._harness.graph_run import AGENT_NODE, call, executor_graph, scripted_model_of

pytestmark = pytest.mark.e2e

CONVERSATION = "conv-interjection"
INTERJECTION = "also check the spam folder"


def plan(*contents: str) -> dict[str, Any]:
    return call("plan_tasks", {"tasks": [{"content": c} for c in contents]}, "p1")


def _executor_config() -> dict[str, Any]:
    """The shape a REAL executor run carries.

    ``thread_id`` is the WRAPPED thread (``executor_<conversation>``) and the
    conversation is a separate key. Passing the bare conversation id as
    ``thread_id`` — as this test first did — hides a whole class of bug: the
    drain keyed on the wrong id builds ``executor:inbox:executor_<conv>``, never
    matches what ``call_executor`` wrote, and nothing fails except the feature.
    """
    return {
        "configurable": {
            "thread_id": f"{EXECUTOR_THREAD_PREFIX}{CONVERSATION}",
            "conversation_id": CONVERSATION,
            "user_id": "u-1",
        },
        "metadata": {"user_id": "u-1"},
        "recursion_limit": 25,
    }


@pytest.fixture
async def inbox():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(channel, "redis_cache") as cache:
        cache.client = client
        yield ExecutorInbox(CONVERSATION)
    await client.aclose()


async def _run_and_interject(graph: Any, inbox: ExecutorInbox, prompt: str) -> dict[str, Any]:
    """Drive one turn, handing work over after the executor's first step.

    Appending between supersteps is what production does — ``call_executor``
    writes to the inbox from another task while the graph is mid-astream.
    """
    config = _executor_config()
    handed_over = False
    async for _mode, payload in graph.astream(
        {"messages": [HumanMessage(content=prompt)], "todos": []},
        stream_mode=["updates"],
        config=config,
    ):
        if not handed_over and AGENT_NODE in payload:
            await inbox.append("task-2", INTERJECTION)
            handed_over = True
    return config


class TestMidRunInterjection:
    async def test_the_executor_sees_it_on_its_next_reasoning_step(self, inbox) -> None:
        async with executor_graph([plan("search email"), "done"]) as graph:
            await _run_and_interject(graph, inbox, "find my flight email")
            calls = scripted_model_of(graph).chat_messages_log

        assert len(calls) >= 2, "need a second model call for the interjection to land on"
        first = "".join(str(m.content) for m in calls[0])
        second = "".join(str(m.content) for m in calls[1])
        assert INTERJECTION not in first, "handed over after step one, so step one cannot see it"
        assert INTERJECTION in second

    async def test_it_survives_into_the_thread(self, inbox) -> None:
        """Not just shown to one model call — committed, so the run still knows
        it when it comes to answer."""
        async with executor_graph([plan("search email"), "done"]) as graph:
            config = await _run_and_interject(graph, inbox, "find my flight email")
            state = await graph.aget_state(config)

        stamped = [
            message
            for message in state.values["messages"]
            if getattr(message, "additional_kwargs", None)
            and message.additional_kwargs.get(INBOX_ENTRY_ID) == "task-2"
        ]
        assert len(stamped) == 1
        assert INTERJECTION in str(stamped[0].content)

    async def test_it_is_not_injected_twice(self, inbox) -> None:
        """Three model calls, one hand-over: the entry must appear once, or the
        executor reads the same request again on every later step."""
        async with executor_graph([plan("search email"), plan("search spam"), "done"]) as graph:
            await _run_and_interject(graph, inbox, "find my flight email")
            calls = scripted_model_of(graph).chat_messages_log

        last = calls[-1]
        occurrences = sum(str(m.content).count(INTERJECTION) for m in last)
        assert occurrences == 1

    async def test_the_entry_is_retired_once_the_thread_holds_it(self, inbox) -> None:
        async with executor_graph([plan("search email"), plan("search spam"), "done"]) as graph:
            await _run_and_interject(graph, inbox, "find my flight email")

        assert await inbox.read() == []

    async def test_an_idle_inbox_changes_nothing(self, inbox) -> None:
        """The hook runs before every executor model call, so it must be inert
        when there is nothing to deliver."""
        async with executor_graph([plan("search email"), "done"]) as graph:
            config = _executor_config()
            async for _ in graph.astream(
                {"messages": [HumanMessage(content="find my flight email")], "todos": []},
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
