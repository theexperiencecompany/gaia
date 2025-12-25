"""
Subagent Tools - Consolidated Delegation Pattern

This module provides two tools for subagent delegation:
1. search_subagents - Semantic search for available subagents
2. handoff - Generic handoff tool that delegates to any subagent

Subagents are lazy-loaded on first invocation via providers.aget().
All metadata comes from oauth_config.py OAUTH_INTEGRATIONS.
"""

from datetime import datetime
from typing import Annotated, List, Optional, TypedDict

from app.agents.core.subagents.subagent_helpers import (
    create_subagent_system_message,
)
from app.config.loggers import common_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.core.lazy_loader import providers
from app.helpers.agent_helpers import build_agent_config
from app.services.oauth_service import (
    check_integration_status,
)
from langchain_core.messages import (
    AIMessageChunk,
    HumanMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.store.base import BaseStore

SUBAGENTS_NAMESPACE = ("subagents",)


class SubagentInfo(TypedDict):
    """Subagent information structure."""

    id: str
    name: str
    connected: bool


async def check_integration_connection(
    integration_id: str,
    user_id: str,
) -> Optional[str]:
    """Check if integration is connected and return error message if not."""
    try:
        integration = get_integration_by_id(integration_id)
        if not integration:
            return None

        is_connected = await check_integration_status(integration_id, user_id)

        if is_connected:
            return None

        writer = get_stream_writer()
        writer({"progress": f"Checking {integration.name} connection..."})

        integration_data = {
            "integration_id": integration.id,
            "message": f"To use {integration.name} features, please connect your account first.",
        }

        writer({"integration_connection_required": integration_data})

        return (
            f"Integration {integration.name} is not connected. Please connect it first."
        )

    except Exception as e:
        logger.error(f"Error checking integration status for {integration_id}: {e}")
        return None


def _get_subagent_integrations() -> List:
    """Get all integrations that have subagent configurations."""
    return [
        integration
        for integration in OAUTH_INTEGRATIONS
        if integration.subagent_config and integration.subagent_config.has_subagent
    ]


def _get_subagent_by_id(subagent_id: str):
    """Get subagent integration by ID or short_name."""
    search_id = subagent_id.lower().strip()
    for integ in OAUTH_INTEGRATIONS:
        if integ.id.lower() == search_id or (
            integ.short_name and integ.short_name.lower() == search_id
        ):
            if integ.subagent_config and integ.subagent_config.has_subagent:
                return integ
    return None


async def index_subagents_to_store(store: BaseStore) -> None:
    """Index all subagents into the store for semantic search with rich descriptions."""
    from langgraph.store.base import PutOp

    subagent_integrations = _get_subagent_integrations()

    put_ops = []
    for integration in subagent_integrations:
        cfg = integration.subagent_config
        # Create comprehensive description with provider name mentioned multiple times
        # for better semantic matching
        provider_name = integration.name
        short_name = integration.short_name or integration.id

        description = (
            f"{provider_name} ({short_name}). "
            f"{provider_name} specializes in {cfg.domain}. "
            f"Use {provider_name} for: {cfg.use_cases}. "
            f"{provider_name} capabilities: {cfg.capabilities}"
        )

        put_ops.append(
            PutOp(
                namespace=SUBAGENTS_NAMESPACE,
                key=integration.id,
                value={
                    "id": integration.id,
                    "name": integration.name,
                    "description": description,
                },
                index=["description"],
            )
        )

    if put_ops:
        await store.abatch(put_ops)
        logger.info(f"Indexed {len(put_ops)} subagents to store")


@tool
async def handoff(
    subagent_id: Annotated[
        str,
        "The ID of the subagent to delegate to (e.g., 'gmail', 'subagent:gmail', 'google_calendar'). "
        "Get this from retrieve_tools results (subagent IDs have 'subagent:' prefix).",
    ],
    task: Annotated[
        str,
        "Detailed description of the task for the subagent, including all relevant context.",
    ],
    config: RunnableConfig,
) -> str:
    """Delegate a task to a specialized subagent.

    Use this tool to hand off tasks to expert subagents that specialize in specific domains.
    First use retrieve_tools to find available subagents (they appear with 'subagent:' prefix).

    The subagent will:
    1. Process the task using its specialized tools
    2. Return the result of the completed task

    Args:
        subagent_id: ID of the subagent from retrieve_tools (with or without 'subagent:' prefix)
        task: Complete task description with all necessary context
    """
    try:
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id")

        # Strip 'subagent:' prefix if present
        clean_id = subagent_id.replace("subagent:", "").strip()

        integration = _get_subagent_by_id(clean_id)

        if not integration or not integration.subagent_config:
            available = [i.id for i in _get_subagent_integrations()][:5]
            return (
                f"Subagent '{subagent_id}' not found. "
                f"Use retrieve_tools to find available subagents. "
                f"Examples: {', '.join([f'subagent:{a}' for a in available])}{'...' if len(available) == 5 else ''}"
            )

        subagent_cfg = integration.subagent_config
        agent_name = subagent_cfg.agent_name

        # Only check connection for non-MCP integrations (MCP doesn't need auth)
        if integration.managed_by != "mcp" and user_id:
            error_message = await check_integration_connection(integration.id, user_id)
            if error_message:
                return error_message

        subagent_graph = await providers.aget(agent_name)
        if not subagent_graph:
            return f"Error: {agent_name} not available"

        thread_id = configurable.get("thread_id", "")
        subagent_thread_id = f"{integration.id}_{thread_id}"

        user = {
            "user_id": user_id,
            "email": configurable.get("email"),
            "name": configurable.get("user_name"),
        }
        user_time_str = configurable.get("user_time", "")
        user_time = (
            datetime.fromisoformat(user_time_str) if user_time_str else datetime.now()
        )

        subagent_runnable_config = build_agent_config(
            conversation_id=thread_id,
            user=user,
            user_time=user_time,
            thread_id=subagent_thread_id,
            base_configurable=configurable,
            agent_name=agent_name,
        )

        system_message = await create_subagent_system_message(
            integration_id=integration.id,
            agent_name=agent_name,
            user_id=user_id,
        )

        initial_state = {
            "messages": [
                system_message,
                HumanMessage(
                    content=task,
                    additional_kwargs={"visible_to": {agent_name}},
                ),
            ]
        }

        complete_message = ""
        writer = get_stream_writer()

        async for event in subagent_graph.astream(
            initial_state,
            stream_mode=["messages", "custom"],
            config=subagent_runnable_config,
        ):
            stream_mode, payload = event

            if stream_mode == "custom":
                writer(payload)
            elif stream_mode == "messages":
                chunk, metadata = payload

                if metadata.get("silent"):
                    continue

                if chunk and isinstance(chunk, AIMessageChunk):
                    content = str(chunk.content)
                    if content:
                        complete_message += content

        return complete_message if complete_message else "Task completed"

    except Exception as e:
        logger.error(f"Error in handoff to {subagent_id}: {e}")
        return f"Error executing task: {str(e)}"
