"""Executor tool for comms agent to delegate tasks to executor agent."""

from datetime import datetime
from typing import Annotated

from app.agents.core.graph_manager import GraphManager
from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import llm_logger as logger
from app.helpers.agent_helpers import build_agent_config
from app.helpers.message_helpers import create_system_message
from app.utils.agent_utils import format_tool_progress
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
        user_id = configurable.get("user_id")

        # Load user's MCP tools if they have any connected
        if user_id:
            try:
                tool_registry = await get_tool_registry()
                loaded = await tool_registry.load_user_mcp_tools(user_id)
                if loaded:
                    logger.info(
                        f"Loaded MCP tools for user {user_id}: {list(loaded.keys())}"
                    )
            except Exception as e:
                logger.warning(f"Failed to load user MCP tools: {e}")

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

        initial_state = {
            "messages": [
                system_message,
                HumanMessage(
                    content=task,
                    additional_kwargs={"visible_to": {"executor_agent"}},
                ),
            ],
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
                    if chunk.tool_calls:
                        for tool_call in chunk.tool_calls:
                            progress_data = await format_tool_progress(tool_call)
                            if progress_data:
                                writer(progress_data)

                    content = str(chunk.content)
                    if content:
                        complete_message += content

        return complete_message if complete_message else "Task completed"

    except Exception as e:
        logger.error(f"Error calling executor: {e}")
        return f"Error executing task: {str(e)}"


tools = [call_executor]
