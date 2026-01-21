"""
Subagent Execution Core - Shared logic for subagent invocation.

This module contains the reusable classes and functions for invoking subagents.
Both handoff_tools.py, executor_tool.py, and direct call_subagent use these.

Keeping shared code here avoids cyclic dependencies since handoff_tools.py
imports from this file, not the other way around.

Key exports:
- SubagentExecutionContext: Container for execution data
- build_initial_messages(): Construct standard message list with context
- execute_subagent_stream(): Unified streaming with configurable tool tracking
- prepare_subagent_execution(): Prepare context for platform subagents
- prepare_executor_execution(): Prepare context for executor agent
"""

from datetime import datetime
from typing import AsyncGenerator, List, Optional

from app.agents.core.subagents.subagent_helpers import (
    create_agent_context_message,
    create_subagent_system_message,
)
from app.config.loggers import common_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.core.lazy_loader import providers
from app.helpers.agent_helpers import build_agent_config
from app.models.models_models import ModelConfig
from app.services.oauth.oauth_service import check_integration_status
from app.utils.agent_utils import format_tool_progress
from langchain_core.messages import (
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)


class SubagentExecutionContext:
    """Container for all data needed to execute a subagent."""

    def __init__(
        self,
        subagent_graph,
        agent_name: str,
        config: dict,
        configurable: dict,
        integration_id: str,
        initial_state: dict,
        user_id: Optional[str] = None,
    ):
        self.subagent_graph = subagent_graph
        self.agent_name = agent_name
        self.config = config
        self.configurable = configurable
        self.integration_id = integration_id
        self.initial_state = initial_state
        self.user_id = user_id


def get_subagent_integrations() -> List:
    """Get all integrations that have subagent configurations."""
    return [
        integration
        for integration in OAUTH_INTEGRATIONS
        if integration.subagent_config and integration.subagent_config.has_subagent
    ]


def get_subagent_by_id(subagent_id: str):
    """Get subagent integration by ID or short_name."""
    search_id = subagent_id.lower().strip()
    for integ in OAUTH_INTEGRATIONS:
        if integ.id.lower() == search_id or (
            integ.short_name and integ.short_name.lower() == search_id
        ):
            if integ.subagent_config and integ.subagent_config.has_subagent:
                return integ
    return None


async def build_initial_messages(
    system_message: SystemMessage,
    agent_name: str,
    configurable: dict,
    task: str,
    user_id: Optional[str] = None,
) -> list:
    """
    Build the standard message list for subagent/executor execution.

    Creates a consistent message structure with:
    1. System message (agent-specific instructions)
    2. Context message (time, timezone, memories)
    3. Human message (the task)

    Args:
        system_message: Pre-built system message for the agent
        agent_name: Name of the agent (for visibility metadata)
        configurable: Config dict with user_time, user_name, etc.
        task: The task/query to execute
        user_id: Optional user ID for memory retrieval

    Returns:
        List of [system_message, context_message, human_message]
    """
    context_message = await create_agent_context_message(
        agent_name=agent_name,
        configurable=configurable,
        user_id=user_id,
        query=task,
    )

    return [
        system_message,
        context_message,
        HumanMessage(
            content=task,
            additional_kwargs={"visible_to": {agent_name}},
        ),
    ]


