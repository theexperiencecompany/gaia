"""When a repeating task comes round next: the one place a repeat rule is read and checked."""

from datetime import UTC, datetime

from app.constants.tasks import REPEAT_ANCHORED, REPEAT_INTERVALS
from app.utils.cron_utils import CronError, get_next_run_time
from app.utils.timezone import Timezone
from shared.py.wide_events import log


def next_occurrence(
    rule: str, timezone: str | None = None, anchor: datetime | None = None
) -> datetime | None:
    """Return the rule's next occurrence after now, in UTC; None for a rule nothing can read.

    The rule is wall-clock time in timezone, so a DST change keeps the local hour.
    Daily and weekly keep the anchor's local time, so a late run does not drift it.
    """
    zone = Timezone.parse(timezone)
    now = datetime.now(UTC)
    if rule in REPEAT_INTERVALS:
        return now + REPEAT_INTERVALS[rule]
    if rule in REPEAT_ANCHORED:
        step = REPEAT_ANCHORED[rule]
        if anchor is None:
            return now + step
        anchor_local = anchor.astimezone(zone.tzinfo).replace(tzinfo=None)
        now_local = now.astimezone(zone.tzinfo).replace(tzinfo=None)
        steps = 0 if anchor_local > now_local else (now_local - anchor_local) // step + 1
        # Stepped on the naive wall clock, then localized: the offset is the one of the fire date.
        return (anchor_local + step * steps).replace(tzinfo=zone.tzinfo).astimezone(UTC)
    try:
        return get_next_run_time(rule, now, zone)
    except CronError:
        log.warning("task.repeat_rule_unreadable", rule=rule)
        return None
