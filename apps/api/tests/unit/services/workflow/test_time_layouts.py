"""``time_layouts``: a recorded argument's layout, told apart by example."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.services.workflow.playbook.time_layouts import (
    ISO_DATE_LAYOUT,
    ISO_DATETIME_LAYOUT,
    KNOWN_TIME_LAYOUTS,
    detect_layout,
    render_iso,
)


@pytest.mark.unit
class TestDetectLayout:
    @pytest.mark.parametrize(
        ("value", "layout"),
        [
            ("2026-09-06 09:00:00", "%Y-%m-%d %H:%M:%S"),
            ("2026-09-06T09:00:00+00:00", "%Y-%m-%dT%H:%M:%S%z"),
            ("2026-09-06T09:00:00Z", "%Y-%m-%dT%H:%M:%SZ"),
            ("2026-09-06T09:00:00", "%Y-%m-%dT%H:%M:%S"),
            ("2026-09-06 09:00", "%Y-%m-%d %H:%M"),
            ("2026-09-06", "%Y-%m-%d"),
            ("06/09/2026", "%d/%m/%Y"),
        ],
    )
    def test_each_known_layout_is_told_apart(self, value: str, layout: str) -> None:
        assert detect_layout(value) == layout
        assert layout in KNOWN_TIME_LAYOUTS

    def test_the_most_specific_layout_wins(self) -> None:
        """A value with seconds must not be read as the minutes-only layout,
        which is what a table in the wrong order would do."""
        assert detect_layout("2026-09-06 09:00:00") != "%Y-%m-%d %H:%M"
        assert detect_layout("2026-09-06T09:00:00+00:00") != "%Y-%m-%dT%H:%M:%S"

    def test_surrounding_whitespace_is_not_part_of_the_layout(self) -> None:
        assert detect_layout("  2026-09-06  ") == "%Y-%m-%d"

    @pytest.mark.parametrize(
        "value", ["", "   ", "tomorrow at nine", 20260906, None, ["2026-09-06"]]
    )
    def test_anything_that_is_not_a_dated_string_has_no_layout(self, value: object) -> None:
        assert detect_layout(value) is None


@pytest.mark.unit
class TestDetectLayoutInProse:
    """Seen live (D4): the run titled a todo "Plan for September 5, 2026"; a
    bare-date hint had the model drop the words. The words are the layout."""

    @pytest.mark.parametrize(
        ("value", "layout"),
        [
            ("Plan for September 5, 2026", "Plan for %B %d, %Y"),
            ("Due 2026-09-06 09:00:00 sharp", "Due %Y-%m-%d %H:%M:%S sharp"),
            ("100% by 2026-09-06", "100%% by %Y-%m-%d"),
            ("6 September 2026", "%d %B %Y"),
        ],
    )
    def test_the_text_around_a_date_is_kept_as_literal_layout(
        self, value: str, layout: str
    ) -> None:
        assert detect_layout(value) == layout
        # The layout renders: the words come back around a date of that shape.
        rendered = datetime(2026, 9, 6, 9, 0, 0, tzinfo=UTC).strftime(layout)
        assert rendered.startswith(value.split("2026")[0].split("September")[0].split("6 ")[0])

    def test_prose_without_a_date_has_no_layout(self) -> None:
        assert detect_layout("Plan for tomorrow morning") is None


class TestRenderIso:
    MOMENT = datetime(2026, 3, 14, 9, 30, 7, 624690, tzinfo=timezone(timedelta(hours=1)))

    def test_a_date_is_the_date_alone(self) -> None:
        assert render_iso(self.MOMENT, date_only=True) == "2026-03-14"
        assert self.MOMENT.strftime(ISO_DATE_LAYOUT) == "2026-03-14"

    def test_a_datetime_is_to_the_second_with_its_offset(self) -> None:
        assert render_iso(self.MOMENT, date_only=False) == "2026-03-14T09:30:07+01:00"
        assert datetime(2026, 3, 14, 9, 30, 7, tzinfo=UTC).strftime(ISO_DATETIME_LAYOUT) == (
            "2026-03-14T09:30:07+0000"
        )
