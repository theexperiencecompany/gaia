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

# How far past its stored scheduled_at a scheduled fire may land and still run.
# ARQ fires a deferred job at its defer time; a fire outside this window is a
# job left behind by a reschedule (ARQ cannot cancel it) and is dropped.
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
