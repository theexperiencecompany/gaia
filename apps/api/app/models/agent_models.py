"""Types for driving one LangGraph agent run: the config, the user it is built
from, and the middleware stack it runs under."""

from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config
from langgraph.constants import CONF
from pydantic import BaseModel, ConfigDict

from app.models.chat_models import ToolDataEntry
from app.models.user_models import AuthenticatedUser

#: One entry of an agent's middleware stack. ``StateT`` is erased since a
#: stack is genuinely heterogeneous, but this still checks every entry IS an
#: ``AgentMiddleware``. Lives here since the stack factory and spawn-graph builder must not import each other.
AnyAgentMiddleware = AgentMiddleware[Any, Any, Any]

#: An agent's middleware stack, in execution order.
AgentMiddlewareStack = list[AnyAgentMiddleware]


class AgentUserContext(TypedDict, total=False):
    """The user fields build_agent_config reads — nothing more.

    Deliberately narrower than AuthenticatedUser, which agent_user_context
    narrows to it: only the top-level entries (chat, background narration) hold
    a real request auth context. Every child agent — executor, handoff
    subagents, spawn, the workflow author — reconstructs a bare identity bag
    from its parent's configurable, and typing those as AuthenticatedUser would
    claim they carry auth-path flags and the whole user document, which they
    do not.

    total=False because those child bags omit timezone (they inherit the
    resolved zone from the parent configurable instead).
    """

    user_id: str
    email: str | None
    name: str | None
    timezone: str | None


def agent_user_context(user: AuthenticatedUser) -> AgentUserContext:
    """Narrow an AuthenticatedUser to the identity bag a top-level run hands build_agent_config.

    The ONE place that narrowing happens.
    """
    return {
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "timezone": user.timezone,
    }


#: The execution mode a run is in. ``background`` runs have no user waiting on
#: them, which is what suppresses HIL pauses and the executor wake-up path.
ExecutionMode = Literal["interactive", "background"]


