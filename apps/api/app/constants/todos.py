"""
Todo Constants.

Constants for todo service operations.
"""

from datetime import timedelta
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

# Terminal-contract marker: finish_todo_run writes "gaia_todo_terminal:{todo_id}"
# (value = outcome); the worker deletes it before a run and requires it after,
# treating a missing marker as a failed run (existing retry ladder).
TERMINAL_MARKER_PREFIX: Final[str] = "gaia_todo_terminal:"
TERMINAL_MARKER_TTL_SECONDS = 6 * 3600

# ask_user guardrails: one outstanding question per todo is enforced by the
# model; this caps how many questions GAIA may ask a user per UTC day.
ASK_USER_DAILY_LIMIT = 5
PENDING_QUESTION_TTL = timedelta(hours=24)


def terminal_marker_key(todo_id: str) -> str:
    """Redis key holding the outcome of a tracked-todo run's terminal tool call."""
    return f"{TERMINAL_MARKER_PREFIX}{todo_id}"
