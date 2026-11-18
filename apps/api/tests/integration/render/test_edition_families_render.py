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

from PIL import Image, ImageStat
from playwright.async_api import ViewportSize
import pytest

from app.constants.briefing import ArtFamily, BriefAction, BriefOutcome, EditionFamily
from app.models.brief_payload_models import BriefingPayload
from app.services.briefing.edition_email import render_edition_png
from app.services.briefing.editions import EXPLORER_RENDERER, edition_frame, explorer_render
from app.services.briefing.editions.artworks import artwork_catalogue
from app.services.render.chromium import chromium_page
from app.services.render.image import ImageRenderOptions, render_html_to_image
from tests.factories import make_brief_item

pytestmark = pytest.mark.asyncio(loop_scope="package")

# The page a template's own markup is read from, outside the delivery render.
_PAGE: ViewportSize = {"width": 540, "height": 800}
# A brief, even a quiet one on the 540px canvas, is at least this many CSS px
# tall; the blank render was 2px.
_MIN_HEIGHT_PX = 200
_MIN_PNG_BYTES = 20_000

_HEADLINE = "Two replies need you before your 11:00 with Sequoia."

_DAILY: dict[str, Any] = {
    "kicker": "THE MORNING BRIEF",
    "template_family": "swiss",
    "date": "2026-10-14",
    "headline": _HEADLINE,
    "lede": "I drafted both and pulled last quarter's numbers into the deck.",
    "sections": [
        {
            "numeral": "I",
            "title": "NEEDS YOU",
            "items": [
                make_brief_item("Priya's term sheet reply", "you", action=BriefAction.APPROVE),
                make_brief_item("Stripe invoice sync", "failed"),
            ],
        },
        {
            "numeral": "II",
            "title": "GAIA'S WORK",
            "items": [
                make_brief_item(
                    "October investor update", "lookback", outcome=BriefOutcome.DRAFTED
                ),
                make_brief_item("Q4 hiring plan", "gaia"),
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
        "ahead": [{"date": "2026-10-19", "start": "09:00", "title": "Board call"}],
    },
    "generated_at": "6:02 AM",
    "mood": "packed",
    "caption": "Coffee first, Priya second.",
    "hue": 120,
}


#: The stored brief's link every render is given: the Invoice, Receipt and Boarding Pass encode it.
_LINK = "https://heygaia.link/aB3dE5gH7jK"


def _composed(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the payload with each section composed as its own items block, in order."""
    blocks = [{"kind": "items", "section": n} for n in range(len(payload["sections"]))]
    return {**payload, "blocks": blocks}


_DAILY = _composed(_DAILY)
# The weekly family only ever renders the weekly recap, which carries its own
# week-level headline (build_weekly_voice_prompt asks for the week's shape).
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
    "blocks": [],
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
# (flightplan once hid every untimed item) fails. The weekly lists the week ahead.
_ITEM_PHRASES = (
    "term sheet reply",
    "Stripe invoice sync",
    "October investor update",
    "Q4 hiring plan",
)
_DAILY_PHRASES = (*_ITEM_PHRASES, "Sequoia partner meeting", "Design review with Dhruv")
_WEEKLY_PHRASES = (*_ITEM_PHRASES, "Board call")
# The invoice once billed "1 Wednesday", the receipt totalled "1 WEDNESDAY" and the
# invoice priced every overnight row at "0.00".
_INVENTED_AMOUNT = re.compile(
    r"\b0\.00\b|\b1 (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
    re.IGNORECASE,
)
_ZERO_FILLED = re.compile(r"(?<![\d:.,])0(?![\d:.,%h])|\bnull\b|\bundefined\b|\bNaN\b")

_FAMILIES = sorted(EXPLORER_RENDERER)


def _png_height(png: bytes) -> int:
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return int(struct.unpack(">I", png[20:24])[0])


# The painting publish_brief draws for a framed family.
_ARTWORK = "wheat-field-cypresses"


def _artwork(family: str) -> str | None:
    return _ARTWORK if family in ArtFamily else None


def _stamp(family: str) -> str | None:
    """Return the city publish_brief draws for an air-mail edition."""
    return "tokyo" if family == EditionFamily.POSTAL else None


def _render_html(family: EditionFamily, payload: dict[str, Any]) -> str:
    data = BriefingPayload.model_validate(
        {
            "artwork_id": _artwork(family),
            "stamp_city": _stamp(family),
            **payload,
            "template_family": family,
        }
    )
    return EXPLORER_RENDERER[family](data, link=_LINK, edition_no=287)


async def _visible_text(html: str) -> str:
    async with chromium_page(_PAGE) as rendering:
        await rendering.page.set_content(html, wait_until="networkidle")
        return str(await rendering.page.evaluate("() => document.body.innerText"))


@pytest.mark.integration
@pytest.mark.parametrize("payload", [_DAILY, _QUIET], ids=["daily", "quiet"])
@pytest.mark.parametrize("family", _FAMILIES)
async def test_family_renders_a_non_blank_png(
    family: EditionFamily, payload: dict[str, Any]
) -> None:
    frame = edition_frame(family)
    rendered = await render_html_to_image(
        _render_html(family, _as_rendered(family, payload)),
        ImageRenderOptions(width=frame.width, device_scale_factor=frame.device_scale_factor),
    )
    png = rendered.image

    assert _png_height(png) >= _MIN_HEIGHT_PX * frame.device_scale_factor
    assert len(png) >= _MIN_PNG_BYTES


@pytest.mark.integration
@pytest.mark.parametrize("payload", [_DAILY, _QUIET], ids=["daily", "quiet"])
@pytest.mark.parametrize("family", sorted(EXPLORER_RENDERER))
async def test_family_prints_the_brief_and_nothing_invented(
    family: EditionFamily, payload: dict[str, Any]
) -> None:
    payload = _as_rendered(family, payload)
    text = await _visible_text(_render_html(family, payload))

    assert " ".join(payload["headline"].split()).lower() in " ".join(text.split()).lower()
    if family == "weekly":
        assert "11:00 with sequoia" not in text.lower(), "weekly printed the daily headline"
    for fixture in _FIXTURE_STRINGS:
        assert fixture.lower() not in text.lower(), f"{family} printed fixture text {fixture!r}"
    if payload is _DAILY:
        flat = " ".join(text.split()).lower()
        phrases = _WEEKLY_PHRASES if family == "weekly" else _DAILY_PHRASES
        missing = [p for p in phrases if p.lower() not in flat]
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
                "blocks": [{"kind": "items", "section": 0}],
                "sections": [
                    {
                        "numeral": "I",
                        "title": "NEEDS YOU",
                        "items": [
                            make_brief_item("Acme MSA renewal", "you", count=3),
                            make_brief_item("Daniel", "you", action=BriefAction.REPLY),
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
    text = " ".join((await _visible_text(_render_html(EditionFamily.INVOICE, payload))).split())

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


_SPARSE = {
    **_DAILY,
    "sections": [_DAILY["sections"][0]],
    "blocks": [{"kind": "items", "section": 0}],
    "calendar": [],
    "tallies": None,
}
_BUSY = {
    **_DAILY,
    "sections": [
        {
            **_DAILY["sections"][0],
            "items": [
                *_DAILY["sections"][0]["items"],
                make_brief_item("Design Tools FM podcast invite", "you", action=BriefAction.REPLY),
            ],
        },
        {
            **_DAILY["sections"][1],
            "items": [
                *_DAILY["sections"][1]["items"],
                make_brief_item("Weekend newsletters archived", "lookback"),
                make_brief_item("Dentist", "lookback", outcome=BriefOutcome.BOOKED),
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
# The design px a desk family keeps around its paper: the opaque paper never comes
# nearer the edge than the minimum, and no more than the target of clear background
# is kept past the outermost shadow.
_MARGIN_MIN_PX = 4
_MARGIN_TARGET_PX = 24
_OPAQUE = 255


def _highest(band: Image.Image) -> float:
    """Return a single-band image's highest value."""
    return ImageStat.Stat(band).extrema[0][1]


def _clear_margins(png: bytes, scale: int, coverage_floor: int) -> dict[str, float]:
    """Design px from each image edge to the first pixel whose alpha passes coverage_floor."""
    alpha = Image.open(io.BytesIO(png)).convert("RGBA").getchannel("A")
    mask = alpha.point(lambda value: 255 if value > coverage_floor else 0)
    box = mask.getbbox()
    assert box is not None, "the edition rendered nothing"
    left, top, right, bottom = box
    return {
        "left": left / scale,
        "right": (alpha.width - right) / scale,
        "top": top / scale,
        "bottom": (alpha.height - bottom) / scale,
    }


_ON_A_DESK = sorted(f for f in EXPLORER_RENDERER if edition_frame(f).trim_margin_px is not None)
_FULL_BLEED = sorted(set(EXPLORER_RENDERER) - set(_ON_A_DESK))


def _shipped(family: str, payload: dict[str, Any]) -> BriefingPayload:
    return BriefingPayload.model_validate(
        {
            **_as_rendered(family, payload),
            "template_family": family,
            "stamp_city": "tokyo" if family == "postal" else None,
            "artwork_id": _artwork(family),
        }
    )


@pytest.mark.integration
@pytest.mark.parametrize("density", sorted(_DENSITIES))
@pytest.mark.parametrize("family", _ON_A_DESK)
async def test_a_paper_on_a_desk_is_cropped_tight_with_an_even_margin(
    family: EditionFamily, density: str
) -> None:
    frame = edition_frame(family)

    png = (await render_edition_png(_shipped(family, _DENSITIES[density]), _LINK)).image

    paper = _clear_margins(png, frame.device_scale_factor, _OPAQUE - 1)
    shadow = _clear_margins(png, frame.device_scale_factor, 0)
    touching = {side: m for side, m in paper.items() if m < _MARGIN_MIN_PX}
    loose = {side: m for side, m in shadow.items() if m > _MARGIN_TARGET_PX}
    assert not touching, f"{family} paper touches the image edge: {touching}"
    assert not loose, f"{family} keeps more than {_MARGIN_TARGET_PX}px past its shadow: {loose}"


@pytest.mark.integration
@pytest.mark.parametrize("family", _ON_A_DESK)
async def test_a_paper_on_a_desk_ships_without_its_desk_or_a_cut_shadow(family: str) -> None:
    image = Image.open(
        io.BytesIO((await render_edition_png(_shipped(family, _DAILY), _LINK)).image)
    )

    assert image.mode == "RGBA"
    alpha = image.getchannel("A")
    edges = [
        alpha.crop((0, 0, alpha.width, 1)),
        alpha.crop((0, alpha.height - 1, alpha.width, alpha.height)),
        alpha.crop((0, 0, 1, alpha.height)),
        alpha.crop((alpha.width - 1, 0, alpha.width, alpha.height)),
    ]
    assert max(_highest(edge) for edge in edges) == 0
    assert _highest(alpha) == _OPAQUE


@pytest.mark.integration
@pytest.mark.parametrize("family", _FULL_BLEED)
async def test_a_full_bleed_family_ships_opaque(family: str) -> None:
    image = Image.open(
        io.BytesIO((await render_edition_png(_shipped(family, _DAILY), _LINK)).image)
    )

    assert ImageStat.Stat(image.convert("RGBA").getchannel("A")).extrema == [(_OPAQUE, _OPAQUE)]


@pytest.mark.integration
@pytest.mark.parametrize("density", sorted(_DENSITIES))
@pytest.mark.parametrize("family", _FULL_BLEED)
async def test_a_full_bleed_family_ships_its_whole_page_and_nothing_more(
    family: EditionFamily, density: str
) -> None:
    frame = edition_frame(family)
    payload = _shipped(family, _DENSITIES[density])

    png = (await render_edition_png(payload, _LINK)).image
    page = (
        await render_html_to_image(
            _render_html(family, payload.model_dump()),
            ImageRenderOptions(width=frame.width, device_scale_factor=frame.device_scale_factor),
        )
    ).image

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
async def test_no_item_row_overprints_another_or_leaves_the_canvas(family: EditionFamily) -> None:
    async with chromium_page(_PAGE) as rendering:
        await rendering.page.set_content(_render_html(family, _as_rendered(family, _BUSY)))
        measured = await rendering.page.evaluate(_ROWS)

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
async def test_the_edition_is_addressed_to_the_user_by_name(family: EditionFamily) -> None:
    payload = {**_DAILY, "recipient_name": "Maya Okafor"}

    text = await _visible_text(_render_html(family, payload))

    assert "Maya" in text
    assert "randeriya" not in text.lower(), f"{family} printed the founder's name"


@pytest.mark.integration
@pytest.mark.parametrize(("name", "code"), [("Maya Okafor", "OKAFOR/M"), ("Maya", "MAYA")])
async def test_the_boarding_pass_barcode_line_carries_the_users_passenger_code(
    name: str, code: str
) -> None:
    text = await _visible_text(
        _render_html(EditionFamily.BOARDINGPASS, {**_DAILY, "recipient_name": name})
    )

    assert f"GA287 0602 {code}" in text


# A brief with nothing on the calendar and nothing waiting on the reader: the
# empty buckets once rendered as fake rows ("EOD  Nothing on the calendar today",
# "REVIEW  Nothing pending your review").
_ONLY_OVERNIGHT = {
    **_DAILY,
    "blocks": [{"kind": "items", "section": 0}],
    "sections": [
        {
            "numeral": "I",
            "title": "GAIA'S WORK",
            "items": [
                make_brief_item("October investor update", "lookback", outcome=BriefOutcome.DRAFTED)
            ],
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
@pytest.mark.parametrize("family", sorted(set(EXPLORER_RENDERER) - {EditionFamily.WEEKLY}))
async def test_an_empty_bucket_renders_no_placeholder_row(
    family: EditionFamily, payload: dict[str, Any]
) -> None:
    text = " ".join((await _visible_text(_render_html(family, payload))).split())

    found = _PLACEHOLDER_ROW.search(text)
    context = text[max(0, found.start() - 60) : found.end() + 40] if found else ""
    assert found is None, f"{family} printed a placeholder row in {context!r}"


_DRAWN_BLOCKS = """() => document.querySelectorAll('.rs-sec, .rs-lead, [data-block]').length"""


@pytest.mark.integration
@pytest.mark.parametrize("family", _FAMILIES)
async def test_an_empty_brief_draws_no_block_and_no_heading(family: EditionFamily) -> None:
    # The weekly lists the week ahead as its calendar, a real block: an empty brief has none.
    empty = {**_QUIET, "week": None}
    async with chromium_page(_PAGE) as rendering:
        await rendering.page.set_content(_render_html(family, _as_rendered(family, empty)))
        drawn = await rendering.page.evaluate(_DRAWN_BLOCKS)

    assert drawn == 0, f"{family} drew {drawn} block(s) for a brief with none"


@pytest.mark.integration
@pytest.mark.parametrize("family", _FAMILIES)
async def test_every_family_marks_where_its_letter_folds(family: str) -> None:
    """The chat letter folds at the template's marker, a gap after the header, not mid-line."""
    rendered = await render_edition_png(_shipped(family, _DENSITIES[sorted(_DENSITIES)[0]]), _LINK)

    assert rendered.fold is not None, f"{family} has no fold marker"
    assert 0.05 < rendered.fold < 0.8, f"{family} folds at {rendered.fold:.2f} of its height"


@pytest.mark.integration
@pytest.mark.parametrize("family", _ON_A_DESK)
async def test_a_family_on_a_desk_records_where_its_paper_lies(family: str) -> None:
    """The letter and the unfold crop to this box, so no desk shows around the paper."""
    rendered = await render_edition_png(_shipped(family, _DENSITIES[sorted(_DENSITIES)[0]]), _LINK)

    assert rendered.paper is not None, f"{family} has no paper marker"
    left, top, right, bottom = rendered.paper
    assert 0 < left < 0.2 and 0.8 < right < 1, f"{family} paper sides at {left:.2f}, {right:.2f}"
    assert 0 <= top < 0.2 and 0.8 < bottom <= 1, f"{family} paper ends at {top:.2f}, {bottom:.2f}"


# Device px inside the box its edges are read at, clear of the sheet's antialiased edge.
_EDGE_INSET_PX = 2
# Where along each edge it is read: past a rounded corner, inside a tilt's wedge of desk.
_EDGE_SHARES = (0.1, 0.9)


# Air Mail's letter is narrower than its envelope, so its box keeps desk beside the letter.
_ONE_SHEET = sorted(set(_ON_A_DESK) - {EditionFamily.POSTAL})


@pytest.mark.integration
@pytest.mark.parametrize("family", _ONE_SHEET)
async def test_a_turned_sheets_paper_box_holds_no_desk_along_its_edges(family: str) -> None:
    """A sheet set at an angle is cut to the level box inside it, not the box around it."""
    rendered = await render_edition_png(_shipped(family, _DAILY), _LINK)
    assert rendered.paper is not None
    alpha = Image.open(io.BytesIO(rendered.image)).convert("RGBA").getchannel("A")
    left, top, right, bottom = (
        edge * size
        for edge, size in zip(rendered.paper, (alpha.width, alpha.height) * 2, strict=True)
    )
    inset = _EDGE_INSET_PX
    along_x = [left + (right - left) * share for share in _EDGE_SHARES]
    along_y = [top + (bottom - top) * share for share in _EDGE_SHARES]
    points = [
        *((x, y) for x in along_x for y in (top + inset, bottom - inset)),
        *((x, y) for y in along_y for x in (left + inset, right - inset)),
    ]

    edges = {(round(x), round(y)): alpha.getpixel((round(x), round(y))) for x, y in points}

    assert all(value == _OPAQUE for value in edges.values()), f"{family} edges: {edges}"


_QUOTED_TITLE = 'Wheat "Field" with Cypresses'


@pytest.mark.integration
@pytest.mark.parametrize("family", sorted(ArtFamily))
async def test_a_quote_in_printed_text_stays_inside_its_attribute(
    family: EditionFamily, monkeypatch: pytest.MonkeyPatch
) -> None:
    artwork = artwork_catalogue()[_ARTWORK]
    monkeypatch.setattr(
        explorer_render,
        "artwork_catalogue",
        lambda: {_ARTWORK: artwork.model_copy(update={"title": _QUOTED_TITLE})},
    )
    async with chromium_page(_PAGE) as rendering:
        await rendering.page.set_content(_render_html(family, _as_rendered(family, _DAILY)))
        alts = await rendering.page.evaluate(
            "() => [...document.querySelectorAll('img[alt]')].map((img) => img.alt)"
        )

    assert any(alt.startswith(_QUOTED_TITLE) for alt in alts), alts
