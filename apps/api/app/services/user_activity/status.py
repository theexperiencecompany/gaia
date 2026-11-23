"""Read one user's activity status from Mongo."""

from datetime import UTC, datetime

from app.constants.user_activity import ActivityStatus
from app.db.repositories.users import user_repository


async def activity_status_of(user_id: str) -> ActivityStatus:
    """Return user_id's activity status now; raise LookupError for an id that is no user."""
    dates = await user_repository.get_activity_dates(user_id)
    if dates is None:
        raise LookupError(f"no user {user_id}")
    return dates.status(datetime.now(UTC))
