"""Every edition family renders a real brief to a real, non-blank PNG.

Drives the production path from a ``BriefingPayload`` through the family's
renderer and headless Chromium (``render_html_to_image``) — no browser fake.
The vendored templates index fixed item slots (``boardingpass`` read
``today[1]`` and ``today[2]``), and a page script that throws leaves an empty
``#root``: Chromium still screenshots it, as a 2px-high blank PNG, which the
email then ships. So the assertion is on the image itself.
"""

from __future__ import annotations

import struct
from typing import Any

import pytest

from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions import EXPLORER_RENDERER, FAMILY_EDITION, render_edition
from app.services.briefing.render import ImageRenderOptions, render_html_to_image

# A real daily brief is at least this tall; the blank render was 2px.
_MIN_HEIGHT_PX = 400
_MIN_PNG_BYTES = 20_000

_DAILY = {
    "kicker": "THE MORNING BRIEF",
    "date": "2026-10-14",
    "headline": "Two replies need you before your 11:00 with Sequoia.",
    "lede": "I drafted both and pulled last quarter's numbers into the deck.",
    "stats": [
        {"value": "4", "label": "done since yesterday"},
        {"value": "2", "label": "in progress"},
        {"value": "2", "label": "waiting on you"},
    ],
    "sections": [
        {
            "numeral": "I",
            "title": "NEEDS YOU",
            "items": [
                {"text": "Approve the reply to Priya about the term sheet", "kind": "you"},
                {"text": "Sync Stripe invoices to the finance sheet", "kind": "failed"},
            ],
        },
        {
            "numeral": "II",
            "title": "GAIA'S WORK",
            "items": [
                {"text": "Investor update draft for October", "kind": "lookback"},
                {"text": "Q4 hiring plan from your notes", "kind": "gaia"},
            ],
        },
    ],
    "mood": "packed",
    "caption": "Coffee first, Priya second.",
    "hue": 120,
}
_QUIET = {**_DAILY, "headline": "A quiet morning.", "stats": [], "sections": [], "mood": "idle"}

_FAMILIES = sorted({FAMILY_EDITION, *EXPLORER_RENDERER})


def _png_height(png: bytes) -> int:
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return int(struct.unpack(">I", png[20:24])[0])


def _render_html(family: str, payload: dict[str, Any]) -> str:
    render = EXPLORER_RENDERER.get(family, render_edition)
    data = BriefingPayload.model_validate(payload).model_dump()
    return render(data, edition_no=287, generated_local="6:02 AM", tz_label="")


@pytest.mark.integration
@pytest.mark.parametrize("payload", [_DAILY, _QUIET], ids=["daily", "quiet"])
@pytest.mark.parametrize("family", _FAMILIES)
async def test_family_renders_a_non_blank_png(family: str, payload: dict[str, Any]) -> None:
    png = await render_html_to_image(_render_html(family, payload), ImageRenderOptions())

    assert _png_height(png) >= _MIN_HEIGHT_PX * ImageRenderOptions().device_scale_factor
    assert len(png) >= _MIN_PNG_BYTES


@pytest.mark.integration
async def test_a_page_script_error_fails_the_render_instead_of_a_blank_png() -> None:
    html = '<!doctype html><html><body><div id="root"></div><script>throw new Error("slot missing")</script></body></html>'

    with pytest.raises(RuntimeError, match="slot missing"):
        await render_html_to_image(html, ImageRenderOptions())
