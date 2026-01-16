"""
Subagent Tools - Consolidated Delegation Pattern

This module provides two tools for subagent delegation:
1. search_subagents - Semantic search for available subagents
2. handoff - Generic handoff tool that delegates to any subagent

Subagents are lazy-loaded on first invocation via providers.aget().
All metadata comes from oauth_config.py OAUTH_INTEGRATIONS.
"""

from datetime import datetime
from typing import Annotated, Optional, TypedDict

from app.agents.core.subagents.provider_subagents import create_subagent_for_user
from app.agents.core.subagents.subagent_helpers import (
    create_subagent_system_message,
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
from app.utils.agent_utils import format_tool_progress
from langchain_core.messages import (
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
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

    # Search by integration_id (case-insensitive)
    custom = await integrations_collection.find_one(
        {
            "source": "custom",
            "$or": [
                {"integration_id": {"$regex": f"^{search_id}$", "$options": "i"}},
                {"name": {"$regex": f"^{search_id}$", "$options": "i"}},
            ],
        }
    )

    if custom:
        # Debug: Log raw MongoDB document
        logger.info(
            f"_get_subagent_by_id found custom MCP: "
            f"integration_id={custom.get('integration_id')}, "
            f"name={custom.get('name')}, "
            f"icon_url={custom.get('icon_url')}, "
            f"all_keys={list(custom.keys())}"
        )
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
        logger.info(
            f"_get_subagent_by_id found via IntegrationResolver: "
            f"integration_id={doc.get('integration_id')}, "
            f"name={doc.get('name')}"
        )
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
        integration_id: Unique ID of the custom integration
        name: Display name of the integration
        description: Description of what the integration does
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
        key=integration_id,
        value={
            "id": integration_id,
            "name": name,
            "description": rich_description,
            "source": "custom",  # Mark as custom for filtering
        },
        index=["description"],
    )

    await store.abatch([put_op])
    logger.info(f"Indexed custom MCP {integration_id} as subagent")


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
        # Defensive check - config may be passed as list in edge cases
        if isinstance(config, dict):
            configurable = config.get("configurable", {})
        else:
            configurable = {}
            logger.warning(f"handoff received non-dict config: {type(config).__name__}")
        user_id = configurable.get("user_id")

        # Strip 'subagent:' prefix if present
        clean_id = subagent_id.replace("subagent:", "").strip()

        integration = await _get_subagent_by_id(clean_id)

        if not integration:
            available = [i.id for i in get_subagent_integrations()][:5]
            return (
                f"Subagent '{subagent_id}' not found. "
                f"Use retrieve_tools to find available subagents. "
                f"Examples: {', '.join([f'subagent:{a}' for a in available])}{'...' if len(available) == 5 else ''}"
            )

        # Handle custom MCPs (returned as dict from MongoDB)
        is_custom = (
            isinstance(integration, dict) and integration.get("source") == "custom"
        )

        # Debug log integration data for custom MCPs
        if is_custom:
            logger.info(
                f"Custom MCP integration data: id={integration.get('id')}, "
                f"name={integration.get('name')}, icon_url={integration.get('icon_url')}"
            )

        if is_custom:
            # Custom MCP - create subagent on-the-fly
            integration_id = integration.get("id")
            integration_name = integration.get("name", integration_id)

            if not user_id:
                return f"Error: {integration_name} requires authentication. Please sign in first."

            # Create subagent for custom MCP
            subagent_graph = await create_subagent_for_user(integration_id, user_id)
            if not subagent_graph:
                return f"Error: Failed to create subagent for {integration_name}"

            agent_name = f"custom_mcp_{integration_id}"

        elif hasattr(integration, "subagent_config") and integration.subagent_config:
            # Platform integration with subagent config
            subagent_cfg = integration.subagent_config
            agent_name = subagent_cfg.agent_name

            # Handle auth-required MCP integrations specially
            if (
                integration.managed_by == "mcp"
                and integration.mcp_config
                and integration.mcp_config.requires_auth
            ):
                if not user_id:
                    return f"Error: {agent_name} requires authentication. Please sign in first."

                # Check if user has connected this MCP integration
                token_store = MCPTokenStore(user_id=user_id)
                is_connected = await token_store.is_connected(integration.id)
                if not is_connected:
                    return (
                        f"Error: {agent_name} requires OAuth connection. "
                        f"Please connect {integration.name} first via settings."
                    )

                # Create subagent on-the-fly with user's tokens
                subagent_graph = await create_subagent_for_user(integration.id, user_id)
                if not subagent_graph:
                    return f"Error: Failed to create {agent_name} subagent"
            else:
                # Non-MCP or non-auth-required MCP integrations
                # Skip connection check for internal integrations (always available)
                if integration.managed_by not in ("mcp", "internal") and user_id:
                    error_message = await check_integration_connection(
                        integration.id, user_id
                    )
                    if error_message:
                        return error_message

                subagent_graph = await providers.aget(agent_name)
                if not subagent_graph:
                    return f"Error: {agent_name} not available"
        else:
            return f"Error: {subagent_id} is not configured as a subagent"

        # Get integration ID properly (dict for custom, object for platform)
        if is_custom:
            int_id = integration.get("id")
        else:
            int_id = integration.id

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

        subagent_runnable_config = build_agent_config(
            conversation_id=thread_id,
            user=user,
            user_time=user_time,
            thread_id=subagent_thread_id,
            base_configurable=configurable,
            agent_name=agent_name,
        )

        system_message = await create_subagent_system_message(
            integration_id=int_id,
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

        # Emit structured progress with integration ID for frontend icon display
        # Use integration_name for display, otherwise fallback to agent_name
        if is_custom:
            display_name = integration.get("name", int_id)
            handoff_icon_url = integration.get("icon_url")
        else:
            display_name = (
                integration.name
                if hasattr(integration, "name")
                else agent_name.replace("_", " ").title()
            )
            handoff_icon_url = None

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

        pending_tool_calls: dict[str, dict] = {}

        async for event in subagent_graph.astream(
            initial_state,
            stream_mode=["messages", "custom", "updates"],
            config=subagent_runnable_config,
        ):
            # Handle both 2-tuple and 3-tuple formats
            if len(event) == 2:
                stream_mode, payload = event
            else:
                continue

            # Capture complete args from updates stream
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
                writer(payload)
            elif stream_mode == "messages":
                chunk, metadata = payload

                if metadata.get("silent"):
                    continue

                if chunk and isinstance(chunk, AIMessageChunk):
                    # Emit tool progress with inputs (same as main agent)
                    if chunk.tool_calls:
                        for tool_call in chunk.tool_calls:
                            tc_id = tool_call.get("id")
                            if tc_id and tc_id not in pending_tool_calls:
                                # Pass icon_url, integration_id, and name for custom MCPs
                                if is_custom:
                                    custom_icon_url = integration.get("icon_url")
                                    custom_int_id = int_id
                                    custom_name = integration.get("name")
                                else:
                                    custom_icon_url = None
                                    custom_int_id = None
                                    custom_name = None
                                progress_data = await format_tool_progress(
                                    tool_call,
                                    icon_url=custom_icon_url,
                                    integration_id=custom_int_id,
                                    integration_name=custom_name,
                                )
                                if progress_data:
                                    writer(progress_data)
                                pending_tool_calls[tc_id] = {
                                    "name": tool_call.get("name"),
                                    "args": tool_call.get("args", {}),
                                }
                            elif tc_id:
                                pending_tool_calls[tc_id]["args"] = tool_call.get(
                                    "args", {}
                                )

                    content = str(chunk.content)
                    if content:
                        complete_message += content

                # Handle ToolMessage - emit inputs and outputs
                elif chunk and isinstance(chunk, ToolMessage):
                    tc_id = chunk.tool_call_id
                    # Emit tool_inputs with category and icon for frontend
                    if tc_id and tc_id in pending_tool_calls:
                        stored_call = pending_tool_calls[tc_id]
                        if stored_call.get("args"):
                            # Get icon_url for custom integrations
                            icon_url = None
                            if is_custom:
                                icon_url = integration.get("icon_url")
                            writer(
                                {
                                    "tool_inputs": {
                                        "tool_call_id": tc_id,
                                        "inputs": stored_call["args"],
                                        "tool_category": int_id,
                                        "icon_url": icon_url,
                                    }
                                }
                            )
                        del pending_tool_calls[tc_id]
                    # Emit tool_output
                    writer(
                        {
                            "tool_output": {
                                "tool_call_id": tc_id,
                                "output": chunk.content[:3000]
                                if isinstance(chunk.content, str)
                                else str(chunk.content)[:3000],
                            }
                        }
                    )

        return complete_message if complete_message else "Task completed"

    except Exception as e:
        logger.error(f"Error in handoff to {subagent_id}: {e}")
        return f"Error executing task: {str(e)}"
