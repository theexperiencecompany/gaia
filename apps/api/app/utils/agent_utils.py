from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any, cast

from langchain_core.messages import ToolCall
from pydantic import BaseModel, ConfigDict, Field

from app.agents.tools.core.registry import UNKNOWN_TOOL_CATEGORY, ToolRegistry, get_tool_registry
from app.agents.tools.execute.unwrap import ExecuteCallArgs, unwrap_execute_call
from app.config.oauth_config import get_integration_by_id, get_integration_by_tool_slug
from app.constants.agents import INTERNAL_AGENT_TAG_PATTERN
from app.constants.browser import BROWSER_TOOL_CATEGORY
from app.constants.log_tags import LogTag
from app.constants.tool_labels import TOOL_DISPLAY_NAMES, humanize_tool_name
from app.db.repositories.integrations import integration_repository
from app.models.chat_models import ToolDataEntry
from app.models.oauth_models import OAuthIntegration
from app.models.stream_events import (
    ResponseFrame,
    SubagentEndPayload,
    SubagentStartPayload,
    ToolCallsDataEntry,
    ToolCallsDataEntryData,
)
from app.services.browser.captions import describe_action
from app.services.chat.chunks import extract_tool_data
from app.utils.stream_publishers import ExtractedToolData
from shared.py.wide_events import log

# Type for the stream_writer callable used across agent execution paths.
StreamWriterCallable = Callable[[dict[str, Any]], None]


class ToolCallView(BaseModel):
    """A LangChain ``ToolCall`` parsed once — the TypedDict is only readable by key.

    ``args`` is the LLM-authored argument bag: open per tool, never read here
    beyond forwarding it as the card's ``inputs``.
    """

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    args: dict[str, object] = Field(default_factory=dict)
    id: str | None = None


class ActivateIntegrationCallArgs(BaseModel):
    """The ``activate_integration`` tool's arguments, as far as the display path reads them."""

    model_config = ConfigDict(extra="ignore")

    integration_id: str | None = None


class IntegrationDisplayMetadata(BaseModel):
    """Icon, id and name for a custom integration's tool card.

    Redis-cached under two prefixes (handoff lookups by subagent id, MCP icon
    lookups by integration id); an all-``None`` instance is the cached negative
    result, written as ``{}``.
    """

    model_config = ConfigDict(extra="forbid")

    icon_url: str | None = None
    integration_id: str | None = None
    integration_name: str | None = None


class NodeMessagesUpdate(BaseModel):
    """One node's "updates" stream payload, read for the messages it wrote.

    ``object`` elements: the drivers narrow each to ``AIMessage`` themselves, so
    a node writing anything else (a tombstone, a message-like) is skipped, not fatal.
    """

    model_config = ConfigDict(extra="ignore")

    messages: list[object] = Field(default_factory=list)


class _McpToolMetadata(BaseModel):
    """The MCP keys the adapter stamps on a tool's ``metadata`` (see resilient_adapter)."""

    model_config = ConfigDict(extra="ignore")

    #: Forwarded to the client verbatim — whatever keys the adapter stamped.
    mcp_ui: dict[str, object] | None = None
    mcp_server_url: str | None = None


def strip_internal_agent_tags(text: str) -> str:
    """Remove internal channel tags (e.g. <executor_result>) an agent may echo into user text.

    Tags frame payloads for comms re-voicing and are never part of the user-facing reply; strip them as a hard backstop against a model parroting them, keeping only the framed text.
    """
    return INTERNAL_AGENT_TAG_PATTERN.sub("", text).strip()


@dataclass(slots=True, frozen=True)
class IntegrationMetadata:
    """Metadata for a custom MCP integration, used to decorate tool events."""

    icon_url: str | None = None
    integration_id: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class SubagentStartDetails:
    """The optional parts of a subagent_start payload."""

    icon_url: str | None = None
    tool_category: str | None = None
    parent_subagent_id: str | None = None


def format_subagent_start_event(
    subagent_name: str,
    agent_type: str,
    subagent_id: str,
    details: SubagentStartDetails | None = None,
    subagent: str | None = None,
) -> dict[str, object]:
    """Format a subagent_start SSE payload."""
    details = details or SubagentStartDetails()
    return SubagentStartPayload(
        subagent=subagent,
        subagent_id=subagent_id,
        subagent_name=subagent_name,
        agent_type=agent_type,
        started_at=datetime.now(UTC).isoformat(),
        icon_url=details.icon_url,
        tool_category=details.tool_category,
        parent_subagent_id=details.parent_subagent_id,
    ).model_dump(exclude_none=True)


