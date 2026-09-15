"""Core agent helpers: config building, state init, and graph execution (streaming and silent)."""

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import time
from typing import Any, TypedDict, cast
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, BaseMessage, ToolMessage
from langsmith import traceable
from posthog.ai.langchain import CallbackHandler as PostHogCallbackHandler

from app.agents.core.background.session import claim_tool_output
from app.agents.core.graph_manager import CompiledAgentGraph
from app.agents.core.interruption import record_interruption
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.llm.lane import AgentRole, ModelLane, resolve_lane
from app.agents.llm.ttft import LLMTtftCallback
from app.agents.llm.types import DevModelOption
from app.config.langfuse import build_langfuse_callback
from app.constants.cache import (
    CUSTOM_INT_METADATA_TTL,
    HANDOFF_METADATA_CACHE_PREFIX,
)
from app.constants.hil import HIL_JUDGE_MAX_TURN_CHARS, HIL_JUDGE_MAX_USER_TURNS
from app.constants.llm import (
    AGENT_RECURSION_LIMIT,
    LLM_LABEL_METADATA_KEY,
)
from app.constants.log_tags import LogTag
from app.core.lazy_loader import providers
from app.core.stream_manager import stream_manager
from app.db.redis import get_cache, set_cache
from app.db.repositories.integrations import integration_repository
from app.models.agent_models import (
    AgentConfigurable,
    AgentRunnableConfig,
    AgentUserContext,
    ExecutionMode,
    agent_configurable,
)
from app.models.chat_models import ConversationSource, SourceCategory, ToolDataEntry
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.payment_models import PlanType
from app.models.stream_events import (
    MessageBoundaryPayload,
    ModelFallbackFrame,
    ToolOutputPayload,
)
from app.services.latency_metrics import observe_comms_graph, span
from app.services.mcp.mcp_resource_fetcher import fetch_mcp_ui_resource
from app.utils.agent_utils import (
    format_sse_data,
    format_sse_response,
    format_tool_call_entry,
    parse_subagent_id,
    process_custom_event_for_tools,
)
from app.utils.general_utils import clip_text
from app.utils.message_breaks import append_message_bubble
from app.utils.multimodal import extract_text_content, has_media_blocks
from shared.py.wide_events import log


class HandoffMetadata(TypedDict, total=False):
    """Display metadata for a handoff subagent's tool card. Empty when unresolvable."""

    icon_url: str | None
    integration_id: str
    integration_name: str


def announces_tool_call(chunk: AIMessage) -> bool:
    """Return whether this chunk already carries a tool call — meaning any text is narration.

    tool_calls (complete) or tool_call_chunks (still assembling) both count.
    getattr guards the second since only the chunk subclass has that field.
    """
    return bool(chunk.tool_calls or getattr(chunk, "tool_call_chunks", None))


def _flush_held_messages(complete_message: str, held: dict[str, str]) -> str:
    """Append text whose message never reached a boundary (a cancelled run)."""
    for text in held.values():
        if text:
            complete_message = append_message_bubble(complete_message, text)
    return complete_message


def drop_retracted_text(payload: object, held: dict[str, str]) -> None:
    """Forget text whose message was retracted mid-node, before its boundary.

    Retractions are normally announced at node end, except the style guard's,
    which retracts a draft mid-node to replace it with a second model call —
    the driver must honour that boundary too, or the draft stays persisted.
    """
    if not isinstance(payload, dict):
        return
    boundary = payload.get("message_boundary")
    if isinstance(boundary, dict) and boundary.get("discarded"):
        held.pop(str(boundary.get("message_id") or ""), None)


def last_ai_message(messages: Sequence[AnyMessage]) -> AIMessage | None:
    """Return the model's own reply in a node update.

    A node update also carries RemoveMessage tombstones for pruned history,
    so "the message this node produced" is the last AI one, not the last one.
    """
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


async def get_handoff_metadata(subagent_id: str) -> HandoffMetadata:
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
        # Written below by this same function, so the cached shape is ours by
        # construction — cast, not isinstance (Type Safety item 12).
        return cast(HandoffMetadata, cached) if cached else {}

    # Find the integration by ID or name.
    # No source filter - we need to find ANY integration (custom OR public).
    # Public integrations created by OTHER users also need metadata lookup.
    try:
        custom = await integration_repository.find_by_id_prefix_or_name(clean_id)

        if not custom:
            # Cache negative result
            await set_cache(cache_key, {}, ttl=CUSTOM_INT_METADATA_TTL)
            return {}

        metadata: HandoffMetadata = {
            "icon_url": custom.icon_url,
            "integration_id": custom.integration_id,
            "integration_name": custom.name,
        }

        log.set(integration_type="custom")
        await set_cache(cache_key, metadata, ttl=CUSTOM_INT_METADATA_TTL)
        return metadata

    except Exception as e:
        log.warning("Failed to lookup handoff metadata", error=str(e), error_type=type(e).__name__)
        return {}


