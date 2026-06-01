"""
Todo Constants.

Constants for todo service operations.
"""

from typing import Final

ONBOARDING_TODO_LIMIT = 3

# Label that marks a todo as "tracked" — GAIA's institutional-memory layer.
# Kept here (not in tracked_todo_service) so the VFS sync glue can import it
# without creating a circular dependency.
GAIA_TRACKED_LABEL: Final[str] = "gaia-tracked"
