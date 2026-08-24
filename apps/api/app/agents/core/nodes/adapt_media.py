"""Pre-model hook that fits the inline media in history to the active model lane.

Media enters ToolMessages on any lane whose tools can produce it (the `read`
tool, MCP tools). Per model call this node rewrites those messages into what the
lane can actually receive — see `app/agents/llm/vision/`. Hook output feeds the
model request only; persisted history keeps the canonical block shape.
"""

from typing import TypeVar, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState
from langgraph.store.base import BaseStore

from app.agents.llm.vision import adapt_media_for_model

T = TypeVar("T", bound=MessagesState)


async def adapt_media_node(
    state: T,
    config: RunnableConfig,
    # Unused here, but execute_hooks() calls every pre-model hook as
    # (state, config, store) — the 3-arg signature is mandatory, so dropping
    # this would be a runtime TypeError, not a cleanup.
    store: BaseStore,  # NOSONAR python:S1172  # noqa: ARG001 -- framework contract
) -> T:
    messages = state["messages"]
    adapted = await adapt_media_for_model(messages, config)
    if len(adapted) == len(messages) and all(new is old for new, old in zip(adapted, messages)):
        return state
    return cast(T, {**state, "messages": adapted})
