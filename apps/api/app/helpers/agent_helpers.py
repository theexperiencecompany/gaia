"""Core agent helpers: config building, state init, and graph execution (streaming and silent)."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
import json
import re

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langsmith import traceable
from posthog.ai.langchain import CallbackHandler as PostHogCallbackHandler

from app.agents.core.subagents.registry import get_subagent_by_id
from app.config.langfuse import build_langfuse_callback
from app.constants.cache import (
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
from app.models.chat_models import ConversationSource, SourceCategory
from app.models.models_models import ModelConfig
from app.services.mcp.mcp_resource_fetcher import fetch_mcp_ui_resource
from app.utils.agent_utils import (
    format_sse_data,
    format_sse_response,
    format_tool_call_entry,
    parse_subagent_id,
    process_custom_event_for_tools,
)
from shared.py.wide_events import log


async def get_handoff_metadata(subagent_id: str) -> dict:
    """Look up icon_url, integration_id, integration_name for handoff subagents.

    Checks platform integrations (in-memory) and custom MCPs (MongoDB, Redis-cached).
    Returns an empty dict if not found.
    """

    clean_id, _ = parse_subagent_id(subagent_id)
    clean_id = clean_id.lower()

    # Check platform/builtin subagents first (in-memory, no caching needed)
    subagent = get_subagent_by_id(clean_id)
    if subagent:
        log.set(integration_type="platform")
        return {
            "icon_url": None,  # Platform/builtin subagents use category-based icons
            "integration_id": subagent.id,
            "integration_name": subagent.name,
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
    """Extract timezone offset string (e.g. "+05:30") from a datetime; "+00:00" if naive."""
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


def _build_agent_callbacks(
    conversation_id: str,
    user: dict,
    agent_name: str,
    usage_metadata_callback: UsageMetadataCallbackHandler | None,
) -> list[BaseCallbackHandler]:
    """Assemble the LangChain callback list for an agent run (PostHog, usage)."""
    callbacks: list[BaseCallbackHandler] = []

    posthog_client = providers.get("posthog") if providers.is_available("posthog") else None
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

    langfuse_callback = build_langfuse_callback()
    if langfuse_callback is not None:
        callbacks.append(langfuse_callback)

    if usage_metadata_callback:
        callbacks.append(usage_metadata_callback)

    return callbacks


def _resolve_model_config(
    user_model_config: ModelConfig | None,
) -> tuple[str, str, int]:
    """Pick the model triple (name, provider, max_tokens) from user choice or defaults."""
    if user_model_config:
        log.set(model_config_source="user_selected")
        return (
            user_model_config.provider_model_name,
            user_model_config.inference_provider.value,
            user_model_config.max_tokens,
        )
    log.set(model_config_source="default")
    return DEFAULT_MODEL_NAME, DEFAULT_LLM_PROVIDER, DEFAULT_MAX_TOKENS


# Fields that fall back to the parent only when the current call left them blank.
_PARENT_FALLBACK_FIELDS: tuple[tuple[str, str], ...] = (
    ("selected_tool", "selected_tool"),
    ("tool_category", "tool_category"),
    ("subagent_id", "subagent_id"),
    ("vfs_session_id", "vfs_session_id"),
    ("active_todo_id", "active_todo_id"),
    ("execution_mode", "execution_mode"),
    ("source", "conversation_source"),
)


def _inherit_from_parent_configurable(
    base_configurable: dict | None,
    current: dict,
) -> dict:
    """Merge `current` with optional inheritance from a parent agent's configurable.

    - Model fields (provider/max_tokens/model_name): parent overrides child.
    - Fallback fields (tool / subagent / vfs / todo / mode / source): child wins; parent
      only fills in blanks.
    - Pass-through (stream_id, pinned memories/skills): always come from parent.
    """
    merged = dict(current)
    merged["stream_id"] = None
    merged["pinned_memories"] = None
    merged["pinned_skills"] = None

    if not base_configurable:
        return merged

    merged["provider_name"] = base_configurable.get("provider", merged["provider_name"])
    merged["max_tokens"] = base_configurable.get("max_tokens", merged["max_tokens"])
    merged["model_name"] = base_configurable.get("model_name", merged["model_name"])

    for local_key, parent_key in _PARENT_FALLBACK_FIELDS:
        if not merged.get(local_key):
            merged[local_key] = base_configurable.get(parent_key)

    # Pre-fetched memory/skills sections avoid repeat ChromaDB lookups on the subagent.
    merged["stream_id"] = base_configurable.get("stream_id")
    merged["pinned_memories"] = base_configurable.get("__pinned_memories__")
    merged["pinned_skills"] = base_configurable.get("__pinned_skills__")
    return merged


def build_agent_config(
    conversation_id: str,
    user: dict,
    user_time: datetime,
    agent_name: str,
    user_model_config: ModelConfig | None = None,
    usage_metadata_callback: UsageMetadataCallbackHandler | None = None,
    thread_id: str | None = None,
    base_configurable: dict | None = None,
    selected_tool: str | None = None,
    tool_category: str | None = None,
    subagent_id: str | None = None,
    vfs_session_id: str | None = None,
    active_todo_id: str | None = None,
    execution_mode: str | None = None,
    source: str | None = None,
    langfuse_trace_id: str | None = None,
    langfuse_tags: list[str] | None = None,
) -> dict:
    """Build the LangGraph execution config (user context, model, auth, execution params).

    Notable args:
        vfs_session_id: Shared VFS session ID held constant across the executor and the
            handoff subagents it spawns, so all resolve VFS paths against the executor
            workspace. Inherited automatically via base_configurable.
        langfuse_trace_id / langfuse_tags: Bind spans to a Langfuse trace; inherit from
            base_configurable when omitted so the executor lands on the comms trace.
    """
    callbacks = _build_agent_callbacks(conversation_id, user, agent_name, usage_metadata_callback)
    model_name, provider_name, max_tokens = _resolve_model_config(user_model_config)

    resolved = _inherit_from_parent_configurable(
        base_configurable,
        {
            "provider_name": provider_name,
            "max_tokens": max_tokens,
            "model_name": model_name,
            "selected_tool": selected_tool,
            "tool_category": tool_category,
            "subagent_id": subagent_id,
            "vfs_session_id": vfs_session_id,
            "active_todo_id": active_todo_id,
            "execution_mode": execution_mode,
            "source": source,
        },
    )

    # Explicit kwargs win over what was inherited from the parent's configurable.
    # `is not None` (not `or`) so callers can pass [] to intentionally clear tags.
    inherited = base_configurable or {}
    effective_trace_id = (
        langfuse_trace_id if langfuse_trace_id is not None else inherited.get("langfuse_trace_id")
    )
    effective_tags = langfuse_tags if langfuse_tags is not None else inherited.get("langfuse_tags")

    # Specific channel (web/mobile/whatsapp/...) and its generalized category
    # (UI/Bot/BG). The channel falls back to "background" when unset because the
    # only callers that omit a source are the silent background paths.
    source_channel = resolved["source"] or ConversationSource.BACKGROUND.value
    source_category = SourceCategory.from_source(resolved["source"]).value

    configurable = {
        "thread_id": thread_id or conversation_id,
        "user_id": user.get("user_id"),
        "email": user.get("email"),
        "user_name": user.get("name", ""),
        "user_time": user_time.isoformat(),
        "user_timezone": _extract_timezone_offset(user_time),
        "provider": resolved["provider_name"],
        "max_tokens": resolved["max_tokens"],
        "model_name": resolved["model_name"],
        "model": resolved["model_name"],
        "selected_tool": resolved["selected_tool"],
        "tool_category": resolved["tool_category"],
        "subagent_id": resolved["subagent_id"],
        "vfs_session_id": resolved["vfs_session_id"],
        "stream_id": resolved["stream_id"],
        "active_todo_id": resolved["active_todo_id"],
        "execution_mode": resolved["execution_mode"] or "interactive",
        "conversation_source": resolved["source"],
        "source_category": source_category,
        "__pinned_memories__": resolved["pinned_memories"],
        "__pinned_skills__": resolved["pinned_skills"],
    }

    # Stash in configurable so child agents (spawned via asyncio.create_task)
    # re-emit the same trace_id from their own build_agent_config call.
    if effective_trace_id:
        configurable["langfuse_trace_id"] = effective_trace_id
    if effective_tags:
        configurable["langfuse_tags"] = effective_tags

    metadata: dict = {
        "user_id": user.get("user_id"),
        "source_category": source_category,
        "source_channel": source_channel,
    }
    if effective_trace_id:
        metadata["langfuse_trace_id"] = effective_trace_id
        metadata["langfuse_session_id"] = conversation_id
        if user.get("user_id"):
            metadata["langfuse_user_id"] = user["user_id"]
        if effective_tags:
            metadata["langfuse_tags"] = effective_tags

    return {
        "configurable": configurable,
        "recursion_limit": AGENT_RECURSION_LIMIT,
        "metadata": metadata,
        "callbacks": callbacks,
        "agent_name": agent_name,
    }


def build_initial_state(
    request,
    user_id: str,
    conversation_id: str,
    history,
    trigger_context: dict | None = None,
) -> dict:
    """Construct the initial LangGraph state (query, history, tool selections, trigger context)."""
    state = {
        "query": request.message,
        "intent": request.message,
        "messages": history,
        "current_datetime": datetime.now(UTC).isoformat(),
        "mem0_user_id": user_id,
        "conversation_id": conversation_id,
        "integration_usernames": {},
        "selected_tool": request.selectedTool,
        "selected_workflow": request.selectedWorkflow,
        "selected_calendar_event": request.selectedCalendarEvent,
    }

    if trigger_context:
        state["trigger_context"] = trigger_context
        # Bind active todo + execution mode so banners and tools default
        # to the firing todo. Scheduled runs always set these; comms-driven
        # turns may set them when delegating todo-bound work.
        if active_todo_id := trigger_context.get("active_todo_id") or trigger_context.get(
            "todo_id"
        ):
            state["active_todo_id"] = active_todo_id
        if execution_mode := trigger_context.get("execution_mode"):
            state["execution_mode"] = execution_mode

    return state


@traceable(run_type="llm", name="Call Agent Silent")
async def execute_graph_silent(
    graph,
    initial_state: dict,
    config: dict,
) -> tuple[str, dict]:
    """Execute LangGraph in silent mode, accumulating the full message and tool data.

    Used for background processing and workflow triggers that don't need streaming.
    Stores intermediate messages and tool outputs as they happen, like normal chat.
    Returns (complete_message, tool_data).
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
                # Only collect tool_data from the LLM node — pre-model hooks
                # produce updates containing historical messages with old tool_calls.
                if node_name != "agent":
                    continue
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
                            tool_metadata: dict = {}

                            # TODO(remove): PR492/CodeRabbit - todo tools already stream todo_progress; suppress tool_data noise.
                            # Safe: doesn't affect agent state; only avoids redundant UI events.
                            if tool_name in {"plan_tasks", "update_tasks"}:
                                continue

                            # Handoff metadata stays pre-resolved here (it's a special
                            # subagent-display path). MCP tool metadata is now resolved
                            # inside format_tool_call_entry when user_id is passed.
                            if tool_name == "handoff":
                                args = tc.get("args", {})
                                subagent_id = args.get("subagent_id", "")
                                if subagent_id:
                                    tool_metadata = await get_handoff_metadata(subagent_id)

                            tool_entry = await format_tool_call_entry(
                                tc,
                                icon_url=tool_metadata.get("icon_url"),
                                integration_id=tool_metadata.get("integration_id"),
                                integration_name=tool_metadata.get("integration_name"),
                                user_id=user_id,
                            )
                            if tool_entry:
                                tool_data["tool_data"].append(tool_entry)
                                emitted_tool_calls.add(tc_id)
            continue

        if stream_mode == "messages":
            chunk, metadata = payload

            if metadata.get("silent"):
                continue  # Skip silent chunks (e.g. follow-up actions generation)

            if chunk and isinstance(chunk, (AIMessage, AIMessageChunk)):
                content = chunk.text if hasattr(chunk, "text") else str(chunk.content)
                if content and config.get("agent_name") == "comms_agent":
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
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    return complete_message, tool_data


