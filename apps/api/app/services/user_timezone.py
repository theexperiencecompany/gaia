"""The one way to change a user's timezone: store it, then move what runs on their clock."""

from app.db.repositories.users import user_repository
from app.models.user_models import UserDocument, UserUpdate
from app.services.briefing.schedule import resync_briefing_schedules
from app.services.user_service import user_not_found


async def set_user_timezone(user_id: str, timezone: str) -> UserDocument:
    """Store the user's timezone and move their briefing schedules onto it.

    Raises user_not_found's 404 for an unknown user.
    """
    user = await user_repository.update(user_id, UserUpdate(timezone=timezone))
    if user is None:
        raise user_not_found(user_id)
    await resync_briefing_schedules(user)
    return user
