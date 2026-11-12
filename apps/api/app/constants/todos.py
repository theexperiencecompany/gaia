"""
Todo Constants.

Constants for todo service operations.
"""

from datetime import timedelta
from enum import StrEnum
import re
from typing import Final

from app.constants.chat import MAX_MESSAGE_LENGTH

ONBOARDING_TODO_LIMIT = 3

# Label marking a todo seeded during onboarding — used to fetch and to purge them.
ONBOARDING_LABEL: Final[str] = "onboarding"

# Label that marks a todo as "tracked" — GAIA's institutional-memory layer.
# Kept here (not in tracked_todo_service) so the VFS sync glue can import it
# without creating a circular dependency.
GAIA_TRACKED_LABEL: Final[str] = "gaia-tracked"

# How many characters an unknown todo id may differ from a real one and still be
# offered as the one meant: a model copying sibling ObjectIds swaps one or two.
MAX_MISCOPIED_ID_CHARS: Final[int] = 4

# Label added by the worker when a tracked todo exhausts its retry budget — the
# execution path skips todos carrying it until the user manually resets.
FAILED_LABEL: Final[str] = "failed"

# Label added by the maintenance sweep to an overdue todo with no scheduled
# follow-up, so the UI can surface it for attention.
NEEDS_FOLLOW_UP_LABEL: Final[str] = "needs-follow-up"

# Labels meaning "this todo is waiting on something outside GAIA". The sweep
# reads them to judge whether an overdue todo is genuinely stuck, and
# trigger-subscription paths set/clear them, so they live here, not a consumer.
WAITING_FOR_REPLY_LABEL: Final[str] = "waiting-for-reply"
# A thread todo's other state: the user owes the reply. Not blocking, the next move is theirs.
NEEDS_REPLY_LABEL: Final[str] = "needs-reply"
# A thread todo the user must act on outside the thread (pay, secure, renew); nobody awaits a reply.
ACTION_NEEDED_LABEL: Final[str] = "action-needed"
WAITING_FOR_APPROVAL_LABEL: Final[str] = "waiting-for-approval"
BLOCKING_LABEL: Final[str] = "blocked"

BLOCKING_LABELS: Final[frozenset[str]] = frozenset(
    {WAITING_FOR_REPLY_LABEL, WAITING_FOR_APPROVAL_LABEL, BLOCKING_LABEL}
)


class WaitingOn(StrEnum):
    """What an open, non-recurring tracked todo is waiting for until its next check."""

    TIME = "time"
    EVENT = "event"
    USER = "user"
    SUB_TODOS = "sub_todos"
    UNPLANNED = "unplanned"


class NoReplyPlan(StrEnum):
    """What a todo waiting on the user does when its question expires unanswered."""

    ASK_AGAIN = "ask_again"
    PROCEED = "proceed"
    HOLD = "hold"


# A next check given as a duration from now ("30m", "4h", "3d", "1w").
NEXT_CHECK_DURATION: Final[re.Pattern[str]] = re.compile(r"(\d+)\s*([mhdw])")
NEXT_CHECK_DURATION_UNITS: Final[dict[str, timedelta]] = {
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
}


class WakeReason(StrEnum):
    """Why a scheduled run of a non-recurring tracked todo woke, read off its open state."""

    SCHEDULED_CHECK = "scheduled_check"
    BACKUP_CHECK = "backup_check"
    SUB_TODO_CHECK = "sub_todo_check"
    PLAN_IT = "plan_it"
    REASK_DUE = "reask_due"
    DEFAULT_DUE = "default_due"
    HOLD_CHECK = "hold_check"
    HOLD_LAST_CHECK = "hold_last_check"
    QUESTION_EXPIRED = "question_expired"


