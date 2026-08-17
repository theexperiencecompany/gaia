"""Types for driving one LangGraph agent run: the config, the user it is built
from, and the middleware stack it runs under."""

from typing import Any, Literal, TypedDict, cast

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.runnables import RunnableConfig

#: One entry of an agent's middleware stack.
#:
#: ``AgentMiddleware``'s ``StateT`` is erased here because a stack is genuinely
#: heterogeneous — ``SubagentMiddleware`` is typed over ``SubagentState``, the
#: rest over the base ``AgentState`` — and ``StateT`` is invariant, so no
#: narrower common element type exists. This still checks that every entry IS an
#: ``AgentMiddleware``, which the ``Any`` it replaces did not.
#:
#: It lives here, rather than beside the factory that builds stacks, because
#: both that factory and the spawn-graph builder that consumes one need it, and
#: those two must not import each other (see ``spawn_agent``'s module docstring).
AnyAgentMiddleware = AgentMiddleware[Any, Any, Any]

#: An agent's middleware stack, in execution order.
AgentMiddlewareStack = list[AnyAgentMiddleware]


class AgentUserContext(TypedDict, total=False):
    """The user fields ``build_agent_config`` reads — nothing more.

    Deliberately narrower than :class:`~app.models.user_models.AuthenticatedUser`,
    which is assignable to it: only the top-level entries (chat, background
    narration) hold a real request auth context. Every child agent — executor,
    handoff subagents, spawn, the workflow author — reconstructs a bare identity
    bag from its parent's ``configurable``, and typing those as
    ``AuthenticatedUser`` would claim they carry auth-path flags and the whole
    user document, which they do not.

    ``total=False`` because those child bags omit ``timezone`` (they inherit the
    resolved zone from the parent configurable instead).
    """

    user_id: str
    email: str | None
    name: str | None
    timezone: str | None


#: The execution mode a run is in. ``background`` runs have no user waiting on
#: them, which is what suppresses HIL pauses and the executor wake-up path.
ExecutionMode = Literal["interactive", "background"]


class AgentConfigurable(TypedDict, total=False):
    """Every key GAIA puts in a run's ``config["configurable"]`` — the whole agreement.

    This is the one place the bag is described. Anything an agent, tool,
    middleware or node expects to find in ``configurable`` is declared here, so
    a reader can answer "what is actually in this thing" without grepping, and
    mypy rejects a subscript for a key nobody writes.

    ``total=False`` is the honest shape, not a shortcut. ``build_agent_config``
    is the main producer and fills nearly all of it, but several paths
    legitimately construct a partial bag — a bare ``{"thread_id": ...}`` to
    address a checkpoint, ``{"user_id": ...}`` for a one-off silent run, the
    queue's serializable subset — and every consumer already reads through
    ``.get()`` with a fallback.

    It stays a ``TypedDict`` over a plain dict (not a Pydantic model) because
    LangGraph owns the object at runtime: it merges its own keys in
    (``checkpoint_ns``, ``checkpoint_id``, ``__pregel_*``), passes it to
    ``llm.with_config(configurable=...)``, and checkpoints it. Declaring the
    GAIA-owned keys describes that bag without trying to own it — read
    :func:`agent_configurable` for how consumers get here from a
    ``RunnableConfig``.
    """

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
    user_message_id: str
    #: The live comms turn's own bot message id (chat stream's ``state.bot_message_id``).
    #: Threaded into ``call_executor`` so a HIL pause that later resumes can reconcile
    #: its result onto this SAME message instead of minting a rival one — see
    #: ``ExecutorRun.bot_message_id`` and ``executor_runner._record_pause``.
    bot_message_id: str
    #: Onboarding preferences / writing style, established once at the root of
    #: a run tree (wherever a full user document is already in hand — comms,
    #: background narration, the dev direct-invoke entrypoint) and inherited
    #: unchanged by every child agent, same as ``user_messages``. Absent when
    #: the root itself had none; the context sections that read them degrade
    #: to no section rather than guessing.
    user_preferences: dict[str, Any] | None
    writing_style: dict[str, Any] | None
    #: One id for the WHOLE user turn: minted at the top-level
    #: ``build_agent_config`` call and inherited by every child agent (executor,
    #: handoff subagents, spawn loops). The accounting middleware keys the
    #: request tree's aggregate token ceiling on it, so the per-request ceiling
    #: binds across the tree instead of resetting per graph.
    root_request_id: str

    # --- model selection ----------------------------------------------------
    #: THE model selection: a serialized :class:`~app.agents.llm.lane.ModelLane`,
    #: resolved once per turn and inherited verbatim by every child agent, queue
    #: hop and HIL resume. **This is the only model key GAIA code reads.**
    #:
    #: Absent on a bag written before lanes existed (an in-flight queue item, a
    #: stored HIL ``resume_item``); ``ModelLane.from_configurable`` returns
    #: ``None`` for those and the caller resolves a fresh lane.
    lane: dict[str, Any]
    #: LangChain's own binding keys, written from the lane by
    #: ``build_agent_config`` and read ONLY by LangChain's field resolution:
    #: ``provider`` selects the configurable_alternative, the rest are
    #: ConfigurableFields. Never read these in GAIA code — they are the
    #: expansion, not the decision. Read ``lane``.
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
    stream_id: str | None
    active_todo_id: str | None
    execution_mode: ExecutionMode
    #: The specific channel (``ConversationSource`` value) and its generalized
    #: category (``SourceCategory`` value).
    conversation_source: str | None
    source_category: str
    #: The user's resolved plan tier (``PlanType`` value), stamped by
    #: ``resolve_lane`` on the top-level configurable and inherited by
    #: children. The accounting middleware's budget wall reads it to avoid a
    #: Redis plan lookup on the hot path; absent, the wall derives the tier
    #: from the cached plan itself.
    plan_type: str

    # --- workflow context (must survive queueing) ---------------------------
    workflow_id: str
    workflow_title: str
    workflow_notify_on_completion: bool

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
    #: model switcher. The executor builds its own configurable rather than
    #: inheriting comms's lane wholesale, so the choice rides down here.
    dev_executor_model: str


