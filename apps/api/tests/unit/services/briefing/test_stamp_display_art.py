from PIL import Image

from app.constants.briefing import STAMP_DISPLAY_MAX_BYTES, STAMP_DISPLAY_WIDTH_PX
from app.services.briefing.editions.stamps import (
    stamp_art,
    stamp_catalogue,
    stamp_display_art,
)


def test_every_stamp_has_a_display_variant_within_the_size_budget() -> None:
    oversized = {
        slug: path.stat().st_size
        for slug in stamp_catalogue()
        if (path := stamp_display_art(slug)).stat().st_size > STAMP_DISPLAY_MAX_BYTES
    }

    assert oversized == {}


def test_a_display_variant_keeps_the_stamps_shape_and_transparency() -> None:
    full = Image.open(stamp_art("tokyo"))
    display = Image.open(stamp_display_art("tokyo"))

    assert display.width == STAMP_DISPLAY_WIDTH_PX
    assert display.height == round(full.height * STAMP_DISPLAY_WIDTH_PX / full.width)
    assert display.mode == "RGBA"
