from app.agents.core.state import State
from app.agents.llm.client import init_llm
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
        use_free_llm: Whether to use the free LLM (Gemini 2.0 Flash via OpenRouter).
                      Defaults to True for cost efficiency on simple tasks like
                      description generation.
    """
    try:
        llm = init_llm(use_free=use_free_llm)

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
