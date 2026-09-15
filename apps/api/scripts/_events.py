"""Parsing rules shared by the scripts that rebuild history from llm_call events.

Small, but shared deliberately: both backfills turn log lines into dollar
figures, and a guard that exists in only one of them is a guard that will be
missing from the other the next time someone copies a parser.
"""

from __future__ import annotations

import math


def finite_cost(value: object) -> float | None:
    """Return value as a cost we can add up: a real, non-negative number, else None.

    json.loads accepts NaN and Infinity, which would silently poison every
    total; those and negative/unparseable values return None so the caller
    can drop the line. A missing value returns 0.0 (a real call that cost
    nothing recorded), not a rejection.
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
