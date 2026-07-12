"""Pre-model hook that fits inline media in history to the active model lane.

Media blocks enter ToolMessages on any lane whose model can view images (the
`read` tool, MCP tools). Per model call this node repacks them into a user
message for lanes that can't take images in tool results (OpenRouter
multimodal models) and strips them to a notice for text-only lanes. Hook
output feeds the model request only — persisted history keeps the canonical
block shape.
"""

from typing import TypeVar

from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState
from langgraph.store.base import BaseStore

from app.agents.llm.vision import adapt_media_blocks_for_model

T = TypeVar("T", bound=MessagesState)


async def adapt_media_node(state: T, config: RunnableConfig, store: BaseStore) -> T:
    messages = state["messages"]
    adapted = await adapt_media_blocks_for_model(messages, config)
    if len(adapted) == len(messages) and all(new is old for new, old in zip(adapted, messages)):
        return state
    return {**state, "messages": adapted}  # type: ignore[return-value]
