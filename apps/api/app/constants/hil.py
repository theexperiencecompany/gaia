"""HIL (human-in-the-loop) approval constants: policy, timings, frame names.

The destructive classification is NOT here — it lives on each tool in the tool
registry (app/agents/tools/core/registry.py), the single source of truth for
every tool in the app. See the ``destructive`` flag on ``Tool`` and the
classifier in ``app/services/hil/classification.py``.
"""

from app.constants.general import FINISH_TASK_NAME

# The launch switch is ``HIL_DEFAULT_MODE`` in app/models/hil_models.py (the
# default mode is a HILPreferences field default, so it lives with the model).

# How many of the user's own turns the auto-mode intent judge sees, and how much of
# each. Intent routinely spans turns ("draft an email to Bob" … "looks good, send it"),
# so the latest message alone cannot be grounded against. Bounded because these ride in
# ``configurable`` — into checkpoints and queued run items. Only USER turns are carried:
# assistant text is deliberately withheld from the judge (see services/hil/intent.py).
HIL_JUDGE_MAX_USER_TURNS = 6
HIL_JUDGE_MAX_TURN_CHARS = 800

# How long an approval may sit unanswered before the sweep resolves it as a
# timeout. Nothing waits in-process for this — the paused run is checkpointed.
# Must stay well under the executor busy-lock TTL (30 min): expiring the
# approval is what releases the paused run's claim before the lock can lapse
# under a still-pending record.
HIL_APPROVAL_TIMEOUT_SECONDS = 900

# A decided record with no resumed_at stamp older than this is a crashed
# resume dispatch; the sweep re-dispatches it from the record's resume_item.
HIL_DECIDED_UNRESUMED_GRACE_SECONDS = 120

# The key LangGraph puts a paused run's Interrupt objects under in an "updates"
# stream event. Mirrored here because langgraph.constants.INTERRUPT went private
# in v1 (deprecated, slated for removal in v2).
LANGGRAPH_INTERRUPT_KEY = "__interrupt__"

# configurable flag set only on a resume re-dispatch. The handoff tool probes the
# subagent thread's checkpoint for a parked interrupt ONLY when this is set — a
# parked subagent can only exist on a resume replay, so fresh runs (the ~100%
# case) skip that per-handoff Postgres read entirely.
HIL_RESUME_CONFIG_KEY = "hil_resume_replay"

# How long a declined call is remembered so a retrying agent is auto-denied
# without re-prompting. Keyed by stream_id (unique per turn), so this only
# suppresses re-asks within the same turn — a genuinely new request in a later
# turn still prompts. Generous enough to outlast a long-running executor turn.
HIL_DECLINE_MEMORY_TTL_SECONDS = 1800

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
