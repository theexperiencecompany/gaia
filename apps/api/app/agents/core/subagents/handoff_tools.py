"""
Subagent Tools - Consolidated Delegation Pattern

This module provides tools for subagent delegation:
1. index_subagents_to_store - Index subagents for semantic search
2. handoff - Generic handoff tool that delegates to any subagent

Subagents are lazy-loaded on first invocation via providers.aget().
All metadata comes from oauth_config.py OAUTH_INTEGRATIONS.
"""

from datetime import datetime
from typing import Annotated, Optional, TypedDict

from app.agents.core.subagents.subagent_runner import (
    execute_subagent_stream,
    get_subagent_by_id,
    get_subagent_integrations,
    prepare_subagent_execution,
)
from app.config.loggers import common_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.services.oauth_service import check_integration_status
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


async def index_subagents_to_store(store: BaseStore) -> None:
    """Index all subagents into the store for semantic search with rich descriptions."""
    from langgraph.store.base import PutOp

    subagent_integrations = get_subagent_integrations()

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

        # Check integration connection first
        clean_id = subagent_id.replace("subagent:", "").strip()
        integration = get_subagent_by_id(clean_id)

        if integration and user_id:
            error_message = await check_integration_connection(integration.id, user_id)
            if error_message:
                return error_message

        # Extract user info from configurable
        user = {
            "user_id": user_id,
            "email": configurable.get("email"),
            "name": configurable.get("user_name"),
        }
        user_time_str = configurable.get("user_time", "")
        user_time = (
            datetime.fromisoformat(user_time_str) if user_time_str else datetime.now()
        )
        thread_id = configurable.get("thread_id", "")

        # Use shared preparation function
        ctx, error = await prepare_subagent_execution(
            subagent_id=subagent_id,
            task=task,
            user=user,
            user_time=user_time,
            conversation_id=thread_id,
            base_configurable=configurable,
        )

        if error or ctx is None:
            return error or "Failed to prepare subagent execution"

        # Execute with stream writer
        writer = get_stream_writer()
        return await execute_subagent_stream(ctx, stream_writer=writer)

    except Exception as e:
        logger.error(f"Error in handoff to {subagent_id}: {e}")
        return f"Error executing task: {str(e)}"
