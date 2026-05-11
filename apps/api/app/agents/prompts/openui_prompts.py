"""OpenUI prompt — paradigm-first, positional-call framing (openui.com style)."""

from app.models.chat_models import tool_fields

# Tools already rendered by TOOL_RENDERERS — LLM must NOT emit :::openui for these
OPENUI_SUPPRESSED_TOOLS: list[str] = list(tool_fields)

_suppression_list = "\n".join(f"  - {t}" for t in OPENUI_SUPPRESSED_TOOLS)

# ---------------------------------------------------------------------------
# The Paradigm (first — load-bearing)
# ---------------------------------------------------------------------------

OPENUI_PARADIGM = """
OpenUI Lang — the 6 rules:

  1. One statement per line: `name = Component(arg1, arg2, ...)`.
  2. Arguments are POSITIONAL, in the exact order shown in the example calls below.
     There are NO named parameters. `Stack(items=[...])` fails silently.
  3. Every openui block MUST start with `root = ...`. Without it, nothing renders.
  4. Forward references are allowed — you may reference a variable defined later.
  5. Omit trailing optional args. Use `null` ONLY to skip an optional middle arg.
  6. Strings use double quotes. Object keys are double-quoted strings.

SILENT-DROP WARNING — the renderer does NOT raise errors. These all vanish without warning:
  - Misspelled component name (case-sensitive; `callout` != `Callout`).
  - Wrong number of positional args.
  - Named parameters (`title="x"`) instead of positional.
  - Object keys without quotes: `{label: "x"}` is dropped; use `{"label": "x"}`.
  - A component that isn't in this library.

One-block starter (copy this shape):

  :::openui
  root = Stack([header, stats, chart])
  header = CardHeader("This Week", "updated 5m ago")
  stats = Row([s1, s2, s3])
  s1 = Stat("Users", 12450, null, "up", "+8.3%")
  s2 = Stat("Revenue", 48200, "$", "up", "+12%")
  s3 = Stat("Churn", 2.1, "%", "down", "-0.5%")
  chart = BarChart([{"m": "Jan", "r": 4200}, {"m": "Feb", "r": 5100}], "m", ["r"], "Monthly")
  :::
"""

# ---------------------------------------------------------------------------
# Component library — example calls, not TypeScript signatures
# ---------------------------------------------------------------------------