def format_subagent_end_event(
    subagent_id: str,
    duration_ms: int,
    token_count: int | None = None,
) -> dict[str, object]:
    """Format a subagent_end SSE payload."""
    return SubagentEndPayload(
        subagent_id=subagent_id,
        duration_ms=duration_ms,
        token_count=token_count,
    ).model_dump()


async def format_tool_call_entry(
    tool_call: ToolCall,
    icon_url: str | None = None,
    integration_id: str | None = None,
    integration_name: str | None = None,
    user_id: str | None = None,
) -> ToolDataEntry | None:
    """Format a tool call as a tool_data entry for frontend streaming, or None if the tool name is missing.

    Args:
        user_id: resolves MCP tool provenance via the user's MCPClient (MCP tools no longer live in the global registry).
    """
    tool_registry = await get_tool_registry()
    call = ToolCallView.model_validate(tool_call)
    tool_name_raw = call.name
    if not tool_name_raw:
        return None

    # An execute-proxied call renders as its REAL tool (name/category/icon/inputs
    # from the unwrapped identity), else every card collapses to a generic
    # "Execute" row. The proxy's task_description becomes the card's label.
    call_args: dict[str, object] = tool_call.get("args", {}) or {}
    task_description: str | None = None  # pragma: no mutate — only read as truthy; "" equals None
    unwrapped_name, unwrapped_args = unwrap_execute_call(tool_name_raw, call_args)
    if unwrapped_name != tool_name_raw:
        # A renamed call is by construction an execute call, so these are its args.
        execute_args: ExecuteCallArgs = cast(ExecuteCallArgs, call_args)
        raw_description = execute_args.get("task_description")
        task_description = raw_description if isinstance(raw_description, str) else None
        tool_name_raw = unwrapped_name
        call_args = unwrapped_args

    is_core_tool = False  # set inside the non-special branch; safe default for short-circuits below

    if tool_name_raw in _SPECIAL_TOOLS:
        tool_category, tool_display_name, show_category = _SPECIAL_TOOLS[tool_name_raw]
        if tool_name_raw == "activate_integration" and not integration_id:
            # The card names the integration being activated, custom MCPs included.
            integration_id = ActivateIntegrationCallArgs.model_validate(call_args).integration_id
    else:
        tool_category, integration_id, is_core_tool = await _general_tool_category(
            tool_registry, tool_name_raw, integration_id, user_id
        )
        tool_display_name = humanize_tool_name(tool_name_raw, tool_category)
        # show_category=False means the primary label is curated (not the raw tool
        # name); the frontend uses this as the single signal to drop the "Category:"
        # prefix and show the raw tool name as the secondary line instead.
        show_category = tool_name_raw not in TOOL_DISPLAY_NAMES

        # A core tool inside a subagent shows its own category, not the subagent's.
        if is_core_tool:
            icon_url = None
            integration_name = None

    if task_description:
        # A curated, user-facing primary label — the thread shows the raw tool
        # name as the secondary line (same contract as TOOL_DISPLAY_NAMES).
        tool_display_name = task_description
        show_category = False

    timestamp = datetime.now(UTC).isoformat()

    # Look up mcp_ui metadata. Try the global registry first (covers platform
    # tools); fall back to MCPClient._tools for per-user MCP tools.
    mcp_ui, mcp_server_url = _registry_mcp_ui_metadata(tool_registry, tool_name_raw)

    if mcp_ui is None and user_id:
        mcp_ui, mcp_server_url = await _resolve_mcp_ui_metadata(tool_name_raw, user_id)

    if integration_id and not (icon_url and integration_name):
        known_icon, known_name = await _integration_display(integration_id)
        icon_url = icon_url or known_icon
        integration_name = integration_name or known_name

    # ToolCallsDataEntry declares exactly the ToolDataEntry keys this variant
    # carries, in the byte order the frontend parser expects — so its dump IS a
    # ToolDataEntry by construction (Type Safety item 12).
    return cast(
        ToolDataEntry,
        ToolCallsDataEntry(
            tool_name="tool_calls_data",
            tool_category=tool_category or "",
            data=ToolCallsDataEntryData(
                tool_name=tool_name_raw,
                tool_category=tool_category or "",
                message=tool_display_name,
                show_category=show_category,
                tool_call_id=call.id,
                inputs=call_args,
                icon_url=icon_url,
                integration_name=integration_name,
            ),
            timestamp=timestamp,
            mcp_ui=mcp_ui,
            mcp_server_url=mcp_server_url,
        ).model_dump(),
    )