def agent_configurable(config: RunnableConfig | None) -> AgentConfigurable:
    """The GAIA-owned keys of a run's ``configurable``, typed.

    The single way to READ a ``configurable``. Every consumer used to inline
    ``config.get("configurable", {}).get(key)``, which yields ``Any`` and so
    checks neither the key nor the value type.

    A ``cast`` rather than a validation step: the dict is built by
    ``build_agent_config`` as an :class:`AgentConfigurable` and is correct by
    construction (Type Safety item 12). LangGraph's own runtime keys ride along
    in the same dict and are simply not part of this view.

    Reads only. The ``or {}`` means a config with no ``configurable`` yields a
    throwaway dict, so a write through it would be silently dropped — the few
    sites that mutate a live bag index ``config["configurable"]`` directly and
    keep today's ``KeyError`` when it is absent.
    """
    return cast(AgentConfigurable, (config or {}).get("configurable") or {})


def runtime_configurable(request: ToolCallRequest) -> AgentConfigurable:
    """The same view as :func:`agent_configurable`, reached through a middleware
    ``ToolCallRequest``.

    A tool intercepted by middleware gets its config off ``request.runtime``
    rather than as an injected ``RunnableConfig``, and that attribute is typed
    loosely enough that it may not be a mapping at all — hence the guard.
    Returns an empty view outside a graph.
    """
    runtime = getattr(request, "runtime", None)
    config = getattr(runtime, "config", None)
    if not isinstance(config, dict):
        return {}
    return agent_configurable(cast(RunnableConfig, config))


class AgentRunnableConfig(RunnableConfig):
    """What ``build_agent_config`` returns: a ``RunnableConfig`` plus ``agent_name``.

    ``agent_name`` is GAIA's own key, not LangGraph's — the graph drivers gate
    text accumulation on ``config["agent_name"] == "comms_agent"`` so only the
    user-facing agent's tokens reach the client. Subclassing rather than a
    parallel type keeps the value directly passable to ``graph.astream(config=...)``.

    ``configurable`` keeps LangGraph's ``dict[str, Any]`` annotation because a
    TypedDict field cannot be narrowed in a subclass without making the result
    unassignable to ``RunnableConfig`` — which is the whole point of
    subclassing. :class:`AgentConfigurable` names what is inside it, and
    :func:`agent_configurable` is how you read it.
    """

    agent_name: str
