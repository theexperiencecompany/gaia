"""Integration test: summarization must not poison the model's message list.

Drives the real compiled create_agent graph -- real acall_model, real MiddlewareExecutor, real
SummarizationMiddleware -- and validates the message list the agent node hands the model with the
actual provider serializer that rejected it in production.

Regression for the executor-endpoint 500s: SummarizationMiddleware clears history by returning
{"messages": [RemoveMessage(REMOVE_ALL_MESSAGES), ...]}, a LangGraph state update. The executor
merged it with dict.update, so the tombstone reached the model and
langchain_google_genai._parse_chat_history raised "Unexpected message with type RemoveMessage at
the position 0."

Not exercised: the network call to Gemini. _parse_chat_history runs inside _prepare_request before
any HTTP, so it is the real code that raised, but nothing past request serialization is covered.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatResult
from langchain_google_genai.chat_models import _parse_chat_history
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import Field
import pytest

from app.agents.context.slots import (
    DYNAMIC_CONTEXT_MARKER,
    TIME_CONTEXT_MARKER,
    has_marker,
    mark,
)
from app.agents.middleware.summarization import WorkspaceArchivingSummarizationMiddleware
from app.config.settings import settings
from app.override.langgraph_bigtool.create_agent import (
    AgentConfig,
    ToolRetrievalConfig,
    create_agent,
)
from tests.helpers import BindableToolsFakeModel

# Fires summarization on the very first model call for a history this size.
SUMMARIZATION_TRIGGER_MESSAGES = 6
SUMMARIZATION_KEEP_MESSAGES = 2
HISTORY_TURNS = 10


class ProviderValidatingFakeModel(BindableToolsFakeModel):
    """Fake model that serializes its input exactly as ChatGoogleGenerativeAI does.

    A plain fake accepts any object at all, so it would happily swallow the
    tombstone and prove nothing. Running the real _parse_chat_history makes
    this test fail on precisely the production symptom.
    """

    seen_messages: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.seen_messages.append(list(messages))
        _parse_chat_history(messages, convert_system_message_to_human=False)
        return super()._generate(messages, *args, **kwargs)


def _long_history() -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for i in range(HISTORY_TURNS):
        messages.append(HumanMessage(content=f"user turn {i}", id=f"h{i}"))
        messages.append(AIMessage(content=f"assistant turn {i}", id=f"a{i}"))
    return messages


@pytest.fixture
def summarizing_agent_graph():
    """Build the real bigtool graph with only the summarization middleware attached."""
    model = ProviderValidatingFakeModel(responses=[AIMessage(content="done")])
    summarizer = GenericFakeChatModel(messages=iter([AIMessage(content="SUMMARY")] * 50))
    middleware = [
        SummarizationMiddleware(
            model=summarizer,
            trigger=("messages", SUMMARIZATION_TRIGGER_MESSAGES),
            keep=("messages", SUMMARIZATION_KEEP_MESSAGES),
        )
    ]

    # An ambient GOOGLE_API_KEY would give create_agent a real fallback model,
    # which swallows the provider error this test exists to catch.
    with patch.object(settings, "GOOGLE_API_KEY", None):
        builder = create_agent(
            model,
            {},
            tools_config=ToolRetrievalConfig(disable_retrieve_tools=True),
            agent_config=AgentConfig(middleware=middleware),
        )
        graph = builder.compile(checkpointer=InMemorySaver(), store=InMemoryStore())
        yield graph, model


@pytest.mark.integration
@pytest.mark.asyncio
class TestSummarizationStateUpdate:
    async def test_graph_run_survives_summarization(self, summarizing_agent_graph):
        graph, model = summarizing_agent_graph

        result = await graph.ainvoke(
            {"messages": _long_history(), "selected_tool_ids": [], "todos": []},
            config={"configurable": {"thread_id": "sum-1", "user_id": "u1"}},
        )

        assert result["messages"][-1].content == "done"
        assert model.seen_messages, "the model node never ran"

    async def test_model_never_sees_a_remove_message(self, summarizing_agent_graph):
        graph, model = summarizing_agent_graph

        await graph.ainvoke(
            {"messages": _long_history(), "selected_tool_ids": [], "todos": []},
            config={"configurable": {"thread_id": "sum-2", "user_id": "u1"}},
        )

        for sent in model.seen_messages:
            assert not any(isinstance(m, RemoveMessage) for m in sent)

    async def test_model_sees_the_summarized_history_not_the_full_one(
        self, summarizing_agent_graph
    ):
        graph, model = summarizing_agent_graph

        await graph.ainvoke(
            {"messages": _long_history(), "selected_tool_ids": [], "todos": []},
            config={"configurable": {"thread_id": "sum-3", "user_id": "u1"}},
        )

        sent_ids = {m.id for m in model.seen_messages[0]}
        assert "h0" not in sent_ids, "summarized-away history was still sent to the model"
        assert len(model.seen_messages[0]) < HISTORY_TURNS * 2


class RecordingSummarizer(GenericFakeChatModel):
    """Summarizer fake that records every prompt it is asked to digest."""

    prompts: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.prompts.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


STATIC_PROMPT = "You are GAIA, the user's personal assistant."
GAIA_TRIGGER_MESSAGES = 10


def _gaia_shaped_turn(turn: int) -> list[BaseMessage]:
    """One request as construct_langchain_messages shapes it: prompt slots around the user turn."""
    return [
        SystemMessage(content=STATIC_PROMPT, id=f"static{turn}"),
        mark(SystemMessage(content="dynamic context", id=f"dyn{turn}"), DYNAMIC_CONTEXT_MARKER),
        HumanMessage(content=f"user turn {turn}", id=f"h{turn}"),
        mark(HumanMessage(content="[Current UTC Time]", id=f"time{turn}"), TIME_CONTEXT_MARKER),
    ]


def _gaia_history() -> list[BaseMessage]:
    messages = _gaia_shaped_turn(0)
    messages.append(AIMessage(content="assistant turn 0", id="a0"))
    for i in range(1, HISTORY_TURNS):
        messages.append(HumanMessage(content=f"user turn {i}", id=f"h{i}"))
        messages.append(AIMessage(content=f"assistant turn {i}", id=f"a{i}"))
    return messages


@pytest.fixture
def gaia_summarizing_graph():
    """Build the real bigtool graph with GAIA's own summarization middleware, archive off."""
    model = ProviderValidatingFakeModel(responses=[AIMessage(content="done")] * 10)
    summarizer = RecordingSummarizer(messages=iter([AIMessage(content="SUMMARY")] * 50))
    middleware = [
        WorkspaceArchivingSummarizationMiddleware(
            model=summarizer,
            # Above the post-summary thread size, so a second run only re-summarizes
            # if the first summary never reached the checkpoint.
            trigger=("messages", GAIA_TRIGGER_MESSAGES),
            keep=("messages", SUMMARIZATION_KEEP_MESSAGES),
            archive=None,
        )
    ]
    with patch.object(settings, "GOOGLE_API_KEY", None):
        builder = create_agent(
            model,
            {},
            tools_config=ToolRetrievalConfig(disable_retrieve_tools=True),
            agent_config=AgentConfig(middleware=middleware),
        )
        graph = builder.compile(checkpointer=InMemorySaver(), store=InMemoryStore())
        yield graph, model, summarizer


