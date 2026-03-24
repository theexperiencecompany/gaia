"""Core agent helper functions for LangGraph execution and configuration.

Provides essential building blocks for agent execution including configuration
building, state initialization, and graph execution in both streaming and silent modes.

These functions are tightly coupled to agent-specific logic and LangGraph execution.
"""

import json
import re
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.messages import AIMessageChunk, ToolMessage
from langsmith import traceable
from opik.integrations.langchain import OpikTracer
from posthog.ai.langchain import CallbackHandler as PostHogCallbackHandler

from app.agents.tools.core.registry import get_tool_registry
from app.config.oauth_config import OAUTH_INTEGRATIONS
from shared.py.wide_events import log
from app.config.settings import settings
from app.constants.cache import (
    CUSTOM_INT_METADATA_CACHE_PREFIX,
    CUSTOM_INT_METADATA_TTL,
    HANDOFF_METADATA_CACHE_PREFIX,
)
from app.constants.llm import (
    AGENT_RECURSION_LIMIT,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
)
from app.core.lazy_loader import providers
from app.core.stream_manager import stream_manager
from app.db.mongodb.collections import integrations_collection
from app.db.redis import get_cache, set_cache
from app.models.models_models import ModelConfig
from app.services.mcp.mcp_resource_fetcher import fetch_mcp_ui_resource
from app.utils.agent_utils import (
    format_sse_data,
    format_sse_response,
    format_tool_call_entry,
    parse_subagent_id,
    process_custom_event_for_tools,
)


async def get_custom_integration_metadata(tool_name: str, user_id: str) -> dict:
    """Look up icon_url, integration_id, integration_name for custom MCP tools.

    Uses Redis cache to avoid repeated MongoDB queries during a conversation.
    Cache is keyed by integration_id (not tool_name) since multiple tools share
    the same integration metadata.

    Args:
        tool_name: Name of the tool being called
        user_id: User ID for MCP category resolution

    Returns:
        Dict with icon_url, integration_id, integration_name if found,
        empty dict otherwise
    """

    tool_registry = await get_tool_registry()
    tool_category = tool_registry.get_category_of_tool(tool_name)

    if not tool_category:
        return {}

    # Extract integration_id from MCP category
    # Category format: mcp_{integration_id} or mcp_{integration_id}_{user_id}
    #
    # Format assumptions for distinguishing integration_id from user_id suffix:
    # - User IDs are UUIDs with dashes (e.g., 550e8400-e29b-41d4-a716-446655440000)
    # - Custom integration IDs have hex suffixes WITHOUT dashes (e.g., custom_reposearch_6966a2fb964b5991c13ab887)
    #
    # This logic is fragile if:
    # - UUID formats change to not include dashes
    # - Custom IDs start using dashes
    # A more robust approach would use a consistent delimiter or explicit marker.
    if not tool_category.startswith("mcp_"):
        return {}

    without_prefix = tool_category[4:]
    parts = without_prefix.rsplit("_", 1)
    # Only strip suffix if it looks like a UUID (contains dashes and is ~36 chars)
    # This is more specific than just checking for dashes
    if len(parts) == 2 and "-" in parts[-1] and len(parts[-1]) >= 32:
        # Last part is likely a user ID (UUID with dashes)
        integration_id = parts[0]
    else:
        integration_id = without_prefix

    # Check Redis cache first
    cache_key = f"{CUSTOM_INT_METADATA_CACHE_PREFIX}:{integration_id}"
    cached = await get_cache(cache_key)
    if cached:
        return cached

    # Cache miss - query MongoDB
    try:
        integration = await integrations_collection.find_one(
            {"integration_id": integration_id}, {"name": 1, "icon_url": 1}
        )

        if not integration:
            # Cache negative result too (empty dict)
            await set_cache(cache_key, {}, ttl=CUSTOM_INT_METADATA_TTL)
            return {}

        metadata = {
            "icon_url": integration.get("icon_url"),
            "integration_id": integration_id,
            "integration_name": integration.get("name"),
        }

        # Cache for 1 hour
        await set_cache(cache_key, metadata, ttl=CUSTOM_INT_METADATA_TTL)
        return metadata

    except Exception as e:
        log.warning(f"Failed to lookup custom integration metadata: {e}")
        return {}


