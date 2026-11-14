"""Mail series, from what the Inbox desk stores: threads it took on and closed per day, and today's sort.

Each mail thread the desk takes on is a Gmail-thread todo, opened when it took the thread
and completed when the thread was handled. Each email the arrival gate or the desk sorted
keeps its verdict for two days; the last day's verdicts, by bucket, are how the mail
that arrived since yesterday was sorted.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import timedelta

from app.constants.desk_buckets import DeskBucket
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.models.brief_pool_models import DataSeries, SeriesPoint
from app.models.email_verdict_models import EmailVerdictDocument
from app.models.todo_models import TodoDocument
from app.services.briefing.candidates.app_names import integration_name
from app.services.briefing.fact_pool.window import (
    SeriesName,
    SeriesWindow,
    categorical_series,
    day_series,
    per_day,
)

#: How each desk bucket reads as a category of the day's mail.
BUCKET_LABELS: dict[DeskBucket, str] = {
    DeskBucket.REPLY: "Needs a reply",
    DeskBucket.ACT: "To act on",
    DeskBucket.FYI: "For your information",
    DeskBucket.JUNK: "Junk",
}
#: The sort reads the day before the brief: verdicts live two days, so one day is always whole.
SORT_SPAN = timedelta(days=1)
SORTED_SERIES_ID = "gmail_sorted"


def _name(series_id: str, label: str, unit: str) -> SeriesName:
    return SeriesName(
        id=series_id,
        label=label,
        unit=unit,
        source=GMAIL_INTEGRATION_ID,
        app=integration_name(GMAIL_INTEGRATION_ID),
    )


def thread_series(threads: Sequence[TodoDocument], window: SeriesWindow) -> list[DataSeries]:
    """Return the threads the desk took on and closed on each day; a series with none is left out."""
    taken = [t.created_at for t in threads if t.created_at is not None]
    closed = [t.completed_at for t in threads if t.completed_at is not None]
    found = (
        day_series(
            _name("gmail_threads_taken", "Mail threads GAIA took on", "threads"),
            per_day(taken, window),
            window,
        ),
        day_series(
            _name("gmail_threads_closed", "Mail threads closed", "threads"),
            per_day(closed, window),
            window,
        ),
    )
    return [series for series in found if series is not None]


def sorted_mail_series(verdicts: Sequence[EmailVerdictDocument]) -> list[DataSeries]:
    """Return the last day's verdicts by what the desk does with each email; empty when none was sorted."""
    buckets = Counter(v.bucket for v in verdicts)
    series = categorical_series(
        _name(SORTED_SERIES_ID, "Mail sorted since yesterday", "emails"),
        [
            SeriesPoint(x=label, y=float(buckets[bucket]))
            for bucket, label in BUCKET_LABELS.items()
            if buckets[bucket]
        ],
    )
    return [series] if series is not None else []
