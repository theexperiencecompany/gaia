"""Integration test: summarization must not poison the model's message list.

Drives the real compiled ``create_agent`` graph — real ``acall_model``, real
``MiddlewareExecutor``, real ``SummarizationMiddleware`` — and validates the
message list the agent node hands the model with the actual provider serializer
that rejected it in production.

Regression for the executor-endpoint 500s: ``SummarizationMiddleware`` clears
history by returning ``{"messages": [RemoveMessage(REMOVE_ALL_MESSAGES), ...]}``,
a LangGraph state update. The executor merged it with ``dict.update``, so the
tombstone reached the model and
``langchain_google_genai._parse_chat_history`` raised
"Unexpected message with type RemoveMessage at the position 0."

Not exercised here: the network call to Gemini. ``_parse_chat_history`` runs
inside ``_prepare_request`` before any HTTP, so it is the real code that raised —
but nothing past request serialization is covered.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage
from langchain_core.outputs import ChatResult
from langchain_google_genai.chat_models import _parse_chat_history
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import Field
import pytest

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
    tombstone and prove nothing. Running the real ``_parse_chat_history`` makes
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
    """The real bigtool graph with only the summarization middleware attached."""
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
