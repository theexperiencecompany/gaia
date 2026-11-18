"""When the briefs land: each brief's weekdays by frequency, at its hour past quiet hours.

BRIEF_RUN_DAYS names the briefs each frequency runs and the weekdays they land on: the
daily brief at the user's hour, the weekly digest on Sunday at WEEKLY_DIGEST_HOUR. A
brief whose hour falls inside quiet hours runs when they end. Every cron, description,
next landing and the Inbox desk's sweep hour derive from that one spec.
"""

import calendar
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.constants.briefing import (
    BRIEF_RUN_DAYS,
    DAILY_BRIEFING_WORKFLOW_KEY,
    EVERY_DAY,
    WEEKLY_DIGEST_HOUR,
    WEEKLY_DIGEST_WORKFLOW_KEY,
    BriefingFrequency,
)
from app.constants.todos import INBOX_DESK_LEAD_HOURS
from app.models.brief_settings_models import BriefingSchedule
from app.models.quiet_hours_models import QuietHours
from app.models.user_models import UserDocument
from app.workers.brief_slots import spread_cron


@dataclass(frozen=True)
class BriefSlot:
    """One brief a schedule runs: the weekdays (Monday 0) it lands on, and its local hour."""

    days: frozenset[int]
    hour: int

    @property
    def cron(self) -> str:
        return f"0 {self.hour} * * {_cron_days(self.days)}"


def _cron_days(days: frozenset[int]) -> str:
    """Spell weekdays (Monday 0) as a cron day-of-week field (Sunday 0): "*", "1-5", "0"."""
    if days == EVERY_DAY:
        return "*"
    runs: list[list[int]] = []
    for number in sorted((day + 1) % 7 for day in days):
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    return ",".join(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]) for run in runs)


def _days_phrase(days: frozenset[int]) -> str:
    """Say which weekdays a brief lands on: "every day", "Monday to Friday", "on Sunday"."""
    if days == EVERY_DAY:
        return "every day"
    ordered = sorted(days)
    names = [calendar.day_name[day] for day in ordered]
    if len(ordered) > 2 and ordered == list(range(ordered[0], ordered[-1] + 1)):
        return f"{names[0]} to {names[-1]}"
    return f"on {', '.join(names)}"


def _past_quiet_hours(hour: int, quiet_hours: QuietHours) -> int:
    """Return hour, or the hour the quiet hours covering it end at."""
    # Quiet hours read only the hour on the clock; any day stands in for the brief's.
    slot = datetime.min.replace(hour=hour, tzinfo=UTC)
    return quiet_hours.end_after(slot).hour


def brief_slots(schedule: BriefingSchedule, quiet_hours: QuietHours) -> dict[str, BriefSlot]:
    """Return the briefs the schedule runs, by workflow key, each at its hour past quiet hours."""
    hours = {
        DAILY_BRIEFING_WORKFLOW_KEY: schedule.hour,
        WEEKLY_DIGEST_WORKFLOW_KEY: WEEKLY_DIGEST_HOUR,
    }
    return {
        key: BriefSlot(days, _past_quiet_hours(hours[key], quiet_hours))
        for key, days in BRIEF_RUN_DAYS[schedule.frequency].items()
    }


_BRIEF_NAMES: dict[str, str] = {
    DAILY_BRIEFING_WORKFLOW_KEY: "a daily brief",
    WEEKLY_DIGEST_WORKFLOW_KEY: "the weekly digest",
}


def describe_briefing_schedule(slots: Mapping[str, BriefSlot]) -> str:
    """Say in plain words which briefs the slots run and when each lands."""
    runs = [
        f"{_BRIEF_NAMES[key]} {_days_phrase(slot.days)} at {slot.hour:02d}:00"
        for key, slot in slots.items()
    ]
    if not runs:
        return "no briefs at all"
    if DAILY_BRIEFING_WORKFLOW_KEY not in slots:
        return f"only {', plus '.join(runs)}, no daily brief"
    return ", plus ".join(runs)


def next_brief_lands(slots: Mapping[str, BriefSlot], now_local: datetime) -> str | None:
    """Say when the next brief of any kind lands on the user's clock ("tomorrow at 7 AM"); None when briefs are off."""
    if not slots:
        return None
    ahead, hour = min(
        (days, slot.hour)
        for slot in slots.values()
        for days in range(8)
        if (now_local + timedelta(days=days)).weekday() in slot.days
        and (days or now_local.hour < slot.hour)
    )
    day = {0: "today", 1: "tomorrow"}.get(ahead, (now_local + timedelta(days=ahead)).strftime("%A"))
    return f"{day} at {now_local.replace(hour=hour).strftime('%-I %p')}"


def briefing_cron(key: str, user: UserDocument, schedule: BriefingSchedule) -> str:
    """Return the cron the schedule gives the user's briefing workflow under key, at their slot minute.

    A workflow the frequency does not run keeps the every-day cron at the user's hour.
    """
    slots = _slots_running(key, schedule, user.effective_quiet_hours)
    return spread_cron(slots[key].cron, user.id)


def _slots_running(
    key: str, schedule: BriefingSchedule, quiet_hours: QuietHours
) -> dict[str, BriefSlot]:
    """Return the schedule's slots, as on an every-day schedule when it does not run key."""
    if key not in BRIEF_RUN_DAYS[schedule.frequency]:
        schedule = schedule.model_copy(update={"frequency": BriefingFrequency.DAILY})
    return brief_slots(schedule, quiet_hours)


def inbox_desk_recurrence(schedule: BriefingSchedule, quiet_hours: QuietHours) -> str:
    """Return the Inbox desk's daily cron: INBOX_DESK_LEAD_HOURS before the daily brief."""
    daily = _slots_running(DAILY_BRIEFING_WORKFLOW_KEY, schedule, quiet_hours)
    hour = (daily[DAILY_BRIEFING_WORKFLOW_KEY].hour - INBOX_DESK_LEAD_HOURS) % 24
    return f"0 {hour} * * *"
