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

import io
import re
import struct
from typing import Any

from PIL import Image, ImageChops
from playwright.async_api import async_playwright
import pytest

from app.models.briefing_models import BriefingPayload
from app.services.briefing.edition_email import render_edition_png
from app.services.briefing.editions import (
    EXPLORER_RENDERER,
    FAMILY_EDITION,
    edition_frame,
    render_edition,
)
from app.services.briefing.render import ImageRenderOptions, render_html_to_image

# A brief, even a quiet one on the 540px canvas, is at least this many CSS px
# tall; the blank render was 2px.
_MIN_HEIGHT_PX = 200
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
    "Aryan",
    "Randeriya",
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
# The invoice once billed "1 Wednesday" and priced every overnight row at "0.00".
_INVENTED_AMOUNT = re.compile(
    r"\b0\.00\b|\b1 (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b"
)
_ZERO_FILLED = re.compile(r"(?<![\d:.,])0(?![\d:.,%h])|\bnull\b|\bundefined\b|\bNaN\b")

_FAMILIES = sorted({FAMILY_EDITION, *EXPLORER_RENDERER})


def _png_height(png: bytes) -> int:
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return int(struct.unpack(">I", png[20:24])[0])


def _render_html(family: str, payload: dict[str, Any]) -> str:
    render = EXPLORER_RENDERER.get(family, render_edition)
    data = BriefingPayload.model_validate(payload)
    return render(data, edition_no=287, generated_local="", tz_label="")


async def _visible_text(html: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 540, "height": 800})
            await page.set_content(html, wait_until="networkidle")
            return str(await page.evaluate("() => document.body.innerText"))
        finally:
            await browser.close()


@pytest.mark.integration
@pytest.mark.parametrize("payload", [_DAILY, _QUIET], ids=["daily", "quiet"])
@pytest.mark.parametrize("family", _FAMILIES)
async def test_family_renders_a_non_blank_png(family: str, payload: dict[str, Any]) -> None:
    frame = edition_frame(family)
    png = await render_html_to_image(
        _render_html(family, _as_rendered(family, payload)),
        ImageRenderOptions(width=frame.width, device_scale_factor=frame.device_scale_factor),
    )

    assert _png_height(png) >= _MIN_HEIGHT_PX * frame.device_scale_factor
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
    invented = _INVENTED_AMOUNT.search(text)
    assert invented is None, f"{family} printed an invented amount {invented.group()!r}"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("payload", "awaiting"),
    [
        (_DAILY, "Awaiting you 2 items"),
        (
            {
                **_DAILY,
                "sections": [
                    {
                        "numeral": "I",
                        "title": "NEEDS YOU",
                        "items": [
                            {"text": "Approve the Acme MSA renewal", "kind": "you", "count": 3},
                            {"text": "Reply to Daniel", "kind": "you"},
                        ],
                    }
                ],
            },
            "Awaiting you 4 items",
        ),
        (_QUIET, "Awaiting you Nothing"),
    ],
    ids=["two-asks", "grouped-asks", "quiet"],
)
async def test_the_invoice_bills_what_awaits_the_user(
    payload: dict[str, Any], awaiting: str
) -> None:
    text = " ".join((await _visible_text(_render_html("invoice", payload))).split())

    assert awaiting in text, f"the amount box does not read {awaiting!r}: {text}"
    assert "Amount" not in text


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


_SPARSE = {**_DAILY, "sections": [_DAILY["sections"][0]], "calendar": [], "tallies": None}
_BUSY = {
    **_DAILY,
    "sections": [
        {
            **_DAILY["sections"][0],
            "items": [
                *_DAILY["sections"][0]["items"],
                {"text": "Decide on the podcast invite from Design Tools FM", "kind": "you"},
            ],
        },
        {
            **_DAILY["sections"][1],
            "items": [
                *_DAILY["sections"][1]["items"],
                {"text": "Archived the newsletters from the weekend", "kind": "lookback"},
                {"text": "Rescheduled the dentist after a calendar clash", "kind": "lookback"},
            ],
        },
    ],
    "calendar": [
        {"date": "2026-10-14", "start": "09:30", "title": "Standup with the platform team"},
        *_DAILY["calendar"],
        {"date": "2026-10-14", "start": "17:00", "title": "Hiring sync for the design lead"},
    ],
}
_DENSITIES = {"busy": _BUSY, "normal": _DAILY, "sparse": _SPARSE}
# The design-px band each side's visible margin must fall in: nothing touches the
# edge, and no more than the target of background is kept around a paper.
_MARGIN_MIN_PX = 4
_MARGIN_TARGET_PX = 24
# Above a background's gradient drift, below the faintest visible shadow.
_INK_THRESHOLD = 24


