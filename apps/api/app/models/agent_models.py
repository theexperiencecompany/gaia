"""Types for driving one LangGraph agent run: the config, the user it is built
from, and the middleware stack it runs under."""

from typing import Any, TypedDict

from langchain.agents.middleware.types import AgentMiddleware
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


class AgentRunnableConfig(RunnableConfig):
    """What ``build_agent_config`` returns: a ``RunnableConfig`` plus ``agent_name``.

    ``agent_name`` is GAIA's own key, not LangGraph's — the graph drivers gate
    text accumulation on ``config["agent_name"] == "comms_agent"`` so only the
    user-facing agent's tokens reach the client. Subclassing rather than a
    parallel type keeps the value directly passable to ``graph.astream(config=...)``.

    ``configurable`` stays LangGraph's ``dict[str, Any]``. It is not narrowed to a
    TypedDict here because LangGraph merges its own keys into it at runtime and
    every consumer indexes it with computed keys; a TypedDict would also stop
    ``config["configurable"]`` flowing into the many helpers that take it
    (Type Safety item 14).
    """

    agent_name: str
