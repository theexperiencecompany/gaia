"""HIL (human-in-the-loop) approval constants: policy, timings, limits, frame names.

Every tunable number the HIL services use lives here. The LLM-facing *text* lives in
app/services/hil/prompts.py; the destructive classification lives on each tool in
the tool registry (app/agents/tools/core/registry.py), the single source of truth
for every tool in the app.
"""

from typing import Final, Literal

from app.constants.cache import EXECUTOR_BUSY_TTL
from app.constants.general import FINISH_TASK_NAME, WAIT_FOR_SUBAGENTS_NAME

# The launch switch is ``HIL_DEFAULT_MODE`` in app/models/hil_models.py (the
# default mode is a HILPreferences field default, so it lives with the model).

# auto mode: what the intent judge is shown. Intent routinely spans turns
# ("draft an email to Bob" ... "looks good, send it"), so the latest message
# alone cannot be grounded against. Only USER turns are carried; bounded because these ride in `configurable`.
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

# The floor on an authorizing quote: a one-word quote ("yes", "ok") appears
# almost anywhere, so requiring only a non-empty substring is close to nothing.
# Errs toward asking — a terse "email bob" no longer grounds on its own.
HIL_JUDGE_MIN_QUOTE_WORDS = 3

# Wall-clock bound on every HIL LLM call (classification, intent judge,
# conversational resolver) — these sit on user-blocking paths the
# tool-execution timeout does not cover. Unbounded, a hung provider holds the executor's busy lock forever.
HIL_LLM_TIMEOUT_SECONDS = 30

# The only statuses a `Command(resume=...)` payload may carry. Anything else
# is treated as a denial. "abandoned" is absent: resolution.py maps it to a deny before sending.
HIL_RESUMABLE_STATUSES: frozenset[str] = frozenset({"approved", "denied", "timeout"})

# Statuses meaning "decided, so the paused run must be re-dispatched" — the
# sweep's crashed-resume pass matches on these. "auto_approved" is absent: it
# never paused, so it has no run to resume.
HIL_UNRESUMED_SWEEP_STATUSES: tuple[str, ...] = ("approved", "denied", "timeout", "abandoned")

# How much of a call's arguments the deterministic one-line summary shows.
HIL_SUMMARY_MAX_ARGS = 2
HIL_SUMMARY_MAX_ARG_CHARS = 60

# The classifier reading a chat reply to a pending approval gets richer context
# than the card summary: recent turns + the full (bounded) args. TOTAL budget
# is the real ceiling; the per-value clip only stops one pathological arg from eating it all.
HIL_CLASSIFIER_MAX_ARG_CHARS = 4000  # per-value clip — a full typical email/message body fits
HIL_CLASSIFIER_MAX_DETAIL_CHARS = 8000  # total budget for one action's rendered detail
HIL_CLASSIFIER_MAX_ARGS = 8  # include non-scalar args too, as compact JSON
HIL_CLASSIFIER_HISTORY_TURNS = 4  # recent {role, content} turns of context

# Marks a synthetic ToolMessage the gate produced (rather than a real tool result).
HIL_STATUS_KWARG = "hil_status"
HILToolMessageStatus = Literal["denied", "timeout", "error", "already_ran"]

# How long an approval may sit unanswered before the sweep resolves it as a
# timeout. Set by how long a human plausibly takes to answer a push
# notification, NOT infrastructure — HIL gates irreversible, third-party-visible actions.
HIL_APPROVAL_TIMEOUT_SECONDS = 6 * 60 * 60

# TTL the executor busy lock is re-armed to when a run parks on an approval. A
# paused run's lock TTL started when the run BEGAN, not when it paused; if it
# lapses first, the next call_executor discards the pending interrupt and orphans the user's card.
HIL_PAUSED_LOCK_TTL_SECONDS = HIL_APPROVAL_TIMEOUT_SECONDS + EXECUTOR_BUSY_TTL

# A decided record with no resumed_at stamp older than this is a crashed
# resume dispatch; the sweep re-dispatches it from the record's resume_item.
HIL_DECIDED_UNRESUMED_GRACE_SECONDS = 120

# The key LangGraph puts a paused run's Interrupt objects under in an "updates"
# stream event. Mirrored here because langgraph.constants.INTERRUPT went private
# in v1 (deprecated, slated for removal in v2).
LANGGRAPH_INTERRUPT_KEY = "__interrupt__"

# configurable flag set only on a resume re-dispatch. The handoff tool probes
# the subagent thread's checkpoint for a parked interrupt ONLY when this is
# set, so fresh runs (the ~100% case) skip that per-handoff Postgres read.
HIL_RESUME_CONFIG_KEY: Final = "hil_resume_replay"

# Keyed by stream_id (unique per turn), so this only suppresses re-asks within
# the same turn — a genuinely new request in a later turn still prompts.
HIL_DECLINE_MEMORY_TTL_SECONDS = 1800

# Background subagent results live in Redis, keyed by conversation (never
# stream_id — it changes on resume): they must survive the executor's approval
# pause, which the in-process session does not.
HIL_BG_RESULTS_KEY_PREFIX = "hil:bg_results:"
HIL_BG_RESULTS_TTL_SECONDS = 7200

# Interrupt payload type for the wait_for_subagents join pause. Carries the whole
# batch of parked-subagent approvals, unlike the gate's single "hil_approval".
HIL_BATCH_INTERRUPT_TYPE = "hil_approval_batch"

# Debounce: at most one executor resume dispatch per conversation at a time —
# two LangGraph runs on one thread would corrupt its checkpoint. TTL is crash
# insurance only; the dispatched run deletes the flag when it finalizes.
HIL_RESUME_ACTIVE_KEY_PREFIX = "hil:resume_active:"
HIL_RESUME_ACTIVE_TTL_SECONDS = 1800

# Orchestration/plumbing tools that must never be gated (they don't touch the
# outside world themselves; their inner tool calls are gated in the child graph).
# These are the only names hardcoded here — everything else is registry-driven.
HIL_EXEMPT_TOOLS: frozenset[str] = frozenset(
    {
        "retrieve_tools",
        "call_executor",
        "cancel_executor",
        "handoff",
        "spawn_subagent",
        WAIT_FOR_SUBAGENTS_NAME,
        FINISH_TASK_NAME,
        "plan_tasks",
        "update_tasks",
        "add_memory",
        "search_memory",
    }
)

# Exempt tools that can nonetheless PAUSE the run. A gated sibling of one of
# these must never auto-run: the pause re-runs the whole tool node, so
# anything already executed would run a second time (see policy.has_pausing_sibling).
HIL_PAUSING_TOOLS: frozenset[str] = frozenset(
    {"handoff", "spawn_subagent", WAIT_FOR_SUBAGENTS_NAME}
)

# tool_data entry name for the approval card (mirrored in @gaia/shared/chat).
APPROVAL_REQUEST_TOOL_NAME = "approval_request"
APPROVAL_TOOL_CATEGORY = "hil"

# Ack text streamed when a chat message resolves a pending approval instead of
# starting a new turn.
HIL_ACK_APPROVED = "Got it — going ahead."
HIL_ACK_DENIED = "Understood — I won't do that."