OPENUI_COMPONENT_LIBRARY_PROMPT = """
--- Layout Containers ---

Stack([children], direction, gap, align, justify, wrap)
  direction: "column" (default) | "row"
  gap: "xs" | "s" | "m" (default) | "l" | "xl"
  align: "start" | "center" | "end" | "stretch"
  justify: "start" | "center" | "end" | "between" | "around"
  wrap: true | false
  Use Stack as the root when combining 2+ components.
  Example: Stack([header, table])

Card([children], variant, direction, gap, align)
  variant: "card" (default, zinc-800 surface) | "sunk" (zinc-900) | "clear" (transparent, no border)
  direction: "column" (default) | "row"
  First child should usually be CardHeader.
  Example: Card([header, body])

Grid([children], columns)  columns 1-4 (default 2); responsive on mobile.
Row([children])            equal-width side-by-side (min 240px each).
Column([children])         vertical group for nesting inside Row/Grid.
Separator(label)           horizontal rule; `label` is an optional uppercase heading.

--- Primitives ---

TextContent(text, variant)
  variant: "body" (default) | "body-heavy" | "small" | "small-heavy" | "large" | "large-heavy" | "h1" | "h2" | "caption" | "muted"
  Example: TextContent("All systems operational", "small")

CardHeader(title, subtitle)
  Example: CardHeader("Project Atlas", "last updated 5m ago")

Tag(label, color, size)
  color: "default" | "primary" | "success" | "warning" | "danger"
  size: "sm" | "md"
  Example: Tag("Active", "success")

TagBlock(labels)  A row of plain-string tags.
  Example: TagBlock(["React", "TypeScript", "v2.1"])

Callout(variant, title, description?, width?, showIcon?)
  width: "sm"|"md"|"lg"|"full" (default "lg"). showIcon: boolean (default true).
  variant: "info" | "success" | "warning" | "error"
  Use for important inline notices — operation results, warnings, alerts.
  Example: Callout("warning", "Rate limit approaching", "85% of monthly quota used.")

Stat(label, value, unit?, trend?, trendLabel?, size?)
  size: "sm"|"md"|"lg" (default "md").
  trend: "up" | "down" | "neutral"
  Example: Stat("Revenue", 48200, "$", "up", "+12%")
  Wrap 2+ Stat in Row or Grid for dashboards.

Col(header, values, type, align)
  type: "string" | "number" | "badge" | "link"
  Child-only — NEVER emit Col standalone. See Table.

Table([Col, Col, ...], title, striped)
  Each Col owns one column's header + values array.
  Example:
    root = Table([c1, c2, c3], "Team")
    c1 = Col("Name", ["Alice", "Bob"])
    c2 = Col("PRs", [14, 8], "number", "end")
    c3 = Col("Status", ["Active", "Review"], "badge")

Button(label, action, variant, color, url)
  variant: "primary" | "secondary" | "flat" | "ghost"
  color: "default" | "primary" | "success" | "warning" | "danger"
  action: follow-up message sent when pressed (continue_conversation).
  url: if set, pressing opens the URL in a new tab (takes priority over action).
  Example action: Button("Accept", "Proceed with deployment", "primary", "success")
  Example link:   Button("View PR #648", null, "flat", null, "https://github.com/org/repo/pull/648")

Buttons([Button, Button, ...])  Horizontal row of Button — action groups.

Progress(value, max?, color?, label?, showValue?, width?)
  width: "sm"|"md"|"lg"|"full" (default "md").
  Example: Progress(72, 100, "primary", "Storage", true)
  For a list, compose multiple Progress inside a Card.

Avatar(name, initials, image, color, showName)
  Default: image-only chip. Pass showName=true to include the label.
  Example: Avatar("Aryan", "AR", "https://github.com/aryanranderiya.png")

Checkbox(label, checked, description)           Read-only.
Radio(label, value, description, selected)      Compose multiple inside Stack for a group.

--- Data Components ---

CopyableContent(content, mode, languageHint)
  mode: "block" (default, full panel) | "inline" (compact chip)
  Example: CopyableContent("/triage weekly", "inline")
  Example: CopyableContent("API_KEY=sk-abc123\\nDATABASE_URL=postgres://...", "block")

FileTree([items], title, variant)
  items: [{"path": "src/main.py", "type": "file", "size": "2.3 KB"}, ...]
  type per item: "file" | "dir" | "item". Paths are flat — nesting inferred from "/".
  variant: "file" (default, folder+file icons) | "generic" (tree of any hierarchy)
  Example: FileTree([{"path": "src/", "type": "dir"}, {"path": "src/main.py", "type": "file"}], "Project")

Accordion([items], title)
  items: [{"label": "Q1", "content": "A1"}, ...]
  Use for FAQs and collapsible grouped sections.

TabsBlock([tabs])
  Each tab: {"label": "Overview", "content": <component ref or string>}
  Tab content can be any component ref OR a plain string.

KbdRow(keys, description)
  Example: KbdRow(["Cmd", "K"], "Open command palette")
  Compose multiple KbdRow inside Card for a full shortcut reference.

--- Analytics ---

BarChart(data, xKey, yKeys, title, description, footer, colors, variant)
  variant: "default" (vertical) | "stacked" | "horizontal" | "multiple"
  yKeys is an array even for a single series: ["revenue"]
  Example: BarChart([{"m":"Jan","r":4200},{"m":"Feb","r":5100}], "m", ["r"], "Monthly Revenue")

LineChart(data, xKey, yKeys, title, description, footer, colors, showDots, showLabels)
  Same data shape as BarChart. showLabels=true for small datasets (<=8 points).

AreaChart(data, xKey, yKeys, title, description, footer, colors)
  Same shape as LineChart. Stacked automatically when yKeys has 2+ values.

PieChart(data, nameKey, valueKey, title, description, footer, mode)
  mode: "donut" (default, total in center) | "legend" (pie + legend) | "label" (labels on slices)
  Example: PieChart([{"src":"Organic","v":45},{"src":"Direct","v":25}], "src", "v", "Traffic")

ScatterChart(data, xKey, yKey, title?, description?, footer?, labelKey?)
  Use for correlation between two numeric variables.

RadarChart(data, angleKey, valueKeys, title, description, footer, colors)
  valueKeys is an array: ["alice", "bob"] — one axis per key.
  Keep angleKey values <=15 chars to avoid clipping.

GaugeChart(value, title?, min?, max?, unit?, thresholds?, variant?, secondValue?, secondLabel?, size?)
  size: "sm"|"md"|"lg" (default "md") — applies to outer container scale.
  variant: "gauge" (default, half-circle + thresholds) | "text" (radial + big number) | "stacked"
  thresholds: {"warning": 70, "danger": 90}
  Example: GaugeChart(73, "CPU", 0, 100, "%", {"warning": 70, "danger": 90})

--- Content ---

ImageGallery([{"src":"...","alt":"..."}, ...], columns?, gap?, aspectRatio?, maxWidth?)
  columns: 1-6 (override auto-layout). gap: "xs"|"sm"|"md"|"lg" (default "sm").
  aspectRatio: CSS string like "3/2" (default), "1/1", "16/9". maxWidth: "sm"|"md"|"lg"|"xl"|"full" (default "lg").
VideoBlock(src, title, poster)                        YouTube/Vimeo URLs auto-embed.
AudioPlayer(src, title, description)
MapBlock(lat, lng, label?, zoom?, markers?, routes?, arcs?, fitBounds?)
  Default: MapBlock(lat, lng, label, zoom) — single point with one marker. ALWAYS prefer this.
  markers, routes, arcs are 100% optional — only pass them when the data genuinely
  has multiple points, a path, or origin-destination connections. Do not invent extras.
  markers: [{"lat":..,"lng":..,"label?":"..","popup?":"..","tooltip?":".."}]
    When markers is provided, the default center marker is replaced — include the primary point as a marker too.
  routes:  [{"points":[{"lat":..,"lng":..}, ...], "color?":"#hex", "width?":3, "opacity?":0.85}]
    Use for an A→B path or trip with intermediate waypoints (>=2 points per route).
  arcs:    [{"from":{"lat":..,"lng":..},"to":{"lat":..,"lng":..},"id?":"..","label?":".."}]
    Use for origin-destination connections (flights, trade routes, network links).
  fitBounds: bool — auto-fits to all points when extras are provided. Defaults to true in that case.
NumberTicker(value, label?, unit?, duration?, size?)  Animated count-up. size: "sm"|"md"|"lg" (default "md").
Carousel([{"title":"...","body":"...","badge":"...","image":"...","actions":[...]}], autoPlay)

--- Timeline ---

Timeline([items], title?)
  items: [{"time": "10:30 AM", "title": "PR merged", "actor": "alice", "status": "success",
           "description": "feat: add auth", "links": [{"label":"View","url":"#"}],
           "actions": [{"label":"Reply","value":"Draft a reply"}]}, ...]
  status: "success" | "error" | "warning" | "neutral"
  Use for activity history, deployment logs, audit trails.

Steps([items], title?)
  items: [{"title": "Install deps", "description": "...", "status": "complete"|"active"|"pending"}, ...]
  Use for ordered instructions, onboarding, migration guides.

--- Code & Documents ---

CodeDiff(filename, oldCode, newCode, title?, diffStyle?, lineDiffType?, diffIndicators?, lang?, disableLineNumbers?, disableFileHeader?, expandUnchanged?)
  diffStyle: "unified" (default, stacked) | "split"
  lineDiffType: "word" (default) | "char" | "none"
  diffIndicators: "bars" (default) | "classic" (+/-) | "none"
  Example: CodeDiff("config.ts", "const x = 1", "const x: number = 1")

  UNIFIED DIFF CONVERSION (when the input is a +/- diff):
    oldCode = remove all + lines; strip - prefix from - lines; keep context as-is
    newCode = remove all - lines; strip + prefix from + lines; keep context as-is

TextDocument(title, body, fields)
  title: document type label — "Email Draft", "Blog Post", "Report", "Letter"
  body: HTML — use <h2>, <h3>, <p>, <ul>, <ol>, <strong>, <em>
  fields: [{"label":"To","value":"..."}, ...] — optional metadata rows above body
  Example: TextDocument("Email Draft", "<p>Hi Sarah,</p><p>Following up...</p>", [{"label":"To","value":"sarah@x.com"},{"label":"Subject","value":"Timeline"}])
"""

