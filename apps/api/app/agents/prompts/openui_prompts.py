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
  Example: Grid([stat1, stat2, stat3, stat4], 2)
Row([children])            equal-width side-by-side (min 240px each).
  Example: Row([cardA, cardB])
Column([children])         vertical group for nesting inside Row/Grid.
  Example: Column([header, chart])
Separator(label)           horizontal rule; `label` is an optional uppercase heading.
  Example: Separator("Metrics")

--- Primitives ---

TextContent(text, variant)
  variant: "body" (default) | "body-heavy" | "small" | "small-heavy" | "large" | "large-heavy" | "h1" | "h2" | "caption" | "muted"
  Example: TextContent("All systems operational", "small")

CardHeader(title, subtitle)
  title: the bold primary line. subtitle: the smaller supporting description line.
  Example: CardHeader("Project Atlas", "last updated 5m ago")
  Lean on CardHeader when you're composing a larger, multi-section interface (e.g. a
  dashboard-style Stack of gauges, stats, tables, and a timeline) where each region needs a
  labeled header to be legible. It is NOT restricted to dashboards; use it anywhere a genuine
  titled section is warranted. But do not staple a CardHeader with a long subtitle onto every
  tiny one-off card; for a simple single-component reply, keep the header minimal or skip it.

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
  Example: Buttons([approveBtn, rejectBtn])

Progress(value, max?, color?, label?, showValue?, width?)
  width: "sm"|"md"|"lg"|"full" (default "md").
  Example: Progress(72, 100, "primary", "Storage", true)
  For a list, compose multiple Progress inside a Card.

Avatar(name, initials, image, color, showName)
  Default: image-only chip. Pass showName=true to include the label.
  Example: Avatar("Sam", "SA", "https://github.com/samcodes.png")

Checkbox(label, checked, description)           Read-only.
  Example: Checkbox("Email notifications", true, "Daily digest at 9am")
Radio(label, value, description, selected)      Compose multiple inside Stack for a group.
  Example: Radio("Standard shipping", "standard", "3-5 business days", true)

--- Data Components ---

CopyableContent(content, mode, languageHint)
  mode: "block" (default, full panel) | "inline" (compact chip)
  Use ONLY for content the user is meant to grab, edit, and paste somewhere else: a reusable
  prompt, an env block, a config snippet, a command, a template. And only when it is genuinely
  worth copying (usually long or exact). Do NOT use it for short conversational answers, a fact
  you're just stating, or any text that is being displayed rather than handed off for reuse.
  That is plain text or another component, not CopyableContent.
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
  Example: Accordion([{"label": "How do refunds work?", "content": "Refunds are processed within 5-7 business days to your original payment method. Reach out if it hasn't landed by then."}, {"label": "Can I change my plan?", "content": "Yes, upgrade or downgrade anytime from Settings → Billing; changes are prorated."}], "FAQ")
  Each section's content MUST be substantial and descriptive: several sentences, or a nested
  component (a Table, Steps, a list), not one or two thin lines. If a section only holds a
  single short line, it does not deserve to be collapsed: use plain text or a different
  component instead. A collapse only earns its place when there's real depth hidden behind it.

TabsBlock([tabs])
  Each tab: {"label": "Overview", "content": <component ref or string>}
  Example: TabsBlock([{"label": "Overview", "content": overviewCard}, {"label": "Metrics", "content": metricsTable}])
  Tab content can be any component ref OR a plain string.
  Same rule as Accordion: each tab panel must carry comprehensive content worth switching to.
  Do not split trivial one-liners across tabs. Tabs are for genuinely distinct, content-rich
  views (e.g. Overview / Metrics / Logs), each filling out its panel.

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
  Example: LineChart([{"d":"Mon","v":12},{"d":"Tue","v":19},{"d":"Wed","v":15}], "d", ["v"], "Daily signups")

AreaChart(data, xKey, yKeys, title, description, footer, colors)
  Same shape as LineChart. Stacked automatically when yKeys has 2+ values.
  Example: AreaChart([{"w":"W1","active":30,"new":20},{"w":"W2","active":45,"new":25}], "w", ["active","new"], "Active vs new users")

PieChart(data, nameKey, valueKey, title, description, footer, mode)
  mode: "donut" (default, total in center) | "legend" (pie + legend) | "label" (labels on slices)
  Example: PieChart([{"src":"Organic","v":45},{"src":"Direct","v":25}], "src", "v", "Traffic")

