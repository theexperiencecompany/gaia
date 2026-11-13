"""The dev/holdout split every outbound-layer suite keeps.

Tune prompts, thresholds and models against dev. The holdout is read, never tuned on:
a number that was optimised against is no longer a measurement.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from .types import Case


class Split(StrEnum):
    """Which half of a suite a case belongs to."""

    DEV = "dev"
    HOLDOUT = "holdout"


def split_of(case: Case) -> Split:
    """Return the split a case declares in expected.split; a case with none is a data error."""
    return Split(case.expected["split"])


def in_split(cases: Iterable[Case], split: Split) -> list[Case]:
    """Return the cases of one split, in order."""
    return [case for case in cases if split_of(case) is split]
