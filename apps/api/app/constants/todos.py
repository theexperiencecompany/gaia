"""
Todo Constants.

Constants for todo service operations.
"""

from typing import Final

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

# Labels that mean "this todo is waiting on something outside GAIA". The
# maintenance sweep reads them to decide whether an overdue todo is genuinely
# stuck, and the trigger-subscription paths set and clear them — so they live
# here rather than inside either consumer.
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
