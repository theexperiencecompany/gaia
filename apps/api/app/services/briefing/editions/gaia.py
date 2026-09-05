"""GAIA edition — a briefing rendered in GAIA's own product design language.

Dark-first, flat and single-accent: depth comes from layered backgrounds and
whitespace, never from boxes, borders, shadows or gradients. One bright cyan
(``#00bbff``) is the only accent — it marks the identity, the section numerals,
the things that still need the reader, and attached artifacts. Everything else
is neutral. The display headline is set in PP Editorial New (embedded so the
offline raster gets crisp brand type); all other text is Inter.

The output is a fixed 1180px-wide, self-contained HTML document (one inline
stylesheet, fonts embedded as data URIs, no external requests) destined for a
headless-browser raster. ``render_edition`` is the only entry point; everything
else is a private section builder.
"""

from html import escape

from app.services.briefing.editions._shared import CANVAS_PX, font_face, format_date

# --- Palette (layered neutrals, one cyan accent — never red) --------------------
_ACCENT = "#00bbff"
_PAGE = "#000000"
_TEXT = "#f4f4f5"
_BODY = "#d4d4d8"
_MUTED = "#a1a1aa"
_DIM = "#71717a"
_HAIR = "#27272a"

# --- Font stacks ----------------------------------------------------------------
# Inter carries every UI surface; PP Editorial New is reserved for the display
# headline. The Editorial faces are embedded below; the Inter stack falls back to
# the platform UI face since Inter itself is not vendored for the offline raster.
_INTER = 'Inter, system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif'
_DISPLAY = '"PP Editorial New", "Playfair Display", Georgia, serif'

# Canvas geometry — the raster viewport is 1180px; the page is that exact width.
_CANVAS_PX = CANVAS_PX

# --- Item furniture: kind -> (marker, tone) -------------------------------------
# ``BriefingItemKind`` ("gaia"/"you"/"proposal"/"lookback"/"note") and the
# caller's "needs_you" vocabulary both resolve here. Cyan markers flag the things
# that still need the reader; dim markers note work already done; a plain item
# carries no marker at all.
_ACCENT_TONE = "accent"
_DIM_TONE = "dim"
_MARKERS: dict[str, tuple[str, str]] = {
    "proposal": ("Needs your approval", _ACCENT_TONE),
    "needs_you": ("Your move", _ACCENT_TONE),
    "you": ("Your move", _ACCENT_TONE),
    "lookback": ("Done", _DIM_TONE),
    "gaia": ("Done", _DIM_TONE),
    "note": ("", ""),
}

# Subtle cyan hint for an attached artifact — never a raw URL.
_ARTIFACT_HINT = "&middot;&#8201;Open"
_DATELINE_SEP = " &middot; "

# Embedded once at import: the two Editorial weights the edition actually uses.
_FONT_FACES = font_face("PP Editorial New", "PPEditorialNew-Ultralight.woff2", 200) + font_face(
    "PP Editorial New", "PPEditorialNew-Regular.woff2", 400
)


def render_edition(
    payload: dict,
    *,
    edition_no: int,
    generated_local: str,
    tz_label: str = "",
) -> str:
    """Render a briefing payload in GAIA's product design language.

    Args:
        payload: A ``BriefingPayload.model_dump()`` dict.
        edition_no: Sequential edition number printed in the dateline.
        generated_local: Human generation time, e.g. ``"6:02 AM"``.
        tz_label: Optional timezone label appended after the time.

    Returns:
        A full, self-contained HTML document as a string.
    """
    kicker = escape(str(payload.get("kicker", "")))
    headline = escape(str(payload.get("headline", "")))
    lede = escape(str(payload.get("lede", "")))
    caption = escape(str(payload.get("caption", "")))
    date_human = format_date(str(payload.get("date", "")))

    generated = escape(generated_local)
    if tz_label:
        generated = f"{generated}&#8201;{escape(tz_label)}"

    dateline = _DATELINE_SEP.join(
        part
        for part in (
            date_human,
            f"Edition {edition_no}",
            f"Generated {generated}",
        )
        if part
    )

    stats = _render_stats(payload.get("stats") or [])
    sections = "\n".join(_render_section(section) for section in payload.get("sections") or [])

    kicker_html = f'<div class="kicker">{kicker}</div>' if kicker else ""
    lede_html = f'<p class="lede">{lede}</p>' if lede else ""
    caption_html = f'<footer class="colophon">{caption}</footer>' if caption else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width={_CANVAS_PX}">
<style>{_STYLE}</style>
</head>
<body>
<main class="brief">
  <div class="aura"></div>
  <div class="page">
    <header class="masthead">
      <div class="brand">
        <span class="mark"></span>
        <span class="wordmark">GAIA</span>
        {kicker_html}
      </div>
      <div class="dateline">{dateline}</div>
    </header>

    <section class="hero">
      <h1 class="headline">{headline}</h1>
      {lede_html}
    </section>

    {stats}

    <div class="sections">
{sections}
    </div>

    {caption_html}
  </div>
