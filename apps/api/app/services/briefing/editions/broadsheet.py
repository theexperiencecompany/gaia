"""Broadsheet edition — a briefing rendered as a newspaper front page.

One editorial tradition, committed to fully: a restrained NYT/FT-style dateline
masthead set in system serif faces. Hierarchy comes from size contrast, small
caps, hairline versus heavy rules and whitespace — never boxes, shadows or
gradients. A single deep-ink-red accent marks the things that need the reader.

The output is a fixed 1180px-wide, self-contained HTML document (all CSS inline,
system fonts only) destined for a headless-browser raster. ``render_edition`` is
the only entry point; everything else is a private section builder.
"""

from datetime import date
from html import escape

# --- Palette (warm paper, warm ink, one accent) --------------------------------
_PAPER = "#f6f3ea"
_INK = "#1b1a16"
_MUTED = "#6a6357"
_HAIR = "#c9c3b4"
_ACCENT = "#8a1c17"

# --- System font stacks (no webfonts — the raster runs offline) -----------------
_SERIF = '"Iowan Old Style","Palatino Linotype",Georgia,"Times New Roman",serif'
_DISPLAY = '"Didot","Bodoni 72","Iowan Old Style",Georgia,serif'
_GROTESQUE = 'system-ui,"Helvetica Neue","Arial",sans-serif'

# Canvas geometry — the raster viewport is 1180px; the page is that exact width.
_CANVAS_PX = 1180

# --- Item furniture: kind -> (catchline, is_accent) ----------------------------
# The payload's own ``BriefingItemKind`` ("gaia"/"you"/"proposal"/"lookback"/
# "note") and the caller's proposal/needs_you vocabulary both resolve here, so a
# single mapping owns every catchline the broadsheet knows how to set.
_CATCHLINES: dict[str, tuple[str, bool]] = {
    "proposal": ("Approve", True),
    "needs_you": ("Needs you", True),
    "you": ("Needs you", True),
    "lookback": ("Filed", False),
    "gaia": ("Filed", False),
    "note": ("", False),
}

# Section mark standing in for an attached artifact — printed in the accent, no
# raw URL ever surfaces on the page.
_ARTIFACT_MARK = "§"


def render_edition(
    payload: dict,
    *,
    edition_no: int,
    generated_local: str,
    tz_label: str = "",
) -> str:
    """Render a briefing payload as a broadsheet front page.

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
    date_human = _format_date(str(payload.get("date", "")))

    generated = escape(generated_local)
    if tz_label:
        generated = f"{generated}&#8201;{escape(tz_label)}"

    ticker = _render_ticker(payload.get("stats") or [])
    sections = "\n".join(_render_section(section) for section in payload.get("sections") or [])

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
<main class="paper">
  <header class="masthead">
    <div class="kicker">{kicker}</div>
    <div class="dateline">
      <span class="ear">{date_human}</span>
      <span class="ear mid">Edition No.&#8201;{edition_no}</span>
      <span class="ear right">Generated {generated} by GAIA</span>
    </div>
  </header>

  <section class="lead">
    <h1 class="headline">{headline}</h1>
    {lede_html}
    <div class="byline">By GAIA &middot; The Autonomous Desk</div>
  </section>

  {ticker}

  <div class="sections">
{sections}
  </div>

  {caption_html}
</main>
</body>
</html>"""


def _format_date(iso: str) -> str:
    """Format an ISO ``YYYY-MM-DD`` date as ``Sunday, July 5, 2026``.

    An unparseable value is escaped and returned verbatim so the masthead never
    silently drops its dateline.
    """
    try:
        parsed = date.fromisoformat(iso)
    except ValueError:
        return escape(iso)
    return f"{parsed:%A, %B} {parsed.day}, {parsed.year}"


def _render_ticker(stats: list[dict]) -> str:
    """Render the stat row as a hairline-ruled ticker strip, or nothing."""
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
            f'<span class="s-value">{value}</span>'
            f'<span class="s-label">{label}{delta_html}</span>'
            f"</div>"
        )
    return f'<div class="ticker">{"".join(cells)}</div>'


def _render_section(section: dict) -> str:
    """Render one Roman-numeraled section, or nothing when it has no items."""
    items = section.get("items") or []
    if not items:
        return ""

    numeral = escape(str(section.get("numeral", "")))
    title = escape(str(section.get("title", "")))
    single = " single" if len(items) == 1 else ""
    body = "\n".join(_render_item(item) for item in items)

    return f"""    <section class="section">
      <div class="section-head">
        <span class="numeral">{numeral}</span>
        <span class="s-title">{title}</span>
      </div>
      <div class="items{single}">
{body}
      </div>
    </section>"""