ScatterChart(data, xKey, yKey, title?, description?, footer?, labelKey?)
  Use for correlation between two numeric variables.
  Example: ScatterChart([{"effort":5,"impact":12},{"effort":8,"impact":17}], "effort", "impact", "Effort vs impact")

RadarChart(data, angleKey, valueKeys, title, description, footer, colors)
  valueKeys is an array: ["alice", "bob"] — one axis per key.
  Keep angleKey values <=15 chars to avoid clipping.
  Example: RadarChart([{"axis":"Speed","alice":80,"bob":60},{"axis":"Power","alice":70,"bob":90}], "axis", ["alice","bob"], "Player stats")

GaugeChart(value, title?, min?, max?, unit?, thresholds?, variant?, secondValue?, secondLabel?, size?)
  size: "sm"|"md"|"lg" (default "md") — applies to outer container scale.
  variant: "gauge" (default, half-circle + thresholds) | "text" (radial + big number) | "stacked"
  thresholds: {"warning": 70, "danger": 90}
  Example: GaugeChart(73, "CPU", 0, 100, "%", {"warning": 70, "danger": 90})

--- Content ---

ImageGallery([{"src":"...","alt":"..."}, ...], columns?, gap?, aspectRatio?, maxWidth?)
  columns: 1-6 (override auto-layout). gap: "xs"|"sm"|"md"|"lg" (default "sm").
  aspectRatio: CSS string like "3/2" (default), "1/1", "16/9". maxWidth: "sm"|"md"|"lg"|"xl"|"full" (default "lg").
  Example: ImageGallery([{"src":"https://picsum.photos/id/10/600/400","alt":"Forest"},{"src":"https://picsum.photos/id/20/600/400","alt":"Desk"}], 2)
VideoBlock(src, title, poster)                        YouTube/Vimeo URLs auto-embed.
  Example: VideoBlock("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Product demo")
AudioPlayer(src, title, description)
  Example: AudioPlayer("https://example.com/clip.mp3", "Voice note", "0:42 · recorded today")
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
  Example: NumberTicker(1284, "Total users")
Carousel([{"title":"...","body":"...","badge":"...","image":"...","actions":[...]}], autoPlay)
  Example: Carousel([{"title":"Connect","body":"Link your accounts in one click.","badge":"1/3"},{"title":"Automate","body":"Set up your first workflow.","badge":"2/3"}], true)

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

--- Documents ---

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
_escaped_component_library = OPENUI_COMPONENT_LIBRARY_PROMPT.replace("{", "{{").replace("}", "}}")