# How far out a next check may be set, so a todo can't be silenced with a far date.
# A todo may live for months; it looks again at least this often.
MAX_NEXT_CHECK_AHEAD: Final[timedelta] = timedelta(days=14)
MAX_QUESTION_EXPIRY: Final[timedelta] = timedelta(days=7)
# Once a question is on hold (nothing can move without the answer), checks slow down.
MAX_HOLD_CHECK_AHEAD: Final[timedelta] = timedelta(days=31)
# One re-ask per todo, ever; three hold checks with no answer and the todo closes.
MAX_REASKS: Final[int] = 1
MAX_HOLD_CHECKS: Final[int] = 3
# When a run ends with no next step even after being sent back, code sets one this far out.
OPEN_STATE_REPAIR_CHECK: Final[timedelta] = timedelta(days=1)
# How soon a parent waiting on its sub-todos runs after one of them completes.
SUB_TODO_PARENT_WAKE_DELAY: Final[timedelta] = timedelta(seconds=30)

# How much of activity.md (from the end) a scheduled run sees in its prompt:
# enough for the recent trail, bounded so a long-lived recurring todo does not
# grow the prompt without limit. Older entries stay readable via the file.
ACTIVITY_PROMPT_TAIL_CHARS: Final[int] = 4_000

# How much of canvas.md a prompt carries, head and tail kept, middle trimmed. An
# uncapped canvas pushed a tracked todo's run past MAX_MESSAGE_LENGTH and failed
# it on every retry; two fifths of that cap leaves room for the rest of the prompt.
CANVAS_PROMPT_MAX_CHARS: Final[int] = MAX_MESSAGE_LENGTH * 2 // 5
# Most of a triggered run's event data inlined in its prompt; the run can fetch the source.
TRIGGER_EVENTS_PROMPT_MAX_CHARS: Final[int] = MAX_MESSAGE_LENGTH // 5

# Tracked-todo recurrence shortcuts. Intervals step from now (drift is fine);
# anchored steps keep the first fire's wall-clock time.
TODO_INTERVAL_RECURRENCES: Final[dict[str, timedelta]] = {
    "every_4h": timedelta(hours=4),
    "every_1h": timedelta(hours=1),
}
TODO_ANCHORED_RECURRENCES: Final[dict[str, timedelta]] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}
TODO_RECURRENCE_SHORTCUTS: Final[frozenset[str]] = frozenset(
    TODO_INTERVAL_RECURRENCES.keys() | TODO_ANCHORED_RECURRENCES.keys()
)

# The ARQ task that runs a tracked todo; also the prefix of its per-occurrence job id.
EXECUTE_TRACKED_TODO_TASK: Final[str] = "execute_tracked_todo"

# How far past its stored scheduled_at an unstamped fire (queued before jobs
# carried their occurrence) may land and still run; outside it, it is dropped.
TODO_SCHEDULE_FIRE_GRACE: Final[timedelta] = timedelta(minutes=2)
# How long a one-time run that came due on a paused account waits before it checks again.
PAUSED_RUN_RECHECK: Final[timedelta] = timedelta(days=1)
# How long a todo paused for its subscription keeps the trigger events that reached it.
PAUSED_TRIGGER_HOLD_TTL: Final[timedelta] = timedelta(days=30)

# How much of a run's final report is kept in its activity.md entry.
RUN_SUMMARY_ACTIVITY_CHARS: Final[int] = 200

# The durable job that finishes a run's delivery when the todo store failed it
# in-process; keyed by the run and its undone step, so each has one job at a time.
TODO_RUN_FINISH_TASK: Final[str] = "finish_tracked_todo_run"
TODO_RUN_FINISH_JOB_PREFIX: Final[str] = "todo-run-finish:"
# 1+2+4+8+16 minutes across six tries: a Mongo outage that long is an incident.
TODO_RUN_FINISH_RETRY_DELAY: Final[timedelta] = timedelta(minutes=1)
TODO_RUN_FINISH_MAX_TRIES: Final[int] = 6


class TodoRunFinishFailure(StrEnum):
    """What of a finished run's delivery was still undone when its durable job gave up."""

    NOT_DELIVERED = "todo_run_result_not_delivered"
    NOT_RECORDED = "todo_run_result_not_recorded"


class TodoRunDeliveryOutcome(StrEnum):
    """What happened to a tracked todo run's result, for activity.md and analytics."""

    DELIVERED = "delivered"
    UNDELIVERED = "undelivered"
    SILENCED = "silenced"
    NOTHING_TO_REPORT = "nothing_to_report"
    NOTIFY_OFF = "notify_off"
    NARRATION_FAILED = "narration_failed"
    INVALID_DIRECTIVE = "invalid_directive"


