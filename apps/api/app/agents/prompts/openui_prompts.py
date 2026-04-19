"""OpenUI prompt with suppression list and generic component library docs."""

from app.models.chat_models import tool_fields

# Tools already rendered by TOOL_RENDERERS — LLM must NOT emit :::openui for these
OPENUI_SUPPRESSED_TOOLS: list[str] = list(tool_fields)

_suppression_list = "\n".join(f"  - {t}" for t in OPENUI_SUPPRESSED_TOOLS)

OPENUI_COMPONENT_LIBRARY_PROMPT = """
Available Generic Components (strict typed signatures):

TYPE KEY: string = "text", number = 42, boolean = true/false, string[] = ["a", "b"] (ALWAYS an array, never a bare string)

--- Layout & Data ---

DataCard(title: string, fields: {label: string, value: string}[])
  Use for: single record details, config values, profile data

ResultList(items: {title: string, subtitle?: string, body?: string, url?: string, badge?: string}[], title?: string)
  Use for: lists of results, search hits, records

ComparisonTable(leftLabel: string, rightLabel: string, rows: {label: string, left: string, right: string, highlight?: boolean}[], title?: string)
  Use for: A vs B comparisons

StatusCard(title: string, status: "success"|"error"|"warning"|"info"|"pending", message?: string, detail?: string)
  Use for: operation results, confirmations, errors

ActionCard(title: string, description?: string, actions?: {label: string, type: "continue_conversation", value: string}[])
  Use for: next-step prompts, follow-up suggestions

TagGroup(tags: {label: string, color?: "default"|"primary"|"success"|"warning"|"danger"}[], title?: string)
  Use for: keyword sets, categories, tech stacks

FileTree(items: {path: string, type: "file"|"dir", size?: string}[], title?: string)
  Use for: directory listings, filesystem output

Accordion(items: {label: string, content: string}[], title?: string)
  Use for: FAQs, grouped results, collapsible sections

TabsBlock(tabs: {label: string, content: string}[])
  Use for: multi-category output, results split by type

ProgressList(items: {label: string, value: number, max?: number, color?: "default"|"primary"|"success"|"warning"|"danger"}[], title?: string)
  Use for: task completion, resource usage, batch status

SelectableList(options: {label: string, description?: string, value: string, badge?: string}[], title?: string, description?: string)
  Use for: structured choices

AvatarList(items: {name: string, role?: string, description?: string, initials?: string, color?: string}[], title?: string)
  Use for: team rosters, assignees, contributors

KbdBlock(shortcuts: {keys: string[], description: string}[], title?: string)
  Use for: keyboard shortcut references

--- Analytics ---

StatRow(title: string, value: string|number, unit?: string, trend?: "up"|"down"|"neutral", trendLabel?: string)
  Use for: single KPI with optional trend. Wrap 2+ in Row() for side-by-side.

BarChart(data: {[key]: string|number}[], xKey: string, yKeys: string[], title?: string, colors?: string[], variant?: string)
  yKeys MUST be an array: ["revenue"] for single series, ["revenue", "cost"] for multi-series
  variant: "default" (vertical bars), "stacked" (stacked bars — parts of a whole), "horizontal" (horizontal — ranked lists or long names), "multiple" (side-by-side with legend always shown — direct group comparison)
  Use for: comparisons, rankings, distributions.

LineChart(data: {[key]: string|number}[], xKey: string, yKeys: string[], title?: string, colors?: string[], showDots?: boolean, showLabels?: boolean)
  yKeys MUST be an array: ["requests", "errors"] — never a bare string
  showDots: true (default) — show dots on data points
  showLabels: false (default) — show value labels above each point; use when data has ≤8 points and labels add clarity
  Use for: trends over time, multi-series comparisons

AreaChart(data: {[key]: string|number}[], xKey: string, yKeys: string[], title?: string, colors?: string[])
  yKeys MUST be an array: ["users"] — even for a single series, wrap in []
  Use for: cumulative values, volume over time

PieChart(data: {[key]: string|number}[], nameKey: string, valueKey: string, title?: string, mode?: string)
  mode: "donut" (default) — donut with center showing total + valueKey label; best for showing a total with breakdown
  mode: "legend" — full pie with legend below; best when label names must always be visible
  Use for: proportions, composition breakdowns

ScatterChart(data: {[key]: string|number}[], xKey: string, yKey: string, title?: string, labelKey?: string)
  Use for: correlation between two numeric variables

RadarChart(data: {[key]: string|number}[], angleKey: string, valueKeys: string[], title?: string, colors?: string[])
  valueKeys MUST be an array: ["alice", "bob"] — never a bare string
  Axes automatically show values — ensure angleKey values are short labels (≤15 chars) to avoid clipping
  Use for: multi-axis comparisons, skill matrices, benchmark scores

GaugeChart(value: number, title?: string, min?: number, max?: number, unit?: string, thresholds?: {warning: number, danger: number}, variant?: string, secondValue?: number, secondLabel?: string)
  variant: "gauge" (default) — half-circle gauge with color thresholds
  variant: "text" — full radial progress ring with large center value; use for a single metric without min/max context
  variant: "stacked" — two-segment half-circle showing two values; use secondValue (number) and secondLabel (string) props; best for breakdown of a total
  Use for: CPU%, disk, scores, health indicators

--- Content ---

ImageBlock(src: string, alt?: string, caption?: string)
  Use for: single image results, previews, screenshots

ImageGallery(images: {src: string, alt?: string, caption?: string}[])
  Use for: photo sets, image search results

VideoBlock(src: string, title?: string, poster?: string)
  src: YouTube/Vimeo URL (auto-embeds) or direct video URL

AudioPlayer(src: string, title?: string, description?: string)
  Use for: podcast clips, voice memos, TTS output

MapBlock(lat: number, lng: number, label?: string, zoom?: number)
  Use for: location results, addresses, venues

CalendarMini(markedDates: {date: string, label?: string, color?: "success"|"warning"|"danger"|"default"}[], title?: string, mode?: "single"|"range")
  Use for: availability views, event schedules, booking slots

NumberTicker(value: number, label?: string, unit?: string, duration?: number)
  Use for: single stat with count-up animation

Carousel(items: {title: string, body?: string, image?: string, badge?: string, actions?: {label: string, value: string}[]}[], autoPlay?: boolean)
  Use for: recommendations, product options — one card at a time

TreeView(nodes: {id: string, label: string, description?: string, children?: node[]}[], title?: string)
  Use for: org charts, nested configs, category hierarchies

--- Timeline & Notifications ---

Timeline(items: {time: string, title: string, description?: string, status?: "success"|"error"|"warning"|"neutral"}[], title?: string)
  Use for: git log, activity history, deployment events, audit trails

AlertBanner(variant: "info"|"success"|"warning"|"error", title: string, description?: string)
  Use for: important notices, inline warnings

Steps(items: {title: string, description?: string, status?: "complete"|"active"|"pending"}[], title?: string)
  Use for: ordered instructions, onboarding, migration guides

--- Code ---

CodeDiff(filename: string, oldCode: string, newCode: string, title?: string, diffStyle?: "unified"|"split", lineDiffType?: "word"|"char"|"none", diffIndicators?: "bars"|"classic"|"none", lang?: string, disableLineNumbers?: boolean, disableFileHeader?: boolean, expandUnchanged?: boolean)
  diffStyle: "unified" (default, stacked) or "split" (side-by-side columns)
  lineDiffType: "word" (default, highlight changed words), "char" (individual chars), "none" (no inline diff)
  diffIndicators: "bars" (default, colored side bar), "classic" (+/- prefix), "none"
  lang: force syntax language e.g. "typescript", "python" — auto-detected from filename by default
  disableLineNumbers: true hides line number gutter
  disableFileHeader: true hides the filename header bar
  expandUnchanged: true shows all context lines with no collapsed hunks
  Use for: before/after code changes, patch previews — never use raw markdown code blocks for diffs
  HOW TO CONVERT A UNIFIED DIFF: When you see a diff with +/- lines, reconstruct the two complete files:
    oldCode = all lines WITHOUT a + prefix (keep lines with - prefix but remove the -; keep unchanged lines as-is)
    newCode = all lines WITHOUT a - prefix (keep lines with + prefix but remove the +; keep unchanged lines as-is)
    Then pass them to CodeDiff. The component computes and renders the diff itself.

--- Documents ---

TextDocument(title: string, body: string, fields?: {label: string, value: string}[])
  title: document type label shown at top (e.g. "Email Draft", "Blog Post", "Article", "Report", "Letter", "Essay")
  body: initial rich text content (plain text or HTML — use <p>, <h2>, <h3>, <ul>, <ol>, <strong>, <em> for structure)
  fields: optional metadata rows shown above the body (e.g. Author, Date, Subject, To, From, Word Count)
  Use for: ANY long-form text output — articles, blog posts, essays, reports, documentation, letters, memos, email drafts, creative writing, summaries longer than ~3 paragraphs, READMEs, guides, how-tos, listicle articles, op-eds, newsletters, technical write-ups, and any content the user will read, review, or copy
  MANDATORY: If your response contains more than ~3 paragraphs of prose, it MUST go in a TextDocument. Never dump long text as raw markdown.
  Do NOT use when: actually sending an email (use the send_email tool directly), or when the user asked to send without reviewing

--- Layout ---

Row(items: component[])
  Use for: placing components side-by-side (equal width, 16:9 fixed height per cell).
  ✓ Good: multiple StatRows, GaugeCharts, BarCharts, LineCharts, StatusCards, DataCards (2–3 items max)
  ✗ Never use for: Timeline, Steps, Accordion, ResultList, TextDocument, AlertBanner — variable-height
    components look broken (empty void or clipped) inside a fixed-height cell
  ✗ Never put more than 3 items — cells become too narrow to read
  ✗ Never mix component types in one Row (e.g. a chart next to a DataCard) — mismatched fill
  ✗ Never wrap a single component — just emit it directly

Stack(items: component[])
  Use for: placing components vertically. Nest Row inside Stack for mixed layouts.
  ✓ Good: Stack([row, chart]) where row = Row([s1, s2, s3])
  ✗ Never wrap a single component in Stack — pointless
  ✗ Never nest Row inside Row — the fixed-height cells do not compose
"""

