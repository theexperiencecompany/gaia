"""Executor tool for comms agent to delegate tasks to executor agent."""

from datetime import datetime
from typing import Annotated

from app.agents.core.graph_manager import GraphManager
from app.agents.core.subagents.subagent_helpers import create_agent_context_message
from app.config.loggers import llm_logger as logger
from app.helpers.agent_helpers import build_agent_config
from app.helpers.message_helpers import create_system_message
from app.utils.chat_utils import get_user_id_from_config, get_user_name_from_config
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer


@tool
async def call_executor(
    config: RunnableConfig,
    task: Annotated[str, "The task to execute - describe what needs to be done"],
) -> str:
    """
    Delegate a task to the executor agent for execution.

    Use this when the user asks you to do something that requires action
    (creating todos, checking calendar, sending emails, searching, etc.)
    or when you need context from your capabilities.

    The executor has access to all tools and integrations.
    """
    try:
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        executor_thread_id = f"executor_{thread_id}"

        executor_graph = await GraphManager.get_graph("executor_agent")
        if not executor_graph:
            return "Error: Executor agent not available"

        user = {
            "user_id": configurable.get("user_id"),
            "email": configurable.get("email"),
            "name": configurable.get("user_name"),
        }
        user_time_str = configurable.get("user_time", "")
        user_time = (
            datetime.fromisoformat(user_time_str) if user_time_str else datetime.now()
        )

        executor_config = build_agent_config(
            conversation_id=thread_id,
            user=user,
            user_time=user_time,
            thread_id=executor_thread_id,
            base_configurable=configurable,
            agent_name="executor_agent",
        )

        system_message = create_system_message(
            user_id=get_user_id_from_config(config),
            agent_type="executor",
            user_name=get_user_name_from_config(config),
        )

        context_message = await create_agent_context_message(
            agent_name="executor_agent",
            configurable=configurable,
            query=task,
            thread_id=thread_id,  # Use thread_id for acontext session consistency
        )

        initial_state = {
            "messages": [
                system_message,
                context_message,
                HumanMessage(content=task),
            ]
        }

        complete_message = ""
        writer = get_stream_writer()

        async for event in executor_graph.astream(
            initial_state,
            stream_mode=["messages", "custom"],
            config=executor_config,
        ):
            stream_mode, payload = event

            if stream_mode == "custom":
                writer(payload)
            elif stream_mode == "messages":
                chunk, metadata = payload

                if metadata.get("silent"):
                    continue

                if (
                    chunk
                    and isinstance(chunk, AIMessageChunk)
                    and metadata.get("agent_name") == "executor_agent"
                ):
                    content = str(chunk.content)
                    if content:
                        complete_message += content

        return complete_message if complete_message else "Task completed"

    except Exception as e:
        logger.error(f"Error calling executor: {e}")
        return f"Error executing task: {str(e)}"


tools = [call_executor]
