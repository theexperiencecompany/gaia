"""When a user was last seen, and the activity status that follows from it."""

from datetime import datetime

from pydantic import BaseModel

from app.constants.user_activity import DORMANT_AFTER, IDLE_AFTER, ActivityStatus
from app.utils.timezone import as_utc


def status_window(status: ActivityStatus, now: datetime) -> tuple[datetime | None, datetime | None]:
    """Return the (after, until] range of last-seen instants that puts a user in status."""
    match status:
        case ActivityStatus.ACTIVE:
            return now - IDLE_AFTER, None
        case ActivityStatus.IDLE:
            return now - DORMANT_AFTER, now - IDLE_AFTER
        case ActivityStatus.DORMANT:
            return None, now - DORMANT_AFTER


class UserActivityDates(BaseModel):
    """The two user fields activity is judged from.

    A user never seen active is judged from signup, so a new account starts
    active and one that never came back goes idle, then dormant, on one clock.
    """

    last_active_at: datetime | None = None
    created_at: datetime | None = None

    def status(self, now: datetime) -> ActivityStatus:
        """Return the activity status at now; a user with neither date reads as dormant."""
        last_seen = as_utc(self.last_active_at or self.created_at)
        if last_seen is None or last_seen <= now - DORMANT_AFTER:
            return ActivityStatus.DORMANT
        if last_seen <= now - IDLE_AFTER:
            return ActivityStatus.IDLE
        return ActivityStatus.ACTIVE
