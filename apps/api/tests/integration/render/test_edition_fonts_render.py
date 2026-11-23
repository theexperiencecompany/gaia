"""Every edition family draws every glyph from its embedded webfonts, never a system font.

Renders each family in headless Chromium through the production document, then
re-renders it in place with every option of every skin axis. For each state it reads
the computed font-family and document.fonts for every text node, and asks Chromium
(CSS.getPlatformFontsForNode) which font actually drew each run: a glyph from a
system font is the bug, because macOS and Linux hosts ship different ones. Chromium
picks a run's font from its computed font and its characters alone, so a run already
asked about in this test is not asked again.
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import CDPSession, Page, ViewportSize
import pytest

from app.constants.briefing import EditionFamily
from app.services.briefing.editions import EXPLORER_RENDERER
from app.services.briefing.editions.edition_fonts import EDITION_FAMILIES
from app.services.dev_brief_compositions import COMPOSITIONS, composed_payload
from app.services.render.chromium import chromium_page
from tests.integration.render.test_edition_families_render import (
    _DAILY,
    _LINK,
    _QUIET,
    _artwork,
    _as_rendered,
    _render_html,
    _stamp,
)

pytestmark = pytest.mark.asyncio(loop_scope="package")

_PAGE: ViewportSize = {"width": 540, "height": 900}

# The page's own skin plus one skin per axis option, each rendered by the template itself.
_SKINS_JS = """() => {
  const t = TEMPLATES.find((x) => x.id === FAMILY);
  window.__skins = [skin, ...Object.entries(t.axes).flatMap(([axis, opts]) => opts.map((o) => ({ ...skin, [axis]: o })))];
  return window.__skins.length;
}"""
_DRAW_JS = """async (i) => {
  const t = TEMPLATES.find((x) => x.id === FAMILY);
  document.getElementById("root").innerHTML = t.render(ed, window.__skins[i]);
  await document.fonts.ready;
}"""
# Text nodes whose first family is not embedded for this edition, or has no loaded face.
_UNRESOLVED_JS = """(allowed) => {
  const loaded = new Set([...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family.replace(/["']/g, "")));
  const bad = [];
  const walk = document.createTreeWalker(document.getElementById("root"), NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if (!n.nodeValue.trim()) continue;
    const cs = getComputedStyle(n.parentElement);
    if (cs.display === "none") continue;
    const first = cs.fontFamily.split(",")[0].trim().replace(/["']/g, "");
    if (!allowed.includes(first) || !loaded.has(first)) bad.push(`${JSON.stringify(n.nodeValue.trim().slice(0, 30))} -> ${cs.fontFamily}`);
  }
  return bad;
}"""
# Marks each element whose own text runs pair a computed font with characters not yet asked about.
_MARK_UNASKED_JS = """() => {
  const asked = (window.__askedRuns ??= new Set());
  document.querySelectorAll("[data-font-probe]").forEach((el) => el.removeAttribute("data-font-probe"));
  let marked = 0;
  for (const el of document.body.querySelectorAll("*")) {
    if (el.closest("script, style")) continue;
    const text = [...el.childNodes].filter((n) => n.nodeType === Node.TEXT_NODE).map((n) => n.nodeValue).join("");
    if (!text.trim()) continue;
    const cs = getComputedStyle(el);
    const run = [cs.font, cs.fontFamily, cs.fontVariant, cs.fontFeatureSettings, cs.fontVariationSettings,
      cs.fontSynthesis, cs.textTransform, el.closest("[lang]")?.lang ?? "", text].join("|");
    if (asked.has(run)) continue;
    asked.add(run);
    el.setAttribute("data-font-probe", "");
    marked += 1;
  }
  return marked;
}"""


async def _system_fonts(page: Page, cdp: CDPSession) -> dict[str, int]:
    """Return every non-embedded font Chromium drew a not-yet-asked run with, and how many glyphs."""
    if not await page.evaluate(_MARK_UNASKED_JS):
        return {}
    document = await cdp.send("DOM.getDocument", {"depth": 0})
    marked = await cdp.send(
        "DOM.querySelectorAll",
        {"nodeId": document["root"]["nodeId"], "selector": "[data-font-probe]"},
    )
    used: dict[str, int] = {}
    for node_id in marked["nodeIds"]:
        fonts = await cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node_id})
        for font in fonts["fonts"]:
            if not font["isCustomFont"]:
                used[font["familyName"]] = used.get(font["familyName"], 0) + font["glyphCount"]
    return used


async def _check_every_skin(page: Page, family: EditionFamily) -> list[str]:
    cdp = await page.context.new_cdp_session(page)
    await cdp.send("DOM.enable")
    await cdp.send("CSS.enable")
    failures: list[str] = []
    for i in range(await page.evaluate(_SKINS_JS)):
        await page.evaluate(_DRAW_JS, i)
        unresolved = await page.evaluate(_UNRESOLVED_JS, list(EDITION_FAMILIES[family]))
        failures += [f"skin {i}: {line}" for line in unresolved]
        failures += [
            f"skin {i}: drew {n} glyphs in system font {name!r}"
            for name, n in (await _system_fonts(page, cdp)).items()
        ]
    return failures


@pytest.mark.integration
@pytest.mark.parametrize("payload", [_DAILY, _QUIET], ids=["daily", "quiet"])
@pytest.mark.parametrize("family", sorted(EXPLORER_RENDERER))
async def test_every_glyph_comes_from_an_embedded_font(
    family: EditionFamily, payload: dict[str, Any]
) -> None:
    async with chromium_page(_PAGE) as rendering:
        await rendering.page.set_content(
            _render_html(family, _as_rendered(family, payload)), wait_until="networkidle"
        )
        failures = await _check_every_skin(rendering.page, family)

    assert not rendering.script_errors, rendering.script_errors
    assert not failures, "\n".join(failures)


@pytest.mark.integration
@pytest.mark.parametrize("composition", sorted(COMPOSITIONS))
@pytest.mark.parametrize("family", sorted(EXPLORER_RENDERER))
async def test_every_composed_block_draws_from_an_embedded_font(
    family: EditionFamily, composition: str
) -> None:
    payload = composed_payload(composition, family, _artwork(family), _stamp(family))
    html = EXPLORER_RENDERER[family](payload, link=_LINK, edition_no=287)
    async with chromium_page(_PAGE) as rendering:
        await rendering.page.set_content(html, wait_until="networkidle")
        failures = await _check_every_skin(rendering.page, family)

    assert not rendering.script_errors, rendering.script_errors
    assert not failures, "\n".join(failures)
