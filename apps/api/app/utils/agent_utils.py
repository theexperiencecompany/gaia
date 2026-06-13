from collections.abc import Callable
from datetime import UTC, datetime
import json
from typing import Any, TypedDict

from langchain_core.messages import ToolCall

from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.tools.core.registry import get_tool_registry
from app.constants.tool_labels import TOOL_DISPLAY_NAMES, humanize_tool_name
from app.db.mongodb.collections import integrations_collection
from app.decorators.caching import Cacheable
from app.services.chat.chunks import extract_tool_data
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

    Reuses ``format_tool_call_entry`` so categories, icons, and special-tool
    display names match the post-execution path; otherwise e.g. ``vfs_read``
    renders with its raw name as the category instead of ``filesystem``.

    With ``user_id``, MCP tool calls resolve their integration metadata via
    the user's MCPClient (MCP tools no longer live in the global registry).
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
    """Format a tool call as a tool_data entry for frontend streaming.

    Emitted once per tool call from the 'updates' stream when complete args
    are available; the frontend appends it to the message's tool_data array.

    Args:
        tool_call: LangChain ToolCall object.
        icon_url: Icon URL for custom integrations.
        integration_id: Integration ID to use as category (for custom MCPs).
        integration_name: Friendly display name (e.g. 'Researcher').
        user_id: Used to resolve MCP tool provenance via the user's MCPClient
            (MCP tools no longer live in the global registry).

    Returns:
        tool_data entry dict, or None if the tool name is missing.
    """
    tool_registry = await get_tool_registry()
    tool_name_raw = tool_call.get("name")
    if not tool_name_raw:
        return None

    is_core_tool = False  # set inside the non-special branch; safe default for short-circuits below

    # Special tools with custom display names and categories
    # Format: (category, display_name, show_category)
    special_tools = {
        "retrieve_tools": ("retrieve_tools", "Retrieve tools", False),
        "call_executor": ("executor", "Delegating to executor", False),
        "handoff": ("handoff", None, False),  # message will be set from args
        "spawn_subagent": ("spawn_subagent", "Spawn subagent", False),
        "wait_for_subagents": ("wait_for_subagents", "Wait for subagents", False),
        "plan_tasks": ("plan_tasks", "Plan tasks", False),
        "update_tasks": ("plan_tasks", "Update tasks", False),
        "finish_task": ("finish_task", "Finish task", False),
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

        tool_display_name = humanize_tool_name(tool_name_raw, tool_category)
        # show_category=False marks "the primary is a custom/curated label" (the
        # tool name isn't already in the primary text). The frontend uses this as
        # the single signal: the live LoadingIndicator drops the "Category:" prefix,
        # and the tool thread shows the raw tool name as the secondary line. When
        # uncurated, the primary IS the tool name, so the category is shown instead.
        show_category = tool_name_raw not in TOOL_DISPLAY_NAMES

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
    """Wrap text content as a JSON-encoded SSE ``data:`` line."""
    return f"data: {json.dumps({'response': content})}\n\n"


def format_sse_data(data: dict) -> str:
    """Wrap a dict as a JSON-encoded SSE ``data:`` line."""
    return f"data: {json.dumps(data)}\n\n"


def process_custom_event_for_tools(payload) -> dict:
    """Extract tool execution data from a custom LangGraph event payload.

    Returns the extracted tool data, or an empty dict on failure / no data.
    """
    try:
        serialized = json.dumps(payload) if payload else "{}"
        new_data = extract_tool_data(serialized)
        return new_data if new_data else {}
    except Exception as e:
        log.error(f"Error extracting tool data: {e}")
        return {}
