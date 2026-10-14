"""Quiet hours: when a proactive chat message may reach the user.

The one policy for every message GAIA sends on its own initiative. The user's
window is whole local hours on their own clock and may span midnight (22 to 8
is 22:00 to 08:00); a message that falls inside it is held until the window's
end, never dropped. A reminder the user timed themselves is exempt: it arrives
when they asked, and so does a reply to something the user just did.
post_to_platform_chat is the only sender that asks; the brief's schedule uses
contains_hour to run at an hour the user is awake.
"""

from datetime import UTC, datetime, timedelta

from app.constants.notifications import ProactiveMessageClass
from app.models.notification.notification_models import QuietHours
from app.utils.timezone import Timezone

#: Classes delivered even inside the user's quiet hours.
QUIET_HOURS_EXEMPT: frozenset[ProactiveMessageClass] = frozenset(
    {ProactiveMessageClass.USER_TIMED, ProactiveMessageClass.USER_TRIGGERED}
)

_HOURS_PER_DAY = 24


def contains_hour(window: QuietHours, local_hour: int) -> bool:
    """Whether local_hour (0-23, on the user's clock) is inside window, across midnight too."""
    since_start = (local_hour - window.start_hour) % _HOURS_PER_DAY
    return since_start < (window.end_hour - window.start_hour) % _HOURS_PER_DAY


def quiet_window_end(
    window: QuietHours, timezone_name: str | None, now: datetime
) -> datetime | None:
    """Return the UTC instant window ends when now is inside it on the user's clock, else None.

    The end is a wall-clock hour in the user's zone (UTC when unset), so a DST
    change inside the window moves the instant, not the hour the user chose. An
    end hour that a spring-forward skips resolves to the first instant after the gap.
    """
    local_now = Timezone.parse(timezone_name).localize(now)
    if not contains_hour(window, local_now.hour):
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
