"""time_layouts: a recorded argument's layout, told apart by example."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.services.workflow.playbook.placeholders import PLACEHOLDER_TOKEN
from app.services.workflow.playbook.time_layouts import (
    ISO_DATE_LAYOUT,
    ISO_DATETIME_LAYOUT,
    KNOWN_TIME_LAYOUTS,
    detect_layout,
    render_iso,
    renders_inside,
    time_slot_layout,
)


@pytest.mark.unit
class TestDetectLayout:
    @pytest.mark.parametrize(
        ("value", "layout"),
        [
            ("2026-09-06 09:00:00", "%Y-%m-%d %H:%M:%S"),
            ("2026-09-06T09:00:00+00:00", "%Y-%m-%dT%H:%M:%S%:z"),
            ("2026-09-06T09:00:00+0000", "%Y-%m-%dT%H:%M:%S%z"),
            ("2026-09-06T09:00:00Z", "%Y-%m-%dT%H:%M:%SZ"),
            ("2026-09-06T09:00:00", "%Y-%m-%dT%H:%M:%S"),
            ("2026-09-06 09:00", "%Y-%m-%d %H:%M"),
            ("2026-09-06", "%Y-%m-%d"),
            ("06/09/2026", "%d/%m/%Y"),
        ],
    )
    def test_each_known_layout_is_told_apart(self, value: str, layout: str) -> None:
        assert detect_layout(value) == layout
        assert layout.replace("%:z", "%z") in KNOWN_TIME_LAYOUTS

    @pytest.mark.parametrize(
        "value",
        ["2026-09-06T09:00:00+00:00", "2026-09-06T09:00:00+0530", "2026-09-06 09:00:00-07:00"],
    )
    def test_an_offset_renders_back_as_it_was_written(self, value: str) -> None:
        """Offsets read alike with or without a colon, but are written differently; a replay sends what the run sent."""
        layout = detect_layout(value)
        assert layout is not None
        moment = datetime.strptime(value, layout.replace("%:z", "%z"))
        assert moment.strftime(layout) == value

    def test_the_most_specific_layout_wins(self) -> None:
        """A value with seconds must not be read as the minutes-only layout, which is what a table in the wrong order would do."""
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
    """Seen live (D4): the run titled a todo "Plan for September 5, 2026"; a bare-date hint had the model drop the words."""

    @pytest.mark.parametrize(
        ("value", "layout"),
        [
            ("Plan for September 5, 2026", "Plan for %B %d, %Y"),
            ("Due 2026-09-06 09:00:00 sharp", "Due %Y-%m-%d %H:%M:%S sharp"),
            ("100% by 2026-09-06", "100%% by %Y-%m-%d"),
            ("2026-09-06 at 100%", "%Y-%m-%d at 100%%"),
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
        # The layout a bare placeholder renders as, so a recorded value in it needs no slot.
        assert self.MOMENT.strftime(ISO_DATETIME_LAYOUT) == render_iso(self.MOMENT, date_only=False)


@pytest.mark.unit
class TestRendersInside:
    """A time placeholder inside text renders as ISO 8601 there."""

    @pytest.mark.parametrize(
        ("placeholder", "example", "renders"),
        [
            ("$today", "Run at 2026-01-01 for someone", True),
            ("$now", "Sent 2026-01-01T09:00:00+00:00 by Dana", True),
            ("$today", "Plan for September 5, 2026", False),
            ("$today", "Due 2026-01-01 09:00:00", False),
            ("$today", "a title with no date", True),
        ],
    )
    def test_it_holds_only_where_the_recorded_date_was_iso(
        self, placeholder: str, example: str, renders: bool
    ) -> None:
        match = PLACEHOLDER_TOKEN.fullmatch(placeholder)
        assert match is not None
        assert renders_inside(match, example) is renders


@pytest.mark.unit
class TestTimeSlotLayout:
    """When a whole time placeholder must carry a layout to render as the recorded value."""

    @pytest.mark.parametrize(
        ("placeholder", "example", "layout"),
        [
            ("$now", "2026-09-06T09:00:00+00:00", None),
            ("$today", "2026-09-06", None),
            ("$now", "2026-09-06T09:00:00+0000", "%Y-%m-%dT%H:%M:%S%z"),
            ("$today", "2026-09-06 09:00:00", "%Y-%m-%d %H:%M:%S"),
            ("$today + 1d 09:00", "2026-09-06", "%Y-%m-%d"),
            ("$now", "soon", None),
        ],
    )
    def test_a_slot_is_needed_only_where_iso_would_not_match(
        self, placeholder: str, example: str, layout: str | None
    ) -> None:
        match = PLACEHOLDER_TOKEN.fullmatch(placeholder)
        assert match is not None
        assert time_slot_layout(match, example) == layout
