"""HIL (human-in-the-loop) approval constants: policy, timings, limits, frame names.

Every tunable number the HIL services use lives here. The LLM-facing *text* lives in
app/services/hil/prompts.py; the destructive classification lives on each tool in
the tool registry (app/agents/tools/core/registry.py), the single source of truth
for every tool in the app.
"""

from datetime import timedelta
from enum import StrEnum
from typing import Final, Literal

from app.constants.cache import EXECUTOR_BUSY_TTL
from app.constants.comms import ANSWERED_TOOL_NAME, REACT_TOOL_NAME, STAY_SILENT_TOOL_NAME
from app.constants.execute import ACTIVATE_INTEGRATION_TOOL_NAME
from app.constants.general import FINISH_TASK_NAME
from shared.py.approvals import ApprovalOutcome, DecidedOutcome

# What a user decides on a pending approval, and the outcome each decision ends it with.
ApprovalDecision = Literal["approve", "deny"]
DECISION_OUTCOME: Final[dict[ApprovalDecision, DecidedOutcome]] = {
    "approve": ApprovalOutcome.APPROVED,
    "deny": ApprovalOutcome.DENIED,
}

# The default mode is ``HIL_DEFAULT_MODE`` in app/models/hil_models.py (a
# HILPreferences field default, so it lives with the model).

HIL_JUDGE_MAX_TURN_CHARS = 800

# The pending call's arguments, and the run's earlier tool calls (provenance for
# args the agent derived, not the user). Prior outputs ride too, clipped small:
# an id minted by an earlier call is only traceable through that output.
HIL_JUDGE_MAX_ARGS_CHARS = 1500
HIL_JUDGE_MAX_PRIOR_CALLS = 8
HIL_JUDGE_MAX_PRIOR_OUTPUT_CHARS = 300

# The run's recent assistant messages: provenance for JEV, never authorization (the
# assistant's words say what it told the user). Bounded — prompts are not free.
HIL_JUDGE_MAX_ASSISTANT_TURNS = 3
HIL_JUDGE_MAX_ASSISTANT_CHARS = 500

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

# JEV choice judge (auto mode v2): model, timeout, decision lines. Lines come
# from the offline sweep (scripts/evals/sweep_hil_judge.py) — the 0.50 plateau
# scored 49/50 with zero dangerous accepts. Retune via the eval, never by hand.
HIL_JEV_MODEL_NAME = "typesafe/jev-1.13"
HIL_JEV_TIMEOUT_SECONDS = 15
#: The name auto mode's one Decisions question goes by, in the request and its answer.
JEV_DECISION_QUESTION_KEY = "decision"


class JevFailure(StrEnum):
    """Why a JEV call gave no usable answer; the values are metric labels an alert rule reads."""

    ERROR = "jev_error"
    TIMEOUT = "jev_timeout"
    # A body that is not JSON, fails validation, or names an answer the caller never offered.
    MALFORMED = "jev_malformed"
    # No OpenRouter key (self-host); not an outage, so callers leave it out of their error logs.
    UNCONFIGURED = "jev_unconfigured"


HIL_JEV_ACCEPT_LINE = 0.50

# The note on a card auto mode raised instead of running the call. The judge's own
# reason names tool slugs and scores, so it stays model-facing; the user reads this.
AUTO_ASK_NOTE = "GAIA isn't sure you asked for this, so it's checking with you first."


class JevChoice(StrEnum):
    """The choice labels the JEV questions offer (prompts.py criteria) and answers carry."""

    AUTHORIZED = "authorized"
    FORBIDDEN = "forbidden"
    UNCLEAR = "unclear"


# JEV reply classifier: an approve under the line leaves the action pending.
# hil-reply sweep (3 runs, v2): 0.65 scored 77/77, 77/77, 79/79, zero dangerous;
# injected approves peaked just under 0.60, true ones bottomed at 0.68.
HIL_JEV_REPLY_APPROVE_LINE = 0.65
# Deny/unrelated under this floor leave the action pending too. Sweep (3 runs): 78/79
# each; the miss is a 0.25-0.38 true deny, but a v1 wrong deny sat at 0.40.
HIL_JEV_REPLY_DECIDE_FLOOR = 0.50

# Decisions question name per pending action: "action_1", "action_2", ...
HIL_JEV_REPLY_QUESTION_PREFIX = "action_"

