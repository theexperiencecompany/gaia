"""The quiet note: what a brief says when nothing new needs the reader, and how a quiet goes on."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from tests.briefing_factories import make_briefing_payload
from tests.factories import make_user_id
import time_machine

from app.constants.briefing import (
    DAILY_KICKER,
    DAILY_QUIET_HEADLINE,
    WEEKLY_KICKER,
    WEEKLY_QUIET_HEADLINE,
    BriefForm,
    BriefingKind,
)
from app.db.repositories.briefings import briefing_repository
from app.models.brief_document_models import BriefingModel
from app.models.brief_payload_models import BriefingMood, UnreadSource
from app.models.scout_models import ScoutSkipReason
from app.services.briefing.calendar_read import CalendarGap
from app.services.briefing.clock import UserClock, resolve_clock
from app.services.briefing.kinds import KIND_SPECS
from app.services.briefing.quiet_note import QuietFacts, continued, last_was_quiet, quiet_note

USER_ID = make_user_id()
# Wednesday 14 Oct, 07:05 in Kolkata.
_NOW = datetime(2026, 10, 14, 1, 35, tzinfo=UTC)
_DAILY = KIND_SPECS[BriefingKind.DAILY]
_WEEKLY = KIND_SPECS[BriefingKind.WEEKLY]
_WATCH = "I'll flag anything that comes in."


@pytest.fixture
def clock() -> Iterator[UserClock]:
    with time_machine.travel(_NOW, tick=False):
        yield resolve_clock("Asia/Kolkata")


def _brief(day: str, form: BriefForm, kind: BriefingKind = BriefingKind.DAILY) -> BriefingModel:
    return BriefingModel(
        id=f"{kind}-{day}",
        user_id=USER_ID,
        date=day,
        kind=kind,
        payload=make_briefing_payload(date=day, form=form),
    )


def _unread(*apps: tuple[str, ScoutSkipReason]) -> list[UnreadSource]:
    return [UnreadSource(app=app, reason=reason) for app, reason in apps]


class TestTheQuietNote:
    def test_a_quiet_day_says_nothing_new_and_a_clear_calendar_and_draws_no_edition(
        self, clock: UserClock
    ) -> None:
        """Founder decision: a day with nothing placed and nothing on the calendar sends a plain note."""
        note = quiet_note(clock, _DAILY, QuietFacts(calendar=None))

        assert note.message == (
            f"Nothing new needs you today, and your calendar is clear.\n{_WATCH}"
        )
        assert (note.form, note.kicker, note.headline, note.date) == (
            BriefForm.QUIET_NOTE,
            DAILY_KICKER,
            DAILY_QUIET_HEADLINE,
            "2026-10-14",
        )
        assert (note.template_family, note.mood, note.lede, note.caption) == (
            None,
            BriefingMood.IDLE,
            "",
            "",
        )

    def test_a_quiet_week_speaks_of_the_week_and_the_week_ahead(self, clock: UserClock) -> None:
        note = quiet_note(clock, _WEEKLY, QuietFacts(calendar=None))

        assert note.message == (
            f"Nothing moved this week, and next week's calendar is clear.\n{_WATCH}"
        )
        assert (note.kicker, note.headline) == (WEEKLY_KICKER, WEEKLY_QUIET_HEADLINE)

    @pytest.mark.parametrize(
        ("calendar", "first_line"),
        [
            (
                CalendarGap.UNAVAILABLE,
                "Nothing new needs you today. I couldn't read your calendar, so check it "
                "before you plan.",
            ),
            (CalendarGap.NOT_CONNECTED, "Nothing new needs you today."),
        ],
        ids=["unread", "not-connected"],
    )
    def test_a_calendar_that_was_not_read_is_never_called_clear(
        self, clock: UserClock, calendar: CalendarGap, first_line: str
    ) -> None:
        note = quiet_note(clock, _DAILY, QuietFacts(calendar=calendar))

        assert note.message.splitlines() == [first_line, _WATCH]

    def test_an_unread_app_is_never_said_to_hold_nothing_and_each_is_named_once(
        self, clock: UserClock
    ) -> None:
        """Audit: an app that could not be read looked empty, and the note said nothing needs you."""
        unread = _unread(
            ("Notion", ScoutSkipReason.FAILED),
            ("Linear", ScoutSkipReason.FAILED),
            ("Notion", ScoutSkipReason.FAILED),
        )

        note = quiet_note(clock, _DAILY, QuietFacts(calendar=None, unread=unread))

        assert note.headline == "Nothing new in what I could read"
        assert note.message.splitlines() == [
            "Nothing new in what I could read, and your calendar is clear.",
            "I couldn't read Notion and Linear this time, so I can't say what they hold.",
            _WATCH,
        ]
        assert note.sources_unavailable == unread

    def test_a_signed_out_app_is_asked_to_reconnect_and_left_out_of_the_unread_line(
        self, clock: UserClock
    ) -> None:
        unread = _unread(("GitHub", ScoutSkipReason.SIGNED_OUT), ("Notion", ScoutSkipReason.FAILED))

        note = quiet_note(clock, _DAILY, QuietFacts(calendar=None, unread=unread))

        assert note.message.splitlines()[1:] == [
            "I couldn't read Notion this time, so I can't say what they hold.",
            "Your GitHub sign-in expired: reconnect it in Settings, Integrations and I'll read "
            "it again.",
            _WATCH,
        ]

    def test_past_three_unread_apps_the_rest_are_counted_not_named(self, clock: UserClock) -> None:
        """Prod 2026-11-24: a note chained 17 app names with "or" in one sentence."""
        apps = ("YouTube", "PumpGTM", "Context7", "Whoop", "Twitter")
        unread = _unread(*((app, ScoutSkipReason.BUDGET) for app in apps))

        note = quiet_note(clock, _DAILY, QuietFacts(calendar=None, unread=unread))

        assert note.message.splitlines()[1] == (
            "I couldn't read YouTube, PumpGTM, Context7 and 2 others this time, so I can't say "
            "what they hold."
        )

    def test_every_signed_out_app_is_asked_to_reconnect_in_one_line(self, clock: UserClock) -> None:
        unread = _unread(
            ("GitHub", ScoutSkipReason.SIGNED_OUT),
            ("Linear", ScoutSkipReason.SIGNED_OUT),
            ("Granola", ScoutSkipReason.SIGNED_OUT),
        )

        note = quiet_note(clock, _DAILY, QuietFacts(calendar=None, unread=unread))

        assert note.message.splitlines()[1:] == [
            "Your GitHub, Linear and Granola sign-ins expired: reconnect them in Settings, "
            "Integrations and I'll read them again.",
            _WATCH,
        ]

    def test_the_users_overdue_todos_are_counted_before_the_watch_line(
        self, clock: UserClock
    ) -> None:
        """Replay: a user with 70 overdue todos of their own was never told of one."""
        note = quiet_note(clock, _DAILY, QuietFacts(calendar=None, overdue=70))

        assert note.message.splitlines()[1:] == ["70 of your own todos are past due.", _WATCH]

    @pytest.mark.parametrize(
        ("edition_day", "first_line"),
        [
            (
                "2026-10-13",
                "Still nothing new since your brief yesterday, and next week's calendar is clear.",
            ),
            (
                "2026-10-05",
                "Still nothing new: 9 days since your brief on Monday Oct 5, and next week's "
                "calendar is clear.",
            ),
            (None, "Still nothing new, as in your last briefs, and next week's calendar is clear."),
        ],
        ids=["edition-yesterday", "edition-days-ago", "no-edition-ever"],
    )
    def test_a_quiet_that_goes_on_says_since_which_brief(
        self, clock: UserClock, edition_day: str | None, first_line: str
    ) -> None:
        last = _brief(edition_day, BriefForm.EDITION) if edition_day else None

        note = quiet_note(
            clock, _WEEKLY, QuietFacts(calendar=None, still_quiet=True, last_edition=last)
        )

        assert note.message.splitlines()[0] == first_line


class TestHowAQuietGoesOn:
    def test_only_the_latest_brief_of_its_own_kind_says_whether_the_last_was_quiet(self) -> None:
        """Replay: the day after a drawn daily, a quiet weekly made it "2 quiet days"."""
        recent = [
            _brief("2026-10-13", BriefForm.QUIET_NOTE, BriefingKind.WEEKLY),
            _brief("2026-10-13", BriefForm.EDITION),
            _brief("2026-10-12", BriefForm.QUIET_NOTE),
        ]

        assert last_was_quiet(recent, BriefingKind.DAILY) is False
        assert last_was_quiet(recent, BriefingKind.WEEKLY) is True
        assert last_was_quiet([], BriefingKind.DAILY) is False

    async def test_after_a_quiet_note_the_quiet_goes_on_from_the_last_edition(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        edition = _brief("2026-10-12", BriefForm.EDITION)
        editions = AsyncMock(return_value=[edition])
        monkeypatch.setattr(briefing_repository, "list_recent", editions)
        facts = QuietFacts(calendar=CalendarGap.UNAVAILABLE, overdue=3)

        went_on = await continued(
            USER_ID, BriefingKind.DAILY, [_brief("2026-10-13", BriefForm.QUIET_NOTE)], facts
        )

        assert went_on == QuietFacts(
            calendar=CalendarGap.UNAVAILABLE, overdue=3, still_quiet=True, last_edition=edition
        )
        editions.assert_awaited_once_with(USER_ID, limit=1, editions_only=True)

    async def test_after_an_edition_the_quiet_is_new_and_nothing_more_is_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        editions = AsyncMock()
        monkeypatch.setattr(briefing_repository, "list_recent", editions)
        facts = QuietFacts(calendar=None)

        went_on = await continued(
            USER_ID, BriefingKind.DAILY, [_brief("2026-10-13", BriefForm.EDITION)], facts
        )

        assert went_on is facts
        editions.assert_not_awaited()
