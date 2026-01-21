"""
Subagent Tools - Consolidated Delegation Pattern

This module provides two tools for subagent delegation:
1. search_subagents - Semantic search for available subagents
2. handoff - Generic handoff tool that delegates to any subagent

Subagents are lazy-loaded on first invocation via providers.aget().
All metadata comes from oauth_config.py OAUTH_INTEGRATIONS.
"""

import re
from datetime import datetime
from typing import Annotated, Optional, TypedDict

from app.agents.core.subagents.provider_subagents import create_subagent_for_user
from app.agents.core.subagents.subagent_helpers import (
    create_subagent_system_message,
)
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    build_initial_messages,
    execute_subagent_stream,
)
from app.config.loggers import common_logger as logger
from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    get_integration_by_id,
    get_subagent_integrations,
)
from app.core.lazy_loader import providers
from app.db.mongodb.collections import integrations_collection
from app.helpers.agent_helpers import build_agent_config
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.oauth.oauth_service import (
    check_integration_status,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.store.base import BaseStore, PutOp

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


async def _get_subagent_by_id(subagent_id: str):
    """
    Get subagent integration by ID or short_name.

    Checks both platform integrations (OAUTH_INTEGRATIONS) and
    custom MCPs from MongoDB.

    Returns:
        Integration config or dict with custom MCP info, or None if not found
    """
    search_id = subagent_id.lower().strip()

    # Check platform integrations first
    for integ in OAUTH_INTEGRATIONS:
        if integ.id.lower() == search_id or (
            integ.short_name and integ.short_name.lower() == search_id
        ):
            if integ.subagent_config and integ.subagent_config.has_subagent:
                return integ

    # Escape regex metacharacters to prevent ReDoS attacks
    escaped_search_id = re.escape(search_id)

    # Search by integration_id (case-insensitive)
    custom = await integrations_collection.find_one(
        {
            "source": "custom",
            "$or": [
                {
                    "integration_id": {
                        "$regex": f"^{escaped_search_id}$",
                        "$options": "i",
                    }
                },
                {"name": {"$regex": f"^{escaped_search_id}$", "$options": "i"}},
            ],
        }
    )

    if custom:
        # Return a dict that mimics the integration structure
        return {
            "id": custom.get("integration_id"),
            "name": custom.get("name"),
            "source": "custom",
            "managed_by": "mcp",
            "mcp_config": custom.get("mcp_config"),
            "icon_url": custom.get("icon_url"),
            "subagent_config": None,  # Custom MCPs don't have static subagent config
        }

    # Fallback: Try IntegrationResolver which checks multiple sources
    # This handles cases where integration is in user_integrations but not integrations

    resolved = await IntegrationResolver.resolve(search_id)
    if resolved and resolved.source == "custom" and resolved.custom_doc:
        doc = resolved.custom_doc
        return {
            "id": doc.get("integration_id"),
            "name": doc.get("name"),
            "source": "custom",
            "managed_by": "mcp",
            "mcp_config": doc.get("mcp_config"),
            "icon_url": doc.get("icon_url"),
            "subagent_config": None,
        }

    return None


async def index_custom_mcp_as_subagent(
    store: BaseStore,
    integration_id: str,
    name: str,
    description: str,
) -> None:
    """
    Index a custom MCP as a subagent for handoff discovery.

    Called when user connects a custom MCP to make it immediately
    available for semantic search and handoff.

    Args:
        store: The ChromaStore instance
        integration_id: Unique ID of the custom integration (12-char hex)
        name: Display name of the integration
        description: Description of what the integration does

    Note: With the new short UUID format for integration_id (e.g., a1b2c3d4e5f6),
    the subagent key is now clean: subagent:a1b2c3d4e5f6
    """
    # Create rich description for semantic matching
    rich_description = (
        f"{name}. Custom MCP integration. "
        f"{description}. "
        f"Use cases: data fetching, automation, API access, external services. "
        f"Examples: fetch data, scrape, query, automate"
    )

    put_op = PutOp(
        namespace=SUBAGENTS_NAMESPACE,
        key=integration_id,  # Now a clean 12-char hex UUID
        value={
            "id": integration_id,
            "name": name,
            "description": rich_description,
            "source": "custom",  # Mark as custom for filtering
        },
        index=["description"],
    )

    await store.abatch([put_op])
    logger.info(f"Indexed custom MCP {name} ({integration_id}) as subagent")


async def _resolve_subagent(
    subagent_id: str,
    user_id: Optional[str],
) -> tuple[Optional[object], Optional[str], Optional[str], bool]:
    """
    Resolve subagent from ID and get the graph.

    Returns:
        Tuple of (subagent_graph, agent_name, integration_id, is_custom)
        or (None, None, error_message, False) on failure
    """
    clean_id = subagent_id.replace("subagent:", "").strip()

    # Check for format with parentheses: "name (id)" -> extract id
    paren_match = re.search(
        r"\(([a-zA-Z0-9_]+)\)$", clean_id
    )  # pragma: allowlist secret
    if paren_match:
        clean_id = paren_match.group(1)

    integration = await _get_subagent_by_id(clean_id)

    if not integration:
        available = [i.id for i in get_subagent_integrations()][:5]
        error = (
            f"Subagent '{subagent_id}' not found. "
            f"Use retrieve_tools to find available subagents. "
            f"Examples: {', '.join([f'subagent:{a}' for a in available])}{'...' if len(available) == 5 else ''}"
        )
        return None, None, error, False

    # Handle custom MCPs (returned as dict from MongoDB)
    if isinstance(integration, dict):
        # Custom MCP - integration is a dict
        integration_id = str(integration.get("id", ""))
        integration_name = str(integration.get("name", integration_id))

        if not integration_id:
            return None, None, "Error: Custom integration has no ID", False

        if not user_id:
            return (
                None,
                None,
                f"Error: {integration_name} requires authentication. Please sign in first.",
                False,
            )

        # Create subagent for custom MCP
        subagent_graph = await create_subagent_for_user(integration_id, user_id)
        if not subagent_graph:
            return (
                None,
                None,
                f"Error: Failed to create subagent for {integration_name}",
                False,
            )

        agent_name = f"custom_mcp_{integration_id}"
        return subagent_graph, agent_name, integration_id, True

    # Platform integration (OAuthIntegration object)
    if not (hasattr(integration, "subagent_config") and integration.subagent_config):
        return (
            None,
            None,
            f"Error: {subagent_id} is not configured as a subagent",
            False,
        )

    subagent_cfg = integration.subagent_config
    agent_name = subagent_cfg.agent_name
    int_id = integration.id

    # Handle auth-required MCP integrations specially
    if (
        integration.managed_by == "mcp"
        and integration.mcp_config
        and integration.mcp_config.requires_auth
    ):
        if not user_id:
            return (
                None,
                None,
                f"Error: {agent_name} requires authentication. Please sign in first.",
                False,
            )

        # Check if user has connected this MCP integration
        token_store = MCPTokenStore(user_id=user_id)
        is_connected = await token_store.is_connected(int_id)
        if not is_connected:
            return (
                None,
                None,
                (
                    f"Error: {agent_name} requires OAuth connection. "
                    f"Please connect {integration.name} first via settings."
                ),
                False,
            )

        # Create subagent on-the-fly with user's tokens
        subagent_graph = await create_subagent_for_user(int_id, user_id)
        if not subagent_graph:
            return (
                None,
                None,
                f"Error: Failed to create {agent_name} subagent",
                False,
            )
    else:
        # Non-MCP or non-auth-required MCP integrations
        # Skip connection check for internal integrations (always available)
        if integration.managed_by not in ("mcp", "internal") and user_id:
            error_message = await check_integration_connection(int_id, user_id)
            if error_message:
                return None, None, error_message, False

        subagent_graph = await providers.aget(agent_name)
        if not subagent_graph:
            return None, None, f"Error: {agent_name} not available", False

    return subagent_graph, agent_name, int_id, False


@tool
async def handoff(
    subagent_id: Annotated[
        str,
        "The ID of the subagent to delegate to (e.g., 'gmail', 'subagent:gmail', 'subagent:semantic_scholar (fb9dfd7e05f8)'). "
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
        subagent_id: ID of the subagent from retrieve_tools. Supports formats:
            - "subagent:gmail" (platform integration)
            - "subagent:semantic_scholar (fb9dfd7e05f8)" (custom integration with name and ID)  # pragma: allowlist secret
            - "gmail" or "fb9dfd7e05f8" (bare IDs)  # pragma: allowlist secret
        task: Complete task description with all necessary context
    """
    try:
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id")

        # Resolve subagent and get graph
        (
            subagent_graph,
            resolved_agent_name,
            int_id_or_error,
            is_custom,
        ) = await _resolve_subagent(subagent_id, user_id)

        if (
            subagent_graph is None
            or resolved_agent_name is None
            or int_id_or_error is None
        ):
            return int_id_or_error or "Unknown error resolving subagent"

        # Type assertion after null check - these are guaranteed to be str at this point
        agent_name: str = resolved_agent_name
        int_id: str = int_id_or_error

        # Build config
        thread_id = configurable.get("thread_id", "")
        subagent_thread_id = f"{int_id}_{thread_id}"

        user = {
            "user_id": user_id,
            "email": configurable.get("email"),
            "name": configurable.get("user_name"),
        }
        user_time_str = configurable.get("user_time", "")
        user_time = (
            datetime.fromisoformat(user_time_str) if user_time_str else datetime.now()
        )

        subagent_config = build_agent_config(
            conversation_id=thread_id,
            user=user,
            user_time=user_time,
            thread_id=subagent_thread_id,
            base_configurable=configurable,
            agent_name=agent_name,
        )
        new_configurable = subagent_config.get("configurable", {})

        # Create system message
        system_message = await create_subagent_system_message(
            integration_id=int_id,
            agent_name=agent_name,
            user_id=user_id,
        )

        # Build messages using shared helper (includes context message - fixes the bug!)
        messages = await build_initial_messages(
            system_message=system_message,
            agent_name=agent_name,
            configurable=new_configurable,
            task=task,
            user_id=user_id,
        )

        # Create execution context
        ctx = SubagentExecutionContext(
            subagent_graph=subagent_graph,
            agent_name=agent_name,
            config=subagent_config,
            configurable=new_configurable,
            integration_id=int_id,
            initial_state={"messages": messages},
            user_id=user_id,
        )

        # Emit handoff progress
        writer = get_stream_writer()

        # Get display name for progress message
        display_name: str = agent_name.replace("_", " ").title()
        handoff_icon_url: Optional[str] = None

        if is_custom:
            # For custom MCPs, we need to get the integration data again
            clean_id = subagent_id.replace("subagent:", "").strip()
            paren_match = re.search(r"\(([a-zA-Z0-9_]+)\)$", clean_id)
            if paren_match:
                clean_id = paren_match.group(1)
            integration = await _get_subagent_by_id(clean_id)
            if isinstance(integration, dict):
                display_name = str(integration.get("name", int_id))
                handoff_icon_url = integration.get("icon_url")
        else:
            integration = get_integration_by_id(int_id)
            if integration and hasattr(integration, "name"):
                display_name = integration.name

        writer(
            {
                "progress": {
                    "message": f"Handing off to {display_name}",
                    "tool_name": "handoff",
                    "tool_category": "handoff",
                    "show_category": False,
                    "icon_url": handoff_icon_url,
                }
            }
        )

        # Build integration metadata for tool tracking
        integration_metadata = None
        if is_custom:
            integration_metadata = {
                "icon_url": handoff_icon_url,
                "integration_id": int_id,
                "name": display_name,
            }

        # Execute using shared streaming function
        return await execute_subagent_stream(
            ctx=ctx,
            stream_writer=writer,
            include_updates_mode=True,
            track_tool_io=True,
            integration_metadata=integration_metadata,
        )

    except Exception as e:
        logger.error(f"Error in handoff to {subagent_id}: {e}")
        return f"Error executing task: {str(e)}"
