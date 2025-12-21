"""
Subagent Execution Core - Shared logic for subagent invocation.

This module contains the reusable classes and functions for invoking subagents.
Both handoff_tools.py and direct call_subagent use these.

Keeping shared code here avoids cyclic dependencies since handoff_tools.py
imports from this file, not the other way around.
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
from app.services.oauth_service import check_integration_status
from langchain_core.messages import AIMessageChunk, HumanMessage


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

    # Create messages
    system_message = await create_subagent_system_message(
        integration_id=integration.id,
        agent_name=agent_name,
        user_id=user_id,
    )

    context_message = await create_agent_context_message(
        agent_name=agent_name,
        configurable=configurable,
        user_id=user_id,
        query=task,
    )

    initial_state = {
        "messages": [
            system_message,
            context_message,
            HumanMessage(
                content=task,
                additional_kwargs={"visible_to": {agent_name}},
            ),
        ]
    }

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
) -> str:
    """
    Execute subagent and stream results.

    Args:
        ctx: SubagentExecutionContext from prepare_subagent_execution
        stream_writer: Optional callback for custom events (for handoff tool)

    Returns:
        Complete message string
    """
    complete_message = ""

    async for event in ctx.subagent_graph.astream(
        ctx.initial_state,
        stream_mode=["messages", "custom"],
        config=ctx.config,
    ):
        stream_mode, payload = event

        if stream_mode == "custom":
            if stream_writer:
                stream_writer(payload)
        elif stream_mode == "messages":
            chunk, metadata = payload

            if metadata.get("silent"):
                continue

            if chunk and isinstance(chunk, AIMessageChunk):
                content = str(chunk.content)
                if content:
                    complete_message += content

    return complete_message if complete_message else "Task completed"


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
    complete_message = ""

    async for event in ctx.subagent_graph.astream(
        ctx.initial_state,
        stream_mode=["messages", "custom"],
        config=ctx.config,
    ):
        stream_mode, payload = event

        if stream_mode == "custom":
            yield f"data: {json.dumps(payload)}\n\n"
        elif stream_mode == "messages":
            chunk, metadata = payload
            if metadata.get("silent"):
                continue
            if chunk and isinstance(chunk, AIMessageChunk):
                content = str(chunk.content)
                if content:
                    complete_message += content
                    yield f"data: {json.dumps({'response': content})}\n\n"

    # Final message for DB storage
    yield f"nostream: {json.dumps({'complete_message': complete_message})}"
    yield "data: [DONE]\n\n"

    logger.info(
        f"[DIRECT] Subagent '{ctx.agent_name}' completed. Response: {len(complete_message)} chars"
    )
