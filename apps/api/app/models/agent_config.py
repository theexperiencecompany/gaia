"""The shape of one agent run's ``config["configurable"]`` bag, and the typed
way to read it.

A leaf on purpose: it imports nothing from langchain, langgraph or the rest of
``app.models``, so ``app.utils.timezone`` — which every user model, and so every
test worker at collection time, pulls in — can read a run's home timezone
without dragging langchain's agent middleware (and the ~1.5 s ``transformers``
import behind it) along. ``app.models.agent_models`` re-exports everything here
under the same names, so consumers keep importing from there.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal, TypedDict, cast

from pydantic import BaseModel, ConfigDict

from app.constants.llm import LaneConfig, OpenRouterModelKwargs, OpenRouterReasoning

#: All home_timezone_from_config needs of a run config: a string-keyed mapping
#: it reads configurable out of. Naming RunnableConfig here pulled langchain_core
#: into every importer. RunnableConfig is a TypedDict and satisfies this.
AgentRunConfig = Mapping[str, object]

#: langgraph.constants.CONF, spelled out. Importing it would pull langgraph
#: into this leaf and undo the whole point of the module; the key is part of
#: LangGraph's public config shape. tests/meta pins the two together.
CONFIGURABLE_KEY = "configurable"


#: The execution mode a run is in. ``background`` runs have no user waiting on
#: them, which is what suppresses HIL pauses and the executor wake-up path.
ExecutionMode = Literal["interactive", "background"]


class SubagentKind(StrEnum):
    """Which delegation tool a subagent run came from — and so how it is rebuilt."""

    SPAWN = "spawn"
    MCP = "mcp"


class SubagentResumeItem(TypedDict):
    """How to rebuild a background subagent run, in any process, from what its tool was given.

    integration_id is the per-user MCP id for an MCP run, empty for a spawn;
    parent_configurable is the executor's configurable, persist-safe.
    """

    kind: SubagentKind
    tool_call_id: str
    task: str
    context: str
    integration_id: str
    inherited_tool_names: list[str]
    parent_configurable: "AgentConfigurable"


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
    #: The live turn's bot message id (a resumed HIL pause reconciles onto it). On an
    #: executor run, the message its frames render into and its background subagents fold into.
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
    lane: LaneConfig
    #: LangChain's own binding keys, written from ``lane`` and read ONLY by
    #: LangChain's field resolution — the expansion, not the decision.
    provider: str
    model: str
    model_kwargs: OpenRouterModelKwargs
    reasoning: OpenRouterReasoning

    # --- run scope ----------------------------------------------------------
    selected_tool: str | None
    tool_category: str | None
    #: True only for comms_narrator re-voicing a finished executor result. It never
    #: dispatches: call_executor refuses and the live status frame stays out, since
    #: the narrated run still holds the busy lock.
    is_result_narration: bool
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
    #: A pre-taken executor busy-lock the dispatch adopts instead of racing for
    #: a fresh one, so a queued/workflow fire hands its reservation to the run
    #: it starts. Keyed by ``WORKFLOW_LOCK_CONTEXT_KEY``.
    executor_lock_reservation: str | None

    # --- tracing ------------------------------------------------------------
    #: Stashed here so child agents spawned via ``asyncio.create_task`` re-emit
    #: the same trace from their own ``build_agent_config`` call.
    langfuse_trace_id: str
    langfuse_tags: list[str]

    # --- internal flags -----------------------------------------------------
    #: Set only on a HIL resume re-dispatch; the handoff tool probes it to tell
    #: a replayed call from a fresh one. Keyed by ``HIL_RESUME_CONFIG_KEY``.
    hil_resume_replay: bool
    #: Set only on a background subagent's own run: the recipe the HIL gate files
    #: on its approvals. Keyed by ``SUBAGENT_RESUME_CONFIG_KEY``.
    subagent_resume: SubagentResumeItem
    #: DEV-ONLY: the DEV_MODEL_OPTIONS key picked for the executor in the dev
    #: model switcher, since the executor builds its own configurable.
    dev_executor_model: str


def agent_configurable(config: AgentRunConfig | None) -> AgentConfigurable:
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
    return cast(AgentConfigurable, (config or {}).get(CONFIGURABLE_KEY) or {})


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


def read_agent_configurable(config: AgentRunConfig | None) -> AgentConfigurableView:
    """Return agent_configurable, parsed into AgentConfigurableView."""
    return AgentConfigurableView.model_validate(agent_configurable(config))
