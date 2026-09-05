"""Render a briefing payload through one of the 20 vendored explorer
template families (``editions/explorer/js/tpl-*.js``).

Unlike the other editions in this package, these templates are not Python —
they are the founder's approved JS design explorer, executed inside the same
headless-Chromium raster pipeline (``render.py``'s ``render_html_to_image``)
that screenshots every edition. ``render_explorer_edition`` builds one
self-contained HTML document that: (1) defines a minimal ``EXPLORER`` shim,
(2) inlines all 10 vendored ``<script>`` modules verbatim so they register
themselves exactly as they do in the original explorer, (3) inlines the
``ed`` payload (built by ``explorer_adapter.build_ed``) and a deterministic
skin pick, and (4) renders the requested family into the DOM — all
synchronously, so Playwright's ``page.set_content(..., wait_until="networkidle")``
captures the finished render (no fetch/timers in this document at all, so
"networkidle" and "load" are effectively immediate).

Skin selection reimplements the explorer shell's own ``mulberry32``/
``strSeed`` RNG (see ``explorer-shell.html``) rather than importing it — it's
generic deterministic-hash infra, not part of any one template's approved
design, and the vendored files never expose it themselves.
"""

from functools import lru_cache
import json
from pathlib import Path
import re

from app.services.briefing.editions._shared import CANVAS_PX
from app.services.briefing.editions.explorer_adapter import build_ed

_EXPLORER_DIR = Path(__file__).parent / "explorer"
_JS_DIR = _EXPLORER_DIR / "js"
_ASSETS_DIR = _EXPLORER_DIR / "assets"

# Matches only a top-level `EXPLORER.register({ id: "..." ...` — not an axis
# option's `id:` further down the same object literal.
_REGISTER_ID_PATTERN = re.compile(r'EXPLORER\.register\(\{\s*\n\s*id:\s*"([a-z0-9-]+)"')

# Asset key -> MIME type, mirroring explorer-shell.html's ASSETS map.
_ASSET_MIME: dict[str, str] = {
    "ART1": "image/jpeg",
    "BAND": "image/webp",
    "STAMP_TOKYO": "image/jpeg",
    "STAMP_LONDON": "image/jpeg",
    "STAMP_PARIS": "image/jpeg",
    "STAMP_VENICE": "image/jpeg",
    "STAMP_ROME": "image/jpeg",
    "STAMP_KYOTO": "image/jpeg",
    "STAMP_NEWYORK": "image/jpeg",
    "STAMP_AMSTERDAM": "image/jpeg",
    "STAMP_ISTANBUL": "image/jpeg",
    "STAMP_AGRA": "image/jpeg",
}

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
    """The vendored explorer template ids, derived from their own
    ``EXPLORER.register({ id: ... })`` calls so a newly vendored
    ``tpl-*.js`` file auto-joins the list without touching this module."""
    ids: list[str] = []
    for js_file in sorted(_JS_DIR.glob("tpl-*.js")):
        ids.extend(_REGISTER_ID_PATTERN.findall(js_file.read_text()))
    return tuple(ids)


@lru_cache(maxsize=1)
def _asset_data_uris() -> dict[str, str]:
    raw: dict[str, str] = json.loads((_ASSETS_DIR / "assets.json").read_text())
    return {
        key: f"data:{_ASSET_MIME[key]};base64,{b64}"
        for key, b64 in raw.items()
        if key in _ASSET_MIME
    }


@lru_cache(maxsize=1)
def _art_credit() -> str:
    art_credits: dict[str, str] = json.loads((_ASSETS_DIR / "credits.json").read_text())
    return art_credits.get("ART1", "")


@lru_cache(maxsize=1)
def _font_faces_css() -> str:
    raw: dict[str, str] = json.loads((_ASSETS_DIR / "assets.json").read_text())
    rules = [
        f"@font-face{{font-family:'{family}';font-style:{style};"
        f"font-weight:{weight};font-display:block;"
        f"src:url(data:font/woff2;base64,{raw[asset_key]}) format('woff2');}}"
        for family, asset_key, weight, style in _FONT_FACE_SPEC
    ]
    return "".join(rules)


def _json_for_script(value: object) -> str:
    """JSON-encode ``value`` for embedding inside an inline ``<script>``
    literal — escapes ``</`` and ``<!--`` so no payload text can prematurely
    close the script tag or open an HTML comment."""
    return json.dumps(value).replace("</", "<\\/").replace("<!--", "<\\!--")


def render_explorer_edition(
    payload: dict,
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

    Args:
        payload: A ``BriefingPayload.model_dump()`` dict.
        family: One of ``explorer_family_ids()``.
        skin_seed: Determinism key for the axis picks — same seed, same
            skin, always (callers typically use the payload date + family).
        edition_no: Sequential edition number.
        generated_local: Human generation time, e.g. ``"6:02 AM"``.
        tz_label: Optional timezone label. Unlike the other editions, the
            explorer templates have no dedicated tz slot in ``ed`` — it is
            accepted for signature parity with ``render_edition`` and
            currently unused (matches ``generated_local``'s "not yet wired
            end to end" state; see ``explorer_adapter.build_ed`` docstring).

    Returns:
        A full, self-contained HTML document as a string.

    Raises:
        ValueError: ``family`` is not a registered explorer template — fails
            before touching the browser rather than risking a blank raster.
    """
    del tz_label  # accepted for signature parity; see docstring
    if family not in explorer_family_ids():
        raise ValueError(f"unknown explorer family: {family!r}")

    assets = _asset_data_uris()
    ed = build_ed(
        payload,
        edition_no=edition_no,
        generated_local=generated_local,
        assets=assets,
        art_credit=_art_credit(),
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
<meta name="viewport" content="width={CANVAS_PX}">
<style>
{_font_faces_css()}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }}
body {{ width: {CANVAS_PX}px; }}
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
const article = tpl.render(ed, skin);
document.head.insertAdjacentHTML("beforeend", "<style>" + tpl.css + "</style>");
document.getElementById("root").innerHTML = article;
</script>
</body>
</html>"""