async def prepare_subagent_execution(
    subagent_id: str,
    task: str,
    user: dict,
    user_time: datetime,
    conversation_id: str,
    base_configurable: Optional[dict] = None,
    user_model_config: Optional[ModelConfig] = None,
) -> tuple[Optional[SubagentExecutionContext], Optional[str]]:
    """
    Prepare everything needed to execute a subagent.

    This is the shared setup logic used by both handoff tool and call_subagent.

    Args:
        subagent_id: The subagent ID (e.g., "google_calendar", "gmail")
        task: The task/query to execute
        user: User dict with user_id, email, name
        user_time: User's local time
        conversation_id: Thread/conversation ID
        base_configurable: Optional configurable to inherit from (for handoff tool)
        user_model_config: Optional model configuration for LLM settings

    Returns:
        Tuple of (SubagentExecutionContext, None) on success, or
        (None, error_message) on failure
    """
    user_id = user.get("user_id")
    clean_id = subagent_id.replace("subagent:", "").strip()

    # Resolve subagent
    integration = get_subagent_by_id(clean_id)
    if not integration or not integration.subagent_config:
        available = [i.id for i in get_subagent_integrations()][:5]
        return None, (
            f"Subagent '{subagent_id}' not found. "
            f"Available: {', '.join(available)}{'...' if len(available) == 5 else ''}"
        )

    subagent_cfg = integration.subagent_config
    agent_name = subagent_cfg.agent_name

    # Load subagent graph
    subagent_graph = await providers.aget(agent_name)
    if not subagent_graph:
        return None, f"Subagent {agent_name} not available"

    # Build thread ID and config
    subagent_thread_id = f"{integration.id}_{conversation_id}"
    config = build_agent_config(
        conversation_id=conversation_id,
        user=user,
        user_time=user_time,
        thread_id=subagent_thread_id,
        base_configurable=base_configurable,
        agent_name=agent_name,
        user_model_config=user_model_config,
    )
    configurable = config.get("configurable", {})

    # Create messages using shared helper
    system_message = await create_subagent_system_message(
        integration_id=integration.id,
        agent_name=agent_name,
        user_id=user_id,
    )

    messages = await build_initial_messages(
        system_message=system_message,
        agent_name=agent_name,
        configurable=configurable,
        task=task,
        user_id=user_id,
    )

    initial_state = {"messages": messages}

    return SubagentExecutionContext(
        subagent_graph=subagent_graph,
        agent_name=agent_name,
        config=config,
        configurable=configurable,
        integration_id=integration.id,
        initial_state=initial_state,
        user_id=user_id,
    ), None


async def execute_subagent_stream(
    ctx: SubagentExecutionContext,
    stream_writer=None,
    include_updates_mode: bool = False,
    track_tool_io: bool = False,
    integration_metadata: Optional[dict] = None,
) -> str:
    """
    Execute subagent with streaming and configurable tool tracking.

    This is the unified streaming function used by handoff, executor, and call_subagent.
    It supports different levels of tool tracking based on the caller's needs.

    Args:
        ctx: SubagentExecutionContext from prepare_subagent_execution
        stream_writer: Callback for custom events (from get_stream_writer())
        include_updates_mode: Include "updates" stream for complete tool args
        track_tool_io: Emit tool_inputs/tool_outputs events (for handoff)
        integration_metadata: Optional dict with {icon_url, integration_id, name}
                              for custom MCP icon display

    Returns:
        Complete message string
    """
    complete_message = ""
    pending_tool_calls: dict[str, dict] = {}

    # Configure stream modes based on needs
    stream_modes = ["messages", "custom"]
    if include_updates_mode:
        stream_modes.append("updates")

    async for event in ctx.subagent_graph.astream(
        ctx.initial_state,
        stream_mode=stream_modes,
        config=ctx.config,
    ):
        # Handle both 2-tuple and 3-tuple formats
        if len(event) == 2:
            stream_mode, payload = event
        else:
            continue

        # Handle updates stream (for complete tool args tracking)
        if stream_mode == "updates":
            for node_name, state_update in payload.items():
                if isinstance(state_update, dict) and "messages" in state_update:
                    for msg in state_update["messages"]:
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                tc_id = tc.get("id")
                                if tc_id:
                                    pending_tool_calls[tc_id] = {
                                        "name": tc.get("name"),
                                        "args": tc.get("args", {}),
                                    }
            continue

        if stream_mode == "custom":
            if stream_writer:
                stream_writer(payload)

        elif stream_mode == "messages":
            chunk, metadata = payload

            if metadata.get("silent"):
                continue

            if chunk and isinstance(chunk, AIMessageChunk):
                # Track tool calls and emit progress
                if chunk.tool_calls:
                    for tool_call in chunk.tool_calls:
                        tc_id = tool_call.get("id")
                        if tc_id and tc_id not in pending_tool_calls:
                            # Emit tool progress with optional metadata
                            progress_data = await format_tool_progress(
                                tool_call,
                                icon_url=(
                                    integration_metadata.get("icon_url")
                                    if integration_metadata
                                    else None
                                ),
                                integration_id=(
                                    integration_metadata.get("integration_id")
                                    if integration_metadata
                                    else None
                                ),
                                integration_name=(
                                    integration_metadata.get("name")
                                    if integration_metadata
                                    else None
                                ),
                            )
                            if progress_data and stream_writer:
                                stream_writer(progress_data)

                            pending_tool_calls[tc_id] = {
                                "name": tool_call.get("name"),
                                "args": tool_call.get("args", {}),
                            }
                        elif tc_id:
                            # Update stored args (they accumulate across chunks)
                            pending_tool_calls[tc_id]["args"] = tool_call.get(
                                "args", {}
                            )

                # Extract text content
                content = chunk.text() if hasattr(chunk, "text") else str(chunk.content)
                if content:
                    complete_message += content

            # Handle ToolMessage for inputs/outputs (when tracking enabled)
            elif track_tool_io and chunk and isinstance(chunk, ToolMessage):
                tc_id = chunk.tool_call_id

                # Emit tool_inputs when tool completes
                if tc_id and tc_id in pending_tool_calls and stream_writer:
                    stored_call = pending_tool_calls[tc_id]
                    if stored_call.get("args"):
                        stream_writer(
                            {
                                "tool_inputs": {
                                    "tool_call_id": tc_id,
                                    "inputs": stored_call["args"],
                                    "tool_category": (
                                        integration_metadata.get("integration_id")
                                        if integration_metadata
                                        else None
                                    ),
                                    "icon_url": (
                                        integration_metadata.get("icon_url")
                                        if integration_metadata
                                        else None
                                    ),
                                }
                            }
                        )
                    del pending_tool_calls[tc_id]

                # Emit tool_output
                if stream_writer:
                    stream_writer(
                        {
                            "tool_output": {
                                "tool_call_id": tc_id,
                                "output": (
                                    chunk.content[:3000]
                                    if isinstance(chunk.content, str)
                                    else str(chunk.content)[:3000]
                                ),
                            }
                        }
                    )

    return complete_message if complete_message else "Task completed"


