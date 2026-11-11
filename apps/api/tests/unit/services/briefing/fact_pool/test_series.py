"""Every series producer, against the documents its store holds: one point per local day, or per category."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from tests.factories import make_user_id

from app.constants.desk_buckets import DeskBucket
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.brief_pool_models import SeriesPoint, SeriesShape
from app.models.calendar_models import GoogleCalendarEventDateTime, GoogleCalendarEventResource
from app.models.email_verdict_models import EmailVerdictDocument
from app.models.scout_models import Signal
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.workflow_execution_models import RunMoment
from app.services.briefing.fact_pool.calendar_series import calendar_series
from app.services.briefing.fact_pool.mail_series import sorted_mail_series, thread_series
from app.services.briefing.fact_pool.run_series import run_series
from app.services.briefing.fact_pool.signal_series import signal_series
from app.services.briefing.fact_pool.window import SeriesWindow
from app.services.briefing.fact_pool.work_series import work_series

USER_ID = make_user_id()
KOLKATA = ZoneInfo("Asia/Kolkata")
# Thursday 5 Nov to Wednesday 11 Nov 2026, on a Kolkata clock (UTC+5:30).
WINDOW = SeriesWindow(first_day=date(2026, 11, 5), days=7, tz=KOLKATA)
DAYS = [f"2026-11-{d:02d}" for d in range(5, 12)]


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    """Return a November 2026 moment on the user's clock as UTC, the way Mongo hands it back."""
    return datetime(2026, 11, day, hour, minute, tzinfo=KOLKATA).astimezone(UTC)


def _todo(title: str, *labels: str, **fields: object) -> TodoDocument:
    return TodoDocument.model_validate(
        {"id": title, "user_id": USER_ID, "title": title, "labels": list(labels), **fields}
    )


def _ys(values: Sequence[float]) -> list[SeriesPoint]:
    return [SeriesPoint(x=x, y=y) for x, y in zip(DAYS, values, strict=True)]


class TestWindow:
    def test_a_moment_falls_on_the_users_local_day_not_its_utc_one(self) -> None:
        # 20:00 UTC on 4 Nov is 01:30 on 5 Nov in Kolkata: the window's first day.
        assert WINDOW.day_of(datetime(2026, 11, 4, 20, 0, tzinfo=UTC)) == date(2026, 11, 5)
        assert WINDOW.day_of(datetime(2026, 11, 4, 18, 0, tzinfo=UTC)) is None
        assert WINDOW.day_of(_local(12, 0, 1)) is None

    def test_its_bounds_are_local_midnights(self) -> None:
        assert (WINDOW.start, WINDOW.end) == (
            datetime(2026, 11, 4, 18, 30, tzinfo=UTC),
            datetime(2026, 11, 11, 18, 30, tzinfo=UTC),
        )


class TestWorkSeries:
    def test_completions_are_counted_per_local_day_by_who_finished_them(self) -> None:
        completed = [
            _todo("Investor update", GAIA_TRACKED_LABEL, completed=True, completed_at=_local(5, 9)),
            _todo("Lisbon flights", GAIA_TRACKED_LABEL, completed=True, completed_at=_local(9, 23)),
            _todo("Deck research", GAIA_TRACKED_LABEL, completed=True, completed_at=_local(9, 7)),
            _todo("Call the bank", completed=True, completed_at=_local(11, 8)),
        ]

        gaia, user = work_series(completed, WINDOW)

        assert (gaia.id, gaia.shape, gaia.points) == (
            "gaia_finished",
            SeriesShape.TIME_SERIES,
            _ys([1, 0, 0, 0, 2, 0, 0]),
        )
        assert (user.id, user.unit, user.points) == ("you_finished", "todos", _ys([0] * 6 + [1]))

    def test_mail_threads_are_the_mail_series_and_an_owner_with_none_is_left_out(self) -> None:
        thread = _todo(
            "Re: offsite",
            GAIA_TRACKED_LABEL,
            completed=True,
            completed_at=_local(6, 10),
            external_ref=ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="t-1"),
        )
        done = _todo("Board memo", GAIA_TRACKED_LABEL, completed=True, completed_at=_local(6, 11))

        assert [s.points for s in work_series([thread, done], WINDOW)] == [
            _ys([0, 1, 0, 0, 0, 0, 0])
        ]

    def test_nothing_finished_is_no_series(self) -> None:
        assert work_series([], WINDOW) == []


def _event(
    start: str | None, end: str | None, *, all_day: str | None = None, kind: str | None = None
) -> GoogleCalendarEventResource:
    return GoogleCalendarEventResource(
        summary="Meeting",
        eventType=kind,
        start=GoogleCalendarEventDateTime(dateTime=start, date=all_day),
        end=GoogleCalendarEventDateTime(dateTime=end, date=all_day),
    )


class TestCalendarSeries:
    def test_meeting_hours_count_overlaps_once_and_split_at_midnight(self) -> None:
        raw = [
            _event("2026-11-10T10:00:00+05:30", "2026-11-10T11:30:00+05:30"),
            # Overlaps the first by half an hour, on another calendar.
            _event("2026-11-10T11:00:00+05:30", "2026-11-10T12:00:00+05:30"),
            # A late call that runs an hour past midnight into the 11th.
            _event("2026-11-10T23:00:00+05:30", "2026-11-11T01:00:00+05:30"),
            _event("2026-11-06T09:00:00Z", "2026-11-06T09:45:00Z"),
        ]

        [series] = calendar_series(raw, WINDOW)

        assert (series.id, series.unit, series.app) == (
            "calendar_meeting_hours",
            "hours",
            "Google Calendar",
        )
        assert series.points == _ys([0, 0.8, 0, 0, 0, 3, 1])

    def test_all_day_events_and_focus_blocks_are_not_meetings(self) -> None:
        raw = [
            _event(None, None, all_day="2026-11-07"),
            _event("2026-11-07T09:00:00+05:30", "2026-11-07T12:00:00+05:30", kind="focusTime"),
            _event("2026-11-07T09:00:00+05:30", "2026-11-07T18:00:00+05:30", kind="outOfOffice"),
        ]

        assert calendar_series(raw, WINDOW) == []


