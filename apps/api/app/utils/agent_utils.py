from collections.abc import Callable
from datetime import UTC, datetime
import json
from typing import Any, TypedDict, cast
from uuid import uuid4

from langchain_core.messages import ToolCall

from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.tools.core.registry import get_tool_registry
from app.db.mongodb.collections import integrations_collection
from app.decorators.caching import Cacheable
from app.models.chat_models import (
    MessageModel,
    ToolDataEntry,
    UpdateMessagesRequest,
    tool_fields,
)
from app.services.chat.chunks import extract_tool_data
from app.services.conversation_service import update_messages
from shared.py.wide_events import log

# Type for the stream_writer callable used across agent execution paths.
StreamWriterCallable = Callable[[dict[str, Any]], None]


class IntegrationMetadata(TypedDict, total=False):
    """Metadata for a custom MCP integration, used to decorate tool events."""

    icon_url: str | None
    integration_id: str | None
    name: str | None


def parse_subagent_id(subagent_id: str) -> tuple[str, str | None]:
    """Parse subagent ID from various formats and extract clean ID and display name.

    Handles:
      - 'subagent:Name [uuid]' -> ('uuid', 'Name')
      - 'subagent:id (Name)' -> ('id', 'Name')
      - 'subagent:id' -> ('id', None)
      - 'id' -> ('id', None)
    """
    clean = subagent_id.replace("subagent:", "").strip()

    if " [" in clean:
        name = clean.split(" [")[0].strip()
        clean_id = clean.split("[")[1].rstrip("]")
        return clean_id, name

    if " (" in clean:
        clean_id = clean.split(" (")[0].strip()
        name = clean.split("(")[1].rstrip(")")
        return clean_id, name

    return clean, None


@Cacheable(key_pattern="handoff_name:{clean_id}", ttl=3600)
async def _lookup_custom_integration_name(clean_id: str) -> str | None:
    """Look up custom integration name from MongoDB with caching."""
    custom = await integrations_collection.find_one(
        {"integration_id": {"$regex": f"^{clean_id}", "$options": "i"}}, {"name": 1}
    )
    return custom.get("name") if custom else None


async def _resolve_handoff_display_name(subagent_id: str) -> str:
    """Resolve human-readable display name for a subagent handoff."""
    clean_id, parsed_name = parse_subagent_id(subagent_id)

    if parsed_name:
        return parsed_name

    platform_subagent = get_subagent_by_id(clean_id)
    if platform_subagent:
        return platform_subagent.name

    cached_name = await _lookup_custom_integration_name(clean_id)
    if cached_name:
        return cached_name

    return clean_id.replace("_", " ").title()


def format_subagent_start_event(
    subagent_name: str,
    agent_type: str,
    subagent_id: str,
    icon_url: str | None = None,
    tool_category: str | None = None,
    parent_subagent_id: str | None = None,
) -> dict:
    """Format a subagent_start SSE payload."""
    payload: dict = {
        "subagent_id": subagent_id,
        "subagent_name": subagent_name,
        "agent_type": agent_type,
        "started_at": datetime.now(UTC).isoformat(),
    }
    if icon_url:
        payload["icon_url"] = icon_url
    if tool_category:
        payload["tool_category"] = tool_category
    if parent_subagent_id:
        payload["parent_subagent_id"] = parent_subagent_id
    return payload


def format_subagent_end_event(
    subagent_id: str,
    duration_ms: int,
    token_count: int | None = None,
) -> dict:
    """Format a subagent_end SSE payload."""
    return {
        "subagent_id": subagent_id,
        "duration_ms": duration_ms,
        "token_count": token_count,
    }


async def emit_subagent_tool_calls(
    stream_writer: StreamWriterCallable,
    subagent_id: str,
    tool_calls: list[ToolCall],
    user_id: str | None = None,
) -> None:
    """Emit tool_data events for each tool call made inside a spawned subagent.

    Called from SubagentMiddleware._execute_subagent before parallel tool
    invocation so the frontend can show tools as they are dispatched.

    Reuses ``format_tool_call_entry`` so categories, icons, and special-tool
    display names match the post-execution emission path exactly — without
    that, e.g. ``vfs_read`` would render with its raw tool name as the
    category (wrench icon) instead of ``filesystem`` (FolderFileStorageIcon).

    When ``user_id`` is provided, MCP tool calls resolve their integration
    metadata (icon, integration name) via the user's MCPClient — required
    after the cross-user-leak fix removed MCP tools from the global registry.
    """
    for tc in tool_calls:
        entry = await format_tool_call_entry(tc, user_id=user_id)
        if entry is None:
            continue
        stream_writer({"tool_data": {**entry, "subagent_id": subagent_id}})


