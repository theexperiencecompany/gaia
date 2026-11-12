"""The web page lists what an edition cut off, so both sides must cut at the same row."""

from pathlib import Path
import re

from app.constants.briefing import EDITION_ROWS_SHOWN

_WEB_CONSTANTS = (
    Path(__file__).parents[6] / "web" / "src" / "features" / "briefing" / "constants.ts"
)


def test_the_web_page_lists_from_the_row_the_edition_stops_at() -> None:
    declared = re.search(r"EDITION_ROWS_SHOWN = (\d+);", _WEB_CONSTANTS.read_text())

    assert declared is not None
    assert int(declared.group(1)) == EDITION_ROWS_SHOWN
