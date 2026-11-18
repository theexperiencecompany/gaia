"""The daily brief and the weekly digest as one run reads them: every setting that differs by kind."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.agents.prompts.brief_composition_prompts import DAILY_FRAME, WEEKLY_FRAME
from app.constants.briefing import (
    BRIEF_VOICE_TIMEOUT_SECONDS,
    DAILY_KICKER,
    DAILY_QUIET_CALENDAR_CLEAR,
    DAILY_QUIET_HEADLINE,
    DAILY_QUIET_NOTHING_NEW,
    SERIES_WINDOW_DAYS,
    WEEKLY_KICKER,
    WEEKLY_QUIET_CALENDAR_CLEAR,
    WEEKLY_QUIET_HEADLINE,
    WEEKLY_QUIET_NOTHING_NEW,
    BriefingKind,
    BriefingRunOutcome,
    EditionFamily,
)
from app.constants.notifications import NotificationKind
from app.models.user_models import UserDocument
from app.services.briefing.clock import DayWindow, UserClock
from app.services.briefing.daily import stand_daily
from app.services.briefing.facts import TODAY, WEEK_AHEAD, BriefSpan
from app.services.briefing.standing import Standing
from app.services.briefing.weekly import stand_weekly


@dataclass(frozen=True)
class QuietWords:
    """What a kind's quiet note says when nothing needs the reader."""

    headline: str
    nothing_new: str
    calendar_clear: str


@dataclass(frozen=True)
class BriefKindSpec:
    """One kind of brief: its masthead, its windows, its quiet rule, its edition and its standing.

    stand reads where the reader stands, or ends the run before any model cost.
    """

    kind: BriefingKind
    kicker: str
    notification_kind: NotificationKind
    #: The local days the brief's series and goals cover.
    series_window: Callable[[UserClock], DayWindow]
    #: The days the brief's calendar and what falls due cover: today, or the week ahead.
    span: BriefSpan
    stand: Callable[[UserDocument, UserClock], Awaitable[Standing | BriefingRunOutcome]]
    quiet: QuietWords
    #: A quiet note after a quiet note says the quiet goes on; otherwise the brief stays silent.
    repeats_quiet_note: bool
    #: How the composition is framed, and whether it must place something.
    frame: str
    must_place: bool
    #: A digest recaps the week: what the user finished, the week in numbers and each day's
    #: count, in place of the day's stats and calendar; it carries no held results.
    recaps_week: bool
    #: The family every edition is drawn in; None draws it from the user's rotation.
    fixed_family: EditionFamily | None
    #: The voice call's ceiling: a stalled run fails the cron loudly instead of holding a worker.
    voice_timeout_seconds: int


def _week_ending_today(clock: UserClock) -> DayWindow:
    return clock.days_ending_today(SERIES_WINDOW_DAYS)


KIND_SPECS: dict[BriefingKind, BriefKindSpec] = {
    BriefingKind.DAILY: BriefKindSpec(
        kind=BriefingKind.DAILY,
        kicker=DAILY_KICKER,
        notification_kind=NotificationKind.BRIEFING_DAILY,
        series_window=_week_ending_today,
        span=TODAY,
        stand=stand_daily,
        quiet=QuietWords(
            headline=DAILY_QUIET_HEADLINE,
            nothing_new=DAILY_QUIET_NOTHING_NEW,
            calendar_clear=DAILY_QUIET_CALENDAR_CLEAR,
        ),
        repeats_quiet_note=False,
        frame=DAILY_FRAME,
        must_place=False,
        recaps_week=False,
        fixed_family=None,
        voice_timeout_seconds=BRIEF_VOICE_TIMEOUT_SECONDS,
    ),
    BriefingKind.WEEKLY: BriefKindSpec(
        kind=BriefingKind.WEEKLY,
        kicker=WEEKLY_KICKER,
        notification_kind=NotificationKind.BRIEFING_WEEKLY,
        series_window=UserClock.this_week,
        span=WEEK_AHEAD,
        stand=stand_weekly,
        quiet=QuietWords(
            headline=WEEKLY_QUIET_HEADLINE,
            nothing_new=WEEKLY_QUIET_NOTHING_NEW,
            calendar_clear=WEEKLY_QUIET_CALENDAR_CLEAR,
        ),
        repeats_quiet_note=True,
        frame=WEEKLY_FRAME,
        must_place=True,
        recaps_week=True,
        fixed_family=EditionFamily.WEEKLY,
        voice_timeout_seconds=BRIEF_VOICE_TIMEOUT_SECONDS,
    ),
}