class AgentConfigurable(TypedDict, total=False):
    """Every key GAIA puts in a run's config["configurable"] — the whole agreement.

    total=False is the honest shape: build_agent_config fills nearly all of
    it, but several paths legitimately construct a partial bag, and every
    consumer already reads through .get() with a fallback. A TypedDict, not
    a Pydantic model, since LangGraph owns the runtime object (merges in its
    own keys, checkpoints it) — this only describes the GAIA-owned keys.
    """

    # Stamped at the top level by build_agent_config and folded in here by
    # LangGraph's ensure_config before a node runs.
    agent_name: str

    # --- identity: who and which conversation ------------------------------
    #: LangGraph's checkpoint thread. For child agents this is the WRAPPED
    #: thread (``<integration>_executor_<conv>``), never the conversation id.
    thread_id: str
    #: The TRUE conversation id, established once by comms and inherited
    #: parent-overrides. HIL approvals, notifications and the executor queue
    #: key on this, never on ``thread_id``.
    conversation_id: str
    user_id: str | None
    email: str | None
    user_name: str
    #: IANA home zone, DST-aware. Read via ``home_timezone_from_config``.
    user_timezone: str
    #: The user's own recent turns, verbatim and oldest first. The HIL intent
    #: judge grounds gated calls against these, so they are never an agent's
    #: paraphrase of the request.
    user_messages: list[str] | None
    #: The live turn's request, exactly as typed and NOT clipped (unlike
    #: ``user_messages``, which is capped per turn). Established once by comms
    #: and inherited parent-overrides. Absent for non-chat roots.
    user_request: str | None
    user_message_id: str
    #: The live comms turn's own bot message id. Threaded into ``call_executor``
    #: so a resumed HIL pause reconciles onto this SAME message, not a new one.
    bot_message_id: str
    #: Onboarding preferences / writing style, established once at a run tree's
    #: root and inherited unchanged by every child agent. Absent when the root
    #: had none; the context sections that read them degrade to no section.
    user_preferences: dict[str, Any] | None
    writing_style: dict[str, Any] | None
    #: One id for the WHOLE user turn, minted at the top-level
    #: ``build_agent_config`` call and inherited by every child agent, so the
    #: accounting middleware's token ceiling binds across the tree.
    root_request_id: str

    # --- model selection ----------------------------------------------------
    #: THE model selection, resolved once per turn and inherited verbatim.
    #: **This is the only model key GAIA code reads.**
    lane: dict[str, Any]
    #: LangChain's own binding keys, written from ``lane`` and read ONLY by
    #: LangChain's field resolution — the expansion, not the decision.
    provider: str
    model: str
    model_kwargs: dict[str, Any]
    reasoning: dict[str, Any]

    # --- run scope ----------------------------------------------------------
    selected_tool: str | None
    tool_category: str | None
    subagent_id: str | None
    #: Shared VFS session, held constant across the executor and the handoff
    #: subagents it spawns so all resolve paths against one workspace.
    vfs_session_id: str | None
    #: OpenRouter sticky-routing key — the conversation id, pinned on every
    #: request so OpenRouter routes the whole conversation tree to the
    #: provider holding the warm prompt cache (see build_agent_config).
    session_id: str | None
    stream_id: str | None
    active_todo_id: str | None
    execution_mode: ExecutionMode
    #: The specific channel (``ConversationSource`` value) and its generalized
    #: category (``SourceCategory`` value).
    conversation_source: str | None
    source_category: str
    #: The user's resolved plan tier, stamped by ``resolve_lane`` and inherited
    #: by children; the budget wall reads it to avoid a Redis lookup, and
    #: derives the tier from the cached plan itself when absent.
    plan_type: str

    # --- workflow context (must survive queueing) ---------------------------
    workflow_id: str
    workflow_title: str
    workflow_notify_on_completion: bool
    #: A playbook replay stopped partway and the agent is finishing it: the
    #: replay's own record of what already ran, carried verbatim to the
    #: executor since comms can't be trusted to transcribe it into its task.
    playbook_fallback: str | None
    #: The calls a stopped replay made this fire, as ``RecordedCall`` dumps, so a
    #: rewrite may freeze them. See ``PLAYBOOK_REPLAYED_CALLS_KEY``.
    playbook_replayed_calls: list[dict[str, Any]] | None

    # --- tracing ------------------------------------------------------------
    #: Stashed here so child agents spawned via ``asyncio.create_task`` re-emit
    #: the same trace from their own ``build_agent_config`` call.
    langfuse_trace_id: str
    langfuse_tags: list[str]

    # --- internal flags -----------------------------------------------------
    #: Set only on a HIL resume re-dispatch; the handoff tool probes it to tell
    #: a replayed call from a fresh one. Keyed by ``HIL_RESUME_CONFIG_KEY``.
    hil_resume_replay: bool
    #: DEV-ONLY: the DEV_MODEL_OPTIONS key picked for the executor in the dev
    #: model switcher, since the executor builds its own configurable.
    dev_executor_model: str


def current_run_config() -> RunnableConfig:
    """Return the active RunnableConfig for the current graph run.

    LangChain's middleware hooks don't hand the config in as a parameter, so
    this reads it from LangGraph's context-var instead. Returns an empty
    config outside a runnable context, so callers never have to guard.
    """
    try:
        return get_config()
    except RuntimeError:
        return RunnableConfig()


def agent_configurable(config: RunnableConfig | None) -> AgentConfigurable:
    """Return the GAIA-owned keys of a run's configurable, typed — the single way to READ one.

    A cast, not a validation step: the dict is built by build_agent_config
    and correct by construction. Reads only — the or {} means a write
    through the result would be silently dropped.
    """
    return cast(AgentConfigurable, (config or {}).get(CONF) or {})