def _build_agent_callbacks(
    conversation_id: str,
    user: AgentUserContext,
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

    # True provider first-token latency for every tier on this run.
    callbacks.append(LLMTtftCallback())

    return callbacks


def _inherit_from_parent_configurable(
    base_configurable: AgentConfigurable | None,
    current: AgentConfigurable,
) -> AgentConfigurable:
    """Merge current with optional inheritance from a parent agent's configurable.

    Fallback fields (tool/subagent/vfs/todo/mode/source): child wins, parent
    fills blanks. stream_id always comes from parent. The model is NOT merged
    here — a child inherits its parent's lane whole (see build_agent_config).
    """
    merged: AgentConfigurable = {**current, "stream_id": None}

    if not base_configurable:
        return merged

    # Parent overrides: the TRUE conversation id is established once by comms and
    # must survive child agents passing their own wrapped thread ids down as the
    # ``conversation_id`` argument (``executor_<conv>`` → ``<integ>_executor_<conv>``).
    merged["conversation_id"] = (
        base_configurable.get("conversation_id") or merged["conversation_id"]
    )
    # Sticky-routing key, conversation-scoped: every agent in the tree must
    # hit the provider holding the conversation's warm cache.
    if "session_id" in base_configurable:
        merged["session_id"] = base_configurable["session_id"]
    # Parent overrides, same reason: the user's VERBATIM turns, established once
    # by comms. A child's own "task" is an agent-authored paraphrase, and the HIL
    # intent judge must check the tool call against what the user actually asked.
    merged["user_messages"] = base_configurable.get("user_messages") or merged["user_messages"]
    merged["user_request"] = base_configurable.get("user_request") or merged["user_request"]
    # Same rule, same reason: established once wherever the root call site had the
    # full user document in hand, and a child never has its own copy to prefer.
    merged["user_preferences"] = (
        base_configurable.get("user_preferences") or merged["user_preferences"]
    )
    merged["writing_style"] = base_configurable.get("writing_style") or merged["writing_style"]
    # Child wins; the parent only fills a blank. Written out per key rather than
    # driven by a table so each one is a checked TypedDict access.
    merged["selected_tool"] = merged.get("selected_tool") or base_configurable.get("selected_tool")
    merged["tool_category"] = merged.get("tool_category") or base_configurable.get("tool_category")
    merged["subagent_id"] = merged.get("subagent_id") or base_configurable.get("subagent_id")
    merged["vfs_session_id"] = merged.get("vfs_session_id") or base_configurable.get(
        "vfs_session_id"
    )
    merged["active_todo_id"] = merged.get("active_todo_id") or base_configurable.get(
        "active_todo_id"
    )
    merged["conversation_source"] = merged.get("conversation_source") or base_configurable.get(
        "conversation_source"
    )
    inherited_mode = merged.get("execution_mode") or base_configurable.get("execution_mode")
    if inherited_mode:
        merged["execution_mode"] = inherited_mode

    merged["stream_id"] = base_configurable.get("stream_id")
    return merged


def recent_user_messages(history: list[MessageDict], current: str) -> list[str]:
    """Return the user's own recent turns, verbatim and oldest first, ending with current.

    Intent routinely spans turns — "draft an email to Bob" … "looks good, send it" — so
    the latest message alone cannot be grounded against. Only role == "user" turns
    are kept: the HIL intent judge must never see assistant text, or the agent can talk
    it into approving (see services/hil/intent.py).
    """
    turns = [
        text
        for message in history
        if message.get("role") == "user" and (text := (message.get("content") or "").strip())
    ]
    current = current.strip()
    # The client usually already appends this turn to `messages`; don't duplicate it, and
    # guarantee it ends the list either way — the judge treats the last as the live request.
    if current and (not turns or turns[-1] != current):
        turns.append(current)
    return [clip_text(text, HIL_JUDGE_MAX_TURN_CHARS) for text in turns[-HIL_JUDGE_MAX_USER_TURNS:]]


# Replaces 22 flat keyword-only parameters, bundled into five groups: AgentIdentity
# (who/where), AgentLane (model lane), AgentThread (parent inheritance), AgentTurn
# (what this turn is about), AgentTracing (spans/tokens) — each optional but identity.
@dataclass(frozen=True)
class AgentIdentity:
    """Who is running, and in which conversation. Required for every run."""

    conversation_id: str
    """The TRUE conversation id — also the OpenRouter sticky-routing session key."""

    user: AgentUserContext
    """The acting user: id, email, name, and (top-level callers) the home timezone."""

    agent_name: str
    """Which agent this run is: comms_agent, executor_agent, a subagent id, ..."""


@dataclass(frozen=True)
class AgentLane:
    """The model lane inputs.

    Only consulted for a TOP-LEVEL run (no AgentThread.base_configurable), which
    is the one that resolves a lane; a child inherits its parent's lane whole and
    ignores both fields.
    """

    role: AgentRole = AgentRole.SUBAGENT
    """Which tier is running, which is what picks the lane."""

    dev_option: DevModelOption | None = None
    """DEV-ONLY explicit model pick; beats inheritance (the switcher's whole purpose)."""


@dataclass(frozen=True)
class AgentThread:
    """Where the run lives, and what it inherits from its parent."""

    thread_id: str | None = None
    """LangGraph thread for the wrapped graph; defaults to the conversation id."""

    base_configurable: AgentConfigurable | None = None
    """The parent run's configurable. Present means this is a child run: it inherits
    the parent's lane, trace, plan, workflow and the parent-overrides keys (see
    ``_inherit_from_parent_configurable``)."""

    subagent_id: str | None = None
    """The subagent this run embodies; also its memory namespace id."""

    vfs_session_id: str | None = None
    """Shared VFS session ID held constant across the executor and the handoff
    subagents it spawns, so all resolve VFS paths against the executor workspace.
    Inherited automatically via ``base_configurable``."""

    recursion_limit: int = AGENT_RECURSION_LIMIT
    """Max LangGraph steps before GraphRecursionError. Defaults to the comms/subagent
    cap; the executor passes EXECUTOR_RECURSION_LIMIT for its longer tool loops."""


@dataclass(frozen=True)
class AgentTurn:
    """What this turn is about: the user's words, the request, and the tool framing."""

    selected_tool: str | None = None
    """A tool the client pinned for this turn."""

    tool_category: str | None = None
    """The category comms already resolved, letting the executor skip discovery."""

    active_todo_id: str | None = None
    """The tracked todo this turn is working, when there is one."""

    execution_mode: ExecutionMode | None = None
    """interactive vs the background modes; inherited when omitted."""

    source: str | None = None
    """The channel (web/mobile/whatsapp/...); falls back to "background" when unset."""

    user_messages: list[str] | None = None
    """The user's own recent turns, verbatim, oldest first (see
    :func:`recent_user_messages`). Set once by comms and inherited (parent-overrides)
    by the executor and every subagent, whose own tasks are agent-authored
    paraphrases. The HIL intent judge checks gated tool calls against these, so they
    must be the user's words — not a restatement."""

    user_request: str | None = None
    """The live turn's request exactly as typed, unclipped. Same inheritance rule as
    ``user_messages``; ``call_executor`` folds it into the executor brief so the
    worker tier is never left with only the comms agent's paraphrase."""

    user_preferences: dict[str, Any] | None = None
    """Onboarding data, same inheritance rule as ``user_messages`` — pass it at
    whichever root call site already has the full user document in hand (comms,
    background narration, the dev direct-invoke entrypoint); every child agent
    inherits it unchanged."""

    writing_style: dict[str, Any] | None = None
    """Onboarding data; same inheritance rule as ``user_preferences``."""


@dataclass(frozen=True)
class AgentTracing:
    """Where this run's spans and token counts go."""

    usage_metadata_callback: UsageMetadataCallbackHandler | None = None
    """Collector the caller reads token usage back off after the run."""

    langfuse_trace_id: str | None = None
    """Binds spans to a Langfuse trace; inherited from ``base_configurable`` when
    omitted so the executor lands on the comms trace."""

    langfuse_tags: list[str] | None = None
    """Tags for that trace. Inherited when omitted; pass ``[]`` to clear them."""


def _stamp_langfuse(
    configurable: AgentConfigurable,
    metadata: dict[str, Any],
    effective_trace_id: str | None,
    effective_tags: list[str] | None,
    user: AgentUserContext,
    conversation_id: str,
) -> None:
    """Bind the run to its Langfuse trace, on the configurable and the metadata.

    Stashed in configurable so child agents (spawned via asyncio.create_task)
    re-emit the same trace_id from their own build_agent_config call.
    """
    if effective_trace_id:
        configurable["langfuse_trace_id"] = effective_trace_id
    if effective_tags:
        configurable["langfuse_tags"] = effective_tags
    if effective_trace_id:
        metadata["langfuse_trace_id"] = effective_trace_id
        metadata["langfuse_session_id"] = conversation_id
        if user.get("user_id"):
            metadata["langfuse_user_id"] = user["user_id"]
        if effective_tags:
            metadata["langfuse_tags"] = effective_tags


async def build_agent_config(
    *,
    identity: AgentIdentity,
    lane: AgentLane | None = None,
    thread: AgentThread | None = None,
    turn: AgentTurn | None = None,
    tracing: AgentTracing | None = None,
) -> AgentRunnableConfig:
    """Build the LangGraph execution config (user context, model, auth, execution params).

    An omitted group is its all-defaults instance; lane is consulted only for
    a top-level run. Per-field notes live on the dataclasses above.
    """
    # An omitted group is its all-defaults instance. The groups whose fields the
    # body reads all over (identity, thread, turn) are unpacked into locals under
    # their old names; lane and tracing are each read in one place and stay whole.
    lane, thread, turn, tracing = (
        lane if lane is not None else AgentLane(),
        thread if thread is not None else AgentThread(),
        turn if turn is not None else AgentTurn(),
        tracing if tracing is not None else AgentTracing(),
    )
    conversation_id, user, agent_name = identity.conversation_id, identity.user, identity.agent_name
    thread_id, base_configurable, subagent_id, vfs_session_id, recursion_limit = (
        thread.thread_id,
        thread.base_configurable,
        thread.subagent_id,
        thread.vfs_session_id,
        thread.recursion_limit,
    )
    (
        selected_tool,
        tool_category,
        active_todo_id,
        execution_mode,
        source,
        user_messages,
        user_request,
        user_preferences,
        writing_style,
    ) = (
        turn.selected_tool,
        turn.tool_category,
        turn.active_todo_id,
        turn.execution_mode,
        turn.source,
        turn.user_messages,
        turn.user_request,
        turn.user_preferences,
        turn.writing_style,
    )

    callbacks = _build_agent_callbacks(
        conversation_id, user, agent_name, tracing.usage_metadata_callback
    )

    # The one seam every execution path crosses: a run with a parent inherits its
    # lane whole, a top-level run resolves one here, so a new entry point can't be
    # born on the wrong lane. An explicit dev choice beats inheritance beats fresh.
    inherited_lane = ModelLane.from_configurable((base_configurable or {}).get("lane"))
    resolved_plan: PlanType | None = None
    if lane.dev_option is None and inherited_lane is not None:
        model_lane = inherited_lane
    else:
        model_lane, resolved_plan = await resolve_lane(
            user.get("user_id"), lane.role, lane.dev_option
        )

    current: AgentConfigurable = {
        "conversation_id": conversation_id,
        # OpenRouter sticky-routing key: pins every request of this
        # conversation to the provider holding its warm prompt cache
        # (see the routing note in constants/llm.py).
        "session_id": conversation_id,
        "selected_tool": selected_tool,
        "tool_category": tool_category,
        "subagent_id": subagent_id,
        "vfs_session_id": vfs_session_id,
        "active_todo_id": active_todo_id,
        "conversation_source": source,
        "user_messages": user_messages,
        "user_request": user_request,
        "user_preferences": user_preferences,
        "writing_style": writing_style,
    }
    if execution_mode:
        current["execution_mode"] = execution_mode
    resolved = _inherit_from_parent_configurable(base_configurable, current)

    # Explicit kwargs win over what was inherited from the parent's configurable.
    # `is not None` (not `or`) so callers can pass [] to intentionally clear tags.
    inherited = base_configurable or {}
    effective_trace_id = (
        tracing.langfuse_trace_id
        if tracing.langfuse_trace_id is not None
        else inherited.get("langfuse_trace_id")
    )
    effective_tags = (
        tracing.langfuse_tags
        if tracing.langfuse_tags is not None
        else inherited.get("langfuse_tags")
    )

    # Specific channel (web/mobile/whatsapp/...) and its generalized category
    # (UI/Bot/BG). The channel falls back to "background" when unset because the
    # only callers that omit a source are the silent background paths.
    resolved_source = resolved.get("conversation_source")
    source_channel = resolved_source or ConversationSource.BACKGROUND.value
    source_category = SourceCategory.from_source(resolved_source).value

    # The agent operates in the user's HOME timezone (IANA, DST-aware). Top-level
    # callers pass it on user["timezone"]; child agents reconstruct a bare user
    # dict, so they inherit the parent's zone from base_configurable instead.
    home_timezone = (user.get("timezone") or "").strip()
    if not home_timezone and base_configurable:
        home_timezone = (base_configurable.get("user_timezone") or "").strip()
    if not home_timezone:
        home_timezone = "UTC"

    # One id for the WHOLE user turn: generated at the top-level call and
    # inherited by every child agent, so the accounting middleware's aggregate
    # token counter binds across the tree instead of resetting per graph.
    root_request_id = inherited.get("root_request_id") or str(uuid4())

    configurable: AgentConfigurable = {
        "thread_id": thread_id or conversation_id,
        # The TRUE conversation id (see _inherit_from_parent_configurable), NOT
        # recoverable from thread_id (the wrapped graph thread). HIL approvals,
        # notifications, and the executor queue read this key, never thread_id.
        "conversation_id": resolved["conversation_id"],
        # The user's own verbatim turns (see build_agent_config). The HIL intent judge
        # reads these; child agents inherit them unchanged.
        "user_messages": resolved["user_messages"],
        "user_request": resolved["user_request"],
        "user_preferences": resolved["user_preferences"],
        "writing_style": resolved["writing_style"],
        "user_id": user.get("user_id"),
        "email": user.get("email"),
        "user_name": user.get("name", ""),
        "user_timezone": home_timezone,
        "root_request_id": root_request_id,
        # The decision, and its expansion into LangChain's binding keys. Only
        # ``lane`` is inherited by children; the binding keys are always
        # re-derived from it, so the two can never drift apart.
        "lane": model_lane.to_configurable(),
        "selected_tool": resolved["selected_tool"],
        "tool_category": resolved["tool_category"],
        "subagent_id": resolved["subagent_id"],
        "vfs_session_id": resolved["vfs_session_id"],
        "stream_id": resolved["stream_id"],
        "active_todo_id": resolved["active_todo_id"],
        "execution_mode": resolved.get("execution_mode") or "interactive",
        "conversation_source": resolved_source,
        "source_category": source_category,
        # Re-emitted in the literal below (a fresh dict — a key dropped here
        # never reaches the graph config).
        "session_id": resolved.get("session_id"),
    }

    # LangChain's binding keys, always re-derived from the lane so the two can
    # never drift apart.
    configurable.update(model_lane.binding_keys())

    # The budget wall reads plan_type to avoid a Redis lookup on the hot path.
    # Stamped from the same resolve_lane call that chose the model, and inherited
    # by children the way root_request_id is.
    if plan := (inherited.get("plan_type") or (resolved_plan.value if resolved_plan else None)):
        configurable["plan_type"] = plan

    # A workflow fire stamps its workflow on the comms configurable; the executor
    # and its handoff subagents inherit it whole, the way root_request_id is.
    if workflow_id := inherited.get("workflow_id"):
        configurable["workflow_id"] = workflow_id
        configurable["workflow_title"] = inherited.get("workflow_title", "")
        configurable["workflow_notify_on_completion"] = inherited.get(
            "workflow_notify_on_completion", True
        )

    metadata: dict[str, Any] = {
        "user_id": user.get("user_id"),
        "source_category": source_category,
        "source_channel": source_channel,
        # Lane identity for the TTFT callback, which reads it off run metadata.
        "lane_provider": model_lane.provider.value,
        "lane_model": model_lane.model or "default",
        # Default per-call label for the TTFT callback: this run's agent tier,
        # so the graph's own streaming model calls attribute to comms/executor/
        # subagent instead of "unknown". Auxiliary calls (title/follow-up/memory)
        # go through ainvoke_llm, which overrides this with their finer label.
        LLM_LABEL_METADATA_KEY: agent_name,
    }
    _stamp_langfuse(
        configurable, metadata, effective_trace_id, effective_tags, user, conversation_id
    )

    config: AgentRunnableConfig = {
        # The one seam where the typed bag becomes LangGraph's untyped field:
        # RunnableConfig declares ``configurable: dict[str, Any]`` and merges its
        # own keys into it at runtime. Read it back with ``agent_configurable``.
        "configurable": cast(dict[str, Any], configurable),
        "recursion_limit": recursion_limit,
        "metadata": metadata,
        "callbacks": callbacks,
        "agent_name": agent_name,
    }
    return config


def build_initial_state(
    request: MessageRequestWithHistory,
    user_id: str,
    conversation_id: str,
    history: list[AnyMessage],
    # The trigger payload merged with the agent's own keys (active_todo_id,
    # execution_mode, workflow_*). Genuinely open: schedulers spread arbitrary
    # provider trigger data through it, so there is no fixed key set to model.
    trigger_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct the initial LangGraph state (query, history, tool selections, trigger context)."""
    state: dict[str, Any] = {
        "query": request.message,
        "intent": request.message,
        "messages": history,
        "current_datetime": datetime.now(UTC).isoformat(),
        "memory_user_id": user_id,
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


def _held_chunk_text(
    chunk: AIMessage,
    is_comms: bool,
    tool_call_message_ids: set[str],
) -> tuple[str, str]:
    """Return the chunk's message id plus the text to hold — "" when it is not a held reply."""
    message_id = chunk.id or ""
    if announces_tool_call(chunk):
        tool_call_message_ids.add(message_id)
    content = chunk.text
    if content and is_comms and message_id not in tool_call_message_ids:
        return message_id, content
    return message_id, ""


def _settle_message_boundary(
    messages: list[Any],
    is_comms: bool,
    complete_message: str,
    message_texts: dict[str, str],
    tool_call_message_ids: set[str],
) -> tuple[str, str | None, bool]:
    """Decide the fate of the message a node just produced: kept, or a handoff preamble.

    Returns the updated complete_message plus the boundary's message id
    (None when the node produced none) and whether it was discarded.
    """
    boundary = last_ai_message(messages) if is_comms else None
    if boundary is None:
        return complete_message, None, False
    boundary_id = boundary.id or ""
    held = message_texts.pop(boundary_id, "")
    discarded = boundary_id in tool_call_message_ids or announces_tool_call(boundary)
    if held and not discarded:
        complete_message = append_message_bubble(complete_message, held)
    return complete_message, boundary_id, discarded


async def _collect_silent_tool_entries(
    messages: list[Any],
    emitted_tool_calls: set[str],
    entries: list[Any],
    user_id: str | None,
) -> None:
    """Append a tool_data entry for each not-yet-emitted tool call in a node update."""
    for msg in messages:
        if not hasattr(msg, "tool_calls") or not msg.tool_calls:
            continue
        for tc in msg.tool_calls:
            tc_id = tc.get("id")
            if not tc_id or tc_id in emitted_tool_calls:
                continue

            # Look up metadata based on tool type
            tool_name = tc.get("name")
            tool_metadata: HandoffMetadata = {}

            # Todo tools already stream todo_progress; suppress tool_data noise.
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
                entries.append(tool_entry)
                emitted_tool_calls.add(tc_id)


def _accumulate_silent_custom_event(
    payload: Any,  # noqa: ANN401 -- the custom stream's payload is open per event
    message_texts: dict[str, str],
    todo_progress_accumulated: dict[str, Any],
    tool_data: dict[str, Any],
) -> None:
    """Fold one custom stream event into the silent run's accumulated tool data."""
    drop_retracted_text(payload, message_texts)
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
        tool_data.update({key: value for key, value in new_data.items() if key != "tool_data"})


@traceable(run_type="llm", name="Call Agent Silent")
def _hold_silent_chunk(
    payload: tuple[BaseMessage, dict[str, Any]],
    is_comms: bool,
    tool_call_message_ids: set[str],
    message_texts: dict[str, str],
) -> None:
    """One "messages"-mode event of a silent run: hold the chunk's text by message."""
    chunk, metadata = payload

    if metadata.get("silent"):
        return  # Skip silent chunks (e.g. follow-up actions generation)

    if chunk and isinstance(chunk, (AIMessage, AIMessageChunk)):
        message_id, held_text = _held_chunk_text(chunk, is_comms, tool_call_message_ids)
        if held_text:
            message_texts[message_id] = message_texts.get(message_id, "") + held_text


async def execute_graph_silent(
    graph: CompiledAgentGraph,
    initial_state: dict[str, Any],
    config: AgentRunnableConfig,
) -> tuple[str, dict[str, Any]]:
    """Execute LangGraph in silent mode, accumulating the full message and tool data.

    Used for background processing and workflow triggers that don't need streaming.
    Stores intermediate messages and tool outputs as they happen, like normal chat.
    Returns (complete_message, tool_data).
    """
    complete_message = ""
    tool_data: dict[str, Any] = {"tool_data": []}
    todo_progress_accumulated: dict[str, Any] = {}  # Accumulate todo_progress by source
    is_comms = config.get("agent_name") == "comms_agent"

    # Same message-scoped hold as execute_graph_streaming: text that turns out to
    # accompany a tool call is a handoff preamble, and the wire only reveals that
    # after the text has already been accumulated.
    message_texts: dict[str, str] = {}
    tool_call_message_ids: set[str] = set()

    # Track tool calls to avoid duplicate emissions (same as streaming)
    emitted_tool_calls: set[str] = set()

    # Get user_id for metadata lookup (not for storage - caller handles that)
    user_id = agent_configurable(config).get("user_id")

    # A list `stream_mode` plus `subgraphs=True` makes astream yield
    # (namespace, mode, payload) triples, which langgraph's own overload return
    # type does not express (same cast as subagent_runner's driver).
    silent_stream = cast(
        AsyncGenerator[tuple[tuple[str, ...], str, Any], None],
        graph.astream(
            initial_state,
            stream_mode=["messages", "custom", "updates"],
            config=config,
            subgraphs=True,
        ),
    )
    async for event in silent_stream:
        _ns, stream_mode, payload = event

        # Process "updates" events - same logic as execute_graph_streaming
        if stream_mode == "updates":
            for node_name, state_update in payload.items():
                # Only collect tool_data from the LLM node — pre-model hooks
                # produce updates containing historical messages with old tool_calls.
                if node_name != "agent":
                    continue
                if isinstance(state_update, dict) and "messages" in state_update:
                    await _collect_silent_tool_entries(
                        state_update["messages"],
                        emitted_tool_calls,
                        tool_data["tool_data"],
                        user_id,
                    )

                    complete_message, _boundary_id, _discarded = _settle_message_boundary(
                        state_update["messages"],
                        is_comms,
                        complete_message,
                        message_texts,
                        tool_call_message_ids,
                    )
            continue

        if stream_mode == "messages":
            _hold_silent_chunk(payload, is_comms, tool_call_message_ids, message_texts)

        elif stream_mode == "custom":
            _accumulate_silent_custom_event(
                payload, message_texts, todo_progress_accumulated, tool_data
            )

    complete_message = _flush_held_messages(complete_message, message_texts)

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


def _json_safe_tool_result(content: Any) -> Any:  # noqa: ANN401 -- framework contract
    """Return the raw tool result handed to an MCP-UI iframe, as JSON-serializable data.

    Inline media is text-extracted out, since media blocks are plain dicts that
    would otherwise ship a megabyte of base64 into the SSE event.
    """
    if has_media_blocks(content):
        return extract_text_content(content)
    try:
        json.dumps(content)
    except TypeError:
        model_dump = getattr(content, "model_dump", None)
        if callable(model_dump):
            return model_dump()
        if hasattr(content, "__dict__"):
            return dict(content.__dict__)
        return str(content)
    return content


@dataclass
class _StreamAccumulators:
    """The per-run state execute_graph_streaming threads through its stream handlers."""

    complete_message: str = ""
    # Emit the model-fallback notice at most once per stream
    fallback_emitted: bool = False
    message_texts: dict[str, str] = field(default_factory=dict)
    tool_call_message_ids: set[str] = field(default_factory=set)
    # Track tool calls to avoid duplicate emissions
    emitted_tool_calls: set[str] = field(default_factory=set)
    # Buffer MCP App UI metadata by tool_call_id for deferred emission
    # We detect UI metadata in "updates" but emit the mcp_app event in "messages"
    # when the ToolMessage arrives with the actual result.
    pending_mcp_apps: dict[str, dict[str, Any]] = field(default_factory=dict)
    # perf_counter of the first comms text yield in this run; None until then.
    # Only comms_agent text reaches the yield below, so executor runs never stamp.
    pipeline_ttft_perf: float | None = None


async def _emit_mcp_app_event(
    app_meta: dict[str, Any],
    tool_call_id: str,
    tool_result: Any,  # noqa: ANN401 -- the raw tool result, open per tool
    user_id: str | None,
    failure_message: str,
) -> AsyncGenerator[str, None]:
    """Fetch the MCP-UI resource and emit the deferred mcp_app frame for one tool call."""
    try:
        ui_resource = await fetch_mcp_ui_resource(
            server_url=app_meta["server_url"],
            resource_uri=app_meta["mcp_ui"]["resource_uri"],
            user_id=user_id or "",
        )
        html_content = ui_resource.get("html") if isinstance(ui_resource, dict) else None
        if html_content:
            content_csp = ui_resource.get("csp") if isinstance(ui_resource, dict) else None
            content_permissions = (
                ui_resource.get("permissions") if isinstance(ui_resource, dict) else None
            )
            yield format_sse_data(
                {
                    "tool_data": {
                        "tool_name": "mcp_app",
                        "tool_category": app_meta["tool_category"],
                        "data": {
                            "tool_call_id": tool_call_id,
                            "tool_name": app_meta["tool_name"],
                            "server_url": app_meta["server_url"],
                            "resource_uri": app_meta["mcp_ui"]["resource_uri"],
                            "html_content": html_content,
                            "tool_result": tool_result,
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
        log.warning(
            failure_message,
            error=str(_e),
            error_type=type(_e).__name__,
        )


def _model_fallback_frame(msg: Any) -> str | None:  # noqa: ANN401 -- any message on a node update
    """Return the model-downgrade frame (retry-then-fallback in ainvoke_llm), when this message has one."""
    if not isinstance(getattr(msg, "response_metadata", None), dict):
        return None
    metadata_rm = msg.response_metadata
    if not metadata_rm.get("gaia_fell_back"):
        return None
    return format_sse_data(
        ModelFallbackFrame(
            model_fallback={"model": metadata_rm.get("gaia_fallback_model", "")}
        ).model_dump()
    )


def _buffer_mcp_app(tool_entry: ToolDataEntry, pending_mcp_apps: dict[str, dict[str, Any]]) -> None:
    """Buffer an MCP App UI tool entry until its ToolMessage result arrives."""
    mcp_ui = tool_entry.get("mcp_ui")
    if tool_entry.get("tool_name") == "tool_calls_data" and mcp_ui and mcp_ui.get("resource_uri"):
        # ToolDataEntry["data"] is open per tool, but a tool_calls_data entry only
        # ever comes from format_tool_call_entry's ToolCallsDataEntryData dump.
        entry_data = cast(dict[str, Any], tool_entry["data"])
        tc_id_for_app = entry_data.get("tool_call_id", "")
        if tc_id_for_app:
            pending_mcp_apps[tc_id_for_app] = {
                "tool_category": tool_entry.get("tool_category", ""),
                "tool_name": entry_data.get("tool_name", ""),
                "server_url": tool_entry.get("mcp_server_url", ""),
                "mcp_ui": mcp_ui,
                "timestamp": tool_entry.get("timestamp"),
                "tool_arguments": entry_data.get("inputs", {}),
            }


async def _stream_tool_call_frames(
    msg: Any,  # noqa: ANN401 -- any message on a node update
    emitted_tool_calls: set[str],
    pending_mcp_apps: dict[str, dict[str, Any]],
    user_id: str | None,
) -> AsyncGenerator[str, None]:
    """Emit a tool_data frame for each not-yet-emitted tool call this message announces."""
    if not hasattr(msg, "tool_calls") or not msg.tool_calls:
        return
    for tc in msg.tool_calls:
        tc_id = tc.get("id")
        if not tc_id or tc_id in emitted_tool_calls:
            continue

        # Look up metadata based on tool type
        tool_name = tc.get("name")
        tool_metadata: HandoffMetadata = {}

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
            _buffer_mcp_app(tool_entry, pending_mcp_apps)


async def _stream_updates(
    payload: dict[str, Any],
    state: _StreamAccumulators,
    is_comms: bool,
    user_id: str | None,
) -> AsyncGenerator[str, None]:
    """Handle one "updates" event: model fallback, tool_data entries, message boundaries."""
    for node_name, state_update in payload.items():
        # Only emit tool_data from the LLM ("agent") node; pre-model hooks also
        # produce "updates" events carrying historical tool_calls that would
        # otherwise replay stale tool cards into the current SSE stream.
        if node_name != "agent":
            continue

        # Process tool entries with metadata lookup
        if isinstance(state_update, dict) and "messages" in state_update:
            for msg in state_update["messages"]:
                # Surface a model downgrade (retry-then-fallback in
                # ainvoke_llm) to the client, once per stream.
                if (
                    not state.fallback_emitted
                    and (fallback_frame := _model_fallback_frame(msg)) is not None
                ):
                    state.fallback_emitted = True
                    yield fallback_frame
                async for frame in _stream_tool_call_frames(
                    msg, state.emitted_tool_calls, state.pending_mcp_apps, user_id
                ):
                    yield frame

            # The node has finished, so the message's fate is decided (kept, or
            # a discarded handoff preamble); announce the boundary either way.
            state.complete_message, boundary_id, discarded = _settle_message_boundary(
                state_update["messages"],
                is_comms,
                state.complete_message,
                state.message_texts,
                state.tool_call_message_ids,
            )
            if boundary_id is not None:
                yield format_sse_data(
                    {
                        "message_boundary": MessageBoundaryPayload(
                            message_id=boundary_id, discarded=discarded
                        ).model_dump()
                    }
                )


async def _stream_tool_message_frames(
    chunk: ToolMessage,
    stream_id: str | None,
    pending_mcp_apps: dict[str, dict[str, Any]],
    user_id: str | None,
) -> AsyncGenerator[str, None]:
    """Emit the tool_output frame for a ToolMessage, plus any deferred mcp_app event."""
    # Todo tools already stream todo_progress; suppress tool_output noise.
    # Safe: doesn't affect agent state; only avoids redundant UI events.
    if chunk.name in {
        "plan_tasks",
        "update_tasks",
    } or chunk.additional_kwargs.get("todo_tool"):
        return
    # Text-extract block content so inline media (base64 image blocks)
    # never streams to the frontend or lands in the persisted message.
    tool_output_payload = ToolOutputPayload(
        tool_call_id=chunk.tool_call_id,
        output=extract_text_content(chunk.content),
    )
    # claim_tool_output dedups: the executor's own driver can see the same
    # ToolMessage while this comms stream is still open, so an ungated second
    # copy would render the card twice. The run that announced the call wins.
    if claim_tool_output(stream_id or "", chunk.tool_call_id):
        yield format_sse_data({"tool_output": tool_output_payload.model_dump(exclude_none=True)})

    # Emit deferred mcp_app event now that tool result is available
    app_meta = pending_mcp_apps.pop(chunk.tool_call_id, None)
    if app_meta:
        tool_result_payload = _json_safe_tool_result(chunk.content)
        async for frame in _emit_mcp_app_event(
            app_meta,
            chunk.tool_call_id,
            tool_result_payload,
            user_id,
            "Failed to emit mcp_app event",
        ):
            yield frame


async def _stream_messages(
    payload: tuple[Any, Any],
    state: _StreamAccumulators,
    is_comms: bool,
    stream_id: str | None,
    user_id: str | None,
) -> AsyncGenerator[str, None]:
    """Handle one "messages" event: streamed reply text, or a ToolMessage result."""
    chunk, metadata = payload
    if metadata.get("silent"):
        return

    # Stream AI response content (only from comms_agent to avoid duplication)
    if chunk and isinstance(chunk, (AIMessage, AIMessageChunk)):
        message_id, held_text = _held_chunk_text(chunk, is_comms, state.tool_call_message_ids)
        if held_text:
            if state.pipeline_ttft_perf is None:
                state.pipeline_ttft_perf = time.perf_counter()
            yield format_sse_response(held_text)
            state.message_texts[message_id] = state.message_texts.get(message_id, "") + held_text

    # Emit tool_output when ToolMessage arrives
    elif chunk and isinstance(chunk, ToolMessage):
        async for frame in _stream_tool_message_frames(
            chunk, stream_id, state.pending_mcp_apps, user_id
        ):
            yield frame


def _buffer_subagent_mcp_app(
    payload: Any,  # noqa: ANN401 -- the custom stream's payload is open per event
    pending_mcp_apps: dict[str, dict[str, Any]],
) -> None:
    """Intercept subagent tool_data events for MCP App detection.

    Custom MCP tools execute inside subagents and their events
    arrive here as "custom" stream events, not "updates"/"messages".
    """
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
                    "tool_name": sub_entry["data"].get("tool_name", ""),
                    "server_url": sub_entry.get("mcp_server_url", ""),
                    "mcp_ui": sub_entry["mcp_ui"],
                    "timestamp": sub_entry.get("timestamp"),
                    "tool_arguments": sub_entry["data"].get("inputs", {}),
                }


async def _stream_custom(
    payload: Any,  # noqa: ANN401 -- the custom stream's payload is open per event
    state: _StreamAccumulators,
    user_id: str | None,
) -> AsyncGenerator[str, None]:
    """Handle one "custom" event: forward it, then honour subagent MCP App metadata."""
    drop_retracted_text(payload, state.message_texts)
    yield f"data: {json.dumps(payload)}\n\n"

    _buffer_subagent_mcp_app(payload, state.pending_mcp_apps)

    # Intercept subagent tool_output events to emit deferred mcp_app
    if isinstance(payload, dict) and "tool_output" in payload:
        sub_output = payload["tool_output"]
        tc_id = sub_output.get("tool_call_id", "")
        app_meta = state.pending_mcp_apps.pop(tc_id, None)
        if app_meta:
            async for frame in _emit_mcp_app_event(
                app_meta,
                tc_id,
                sub_output.get("output"),
                user_id,
                "Failed to emit mcp_app from subagent",
            ):
                yield frame


async def _record_interruption_quietly(
    graph: CompiledAgentGraph, config: AgentRunnableConfig
) -> None:
    """Record the run's interruption; the cancel ack must still reach the client."""
    try:
        await record_interruption(graph, config)
    except Exception as e:  # the cancel ack must still reach the client
        log.error(
            f"{LogTag.AGENT} Failed to record interruption",
            error=str(e),
            error_type=type(e).__name__,
        )


def _parse_stream_event(event: tuple[Any, ...]) -> tuple[str, Any] | None:
    """Return the (mode, payload) of a stream event; handles the 2-tuple and 3-tuple shapes, else None.

    NOT traceable: decorating it as an llm run flooded LangSmith with one
    empty "Call Agent" root run per chunk (dozens/hundreds per turn).
    """
    if len(event) == 3:
        _ns, stream_mode, payload = event
        return stream_mode, payload
    if len(event) == 2:
        stream_mode, payload = event
        return stream_mode, payload
    return None


async def _frames_for_stream_event(
    event: tuple[Any, ...],
    state: _StreamAccumulators,
    is_comms: bool,
    stream_id: str | None,
    user_id: str | None,
) -> AsyncGenerator[str, None]:
    """Yield the SSE frames one langgraph stream event produces."""
    parsed = _parse_stream_event(event)
    if parsed is None:
        return
    stream_mode, payload = parsed
    if stream_mode == "updates":
        frames = _stream_updates(payload, state, is_comms, user_id)
    elif stream_mode == "messages":
        frames = _stream_messages(payload, state, is_comms, stream_id, user_id)
    elif stream_mode == "custom":
        frames = _stream_custom(payload, state, user_id)
    else:
        return
    async for frame in frames:
        yield frame


async def execute_graph_streaming(
    graph: CompiledAgentGraph,
    initial_state: dict[str, Any],
    config: AgentRunnableConfig,
) -> AsyncGenerator[str, None]:
    """Execute LangGraph in streaming mode, yielding SSE-formatted updates.

    Cancellable via stream_id in config (through stream_manager). Handles
    LangGraph's three stream modes: "updates" (tool_data), "messages"
    (text/tool_output), and "custom" (forwarded as-is).
    """
    stream_id = agent_configurable(config).get("stream_id")
    user_id = agent_configurable(config).get("user_id")
    is_comms = config.get("agent_name") == "comms_agent"

    # ``state.message_texts`` holds streamed text per message until known to be
    # a real reply, not a handoff preamble (text deltas precede tool-call deltas
    # on the wire). Keyed by message id since delegated-tier chunks interleave.
    state = _StreamAccumulators()

    cancelled = False
    graph_status = "success"
    run_start = time.perf_counter()
    # Yields (namespace, mode, payload) triples — occasionally (mode, payload)
    # pairs, handled below — and is a real async generator, so it supports
    # aclose(); langgraph's astream overloads express neither.
    stream = cast(
        AsyncGenerator[tuple[Any, ...], None],
        graph.astream(
            initial_state,
            stream_mode=["messages", "custom", "updates"],
            config=config,
            subgraphs=True,
        ),
    )
    with span() as elapsed_graph:
        try:
            async for event in stream:
                # Check for cancellation at each event
                if stream_id and await stream_manager.is_cancelled(stream_id):
                    cancelled = True
                    break
                async for frame in _frames_for_stream_event(
                    event, state, is_comms, stream_id, user_id
                ):
                    yield frame
        except GeneratorExit:
            # Abandoned mid-stream without cancellation (server shutdown path):
            # neither success nor cancelled, and neither label may claim it.
            graph_status = "abandoned"
            raise
        except Exception:
            graph_status = "error"
            raise
        finally:
            observe_comms_graph(
                elapsed_graph(), status=graph_status if not cancelled else "cancelled"
            )

    # A run that ends without its closing node update (cancellation, a graph that
    # never reaches the agent node again) still owes the user what it streamed.
    state.complete_message = _flush_held_messages(state.complete_message, state.message_texts)
    if state.pipeline_ttft_perf is not None:
        log.set(comms_pipeline_ttft_ms=round((state.pipeline_ttft_perf - run_start) * 1000.0, 2))

    if cancelled:
        # aclose() raises GeneratorExit at the run's yield point so LangGraph
        # cancels in-flight work and commits nothing further before the state
        # read by record_interruption.
        await stream.aclose()
        await _record_interruption_quietly(graph, config)
        yield (
            "nostream: "
            f"{json.dumps({'complete_message': state.complete_message, 'cancelled': True})}"
        )
        yield "data: [DONE]\n\n"
        return

    # Yield complete message for DB storage
    yield f"nostream: {json.dumps({'complete_message': state.complete_message})}"
    yield "data: [DONE]\n\n"