def format_browser_action_entry(
    *,
    name: str,
    inputs: dict[str, object],
    target: str | None,
    subagent_id: str,
    tool_call_id: str,
) -> ToolDataEntry:
    """Format one browser-agent action as a tool_calls_data entry.

    The browser agent runs its own loop inside the browser_task tool, so its
    actions never pass through the graph's tool node and cannot be formatted by
    format_tool_call_entry. Tagging them with subagent_id is what nests them
    under the run's "Browser" group in the chat thread.
    """
    return cast(
        ToolDataEntry,
        {
            **ToolCallsDataEntry(
                tool_name="tool_calls_data",
                tool_category=BROWSER_TOOL_CATEGORY,
                data=ToolCallsDataEntryData(
                    tool_name=name,
                    tool_category=BROWSER_TOOL_CATEGORY,
                    message=describe_action(name, inputs, target),
                    show_category=False,
                    tool_call_id=tool_call_id,
                    inputs=inputs,
                    icon_url=None,
                    integration_name=None,
                ),
                timestamp=datetime.now(UTC).isoformat(),
                mcp_ui=None,
                mcp_server_url=None,
            ).model_dump(),
            "subagent_id": subagent_id,
        },
    )


# Special tools with custom display names and categories
# Format: (category, display_name, show_category)
_SPECIAL_TOOLS: dict[str, tuple[str, str, bool]] = {
    "retrieve_tools": ("retrieve_tools", "Retrieve tools", False),
    "call_executor": ("executor", "Delegating to executor", False),
    "cancel_executor": ("cancel_executor", "Cancelling the task", False),
    "browser_step_done": (BROWSER_TOOL_CATEGORY, "Continuing the browser task", False),
    "stop_browser_task": (BROWSER_TOOL_CATEGORY, "Stopping the browser task", False),
    "tell_browser_task": (BROWSER_TOOL_CATEGORY, "Telling the browser task", False),
    "spawn_subagent": ("spawn_subagent", "Spawn subagent", False),
    "activate_integration": ("integrations", "Activating integration", False),
    "plan_tasks": ("plan_tasks", "Plan tasks", False),
    # Synthetic card a replayed workflow run leads with — never a callable
    # tool. The playbooks category carries the icon the authoring tools use.
    "run_playbook": ("playbooks", "Run playbook", True),
    "update_tasks": ("plan_tasks", "Update tasks", False),
    "finish_task": ("finish_task", "Finish task", False),
}


def _owning_integration(tool_name: str, registry_category: str) -> OAuthIntegration | None:
    """Return the integration a tool belongs to, or None for a core tool.

    A Composio tool by its TOOLKIT_ACTION slug, registered or materialized on
    demand; an unauthenticated platform MCP's by the category named after it.
    """
    composio = get_integration_by_tool_slug(tool_name)
    if composio is not None:
        return composio
    mcp = get_integration_by_id(registry_category)
    return mcp if mcp is not None and mcp.managed_by == "mcp" else None


async def _general_tool_category(
    tool_registry: ToolRegistry,
    tool_name_raw: str,
    integration_id: str | None,
    user_id: str | None,
) -> tuple[str | None, str | None, bool]:
    """Return the general tool's category, its owning integration, and whether it is a core tool.

    A core tool (vfs_cmd, web_search_tool, ...) keeps its own category even inside
    a subagent; an integration's tool is categorised as that integration.
    """
    registry_category = tool_registry.get_category_of_tool(tool_name_raw)
    owner = _owning_integration(tool_name_raw, registry_category)
    if owner is not None:
        return owner.id, owner.id, False
    if registry_category and registry_category != UNKNOWN_TOOL_CATEGORY:
        return registry_category, None, True

    # MCP tools no longer live in the global registry — resolve provenance
    # via the user's MCPClient when the caller didn't pre-supply it.
    if not integration_id and user_id:
        integration_id = await _resolve_mcp_integration_id(tool_name_raw, user_id)
    return integration_id or registry_category, integration_id, False


