"""Quiet hours: when a proactive chat message may reach the user.

The one policy for every message GAIA sends on its own initiative. The user's
window is whole local hours on their own clock and may span midnight (22 to 8
is 22:00 to 08:00); a message that falls inside it is held until the window's
end, never dropped. A reminder the user timed themselves is exempt: it arrives
when they asked. post_to_platform_chat is the only caller; nothing else in the
codebase decides about quiet hours.
"""

from datetime import UTC, datetime, timedelta

from app.constants.notifications import ProactiveMessageClass
from app.models.notification.notification_models import QuietHours
from app.utils.timezone import Timezone

#: Classes delivered even inside the user's quiet hours.
QUIET_HOURS_EXEMPT: frozenset[ProactiveMessageClass] = frozenset({ProactiveMessageClass.USER_TIMED})

_HOURS_PER_DAY = 24


def quiet_window_end(
    window: QuietHours, timezone_name: str | None, now: datetime
) -> datetime | None:
    """Return the UTC instant window ends when now is inside it on the user's clock, else None.

    The end is a wall-clock hour in the user's zone (UTC when unset), so a DST
    change inside the window moves the instant, not the hour the user chose. An
    end hour that a spring-forward skips resolves to the first instant after the gap.
    """
    local_now = Timezone.parse(timezone_name).localize(now)
    since_start = (local_now.hour - window.start_hour) % _HOURS_PER_DAY
    length = (window.end_hour - window.start_hour) % _HOURS_PER_DAY
    if since_start >= length:
        return None
    hours_left = (window.end_hour - local_now.hour) % _HOURS_PER_DAY
    # Aware-datetime arithmetic is wall-clock arithmetic: the offset is recomputed
    # for the resulting local time, which is what makes the end DST-correct.
    top_of_hour = local_now.replace(minute=0, second=0, microsecond=0)
    return (top_of_hour + timedelta(hours=hours_left)).astimezone(UTC)


def held_until(
    message_class: ProactiveMessageClass,
    window: QuietHours,
    timezone_name: str | None,
    now: datetime,
) -> datetime | None:
    """Return when a message of message_class sent at now may be delivered, or None for now."""
    if message_class in QUIET_HOURS_EXEMPT:
        return None
    return quiet_window_end(window, timezone_name, now)
