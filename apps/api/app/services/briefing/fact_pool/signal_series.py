"""Series from the figures the user's apps hold: one categorical series per kind of item that carries an amount.

Any connected app counts the same way: a scout that read an amount on its items (an
invoice's total, a payout, a deal's value) gives one bar per item, in the unit the app's
values read. Items whose amount has no unit say nothing a reader can trust, so they are
left out.
"""

from collections.abc import Sequence
from itertools import groupby
import re

from app.models.brief_pool_models import DataSeries, SeriesPoint
from app.models.scout_models import Signal
from app.services.briefing.fact_pool.window import SeriesName, categorical_series

_ID_UNSAFE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _ID_UNSAFE.sub("_", text.casefold()).strip("_")


def _group(signal: Signal) -> tuple[str, str, str]:
    return (signal.integration_id, signal.kind, signal.amount_unit or "")


def signal_series(signals: Sequence[Signal]) -> list[DataSeries]:
    """Return one series per app and kind of item with a figure, each item one category."""
    counted = sorted((s for s in signals if s.amount is not None and s.amount_unit), key=_group)
    found: list[DataSeries] = []
    for (integration_id, kind, unit), items in groupby(counted, key=_group):
        group = list(items)
        name = SeriesName(
            id="_".join(_slug(part) for part in (integration_id, kind, unit)),
            label=kind,
            unit=unit,
            source=integration_id,
            app=group[0].app,
        )
        series = categorical_series(
            name, [SeriesPoint(x=s.title, y=s.amount) for s in group if s.amount is not None]
        )
        if series is not None:
            found.append(series)
    return found