@traceable(run_type="llm", name="Call Agent")
async def execute_graph_streaming(
    graph,
    initial_state: dict,
    config: dict,
) -> AsyncGenerator[str, None]:
    """Execute LangGraph in streaming mode, yielding SSE-formatted updates.

    Cancellable via stream_id in config (through stream_manager).

    LangGraph emits three stream modes:
        - "updates": state changes after each node; AIMessage.tool_calls carry full
          args, emitted as tool_data entries (frontend shows loading state).
        - "messages": AIMessageChunk text content; ToolMessage results -> tool_output.
        - "custom": application-specific tool events, forwarded as-is.
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
                # Only emit tool_data from the LLM ("agent") node.
                # Pre-model hooks (filter_messages_node, manage_system_prompts_node,
                # etc.) also produce "updates" events that include historical
                # AIMessages with tool_calls from previous turns — emitting those
                # would replay stale tool cards into the current SSE stream.
                if node_name != "agent":
                    continue

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
                            tool_metadata: dict = {}

                            # Handoff metadata stays pre-resolved here (it's a special
                            # subagent-display path). MCP tool metadata is now resolved
                            # inside format_tool_call_entry when user_id is passed.
                            if tool_name == "handoff":
                                args = tc.get("args", {})
                                subagent_id = args.get("subagent_id", "")
                                if subagent_id:
                                    tool_metadata = await get_handoff_metadata(subagent_id)

                            # Format and emit tool_data entry
                            tool_entry = await format_tool_call_entry(
                                tc,
                                icon_url=tool_metadata.get("icon_url"),
                                integration_id=tool_metadata.get("integration_id"),
                                integration_name=tool_metadata.get("integration_name"),
                                user_id=user_id,
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
                                    tc_id_for_app = tool_entry["data"].get("tool_call_id", "")
                                    if tc_id_for_app:
                                        pending_mcp_apps[tc_id_for_app] = {
                                            "tool_category": tool_entry.get("tool_category", ""),
                                            "tool_name": tool_entry["data"].get("tool_name", ""),
                                            "server_url": tool_entry.get("mcp_server_url", ""),
                                            "mcp_ui": tool_entry["mcp_ui"],
                                            "timestamp": tool_entry.get("timestamp"),
                                            "tool_arguments": tool_entry["data"].get("inputs", {}),
                                        }
            continue

        if stream_mode == "messages":
            chunk, metadata = payload
            if metadata.get("silent"):
                continue

            # Stream AI response content (only from comms_agent to avoid duplication)
            if chunk and isinstance(chunk, (AIMessage, AIMessageChunk)):
                content = chunk.text
                if content and config.get("agent_name") == "comms_agent":
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
                    model_dump = getattr(tool_result_payload, "model_dump", None)
                    if callable(model_dump):
                        tool_result_payload = model_dump()
                    elif hasattr(tool_result_payload, "__dict__"):
                        tool_result_payload = dict(tool_result_payload.__dict__)
                    else:
                        tool_result_payload = str(tool_result_payload)
                output = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
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
                            ui_resource.get("html") if isinstance(ui_resource, dict) else None
                        )
                        if html_content:
                            content_csp = (
                                ui_resource.get("csp") if isinstance(ui_resource, dict) else None
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
                                            "resource_uri": app_meta["mcp_ui"]["resource_uri"],
                                            "html_content": html_content,
                                            "tool_result": tool_result_payload,
                                            "csp": content_csp
                                            if content_csp is not None
                                            else app_meta["mcp_ui"].get("csp"),
                                            "permissions": content_permissions
                                            if content_permissions is not None
                                            else app_meta["mcp_ui"].get("permissions", []),
                                            "tool_arguments": app_meta.get("tool_arguments", {}),
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
                            "tool_arguments": sub_entry.get("data", {}).get("inputs", {}),
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
                            ui_resource.get("html") if isinstance(ui_resource, dict) else None
                        )
                        if html_content:
                            content_csp = (
                                ui_resource.get("csp") if isinstance(ui_resource, dict) else None
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
                                            "resource_uri": app_meta["mcp_ui"]["resource_uri"],
                                            "html_content": html_content,
                                            "tool_result": sub_output.get("output"),
                                            "csp": content_csp
                                            if content_csp is not None
                                            else app_meta["mcp_ui"].get("csp"),
                                            "permissions": content_permissions
                                            if content_permissions is not None
                                            else app_meta["mcp_ui"].get("permissions", []),
                                            "tool_arguments": app_meta.get("tool_arguments", {}),
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