# ---------------------------------------------------------------------------
# Full instructions (what the LLM actually sees)
# ---------------------------------------------------------------------------

_escaped_paradigm = OPENUI_PARADIGM.replace("{", "{{").replace("}", "}}")
_escaped_component_library = OPENUI_COMPONENT_LIBRARY_PROMPT.replace("{", "{{").replace(
    "}", "}}"
)

OPENUI_INSTRUCTIONS = f"""
---OpenUI Lang (Rich UI Components)---

The following tool outputs are already rendered by dedicated GAIA cards. Do NOT emit :::openui for them:
{_suppression_list}

For ALL other tool outputs (MCP tools, integrations, anything not above) AND for your own
structured responses (lists, comparisons, stats, tables, timelines, code diffs, long documents),
render with :::openui fences. Do NOT fall back to markdown lists or tables when an OpenUI
component fits — markdown looks broken next to the rich cards.

{_escaped_paradigm}

{_escaped_component_library}

---
How to emit openui — fence the code and mix freely with text:

  Here are the results:

  :::openui
  root = GaugeChart(73, "CPU Usage", 0, 100, "%")
  :::

  Anything else you'd like to see?

Never put :::openui inside greetings, opinions, or plain conversational replies.

---
ABSOLUTE RULE — CODE DIFFS:
  Any before/after code comparison MUST use CodeDiff. Never show a diff in markdown ``` fences.
  If the input is a unified diff, reconstruct oldCode and newCode per the conversion rule above.

ABSOLUTE RULE — LONG PROSE:
  If your response has more than ~3 paragraphs of continuous prose — articles, blog posts,
  essays, reports, docs, emails, memos, summaries, how-tos, newsletters — it MUST be wrapped in
  a TextDocument. Never dump long text as raw markdown.
  Use rich HTML in the body: <h2>, <h3>, <p>, <ul>, <ol>, <strong>, <em>.
  Exception: when actually sending an email via the send_email tool (not drafting for review).

Quality notes:
  - Stat for a single KPI; wrap 2+ in Row or Grid.
  - Callout for inline notices; operation-result banners are just Callout (+ Card if needed).
  - Table for tabular data (use Col children). No DataTable — it doesn't exist.
  - Timeline for sequences of events with timestamps; Steps for ordered instructions.
  - Carousel for 2+ options the user should browse one at a time.
  - Prefer one well-chosen component over stacking many. Use Stack/Grid/Row/Column only when
    the content genuinely splits into sections.
"""
