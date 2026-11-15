"""Series from the figures the user's apps hold: one categorical series per kind of item that carries an amount.

Any connected app counts the same way: a scout that read an amount on its items (an
invoice's total, a payout, a deal's value) gives one bar per item, in the unit the app's
values read; an amount the app gives no unit for is a series with no unit.
"""

from collections.abc import Sequence
from itertools import groupby
import re

from app.models.brief_pool_models import DataSeries, SeriesPoint
from app.models.scout_models import Signal
from app.services.briefing.fact_pool.window import SeriesName, categorical_series

_ID_WORD = re.compile(r"[a-z0-9]+")
# A unit the app counts in hundredths of another ("USD cents"): said in the whole unit.
_HUNDREDTHS = re.compile(r"^(?P<unit>.+?)\s+cents$", re.IGNORECASE)
_CENTS_PER_UNIT = 100
_MONEY_DECIMALS = 2


def _in_whole_units(amount: float, unit: str | None) -> tuple[float, str | None]:
    """Return an amount in the unit people say: 1250 USD cents is 12.5 USD."""
    match = _HUNDREDTHS.match(unit or "")
    if match is None:
        return amount, unit
    return round(amount / _CENTS_PER_UNIT, _MONEY_DECIMALS), match.group("unit")


def _slug(text: str) -> str:
    return "_".join(_ID_WORD.findall(text.casefold()))


def _group(signal: Signal) -> tuple[str, str, str | None]:
    return (signal.integration_id, signal.kind, _in_whole_units(0, signal.amount_unit)[1])


def _order(signal: Signal) -> tuple[str, str, str]:
    """Order a unitless amount before the same kind's united ones; the blank is a sort key only."""
    return (signal.integration_id, signal.kind, _group(signal)[2] or "")


def signal_series(signals: Sequence[Signal]) -> list[DataSeries]:
    """Return one series per app and kind of item with a figure, each item one category."""
    counted = sorted((s for s in signals if s.amount is not None), key=_order)
    found: list[DataSeries] = []
    for (integration_id, kind, unit), items in groupby(counted, key=_group):
        group = list(items)
        parts = [integration_id, kind] if unit is None else [integration_id, kind, unit]
        name = SeriesName(
            id="_".join(_slug(part) for part in parts),
            label=kind,
            unit=unit,
            source=integration_id,
            app=group[0].app,
        )
        series = categorical_series(
            name,
            [
                SeriesPoint(x=s.title, y=_in_whole_units(s.amount, s.amount_unit)[0])
                for s in group
                if s.amount is not None
            ],
        )
        if series is not None:
            found.append(series.model_copy(update={"shown_not_total": True}))
    return found
