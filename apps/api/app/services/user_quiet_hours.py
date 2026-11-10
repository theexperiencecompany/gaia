"""The one way to change a user's quiet hours: store them, then move the daily brief out of them."""

from fastapi import HTTPException

from app.db.repositories.users import user_repository
from app.models.quiet_hours_models import QuietHours
from app.services.analytics_service import capture
from app.services.briefing.schedule import resync_briefing_schedules
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsQuietHoursUpdated


async def set_quiet_hours(user_id: str, hours: QuietHours) -> QuietHours:
    """Store the user's quiet hours, move the daily brief out of them, and report the change.

    404 when there is no such user.
    """
    user = await user_repository.set_quiet_hours(user_id, hours)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    await resync_briefing_schedules(user)
    capture(
        UserId(user_id),
        SettingsQuietHoursUpdated(
            enabled=hours.enabled, start_hour=hours.start_hour, end_hour=hours.end_hour
        ),
    )
    return hours
