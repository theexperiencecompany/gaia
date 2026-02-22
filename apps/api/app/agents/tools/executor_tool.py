"""Executor tool for comms agent to delegate tasks to executor agent."""

import asyncio
from datetime import datetime
from typing import Annotated

from app.agents.core.subagents.subagent_runner import (
    execute_subagent_stream,
    prepare_executor_execution,
)
from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import llm_logger as logger
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
        user_id = configurable.get("user_id")
        stream_id = configurable.get("stream_id")  # Extract stream_id for cancellation

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

        # Parse user time
        user_time_str = configurable.get("user_time", "")
        user_time = (
            datetime.fromisoformat(user_time_str) if user_time_str else datetime.now()
        )

        # Prepare execution context using shared function
        ctx, error = await prepare_executor_execution(
            task=task,
            configurable=configurable,
            user_time=user_time,
            stream_id=stream_id,
        )

        if error or ctx is None:
            logger.error(error or "Failed to prepare executor execution")
            return f"Error: {error or 'Executor agent not available'}"

        # Execute with streaming using shared function
        writer = get_stream_writer()
        return await execute_subagent_stream(
            ctx=ctx,
            stream_writer=writer,
        )

    except asyncio.CancelledError:
        logger.info("Executor call cancelled")
        return "Task was cancelled"
    except Exception as e:
        logger.error("Error calling executor: {}", str(e), exc_info=True)
        return f"Error executing task: {str(e)}"


tools = [call_executor]