async def prepare_executor_execution(
    task: str,
    configurable: dict,
    user_time: datetime,
) -> tuple[Optional[SubagentExecutionContext], Optional[str]]:
    """
    Prepare execution context for the executor agent.

    Similar to prepare_subagent_execution but:
    - Uses GraphManager for graph resolution (not providers)
    - Uses create_system_message for executor-specific prompts

    Args:
        task: The task/query to execute
        configurable: Config dict from RunnableConfig (with user_id, user_time, etc.)
        user_time: User's local time

    Returns:
        Tuple of (SubagentExecutionContext, None) on success, or
        (None, error_message) on failure
    """
    # Lazy import to avoid circular dependency
    from app.agents.core.graph_manager import GraphManager
    from app.helpers.message_helpers import create_system_message

    user_id = configurable.get("user_id")
    thread_id = configurable.get("thread_id", "")
    executor_thread_id = f"executor_{thread_id}"

    # Load executor graph
    executor_graph = await GraphManager.get_graph("executor_agent")
    if not executor_graph:
        return None, "Executor agent not available"

    # Build user dict for config
    user = {
        "user_id": user_id,
        "email": configurable.get("email"),
        "name": configurable.get("user_name"),
    }

    # Build config
    config = build_agent_config(
        conversation_id=thread_id,
        user=user,
        user_time=user_time,
        thread_id=executor_thread_id,
        base_configurable=configurable,
        agent_name="executor_agent",
    )
    new_configurable = config.get("configurable", {})

    # Create system message (executor-specific)
    system_message = create_system_message(
        user_id=user_id,
        agent_type="executor",
        user_name=configurable.get("user_name"),
    )

    # Build messages using shared helper
    messages = await build_initial_messages(
        system_message=system_message,
        agent_name="executor_agent",
        configurable=new_configurable,
        task=task,
        user_id=user_id,
    )

    return SubagentExecutionContext(
        subagent_graph=executor_graph,
        agent_name="executor_agent",
        config=config,
        configurable=new_configurable,
        integration_id="executor",
        initial_state={"messages": messages},
        user_id=user_id,
    ), None


async def check_subagent_integration(
    integration_id: str,
    user_id: str,
) -> Optional[str]:
    """
    Check if integration is connected. Returns error message if not connected.

    This is a simpler version that doesn't use stream_writer (for direct calls).
    """
    try:
        is_connected = await check_integration_status(integration_id, user_id)
        if is_connected:
            return None
        return (
            f"Integration {integration_id} is not connected. Please connect it first."
        )
    except Exception as e:
        logger.warning(f"Integration check failed: {e}")
        return None


