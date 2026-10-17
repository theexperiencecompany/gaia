"""Render a briefing payload through one of the vendored explorer template families.

The families are the founder's approved JS design explorer (editions/explorer/js/
tpl-*.js), executed inside the headless-Chromium raster pipeline. The document is
fully synchronous (no fetch or timers), so Playwright's networkidle wait returns
immediately.

Skin selection reimplements the explorer shell's mulberry32/strSeed RNG rather than
importing it: the vendored files never expose it.
"""

import base64
from functools import lru_cache
import json
from pathlib import Path
import re

from app.constants.briefing import POSTAL_FAMILY
from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions._shared import EXPLORER_CANVAS_PX
from app.services.briefing.editions.artworks import artwork_for
from app.services.briefing.editions.explorer_adapter import ExplorerArt, build_ed
from app.services.briefing.editions.stamps import (
    STAMP_ASSET_KEY,
    axis_stamp_assets,
    stamp_asset_url,
)

_EXPLORER_DIR = Path(__file__).parent / "explorer"
_JS_DIR = _EXPLORER_DIR / "js"
_ASSETS_DIR = _EXPLORER_DIR / "assets"
_ASSETS_JSON = _ASSETS_DIR / "assets.json"
_TEC_MARK_WEBP = _ASSETS_DIR / "brand" / "tec_mark_black.webp"

# Matches only a top-level `EXPLORER.register({ id: "..." ...` — not an axis
# option's `id:` further down the same object literal.
_REGISTER_ID_PATTERN = re.compile(r'EXPLORER\.register\(\{\s*\n\s*id:\s*"([a-z0-9-]+)"')

# The band wallpaper in assets.json (WebP; the paintings there are JPEGs).
_BAND_ASSET_KEY = "BAND"
# The Experience Company symbol heading Air Mail's return address.
_TEC_MARK_ASSET_KEY = "TEC_MARK"

# (family, asset key, weight, style) for the two embedded webfonts the
# templates are designed against (explorer-contract.md rule 6).
_FONT_FACE_SPEC: list[tuple[str, str, int, str]] = [
    ("Aeonik Extended", "AEONIK_SEMIBOLD", 600, "normal"),
    ("Aeonik Extended", "AEONIK_BOLD", 700, "normal"),
    ("Playfair Display", "PLAYFAIR_NORMAL_500", 500, "normal"),
    ("Playfair Display", "PLAYFAIR_NORMAL_700", 700, "normal"),
    ("Playfair Display", "PLAYFAIR_ITALIC_500", 500, "italic"),
]

# Generic deterministic RNG — a straight port of explorer-shell.html's own
# helpers, not vendored design. Picks one option per skin axis from
# SKIN_SEED so the same seed always yields the same skin.
_RNG_SHIM = """
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function strSeed(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
"""


@lru_cache(maxsize=1)
def _module_sources() -> tuple[str, ...]:
    return tuple(f.read_text() for f in sorted(_JS_DIR.glob("tpl-*.js")))


@lru_cache(maxsize=1)
def explorer_family_ids() -> tuple[str, ...]:
    """Return the vendored explorer template ids.

    Derived from their EXPLORER.register calls so a newly vendored tpl-*.js file
    auto-joins the list.
    """
    ids: list[str] = []
    for js_file in sorted(_JS_DIR.glob("tpl-*.js")):
        ids.extend(_REGISTER_ID_PATTERN.findall(js_file.read_text()))
    return tuple(ids)


@lru_cache(maxsize=1)
def _raw_assets() -> dict[str, str]:
    """Return assets.json: asset key -> base64 file bytes."""
    raw: dict[str, str] = json.loads(_ASSETS_JSON.read_text())
    return raw


@lru_cache(maxsize=1)
def _asset_data_uris() -> dict[str, str]:
    """Return the images every family may read from ed.assets, as data URIs."""
    tec_mark = base64.b64encode(_TEC_MARK_WEBP.read_bytes()).decode()
    return {
        _BAND_ASSET_KEY: f"data:image/webp;base64,{_raw_assets()[_BAND_ASSET_KEY]}",
        _TEC_MARK_ASSET_KEY: f"data:image/webp;base64,{tec_mark}",
    }