_escaped_component_library = OPENUI_COMPONENT_LIBRARY_PROMPT.replace("{", "{{").replace(
    "}", "}}"
)

OPENUI_INSTRUCTIONS = f"""
---OpenUI Lang (Rich UI Components)---

The following tool outputs are rendered automatically by the frontend — do NOT emit :::openui for them:
{_suppression_list}

For ALL other tool outputs (MCP tools, integrations, anything not in the list above), render data
using :::openui fences with the components below.

{_escaped_component_library}

---
OpenUI Lang — strict syntax rules (violations cause silent blank rendering):

  RULE 1 — One statement per line: variable = Expression
  RULE 2 — First line MUST be: root = ComponentName(arg1, arg2, ...)
  RULE 3 — Arguments are POSITIONAL in the exact order listed in the signature above.
           ✗ WRONG:  root = DataCard(title="Server", fields=[...])   ← named args fail silently
           ✓ CORRECT: root = DataCard("Server", [...])
  RULE 4 — Component names are case-sensitive and must match exactly.
           ✗ WRONG:  root = data_card(...)  or  root = Datacard(...)
           ✓ CORRECT: root = DataCard(...)
  RULE 5 — Use null ONLY to skip an optional argument in a middle position.
           Trailing optional arguments can simply be omitted.
  RULE 6 — Multi-component layouts:
           Stack([c1, c2]) — vertical (top to bottom). Use for different component types.
           Row([c1, c2]) — horizontal (side by side, equal width). Use for same-type components like StatRows, StatusCards, DataCards.
           You can nest them: Stack([row, chart]) where row = Row([s1, s2]).
           Forward references are allowed.
  RULE 7 — Strings must use double quotes. No single quotes.
  RULE 8 — Array items are objects with curly braces. Each key is a double-quoted string.
           ✗ WRONG:  [{{{{label: "CPU"}}}}]          ← unquoted keys break the parser
           ✓ CORRECT: [{{{{"label": "CPU"}}}}]

---
Complete examples for every component (copy these patterns exactly):

--- Layout & Data ---

DataCard — single record with key-value pairs:
  :::openui
  root = DataCard("Server Info", [{{{{"label": "Host", "value": "prod-01"}}}}, {{{{"label": "IP", "value": "10.0.1.5"}}}}, {{{{"label": "OS", "value": "Ubuntu 24.04"}}}}])
  :::

ResultList — list of results with optional badges and URLs:
  :::openui
  root = ResultList([{{{{"title": "Getting Started Guide", "subtitle": "docs.example.com", "badge": "Popular"}}}}, {{{{"title": "API Reference", "body": "Full REST API documentation", "url": "https://docs.example.com/api"}}}}], "Search Results")
  :::

ComparisonTable — side-by-side comparison of two options:
  :::openui
  root = ComparisonTable("PostgreSQL", "MongoDB", [{{{{"label": "Type", "left": "Relational", "right": "Document"}}}}, {{{{"label": "Schema", "left": "Fixed", "right": "Flexible", "highlight": true}}}}, {{{{"label": "Joins", "left": "Native", "right": "Manual"}}}}], "Database Comparison")
  :::

StatusCard — operation result with status indicator:
  :::openui
  root = StatusCard("Deployment Complete", "success", "All 3 services deployed", "Region: us-east-1")
  :::

  :::openui
  root = StatusCard("Build Failed", "error", "TypeScript compilation error in src/index.ts")
  :::

ActionCard — follow-up suggestions the user can click:
  :::openui
  root = ActionCard("What would you like to do next?", "Here are some options:", [{{{{"label": "Show logs", "type": "continue_conversation", "value": "Show me the deployment logs"}}}}, {{{{"label": "Run tests", "type": "continue_conversation", "value": "Run the test suite"}}}}])
  :::

TagGroup — set of labels or categories as chips:
  :::openui
  root = TagGroup([{{{{"label": "Python", "color": "primary"}}}}, {{{{"label": "FastAPI", "color": "success"}}}}, {{{{"label": "Deprecated", "color": "danger"}}}}, {{{{"label": "v2.1"}}}}], "Tech Stack")
  :::

FileTree — directory listing:
  :::openui
  root = FileTree([{{{{"path": "src/", "type": "dir"}}}}, {{{{"path": "src/main.py", "type": "file", "size": "2.3 KB"}}}}, {{{{"path": "src/utils.py", "type": "file", "size": "800 B"}}}}, {{{{"path": "tests/", "type": "dir"}}}}], "Project Structure")
  :::

Accordion — collapsible sections:
  :::openui
  root = Accordion([{{{{"label": "What is GAIA?", "content": "GAIA is a proactive personal AI assistant."}}}}, {{{{"label": "How do I get started?", "content": "Run pnpm install and then nx dev web."}}}}], "FAQ")
  :::

TabsBlock — content split by category:
  :::openui
  root = TabsBlock([{{{{"label": "Frontend", "content": "Next.js 16 with React 19 and TailwindCSS"}}}}, {{{{"label": "Backend", "content": "FastAPI with LangGraph agents and PostgreSQL"}}}}, {{{{"label": "Infra", "content": "Docker Compose with Redis, MongoDB, ChromaDB"}}}}])
  :::

ProgressList — progress bars for tasks or resources:
  :::openui
  root = ProgressList([{{{{"label": "CPU Usage", "value": 73, "max": 100, "color": "warning"}}}}, {{{{"label": "Memory", "value": 4200, "max": 8192, "color": "success"}}}}, {{{{"label": "Disk", "value": 92, "max": 100, "color": "danger"}}}}], "System Resources")
  :::

SelectableList — structured choices:
  :::openui
  root = SelectableList([{{{{"label": "Production", "description": "US East, 3 replicas", "value": "prod", "badge": "Active"}}}}, {{{{"label": "Staging", "description": "EU West, 1 replica", "value": "staging"}}}}], "Select Environment")
  :::

AvatarList — people or team members:
  :::openui
  root = AvatarList([{{{{"name": "Alice Chen", "role": "Lead Engineer", "initials": "AC"}}}}, {{{{"name": "Bob Kim", "role": "Designer", "initials": "BK"}}}}], "Team")
  :::

KbdBlock — keyboard shortcuts or CLI flags:
  :::openui
  root = KbdBlock([{{{{"keys": ["Cmd", "K"], "description": "Open command palette"}}}}, {{{{"keys": ["Cmd", "Shift", "P"], "description": "Open settings"}}}}], "Shortcuts")
  :::

--- Analytics ---

StatRow — single KPI with trend (use Row for multiple):
  :::openui
  root = Row([s1, s2, s3])
  s1 = StatRow("Users", 12450, "users", "up", "+8.3%")
  s2 = StatRow("Revenue", 48200, "$", "up", "+12%")
  s3 = StatRow("Churn", 2.1, "%", "down", "-0.5%")
  :::

BarChart — single series (default vertical):
  :::openui
  root = BarChart([{{{{"month": "Jan", "revenue": 4200}}}}, {{{{"month": "Feb", "revenue": 5100}}}}, {{{{"month": "Mar", "revenue": 4800}}}}], "month", ["revenue"], "Monthly Revenue")
  :::

BarChart — stacked (composition, parts of a whole):
  :::openui
  root = BarChart([{{{{"month": "Jan", "mobile": 2100, "desktop": 2100}}}}, {{{{"month": "Feb", "mobile": 2600, "desktop": 2500}}}}], "month", ["mobile", "desktop"], "Traffic by Platform", null, "stacked")
  :::

BarChart — horizontal (ranked list or long category names):
  :::openui
  root = BarChart([{{{{"lang": "Python", "stars": 52000}}}}, {{{{"lang": "TypeScript", "stars": 48000}}}}, {{{{"lang": "Rust", "stars": 31000}}}}], "lang", ["stars"], "Top Languages", null, "horizontal")
  :::

BarChart — multiple (side-by-side with legend, direct group comparison):
  :::openui
  root = BarChart([{{{{"month": "Jan", "revenue": 4200, "cost": 2800}}}}, {{{{"month": "Feb", "revenue": 5100, "cost": 3100}}}}, {{{{"month": "Mar", "revenue": 4800, "cost": 2600}}}}], "month", ["revenue", "cost"], "Revenue vs Cost", ["#00bbff", "#f472b6"], "multiple")
  :::

LineChart — trends over time (supports multiple series via yKeys array):
  :::openui
  root = LineChart([{{{{"date": "Mon", "requests": 120, "errors": 3}}}}, {{{{"date": "Tue", "requests": 145, "errors": 5}}}}, {{{{"date": "Wed", "requests": 98, "errors": 1}}}}], "date", ["requests", "errors"], "Traffic This Week")
  :::

LineChart — with value labels (few data points, labels add clarity):
  :::openui
  root = LineChart([{{{{"q": "Q1", "sales": 42}}}}, {{{{"q": "Q2", "sales": 58}}}}, {{{{"q": "Q3", "sales": 51}}}}, {{{{"q": "Q4", "sales": 67}}}}], "q", ["sales"], "Quarterly Sales", null, true, true)
  :::

AreaChart — same as LineChart but filled area style:
  :::openui
  root = AreaChart([{{{{"month": "Jan", "users": 800}}}}, {{{{"month": "Feb", "users": 1200}}}}, {{{{"month": "Mar", "users": 1900}}}}], "month", ["users"], "User Growth")
  :::

PieChart — donut (default, total + breakdown in center):
  :::openui
  root = PieChart([{{{{"browser": "Chrome", "share": 65}}}}, {{{{"browser": "Firefox", "share": 18}}}}, {{{{"browser": "Safari", "share": 12}}}}, {{{{"browser": "Other", "share": 5}}}}], "browser", "share", "Browser Usage")
  :::

PieChart — legend mode (full pie, labels always visible):
  :::openui
  root = PieChart([{{{{"region": "APAC", "revenue": 420}}}}, {{{{"region": "EMEA", "revenue": 310}}}}, {{{{"region": "AMER", "revenue": 580}}}}], "region", "revenue", "Revenue by Region", "legend")
  :::

ScatterChart — correlation between two variables:
  :::openui
  root = ScatterChart([{{{{"hours": 2, "score": 65}}}}, {{{{"hours": 5, "score": 80}}}}, {{{{"hours": 8, "score": 92}}}}], "hours", "score", "Study Hours vs Score")
  :::

RadarChart — multi-axis comparison:
  :::openui
  root = RadarChart([{{{{"skill": "Frontend", "alice": 90, "bob": 70}}}}, {{{{"skill": "Backend", "alice": 75, "bob": 95}}}}, {{{{"skill": "DevOps", "alice": 60, "bob": 85}}}}], "skill", ["alice", "bob"], "Skill Matrix")
  :::

GaugeChart — half-circle gauge with color thresholds (default):
  :::openui
  root = GaugeChart(73, "CPU Usage", 0, 100, "%", {{{{"warning": 70, "danger": 90}}}})
  :::

GaugeChart — radial progress ring with large center value (no min/max context):
  :::openui
  root = GaugeChart(87, "Completion", null, null, "%", null, "text")
  :::

GaugeChart — stacked two-segment showing breakdown of a total:
  :::openui
  root = GaugeChart(60, "Storage", 0, 100, "GB", null, "stacked", 25, "Backups")
  :::

--- Content ---

ImageBlock — single image:
  :::openui
  root = ImageBlock("https://example.com/photo.jpg", "Sunset over the ocean", "Photo by Jane Doe")
  :::

ImageGallery — multiple images:
  :::openui
  root = ImageGallery([{{{{"src": "https://example.com/1.jpg", "alt": "Photo 1"}}}}, {{{{"src": "https://example.com/2.jpg", "alt": "Photo 2", "caption": "Award winner"}}}}])
  :::

VideoBlock — YouTube/Vimeo URL or direct video:
  :::openui
  root = VideoBlock("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Tutorial Video")
  :::

AudioPlayer — audio file or podcast:
  :::openui
  root = AudioPlayer("https://example.com/episode.mp3", "Episode 42", "Weekly tech roundup")
  :::

MapBlock — location with coordinates:
  :::openui
  root = MapBlock(40.7128, -74.006, "New York City", 12)
  :::

CalendarMini — marked dates on a calendar:
  :::openui
  root = CalendarMini([{{{{"date": "2025-03-15", "label": "Sprint Start", "color": "success"}}}}, {{{{"date": "2025-03-28", "label": "Demo Day", "color": "warning"}}}}], "Sprint Calendar")
  :::

NumberTicker — animated count-up for a single stat:
  :::openui
  root = NumberTicker(99.7, "Uptime", "%")
  :::

Carousel — swipeable cards (one at a time):
  :::openui
  root = Carousel([{{{{"title": "Pro Plan", "body": "Unlimited projects", "badge": "Popular", "actions": [{{{{"label": "Select", "value": "Choose Pro Plan"}}}}]}}}}, {{{{"title": "Free Plan", "body": "Up to 3 projects"}}}}])
  :::

TreeView — nested hierarchy:
  :::openui
  root = TreeView([{{{{"id": "1", "label": "Engineering", "children": [{{{{"id": "1a", "label": "Frontend"}}}}, {{{{"id": "1b", "label": "Backend"}}}}]}}}}, {{{{"id": "2", "label": "Design"}}}}], "Org Chart")
  :::

--- Timeline & Notifications ---

Timeline — sequence of events:
  :::openui
  root = Timeline([{{{{"time": "10:30 AM", "title": "PR Merged", "description": "feat: add user auth", "status": "success"}}}}, {{{{"time": "10:45 AM", "title": "Deploy Started", "status": "neutral"}}}}, {{{{"time": "11:02 AM", "title": "Deploy Failed", "description": "Health check timeout", "status": "error"}}}}], "Deployment Log")
  :::

AlertBanner — inline notice (lighter than StatusCard):
  :::openui
  root = AlertBanner("warning", "Rate Limit Approaching", "You have used 85% of your API quota this month.")
  :::

Steps — ordered instructions:
  :::openui
  root = Steps([{{{{"title": "Install dependencies", "description": "Run pnpm install", "status": "complete"}}}}, {{{{"title": "Configure env", "description": "Copy .env.example to .env", "status": "active"}}}}, {{{{"title": "Start dev server", "description": "Run nx dev web", "status": "pending"}}}}], "Setup Guide")
  :::

--- Documents ---

TextDocument — email draft with metadata fields:
  :::openui
  root = TextDocument("Email Draft", "<p>Hi Sarah,</p><p>Just following up on our conversation from last week. I wanted to confirm that the timeline works for your team.</p><p>Looking forward to hearing from you.</p><p>Best,<br>Alex</p>", [{{{{"label": "To", "value": "sarah@example.com"}}}}, {{{{"label": "Subject", "value": "Timeline Confirmation"}}}}])
  :::

TextDocument — article or blog post (no fields needed):
  :::openui
  root = TextDocument("Blog Post", "<h2>Why TypeScript Wins in 2025</h2><p>TypeScript has become the default choice for serious JavaScript projects. Here is why that trend is only accelerating.</p><h3>Type Safety at Scale</h3><p>As codebases grow, untyped JavaScript becomes a liability. TypeScript catches entire classes of bugs at compile time that would otherwise surface in production.</p><h3>Ecosystem Adoption</h3><p>Every major framework — React, Vue, Angular, Next.js — ships first-class TypeScript support. The ecosystem has spoken.</p>")
  :::

TextDocument — report or summary with metadata:
  :::openui
  root = TextDocument("Weekly Report", "<h2>Summary</h2><p>This week the team shipped the new authentication flow and resolved 14 open bugs. Performance benchmarks improved by 18% following the Redis caching rollout.</p><h2>Highlights</h2><ul><li>Auth v2 deployed to production</li><li>14 bugs resolved</li><li>Redis caching live</li></ul><h2>Next Week</h2><p>Focus shifts to the mobile onboarding redesign and API rate limiting.</p>", [{{{{"label": "Author", "value": "Aryan"}}}}, {{{{"label": "Period", "value": "Apr 7 – Apr 12, 2025"}}}}])
  :::

--- Code ---

CodeDiff — unified (default), no title:
  :::openui
  root = CodeDiff("src/config.ts", "export const API_URL = 'http://localhost:3000';", "export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:3000';")
  :::

CodeDiff — split view with title:
  :::openui
  root = CodeDiff("auth.py", "def login(user, pwd):\n    return check(user, pwd)", "def login(user: str, pwd: str) -> bool:\n    return check(user, pwd)", "Login Refactor", "split")
  :::

CodeDiff — char-level diff, no header, expanded context:
  :::openui
  root = CodeDiff("utils.ts", "const x = foo(a, b)", "const x = foo(a, b, c)", null, "unified", "char", "bars", null, false, true, true)
  :::

--- Multi-Component Layout ---

Row — place any components side-by-side in equal-width columns:
  :::openui
  root = Row([s1, s2, s3])
  s1 = StatRow("CPU", 73, "%", "up", "+5%")
  s2 = StatRow("Memory", 4.2, "GB")
  s3 = StatRow("Disk", 120, "GB")
  :::

  Row cells are fixed 16:9 height — only use components that look good at a fixed height.
  ✓ StatRow, GaugeChart, BarChart, LineChart, StatusCard, DataCard (2–3 items max)
  ✗ Timeline, Steps, Accordion, ResultList, TextDocument, AlertBanner — these have variable height

Stack — combine multiple components vertically:
  :::openui
  root = Stack([stats, chart])
  stats = Row([s1, s2, s3])
  s1 = StatRow("Users", 12450, null, "up", "+8%")
  s2 = StatRow("Revenue", 48200, "$", "up", "+12%")
  s3 = StatRow("Churn", 2.1, "%", "down", "-0.5%")
  chart = BarChart([{{{{"month": "Jan", "revenue": 4200}}}}, {{{{"month": "Feb", "revenue": 5100}}}}], "month", ["revenue"], "Monthly Revenue")
  :::

  Use Stack to combine a Row of stats with a chart below — this is the correct pattern.
  ✗ Never wrap a single component in Stack — just emit it directly
  ✗ Never nest Row inside Row — fixed-height cells do not compose

---

How to emit an OpenUI block — surround the code in fences, mix freely with text:

  Some text before.

  :::openui
  root = GaugeChart(73, "CPU Usage", 0, 100)
  :::

  Some text after.

Skipping an optional middle argument with null:

  :::openui
  root = GaugeChart(73, null, 0, 100)
  :::

Do NOT use :::openui for greetings, opinions, or plain conversational responses.

IMPORTANT: You MUST use :::openui whenever your response contains structured data — lists, comparisons, stats, steps, timelines, key-value pairs, status results, or anything with repeated structure. Never fall back to markdown lists, tables, or bullet points when an OpenUI component exists for that data shape. The frontend renders OpenUI as rich interactive cards. Plain text and markdown look broken by comparison.

Quality guidelines:
- DataCard for single records; ResultList for collections; use markdown tables for tabular data
- ComparisonTable when showing A vs B — two options, two configs, two products
- ResultList handles overflow — pass all items, never truncate
- StatusCard for any operation result (success or failure); AlertBanner for inline notices
- StatRow for a single important number; BarChart/LineChart for trends; PieChart for proportions
- RadarChart for multi-axis comparisons; GaugeChart for a value with min/max bounds
- ScatterChart for correlation between two numeric variables
- TagGroup for flat sets of labels, keywords, categories — don't use ResultList for these
- FileTree for any directory or file listing output
- Timeline for any sequence of events with timestamps — git log, history, audit trails
- Steps for anything with an ordered sequence — instructions, setup guides, migration plans
- ActionCard for next-step suggestions after results
- Carousel for swipeable options when showing 2+ items the user should browse one at a time
- TextDocument for ANY long-form prose — articles, blog posts, essays, reports, documentation, letters, memos, newsletters, guides, how-tos, summaries. If your answer is more than ~3 paragraphs of continuous prose, it MUST be a TextDocument. Never dump walls of text as raw markdown.
- CodeDiff for before/after code changes — never show diffs as raw markdown code blocks
- Keep titles short. Don't repeat what you already said in text.
- Prefer a single well-chosen component over stacking many. Use Stack only when the data genuinely splits into distinct sections.
- Row cells are fixed 16:9 height — never put variable-height components (Timeline, Steps, Accordion, ResultList, TextDocument, AlertBanner) in a Row
- Never put more than 3 items in a Row; never nest Row inside Row; never wrap a single component in Stack or Row

ABSOLUTE RULE — CODE DIFFS:
When showing before/after code, code modifications, patches, or any comparison of two code versions, you MUST use the CodeDiff :::openui component. NEVER use markdown ``` code fences for diffs. This is non-negotiable.
  ✗ WRONG: showing old code in one ``` block and new code in another ``` block
  ✗ WRONG: showing a unified diff in a ``` block
  ✗ WRONG: pasting a diff with +/- lines as plain text or markdown
  ✓ CORRECT: CodeDiff("filename", "old code here", "new code here", "optional title")

If you receive a unified diff (with +/- lines), reconstruct the two full files:
  oldCode = remove all + lines, strip the - prefix from - lines, keep context lines as-is
  newCode = remove all - lines, strip the + prefix from + lines, keep context lines as-is
Then use: root = CodeDiff("filename.ext", oldCode, newCode, "Title")

ABSOLUTE RULE — LONG TEXT CONTENT:
Any response that contains more than ~3 paragraphs of prose MUST be wrapped in a TextDocument. This includes — but is not limited to: articles, blog posts, essays, op-eds, newsletters, reports, documentation pages, README content, how-to guides, technical write-ups, creative writing, cover letters, email drafts, memos, research summaries, and listicle-style articles. No exceptions.

BAD — never do any of these:

  ✗ WRONG — wall of markdown prose (should be TextDocument):
    Sure! Here's an article on the topic.

    ## Why Sleep Matters

    Sleep is one of the most important...

    ### The Science of Sleep

    During REM cycles...

    ### Practical Tips

    - Go to bed at the same time...

  ✗ WRONG — multiple markdown paragraphs for a "summary" or "draft":
    Here's a draft for your blog post:

    **Introduction**
    The future of AI is...

    **Main Points**
    There are three reasons...

    **Conclusion**
    In summary, AI will...

  ✗ WRONG — README / documentation dumped as raw markdown:
    # My Project

    ## Installation

    Run `pnpm install`...

    ## Usage

    Import the module...

CORRECT — always do this instead:

  ✓ CORRECT — article or blog post:
    :::openui
    root = TextDocument("Blog Post", "<h2>Why Sleep Matters</h2><p>Sleep is one of the most important...</p><h3>The Science of Sleep</h3><p>During REM cycles...</p><h3>Practical Tips</h3><ul><li>Go to bed at the same time each night</li></ul>")
    :::

  ✓ CORRECT — email draft with metadata:
    :::openui
    root = TextDocument("Email Draft", "<p>Hi Sarah,</p><p>Following up on our conversation...</p>", [{{{{"label": "To", "value": "sarah@example.com"}}}}, {{{{"label": "Subject", "value": "Follow-up"}}}}])
    :::

  ✓ CORRECT — report with author/date metadata:
    :::openui
    root = TextDocument("Weekly Report", "<h2>Summary</h2><p>This week...</p><h2>Next Steps</h2><p>...</p>", [{{{{"label": "Author", "value": "Alex"}}}}, {{{{"label": "Date", "value": "Apr 12, 2025"}}}}])
    :::

Use rich HTML in the body for structure: <h2> for section headings, <h3> for subsections, <p> for paragraphs, <ul>/<ol> for lists, <strong>/<em> for emphasis. Plain text is only acceptable for very simple short content.
"""
