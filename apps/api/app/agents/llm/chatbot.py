from app.agents.core.state import State
from app.agents.llm.client import get_free_llm_chain, init_llm, invoke_with_fallback
from app.config.loggers import chat_logger as logger
from langchain_core.messages import AIMessage


async def chatbot(
    state: State,
    use_free_llm: bool = True,
):
    """
    Chatbot function that uses the state graph and model.

    Args:
        state: The conversation state containing messages
        use_free_llm: Whether to use the free LLM with fallback support.
                      Defaults to True for cost efficiency on simple tasks like
                      description generation.
    """
    try:
        if use_free_llm:
            llm_chain = get_free_llm_chain()
            response = await invoke_with_fallback(llm_chain, state.messages)
        else:
            llm = init_llm(use_free=False)
            response = await llm.ainvoke(state.messages)

        return {"messages": [response]}
    except Exception as e:
        logger.error(f"Error in LLM API call: {str(e)}")

        return {
            "messages": [
                AIMessage(
                    content="I'm having trouble processing your request. Please try again later."
                )
            ]
        }
