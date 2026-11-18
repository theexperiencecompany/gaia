"""Spread brief runs across the minutes after their hour, so one hour's briefs never fire at once.

Every daily brief and weekly digest used to fire at minute 0 of its hour, so all users with
one local hour hit the shared worker queue in the same second. Each user gets a stable minute
(a hash of their id), so their brief always lands at the same time and the fleet's are spread.
"""

import hashlib

from app.constants.brief_slots import BRIEF_SLOT_SPREAD_MINUTES


def slot_minute(user_id: str) -> int:
    """Return the user's stable minute past the hour, in [0, BRIEF_SLOT_SPREAD_MINUTES)."""
    digest = hashlib.sha256(user_id.encode()).digest()
    return int.from_bytes(digest[:4], "big") % BRIEF_SLOT_SPREAD_MINUTES
