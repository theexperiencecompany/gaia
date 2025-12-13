from app.config.loggers import chat_logger as logger
from app.agents.core.state import State
from app.agents.llm.client import init_llm
from langchain_core.messages import AIMessage


async def chatbot(
    state: State,
):
    """Chatbot function that uses the state graph and model."""
    try:
        llm = init_llm()

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