async def format_tool_call_entry(
    tool_call: ToolCall,
    icon_url: str | None = None,
    integration_id: str | None = None,
    integration_name: str | None = None,
    user_id: str | None = None,
) -> dict | None:
    """Format tool call as tool_data entry for frontend streaming.

    Creates a unified tool_data entry that the frontend can directly append
    to the message's tool_data array. This is emitted once per tool call
    from the 'updates' stream when complete args are available.

    Args:
        tool_call: LangChain ToolCall object containing tool execution details
        icon_url: Optional icon URL for custom integrations
        integration_id: Optional integration ID to use as category (for custom MCPs)
        integration_name: Optional friendly name for display (e.g., 'Researcher')
        user_id: Optional user ID used to resolve MCP tool provenance via the
            user's MCPClient — required for MCP-tool icons / names after the
            cross-user-leak fix moved MCP tools out of the global registry.

    Returns:
        Dictionary in tool_data entry format with tool_name="tool_calls_data",
        or None if tool name is missing
    """
    tool_registry = await get_tool_registry()
    tool_name_raw = tool_call.get("name")
    if not tool_name_raw:
        return None

    is_core_tool = False  # set inside the non-special branch; safe default for short-circuits below

    # Special tools with custom display names and categories
    # Format: (category, display_name, show_category)
    special_tools = {
        "retrieve_tools": ("retrieve_tools", "Retrieving tools", False),
        "call_executor": ("executor", "Delegating to executor", False),
        "handoff": ("handoff", None, False),  # message will be set from args
        "spawn_subagent": ("spawn_subagent", "Spawning subagent", False),
        "plan_tasks": ("plan_tasks", "Planning tasks", True),
        "update_tasks": ("plan_tasks", "Updating tasks", True),
        "finish_task": ("finish_task", "Finishing task", False),
    }

    if tool_name_raw in special_tools:
        tool_category, tool_display_name, show_category = special_tools[tool_name_raw]

        if tool_name_raw == "handoff":
            args = tool_call.get("args", {})
            subagent_id = args.get("subagent_id", "subagent")
            display_name = await _resolve_handoff_display_name(subagent_id)
            tool_display_name = f"Handing off to {display_name}"
    else:
        # General tools (vfs_cmd, web_search_tool, tracked_todo helpers, etc.)
        # called inside an MCP subagent should keep their own category so the
        # frontend renders the right icon — not the subagent's integration
        # logo. Only fall back to integration_id when the tool has no known
        # core category (i.e. it's an MCP tool).
        registry_category = tool_registry.get_category_of_tool(tool_name_raw)
        is_core_tool = bool(
            registry_category
            and registry_category != "unknown"
            and not registry_category.startswith("mcp_")
        )

        # MCP tools no longer live in the global registry — resolve provenance
        # via the user's MCPClient when the caller didn't pre-supply it.
        if not integration_id and not is_core_tool and user_id:
            integration_id = await _resolve_mcp_integration_id(tool_name_raw, user_id)

        if integration_id and not is_core_tool:
            tool_category = integration_id
        else:
            tool_category = registry_category
            # Strip mcp_ prefix from MCP-namespaced categories.
            if tool_category and tool_category.startswith("mcp_"):
                tool_category = tool_category[4:]

        tool_display_name = tool_name_raw.replace("_", " ").title()
        show_category = True

        # When a core tool runs inside an MCP subagent, also drop the
        # integration's icon_url / display name so the secondary label
        # reflects the tool's true category instead of the subagent context.
        if integration_id and is_core_tool:
            icon_url = None
            integration_name = None

    timestamp = datetime.now(UTC).isoformat()

    # Look up mcp_ui metadata. Try the global registry first (covers platform
    # tools); fall back to MCPClient._tools for per-user MCP tools.
    mcp_ui: dict | None = None
    mcp_server_url: str | None = None
    try:
        registry_tools = tool_registry.get_all_tools_for_search()
        for registry_tool in registry_tools:
            if registry_tool.name == tool_name_raw:
                base_tool = registry_tool.tool
                tool_meta = getattr(base_tool, "metadata", None)
                if tool_meta and isinstance(tool_meta, dict):
                    mcp_ui = tool_meta.get("mcp_ui")
                    mcp_server_url = tool_meta.get("mcp_server_url")
                break
    except Exception:  # nosec B110
        pass

    if mcp_ui is None and user_id:
        mcp_ui, mcp_server_url = await _resolve_mcp_ui_metadata(tool_name_raw, user_id)

    # Lazy-fill icon/name for MCP tools the caller didn't pre-resolve.
    if integration_id and not is_core_tool and not icon_url and user_id:
        icon_url, integration_name = await _resolve_mcp_icon_name(integration_id)

    return {
        "tool_name": "tool_calls_data",
        "tool_category": tool_category or "",
        "data": {
            "tool_name": tool_name_raw,
            "tool_category": tool_category or "",
            "message": tool_display_name,
            "show_category": show_category,
            "tool_call_id": tool_call.get("id"),
            "inputs": tool_call.get("args", {}),
            "icon_url": icon_url,
            "integration_name": integration_name,
        },
        "timestamp": timestamp,
        "mcp_ui": mcp_ui,
        "mcp_server_url": mcp_server_url,
    }


