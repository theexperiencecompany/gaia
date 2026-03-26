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
  Use for: Single KPI with optional trend

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
  RULE 6 — Multi-component: root = Stack([c1, c2]) then c1 = ..., c2 = ... on following lines.
           Forward references are allowed.
  RULE 7 — Strings must use double quotes. No single quotes.

How to emit an OpenUI block — surround the code in fences, mix freely with text:

  Some text before.

  :::openui
  root = GaugeChart(73, "CPU Usage", 0, 100)
  :::

  Some text after.

Multi-component (Stack):

  :::openui
  root = Stack([gauge, info])
  gauge = GaugeChart(73, "CPU", 0, 100)
  info = DataCard("prod-01", [{{{{"label": "Status", "value": "healthy"}}}}])
  :::

Skipping an optional middle argument with null:

  :::openui
  root = GaugeChart(73, null, 0, 100)
  :::

Do NOT use :::openui for greetings, opinions, or plain conversational responses.

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
- Keep titles short. Don't repeat what you already said in text.
"""