class TodoWakeKind(StrEnum):
    """What woke a tracked todo's run: its schedule, a watched event, or an approval it waited on."""

    SCHEDULE = "schedule"
    TRIGGER = "trigger"
    APPROVAL = "approval"


class TodoActivityEvent(StrEnum):
    """A lifecycle event code records in a tracked todo's activity.md, as "[event] detail"."""

    CREATED = "created"
    SCHEDULED = "scheduled"
    SCHEDULE_CLEARED = "schedule_cleared"
    RECURRENCE_CHANGED = "recurrence_changed"
    DELIVERY_CHANGED = "delivery_changed"
    EXPIRY_CHANGED = "expiry_changed"
    DUE_DATE_CHANGED = "due_date_changed"
    WATCH_ADDED = "watch_added"
    WATCH_REMOVED = "watch_removed"
    WATCH_PAUSED = "watch_paused"
    WATCH_RESUMED = "watch_resumed"
    TRIGGER_FIRED = "trigger_fired"
    TRIGGER_ACTION_FAILED = "trigger_action_failed"
    SUB_TODO_COMPLETED = "sub_todo_completed"
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    RUN_FAILED = "run_failed"
    RUN_SKIPPED = "run_skipped"
    RUN_CANCELLED = "run_cancelled"
    RETRY_SCHEDULED = "retry_scheduled"
    MARKED_FAILED = "marked_failed"
    OCCURRENCE_GIVEN_UP = "occurrence_given_up"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    MAINTENANCE = "maintenance"
    WAITING_CHANGED = "waiting_changed"
    OPEN_STATE_REPAIRED = "open_state_repaired"
    SANDBOX_EVENT = "sandbox_event"
    COMPLETED = "completed"
    REOPENED = "reopened"


# The activity detail of a reopen made from the todos page, as completion's is "Completed via UI".
REOPENED_IN_THE_APP_DETAIL: Final[str] = "via UI"

# What a reopen starts again from zero, as on a new todo: retries, re-asks and holds.
REOPEN_RESET_COUNTERS: Final[tuple[str, ...]] = ("gaia_retry_count", "reasks_used", "hold_checks")

# What a create sets on a todo it reopens even when left out, as a new todo starts without them.
REOPEN_CLEARED_SCHEDULE_FIELDS: Final[tuple[str, ...]] = (
    "scheduled_at",
    "recurrence",
    "due_date",
    "expires_at",
    "waiting_on",
    "question",
    "if_no_reply",
    "default_action",
)


# The sections every canvas.md carries exactly once, in this order. Activity
# (dated "### YYYY-MM-DD" entries, any run log) belongs in activity.md, never here.
CANVAS_STANDING_RULES_SECTION: Final[str] = "Standing rules"
CANVAS_KEY_DETAILS_SECTION: Final[str] = "Key Details"
# What makes the todo done, and where the proof will show up: what every run checks against.
CANVAS_DONE_WHEN_SECTION: Final[str] = "Done when"
CANVAS_EVIDENCE_SECTION: Final[str] = "Evidence"
CANVAS_CURRENT_STATE_SECTION: Final[str] = "Current State"
CANVAS_LEARNINGS_SECTION: Final[str] = "Learnings"
CANVAS_SECTIONS: Final[tuple[str, ...]] = (
    CANVAS_STANDING_RULES_SECTION,
    CANVAS_DONE_WHEN_SECTION,
    CANVAS_EVIDENCE_SECTION,
    CANVAS_KEY_DETAILS_SECTION,
    CANVAS_CURRENT_STATE_SECTION,
    "Context",
    CANVAS_LEARNINGS_SECTION,
)
# The Inbox desk's canvas section from before observations.md; its run moves it there.
CANVAS_OBSERVATIONS_SECTION: Final[str] = "Observations"

# Most a Standing rules section may hold. Every prompt carries it whole, never
# trimmed, so a canvas write that grows it past this is refused instead.
STANDING_RULES_MAX_CHARS: Final[int] = 2_000

