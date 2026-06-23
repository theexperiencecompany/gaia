from langchain_core.messages import AnyMessage, RemoveMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState
from langgraph.store.base import BaseStore

from app.constants.llm import MAX_CONTEXT_MESSAGES
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


def trim_messages_node(state: MessagesState, config: RunnableConfig, store: BaseStore) -> dict:
    messages: list[AnyMessage] = state["messages"]
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    if len(non_system) <= MAX_CONTEXT_MESSAGES:
        return {}

    to_remove = non_system[: len(non_system) - MAX_CONTEXT_MESSAGES]
    log.info(
        f"{LogTag.AGENT} trim_messages: removing {len(to_remove)} oldest messages "
        f"(keeping {MAX_CONTEXT_MESSAGES} of {len(non_system)} non-system)"
    )
    return {"messages": [RemoveMessage(id=m.id) for m in to_remove]}