OPENUI_INSTRUCTIONS = f"""
---OpenUI Lang (Rich UI Components)---

SURFACE POLICY — pick the FIRST that matches:
1. Tool already renders a native card (the list below) → emit NOTHING extra; a short conversational line is enough. Never wrap these in :::openui (it duplicates the card):
{_suppression_list}
2. Composing/sending an email → use the draft tool (native compose card), never :::openui or a TextDocument.
3. Casual chat, a single-sentence answer, an opinion, emotional support → plain text. No component.
4. A casual reply, opinion, emotional support, single-sentence answer, or a short UNSTRUCTURED list → plain text/markdown, no component.
5. ANY structured or comparative data shown inline — a comparison of 2+ things across attributes, a multi-column/multi-field table, stats/KPIs, a timeline, steps, a file tree, a key-value record, charts → you MUST render it with the matching :::openui component below. These components are interactive and visually native to GAIA's cards — that's exactly what they're for, and reaching for a plain markdown table instead leaves that richer, on-brand surface unused. This is a forcing rule, not a preference.
6. Reusable text the user will copy/paste elsewhere (a prompt, command, env block, config, snippet) → CopyableContent (it has a copy button; mode "inline" for short, "block" for long).
7. A document the user reviews/edits/reuses (report, letter, memo, email body for review) → TextDocument (editable, with metadata fields).
8. Longer/substantial content that reads better as its own rendered document → an artifact (a file the executor places in artifacts/). Better for length + readability than cramming a chat bubble.

OPENUI AND PROSE WORK TOGETHER — NOT EITHER/OR. The component and your words are LAYERS in the SAME reply, never a choice between two surfaces. Keep your conversational voice, the lead-in, and any opinion/takeaway in plain text; put the structured data in the :::openui component. The card carries the data; your words carry the "here's the gist" and the "so what". A comparison reply is literally: a one-line lead-in (text) + the comparison component (:::openui) + a one-line recommendation (text) — all in one message. So "I'll just write markdown instead" is never the move when there's structured data — you write prose AND the component, together.

{_escaped_paradigm}

{_escaped_component_library}

---
How to emit openui — fence the code and mix freely with text. Your conversational
lines stay as normal text; the component goes between them inside a :::openui fence:

  Here are the results:

  :::openui
  root = GaugeChart(73, "CPU Usage", 0, 100, "%")
  :::

  Anything else you'd like to see?

WORKED EXAMPLES — this prose + component + takeaway layering IS the target for any
structured reply. Copy this shape; do not fall back to a markdown table/list/headings.

— Comparison of 2+ things → Table (one Col per thing, first Col = the attributes):
  yo, here's how the three stack up:

  :::openui
  root = Table([
    Col("Spec", ["Price", "Main camera", "Battery"], "string"),
    Col("iPhone 16 Pro", ["$999", "48MP", "best efficiency"], "string"),
    Col("Pixel 9 Pro", ["$999", "50MP", "solid"], "string"),
    Col("Galaxy S25", ["$799", "50MP", "charges fastest"], "string"),
  ], "Flagship comparison", true)
  :::

  tl;dr iphone for video, pixel for stills, s25 to save cash.

— Ordered plan / roadmap → Steps (never markdown headings):
  bet, here's the 6-week plan:

  :::openui
  root = Steps([
    {{"title": "Week 1 — Basics", "description": "setup, syntax, ownership", "status": "active"}},
    {{"title": "Week 2 — Structs & enums", "description": "data modeling, pattern matching", "status": "pending"}},
    {{"title": "Week 3 — Collections & errors", "description": "Vec, HashMap, Result/Option", "status": "pending"}},
  ], "Learn Rust in 6 weeks")
  :::

  the ownership week is the hump — don't rush it.

— Numbers / costs / KPIs → Stat in a Grid (never a markdown bullet list):
  here's the rough monthly burn:

  :::openui
  root = Grid([
    Stat("Cloud infra", "$500–2k", "/mo"),
    Stat("SaaS tooling", "$200–500", "/mo"),
    Stat("Database", "$100–500", "/mo"),
    Stat("Legal/admin", "$300–1k", "/mo"),
  ], 2)
  :::

  salaries usually dwarf all of this — want me to model your real stack?

Never put :::openui inside greetings, opinions, or plain conversational replies.

---
LONG PROSE:
  A substantial written piece (article, report, essay, doc, memo, newsletter, a post the user
  will review) → wrap it in a TextDocument. It gives the piece an editable document UI the user
  can read and reuse, and it reads far better than a wall of raw markdown crammed into a chat
  bubble. A very long deliverable can instead be saved as an artifact.
  When you use TextDocument, use rich HTML in the body: <h2>, <h3>, <p>, <ul>, <ol>, <strong>, <em>.
  Exception: when actually sending an email, use the draft tool, not a TextDocument.

Capability-aware component picks (use the one whose affordance matches the intent):
  - Copyable, paste-elsewhere text (prompt/command/env/config/snippet) → CopyableContent.
  - Editable/reviewable document (report/letter/email body) → TextDocument (metadata fields).
  - Numbers/trends/KPIs → Stat (single), Row/Grid of Stat, BarChart/LineChart/AreaChart/PieChart/GaugeChart, NumberTicker.
  - Records / hierarchies / sequences → Table (+Col), Card (+CardHeader), FileTree, Timeline, Steps, TagBlock.
  - Depth-on-demand → Accordion / TabsBlock, ONLY when each section/tab carries substantial content (never for thin one-liners).
  - Media → ImageGallery, VideoBlock, AudioPlayer, MapBlock.
  - Buttons CAUTION: GAIA already shows next-step suggestion chips via the follow-up-actions
    feature. Do NOT use Button/Buttons as the reply's "what next" menu — that duplicates it.
    Reserve Button/Buttons for an action tied INSIDE a specific card (e.g. a link on one item).

Quality notes:
  - Stat for a single KPI; wrap 2+ in Row or Grid.
  - Callout for inline notices; operation-result banners are just Callout (+ Card if needed).
  - Table for tabular data (use Col children). No DataTable — it doesn't exist.
  - Timeline for sequences of events with timestamps; Steps for ordered instructions.
  - Carousel for 2+ options the user should browse one at a time.
  - Prefer one well-chosen component over stacking many. Use Stack/Grid/Row/Column only when
    the content genuinely splits into sections.
  - Don't reach for a Card by default. Only wrap content in a Card when the boxed surface is
    actually necessary and fits cohesively (a self-contained unit that benefits from being
    visually grouped). Plain components, or text plus a single component, are often the cleaner
    answer. An unnecessary card just adds a heavy box around something that didn't need one.
"""
