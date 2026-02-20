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

import json
from datetime import datetime
from typing import AsyncGenerator, List, Optional

from app.agents.core.subagents.subagent_helpers import (
    create_agent_context_message,
    create_subagent_system_message,
)
from app.config.loggers import common_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.core.lazy_loader import providers
from app.core.stream_manager import stream_manager
from app.helpers.agent_helpers import build_agent_config
from app.models.models_models import ModelConfig
from app.services.oauth.oauth_service import check_integration_status
from app.utils.stream_utils import extract_tool_entries_from_update
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
        stream_id: Optional[str] = None,
    ):
        self.subagent_graph = subagent_graph
        self.agent_name = agent_name
        self.config = config
        self.configurable = configurable
        self.integration_id = integration_id
        self.initial_state = initial_state
        self.user_id = user_id
        self.stream_id = stream_id


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
    subagent_id: Optional[str] = None,
    retrieval_query: Optional[str] = None,
) -> list:
    """
    Build the standard message list for subagent/executor execution.

    Creates a consistent message structure with:
    1. System message (agent-specific instructions)
    2. Context message (time, timezone, memories, skills)
    3. Human message (the task)

    Args:
        system_message: Pre-built system message for the agent
        agent_name: Name of the agent (for visibility metadata)
        configurable: Config dict with user_time, user_name, etc.
        task: The task/query to execute (used as LLM prompt content)
        user_id: Optional user ID for memory retrieval
        subagent_id: Optional subagent ID for skill retrieval (e.g., "twitter", "github")
        retrieval_query: Optional query for memory/context retrieval. Defaults to task
            if not provided. Use this to pass the original unenhanced task when task
            contains injected hints that would pollute semantic search.

    Returns:
        List of [system_message, context_message, human_message]
    """
    context_message = await create_agent_context_message(
        configurable=configurable,
        user_id=user_id,
        query=retrieval_query if retrieval_query is not None else task,
        subagent_id=subagent_id,
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
    stream_id: Optional[str] = None,
) -> tuple[Optional[SubagentExecutionContext], Optional[str]]:
    """
    Prepare everything needed to execute a subagent.

    This is the shared setup logic used by both handoff tool and call_subagent.

    Args:
        subagent_id: The subagent ID (e.g., "googlecalendar", "gmail")
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
        subagent_id=agent_name,
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
        subagent_id=integration.id,  # Pass for skill retrieval
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
        stream_id=stream_id,
    ), None


async def execute_subagent_stream(
    ctx: SubagentExecutionContext,
    stream_writer=None,
    integration_metadata: Optional[dict] = None,
) -> str:
    """
    Execute subagent with streaming and tool tracking.

    Args:
        ctx: SubagentExecutionContext from prepare_subagent_execution
        stream_writer: Callback for custom events (from get_stream_writer())
        integration_metadata: Optional dict with {icon_url, integration_id, name}
                              for custom MCP icon display

    Returns:
        Complete message string

    Stream Event Flow:
        1. "updates" - Emit tool_data with complete args when tool is called
        2. "messages" - Stream content, emit tool_output when ToolMessage arrives
        3. "custom" - Forward custom events (progress messages, etc.) to parent
    """
    complete_message = ""
    emitted_tool_calls: set[str] = set()

    async for event in ctx.subagent_graph.astream(
        ctx.initial_state,
        stream_mode=["messages", "custom", "updates"],
        config=ctx.config,
    ):
        # Check for cancellation
        if ctx.stream_id and await stream_manager.is_cancelled(ctx.stream_id):
            logger.info(f"Subagent stream {ctx.stream_id} cancelled by user")
            break

        # Handle 2-tuple format only (no subgraphs)
        if len(event) != 2:
            continue
        stream_mode, payload = event

        if stream_mode == "updates":
            for node_name, state_update in payload.items():
                # Use shared helper to extract and format tool entries
                entries = await extract_tool_entries_from_update(
                    state_update=state_update,
                    emitted_tool_calls=emitted_tool_calls,
                    integration_metadata=integration_metadata,
                )
                for tc_id, tool_entry in entries:
                    if stream_writer:
                        stream_writer({"tool_data": tool_entry})
            continue

        if stream_mode == "messages":
            chunk, metadata = payload
            if metadata.get("silent"):
                continue

            # Accumulate AI response content
            if chunk and isinstance(chunk, AIMessageChunk):
                content = chunk.text if hasattr(chunk, "text") else str(chunk.content)
                if content:
                    complete_message += content

            # Emit tool_output when ToolMessage arrives
            elif chunk and isinstance(chunk, ToolMessage):
                output = (
                    chunk.content[:3000]
                    if isinstance(chunk.content, str)
                    else str(chunk.content)[:3000]
                )
                if stream_writer:
                    stream_writer(
                        {
                            "tool_output": {
                                "tool_call_id": chunk.tool_call_id,
                                "output": output,
                            }
                        }
                    )
            continue

        if stream_mode == "custom":
            if stream_writer:
                stream_writer(payload)

    return complete_message if complete_message else "Task completed"


async def prepare_executor_execution(
    task: str,
    configurable: dict,
    user_time: datetime,
    stream_id: Optional[str] = None,
) -> tuple[Optional[SubagentExecutionContext], Optional[str]]:
    """
    Prepare execution context for the executor agent.

    Similar to prepare_subagent_execution but:
    - Uses GraphManager for graph resolution (not providers)
    - Uses create_system_message for executor-specific prompts
    - Injects direct handoff hints when selected_tool/tool_category is known

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
        subagent_id="executor_agent",  # Use agent_name as agent_id in mem0
    )
    new_configurable = config.get("configurable", {})

    # Create system message (executor-specific)
    system_message = create_system_message(
        user_id=user_id,
        agent_type="executor",
        user_name=configurable.get("user_name"),
    )

    # Inject direct handoff hint when tool_category maps to a known subagent
    # This lets the executor skip the retrieve_tools discovery round-trip
    enhanced_task = task
    tool_category = configurable.get("tool_category")
    selected_tool = configurable.get("selected_tool")
    if tool_category and selected_tool:
        subagent_integration = get_subagent_by_id(tool_category)
        if subagent_integration:
            enhanced_task = (
                f"{task}\n\n"
                f"DIRECT EXECUTION HINT: The tool '{selected_tool}' belongs to the "
                f"'{tool_category}' subagent. Skip retrieve_tools discovery and directly "
                f'call handoff(subagent_id="{tool_category}", task="{task}").'
            )

    # Build messages using shared helper.
    # Pass original task as retrieval_query so memory/context semantic search
    # is not polluted by the DIRECT EXECUTION HINT injected into enhanced_task.
    messages = await build_initial_messages(
        system_message=system_message,
        agent_name="executor_agent",
        configurable=new_configurable,
        task=enhanced_task,
        user_id=user_id,
        retrieval_query=task,
    )

    return SubagentExecutionContext(
        subagent_graph=executor_graph,
        agent_name="executor_agent",
        config=config,
        configurable=new_configurable,
        integration_id="executor",
        initial_state={"messages": messages},
        user_id=user_id,
        stream_id=stream_id,
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
    stream_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Directly invoke a subagent with streaming - drop-in for call_agent in chat_service.

    Primarily used for testing subagents directly without going through the main agent.

    Args:
        subagent_id: e.g., "googlecalendar", "gmail", "github"
        query: The user's message/query
        user: User dict with user_id, email, name
        conversation_id: Conversation thread ID
        user_time: User's local time
        skip_integration_check: Skip OAuth check (default True for testing)
        user_model_config: Optional model configuration

    Yields:
        SSE-formatted strings compatible with chat_service streaming

    Usage:
        async for chunk in call_subagent(
            subagent_id="googlecalendar",
            query="What's on my calendar today?",
            user=user,
            conversation_id=conversation_id,
            user_time=user_time,
        ):
            yield chunk
    """
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
        stream_id=stream_id,
    )

    if error or ctx is None:
        logger.error(error or "Failed to prepare subagent execution")
        yield f"data: {json.dumps({'error': error or 'Failed to prepare subagent execution'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    logger.info(
        f"[DIRECT] Invoking subagent '{ctx.agent_name}' with query: {query[:80]}..."
    )

    complete_message = ""
    emitted_tool_calls: set[str] = set()

    async for event in ctx.subagent_graph.astream(
        ctx.initial_state,
        stream_mode=["messages", "custom", "updates"],
        config=ctx.config,
    ):
        # Check for cancellation
        if stream_id and await stream_manager.is_cancelled(stream_id):
            logger.info(f"Subagent stream {stream_id} cancelled by user")
            break
        # Handle 2-tuple format only (no subgraphs)
        if len(event) != 2:
            continue
        stream_mode, payload = event

        if stream_mode == "updates":
            for node_name, state_update in payload.items():
                # Use shared helper to extract and format tool entries
                entries = await extract_tool_entries_from_update(
                    state_update=state_update,
                    emitted_tool_calls=emitted_tool_calls,
                )
                for tc_id, tool_entry in entries:
                    yield f"data: {json.dumps({'tool_data': tool_entry})}\n\n"
            continue

        if stream_mode == "messages":
            chunk, metadata = payload
            if metadata.get("silent"):
                continue

            # Stream AI response content
            if chunk and isinstance(chunk, AIMessageChunk):
                content = chunk.text if hasattr(chunk, "text") else str(chunk.content)
                if content:
                    complete_message += content
                    yield f"data: {json.dumps({'response': content})}\n\n"

            # Emit tool_output when ToolMessage arrives
            elif chunk and isinstance(chunk, ToolMessage):
                output = (
                    chunk.content[:3000]
                    if isinstance(chunk.content, str)
                    else str(chunk.content)[:3000]
                )
                yield f"data: {json.dumps({'tool_output': {'tool_call_id': chunk.tool_call_id, 'output': output}})}\n\n"
            continue

        if stream_mode == "custom":
            yield f"data: {json.dumps(payload)}\n\n"

    # Final message for DB storage
    yield f"nostream: {json.dumps({'complete_message': complete_message})}"
    yield "data: [DONE]\n\n"

    logger.info(
        f"[DIRECT] Subagent '{ctx.agent_name}' completed. Response: {len(complete_message)} chars"
    )