def _render_item(item: dict) -> str:
    """Render a single section item with its catchline and artifact mark."""
    text = escape(str(item.get("text", "")))
    kind = str(item.get("kind", "note"))
    catchline, is_accent = _CATCHLINES.get(kind, ("", False))

    tag_html = ""
    if catchline:
        tone = "accent" if is_accent else "muted"
        tag_html = f'<span class="tag {tone}">{escape(catchline)}</span>'

    artifact_html = f'<span class="artifact">{_ARTIFACT_MARK}</span>' if item.get("link") else ""

    return f'        <p class="item">{tag_html}{text}{artifact_html}</p>'


_STYLE = f"""
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }}
body {{
  width: {_CANVAS_PX}px;
  background: {_PAPER};
  color: {_INK};
  font-family: {_SERIF};
}}
.paper {{ width: {_CANVAS_PX}px; padding: 74px 88px 60px; }}

/* --- Masthead ------------------------------------------------------------- */
.masthead {{ text-align: center; }}
.kicker {{
  font-family: {_DISPLAY};
  font-weight: 500;
  font-size: 66px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  line-height: 1;
  margin-bottom: 16px;
}}
.dateline {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 9px 2px;
  border-top: 3px solid {_INK};
  border-bottom: 1px solid {_INK};
  font-family: {_GROTESQUE};
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: {_INK};
}}
.dateline .ear {{ flex: 0 0 auto; white-space: nowrap; }}
.dateline .mid {{ flex: 1 1 auto; text-align: center; }}
.dateline .right {{ text-align: right; }}

/* --- Lead splash ---------------------------------------------------------- */
.lead {{ text-align: center; padding: 48px 0 30px; }}
.headline {{
  font-family: {_SERIF};
  font-weight: 600;
  font-size: 60px;
  line-height: 1.02;
  letter-spacing: -0.012em;
  max-width: 22ch;
  margin: 0 auto;
}}
.lede {{
  font-family: {_SERIF};
  font-style: italic;
  font-size: 23px;
  line-height: 1.42;
  color: #2f2b24;
  max-width: 60ch;
  margin: 20px auto 0;
}}
.byline {{
  margin-top: 22px;
  font-family: {_GROTESQUE};
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: {_MUTED};
}}

/* --- Stat ticker ---------------------------------------------------------- */
.ticker {{
  display: flex;
  border-top: 1px solid {_INK};
  border-bottom: 1px solid {_INK};
  margin-top: 6px;
}}
.stat {{
  flex: 1 1 0;
  text-align: center;
  padding: 15px 12px 14px;
}}
.stat + .stat {{ border-left: 1px solid {_HAIR}; }}
.s-value {{
  display: block;
  font-family: {_SERIF};
  font-weight: 600;
  font-size: 34px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}}
.s-label {{
  display: block;
  margin-top: 7px;
  font-family: {_GROTESQUE};
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: {_MUTED};
}}
.s-delta {{ color: {_ACCENT}; margin-left: 6px; }}

/* --- Sections ------------------------------------------------------------- */
.sections {{ margin-top: 42px; }}
.section + .section {{ margin-top: 36px; }}
.section-head {{
  display: flex;
  align-items: baseline;
  gap: 16px;
  padding-bottom: 8px;
  border-bottom: 2px solid {_INK};
}}
.section-head .numeral {{
  font-family: {_SERIF};
  font-weight: 700;
  font-size: 16px;
  letter-spacing: 0.06em;
}}
.section-head .s-title {{
  font-family: {_GROTESQUE};
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}}
.items {{
  columns: 2;
  column-gap: 56px;
  column-rule: 1px solid {_HAIR};
  padding-top: 22px;
}}
.items.single {{ columns: 1; column-rule: none; max-width: 62ch; }}
.item {{
  break-inside: avoid;
  font-family: {_SERIF};
  font-size: 18px;
  line-height: 1.5;
  padding-bottom: 20px;
}}
.item:last-child {{ padding-bottom: 0; }}
.tag {{
  font-family: {_GROTESQUE};
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  margin-right: 9px;
}}
.tag.accent {{ color: {_ACCENT}; }}
.tag.muted {{ color: {_MUTED}; }}
.artifact {{
  color: {_ACCENT};
  font-weight: 700;
  margin-left: 6px;
}}

/* --- Colophon ------------------------------------------------------------- */
.colophon {{
  margin-top: 48px;
  padding-top: 14px;
  border-top: 1px solid {_INK};
  text-align: center;
  font-family: {_GROTESQUE};
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: {_MUTED};
}}
"""