async def _resolve_mcp_integration_id(tool_name: str, user_id: str) -> str | None:
    """Resolve which integration owns an MCP tool via the user's MCPClient.

    MCP tools no longer live in the global ToolRegistry — each MCPClient is
    the single source of truth. Returns None if the tool isn't an MCP tool
    or the user has no connected MCP that exposes it.
    """
    from app.services.mcp.mcp_client import (
        get_mcp_client,  # noqa: PLC0415  (lazy: avoid import cycle)
    )

    try:
        mcp_client = await get_mcp_client(user_id)
        return mcp_client.find_integration(tool_name)
    except Exception as e:
        log.warning(f"MCP integration lookup failed for {tool_name}: {e}")
        return None


async def _resolve_mcp_ui_metadata(tool_name: str, user_id: str) -> tuple[dict | None, str | None]:
    """Pull mcp_ui + mcp_server_url off the user's MCPClient tool object."""
    from app.services.mcp.mcp_client import get_mcp_client  # noqa: PLC0415

    try:
        mcp_client = await get_mcp_client(user_id)
        for tools in mcp_client._tools.values():
            for tool in tools:
                if tool.name == tool_name:
                    meta = getattr(tool, "metadata", None)
                    if meta and isinstance(meta, dict):
                        return meta.get("mcp_ui"), meta.get("mcp_server_url")
                    return None, None
    except Exception as e:
        log.warning(f"MCP UI metadata lookup failed for {tool_name}: {e}")
    return None, None


async def _resolve_mcp_icon_name(integration_id: str) -> tuple[str | None, str | None]:
    """Fetch (icon_url, integration_name) for an integration via Redis-cached Mongo."""
    from app.constants.cache import (  # noqa: PLC0415
        CUSTOM_INT_METADATA_CACHE_PREFIX,
        CUSTOM_INT_METADATA_TTL,
    )
    from app.db.redis import get_cache, set_cache  # noqa: PLC0415

    cache_key = f"{CUSTOM_INT_METADATA_CACHE_PREFIX}:{integration_id}"
    cached = await get_cache(cache_key)
    if cached:
        return cached.get("icon_url"), cached.get("integration_name")

    try:
        integration = await integrations_collection.find_one(
            {"integration_id": integration_id}, {"name": 1, "icon_url": 1}
        )
        if not integration:
            await set_cache(cache_key, {}, ttl=CUSTOM_INT_METADATA_TTL)
            return None, None
        metadata = {
            "icon_url": integration.get("icon_url"),
            "integration_id": integration_id,
            "integration_name": integration.get("name"),
        }
        await set_cache(cache_key, metadata, ttl=CUSTOM_INT_METADATA_TTL)
        return metadata["icon_url"], metadata["integration_name"]
    except Exception as e:
        log.warning(f"MCP icon/name lookup failed for {integration_id}: {e}")
        return None, None


