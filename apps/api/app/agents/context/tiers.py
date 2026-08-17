"""The agent tiers that assemble a run context.

A tier is the unit a section declares applicability against, so it has to be a
closed set: a bare string would let a typo silently produce a tier no section
applies to, and the agent would run with an empty context rather than an error.
"""

from enum import StrEnum


class AgentTier(StrEnum):
    """Who is assembling context. One member per seeding call site."""

    #: User-facing front door. No work tools; narrates the executor's results.
    COMMS = "comms"
    #: Worker tier with the full registry, driven by ``call_executor``.
    EXECUTOR = "executor"
    #: Per-integration subagent reached through ``handoff``.
    PROVIDER_SUBAGENT = "provider_subagent"
    #: One-shot scratch worker from ``spawn_subagent``. Owns no todo list.
    SPAWN = "spawn"
    #: Authoring-only workflow drafter. Emits a draft; never executes one.
    WORKFLOW_AUTHORING = "workflow_authoring"


#: Every tier that runs work tools. They share the workspace-session banner and
#: the skills listing; comms has neither because it holds no file or shell tools.
WORKER_TIERS = frozenset(
    {
        AgentTier.EXECUTOR,
        AgentTier.PROVIDER_SUBAGENT,
        AgentTier.SPAWN,
        AgentTier.WORKFLOW_AUTHORING,
    }
)

ALL_TIERS = frozenset(AgentTier)
