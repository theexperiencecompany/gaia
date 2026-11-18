"""Series of finished work: what GAIA and the user each completed per day, from the todos store.

Mail threads are left out: the mail series count them.
"""

from app.constants.briefing import GAIA_APP_NAME, GAIA_SOURCE
from app.models.brief_pool_models import DataSeries
from app.models.todo_models import ExternalRefSource, TodoDocument
from app.services.briefing.clock import DayWindow
from app.services.briefing.fact_pool.series import SeriesName, day_series, per_day
from app.services.briefing.work import CompletedWork

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


def work_series(completed: CompletedWork, window: DayWindow) -> list[DataSeries]:
    """Return what GAIA and the user each finished per day; a series with none at all is left out."""
    by_gaia = [d.completed_at for d in completed.gaia if d.completed_at and not _mail(d)]
    by_user = [d.completed_at for d in completed.user if d.completed_at and not _mail(d)]
    found = (
        day_series(GAIA_FINISHED, per_day(by_gaia, window), window),
        day_series(USER_FINISHED, per_day(by_user, window), window),
    )
    return [series for series in found if series is not None]
