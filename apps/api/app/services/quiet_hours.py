"""A user's quiet hours as delivery reads them: theirs or the default, when they end, and URGENT.

Changing them is user_quiet_hours', which moves the briefs that read these.
"""

from datetime import datetime

from app.constants.notifications import ProactiveMessageClass
from app.db.repositories.users import user_repository
from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS, QuietHours
from app.services import user_service


async def get_quiet_hours(user_id: str) -> QuietHours:
    """Return the user's quiet hours: their own, or 22:00 to 08:00 when they never set any."""
    user = await user_repository.get(user_id)
    return user.effective_quiet_hours if user else DEFAULT_QUIET_HOURS


async def quiet_hours_end(user_id: str) -> datetime | None:
    """Return when the user's quiet hours end when their own clock is inside them now, else None."""
    local_now = datetime.now((await user_service.get_profile_timezone(user_id)).tzinfo)
    hours = await get_quiet_hours(user_id)
    return hours.end_after(local_now) if hours.contains(local_now) else None


def message_class(broke_through: bool) -> ProactiveMessageClass:
    """URGENT for a message the trigger gate let through quiet hours, else ROUTINE."""
    return ProactiveMessageClass.URGENT if broke_through else ProactiveMessageClass.ROUTINE