async def get_handoff_metadata(subagent_id: str) -> dict:
    """Look up icon_url, integration_id, integration_name for handoff subagents.

    Checks both platform integrations (in-memory) and custom MCPs (MongoDB/Redis).
    Uses Redis cache for custom MCPs to avoid repeated DB queries.

    Args:
        subagent_id: The subagent ID from handoff tool args

    Returns:
        Dict with icon_url, integration_id, integration_name if found,
        empty dict otherwise
    """

    clean_id, _ = parse_subagent_id(subagent_id)
    clean_id = clean_id.lower()

    # Check platform integrations first (in-memory, no caching needed)
    for integ in OAUTH_INTEGRATIONS:
        if integ.id.lower() == clean_id or (
            integ.short_name and integ.short_name.lower() == clean_id
        ):
            if integ.subagent_config and integ.subagent_config.has_subagent:
                log.set(integration_type="platform")
                return {
                    "icon_url": None,  # Platform integrations use category-based icons
                    "integration_id": integ.id,
                    "integration_name": integ.name,
                }

    # Check Redis cache for custom integrations
    cache_key = f"{HANDOFF_METADATA_CACHE_PREFIX}:{clean_id}"
    cached = await get_cache(cache_key)
    if cached is not None:
        return cached if cached else {}

    # Escape regex metacharacters for safety
    escaped_id = re.escape(clean_id)

    # Query MongoDB to find the integration by ID or name.
    # No source filter - we need to find ANY integration (custom OR public).
    # Public integrations created by OTHER users also need metadata lookup.
    try:
        custom = await integrations_collection.find_one(
            {
                "$or": [
                    {"integration_id": {"$regex": f"^{escaped_id}", "$options": "i"}},
                    {"name": {"$regex": f"^{escaped_id}$", "$options": "i"}},
                ],
            },
            {"name": 1, "icon_url": 1, "integration_id": 1},
        )

        if not custom:
            # Cache negative result
            await set_cache(cache_key, {}, ttl=CUSTOM_INT_METADATA_TTL)
            return {}

        metadata = {
            "icon_url": custom.get("icon_url"),
            "integration_id": custom.get("integration_id"),
            "integration_name": custom.get("name"),
        }

        log.set(integration_type="custom")
        await set_cache(cache_key, metadata, ttl=CUSTOM_INT_METADATA_TTL)
        return metadata

    except Exception as e:
        log.warning(f"Failed to lookup handoff metadata: {e}")
        return {}


def _extract_timezone_offset(user_time: datetime) -> str:
    """
    Extract timezone offset string from a datetime object.

    Returns the offset as a string like "+05:30" or "-08:00".
    Falls back to "+00:00" (UTC) if the datetime has no timezone info.

    Args:
        user_time: Datetime object (preferably timezone-aware)

    Returns:
        Timezone offset string (e.g., "+05:30", "-08:00", "+00:00")
    """
    if user_time.tzinfo is None:
        return "+00:00"

    # Get the UTC offset as a timedelta
    offset = user_time.utcoffset()
    if offset is None:
        return "+00:00"

    # Convert to hours and minutes
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60

    return f"{sign}{hours:02d}:{minutes:02d}"


