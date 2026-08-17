from langchain_core.messages import AIMessage, AnyMessage, BaseMessage

from app.agents.llm.client import ainvoke_llm, get_default_llm
from app.agents.llm.exceptions import CHATBOT_FALLBACK_EXCEPTIONS
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


async def chatbot(messages: list[AnyMessage]) -> dict[str, list[BaseMessage]]:
    """One-shot LLM call over a message list (no graph, no checkpointer), used for
    simple helper tasks like description generation. Always runs on the default
    model — one-shot helpers never use the pro model. Degrades to a friendly
    message rather than raising, so a helper failure never breaks its caller."""
    try:
        response = await ainvoke_llm(get_default_llm(), messages, label="chatbot")
        return {"messages": [response]}
    except CHATBOT_FALLBACK_EXCEPTIONS as e:
        log.error(
            f"{LogTag.AGENT} chatbot LLM call failed", error_type=type(e).__name__, error=str(e)
        )
        return {
            "messages": [
                AIMessage(
                    content="I'm having trouble processing your request. Please try again later."
                )
            ]
        }