class AgentConfigurableView(BaseModel):
    """The GAIA-owned keys of a ``configurable``, parsed once for attribute reads.

    :class:`AgentConfigurable` describes the live bag LangGraph owns; this is
    how a consumer READS it, instead of guessing at string keys. Every field is
    optional because the bag may be partial (see ``AgentConfigurable``); the two
    workflow defaults match what ``build_agent_config`` writes for a workflow
    run. ``model_fields_set`` still tells an absent key from one carried as
    ``None`` where that matters (``session_id`` inheritance).
    """

    model_config = ConfigDict(extra="ignore")

    thread_id: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    email: str | None = None
    user_name: str | None = None
    user_timezone: str | None = None
    user_messages: list[str] | None = None
    user_request: str | None = None
    user_preferences: dict[str, object] | None = None
    writing_style: dict[str, object] | None = None
    root_request_id: str | None = None
    lane: dict[str, object] | None = None
    #: LangChain's binding key — logged, never used to pick a model (read ``lane``).
    model: str | None = None
    selected_tool: str | None = None
    tool_category: str | None = None
    subagent_id: str | None = None
    vfs_session_id: str | None = None
    stream_id: str | None = None
    active_todo_id: str | None = None
    execution_mode: ExecutionMode | None = None
    conversation_source: str | None = None
    source_category: str | None = None
    plan_type: str | None = None
    workflow_id: str | None = None
    workflow_title: str = ""
    workflow_notify_on_completion: bool = True
    langfuse_trace_id: str | None = None
    langfuse_tags: list[str] | None = None


def read_agent_configurable(config: RunnableConfig | None) -> AgentConfigurableView:
    """Return agent_configurable, parsed into AgentConfigurableView."""
    return AgentConfigurableView.model_validate(agent_configurable(config))


def config_agent_name(config: RunnableConfig | None) -> str:
    """Return which agent a run belongs to for metric labels, "unknown" when unstamped.

    build_agent_config stamps agent_name at the top level, but LangGraph's
    ensure_config folds every non-standard top-level key into configurable
    before a node sees the config — so inside a graph the key only exists there.
    """
    configurable: AgentConfigurable = agent_configurable(config)
    return configurable.get("agent_name") or "unknown"


def runtime_configurable(request: ToolCallRequest) -> AgentConfigurable:
    """Same view as agent_configurable, reached through a middleware ToolCallRequest.

    request.runtime.config is typed loosely enough that it may not be a
    mapping at all, hence the guard; returns an empty view outside a graph.
    """
    runtime = getattr(request, "runtime", None)
    config = getattr(runtime, "config", None)
    if not isinstance(config, dict):
        return {}
    return agent_configurable(cast(RunnableConfig, config))


class LlmCallMetadata(TypedDict, total=False):
    """The run-metadata keys the TTFT callback reads off one LLM call.

    lane_* is stamped by build_agent_config for the whole run; llm_label by
    ainvoke_llm per call (under LLM_LABEL_METADATA_KEY).
    """

    lane_provider: str
    lane_model: str
    llm_label: str


class AgentRunnableConfig(RunnableConfig):
    """What build_agent_config returns: a RunnableConfig plus agent_name.

    agent_name is GAIA's own key, not LangGraph's — the graph drivers gate
    text accumulation on config["agent_name"] == "comms_agent" so only the
    user-facing agent's tokens reach the client. Subclassing rather than a
    parallel type keeps the value directly passable to graph.astream(config=...).

    configurable keeps LangGraph's dict[str, Any] annotation because a
    TypedDict field cannot be narrowed in a subclass without making the result
    unassignable to RunnableConfig — which is the whole point of
    subclassing. :class:AgentConfigurable names what is inside it, and
    :func:agent_configurable is how you read it.
    """

    agent_name: str


@dataclass(frozen=True)
class SilentRunResult:
    """What one call_agent_silent turn produced.

    queued_task_id is set when the turn's comms agent delegated to the
    executor and that dispatch was QUEUED behind an in-flight run for the same
    conversation instead of running. The message is then an acknowledgement
    of work that has not started, so a caller must not record the turn as work
    done. It is None whenever an executor actually ran.
    """

    message: str
    tool_data: list[ToolDataEntry]
    queued_task_id: str | None = None
    #: The executor this turn delegated to ended in an error. ``message`` is
    #: then comms' account of that error, not a result; ``executor_failure``
    #: is the error itself, or why the wait for it gave up.
    executor_failed: bool = False
    executor_failure: str | None = None
