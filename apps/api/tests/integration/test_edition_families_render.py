"""Every edition family renders a real brief honestly, in a real browser.

Drives the production path from a BriefingPayload through the family's renderer and
headless Chromium, with no browser fake. Two shipped failure modes are pinned:

- Templates index fixed item slots; a throwing page script leaves an empty root that
  screenshots as a 2px-high blank PNG, so the image is asserted on.
- Templates printed demo-fixture text and zero-filled missing figures, so the rendered
  text is asserted on: the brief's headline is there, no fixture string, "0" or
  "null"/"undefined" is.
"""

from __future__ import annotations

import re
import struct
from typing import Any

from playwright.async_api import async_playwright
import pytest

from app.models.briefing_models import BriefingPayload
from app.services.briefing.edition_email import render_edition_png
from app.services.briefing.editions import EXPLORER_RENDERER, FAMILY_EDITION, render_edition
from app.services.briefing.render import ImageRenderOptions, render_html_to_image

# A real daily brief is at least this tall; the blank render was 2px.
_MIN_HEIGHT_PX = 400
_MIN_PNG_BYTES = 20_000

_HEADLINE = "Two replies need you before your 11:00 with Sequoia."

_DAILY = {
    "kicker": "THE MORNING BRIEF",
    "date": "2026-10-14",
    "headline": _HEADLINE,
    "lede": "I drafted both and pulled last quarter's numbers into the deck.",
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
    "calendar": [
        {"date": "2026-10-14", "start": "11:00", "title": "Sequoia partner meeting"},
        {"date": "2026-10-14", "start": "15:30", "title": "Design review with Dhruv"},
    ],
    "tallies": {"done_by_you": 1, "done_by_gaia": 3},
    "week": {
        "days": [{"you": 1, "gaia": 2}, {"you": 3, "gaia": 1}] + [{"you": 0, "gaia": 1}] * 5,
        "shipped": ["Closed the Acme renewal"],
        "handled": ["Filed every October receipt"],
        "ahead": [{"date": "2026-10-19", "start": "09:00", "title": "Board call"}],
    },
    "generated_at": "6:02 AM",
    "mood": "packed",
    "caption": "Coffee first, Priya second.",
    "hue": 120,
}
# The weekly family only ever renders the weekly recap, which carries its own
# week-level headline (build_weekly_digest_prompt asks for the week's shape).
_WEEKLY_HEADLINE = "A steady week: twelve things done, four of them by you."


def _as_rendered(family: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return the payload as the pipeline would hand it to the family."""
    if family == "weekly":
        return {**payload, "headline": _WEEKLY_HEADLINE, "mood": "weekly"}
    return payload


_QUIET = {
    **_DAILY,
    "headline": "A quiet morning.",
    "sections": [],
    "calendar": [],
    "tallies": None,
    "mood": "idle",
}

# Strings only the vendored templates' demo fixture contains.
_FIXTURE_STRINGS = (
    "Mehul",
    "217",
    "31.5",
    "340 newsletters",
    "A heavy Tuesday",
    "Redesigned the dashboard",
    "decisions made",
    "approval-flow",
    "CI green",
    "of 100",
    "hours saved",
    "02:14",
    "Sunday 18:00",
)
# One phrase from every item and event in _DAILY: a family that drops one
# (dayline/flightplan once hid every untimed item) fails.
_DAILY_PHRASES = (
    "reply to Priya",
    "Sync Stripe invoices",
    "Investor update draft",
    "Q4 hiring plan",
    "Sequoia partner meeting",
    "Design review with Dhruv",
)
_ZERO_FILLED = re.compile(r"(?<![\d:.,])0(?![\d:.,%h])|\bnull\b|\bundefined\b|\bNaN\b")

_FAMILIES = sorted({FAMILY_EDITION, *EXPLORER_RENDERER})


def _png_height(png: bytes) -> int:
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return int(struct.unpack(">I", png[20:24])[0])


def _render_html(family: str, payload: dict[str, Any]) -> str:
    render = EXPLORER_RENDERER.get(family, render_edition)
    data = BriefingPayload.model_validate(payload).model_dump()
    return render(data, edition_no=287, generated_local="", tz_label="")


async def _visible_text(html: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1180, "height": 800})
            await page.set_content(html, wait_until="networkidle")
            return str(await page.evaluate("() => document.body.innerText"))
        finally:
            await browser.close()


@pytest.mark.integration
@pytest.mark.parametrize("payload", [_DAILY, _QUIET], ids=["daily", "quiet"])
@pytest.mark.parametrize("family", _FAMILIES)
async def test_family_renders_a_non_blank_png(family: str, payload: dict[str, Any]) -> None:
    png = await render_html_to_image(
        _render_html(family, _as_rendered(family, payload)), ImageRenderOptions()
    )

    assert _png_height(png) >= _MIN_HEIGHT_PX * ImageRenderOptions().device_scale_factor
    assert len(png) >= _MIN_PNG_BYTES


@pytest.mark.integration
@pytest.mark.parametrize("payload", [_DAILY, _QUIET], ids=["daily", "quiet"])
@pytest.mark.parametrize("family", sorted(EXPLORER_RENDERER))
async def test_family_prints_the_brief_and_nothing_invented(
    family: str, payload: dict[str, Any]
) -> None:
    payload = _as_rendered(family, payload)
    text = await _visible_text(_render_html(family, payload))

    assert " ".join(payload["headline"].split()).lower() in " ".join(text.split()).lower()
    if family == "weekly":
        assert "11:00 with sequoia" not in text.lower(), "weekly printed the daily headline"
    for fixture in _FIXTURE_STRINGS:
        assert fixture not in text, f"{family} printed demo fixture text {fixture!r}"
    if payload is _DAILY:
        flat = " ".join(text.split()).lower()
        missing = [p for p in _DAILY_PHRASES if p.lower() not in flat]
        assert not missing, f"{family} dropped {missing}"
    found = _ZERO_FILLED.search(text)
    context = text[max(0, found.start() - 60) : found.end() + 20] if found else ""
    assert found is None, f"{family} printed a zero-filled or missing figure in {context!r}"


@pytest.mark.integration
async def test_a_page_script_error_fails_the_render_instead_of_a_blank_png() -> None:
    html = (
        '<!doctype html><html><body><div id="root"></div>'
        '<script>throw new Error("slot missing")</script></body></html>'
    )

    with pytest.raises(RuntimeError, match="slot missing"):
        await render_html_to_image(html, ImageRenderOptions())


def _png_width(png: bytes) -> int:
    return int(struct.unpack(">I", png[16:20])[0])


@pytest.mark.integration
@pytest.mark.parametrize(
    "family", ["postal", "receipt", "memo", "playbill", "librarycard", "boardingpass"]
)
async def test_the_chat_image_is_cropped_to_the_paper(family: str) -> None:
    payload = BriefingPayload.model_validate({**_DAILY, "template_family": family}).model_dump()

    full = await render_edition_png(payload, crop_to_paper=False)
    cropped = await render_edition_png(payload, crop_to_paper=True)

    assert _png_width(cropped) < _png_width(full)
    assert _png_height(cropped) <= _png_height(full)
    assert len(cropped) >= _MIN_PNG_BYTES


@pytest.mark.integration
async def test_a_full_bleed_family_keeps_its_width_when_cropped() -> None:
    payload = BriefingPayload.model_validate({**_DAILY, "template_family": "swiss"}).model_dump()

    cropped = await render_edition_png(payload, crop_to_paper=True)

    assert _png_width(cropped) == 1180 * ImageRenderOptions().device_scale_factor
