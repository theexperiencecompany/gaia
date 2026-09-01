"""Parsing rules shared by the scripts that rebuild history from ``llm_call`` events.

Small, but shared deliberately: both backfills turn log lines into dollar
figures, and a guard that exists in only one of them is a guard that will be
missing from the other the next time someone copies a parser.
"""

from __future__ import annotations

import math


def finite_cost(value: object) -> float | None:
    """A cost we are willing to add up: a real, non-negative number.

    ``None`` for anything else — unparseable, negative, NaN or infinite — so the
    caller can drop the line rather than let it into a sum. ``json.loads``
    accepts ``NaN`` and ``Infinity`` happily, and either one silently poisons
    every total it reaches, including the ones these scripts write.

    A missing value is 0.0, not a rejection: an unpriced call is a real call
    that cost nothing recorded, which is different from a corrupt one.
    """
    if value is None:
        return 0.0
    try:
        cost = float(value)  # type: ignore[arg-type]  # guarded by the except below
    except (TypeError, ValueError):
        return None
    if not math.isfinite(cost) or cost < 0:
        return None
    return cost
