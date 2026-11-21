"""Regression: every agent call begins with the previous call on its thread, byte for byte.

Provider prompt caches reuse an earlier request's prefix (OpenAI only a whole
earlier request), so the request is the thread, append-only. Production read 30%
cached on gpt-5.6-luna because the per-turn recall and clock led the conversation
and were swapped every turn, moving the cache boundary to the static prompt and
re-billing the whole history on every new turn.

These drive the real node across turns, committing what the model node commits,
and assert the prefix property itself rather than a slot order. The layout no
longer depends on the provider, so every lane is exercised.
"""

from collections.abc import Sequence
from typing import Any, cast
from unittest.mock import MagicMock

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    MessageLikeRepresentation,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import add_messages
import pytest

from app.agents.context.slots import (
    DYNAMIC_CONTEXT_MARKER,
    MEMORY_RECALL_MARKER,
    TIME_CONTEXT_MARKER,
)
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.constants.llm import LLMProviderName
from app.override.langgraph_bigtool.utils import State, pop_pruned_tombstones
from tests._harness.context_chain import bound_for

WireMessage = tuple[str, str]

PROVIDERS = [
    LLMProviderName.OPENAI,
    LLMProviderName.OPENROUTER,
    LLMProviderName.GEMINI,
    None,
]


def _config(provider: LLMProviderName | None) -> RunnableConfig:
    lane = bound_for(provider) if provider is not None else {}
    return cast(RunnableConfig, {"configurable": {"user_id": "u1", "thread_id": "t1", **lane}})


def _turn(n: int, *, stable: str = "stable context") -> list[AnyMessage]:
    """Return what comms_turn_messages writes into the thread at the start of turn n."""
    return [
        SystemMessage(content="static prompt"),
        SystemMessage(content=stable, additional_kwargs={DYNAMIC_CONTEXT_MARKER: True}),
        SystemMessage(content=f"recall {n}", additional_kwargs={MEMORY_RECALL_MARKER: True}),
        HumanMessage(content=f"question {n}"),
        HumanMessage(content=f"clock {n}", additional_kwargs={TIME_CONTEXT_MARKER: True}),
    ]


def _wire(messages: list[AnyMessage]) -> list[WireMessage]:
    return [(m.type, str(m.content)) for m in messages]


class _Thread:
    """A checkpointed thread driven through the node the way the model node drives it."""

    def __init__(self, provider: LLMProviderName | None) -> None:
        self.checkpoint: list[AnyMessage] = []
        self.config = _config(provider)

    def write(self, messages: Sequence[MessageLikeRepresentation]) -> None:
        merged = add_messages(
            list[MessageLikeRepresentation](self.checkpoint),
            list[MessageLikeRepresentation](messages),
        )
        # add_messages coerces every entry to a BaseMessage and returns the merged list.
        self.checkpoint = cast(list[AnyMessage], merged)

    def call(self, reply: AIMessage) -> list[AnyMessage]:
        """Run one model call, commit its tombstones and reply; return the request it sent."""
        state = cast(State, {"messages": list(self.checkpoint)})
        result = cast(dict[str, Any], manage_system_prompts_node(state, self.config, MagicMock()))
        self.write([*pop_pruned_tombstones(cast(State, result)), reply])
        return list(result["messages"])


@pytest.mark.unit
@pytest.mark.parametrize("provider", PROVIDERS)
class TestTheRequestIsAppendOnly:
    def test_the_next_turn_begins_with_the_whole_previous_request(
        self, provider: LLMProviderName | None
    ) -> None:
        thread = _Thread(provider)
        thread.write(_turn(1))
        first = thread.call(AIMessage(content="answer 1"))
        thread.write(_turn(2))
        second = thread.call(AIMessage(content="answer 2"))

        assert _wire(second)[: len(first) + 1] == [*_wire(first), ("ai", "answer 1")]

    def test_every_turn_keeps_its_own_recall_and_clock_where_it_happened(
        self, provider: LLMProviderName | None
    ) -> None:
        thread = _Thread(provider)
        for n in (1, 2, 3):
            thread.write(_turn(n))
            request = thread.call(AIMessage(content=f"answer {n}"))

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

    def test_stale_leading_copies_are_pruned_from_the_thread(
        self, provider: LLMProviderName | None
    ) -> None:
        thread = _Thread(provider)
        for n in (1, 2):
            thread.write(_turn(n))
            thread.call(AIMessage(content=f"answer {n}"))

        assert [m.content for m in thread.checkpoint].count("static prompt") == 1
        assert [m.content for m in thread.checkpoint].count("stable context") == 1

    def test_an_edited_setting_leads_with_its_latest_copy(
        self, provider: LLMProviderName | None
    ) -> None:
        thread = _Thread(provider)
        thread.write(_turn(1))
        thread.call(AIMessage(content="answer 1"))
        thread.write(_turn(2, stable="stable context, edited"))
        request = thread.call(AIMessage(content="answer 2"))

        assert _wire(request)[:2] == [
            ("system", "static prompt"),
            ("system", "stable context, edited"),
        ]
        assert "stable context" not in [text for _, text in _wire(request)]
