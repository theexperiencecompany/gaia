"""Pre-model hook that strips inline media from history for non-vision lanes.

Inline media blocks enter ToolMessages on vision-capable lanes (the `read`
tool, MCP tools). When the same thread later runs on a non-vision lane — plan
change, dev model override — forwarding those blocks would make the provider
reject the request. This node swaps them for a text notice; on vision-capable
lanes it is a no-op.
"""

from typing import TypeVar

from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState
from langgraph.store.base import BaseStore

from app.agents.llm.vision import strip_media_blocks_for_non_vision

T = TypeVar("T", bound=MessagesState)


def sanitize_media_node(state: T, config: RunnableConfig, store: BaseStore) -> T:
    messages = state["messages"]
    sanitized = strip_media_blocks_for_non_vision(messages, config)
    if all(new is old for new, old in zip(sanitized, messages)):
        return state
    return {**state, "messages": sanitized}  # type: ignore[return-value]