</main>
</body>
</html>"""


def _render_stats(stats: list[dict]) -> str:
    """Render the stat row as a flat, borderless figure strip, or nothing."""
    if not stats:
        return ""

    cells = []
    for stat in stats:
        value = escape(str(stat.get("value", "")))
        label = escape(str(stat.get("label", "")))
        delta = stat.get("delta")
        delta_html = f'<span class="s-delta">{escape(str(delta))}</span>' if delta else ""
        cells.append(
            f'<div class="stat">'
            f'<span class="s-value">{value}{delta_html}</span>'
            f'<span class="s-label">{label}</span>'
            f"</div>"
        )
    return f'<div class="stats">{"".join(cells)}</div>'


def _render_section(section: dict) -> str:
    """Render one numeraled section, or nothing when it has no items."""
    items = section.get("items") or []
    if not items:
        return ""

    numeral = escape(str(section.get("numeral", "")))
    title = escape(str(section.get("title", "")))
    body = "\n".join(_render_item(item) for item in items)

    return f"""      <section class="section">
        <div class="section-head">
          <span class="numeral">{numeral}</span>
          <span class="s-title">{title}</span>
        </div>
        <div class="items">
{body}
        </div>
      </section>"""


def _render_item(item: dict) -> str:
    """Render a single section item with its marker and artifact hint."""
    text = escape(str(item.get("text", "")))
    # An unknown or absent kind renders like a note: no marker, no tone.
    kind = str(item.get("kind"))
    marker, tone = _MARKERS.get(kind, _MARKERS["note"])

    marker_html = f'<span class="marker {tone}">{escape(marker)}</span>' if marker else ""
    hint_html = f'<span class="open">{_ARTIFACT_HINT}</span>' if item.get("link") else ""

    return (
        f'          <p class="item">{marker_html}<span class="i-text">{text}{hint_html}</span></p>'
    )


_STYLE = f"""
{_FONT_FACES}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }}
body {{
  width: {_CANVAS_PX}px;
  background: {_PAGE};
  color: {_TEXT};
  font-family: {_INTER};
}}
.brief {{ position: relative; width: {_CANVAS_PX}px; background: {_PAGE}; overflow: hidden; }}

/* --- Signature cyan aura (the only gradient GAIA allows) ------------------- */
.aura {{
  position: absolute;
  top: -260px;
  left: -160px;
  width: 900px;
  height: 620px;
  background: radial-gradient(46% 50% at 30% 40%, rgba(0, 187, 255, 0.16), rgba(0, 187, 255, 0) 72%);
  pointer-events: none;
}}
.page {{ position: relative; z-index: 1; padding: 88px 96px 72px; }}

/* --- Masthead ------------------------------------------------------------- */
.masthead {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 32px;
}}
.brand {{ display: flex; align-items: center; gap: 12px; }}
.mark {{
  width: 10px;
  height: 10px;
  border-radius: 3px;
  background: {_ACCENT};
}}
.wordmark {{
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: {_TEXT};
}}
.kicker {{
  margin-left: 4px;
  font-size: 15px;
  font-weight: 500;
  color: {_MUTED};
}}
.dateline {{
  font-size: 14px;
  font-weight: 400;
  color: {_DIM};
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}}

/* --- Hero ----------------------------------------------------------------- */
.hero {{ margin-top: 76px; }}
.headline {{
  font-family: {_DISPLAY};
  font-weight: 200;
  font-size: 66px;
  line-height: 1.06;
  letter-spacing: -0.02em;
  color: {_TEXT};
  max-width: 19ch;
}}
.lede {{
  margin-top: 26px;
  font-size: 21px;
  font-weight: 400;
  line-height: 1.5;
  color: {_MUTED};
  max-width: 60ch;
}}

/* --- Stats ---------------------------------------------------------------- */
.stats {{
  display: flex;
  gap: 72px;
  margin-top: 56px;
  padding-top: 40px;
  border-top: 1px solid {_HAIR};
}}
.stat {{ display: flex; flex-direction: column; }}
.s-value {{
  font-size: 40px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.02em;
  color: {_TEXT};
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}}
.s-delta {{ margin-left: 10px; font-size: 16px; font-weight: 500; color: {_ACCENT}; }}
.s-label {{ margin-top: 10px; font-size: 15px; font-weight: 400; color: {_DIM}; }}

/* --- Sections ------------------------------------------------------------- */
.sections {{ margin-top: 60px; }}
.section + .section {{ margin-top: 44px; }}
.section-head {{ display: flex; align-items: baseline; gap: 16px; }}
.numeral {{
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: {_ACCENT};
  font-variant-numeric: tabular-nums;
  min-width: 1.4ch;
}}
.s-title {{
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: {_TEXT};
}}
.items {{ margin-top: 22px; padding-left: calc(1.4ch + 16px); }}
.item {{ display: flex; align-items: baseline; gap: 14px; }}
.item + .item {{ margin-top: 16px; }}
.marker {{
  flex: 0 0 auto;
  min-width: 152px;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.6;
  padding-top: 1px;
}}
.marker.accent {{ color: {_ACCENT}; }}
.marker.dim {{ color: {_DIM}; }}
.i-text {{
  font-size: 18px;
  font-weight: 400;
  line-height: 1.55;
  color: {_BODY};
}}
.open {{ margin-left: 8px; font-weight: 500; color: {_ACCENT}; white-space: nowrap; }}

/* --- Colophon ------------------------------------------------------------- */
.colophon {{
  margin-top: 64px;
  padding-top: 24px;
  border-top: 1px solid {_HAIR};
  font-size: 14px;
  font-weight: 400;
  color: {_DIM};
}}
"""
