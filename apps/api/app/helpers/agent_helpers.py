"""Core agent helpers: config building, state init, and graph execution (streaming and silent)."""

from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from pydantic import BaseModel, ConfigDict

from app.agents.llm.lane import AgentRole, ModelLane, inherits_lane, resolve_lane
from app.agents.llm.ttft import LLMTtftCallback
from app.config.langfuse import build_langfuse_callback
from app.constants.hil import HIL_JUDGE_MAX_TURN_CHARS
from app.constants.llm import (
    AGENT_RECURSION_LIMIT,
    DevModelOption,
)
from app.models.agent_models import (
    AgentConfigurable,
    AgentConfigurableView,
    AgentRunnableConfig,
    AgentUserContext,
    ExecutionMode,
    LlmCallMetadata,
    run_analytics_context,
)
from app.models.chat_models import ConversationSource, SourceCategory
from app.models.payment_models import PlanType
from app.models.presence_models import PresenceSnapshot
from app.services.delivery.presence import read_presence
from app.utils.general_utils import clip_text


class _AgentUser(BaseModel):
    """The ``AgentUserContext`` fields ``build_agent_config`` reads, parsed once.

    ``name`` defaults to ``""`` when absent and stays ``None`` when passed so —
    the two are distinguishable on the configurable, as they always were.
    """

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None
    email: str | None = None
    name: str | None = ""
    timezone: str | None = None


def _build_agent_callbacks(
    usage_metadata_callback: UsageMetadataCallbackHandler | None,
) -> list[BaseCallbackHandler]:
    """Assemble the LangChain callback list for an agent run (tracing, usage, TTFT).

    No PostHog handler: every model call reaches PostHog once, from its
    llm_calls ledger row (see llm_usage_analytics).
    """
    callbacks: list[BaseCallbackHandler] = []

    langfuse_callback = build_langfuse_callback()
    if langfuse_callback is not None:
        callbacks.append(langfuse_callback)

    if usage_metadata_callback:
        callbacks.append(usage_metadata_callback)

    # True provider first-token latency for every tier on this run.
    callbacks.append(LLMTtftCallback())

    return callbacks


@dataclass(slots=True, frozen=True)
class _TurnScope:
    """The turn-scoped configurable keys, before and after parent inheritance."""

    conversation_id: str
    session_id: str | None
    selected_tool: str | None
    tool_category: str | None
    subagent_id: str | None
    vfs_session_id: str | None
    active_todo_id: str | None
    conversation_source: str | None
    user_messages: list[str] | None
    user_request: str | None
    user_preferences: dict[str, object] | None
    writing_style: dict[str, object] | None
    execution_mode: ExecutionMode | None
    presence: PresenceSnapshot | None
    stream_id: str | None = None


def _inherit_from_parent_configurable(
    parent: AgentConfigurableView | None,
    current: _TurnScope,
) -> _TurnScope:
    """Merge current with optional inheritance from a parent agent's configurable.

    Fallback fields (tool/subagent/vfs/todo/mode/source/presence): child wins, parent
    fills blanks. stream_id always comes from parent. The model is NOT merged
    here — a child inherits its parent's lane whole (see build_agent_config).
    """
    if parent is None:
        return current

    return replace(
        current,
        # Parent overrides: the TRUE conversation id is established once by comms and
        # must survive child agents passing their own wrapped thread ids down as the
        # ``conversation_id`` argument (``executor_<conv>`` → ``<integ>_executor_<conv>``).
        conversation_id=parent.conversation_id or current.conversation_id,
        # Sticky-routing key, conversation-scoped: every agent in the tree must
        # hit the provider holding the conversation's warm cache.
        session_id=(
            parent.session_id if "session_id" in parent.model_fields_set else current.session_id
        ),
        # Parent overrides, same reason: the user's VERBATIM turns, established once
        # by comms. A child's own "task" is an agent-authored paraphrase, and the HIL
        # intent judge must check the tool call against what the user actually asked.
        user_messages=parent.user_messages or current.user_messages,
        user_request=parent.user_request or current.user_request,
        # Same rule, same reason: established once wherever the root call site had the
        # full user document in hand, and a child never has its own copy to prefer.
        user_preferences=parent.user_preferences or current.user_preferences,
        writing_style=parent.writing_style or current.writing_style,
        # Child wins; the parent only fills a blank. Written out per key rather than
        # driven by a table so each one is a checked attribute access.
        selected_tool=current.selected_tool or parent.selected_tool,
        tool_category=current.tool_category or parent.tool_category,
        subagent_id=current.subagent_id or parent.subagent_id,
        vfs_session_id=current.vfs_session_id or parent.vfs_session_id,
        active_todo_id=current.active_todo_id or parent.active_todo_id,
        conversation_source=current.conversation_source or parent.conversation_source,
        execution_mode=current.execution_mode or parent.execution_mode,
        presence=current.presence or parent.presence,
        stream_id=parent.stream_id,
    )