def _art(edition_no: int) -> ExplorerArt:
    """Return the painting the edition hangs, its image inlined as a data URI."""
    artwork = artwork_for(edition_no)
    return {
        "src": f"data:image/jpeg;base64,{_raw_assets()[artwork.asset_key]}",
        "title": artwork.title,
        "artist": artwork.artist,
        "year": artwork.year,
        "medium": artwork.medium,
    }


@lru_cache(maxsize=1)
def _font_faces_css() -> str:
    raw = _raw_assets()
    rules = [
        f"@font-face{{font-family:'{family}';font-style:{style};"
        f"font-weight:{weight};font-display:block;"
        f"src:url(data:font/woff2;base64,{raw[asset_key]}) format('woff2');}}"
        for family, asset_key, weight, style in _FONT_FACE_SPEC
    ]
    return "".join(rules)


def _json_for_script(value: object) -> str:
    """JSON-encode value for embedding inside an inline script literal.

    Escapes "</" and "<!--" so no payload text can close the script tag or open an HTML
    comment.
    """
    return json.dumps(value).replace("</", "<\\/").replace("<!--", "<\\!--")


def render_explorer_edition(
    payload: BriefingPayload,
    *,
    family: str,
    skin_seed: str,
    edition_no: int,
    generated_local: str,
    # The default is unobservable — the parameter is deleted before its first
    # read (see below), so no value of it can reach the document.
    tz_label: str = "",  # pragma: no mutate
) -> str:
    """Render a briefing payload through one vendored explorer family.

    Raises ValueError for a family not in explorer_family_ids(). skin_seed makes the skin
    deterministic; tz_label is accepted for signature parity with render_edition, unused.
    """
    del tz_label  # accepted for signature parity; see docstring
    if family not in explorer_family_ids():
        raise ValueError(f"unknown explorer family: {family!r}")

    assets = dict(_asset_data_uris())
    if family == POSTAL_FAMILY:
        # The drawn city's stamp; a legacy brief without one picks from the
        # template's own city axis, so those cities' art loads too.
        if payload.stamp_city:
            assets[STAMP_ASSET_KEY] = stamp_asset_url(payload.stamp_city)
        else:
            assets.update(axis_stamp_assets())
    ed = build_ed(
        payload,
        edition_no=edition_no,
        generated_local=generated_local,
        assets=assets,
        art=_art(edition_no),
        family=family,
    )

    modules_html = "\n".join(f"<script>\n{source}\n</script>" for source in _module_sources())

    ed_json = _json_for_script(ed)
    family_json = _json_for_script(family)
    seed_json = _json_for_script(f"{skin_seed}|{family}")
    assets_json = _json_for_script(assets)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width={EXPLORER_CANVAS_PX}">
<style>
{_font_faces_css()}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }}
body {{ width: {EXPLORER_CANVAS_PX}px; }}
</style>
</head>
<body>
<div id="root"></div>
<script>
"use strict";
const TEMPLATES = [];
const EXPLORER = {{
  register(t) {{
    if (!t.id || !t.name || !t.axes || !t.render || !t.css) throw new Error("bad template: " + (t.id || "?"));
    TEMPLATES.push(t);
  }},
  assets: {assets_json},
}};
</script>
{modules_html}
<script>
"use strict";
{_RNG_SHIM}
const ed = {ed_json};
const FAMILY = {family_json};
const SKIN_SEED = {seed_json};
const tpl = TEMPLATES.find((t) => t.id === FAMILY);
if (!tpl) throw new Error("explorer family not registered: " + FAMILY);
const skin = {{}};
for (const axisName of Object.keys(tpl.axes)) {{
  const opts = tpl.axes[axisName];
  const rng = mulberry32(strSeed(SKIN_SEED + "|" + axisName));
  skin[axisName] = opts[Math.floor(rng() * opts.length)];
}}
// Air Mail's city is the brief's drawn stamp city, not a random skin pick.
if (ed.stamp) skin.city = ed.stamp;
const article = tpl.render(ed, skin);
document.head.insertAdjacentHTML("beforeend", "<style>" + tpl.css + "</style>");
document.getElementById("root").innerHTML = article;
</script>
</body>
</html>"""
