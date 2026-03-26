"""OpenUI prompt with suppression list and generic component library docs."""

from app.models.chat_models import tool_fields

# Tools already rendered by TOOL_RENDERERS — LLM must NOT emit :::openui for these
OPENUI_SUPPRESSED_TOOLS: list[str] = list(tool_fields)

_suppression_list = "\n".join(f"  - {t}" for t in OPENUI_SUPPRESSED_TOOLS)

OPENUI_COMPONENT_LIBRARY_PROMPT = """
Available Generic Components:

--- Layout & Data ---
DataCard(title, fields)
  title: string
  fields: {label: string, value: string}[]
  Use for: single record details, config values, profile data

ResultList(items, title?)
  items: {title: string, subtitle?: string, body?: string, url?: string, badge?: string}[]
  title?: string
  Use for: lists of results, search hits, records — overflow scroll, no truncation

ComparisonTable(leftLabel, rightLabel, rows, title?)
  leftLabel: string; rightLabel: string
  rows: {label: string, left: string, right: string, highlight?: boolean}[]
  Use for: A vs B comparisons — highlight: true gives accent treatment

StatusCard(title, status, message?, detail?)
  status: "success" | "error" | "warning" | "info" | "pending"
  Use for: operation results, confirmations, errors, API call outcomes

ActionCard(title, description?, actions?)
  actions?: {label: string, type: "continue_conversation", value: string}[]
  Use for: next-step prompts, follow-up suggestions

TagGroup(tags, title?)
  tags: {label: string, color?: "default"|"primary"|"success"|"warning"|"danger"}[]
  Use for: keyword sets, categories, tech stacks — rendered as chips

FileTree(items, title?)
  items: {path: string, type: "file"|"dir", size?: string}[]
  Use for: directory listings, filesystem output

Accordion(items, title?)
  items: {label: string, content: string}[]
  Use for: FAQs, grouped results, collapsible sections

TabsBlock(tabs)
  tabs: {label: string, content: string}[]
  Use for: multi-category output, results split by type

ProgressList(items, title?)
  items: {label: string, value: number, max?: number, color?: "default"|"primary"|"success"|"warning"|"danger"}[]
  Use for: task completion, resource usage, batch status

SelectableList(options, title?, description?)
  options: {label: string, description?: string, value: string, badge?: string}[]
  Use for: structured choices — server selection, plan choices, environment selection

AvatarList(items, title?)
  items: {name: string, role?: string, description?: string, initials?: string, color?: string}[]
  Use for: team rosters, assignees, contributors, attendees

KbdBlock(shortcuts, title?)
  shortcuts: {keys: string[], description: string}[]
  Use for: keyboard shortcut references, CLI flag tables

--- Analytics ---
StatRow(title, value, unit?, trend?, trendLabel?)
  trend?: "up" | "down" | "neutral"
  Use for: Single KPI with optional trend. Wrap 2+ StatRows in Row() for side-by-side display.

BarChart(data, xKey, yKey, title?, color?)
  data: {[key: string]: string|number}[]; xKey: string; yKey: string
  Use for: comparisons, rankings, distributions

LineChart(data, xKey, yKeys, title?, colors?)
  yKeys: string[] (multiple series)
  Use for: trends over time, multi-series comparisons

AreaChart(data, xKey, yKeys, title?, colors?)
  Same as LineChart — filled area with gradient fill style. Use for: cumulative values, volume over time

PieChart(data, nameKey, valueKey, title?)
  Use for: proportions, composition breakdowns

ScatterChart(data, xKey, yKey, title?, labelKey?)
  Use for: correlation between two numeric variables

RadarChart(data, angleKey, valueKeys, title?, colors?)
  angleKey: string (axis label field); valueKeys: string[]
  Use for: multi-axis comparisons, skill matrices, benchmark scores

GaugeChart(value, title?, min?, max?, unit?, thresholds?)
  thresholds?: {warning: number, danger: number}
  Use for: CPU%, disk, scores, health indicators — value with bounds

--- Content ---
ImageBlock(src, alt?, caption?)
  Use for: single image results, previews, screenshots

ImageGallery(images)
  images: {src: string, alt?: string, caption?: string}[]
  Use for: photo sets, image search results

VideoBlock(src, title?, poster?)
  src: YouTube/Vimeo URL (auto-embeds) or direct video URL
  Use for: video results, tutorials, recordings

AudioPlayer(src, title?, description?)
  Use for: podcast clips, voice memos, TTS output

MapBlock(lat, lng, label?, zoom?)
  Use for: location results, addresses, venues, any coordinates

CalendarMini(markedDates, title?, mode?)
  markedDates: {date: string, label?: string, color?: "success"|"warning"|"danger"|"default"}[]
  mode?: "single" | "range"
  Use for: availability views, event schedules, booking slots, free days

NumberTicker(value, label?, unit?, duration?)
  Use for: single important stat with count-up animation — download count, score, uptime

Carousel(items, autoPlay?)
  items: {title: string, body?: string, image?: string, badge?: string, actions?: {label: string, value: string}[]}[]
  Use for: recommendations, product options, photos — one card at a time

TreeView(nodes, title?)
  nodes: {id: string, label: string, description?: string, children?: node[]}[] (recursive)
  Use for: org charts, nested configs, category hierarchies

--- Timeline & Notifications ---
Timeline(items, title?)
  items: {time: string, title: string, description?: string, status?: "success"|"error"|"warning"|"neutral"}[]
  Use for: git log, activity history, deployment events, audit trails

AlertBanner(variant, title, description?)
  variant: "info" | "success" | "warning" | "error"
  Use for: important notices, inline warnings — lighter than StatusCard

Steps(items, title?)
  items: {title: string, description?: string, status?: "complete"|"active"|"pending"}[]
  Use for: ordered instructions, onboarding, migration guides

--- Code ---
CodeDiff(filename, oldCode, newCode, diffStyle?, title?)
  filename: string (e.g. "src/utils.ts" — used for header and language detection)
  oldCode: string (before content)
  newCode: string (after content)
  diffStyle?: "unified" | "split" — defaults to "unified"
  title?: string
  Use for: before/after code changes, patch previews, refactoring summaries
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

BarChart — comparisons or rankings:
  :::openui
  root = BarChart([{{{{"month": "Jan", "revenue": 4200}}}}, {{{{"month": "Feb", "revenue": 5100}}}}, {{{{"month": "Mar", "revenue": 4800}}}}], "month", "revenue", "Monthly Revenue")
  :::

LineChart — trends over time (supports multiple series via yKeys array):
  :::openui
  root = LineChart([{{{{"date": "Mon", "requests": 120, "errors": 3}}}}, {{{{"date": "Tue", "requests": 145, "errors": 5}}}}, {{{{"date": "Wed", "requests": 98, "errors": 1}}}}], "date", ["requests", "errors"], "Traffic This Week")
  :::

AreaChart — same as LineChart but filled area style:
  :::openui
  root = AreaChart([{{{{"month": "Jan", "users": 800}}}}, {{{{"month": "Feb", "users": 1200}}}}, {{{{"month": "Mar", "users": 1900}}}}], "month", ["users"], "User Growth")
  :::

PieChart — proportions or composition:
  :::openui
  root = PieChart([{{{{"browser": "Chrome", "share": 65}}}}, {{{{"browser": "Firefox", "share": 18}}}}, {{{{"browser": "Safari", "share": 12}}}}, {{{{"browser": "Other", "share": 5}}}}], "browser", "share", "Browser Usage")
  :::

ScatterChart — correlation between two variables:
  :::openui
  root = ScatterChart([{{{{"hours": 2, "score": 65}}}}, {{{{"hours": 5, "score": 80}}}}, {{{{"hours": 8, "score": 92}}}}], "hours", "score", "Study Hours vs Score")
  :::

RadarChart — multi-axis comparison:
  :::openui
  root = RadarChart([{{{{"skill": "Frontend", "alice": 90, "bob": 70}}}}, {{{{"skill": "Backend", "alice": 75, "bob": 95}}}}, {{{{"skill": "DevOps", "alice": 60, "bob": 85}}}}], "skill", ["alice", "bob"], "Skill Matrix")
  :::

GaugeChart — value within a bounded range:
  :::openui
  root = GaugeChart(73, "CPU Usage", 0, 100, "%", {{{{"warning": 70, "danger": 90}}}})
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

--- Code ---

CodeDiff — before/after code comparison:
  :::openui
  root = CodeDiff("src/config.ts", "export const API_URL = 'http://localhost:3000';", "export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:3000';", "unified", "Environment Variable Fix")
  :::

--- Multi-Component Layout ---

Row — place any components side-by-side in equal-width columns:
  :::openui
  root = Row([s1, s2, s3])
  s1 = StatRow("CPU", 73, "%", "up", "+5%")
  s2 = StatRow("Memory", 4.2, "GB")
  s3 = StatRow("Disk", 120, "GB")
  :::

  Use Row for: multiple StatRows, side-by-side StatusCards, paired DataCards, or any components that should share horizontal space equally.

Stack — combine multiple components vertically:
  :::openui
  root = Stack([stats, chart])
  stats = Row([s1, s2, s3])
  s1 = StatRow("Users", 12450, null, "up", "+8%")
  s2 = StatRow("Revenue", 48200, "$", "up", "+12%")
  s3 = StatRow("Churn", 2.1, "%", "down", "-0.5%")
  chart = BarChart([{{{{"month": "Jan", "revenue": 4200}}}}, {{{{"month": "Feb", "revenue": 5100}}}}], "month", "revenue", "Monthly Revenue")
  :::

  Nest Row inside Stack to combine horizontal groups with other components. Any combination works.

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
- CodeDiff for before/after code changes — never show diffs as raw markdown code blocks
- Keep titles short. Don't repeat what you already said in text.
- Prefer a single well-chosen component over stacking many. Use Stack only when the data genuinely splits into distinct sections.
"""