def background_authorization(
    turns: list[str],
    *,
    execution_mode: str,
    workflow_title: str = "",
    workflow_description: str = "",
    todo_title: str = "",
) -> list[str]:
    """Append a background run's schedule text as standing authorization.

    A scheduled workflow/todo is a standing directive, so its human-written
    display fields (title, description ONLY) authorize like a live turn's words —
    the judge grounds calls against them verbatim. Step lists and execution
    prompts may be LLM-generated and never authorize; interactive runs pass through.
    """
    if execution_mode != "background":
        return turns
    extra: list[str] = []
    title = workflow_title.strip()
    description = workflow_description.strip()
    if title or description:
        extra.append(
            "Scheduled workflow"
            + (f": {title}" if title else "")
            + (f". {description}" if description else "")
        )
    label = todo_title.strip()
    if label and not any(label in turn for turn in turns):
        extra.append(f"Tracked todo: {label}")
    if not extra:
        return turns
    return turns + [clip_text(text, HIL_JUDGE_MAX_TURN_CHARS) for text in extra]


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
    """Shared VFS session ID held constant across the executor and the
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

    workflow_id: str | None = None
    """The workflow this fire belongs to, on a top-level run only. Child runs
    inherit it from the parent's configurable."""

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

    presence: PresenceSnapshot | None = None
    """Where the user is, as captured by the interactive turn that started this tree.
    Inherited from the parent when omitted; a root run without one reads it."""


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
    metadata: dict[str, object],
    effective_trace_id: str | None,
    effective_tags: list[str] | None,
    user_id: str | None,
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
        if user_id:
            metadata["langfuse_user_id"] = user_id
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
        presence,
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
        turn.presence,
    )

    acting_user = _AgentUser.model_validate(user)
    parent = (
        AgentConfigurableView.model_validate(base_configurable)
        if base_configurable is not None
        else None
    )

    callbacks = _build_agent_callbacks(tracing.usage_metadata_callback)

    # The one seam every execution path crosses: a child inherits its parent's lane
    # whole (except comms' own lane), a top-level run resolves one here. An explicit
    # dev choice beats inheritance beats fresh.
    inherited_lane = ModelLane.from_configurable(parent.lane if parent else None)
    resolved_plan: PlanType | None = None
    if (
        lane.dev_option is None
        and inherited_lane is not None
        and inherits_lane(inherited_lane, lane.role)
    ):
        model_lane = inherited_lane
    else:
        model_lane, resolved_plan = await resolve_lane(
            acting_user.user_id, lane.role, lane.dev_option
        )

    current = _TurnScope(
        conversation_id=conversation_id,
        # OpenRouter sticky-routing key: pins every request of this
        # conversation to the provider holding its warm prompt cache
        # (see the routing note in constants/llm.py).
        session_id=conversation_id,
        selected_tool=selected_tool,
        tool_category=tool_category,
        subagent_id=subagent_id,
        vfs_session_id=vfs_session_id,
        active_todo_id=active_todo_id,
        conversation_source=source,
        user_messages=user_messages,
        user_request=user_request,
        user_preferences=user_preferences,
        writing_style=writing_style,
        execution_mode=execution_mode,
        presence=presence,
    )
    resolved = _inherit_from_parent_configurable(parent, current)

    # Captured by the interactive turn at the tree's root and inherited from there;
    # a root with none (a tracked todo run, a dev run) reads it here, the same
    # seam that resolves the lane. Comms roots read it in _core_agent_logic.
    resolved_presence = resolved.presence or (
        await read_presence(acting_user.user_id) if acting_user.user_id else None
    )

    # Explicit kwargs win over what was inherited from the parent's configurable.
    # `is not None` (not `or`) so callers can pass [] to intentionally clear tags.
    inherited = parent if parent is not None else AgentConfigurableView()
    effective_trace_id = (
        tracing.langfuse_trace_id
        if tracing.langfuse_trace_id is not None
        else inherited.langfuse_trace_id
    )
    effective_tags = (
        tracing.langfuse_tags if tracing.langfuse_tags is not None else inherited.langfuse_tags
    )

    # Specific channel (web/mobile/whatsapp/...) and its generalized category
    # (UI/Bot/BG). The channel falls back to "background" when unset because the
    # only callers that omit a source are the silent background paths.
    resolved_source = resolved.conversation_source
    source_channel = resolved_source or ConversationSource.BACKGROUND.value
    source_category = SourceCategory.from_source(resolved_source).value

    # The agent operates in the user's HOME timezone (IANA, DST-aware). Top-level
    # callers pass it on user.timezone; child agents reconstruct a bare user,
    # so they inherit the parent's zone from its configurable instead.
    home_timezone = (acting_user.timezone or "").strip()
    if not home_timezone and base_configurable:
        home_timezone = (inherited.user_timezone or "").strip()
    if not home_timezone:
        home_timezone = "UTC"

    # One id for the WHOLE user turn: generated at the top-level call and
    # inherited by every child agent, so the accounting middleware's aggregate
    # token counter binds across the tree instead of resetting per graph.
    root_request_id = inherited.root_request_id or str(uuid4())

    configurable: AgentConfigurable = {
        "thread_id": thread_id or conversation_id,
        # The TRUE conversation id (see _inherit_from_parent_configurable), NOT
        # recoverable from thread_id (the wrapped graph thread). HIL approvals,
        # notifications, and the executor queue read this key, never thread_id.
        "conversation_id": resolved.conversation_id,
        # The user's own verbatim turns (see build_agent_config). The HIL intent judge
        # reads these; child agents inherit them unchanged.
        "user_messages": resolved.user_messages,
        "user_request": resolved.user_request,
        "user_preferences": resolved.user_preferences,
        "writing_style": resolved.writing_style,
        "user_id": acting_user.user_id,
        "email": acting_user.email,
        "user_name": acting_user.name,
        "user_timezone": home_timezone,
        "root_request_id": root_request_id,
        "analytics_context": run_analytics_context(base_configurable or {}).model_dump(mode="json"),
        "presence": resolved_presence,
        # The decision, and its expansion into LangChain's binding keys. Only
        # ``lane`` is inherited by children; the binding keys are always
        # re-derived from it, so the two can never drift apart.
        "lane": model_lane.to_configurable(),
        "selected_tool": resolved.selected_tool,
        "tool_category": resolved.tool_category,
        "subagent_id": resolved.subagent_id,
        "vfs_session_id": resolved.vfs_session_id,
        "stream_id": resolved.stream_id,
        "active_todo_id": resolved.active_todo_id,
        "execution_mode": resolved.execution_mode or "interactive",
        "conversation_source": resolved_source,
        "source_category": source_category,
        # Re-emitted in the literal below (a fresh dict — a key dropped here
        # never reaches the graph config).
        "session_id": resolved.session_id,
    }

    # LangChain's binding keys, always re-derived from the lane so the two can
    # never drift apart.
    configurable.update(model_lane.binding_keys())

    # The budget wall reads plan_type to avoid a Redis lookup on the hot path.
    # Stamped from the same resolve_lane call that chose the model, and inherited
    # by children the way root_request_id is.
    if plan := (inherited.plan_type or (resolved_plan.value if resolved_plan else None)):
        configurable["plan_type"] = plan

    # A workflow fire stamps its workflow on the comms configurable; the executor
    # and its spawned subagents inherit it whole, the way root_request_id is.
    if workflow_id := inherited.workflow_id:
        configurable["workflow_id"] = workflow_id
        configurable["workflow_title"] = inherited.workflow_title
        configurable["workflow_notify_on_completion"] = inherited.workflow_notify_on_completion

    metadata: dict[str, object] = {
        "user_id": acting_user.user_id,
        "source_category": source_category,
        "source_channel": source_channel,
        # Read back as StreamChunkMetadata, telling a nested run's chunks from this run's own.
        "agent_thread_id": configurable["thread_id"],
        # Lane identity for the TTFT callback, which reads it back as LlmCallMetadata.
        # llm_label defaults to this run's agent tier so the graph's own streaming
        # calls never land on "unknown"; ainvoke_llm overrides it per side call.
        **LlmCallMetadata(
            lane_provider=model_lane.provider.value,
            lane_model=model_lane.model or "default",
            llm_label=identity.agent_name,
        ),
    }
    _stamp_langfuse(
        configurable,
        metadata,
        effective_trace_id,
        effective_tags,
        acting_user.user_id,
        conversation_id,
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