def _side_margins(png: bytes, scale: int) -> dict[str, float]:
    """Design px from each image edge to the first pixel unlike that edge's own."""
    image = Image.open(io.BytesIO(png)).convert("RGB")
    width, height = image.size

    def run(lines: range, columns: bool) -> int:
        def line(i: int) -> Image.Image:
            return image.crop((i, 0, i + 1, height) if columns else (0, i, width, i + 1))

        edge = line(lines[0])
        for count, i in enumerate(lines):
            differs = ImageChops.difference(line(i), edge).point(
                lambda v: 255 if v > _INK_THRESHOLD else 0
            )
            if differs.getbbox() is not None:
                return count
        return len(lines)

    return {
        "left": run(range(width), True) / scale,
        "right": run(range(width - 1, -1, -1), True) / scale,
        "top": run(range(height), False) / scale,
        "bottom": run(range(height - 1, -1, -1), False) / scale,
    }


_ON_A_DESK = sorted(f for f in EXPLORER_RENDERER if edition_frame(f).trim_margin_px is not None)
_FULL_BLEED = sorted(set(EXPLORER_RENDERER) - set(_ON_A_DESK))


def _shipped(family: str, payload: dict[str, Any]) -> BriefingPayload:
    return BriefingPayload.model_validate(
        {
            **_as_rendered(family, payload),
            "template_family": family,
            "stamp_city": "tokyo" if family == "postal" else None,
        }
    )


@pytest.mark.integration
@pytest.mark.parametrize("density", sorted(_DENSITIES))
@pytest.mark.parametrize("family", _ON_A_DESK)
async def test_a_paper_on_a_desk_is_cropped_tight_with_an_even_margin(
    family: str, density: str
) -> None:
    frame = edition_frame(family)

    png = await render_edition_png(_shipped(family, _DENSITIES[density]))

    margins = _side_margins(png, frame.device_scale_factor)
    touching = {side: m for side, m in margins.items() if m < _MARGIN_MIN_PX}
    loose = {side: m for side, m in margins.items() if m > _MARGIN_TARGET_PX}
    assert not touching, f"{family} paper touches the image edge: {touching}"
    assert not loose, f"{family} keeps more than {_MARGIN_TARGET_PX}px of desk: {loose}"


@pytest.mark.integration
@pytest.mark.parametrize("density", sorted(_DENSITIES))
@pytest.mark.parametrize("family", _FULL_BLEED)
async def test_a_full_bleed_family_ships_its_whole_page_and_nothing_more(
    family: str, density: str
) -> None:
    frame = edition_frame(family)
    payload = _shipped(family, _DENSITIES[density])

    png = await render_edition_png(payload)
    page = await render_html_to_image(
        _render_html(family, payload.model_dump()),
        ImageRenderOptions(width=frame.width, device_scale_factor=frame.device_scale_factor),
    )

    assert _png_width(png) == frame.width * frame.device_scale_factor
    # The page may run one CSS px past the article where its height is fractional.
    assert 0 <= _png_height(page) - _png_height(png) <= frame.device_scale_factor


# Item rows measured with transforms off: a half-degree tilt grows each row's box
# into its neighbour's without moving text, and never changes layout.
_ROWS = """() => {
  for (const el of document.querySelectorAll("*")) el.style.transform = "none";
  const canvas = document.querySelector("#root > article").getBoundingClientRect();
  const rows = [...document.querySelectorAll('[data-role="body"]')].map((el) => {
    const r = el.getBoundingClientRect();
    return { text: el.innerText.trim().slice(0, 40), left: r.left, top: r.top, right: r.right, bottom: r.bottom };
  }).filter((r) => r.right > r.left && r.bottom > r.top);
  return { canvas: { left: canvas.left, right: canvas.right }, rows };
}"""


@pytest.mark.integration
@pytest.mark.parametrize("family", sorted(EXPLORER_RENDERER))
async def test_no_item_row_overprints_another_or_leaves_the_canvas(family: str) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 540, "height": 800})
            await page.set_content(_render_html(family, _as_rendered(family, _BUSY)))
            measured = await page.evaluate(_ROWS)
        finally:
            await browser.close()

    rows, canvas = measured["rows"], measured["canvas"]
    assert rows, f"{family} marks no item rows"
    outside = [
        r["text"] for r in rows if r["left"] < canvas["left"] or r["right"] > canvas["right"]
    ]
    overprinted = [
        (a["text"], b["text"])
        for i, a in enumerate(rows)
        for b in rows[i + 1 :]
        if a["left"] < b["right"] - 1
        and b["left"] < a["right"] - 1
        and a["top"] < b["bottom"] - 1
        and b["top"] < a["bottom"] - 1
    ]
    assert outside == [], f"{family} rows leave the canvas: {outside}"
    assert overprinted == [], f"{family} rows overprint: {overprinted}"


@pytest.mark.integration
@pytest.mark.parametrize("family", ["boardingpass", "invoice", "memo", "postal"])
async def test_the_edition_is_addressed_to_the_user_by_name(family: str) -> None:
    payload = {**_DAILY, "recipient_name": "Maya Okafor"}

    text = await _visible_text(_render_html(family, payload))

    assert "Maya" in text