# observations.md: one block per pattern, its evidence kept across runs.
OBSERVATIONS_SENDERS_SECTION: Final[str] = "Senders"
OBSERVATIONS_RECURRING_SECTION: Final[str] = "Recurring"
OBSERVATIONS_PEOPLE_SECTION: Final[str] = "People"
OBSERVATION_CONCLUSION: Final[str] = "conclusion"
OBSERVATION_CONFIDENCE: Final[str] = "confidence"
OBSERVATION_FIRST_SEEN: Final[str] = "first seen"
OBSERVATION_LAST_SEEN: Final[str] = "last seen"
OBSERVATION_DAILY_COUNTS: Final[str] = "daily counts"
OBSERVATION_EARLIER: Final[str] = "earlier"
# When the desk last suggested a Gmail change from this pattern; it never suggests it twice.
OBSERVATION_SUGGESTED: Final[str] = "suggested"
# Days of per-day counts an entry keeps; older days fold into its "earlier" average.
OBSERVATION_DAILY_COUNT_DAYS: Final[int] = 14
# Messages from one sender in a run before it gets an entry: a one-off is not a pattern.
OBSERVATION_MIN_MESSAGES: Final[int] = 3
# Most observations.md may hold; a write past it is refused.
OBSERVATIONS_MAX_CHARS: Final[int] = 12_000
# Most of observations.md a run prompt carries; past it, the conclusions alone.
OBSERVATIONS_PROMPT_MAX_CHARS: Final[int] = 6_000
# Most of a todo's Key Details its delivery decision reads.
DELIVERY_KEY_DETAILS_MAX_CHARS: Final[int] = 1500
# Earlier runs' delivery outcomes shown to comms when it decides whether to message.
DELIVERY_RUN_HISTORY_LINES: Final[int] = 3

# How many referenced todos a run reads Learnings from.
REFERENCED_TODOS_PROMPT_LIMIT: Final[int] = 5

# Top-level tracked todos in every agent's ACTIVE TRACKED TODOS block; sub-todos fold into a count.
ACTIVE_TRACKED_SUMMARY_LIMIT: Final[int] = 15

# Open sub-todos a parent's run reads, and how much of each one's Current State.
SUB_TODOS_PROMPT_LIMIT: Final[int] = 50
SUB_TODO_STATE_EXCERPT_CHARS: Final[int] = 300

# How much of an existing todo's Current State a refused duplicate create shows.
EXISTING_TODO_STATE_EXCERPT_CHARS: Final[int] = 400

# Most todos list_tracked_todos returns, filtered or not; the freshest win.
LIST_TRACKED_TODOS_LIMIT: Final[int] = 50

