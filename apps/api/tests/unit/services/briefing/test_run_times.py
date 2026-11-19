"""When each brief lands: its weekdays by frequency, at its hour past quiet hours."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.constants.briefing import (
    DAILY_BRIEFING_WORKFLOW_KEY,
    WEEKLY_DIGEST_WORKFLOW_KEY,
    BriefingFrequency,
)
from app.models.brief_settings_models import BriefingSchedule
from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS, QuietHours
from app.models.user_models import UserDocument
from app.services.briefing import run_times
from app.workers.brief_slots import slot_minute

_KOLKATA = ZoneInfo("Asia/Kolkata")
_MINUTE = 12


def _slots(
    frequency: BriefingFrequency = BriefingFrequency.DAILY, hour: int = 8
) -> dict[str, run_times.BriefSlot]:
    return run_times.brief_slots(
        BriefingSchedule(frequency=frequency, hour=hour), DEFAULT_QUIET_HOURS, _MINUTE
    )


class TestTheDailyBriefsCron:
    @pytest.mark.parametrize(
        ("quiet_hours", "cron"),
        [
            (DEFAULT_QUIET_HOURS, "8 * * *"),
            (QuietHours(enabled=True, start_hour=22, end_hour=8), "8 * * *"),
            (QuietHours(enabled=True, start_hour=13, end_hour=17), "8 * * *"),
            (QuietHours(enabled=True, start_hour=0, end_hour=10), "10 * * *"),
            (QuietHours(enabled=True, start_hour=23, end_hour=9), "9 * * *"),
            (QuietHours(enabled=True, start_hour=8, end_hour=11), "11 * * *"),
            (QuietHours(enabled=False, start_hour=0, end_hour=10), "8 * * *"),
        ],
        ids=[
            "default",
            "ends-at-8",
            "afternoon",
            "until-10",
            "past-midnight",
            "starts-at-8",
            "switched-off",
        ],
    )
    def test_the_brief_runs_at_8_or_when_quiet_hours_end(
        self, quiet_hours: QuietHours, cron: str
    ) -> None:
        user = UserDocument(quiet_hours=quiet_hours)

        assert (
            run_times.briefing_cron(DAILY_BRIEFING_WORKFLOW_KEY, user, BriefingSchedule())
            == f"{slot_minute(user.id)} {cron}"
        )

    @pytest.mark.parametrize(
        ("frequency", "hour", "cron"),
        [
            (BriefingFrequency.WEEKDAYS, 8, "8 * * 1-5"),
            (BriefingFrequency.DAILY, 6, "8 * * *"),
            (BriefingFrequency.DAILY, 9, "9 * * *"),
            (BriefingFrequency.WEEKDAYS, 23, "8 * * 1-5"),
            (BriefingFrequency.OFF, 9, "9 * * *"),
        ],
        ids=["weekdays", "inside-quiet-hours", "own-hour", "weekdays-late", "off-keeps-every-day"],
    )
    def test_the_brief_runs_on_the_users_days_and_hour(
        self, frequency: BriefingFrequency, hour: int, cron: str
    ) -> None:
        user = UserDocument()
        schedule = BriefingSchedule(frequency=frequency, hour=hour)

        assert (
            run_times.briefing_cron(DAILY_BRIEFING_WORKFLOW_KEY, user, schedule)
            == f"{slot_minute(user.id)} {cron}"
        )


class TestTheWeeklyDigestsCron:
    def test_it_runs_on_sunday_at_five(self) -> None:
        user = UserDocument()

        assert (
            run_times.briefing_cron(WEEKLY_DIGEST_WORKFLOW_KEY, user, BriefingSchedule())
            == f"{slot_minute(user.id)} 17 * * 0"
        )

    def test_quiet_hours_covering_it_push_it_to_when_they_end(self) -> None:
        user = UserDocument(quiet_hours=QuietHours(enabled=True, start_hour=16, end_hour=19))

        assert (
            run_times.briefing_cron(WEEKLY_DIGEST_WORKFLOW_KEY, user, BriefingSchedule())
            == f"{slot_minute(user.id)} 19 * * 0"
        )


class TestBriefSlots:
    @pytest.mark.parametrize(
        ("frequency", "keys"),
        [
            (BriefingFrequency.DAILY, [DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY]),
            (BriefingFrequency.WEEKDAYS, [DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY]),
            (BriefingFrequency.WEEKLY_ONLY, [WEEKLY_DIGEST_WORKFLOW_KEY]),
            (BriefingFrequency.OFF, []),
        ],
    )
    def test_each_frequency_runs_its_briefs(
        self, frequency: BriefingFrequency, keys: list[str]
    ) -> None:
        assert list(_slots(frequency)) == keys


class TestDescribeBriefingSchedule:
    @pytest.mark.parametrize(
        ("frequency", "hour", "text"),
        [
            (
                BriefingFrequency.DAILY,
                9,
                "a daily brief every day at 9:12 AM, plus the weekly digest on Sunday at 5:12 PM",
            ),
            (
                BriefingFrequency.WEEKDAYS,
                6,
                "a daily brief Monday to Friday at 8:12 AM, plus the weekly digest on Sunday at 5:12 PM",
            ),
            (
                BriefingFrequency.WEEKLY_ONLY,
                9,
                "only the weekly digest on Sunday at 5:12 PM, no daily brief",
            ),
            (BriefingFrequency.OFF, 9, "no briefs at all"),
        ],
    )
    def test_it_names_the_briefs_and_the_hour_they_really_land(
        self, frequency: BriefingFrequency, hour: int, text: str
    ) -> None:
        assert run_times.describe_briefing_schedule(_slots(frequency, hour)) == text


class TestNextBriefLands:
    @pytest.mark.parametrize(
        ("frequency", "now", "lands"),
        [
            # Wednesday 14 Oct, 07:00: today's daily is still ahead.
            (BriefingFrequency.DAILY, datetime(2026, 10, 14, 7), "today at 9:12 AM"),
            # Friday evening on weekdays: Sunday's digest comes before Monday's daily.
            (BriefingFrequency.WEEKDAYS, datetime(2026, 10, 16, 20), "Sunday at 5:12 PM"),
            (BriefingFrequency.WEEKDAYS, datetime(2026, 10, 18, 18), "tomorrow at 9:12 AM"),
            (BriefingFrequency.WEEKLY_ONLY, datetime(2026, 10, 14, 7), "Sunday at 5:12 PM"),
            # 09:05: the hour has struck, but today's daily lands at its minute, still ahead.
            (BriefingFrequency.DAILY, datetime(2026, 10, 14, 9, 5), "today at 9:12 AM"),
            (BriefingFrequency.DAILY, datetime(2026, 10, 14, 9, 12), "tomorrow at 9:12 AM"),
        ],
        ids=[
            "daily-today",
            "weekdays-friday",
            "weekdays-sunday-evening",
            "weekly-only",
            "before-the-minute",
            "at-the-minute",
        ],
    )
    def test_it_is_the_soonest_brief_of_any_kind(
        self, frequency: BriefingFrequency, now: datetime, lands: str
    ) -> None:
        now_local = now.replace(tzinfo=_KOLKATA)

        assert run_times.next_brief_lands(_slots(frequency, 9), now_local) == lands

    def test_briefs_off_promise_none(self) -> None:
        now_local = datetime(2026, 10, 14, 7, tzinfo=_KOLKATA)

        assert run_times.next_brief_lands(_slots(BriefingFrequency.OFF), now_local) is None


class TestTheInboxDesksRecurrence:
    @pytest.mark.parametrize(
        ("frequency", "hour", "recurrence"),
        [
            (BriefingFrequency.DAILY, 8, "0 7 * * *"),
            (BriefingFrequency.DAILY, 10, "0 9 * * *"),
            # Quiet hours until 08:00 hold a 6 AM brief, and the desk with it.
            (BriefingFrequency.DAILY, 6, "0 7 * * *"),
            (BriefingFrequency.WEEKLY_ONLY, 10, "0 9 * * *"),
        ],
    )
    def test_it_sweeps_an_hour_ahead_of_the_daily_brief(
        self, frequency: BriefingFrequency, hour: int, recurrence: str
    ) -> None:
        schedule = BriefingSchedule(frequency=frequency, hour=hour)

        assert run_times.inbox_desk_recurrence(schedule, DEFAULT_QUIET_HOURS) == recurrence

    def test_a_brief_at_midnight_sweeps_the_hour_before_it(self) -> None:
        quiet_off = QuietHours(enabled=False, start_hour=22, end_hour=8)

        assert run_times.inbox_desk_recurrence(BriefingSchedule(hour=0), quiet_off) == "0 23 * * *"


class TestWeekdaySpelling:
    @pytest.mark.parametrize(
        ("days", "cron", "phrase"),
        [
            (frozenset({0, 1, 3}), "1-2,4", "on Monday, Tuesday, Thursday"),
            (frozenset({0, 1}), "1-2", "on Monday, Tuesday"),
            (frozenset({0, 1, 2}), "1-3", "Monday to Wednesday"),
            (frozenset({1, 2, 3}), "2-4", "Tuesday to Thursday"),
            (frozenset({0, 2}), "1,3", "on Monday, Wednesday"),
        ],
    )
    def test_a_set_of_weekdays_is_spelled_as_cron_and_in_words(
        self, days: frozenset[int], cron: str, phrase: str
    ) -> None:
        assert (run_times._cron_days(days), run_times._days_phrase(days)) == (cron, phrase)
