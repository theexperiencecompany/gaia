"""Regression: every OpenAI call must begin with the previous call on its thread, byte for byte.

OpenAI reuses an earlier request only whole (docs/llm-cache-measurements.md), so
the request on an OpenAI lane has to be an append-only log. Production read 30%
cached on gpt-5.6-luna because the per-turn slots (memory recall, the clock, the
hook status frames) led the conversation and were swapped every turn, moving the
cache boundary to just after the static prompt and re-billing the whole history.

These drive the real node across turns and model calls, committing what the model
node commits, and assert the prefix property itself rather than a slot order.
"""

from typing import Any, cast
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import add_messages
import pytest

from app.agents.context.slots import (
    DYNAMIC_CONTEXT_MARKER,
    EXECUTOR_STATUS_MARKER,
    MEMORY_RECALL_MARKER,
    TIME_CONTEXT_MARKER,
    TODO_CONTEXT_MARKER,
)
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.constants.llm import LLMProviderName
from app.override.langgraph_bigtool.utils import (
    State,
    pop_injected_messages,
    pop_pruned_tombstones,
)
from tests._harness.context_chain import bound_for

WireMessage = tuple[str, str]


def _config(provider: LLMProviderName) -> RunnableConfig:
    return cast(
        RunnableConfig,
        {"configurable": {"user_id": "u1", "thread_id": "t1", **bound_for(provider)}},
    )


def _turn(n: int) -> list[AnyMessage]:
    """Return what construct_langchain_messages writes into the thread at the start of turn n."""
    return [
        SystemMessage(content="static prompt"),
        SystemMessage(content="stable context", additional_kwargs={DYNAMIC_CONTEXT_MARKER: True}),
        SystemMessage(content=f"recall {n}", additional_kwargs={MEMORY_RECALL_MARKER: True}),
        HumanMessage(content=f"question {n}"),
        HumanMessage(content=f"clock {n}", additional_kwargs={TIME_CONTEXT_MARKER: True}),
    ]


def _frame(marker: str, text: str) -> SystemMessage:
    """Return a per-call status frame exactly as a pre-model hook appends it: never checkpointed."""
    return SystemMessage(content=text, additional_kwargs={marker: True})


def _wire(messages: list[AnyMessage]) -> list[WireMessage]:
    return [(m.type, str(m.content)) for m in messages]


class _Thread:
    """A checkpointed thread driven through the node the way the model node drives it."""

    def __init__(self, provider: LLMProviderName = LLMProviderName.OPENAI) -> None:
        self.checkpoint: list[AnyMessage] = []
        self.config = _config(provider)

    def write(self, messages: list[AnyMessage]) -> None:
        self.checkpoint = cast(list[AnyMessage], add_messages(self.checkpoint, messages))

    def call(self, *frames: AnyMessage, reply: AIMessage | None = None) -> list[AnyMessage]:
        """Run one model call and commit what the model node would; return the request."""
        state = cast(State, {"messages": [*self.checkpoint, *frames]})
        result = cast(dict[str, Any], manage_system_prompts_node(state, self.config, MagicMock()))
        request = list(result["messages"])
        writes: list[AnyMessage] = [
            *pop_pruned_tombstones(cast(State, result)),
            *pop_injected_messages(cast(State, result)),
            reply or AIMessage(content=f"reply {len(self.checkpoint)}"),
        ]
        self.write(writes)
        return request


@pytest.mark.unit
class TestOpenAIRequestIsAppendOnly:
    def test_the_next_turn_begins_with_the_whole_previous_request(self) -> None:
        thread = _Thread()
        thread.write(_turn(1))
        first = thread.call(reply=AIMessage(content="answer 1"))
        thread.write(_turn(2))
        second = thread.call()

        assert _wire(second)[: len(first) + 1] == [*_wire(first), ("ai", "answer 1")]

    def test_every_turn_keeps_its_own_recall_and_clock_where_it_happened(self) -> None:
        thread = _Thread()
        for n in (1, 2, 3):
            thread.write(_turn(n))
            request = thread.call(reply=AIMessage(content=f"answer {n}"))

        assert _wire(request) == [
            ("system", "static prompt"),
            ("system", "stable context"),
            ("system", "recall 1"),
            ("human", "question 1"),
            ("human", "clock 1"),
            ("ai", "answer 1"),
            ("system", "recall 2"),
            ("human", "question 2"),
            ("human", "clock 2"),
            ("ai", "answer 2"),
            ("system", "recall 3"),
            ("human", "question 3"),
            ("human", "clock 3"),
        ]

    def test_a_status_frame_is_committed_once_and_extends_the_request_when_it_changes(
        self,
    ) -> None:
        thread = _Thread()
        thread.write(_turn(1))
        tool_call = AIMessage(
            content="", tool_calls=[{"id": "c1", "name": "write_todos", "args": {}}]
        )
        first = thread.call(_frame(TODO_CONTEXT_MARKER, "todos v1"), reply=tool_call)
        thread.write([ToolMessage(content="ok", tool_call_id="c1")])
        unchanged = thread.call(_frame(TODO_CONTEXT_MARKER, "todos v1"), reply=tool_call)
        thread.write([ToolMessage(content="ok", tool_call_id="c1")])
        changed = thread.call(_frame(TODO_CONTEXT_MARKER, "todos v2"))

        assert _wire(unchanged)[: len(first)] == _wire(first)
        assert _wire(changed)[: len(unchanged)] == _wire(unchanged)
        assert [text for kind, text in _wire(changed) if text.startswith("todos")] == [
            "todos v1",
            "todos v2",
        ]
        assert _wire(changed)[-1] == ("system", "todos v2")

    def test_a_frame_that_matches_the_committed_one_is_not_sent_twice(self) -> None:
        thread = _Thread()
        thread.write(_turn(1))
        thread.call(_frame(EXECUTOR_STATUS_MARKER, "idle"), reply=AIMessage(content="a1"))
        thread.write(_turn(2))
        request = thread.call(_frame(EXECUTOR_STATUS_MARKER, "idle"))

        assert [text for _, text in _wire(request)].count("idle") == 1

    def test_stale_leading_copies_are_pruned_from_the_thread(self) -> None:
        thread = _Thread()
        for n in (1, 2):
            thread.write(_turn(n))
            thread.call()

        static_copies = [m for m in thread.checkpoint if m.content == "static prompt"]
        assert len(static_copies) == 1


@pytest.mark.unit
class TestOtherProvidersKeepTheirSlotLayout:
    def test_openrouter_still_sends_one_recall_behind_the_conversation(self) -> None:
        thread = _Thread(LLMProviderName.OPENROUTER)
        for n in (1, 2):
            thread.write(_turn(n))
            request = thread.call(_frame(TODO_CONTEXT_MARKER, f"todos {n}"))

        texts = [text for _, text in _wire(request)]
        assert texts.count("recall 2") == 1
        assert "recall 1" not in texts
        assert "todos 1" not in texts