def format_sse_response(content: str) -> str:
    """Format text content as Server-Sent Events (SSE) response.

    Wraps content in the standard SSE data format with JSON encoding
    for transmission to frontend clients via EventSource connections.

    Args:
        content: Text content to be streamed to the client

    Returns:
        SSE-formatted string with 'data:' prefix and proper line endings
    """
    return f"data: {json.dumps({'response': content})}\n\n"


def format_sse_data(data: dict) -> str:
    """Format structured data as Server-Sent Events (SSE) response.

    Converts dictionary data to JSON and wraps it in SSE format for
    streaming structured information like tool progress, errors, or
    custom events to frontend clients.

    Args:
        data: Dictionary containing structured data to stream

    Returns:
        SSE-formatted string with JSON-encoded data and proper line endings
    """
    return f"data: {json.dumps(data)}\n\n"


def process_custom_event_for_tools(payload) -> dict:
    """Extract and process tool execution data from custom LangGraph events.

    Safely processes custom event payloads from LangGraph streams to extract
    tool execution results and data. Handles serialization and delegates to
    the chat service for tool-specific data extraction.

    Args:
        payload: Raw event payload from LangGraph custom events

    Returns:
        Dictionary containing extracted tool data, or empty dict if
        extraction fails or no data is available
    """
    try:
        serialized = json.dumps(payload) if payload else "{}"
        new_data = extract_tool_data(serialized)
        return new_data if new_data else {}
    except Exception as e:
        log.error(f"Error extracting tool data: {e}")
        return {}


async def store_agent_progress(
    conversation_id: str, user_id: str, current_message: str, current_tool_data: dict
) -> None:
    """Store agent execution progress in real-time.

    Generic function for storing bot messages during agent execution.
    Works for any agent execution - workflows, normal chat, etc.
    Only stores messages that have meaningful content (message text or tool data).

    Args:
        conversation_id: Conversation ID for storage
        user_id: User ID for authorization
        current_message: Current accumulated LLM response
        current_tool_data: Current accumulated tool outputs (can contain both unified tool_data and legacy individual fields)
    """
    log.set(conversation_id=conversation_id, user_id=user_id)
    try:
        # Check if there's meaningful content
        has_tool_data = False
        if current_tool_data:
            # Check for unified tool_data format
            if current_tool_data.get("tool_data") or any(current_tool_data.values()):
                has_tool_data = True

        has_content = current_message.strip() or has_tool_data

        if not has_content:
            return  # Skip storing empty messages

        # Create bot message using same pattern as chat_service.py
        bot_message = MessageModel(
            type="bot",
            response=current_message,
            date=datetime.now(UTC).isoformat(),
            message_id=str(uuid4()),
        )

        # Handle tool data in unified format
        if current_tool_data:
            # If we have unified tool_data, use it directly
            if "tool_data" in current_tool_data:
                bot_message.tool_data = current_tool_data["tool_data"]
            else:
                # Legacy support: convert individual fields to unified format
                tool_data_entries = []
                timestamp = datetime.now(UTC).isoformat()

                # Convert individual tool fields to unified ToolDataEntry format using tool_fields list
                for field_name in tool_fields:
                    if (
                        field_name in current_tool_data
                        and current_tool_data[field_name] is not None
                    ):
                        tool_entry = {
                            "tool_name": field_name,
                            "data": current_tool_data[field_name],
                            "timestamp": timestamp,
                        }
                        tool_data_entries.append(tool_entry)

                if tool_data_entries:
                    bot_message.tool_data = cast(list[ToolDataEntry], tool_data_entries)

            # Handle follow_up_actions separately (it's a core field, not tool data)
            if "follow_up_actions" in current_tool_data:
                bot_message.follow_up_actions = current_tool_data["follow_up_actions"]

        # Store immediately using existing service
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=conversation_id,
                messages=[bot_message],
            ),
            user={"user_id": user_id},
        )

    except Exception as e:
        # Don't break agent execution for storage failures
        log.error(f"Failed to store agent progress: {e!s}")