def build_agent_config(
    conversation_id: str,
    user: dict,
    user_time: datetime,
    agent_name: str,
    user_model_config: Optional[ModelConfig] = None,
    usage_metadata_callback: Optional[UsageMetadataCallbackHandler] = None,
    thread_id: Optional[str] = None,
    base_configurable: Optional[dict] = None,
    selected_tool: Optional[str] = None,
    tool_category: Optional[str] = None,
    subagent_id: Optional[str] = None,
    vfs_session_id: Optional[str] = None,
) -> dict:
    """Build configuration for graph execution with optional authentication tokens.

    Creates a comprehensive configuration object for LangGraph execution that includes
    user context, model settings, authentication tokens, and execution parameters.

    Args:
        conversation_id: Unique identifier for the conversation thread
        user: User information dictionary containing user_id and email
        user_time: Current datetime for the user's timezone
        user_model_config: Optional model configuration with provider and token limits
        thread_id: Optional override for thread_id (defaults to conversation_id)
        base_configurable: Optional base configurable to inherit from (for child agents)
        selected_tool: Optional tool name selected via slash command
        tool_category: Optional category of the selected tool
        subagent_id: Optional subagent ID for skill learning (e.g., "twitter", "github")
        vfs_session_id: Shared VFS session ID that stays constant across the executor
            and all handoff subagents it spawns. All agents in the chain resolve VFS
            paths relative to the executor workspace using this ID. When provided via
            base_configurable it is inherited automatically.

    Returns:
        Configuration dictionary formatted for LangGraph execution with configurable
        parameters, metadata, and recursion limits
    """

    callbacks: list[BaseCallbackHandler] = []

    # Add OpikTracer in production, or in development only if configured
    # This prevents cluttered error logs when Opik isn't set up locally
    is_opik_configured = settings.OPIK_API_KEY and settings.OPIK_WORKSPACE
    if settings.ENV == "production" or is_opik_configured:
        callbacks.append(
            OpikTracer(
                tags=["langchain", settings.ENV],
                thread_id=conversation_id,
                metadata={
                    "user_id": user.get("user_id"),
                    "conversation_id": conversation_id,
                    "agent_name": agent_name,
                },
                project_name="GAIA",
            )
        )
    posthog_client = providers.get("posthog")

    if posthog_client is not None:
        callbacks.append(
            PostHogCallbackHandler(
                client=posthog_client,
                distinct_id=user.get("user_id"),
                properties={
                    "conversation_id": conversation_id,
                    "agent_name": agent_name,
                },
                privacy_mode=False,
            ),
        )

    if usage_metadata_callback:
        callbacks.append(usage_metadata_callback)

    model_name = (
        user_model_config.provider_model_name
        if user_model_config
        else DEFAULT_MODEL_NAME
    )
    provider_name = (
        user_model_config.inference_provider.value
        if user_model_config
        else DEFAULT_LLM_PROVIDER
    )
    max_tokens = (
        user_model_config.max_tokens if user_model_config else DEFAULT_MAX_TOKENS
    )

    log.set(model_config_source="user_selected" if user_model_config else "default")

    # Cherry-pick specific keys from base_configurable if provided
    # Only inherit model config and user context, not LangChain internal state
    if base_configurable:
        # Inherit model config from parent if not overridden
        provider_name = base_configurable.get("provider", provider_name)
        max_tokens = base_configurable.get("max_tokens", max_tokens)
        model_name = base_configurable.get("model_name", model_name)
        selected_tool = selected_tool or base_configurable.get("selected_tool")
        tool_category = tool_category or base_configurable.get("tool_category")
        subagent_id = subagent_id or base_configurable.get("subagent_id")
        vfs_session_id = vfs_session_id or base_configurable.get("vfs_session_id")

    configurable = {
        "thread_id": thread_id or conversation_id,
        "user_id": user.get("user_id"),
        "email": user.get("email"),
        "user_name": user.get("name", ""),
        "user_time": user_time.isoformat(),
        "user_timezone": _extract_timezone_offset(user_time),
        "provider": provider_name,
        "max_tokens": max_tokens,
        "model_name": model_name,
        "model": model_name,
        "selected_tool": selected_tool,
        "tool_category": tool_category,
        "subagent_id": subagent_id,
        "vfs_session_id": vfs_session_id,
    }

    config = {
        "configurable": configurable,
        "recursion_limit": AGENT_RECURSION_LIMIT,
        "metadata": {"user_id": user.get("user_id")},
        "callbacks": callbacks,
        "agent_name": agent_name,
    }

    return config


def build_initial_state(
    request,
    user_id: str,
    conversation_id: str,
    history,
    trigger_context: Optional[dict] = None,
) -> dict:
    """Construct initial state dictionary for LangGraph execution.

    Builds the starting state containing all necessary context for the agent
    including user query, conversation history, tool selections, and optional
    workflow trigger context.

    Args:
        request: Message request object containing user message and selections
        user_id: Unique identifier for the user
        conversation_id: Unique identifier for the conversation thread
        history: List of previous messages in LangChain format
        trigger_context: Optional context data from workflow triggers

    Returns:
        State dictionary with query, messages, datetime, user context, and
        selected tools/workflows for graph processing
    """
    state = {
        "query": request.message,
        "messages": history,
        "current_datetime": datetime.now(timezone.utc).isoformat(),
        "mem0_user_id": user_id,
        "conversation_id": conversation_id,
        "selected_tool": request.selectedTool,
        "selected_workflow": request.selectedWorkflow,
        "selected_calendar_event": request.selectedCalendarEvent,
    }

    if trigger_context:
        state["trigger_context"] = trigger_context

    return state


