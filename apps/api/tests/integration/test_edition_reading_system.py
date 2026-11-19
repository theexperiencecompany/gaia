"""Every edition family draws every composed block by the reading system's rules, in real Chromium.

Each family renders four compositions (busy, quiet with a goal, a charted spike, a week) through the
production document at the export scale, after the split by what the family draws. The rules are
measured on the page (edition_reading_rules.js, ported from the founder-reviewed gallery's
reading_check): the verb first, titles in two lines, sections twice the item gap apart, no empty
label column, marks on app items, no imperative on done items, at most two type families, one
family per row, one label per section, headings outranking items, and every composed chart,
quote, goal and note on the page with the facts it must print.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, async_playwright
import pytest
import pytest_asyncio

from app.constants.briefing import EXPLORER_SCALE, ArtFamily, BriefAction
from app.models.brief_composition_models import ChartBlock, NoteBlock, ProgressBlock, QuoteBlock
from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions import EXPLORER_RENDERER
from app.services.briefing.editions.explorer_blocks import build_blocks
from app.services.briefing.editions.explorer_render import EXPLORER_CANVAS_PX
from tests.integration.brief_compositions import COMPOSITIONS, composed_payload

pytestmark = pytest.mark.asyncio(loop_scope="module")

_RULES_JS = (Path(__file__).parent / "edition_reading_rules.js").read_text()
_ARTWORK = "wheat-field-cypresses"
_SPELLED = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
# The settle render_html_to_image waits after fonts report ready.
_SETTLE_MS = 150


def _number_words(n: int) -> list[str]:
    return [str(n), _SPELLED[n]] if n < len(_SPELLED) else [str(n)]


def expectations(payload: BriefingPayload) -> dict[str, Any]:
    """Return what the page must show for the payload's drawn blocks."""
    charts = [b for b in payload.blocks if isinstance(b, ChartBlock)]
    quotes = [b.quote for b in payload.blocks if isinstance(b, QuoteBlock)]
    goals = [b.goal for b in payload.blocks if isinstance(b, ProgressBlock)]
    drawn = build_blocks(payload.blocks, payload.sections, payload.calendar, payload.date)
    return {
        "imperatives": [a.value for a in BriefAction],
        "counts": {
            "chart": len(charts),
            "quote": len(quotes),
            "progress": len(goals),
            "note": sum(isinstance(b, NoteBlock) for b in payload.blocks),
        },
        "charts": [
            {
                "title": c["title"],
                "takeaway": c["takeaway"],
                "unit": c["unit"],
                "range": c["range"],
                "legend": [s["name"] for s in c["series"]],
                "x": c["x"],
            }
            for c in drawn
            if c["kind"] == "chart"
        ],
        "quotes": [{"text": q.text, "author": q.author, "app": q.app} for q in quotes],
        "progress": [
            {
                "statement": g.statement,
                "done": _number_words(g.done),
                "total": _number_words(g.done + g.open),
            }
            for g in goals
        ],
        "notes": [b.text for b in payload.blocks if isinstance(b, NoteBlock)],
        "sources": payload.sources_read,
    }


async def reading_problems(browser: Browser, payload: BriefingPayload) -> list[str]:
    """Render the payload's family at the export scale and return every broken reading rule."""
    html = EXPLORER_RENDERER[payload.template_family](
        payload, edition_no=42, generated_local="6:02 AM"
    )
    context = await browser.new_context(
        viewport={"width": EXPLORER_CANVAS_PX, "height": 900}, device_scale_factor=EXPLORER_SCALE
    )
    try:
        page = await context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(f"page error: {error}"))
        await page.set_content(html, wait_until="networkidle")
        await page.evaluate("document.fonts.ready")
        await page.wait_for_timeout(_SETTLE_MS)
        result = await page.evaluate(_RULES_JS, expectations(payload))
        return errors + list(result["fails"])
    finally:
        await context.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def browser() -> AsyncIterator[Browser]:
    async with async_playwright() as p:
        launched = await p.chromium.launch(args=["--font-render-hinting=none"])
        try:
            yield launched
        finally:
            await launched.close()


@pytest.mark.integration
@pytest.mark.parametrize("composition", sorted(COMPOSITIONS))
@pytest.mark.parametrize("family", sorted(EXPLORER_RENDERER))
async def test_family_draws_the_composition_by_the_reading_rules(
    browser: Browser, family: str, composition: str
) -> None:
    payload = composed_payload(composition, family, _ARTWORK if family in ArtFamily else None)

    assert await reading_problems(browser, payload) == []
