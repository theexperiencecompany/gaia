"""How brief runs are spread across their hour (app/workers/brief_slots.py)."""

from typing import Final

#: Minutes past the hour a user's brief may land on; each user keeps one of them for good.
BRIEF_SLOT_SPREAD_MINUTES: Final[int] = 30