# A brief with nothing on the calendar and nothing waiting on the reader: the
# empty buckets once rendered as fake rows ("EOD  Nothing on the calendar today",
# "REVIEW  Nothing pending your review").
_ONLY_OVERNIGHT = {
    **_DAILY,
    "sections": [
        {
            "numeral": "I",
            "title": "GAIA'S WORK",
            "items": [{"text": "Investor update draft for October", "kind": "lookback"}],
        }
    ],
    "calendar": [],
}
_PLACEHOLDER_ROW = re.compile(
    r"\bEOD\b|\breview\b|nothing on the calendar|nothing pending|nothing to report",
    re.IGNORECASE,
)


@pytest.mark.integration
@pytest.mark.parametrize("payload", [_QUIET, _ONLY_OVERNIGHT], ids=["quiet", "only-overnight"])
@pytest.mark.parametrize("family", sorted(set(EXPLORER_RENDERER) - {"weekly"}))
async def test_an_empty_bucket_renders_no_placeholder_row(
    family: str, payload: dict[str, Any]
) -> None:
    text = " ".join((await _visible_text(_render_html(family, payload))).split())

    found = _PLACEHOLDER_ROW.search(text)
    context = text[max(0, found.start() - 60) : found.end() + 40] if found else ""
    assert found is None, f"{family} printed a placeholder row in {context!r}"


# Section headings each family prints only above a non-empty bucket (explorer/README.md,
# "Empty sections"). A quiet brief has every bucket empty, so none may survive.
_EMPTY_BUCKET_HEADINGS = {
    "almanac": (
        "Matters for your judgement",
        "What matters to-day",
        "Work performed in the night",
        "Calculations for the day",
    ),
    "band": ("need your call", "on today", "done while you slept"),
    "boardingpass": (
        "Awaiting your confirmation",
        "Itinerary · today",
        "Services completed in transit",
    ),
    "broadsheet": ("Needs your call", "What matters today", "While you slept", "day's figures"),
    "dayline": ("while you slept", "needs your call"),
    "exhibition": ("Programme for the day", "Awaiting your decision", "while you slept"),
    "flightplan": ("needs your call", "Elevation · the day", "while you slept"),
    "gradient": ("Needs your call", "Handled overnight"),
    "instrument": ("needs your call", "Operating window", "Overnight log", "readout"),
    "invoice": ("Approval required", "Today, billable", "Paid in advance"),
    "librarycard": ("Awaiting your signature", "Checked out", "Returned overnight"),
    "memo": ("What matters today", "While you slept", "Needs your call", "By the numbers"),
    "menu": ("awaiting the table", "prepared overnight"),
    "metromap": ("Decision line", "Day line", "night line"),
    "playfair": ("The day ahead", "While you slept", "For your decision"),
    "postal": ("Waiting on your reply", "Your day", "Done while you slept"),
    "receipt": ("Overnight", "Awaiting payment", "Items:"),
    "swiss": ("What matters today", "While you slept", "Needs your call"),
}


@pytest.mark.integration
@pytest.mark.parametrize(("family", "headings"), sorted(_EMPTY_BUCKET_HEADINGS.items()))
async def test_an_empty_bucket_leaves_no_section_heading(
    family: str, headings: tuple[str, ...]
) -> None:
    text = " ".join((await _visible_text(_render_html(family, _QUIET))).split()).lower()

    left = [h for h in headings if h.lower() in text]
    assert not left, f"{family} printed {left} above an empty bucket"


# The heading each family files GAIA's still-running work under, apart from what it
# finished. Air Mail once printed in-progress work under "Done while you slept".
_RUNNING_HEADINGS = {
    "almanac": "Work still in progress",
    "band": "still in progress",
    "boardingpass": "Services still in progress",
    "broadsheet": "Still in progress",
    "dayline": "Still in progress",
    "exhibition": "Still in progress",
    "flightplan": "still in progress",
    "gradient": "Still in progress",
    "instrument": "still running",
    "invoice": "Still in progress",
    "librarycard": "Still in progress with GAIA",
    "memo": "Still in progress",
    "menu": "still in preparation",
    "metromap": "night line · still running",
    "playfair": "Still in progress",
    "postal": "Still in progress",
    "receipt": "Still in progress",
    "swiss": "Still in progress",
}


@pytest.mark.integration
@pytest.mark.parametrize(("family", "heading"), sorted(_RUNNING_HEADINGS.items()))
async def test_running_work_is_filed_apart_from_finished_work(family: str, heading: str) -> None:
    daily = " ".join((await _visible_text(_render_html(family, _DAILY))).split()).lower()
    done_only = " ".join((await _visible_text(_render_html(family, _ONLY_OVERNIGHT))).split())

    assert heading.lower() in daily, f"{family} filed running work under no running heading"
    assert heading.lower() not in done_only.lower(), f"{family} labelled finished work running"