def _thread(created: datetime, completed: datetime | None) -> TodoDocument:
    return _todo(
        f"thread-{created.isoformat()}",
        GAIA_TRACKED_LABEL,
        created_at=created,
        completed=completed is not None,
        completed_at=completed,
        external_ref=ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id=created.isoformat()),
    )


class TestMailSeries:
    def test_threads_taken_on_and_closed_are_counted_on_their_own_days(self) -> None:
        threads = [
            _thread(_local(9, 7), _local(9, 15)),
            _thread(_local(9, 8), _local(11, 9)),
            _thread(_local(10, 7), None),
            # Taken on before the window, closed inside it.
            _thread(_local(2, 7), _local(5, 12)),
        ]

        taken, closed = thread_series(threads, WINDOW)

        assert (taken.id, taken.points) == ("gmail_threads_taken", _ys([0, 0, 0, 0, 2, 1, 0]))
        assert (closed.id, closed.points) == ("gmail_threads_closed", _ys([1, 0, 0, 0, 1, 0, 1]))

    def test_the_days_mail_is_counted_by_what_the_desk_does_with_it(self) -> None:
        buckets = [DeskBucket.JUNK] * 5 + [DeskBucket.REPLY] * 2 + [DeskBucket.FYI, None]
        verdicts = [
            EmailVerdictDocument(user_id=USER_ID, message_id=f"m{i}", answers={}, bucket=b)
            for i, b in enumerate(buckets)
        ]

        [series] = sorted_mail_series(verdicts)

        assert (series.id, series.shape, series.unit) == (
            "gmail_sorted",
            SeriesShape.CATEGORICAL,
            "emails",
        )
        assert series.points == [
            SeriesPoint(x="Needs a reply", y=2),
            SeriesPoint(x="For your information", y=1),
            SeriesPoint(x="Junk", y=5),
        ]

    def test_no_sorted_mail_is_no_series(self) -> None:
        unbucketed = EmailVerdictDocument(user_id=USER_ID, message_id="m", answers={})

        assert sorted_mail_series([unbucketed]) == []


class TestRunSeries:
    def test_runs_are_counted_per_day_by_how_they_ended(self) -> None:
        runs = [
            RunMoment(started_at=_local(8, 6), status="success"),
            RunMoment(started_at=_local(8, 7), status="success"),
            RunMoment(started_at=_local(8, 8), status="failed"),
            RunMoment(started_at=_local(11, 6), status="running"),
            RunMoment(started_at=_local(11, 6), status="skipped"),
        ]

        succeeded, failed = run_series(runs, WINDOW)

        assert (succeeded.id, succeeded.points) == (
            "workflows_succeeded",
            _ys([0, 0, 0, 2, 0, 0, 0]),
        )
        assert (failed.id, failed.points) == ("workflows_failed", _ys([0, 0, 0, 1, 0, 0, 0]))

    def test_a_week_of_runs_still_going_is_no_series(self) -> None:
        assert run_series([RunMoment(started_at=_local(8, 6), status="running")], WINDOW) == []


def _signal(title: str, **fields: object) -> Signal:
    return Signal.model_validate(
        {
            "integration_id": "stripe",
            "app": "Stripe",
            "external_id": title,
            "kind": "open invoice",
            "title": title,
            **fields,
        }
    )


class TestSignalSeries:
    def test_items_with_a_figure_are_one_bar_each_per_app_kind_and_unit(self) -> None:
        signals = [
            _signal("INV-2207 Acme Corp", amount=4800, amount_unit="USD"),
            _signal("INV-2211 Globex", amount=1250.5, amount_unit="USD"),
            _signal("Payout to HDFC", kind="payout", amount=9900, amount_unit="USD"),
            _signal("Dispute DP-17"),
            _signal("INV-9 Initech", amount=7, amount_unit=None),
        ]

        invoices, payouts = sorted(signal_series(signals), key=lambda s: s.label)

        assert (invoices.id, invoices.label, invoices.unit, invoices.app) == (
            "stripe_open_invoice_usd",
            "open invoice",
            "USD",
            "Stripe",
        )
        assert invoices.points == [
            SeriesPoint(x="INV-2207 Acme Corp", y=4800),
            SeriesPoint(x="INV-2211 Globex", y=1250.5),
        ]
        assert (payouts.id, payouts.shape) == ("stripe_payout_usd", SeriesShape.CATEGORICAL)

    @pytest.mark.parametrize("app", ["hubspot", "github", "notion"])
    def test_any_app_counts_the_same_way(self, app: str) -> None:
        signal = _signal("Deal: Northwind renewal", amount=12000, amount_unit="EUR").model_copy(
            update={"integration_id": app, "app": app.title()}
        )

        [series] = signal_series([signal])

        assert (series.source, series.points) == (
            app,
            [SeriesPoint(x="Deal: Northwind renewal", y=12000)],
        )

    def test_signals_without_figures_are_no_series(self) -> None:
        assert signal_series([_signal("Dispute DP-17")]) == []


def test_a_window_moment_outside_every_day_counts_nowhere() -> None:
    later = [_todo("Late", completed=True, completed_at=WINDOW.end + timedelta(minutes=1))]

    assert work_series(later, WINDOW) == []
