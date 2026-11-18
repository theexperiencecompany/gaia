"""The one way to change a user's quiet hours: store them, then move the briefs and the Inbox desk out of them."""

from app.db.repositories.users import user_repository
from app.models.quiet_hours_models import QuietHours
from app.services.analytics_service import capture
from app.services.briefing.run_times import inbox_desk_recurrence
from app.services.briefing.schedule import resync_briefing_schedules
from app.services.todos.inbox_desk import follow_the_brief
from app.services.user_service import require_user, user_not_found
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsQuietHoursUpdated


async def set_quiet_hours(user_id: str, hours: QuietHours) -> QuietHours:
    """Store the user's quiet hours, move the briefs and the desk out of them, and report it.

    Raises user_not_found's 404 for an unknown user.
    """
    before = await require_user(user_id)
    user = await user_repository.set_quiet_hours(user_id, hours)
    if user is None:
        raise user_not_found(user_id)
    await resync_briefing_schedules(user)
    await follow_the_brief(user_id, inbox_desk_recurrence(before), inbox_desk_recurrence(user))
    capture(
        UserId(user_id),
        SettingsQuietHoursUpdated(
            enabled=hours.enabled, start_hour=hours.start_hour, end_hour=hours.end_hour
        ),
    )
    return hours
