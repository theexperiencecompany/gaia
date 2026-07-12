"""HIL (human-in-the-loop) approval constants: policy, timings, limits, frame names.

Every tunable number the HIL services use lives here. The LLM-facing *text* lives in
``app/services/hil/prompts.py``; the destructive classification lives on each tool in
the tool registry (``app/agents/tools/core/registry.py``), the single source of truth
for every tool in the app.
"""

from typing import Literal

from app.constants.general import FINISH_TASK_NAME

# The launch switch is ``HIL_DEFAULT_MODE`` in app/models/hil_models.py (the
# default mode is a HILPreferences field default, so it lives with the model).

# --- auto mode: what the intent judge is shown ---------------------------------------
#
# How many of the user's own turns the judge sees, and how much of each. Intent routinely
# spans turns ("draft an email to Bob" … "looks good, send it"), so the latest message
# alone cannot be grounded against. Bounded because these ride in ``configurable`` — into
# checkpoints and queued run items. Only USER turns are carried: assistant text is
# deliberately withheld from the judge (see services/hil/intent.py).
HIL_JUDGE_MAX_USER_TURNS = 6
HIL_JUDGE_MAX_TURN_CHARS = 800

# The pending call's arguments, and the run's earlier tool calls (the provenance for
# arguments the agent derived rather than the user dictating).
HIL_JUDGE_MAX_ARGS_CHARS = 1500
HIL_JUDGE_MAX_PRIOR_CALLS = 8
HIL_JUDGE_MAX_PRIOR_ARGS_CHARS = 200

# Bytes of randomness in the fence around untrusted content in the judge prompt. Fixed
# tags are guessable from a leaked prompt and can simply be closed by an attacker.
HIL_JUDGE_NONCE_BYTES = 6

# The floor on an authorizing quote. Grounding is what stops a lenient judge approving on
# words the user never wrote — but a one-word quote ("yes", "ok", "it") appears somewhere
# in almost any conversation, so requiring only a non-empty substring is close to
# requiring nothing. A quote must carry enough of the request to identify the action.
#
# This deliberately errs toward asking: a terse "email bob" no longer grounds on its own.
# That is the safe direction, and it matches the prompt's own instruction — for "send it",
# the authorizing words live in the earlier turn that said what "it" is.
HIL_JUDGE_MIN_QUOTE_WORDS = 3

# --- resume ---------------------------------------------------------------------------
#
# The only statuses a ``Command(resume=...)`` payload may carry. Anything else is treated
# as a denial — an approval must never be inferred from a malformed payload. "abandoned"
# is absent by design: resolution.py maps it to a deny before sending.
HIL_RESUMABLE_STATUSES: frozenset[str] = frozenset({"approved", "denied", "timeout"})

# --- approval card summary -------------------------------------------------------------
#
# How much of a call's arguments the deterministic one-line summary shows.
HIL_SUMMARY_MAX_ARGS = 2
HIL_SUMMARY_MAX_ARG_CHARS = 60

# Marks a synthetic ToolMessage the gate produced (rather than a real tool result).
HIL_STATUS_KWARG = "hil_status"
HILToolMessageStatus = Literal["denied", "timeout", "error"]

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
