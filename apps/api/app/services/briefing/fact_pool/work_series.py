"""Series of finished work: what GAIA and the user each completed per day, from the todos store.

Mail threads are left out: the mail series count them.
"""

from collections.abc import Sequence

from app.constants.briefing import GAIA_APP_NAME, GAIA_SOURCE
from app.models.brief_pool_models import DataSeries
from app.models.todo_models import ExternalRefSource, TodoDocument
from app.services.briefing.context import is_gaia_tracked
from app.services.briefing.fact_pool.window import SeriesName, SeriesWindow, day_series, per_day

GAIA_FINISHED = SeriesName(
    id="gaia_finished",
    label="Tasks GAIA finished",
    unit="tasks",
    source=GAIA_SOURCE,
    app=GAIA_APP_NAME,
)
USER_FINISHED = SeriesName(
    id="you_finished",
    label="Todos you finished",
    unit="todos",
    source=GAIA_SOURCE,
    app=GAIA_APP_NAME,
)


def _mail(doc: TodoDocument) -> bool:
    return doc.external_ref is not None and doc.external_ref.source in (
        ExternalRefSource.GMAIL_THREAD,
        ExternalRefSource.INBOX_DESK,
    )


def work_series(completed: Sequence[TodoDocument], window: SeriesWindow) -> list[DataSeries]:
    """Return GAIA's and the user's completions per day; a series with none at all is left out."""
    work = [d for d in completed if d.completed_at is not None and not _mail(d)]
    by_gaia = [d.completed_at for d in work if d.completed_at and is_gaia_tracked(d)]
    by_user = [d.completed_at for d in work if d.completed_at and not is_gaia_tracked(d)]
    found = (
        day_series(GAIA_FINISHED, per_day(by_gaia, window), window),
        day_series(USER_FINISHED, per_day(by_user, window), window),
    )
    return [series for series in found if series is not None]