def _registry_mcp_ui_metadata(
    tool_registry: ToolRegistry, tool_name_raw: str
) -> tuple[dict[str, object] | None, str | None]:
    """Return the mcp_ui metadata the global registry holds for a tool, if any."""
    mcp_ui: dict[str, object] | None = None
    mcp_server_url: str | None = None
    try:
        registry_tools = tool_registry.get_all_tools_for_search()
        for registry_tool in registry_tools:
            if registry_tool.name == tool_name_raw:
                base_tool = registry_tool.tool
                tool_meta = getattr(base_tool, "metadata", None)
                if tool_meta and isinstance(tool_meta, dict):
                    mcp_meta = _McpToolMetadata.model_validate(tool_meta)
                    mcp_ui = mcp_meta.mcp_ui
                    mcp_server_url = mcp_meta.mcp_server_url
                break
    except Exception as registry_error:
        # Recoverable via the per-user MCPClient fallback below, but must not be
        # silent: an outage here strips the UI metadata from every platform tool.
        log.debug(
            f"{LogTag.AGENT} Tool registry lookup failed for mcp_ui metadata",
            error=str(registry_error),
            error_type=type(registry_error).__name__,
        )
    return mcp_ui, mcp_server_url


async def _resolve_mcp_integration_id(tool_name: str, user_id: str) -> str | None:
    """Resolve which integration owns an MCP tool via the user's MCPClient.

    MCP tools no longer live in the global ToolRegistry — each MCPClient is
    the single source of truth. Returns None if the tool isn't an MCP tool
    or the user has no connected MCP that exposes it.
    """
    from app.services.mcp.mcp_client import (
        get_mcp_client,
    )

    try:
        mcp_client = await get_mcp_client(user_id)
        return mcp_client.find_integration(tool_name)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} MCP integration lookup failed for",
            tool_name=tool_name,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return None


async def _resolve_mcp_ui_metadata(
    tool_name: str, user_id: str
) -> tuple[dict[str, object] | None, str | None]:
    """Pull mcp_ui + mcp_server_url off the user's MCPClient tool object."""
    from app.services.mcp.mcp_client import get_mcp_client

    try:
        mcp_client = await get_mcp_client(user_id)
        for tools in mcp_client._tools.values():
            for tool in tools:
                if tool.name == tool_name:
                    meta = getattr(tool, "metadata", None)
                    if meta and isinstance(meta, dict):
                        mcp_meta = _McpToolMetadata.model_validate(meta)
                        return mcp_meta.mcp_ui, mcp_meta.mcp_server_url
                    return None, None
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} MCP UI metadata lookup failed for",
            tool_name=tool_name,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
    return None, None


async def _integration_display(integration_id: str) -> tuple[str | None, str | None]:
    """Return (icon_url, name) for a platform integration, or a custom one via Redis-cached Mongo."""
    platform = get_integration_by_id(integration_id)
    if platform is not None:
        return platform.icon_url, platform.name
    from app.constants.cache import (
        CUSTOM_INT_METADATA_CACHE_PREFIX,
        CUSTOM_INT_METADATA_TTL,
    )
    from app.db.redis import get_cache, set_cache

    cache_key = f"{CUSTOM_INT_METADATA_CACHE_PREFIX}:{integration_id}"
    cached = await get_cache(cache_key, IntegrationDisplayMetadata)
    if cached:
        return cached.icon_url, cached.integration_name

    try:
        integration = await integration_repository.get(integration_id)
        if not integration:
            await set_cache(cache_key, {}, ttl=CUSTOM_INT_METADATA_TTL)
            return None, None
        metadata = IntegrationDisplayMetadata(
            icon_url=integration.icon_url,
            integration_id=integration_id,
            integration_name=integration.name,
        )
        await set_cache(cache_key, metadata, ttl=CUSTOM_INT_METADATA_TTL)
        return metadata.icon_url, metadata.integration_name
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} MCP icon/name lookup failed for",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None, None


def format_sse_response(content: str) -> str:
    """Wrap text content as a JSON-encoded SSE data: line."""
    return f"data: {json.dumps(ResponseFrame(response=content).model_dump())}\n\n"


def format_sse_data(data: Mapping[str, object]) -> str:
    """Wrap a mapping as a JSON-encoded SSE data: line."""
    return f"data: {json.dumps(data)}\n\n"


def process_custom_event_for_tools(payload: Mapping[str, object] | None) -> ExtractedToolData:
    """Extract tool execution data from a custom LangGraph event payload.

    Returns the extracted tool data, empty on failure / no data.
    """
    try:
        serialized = json.dumps(payload) if payload else "{}"
        return ExtractedToolData.model_validate(extract_tool_data(serialized) or {})
    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Error extracting tool data", error=str(e), error_type=type(e).__name__
        )
        return ExtractedToolData()
