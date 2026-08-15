from langchain_core.messages import AnyMessage, BaseMessage

from app.agents.llm.client import ainvoke_llm, get_helper_llm
from app.agents.llm.exceptions import CHATBOT_OPERATIONAL_EXCEPTIONS
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


async def chatbot(messages: list[AnyMessage]) -> dict[str, list[BaseMessage]]:
    """One-shot LLM call over a message list (no graph, no checkpointer), used for
    simple helper tasks like description generation. Always runs on the default
    model — one-shot helpers never use the pro model. Operational failures are
    logged and re-raised; callers own how they degrade, not this helper."""
    try:
        response = await ainvoke_llm(get_helper_llm(), messages, label="chatbot")
    except CHATBOT_OPERATIONAL_EXCEPTIONS as e:
        log.error(
            f"{LogTag.AGENT} chatbot LLM call failed", error_type=type(e).__name__, error=str(e)
        )
        raise
    return {"messages": [response]}
