from langchain_core.messages import AIMessage, AnyMessage, BaseMessage

from app.agents.llm.client import get_free_llm_chain, init_llm, invoke_with_fallback
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


async def chatbot(
    messages: list[AnyMessage],
    use_free_llm: bool = True,
) -> dict[str, list[BaseMessage]]:
    """
    One-shot LLM call over a message list (no graph, no checkpointer).

    Args:
        messages: The conversation messages to send to the model.
        use_free_llm: Whether to use the free LLM with fallback support.
                      Defaults to True for cost efficiency on simple tasks like
                      description generation.
    """
    try:
        if use_free_llm:
            llm_chain = get_free_llm_chain()
            response = await invoke_with_fallback(llm_chain, messages)
        else:
            llm = init_llm()
            response = await llm.ainvoke(messages)

        return {"messages": [response]}
    except Exception as e:
        log.error(f"{LogTag.AGENT} Error in LLM API call: {e!s}")

        return {
            "messages": [
                AIMessage(
                    content="I'm having trouble processing your request. Please try again later."
                )
            ]
        }
