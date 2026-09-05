"""Unit tests for the edition renderers' shared plumbing.

``font_face`` and ``format_date`` are pure and touch only the vendored font
files on disk, so every assertion here pins the exact string the renderers
embed — no mocking, no fixtures.
"""

import base64
from pathlib import Path

import pytest

from app.services.briefing.editions._shared import (
    CANVAS_PX,
    FONTS_DIR,
    font_face,
    format_date,
)

_REGULAR = "PPEditorialNew-Regular.woff2"
_ULTRALIGHT = "PPEditorialNew-Ultralight.woff2"


@pytest.mark.unit
class TestCanvas:
    def test_canvas_width_is_the_1180px_raster_viewport(self) -> None:
        assert CANVAS_PX == 1180

    def test_fonts_dir_points_at_the_vendored_woff2_files(self) -> None:
        assert Path(__file__).parents[5] / "app/services/briefing/editions/fonts" == FONTS_DIR
        assert (FONTS_DIR / _REGULAR).is_file()
        assert (FONTS_DIR / _ULTRALIGHT).is_file()


@pytest.mark.unit
class TestFontFace:
    def test_rule_embeds_the_real_file_bytes_as_a_data_uri(self) -> None:
        encoded = base64.b64encode((FONTS_DIR / _REGULAR).read_bytes()).decode("ascii")

        assert font_face("PP Editorial New", _REGULAR, 400) == (
            "@font-face{font-family:'PP Editorial New';font-style:normal;"
            "font-weight:400;font-display:block;"
            f"src:url(data:font/woff2;base64,{encoded}) format('woff2');}}"
        )

    def test_weight_and_family_are_taken_from_the_arguments(self) -> None:
        rule = font_face("Other Face", _ULTRALIGHT, 200)

        assert rule.startswith(
            "@font-face{font-family:'Other Face';font-style:normal;"
            "font-weight:200;font-display:block;src:url(data:font/woff2;base64,"
        )
        assert rule.endswith(") format('woff2');}")

    def test_two_different_files_produce_different_payloads(self) -> None:
        regular = font_face("PP Editorial New", _REGULAR, 400)
        ultralight = font_face("PP Editorial New", _ULTRALIGHT, 400)

        assert regular != ultralight

    def test_missing_font_file_raises_rather_than_embedding_nothing(self) -> None:
        with pytest.raises(FileNotFoundError):
            font_face("PP Editorial New", "does-not-exist.woff2", 400)


@pytest.mark.unit
class TestFormatDate:
    @pytest.mark.parametrize(
        ("iso", "expected"),
        [
            ("2026-07-05", "July 5, 2026"),
            ("2026-01-01", "January 1, 2026"),
            ("2026-12-31", "December 31, 2026"),
            ("2024-02-29", "February 29, 2024"),
            ("1999-09-09", "September 9, 1999"),
        ],
    )
    def test_iso_date_renders_as_month_day_year(self, iso: str, expected: str) -> None:
        assert format_date(iso) == expected

    def test_day_is_not_zero_padded(self) -> None:
        assert format_date("2026-03-07") == "March 7, 2026"

    def test_unparseable_value_is_returned_verbatim(self) -> None:
        assert format_date("not a date") == "not a date"

    def test_empty_value_stays_empty(self) -> None:
        assert format_date("") == ""

    def test_unparseable_value_is_html_escaped(self) -> None:
        assert format_date('<img src=x onerror="a">') == "&lt;img src=x onerror=&quot;a&quot;&gt;"

    def test_out_of_range_calendar_date_is_escaped_not_raised(self) -> None:
        assert format_date("2026-02-30") == "2026-02-30"