# The one tracked todo per user that triages mail, owns its threads, briefs each morning and alerts on new mail.
# Where a ping meets follow-through: one rule, read by comms, the executor and the manual.
PING_WITH_FOLLOW_THROUGH_RULE: Final[str] = (
    "A ping that GAIA must also see through is ONE tracked todo whose first run gives the "
    "ping: never a reminder beside it, and never the reminder alone."
)
INBOX_DESK_TITLE: Final[str] = "Inbox desk"
INBOX_DESK_RECURRENCE: Final[str] = "0 8 * * *"
PROVISION_INBOX_DESK_TASK: Final[str] = "provision_inbox_desk"
# Automated senders the desk's fetch leaves out: GitHub and other
# notifications land in Primary, and this cut a live 24h window from 224 messages to 10 people.
INBOX_DESK_AUTOMATED_SENDERS: Final[tuple[str, ...]] = (
    "noreply",
    "no-reply",
    "notifications",
    "notification",
    "mailer-daemon",
    "donotreply",
)
# Every inbox tab but Promotions and Social, minus automated senders: group-delivered
# work threads land in Forums, which a Primary-only fetch never read.
INBOX_DESK_MAIL_FILTER: Final[str] = "in:inbox -category:promotions -category:social " + " ".join(
    f"-from:{sender}" for sender in INBOX_DESK_AUTOMATED_SENDERS
)
# The desk's second fetch: mail the user may have to act on, which banks and billing send
# from the automated senders the Primary filter leaves out. Step 5 still classifies each one.
INBOX_DESK_ACTION_MAIL_TERMS: Final[tuple[str, ...]] = (
    "declined",
    "(insufficient funds)",
    "(payment failed)",
    "(payment unsuccessful)",
    "(security alert)",
    "(unusual activity)",
    "expiring",
    "expires",
    "suspended",
    "overdue",
    "(past due)",
    "(action required)",
)
# Routine sign-in notices and codes ask nothing of the user, so the action fetch leaves them out.
INBOX_DESK_ROUTINE_SIGN_IN_TERMS: Final[tuple[str, ...]] = (
    "(new sign-in)",
    "(new login)",
    "(new device)",
    "(verification code)",
    "(security code)",
    "(login code)",
    "(sign-in code)",
)
# A security problem is fetched whatever else its subject says, sign-in words included.
INBOX_DESK_SECURITY_PROBLEM_TERMS: Final[tuple[str, ...]] = (
    "blocked",
    "locked",
    "suspicious",
    "unrecognised",
    "unrecognized",
    "compromised",
    "(password changed)",
    "(password was changed)",
    "(recovery changed)",
    "(recovery email)",
    "(recovery phone)",
    "(two-factor enabled)",
    "(two-factor removed)",
    "(2-step verification)",
    "(security settings)",
    "(password updated)",
    "(turned off)",
    "disabled",
)
# Gmail's (a b) is every word, so no quote reaches the prompt's quoted query, and no brace
# reaches the run prompt's str.format.
INBOX_DESK_ACTION_MAIL_FILTER: Final[str] = (
    "in:inbox ((("
    + " OR ".join(f"subject:{term}" for term in INBOX_DESK_ACTION_MAIL_TERMS)
    + ") "
    + " ".join(f"-subject:{term}" for term in INBOX_DESK_ROUTINE_SIGN_IN_TERMS)
    + ") OR ("
    + " OR ".join(f"subject:{term}" for term in INBOX_DESK_SECURITY_PROBLEM_TERMS)
    + "))"
)
# The desk's briefing is read in seconds: words per item, per summary under an item,
# and lines per capped section.
INBOX_DESK_BRIEFING_ITEM_MAX_WORDS: Final[int] = 12
INBOX_DESK_SUMMARY_MAX_WORDS: Final[int] = 25
INBOX_DESK_NEEDS_YOU_MAX_ITEMS: Final[int] = 5
INBOX_DESK_FYI_MAX_LINES: Final[int] = 5
# Days a high-confidence pattern must hold before the desk suggests a Gmail change from it.
INBOX_DESK_SUGGEST_AFTER_DAYS: Final[int] = 3
# Heads the desk's Current State line naming each question it already asked once.
INBOX_DESK_ASKED_ONCE: Final[str] = "Asked once"


class InboxDeskAsk(StrEnum):
    """What the desk does only once the user says yes, each asked at most once ever."""

    SUMMARIES = "summaries"
    TODOS = "todos"


# First retry delay of a failed provisioning; each further try doubles it.
INBOX_DESK_PROVISION_RETRY_DELAY: Final[timedelta] = timedelta(minutes=2)

# How many times a failed tracked-todo run is retried, and how long each retry waits.
MAX_RETRY_ATTEMPTS: Final[int] = 3
RETRY_BACKOFF: Final[list[timedelta]] = [timedelta(hours=1), timedelta(hours=4)]
# How long one run of a todo may hold its execution lock.
LOCK_TTL_SECONDS: Final[int] = 1800
# Held by whichever run of a todo is going: a scheduled or triggered run, or an approval resume.
RUN_LOCK_KEY: Final[str] = "gaia_todo_exec:{todo_id}"

# An approval resume that lands mid-execution waits for the lock instead of vanishing.
# Bounded, because a todo stuck under the 30-minute lock TTL must eventually give
# up loudly rather than re-enqueue itself forever.
LOCK_DEFER_BACKOFF: Final[list[timedelta]] = [
    timedelta(minutes=1),
    timedelta(minutes=3),
    timedelta(minutes=10),
]
# The daily cost-budget feature a triggered todo run charges against.
TRIGGER_TODO_FEATURE_KEY: Final[str] = "trigger_todo_executions"
