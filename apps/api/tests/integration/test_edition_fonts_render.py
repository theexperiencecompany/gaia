"""Every edition family draws every glyph from its embedded webfonts, never a system font.

Renders each family in headless Chromium through the production document, then
re-renders it in place with every option of every skin axis. For each state it reads
the computed font-family and document.fonts for every text node, and asks Chromium
(CSS.getPlatformFontsForNode) which font actually drew each run: a glyph from a
system font is the bug, because macOS and Linux hosts ship different ones.
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import CDPSession, Page, async_playwright
import pytest

from app.services.briefing.editions import EXPLORER_RENDERER
from app.services.briefing.editions.edition_fonts import EDITION_FAMILIES
from tests.integration.test_edition_families_render import (
    _DAILY,
    _QUIET,
    _as_rendered,
    _render_html,
)

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


async def _system_fonts(cdp: CDPSession) -> dict[str, int]:
    """Return every non-embedded font Chromium drew a glyph with, and how many glyphs."""
    document = await cdp.send("DOM.getDocument", {"depth": -1})
    used: dict[str, int] = {}
    stack: list[dict[str, Any]] = [document["root"]]
    while stack:
        node = stack.pop()
        stack.extend(node.get("children", []))
        if node.get("nodeType") != 1 or node.get("nodeName") in ("SCRIPT", "STYLE", "HEAD"):
            continue
        fonts = await cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node["nodeId"]})
        for font in fonts["fonts"]:
            if not font["isCustomFont"]:
                used[font["familyName"]] = used.get(font["familyName"], 0) + font["glyphCount"]
    return used


async def _check_every_skin(page: Page, family: str) -> list[str]:
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
            for name, n in (await _system_fonts(cdp)).items()
        ]
    return failures


@pytest.mark.integration
@pytest.mark.parametrize("payload", [_DAILY, _QUIET], ids=["daily", "quiet"])
@pytest.mark.parametrize("family", sorted(EXPLORER_RENDERER))
async def test_every_glyph_comes_from_an_embedded_font(
    family: str, payload: dict[str, Any]
) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 540, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.set_content(
                _render_html(family, _as_rendered(family, payload)), wait_until="networkidle"
            )
            failures = await _check_every_skin(page, family)
        finally:
            await browser.close()

    assert not errors, errors
    assert not failures, "\n".join(failures)
