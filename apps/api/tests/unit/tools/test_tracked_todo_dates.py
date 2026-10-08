"""A tracked todo's dates must carry a timezone offset: a naive one is read as UTC."""

import pytest

from app.agents.tools.tracked_todo_fields import build_clearable_datetime_update


@pytest.mark.regression
@pytest.mark.parametrize("value", ["2026-09-30", "2026-09-30T17:00:00"])
def test_a_date_without_an_offset_is_refused(value: str) -> None:
    """A naive wall time would be saved as UTC, off by the user's offset."""
    fields: dict[str, object] = {}
    error = build_clearable_datetime_update(value, "due_date", fields)
    assert error == f"Error: due_date '{value}' must include a timezone offset."
    assert fields == {}