# The bot approval prompt's own answer words (approval-prompt.ts): a reply that is
# one of them, optionally followed by item numbers, decides without the classifier.
HIL_PLAIN_REPLY_WORDS: Final[dict[str, ApprovalDecision]] = {
    **dict.fromkeys(("yes", "y", "yep", "yeah", "ok", "okay", "sure", "approve"), "approve"),
    **dict.fromkeys(("no", "n", "nope", "cancel", "deny"), "deny"),
}


class ReplyChoice(StrEnum):
    """What a chat reply means for one pending action: the JEV reply question's labels."""

    APPROVE = "approve"
    # Accepted with a change: it approves, and the change goes to the work with it.
    AMEND = "amend"
    DENY = "deny"
    LEAVE = "leave"
    UNRELATED = "unrelated"


# The classifier reading a chat reply to a pending approval gets richer context
# than the card summary: recent turns + the full (bounded) args. TOTAL budget
# is the real ceiling; the per-value clip only stops one pathological arg from eating it all.
HIL_CLASSIFIER_MAX_ARG_CHARS = 4000  # per-value clip — a full typical email/message body fits
HIL_CLASSIFIER_MAX_DETAIL_CHARS = 8000  # total budget for one action's rendered detail
HIL_CLASSIFIER_MAX_ARGS = 8  # include non-scalar args too, as compact JSON
HIL_CLASSIFIER_HISTORY_TURNS = 4  # recent {role, content} turns of context

# Marks a synthetic ToolMessage the gate produced (rather than a real tool result).
HIL_STATUS_KWARG = "hil_status"
HILToolMessageStatus = Literal["denied", "error", "pending"]

# How long an approval may sit unanswered before the sweep resolves it as a
# timeout. Set by how long a human plausibly takes to answer a push
# notification, NOT infrastructure — HIL gates irreversible, third-party-visible actions.
HIL_APPROVAL_TIMEOUT_SECONDS = 6 * 60 * 60

# How long a decision's hand-off to the waiting work may take before the sweeper
# treats it as failed and carries the logged decision out again.
DECISION_HANDOFF_LEASE = timedelta(minutes=2)

# How long unread executor inbox work lives: an approval ticket handed over waits
# as long as the user may take to answer, plus one busy run.
EXECUTOR_INBOX_TTL = HIL_APPROVAL_TIMEOUT_SECONDS + EXECUTOR_BUSY_TTL

# Background-dispatch claims (one per delegating tool call), keyed by conversation
# (never stream_id — it changes on resume): a node replay after the executor's
# approval pause must find the dispatch the first pass already made.
HIL_BG_RESULTS_KEY_PREFIX = "hil:bg_results:"
HIL_BG_RESULTS_TTL_SECONDS = 7200

# Orchestration/plumbing tools that must never be gated (they don't touch the
# outside world; their inner calls are gated in the child graph). Ticket ops
# (approve/revoke) are exempt too: the approval IS the gate, re-gating re-asks.
HIL_EXEMPT_TOOLS: frozenset[str] = frozenset(
    {
        "retrieve_tools",
        ACTIVATE_INTEGRATION_TOOL_NAME,
        "call_executor",
        "cancel_executor",
        "browser_step_done",
        "stop_browser_task",
        "tell_browser_task",
        "spawn_subagent",
        "approve",
        "revoke",
        FINISH_TASK_NAME,
        "plan_tasks",
        "update_tasks",
        "add_memory",
        "search_memory",
        REACT_TOOL_NAME,
        STAY_SILENT_TOOL_NAME,
        ANSWERED_TOOL_NAME,
    }
)

# tool_data entry name for the approval card (mirrored in @gaia/shared/chat).
APPROVAL_REQUEST_TOOL_NAME = "approval_request"
APPROVAL_TOOL_CATEGORY = "hil"

# Ack text streamed when a chat message resolves a pending approval instead of
# starting a new turn.
HIL_ACK_APPROVED = "Got it, going ahead."
HIL_ACK_DENIED = "Understood, I will not do that."
# The same acks when the reply decided exactly one action, named in plain words.
HIL_ACK_APPROVED_ONE = "Got it, I'll {action}."
HIL_ACK_DENIED_ONE = "Understood, I won't {action}."
