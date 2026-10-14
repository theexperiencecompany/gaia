"""The one way to change a user's timezone: store it, then move what runs on their clock."""

from app.db.repositories.users import user_repository
from app.models.user_models import UserDocument, UserUpdate
from app.services.briefing.schedule import resync_briefing_schedules


async def set_user_timezone(user_id: str, timezone: str) -> UserDocument | None:
    """Store the user's timezone and move their briefing schedules onto it.

    Returns the updated user, or None when no such user exists.
    """
    user = await user_repository.update(user_id, UserUpdate(timezone=timezone))
    if user is not None:
        await resync_briefing_schedules(user)
    return user
