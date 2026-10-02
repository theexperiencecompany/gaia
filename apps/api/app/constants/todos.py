"""
Todo Constants.

Constants for todo service operations.
"""

from datetime import timedelta
from enum import StrEnum
from typing import Final

from app.constants.chat import MAX_MESSAGE_LENGTH

ONBOARDING_TODO_LIMIT = 3

# Label marking a todo seeded during onboarding — used to fetch and to purge them.
ONBOARDING_LABEL: Final[str] = "onboarding"

# Label that marks a todo as "tracked" — GAIA's institutional-memory layer.
# Kept here (not in tracked_todo_service) so the VFS sync glue can import it
# without creating a circular dependency.
GAIA_TRACKED_LABEL: Final[str] = "gaia-tracked"

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
WAITING_FOR_APPROVAL_LABEL: Final[str] = "waiting-for-approval"
BLOCKING_LABEL: Final[str] = "blocked"

BLOCKING_LABELS: Final[frozenset[str]] = frozenset(
    {WAITING_FOR_REPLY_LABEL, WAITING_FOR_APPROVAL_LABEL, BLOCKING_LABEL}
)

# How much of activity.md (from the end) a scheduled run sees in its prompt:
# enough for the recent trail, bounded so a long-lived recurring todo does not
# grow the prompt without limit. Older entries stay readable via the file.
ACTIVITY_PROMPT_TAIL_CHARS: Final[int] = 4_000

# How much of canvas.md a prompt carries, head and tail kept, middle trimmed. An
# uncapped canvas pushed a tracked todo's run past MAX_MESSAGE_LENGTH and failed
# it on every retry; two fifths of that cap leaves room for the rest of the prompt.
CANVAS_PROMPT_MAX_CHARS: Final[int] = MAX_MESSAGE_LENGTH * 2 // 5

# The ARQ task that runs a tracked todo; also the prefix of its per-occurrence job id.
EXECUTE_TRACKED_TODO_TASK: Final[str] = "execute_tracked_todo"

# How far past its stored scheduled_at an unstamped fire (queued before jobs
# carried their occurrence) may land and still run; outside it, it is dropped.
TODO_SCHEDULE_FIRE_GRACE: Final[timedelta] = timedelta(minutes=2)

# How much of a run's final report is kept in its activity.md entry.
RUN_SUMMARY_ACTIVITY_CHARS: Final[int] = 200


class TodoRunDeliveryOutcome(StrEnum):
    """What happened to a tracked todo run's result, for activity.md and analytics."""

    DELIVERED = "delivered"
    UNDELIVERED = "undelivered"
    SILENCED = "silenced"
    NOTIFY_OFF = "notify_off"
    NARRATION_FAILED = "narration_failed"
    INVALID_DIRECTIVE = "invalid_directive"


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
    RETRY_SCHEDULED = "retry_scheduled"
    MARKED_FAILED = "marked_failed"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    MAINTENANCE = "maintenance"
    COMPLETED = "completed"


# The sections every canvas.md carries exactly once, in this order. Activity
# (dated "### YYYY-MM-DD" entries, any run log) belongs in activity.md, never here.
CANVAS_STANDING_RULES_SECTION: Final[str] = "Standing rules"
CANVAS_KEY_DETAILS_SECTION: Final[str] = "Key Details"
CANVAS_CURRENT_STATE_SECTION: Final[str] = "Current State"
CANVAS_LEARNINGS_SECTION: Final[str] = "Learnings"
CANVAS_SECTIONS: Final[tuple[str, ...]] = (
    CANVAS_STANDING_RULES_SECTION,
    CANVAS_KEY_DETAILS_SECTION,
    CANVAS_CURRENT_STATE_SECTION,
    "Context",
    CANVAS_LEARNINGS_SECTION,
)

# Most a Standing rules section may hold. Every prompt carries it whole, never
# trimmed, so a canvas write that grows it past this is refused instead.
STANDING_RULES_MAX_CHARS: Final[int] = 2_000
# Most of a todo's Key Details its delivery decision reads.
DELIVERY_KEY_DETAILS_MAX_CHARS: Final[int] = 1500

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
