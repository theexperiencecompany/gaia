"""Linear priority survives the Float the API actually sends.

Linear's published schema types ``Issue.priority`` as ``Float!``, so a
priority can arrive as ``2.0`` rather than ``2``. The strict-typing migration
read it with ``int_bag``, whose ``isinstance(value, int)`` check rejects a
float and falls back to 0 — turning every issue into "none".

The existing Linear tool tests all patch ``format_issue_summary`` out, so the
mapping itself never ran under test and the regression was invisible to them.
"""

import pytest

from app.utils.linear_utils import format_issue_summary, priority_to_str


@pytest.mark.parametrize(
    ("wire_value", "expected"),
    [
        (1.0, "urgent"),
        (2.0, "high"),
        (3.0, "medium"),
        (4.0, "low"),
        (0.0, "none"),
    ],
)
def test_float_priority_maps_to_its_label(wire_value: float, expected: str) -> None:
    """A Float! off the wire resolves to the same label its int would."""
    assert priority_to_str(wire_value) == expected


@pytest.mark.parametrize(
    ("wire_value", "expected"),
    [(1, "urgent"), (2, "high"), (3, "medium"), (4, "low"), (0, "none")],
)
def test_int_priority_still_maps_to_its_label(wire_value: int, expected: str) -> None:
    """The int form some queries send keeps working."""
    assert priority_to_str(wire_value) == expected


def test_unknown_priority_falls_back_to_none() -> None:
    """A value outside the 0-4 scale is reported as no priority, not raised."""
    assert priority_to_str(99.0) == "none"


def test_summary_reports_a_float_priority_not_none() -> None:
    """The whole read path, not just the mapping, tolerates the Float."""
    summary = format_issue_summary({"id": "i", "identifier": "ENG-1", "priority": 2.0})

    assert summary["priority"] == "high"


def test_summary_reports_none_when_priority_is_absent() -> None:
    """An issue with no priority is still 'none' rather than a KeyError."""
    summary = format_issue_summary({"id": "i", "identifier": "ENG-1"})

    assert summary["priority"] == "none"