@traceable(run_type="llm", name="Call Agent Silent")
async def execute_graph_silent(
    graph,
    initial_state: dict,
    config: dict,
) -> tuple[str, dict]:
    """Execute LangGraph in silent mode with real-time progress storage.

    Runs the agent graph asynchronously and accumulates all results including
    the complete message content and extracted tool data. Used for background
    processing and workflow triggers where real-time streaming is not needed.

    Stores intermediate messages and tool outputs as they happen during execution,
    using the same storage patterns as normal chat.

    Args:
        graph: LangGraph instance to execute
        initial_state: Starting state dictionary with query and context
        config: Configuration dictionary with user context and settings

    Returns:
        Tuple containing:
        - complete_message: Full response text accumulated from all chunks
        - tool_data: Dictionary of extracted tool execution data and results
    """
    complete_message = ""
    tool_data: dict = {"tool_data": []}
    todo_progress_accumulated: dict = {}  # Accumulate todo_progress by source

    # Track tool calls to avoid duplicate emissions (same as streaming)
    emitted_tool_calls: set[str] = set()

    # Get user_id for metadata lookup (not for storage - caller handles that)
    user_id = config.get("configurable", {}).get("user_id")

    async for event in graph.astream(
        initial_state,
        stream_mode=["messages", "custom", "updates"],
        config=config,
        subgraphs=True,
    ):
        ns, stream_mode, payload = event

        # Process "updates" events - same logic as execute_graph_streaming
        if stream_mode == "updates":
            for node_name, state_update in payload.items():
                if isinstance(state_update, dict) and "messages" in state_update:
                    for msg in state_update["messages"]:
                        if not hasattr(msg, "tool_calls") or not msg.tool_calls:
                            continue
                        for tc in msg.tool_calls:
                            tc_id = tc.get("id")
                            if not tc_id or tc_id in emitted_tool_calls:
                                continue

                            # Look up metadata based on tool type
                            tool_name = tc.get("name")
                            tool_metadata = {}

                            # TODO(remove): PR492/CodeRabbit - todo tools already stream todo_progress; suppress tool_data noise.
                            # Safe: doesn't affect agent state; only avoids redundant UI events.
                            if tool_name in {"plan_tasks", "update_tasks"}:
                                continue

                            if tool_name == "handoff":
                                args = tc.get("args", {})
                                subagent_id = args.get("subagent_id", "")
                                if subagent_id:
                                    tool_metadata = await get_handoff_metadata(
                                        subagent_id
                                    )
                            elif tool_name and user_id:
                                tool_metadata = await get_custom_integration_metadata(
                                    tool_name, user_id
                                )

                            # Format tool_data entry (same as streaming)
                            tool_entry = await format_tool_call_entry(
                                tc,
                                icon_url=tool_metadata.get("icon_url"),
                                integration_id=tool_metadata.get("integration_id"),
                                integration_name=tool_metadata.get("integration_name"),
                            )
                            if tool_entry:
                                tool_data["tool_data"].append(tool_entry)
                                emitted_tool_calls.add(tc_id)
            continue

        if stream_mode == "messages":
            chunk, metadata = payload

            if metadata.get("silent"):
                continue  # Skip silent chunks (e.g. follow-up actions generation)

            if chunk and isinstance(chunk, AIMessageChunk):
                content = chunk.text if hasattr(chunk, "text") else str(chunk.content)
                if content and metadata.get("agent_name") == "comms_agent":
                    complete_message += content

        elif stream_mode == "custom":
            # Accumulate todo_progress for persistence (payload is a dict here)
            if isinstance(payload, dict) and "todo_progress" in payload:
                snapshot = payload["todo_progress"]
                source = snapshot.get("source", "executor")
                todo_progress_accumulated[source] = snapshot

            new_data = process_custom_event_for_tools(payload)
            if new_data:
                # Merge custom event tool_data into our array
                if "tool_data" in new_data:
                    for entry in new_data["tool_data"]:
                        tool_data["tool_data"].append(entry)
                # Always merge non-tool_data keys (follow_up_actions, etc.)
                for key, value in new_data.items():
                    if key != "tool_data":
                        tool_data[key] = value

    # Inject accumulated todo_progress as a single tool_data entry
    if todo_progress_accumulated:
        tool_data["tool_data"].append(
            {
                "tool_name": "todo_progress",
                "data": todo_progress_accumulated,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    return complete_message, tool_data


@traceable(run_type="llm", name="Call Agent")
async def execute_graph_streaming(
    graph,
    initial_state: dict,
    config: dict,
) -> AsyncGenerator[str, None]:
    """Execute LangGraph in streaming mode with real-time output.

    Runs the agent graph and yields Server-Sent Events (SSE) formatted updates
    as they occur. Handles both message content streaming and tool execution.

    Supports cancellation via stream_id in config - when cancelled via
    stream_manager, streaming stops gracefully.

    Args:
        graph: LangGraph instance to execute
        initial_state: Starting state dictionary with query and context
        config: Configuration dictionary with user context and settings

    Yields:
        SSE-formatted strings containing:
        - Real-time message content as it's generated
        - Tool data entries (tool_data) with complete inputs
        - Tool outputs (tool_output) when tools complete
        - Custom events from tool executions
        - Final completion marker and accumulated message

    Stream Event Flow:
        LangGraph emits events in 3 stream modes:

        1. "updates" - State changes after each node execution
           Contains AIMessage.tool_calls with complete args.
           We emit tool_data entries here (frontend shows loading state).

        2. "messages" - Individual message chunks
           AIMessageChunk: streaming text content
           ToolMessage: tool execution results -> emit tool_output

        3. "custom" - Application-specific events from tools
           Progress messages, errors, custom data.
           Forwarded to frontend as-is.
    """
    complete_message = ""
    stream_id = config.get("configurable", {}).get("stream_id")
    user_id = config.get("configurable", {}).get("user_id")

    # Track tool calls to avoid duplicate emissions
    emitted_tool_calls: set[str] = set()
    # Buffer MCP App UI metadata by tool_call_id for deferred emission
    # We detect UI metadata in "updates" but emit the mcp_app event in "messages"
    # when the ToolMessage arrives with the actual result.
    pending_mcp_apps: dict[str, dict] = {}

    async for event in graph.astream(
        initial_state,
        stream_mode=["messages", "custom", "updates"],
        config=config,
        subgraphs=True,
    ):
        # Check for cancellation at each event
        if stream_id and await stream_manager.is_cancelled(stream_id):
            yield f"nostream: {json.dumps({'complete_message': complete_message, 'cancelled': True})}"
            yield "data: [DONE]\n\n"
            return

        # Parse event tuple - handle both 2-tuple and 3-tuple (subgraphs=True)
        if len(event) == 3:
            ns, stream_mode, payload = event
        elif len(event) == 2:
            stream_mode, payload = event
        else:
            continue

        if stream_mode == "updates":
            for node_name, state_update in payload.items():
                # Process tool entries with metadata lookup
                if isinstance(state_update, dict) and "messages" in state_update:
                    for msg in state_update["messages"]:
                        if not hasattr(msg, "tool_calls") or not msg.tool_calls:
                            continue
                        for tc in msg.tool_calls:
                            tc_id = tc.get("id")
                            if not tc_id or tc_id in emitted_tool_calls:
                                continue

                            # Look up metadata based on tool type
                            tool_name = tc.get("name")
                            tool_metadata = {}

                            if tool_name == "handoff":
                                args = tc.get("args", {})
                                subagent_id = args.get("subagent_id", "")
                                if subagent_id:
                                    tool_metadata = await get_handoff_metadata(
                                        subagent_id
                                    )
                            elif tool_name and user_id:
                                tool_metadata = await get_custom_integration_metadata(
                                    tool_name, user_id
                                )

                            # Format and emit tool_data entry
                            tool_entry = await format_tool_call_entry(
                                tc,
                                icon_url=tool_metadata.get("icon_url"),
                                integration_id=tool_metadata.get("integration_id"),
                                integration_name=tool_metadata.get("integration_name"),
                            )
                            if tool_entry:
                                yield format_sse_data({"tool_data": tool_entry})
                                emitted_tool_calls.add(tc_id)

                                # Buffer MCP App UI metadata for deferred emission
                                # The actual mcp_app event is emitted when the
                                # ToolMessage arrives with the tool result.
                                if (
                                    tool_entry.get("tool_name") == "tool_calls_data"
                                    and tool_entry.get("mcp_ui")
                                    and tool_entry["mcp_ui"].get("resource_uri")
                                ):
                                    tc_id_for_app = tool_entry["data"].get(
                                        "tool_call_id", ""
                                    )
                                    if tc_id_for_app:
                                        pending_mcp_apps[tc_id_for_app] = {
                                            "tool_category": tool_entry.get(
                                                "tool_category", ""
                                            ),
                                            "tool_name": tool_entry["data"].get(
                                                "tool_name", ""
                                            ),
                                            "server_url": tool_entry.get(
                                                "mcp_server_url", ""
                                            ),
                                            "mcp_ui": tool_entry["mcp_ui"],
                                            "timestamp": tool_entry.get("timestamp"),
                                            "tool_arguments": tool_entry["data"].get(
                                                "inputs", {}
                                            ),
                                        }
            continue

        if stream_mode == "messages":
            chunk, metadata = payload
            if metadata.get("silent"):
                continue

            # Stream AI response content (only from comms_agent to avoid duplication)
            if chunk and isinstance(chunk, AIMessageChunk):
                content = chunk.text
                if content and metadata.get("agent_name") == "comms_agent":
                    yield format_sse_response(content)
                    complete_message += content

            # Emit tool_output when ToolMessage arrives
            elif chunk and isinstance(chunk, ToolMessage):
                # TODO(remove): PR492/CodeRabbit - todo tools already stream todo_progress; suppress tool_output noise.
                # Safe: doesn't affect agent state; only avoids redundant UI events.
                if getattr(chunk, "name", None) in {
                    "plan_tasks",
                    "update_tasks",
                } or chunk.additional_kwargs.get("todo_tool", False):
                    continue
                tool_result_payload = chunk.content
                try:
                    json.dumps(tool_result_payload)
                except TypeError:
                    if hasattr(tool_result_payload, "model_dump"):
                        tool_result_payload = tool_result_payload.model_dump()
                    elif hasattr(tool_result_payload, "__dict__"):
                        tool_result_payload = dict(tool_result_payload.__dict__)
                    else:
                        tool_result_payload = str(tool_result_payload)
                output = (
                    chunk.content[:3000]
                    if isinstance(chunk.content, str)
                    else str(chunk.content)[:3000]
                )
                yield format_sse_data(
                    {
                        "tool_output": {
                            "tool_call_id": chunk.tool_call_id,
                            "output": output,
                        }
                    }
                )

                # Emit deferred mcp_app event now that tool result is available
                app_meta = pending_mcp_apps.pop(chunk.tool_call_id, None)
                if app_meta:
                    try:
                        ui_resource = await fetch_mcp_ui_resource(
                            server_url=app_meta["server_url"],
                            resource_uri=app_meta["mcp_ui"]["resource_uri"],
                            user_id=user_id or "",
                        )
                        html_content = (
                            ui_resource.get("html")
                            if isinstance(ui_resource, dict)
                            else None
                        )
                        if html_content:
                            content_csp = (
                                ui_resource.get("csp")
                                if isinstance(ui_resource, dict)
                                else None
                            )
                            content_permissions = (
                                ui_resource.get("permissions")
                                if isinstance(ui_resource, dict)
                                else None
                            )
                            yield format_sse_data(
                                {
                                    "tool_data": {
                                        "tool_name": "mcp_app",
                                        "tool_category": app_meta["tool_category"],
                                        "data": {
                                            "tool_call_id": chunk.tool_call_id,
                                            "tool_name": app_meta["tool_name"],
                                            "server_url": app_meta["server_url"],
                                            "resource_uri": app_meta["mcp_ui"][
                                                "resource_uri"
                                            ],
                                            "html_content": html_content,
                                            "tool_result": tool_result_payload,
                                            "csp": content_csp
                                            if content_csp is not None
                                            else app_meta["mcp_ui"].get("csp"),
                                            "permissions": content_permissions
                                            if content_permissions is not None
                                            else app_meta["mcp_ui"].get(
                                                "permissions", []
                                            ),
                                            "tool_arguments": app_meta.get(
                                                "tool_arguments", {}
                                            ),
                                        },
                                        "timestamp": app_meta["timestamp"],
                                    }
                                }
                            )
                    except Exception as _e:
                        log.warning(f"Failed to emit mcp_app event: {_e}")
            continue

        if stream_mode == "custom":
            yield f"data: {json.dumps(payload)}\n\n"

            # Intercept subagent tool_data events for MCP App detection.
            # Custom MCP tools execute inside subagents and their events
            # arrive here as "custom" stream events, not "updates"/"messages".
            if isinstance(payload, dict) and "tool_data" in payload:
                sub_entry = payload["tool_data"]
                if (
                    isinstance(sub_entry, dict)
                    and sub_entry.get("tool_name") == "tool_calls_data"
                    and sub_entry.get("mcp_ui")
                    and sub_entry["mcp_ui"].get("resource_uri")
                ):
                    tc_id_for_app = sub_entry.get("data", {}).get("tool_call_id", "")
                    if tc_id_for_app:
                        pending_mcp_apps[tc_id_for_app] = {
                            "tool_category": sub_entry.get("tool_category", ""),
                            "tool_name": sub_entry.get("data", {}).get("tool_name", ""),
                            "server_url": sub_entry.get("mcp_server_url", ""),
                            "mcp_ui": sub_entry["mcp_ui"],
                            "timestamp": sub_entry.get("timestamp"),
                            "tool_arguments": sub_entry.get("data", {}).get(
                                "inputs", {}
                            ),
                        }

            # Intercept subagent tool_output events to emit deferred mcp_app
            if isinstance(payload, dict) and "tool_output" in payload:
                sub_output = payload["tool_output"]
                tc_id = sub_output.get("tool_call_id", "")
                app_meta = pending_mcp_apps.pop(tc_id, None)
                if app_meta:
                    try:
                        ui_resource = await fetch_mcp_ui_resource(
                            server_url=app_meta["server_url"],
                            resource_uri=app_meta["mcp_ui"]["resource_uri"],
                            user_id=user_id or "",
                        )
                        html_content = (
                            ui_resource.get("html")
                            if isinstance(ui_resource, dict)
                            else None
                        )
                        if html_content:
                            content_csp = (
                                ui_resource.get("csp")
                                if isinstance(ui_resource, dict)
                                else None
                            )
                            content_permissions = (
                                ui_resource.get("permissions")
                                if isinstance(ui_resource, dict)
                                else None
                            )
                            yield format_sse_data(
                                {
                                    "tool_data": {
                                        "tool_name": "mcp_app",
                                        "tool_category": app_meta["tool_category"],
                                        "data": {
                                            "tool_call_id": tc_id,
                                            "tool_name": app_meta["tool_name"],
                                            "server_url": app_meta["server_url"],
                                            "resource_uri": app_meta["mcp_ui"][
                                                "resource_uri"
                                            ],
                                            "html_content": html_content,
                                            "tool_result": sub_output.get("output"),
                                            "csp": content_csp
                                            if content_csp is not None
                                            else app_meta["mcp_ui"].get("csp"),
                                            "permissions": content_permissions
                                            if content_permissions is not None
                                            else app_meta["mcp_ui"].get(
                                                "permissions", []
                                            ),
                                            "tool_arguments": app_meta.get(
                                                "tool_arguments", {}
                                            ),
                                        },
                                        "timestamp": app_meta["timestamp"],
                                    }
                                }
                            )
                    except Exception as _e:
                        log.warning(f"Failed to emit mcp_app from subagent: {_e}")

    # Yield complete message for DB storage
    yield f"nostream: {json.dumps({'complete_message': complete_message})}"
    yield "data: [DONE]\n\n"