@pytest.mark.integration
@pytest.mark.asyncio
class TestGaiaSummarizationKeepsPromptsAndPersists:
    """Regression: GAIA's prompt slots were summarized away and the summary was never kept.

    The digest swallowed the static system prompt, so the model ran with no
    instructions and a "SESSION INTENT" block as its first message; and since
    the rewrite never reached the checkpoint, every model call re-summarized.
    """

    async def test_the_model_still_leads_with_the_system_prompt(self, gaia_summarizing_graph):
        graph, model, _ = gaia_summarizing_graph

        await graph.ainvoke(
            {"messages": _gaia_history(), "selected_tool_ids": [], "todos": []},
            config={"configurable": {"thread_id": "gaia-1", "user_id": "u1"}},
        )

        sent = model.seen_messages[0]
        assert sent[0].content == STATIC_PROMPT
        assert any(has_marker(m, DYNAMIC_CONTEXT_MARKER) for m in sent)
        assert any(has_marker(m, TIME_CONTEXT_MARKER) for m in sent)
        assert sent[-1].id == f"a{HISTORY_TURNS - 1}"

    async def test_the_summarizer_never_digests_prompt_slots(self, gaia_summarizing_graph):
        graph, _, summarizer = gaia_summarizing_graph

        await graph.ainvoke(
            {"messages": _gaia_history(), "selected_tool_ids": [], "todos": []},
            config={"configurable": {"thread_id": "gaia-2", "user_id": "u1"}},
        )

        assert len(summarizer.prompts) == 1
        digested = str(summarizer.prompts[0][-1].content)
        assert "user turn 0" in digested
        assert STATIC_PROMPT not in digested
        assert "dynamic context" not in digested
        assert "[Current UTC Time]" not in digested

    async def test_the_summary_is_checkpointed_in_place(self, gaia_summarizing_graph):
        graph, _, _ = gaia_summarizing_graph
        config = {"configurable": {"thread_id": "gaia-3", "user_id": "u1"}}

        await graph.ainvoke(
            {"messages": _gaia_history(), "selected_tool_ids": [], "todos": []}, config=config
        )

        kept = (await graph.aget_state(config)).values["messages"]
        ids = [m.id for m in kept]
        assert "a0" not in ids and "h1" not in ids, "summarized history stayed in the checkpoint"
        summary_index = next(
            i for i, m in enumerate(kept) if m.additional_kwargs.get("lc_source") == "summarization"
        )
        assert ids.index("static0") < summary_index < ids.index(f"h{HISTORY_TURNS - 1}")
        assert kept[-1].content == "done"

    async def test_the_next_turn_does_not_summarize_again(self, gaia_summarizing_graph):
        graph, _, summarizer = gaia_summarizing_graph
        config = {"configurable": {"thread_id": "gaia-4", "user_id": "u1"}}

        await graph.ainvoke(
            {"messages": _gaia_history(), "selected_tool_ids": [], "todos": []}, config=config
        )
        await graph.ainvoke({"messages": [HumanMessage(content="next", id="next")]}, config=config)

        assert len(summarizer.prompts) == 1
