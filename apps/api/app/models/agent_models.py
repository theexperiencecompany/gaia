"""Types for driving one LangGraph agent run: the config, the user it is built
from, and the middleware stack it runs under."""

from dataclasses import dataclass
from typing import Any, TypedDict, cast

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config

from app.constants.agents import AgentTag
from app.constants.comms import CommsDirectiveKind
from app.constants.hil import HIL_RESUME_CONFIG_KEY, SUBAGENT_RESUME_CONFIG_KEY

# The configurable bag's shape and its typed read live in app.models.agent_config,
# a leaf with no langchain import, so app.utils.timezone can read a home timezone
# without the middleware stack. Re-exported here, the import site consumers use.
from app.models.agent_config import (
    AgentConfigurable,
    AgentConfigurableView,
    AgentRunConfig,
    ExecutionMode,
    SubagentKind,
    SubagentResumeItem,
    agent_configurable,
    read_agent_configurable,
)
from app.models.chat_models import ToolDataEntry
from app.models.user_models import AuthenticatedUser

__all__ = [
    "CONFIGURABLE_OWNED_KEYS",
    "CONFIGURABLE_RUN_SCOPED_KEYS",
    "AgentConfigurable",
    "AgentConfigurableView",
    "AgentMiddlewareStack",
    "AgentRunConfig",
    "AgentRunnableConfig",
    "AgentUserContext",
    "AnyAgentMiddleware",
    "CommsDirective",
    "ExecutionMode",
    "InboxDrain",
    "InboxEntry",
    "RunningSubagent",
    "SilentRunResult",
    "SubagentKind",
    "SubagentResumeItem",
    "agent_configurable",
    "read_agent_configurable",
    "config_agent_name",
    "current_run_config",
    "runtime_configurable",
]

#: One entry of an agent's middleware stack. ``StateT`` is erased since a
#: stack is genuinely heterogeneous, but this still checks every entry IS an
#: ``AgentMiddleware``. Lives here since the stack factory and spawn-graph builder must not import each other.
AnyAgentMiddleware = AgentMiddleware[Any, Any, Any]

#: An agent's middleware stack, in execution order.
AgentMiddlewareStack = list[AnyAgentMiddleware]


class AgentUserContext(TypedDict, total=False):
    """The user fields ``build_agent_config`` reads — nothing more.

    Deliberately narrower than AuthenticatedUser, which agent_user_context
    narrows to it: only the top-level entries (chat, background narration) hold
    a real request auth context. Every child agent — executor, handoff
    subagents, spawn, the workflow author — reconstructs a bare identity bag
    from its parent's configurable, and typing those as AuthenticatedUser would
    claim they carry auth-path flags and the whole user document, which they
    do not.

    ``total=False`` because those child bags omit ``timezone`` (they inherit the
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


def current_run_config() -> RunnableConfig:
    """The active ``RunnableConfig`` for the current graph run.

    LangChain's middleware hooks are called as ``(state, runtime)`` and
    ``(request, handler)`` — neither hands the config in as a parameter.
    ``get_config()`` reads it from LangGraph's context-var, the same mechanism
    nodes use. Returns an empty config outside a runnable context, so callers on
    a sync fallback path never have to guard.
    """
    try:
        return get_config()
    except RuntimeError:
        return RunnableConfig()


def config_agent_name(config: RunnableConfig | None) -> str:
    """Return which agent a run belongs to for metric labels, "unknown" when unstamped.

    build_agent_config stamps agent_name at the top level, but LangGraph's
    ensure_config folds every non-standard top-level key into configurable
    before a node sees the config — so inside a graph the key only exists there.
    """
    configurable: AgentConfigurable = agent_configurable(config)
    return configurable.get("agent_name") or "unknown"


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


class LlmCallMetadata(TypedDict, total=False):
    """The run-metadata keys the TTFT callback reads off one LLM call.

    lane_* is stamped by build_agent_config for the whole run; llm_label by
    ainvoke_llm per call (under LLM_LABEL_METADATA_KEY).
    """

    lane_provider: str
    lane_model: str
    llm_label: str


class StreamChunkMetadata(TypedDict, total=False):
    """The run-metadata keys a messages-mode stream consumer reads off one chunk.

    silent is stamped by quiet LLM calls (llm/client.py, follow_up_actions_node) so their tokens never stream.
    """

    silent: bool


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


@dataclass(frozen=True)
class SilentRunResult:
    """What one ``call_agent_silent`` turn produced."""

    message: str
    tool_data: list[ToolDataEntry]


@dataclass(frozen=True, slots=True)
class InboxEntry:
    """One thing the executor has not been told yet.

    ``tag`` decides how it reads to the model: ordinary work is the user
    speaking, an interruption is the system reporting that a task was stopped.
    """

    id: str
    text: str
    tag: AgentTag = AgentTag.USER_INTERJECTION


@dataclass(frozen=True, slots=True)
class InboxDrain:
    """What a single drain pass decided to do."""

    inject: list[InboxEntry]
    retire: list[InboxEntry]

    def __bool__(self) -> bool:
        return bool(self.inject or self.retire)


@dataclass(frozen=True, slots=True)
class CommsDirective:
    """A parsed comms narration outcome. ``payload`` is the reply text, the silence
    reason, or the emoji, depending on ``kind``."""

    kind: CommsDirectiveKind
    payload: str


@dataclass(frozen=True, slots=True)
class RunningSubagent:
    """One subagent currently executing for a conversation.

    The stable, addressable handle the executor needs to steer or cancel a
    specific worker: ``subagent_id`` is what the executor names in
    ``message_subagent``/``cancel_subagent``; ``subagent_thread_id`` is the key
    its mailbox and cancel flag live under. ``stream_id`` is the stream whose stop
    ends the run; ``dispatched_by`` is the stream of the run that started it.
    """

    subagent_id: str
    subagent_thread_id: str
    integration_id: str
    agent_name: str
    task_summary: str
    started_at: str
    # Defaulted so a record written before these fields existed still decodes.
    stream_id: str | None = None
    dispatched_by: str | None = None


# What survives a queue hop / HIL resume. AgentConfigurable IS the allowlist; the
# hand-maintained list it replaced had fallen behind. LangGraph's runtime keys
# (checkpoint_ns, __pregel_*) are filtered by not being declared on it.
CONFIGURABLE_OWNED_KEYS: frozenset[str] = frozenset(AgentConfigurable.__annotations__)

# Owned keys scoped to ONE dispatch: hil_resume_replay ("this call is a replay") would
# make a fresh run probe for interrupts it cannot have; subagent_resume is one run's own.
CONFIGURABLE_RUN_SCOPED_KEYS: frozenset[str] = frozenset(
    {HIL_RESUME_CONFIG_KEY, SUBAGENT_RESUME_CONFIG_KEY}
)