async def call_subagent(
    subagent_id: str,
    query: str,
    user: dict,
    conversation_id: str,
    user_time: datetime,
    skip_integration_check: bool = True,
    user_model_config: Optional[ModelConfig] = None,
) -> AsyncGenerator[str, None]:
    """
    Directly invoke a subagent with streaming - drop-in for call_agent in chat_service.

    Args:
        subagent_id: e.g., "google_calendar", "gmail", "github"
        query: The user's message/query
        user: User dict with user_id, email, name
        conversation_id: Conversation thread ID
        user_time: User's local time
        skip_integration_check: Skip OAuth check (default True for testing)

    Yields:
        SSE-formatted strings compatible with chat_service streaming

    Usage in chat_service.py:
        from app.agents.core.subagents.subagent_runner import call_subagent

        async for chunk in call_subagent(
            subagent_id="google_calendar",
            query=body.message,
            user=user,
            conversation_id=conversation_id,
            user_time=user_time,
            user_model_config=user_model_config,
        ):
            yield chunk
    """
    import json

    user_id = user.get("user_id")

    # Optional integration check (before prepare to fail fast)
    if not skip_integration_check and user_id:
        clean_id = subagent_id.replace("subagent:", "").strip()
        integration = get_subagent_by_id(clean_id)
        if integration:
            error_message = await check_subagent_integration(integration.id, user_id)
            if error_message:
                yield f"data: {json.dumps({'error': error_message})}\n\n"
                yield "data: [DONE]\n\n"
                return

    ctx, error = await prepare_subagent_execution(
        subagent_id=subagent_id,
        task=query,
        user=user,
        user_time=user_time,
        conversation_id=conversation_id,
        user_model_config=user_model_config,
    )

    if error or ctx is None:
        logger.error(error or "Failed to prepare subagent execution")
        yield f"data: {json.dumps({'error': error or 'Failed to prepare subagent execution'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    logger.info(
        f"[DIRECT] Invoking subagent '{ctx.agent_name}' with query: {query[:80]}..."
    )

    # Stream execution with SSE formatting
    # Uses "updates" mode for complete tool args (same as handoff)
    complete_message = ""
    pending_tool_calls: dict[str, dict] = {}

    async for event in ctx.subagent_graph.astream(
        ctx.initial_state,
        stream_mode=["messages", "custom", "updates"],
        config=ctx.config,
    ):
        # Handle both 2-tuple and 3-tuple formats
        if len(event) == 2:
            stream_mode, payload = event
        else:
            continue

        # Handle updates stream (for complete tool args)
        if stream_mode == "updates":
            for node_name, state_update in payload.items():
                if isinstance(state_update, dict) and "messages" in state_update:
                    for msg in state_update["messages"]:
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                tc_id = tc.get("id")
                                if tc_id:
                                    pending_tool_calls[tc_id] = {
                                        "name": tc.get("name"),
                                        "args": tc.get("args", {}),
                                    }
            continue

        if stream_mode == "custom":
            yield f"data: {json.dumps(payload)}\n\n"
        elif stream_mode == "messages":
            chunk, metadata = payload
            if metadata.get("silent"):
                continue

            if chunk and isinstance(chunk, AIMessageChunk):
                # Track tool calls and emit progress
                if chunk.tool_calls:
                    for tool_call in chunk.tool_calls:
                        tc_id = tool_call.get("id")
                        if tc_id and tc_id not in pending_tool_calls:
                            progress_data = await format_tool_progress(tool_call)
                            if progress_data:
                                yield f"data: {json.dumps(progress_data)}\n\n"
                            pending_tool_calls[tc_id] = {
                                "name": tool_call.get("name"),
                                "args": tool_call.get("args", {}),
                            }
                        elif tc_id:
                            pending_tool_calls[tc_id]["args"] = tool_call.get(
                                "args", {}
                            )

                content = chunk.text() if hasattr(chunk, "text") else str(chunk.content)
                if content:
                    complete_message += content
                    yield f"data: {json.dumps({'response': content})}\n\n"

    # Final message for DB storage
    yield f"nostream: {json.dumps({'complete_message': complete_message})}"
    yield "data: [DONE]\n\n"

    logger.info(
        f"[DIRECT] Subagent '{ctx.agent_name}' completed. Response: {len(complete_message)} chars"
    )
