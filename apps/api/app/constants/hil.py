"""HIL (human-in-the-loop) approval constants: policy, timings, frame names.

The destructive classification is NOT here — it lives on each tool in the tool
registry (app/agents/tools/core/registry.py), the single source of truth for
every tool in the app. See the ``destructive`` flag on ``Tool`` and the
classifier in ``app/services/hil/classification.py``.
"""

from app.constants.general import FINISH_TASK_NAME

# Launch switch: HIL is opt-in until this flips.
HIL_DEFAULT_ENABLED = False

# How long an approval waits before resolving as timeout. Well below typical
# stream lifetimes; the pending Redis key outlives the wait by the grace below.
HIL_APPROVAL_TIMEOUT_SECONDS = 900.0
HIL_REQUEST_TTL_GRACE_SECONDS = 60

# Orchestration/plumbing tools that must never be gated (they don't touch the
# outside world themselves; their inner tool calls are gated in the child graph).
# These are the only names hardcoded here — everything else is registry-driven.
HIL_EXEMPT_TOOLS: frozenset[str] = frozenset(
    {
        "retrieve_tools",
        "call_executor",
        "handoff",
        "spawn_subagent",
        FINISH_TASK_NAME,
        "plan_tasks",
        "update_tasks",
        "add_memory",
        "search_memory",
    }
)

# tool_data entry name for the approval card (mirrored in @gaia/shared/chat).
APPROVAL_REQUEST_TOOL_NAME = "approval_request"
APPROVAL_TOOL_CATEGORY = "hil"

# Ack text streamed when a chat message resolves a pending approval instead of
# starting a new turn.
HIL_ACK_APPROVED = "Got it — going ahead."
HIL_ACK_DENIED = "Understood — I won't do that."
