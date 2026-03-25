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

ResultList(title?, items)
  title?: string
  items: {title: string, subtitle?: string, body?: string, url?: string, badge?: string}[]
  Use for: lists of results, search hits, records — overflow scroll, no truncation

DataTable(title?, columns, rows)
  title?: string; columns: string[]; rows: string[][]
  Use for: structured tabular data, multi-column records

ComparisonTable(title?, leftLabel, rightLabel, rows)
  leftLabel: string; rightLabel: string
  rows: {label: string, left: string, right: string, highlight?: boolean}[]
  Use for: A vs B comparisons — highlight: true gives accent treatment

StatusCard(title, status, message?, detail?)
  status: "success" | "error" | "warning" | "info" | "pending"
  Use for: operation results, confirmations, errors, API call outcomes

ActionCard(title, description?, actions?)
  actions?: {label: string, type: "continue_conversation", value: string}[]
  Use for: next-step prompts, follow-up suggestions

TagGroup(title?, tags)
  tags: {label: string, color?: "default"|"primary"|"success"|"warning"|"danger"}[]
  Use for: keyword sets, categories, tech stacks — rendered as chips

FileTree(title?, items)
  items: {path: string, type: "file"|"dir", size?: string}[]
  Use for: directory listings, filesystem output

Accordion(title?, items)
  items: {label: string, content: string}[]
  Use for: FAQs, grouped results, collapsible sections

TabsBlock(tabs)
  tabs: {label: string, content: string}[]
  Use for: multi-category output, results split by type

ProgressList(title?, items)
  items: {label: string, value: number, max?: number, color?: "default"|"primary"|"success"|"warning"|"danger"}[]
  Use for: task completion, resource usage, batch status

StatRow(stats)
  stats: {label: string, value: string, description?: string}[]
  Use for: compact dashboard summary — horizontal strip of labeled numbers

SelectableList(title?, description?, options)
  options: {label: string, description?: string, value: string, badge?: string}[]
  Use for: structured choices — server selection, plan choices, environment selection

AvatarList(title?, items)
  items: {name: string, role?: string, description?: string, initials?: string, color?: string}[]
  Use for: team rosters, assignees, contributors, attendees

KbdBlock(title?, shortcuts)
  shortcuts: {keys: string[], description: string}[]
  Use for: keyboard shortcut references, CLI flag tables

--- Analytics ---
MetricCard(title, value, unit?, trend?, trendLabel?)
  trend?: "up" | "down" | "neutral"
  Use for: KPIs, counters, single-number summaries

BarChart(title?, data, xKey, yKey, color?)
  data: {[key: string]: string|number}[]; xKey: string; yKey: string
  Use for: comparisons, rankings, distributions

LineChart(title?, data, xKey, yKeys, colors?)
  yKeys: string[] (multiple series)
  Use for: trends over time, multi-series comparisons

AreaChart(title?, data, xKey, yKeys, colors?)
  Same as LineChart — filled area. Use for: cumulative values, volume over time

PieChart(title?, data, nameKey, valueKey)
  Use for: proportions, composition breakdowns

ScatterChart(title?, data, xKey, yKey, labelKey?)
  Use for: correlation between two numeric variables

RadarChart(title?, data, angleKey, valueKeys, colors?)
  angleKey: string (axis label field); valueKeys: string[]
  Use for: multi-axis comparisons, skill matrices, benchmark scores

GaugeChart(title?, value, min?, max?, unit?, thresholds?)
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

DiffBlock(title?, hunks)
  hunks: {header: string, lines: {type: "add"|"remove"|"context", content: string}[]}[]
  Use for: code diffs, config changes, what-changed output

MapBlock(lat, lng, label?, zoom?)
  Use for: location results, addresses, venues, any coordinates

CalendarMini(title?, markedDates, mode?)
  markedDates: {date: string, label?: string, color?: "success"|"warning"|"danger"|"default"}[]
  mode?: "single" | "range"
  Use for: availability views, event schedules, booking slots, free days

NumberTicker(value, label?, unit?, duration?)
  Use for: single important stat with count-up animation — download count, score, uptime

Carousel(items, autoPlay?)
  items: {title: string, body?: string, image?: string, badge?: string, actions?: {label: string, value: string}[]}[]
  Use for: recommendations, product options, photos — one card at a time

TreeView(title?, nodes)
  nodes: {id: string, label: string, description?: string, children?: node[]}[] (recursive)
  Use for: org charts, nested configs, category hierarchies

--- Timeline & Notifications ---
Timeline(title?, items)
  items: {time: string, title: string, description?: string, status?: "success"|"error"|"warning"|"neutral"}[]
  Use for: git log, activity history, deployment events, audit trails

JsonViewer(title?, data)
  data: string (JSON string — LLM serializes, component parses)
  Use for: raw API responses, deeply nested data — collapsible tree

AlertBanner(variant, title, description?)
  variant: "info" | "success" | "warning" | "error"
  Use for: important notices, inline warnings — lighter than StatusCard

Steps(title?, items)
  items: {title: string, description?: string, status?: "complete"|"active"|"pending"}[]
  Use for: ordered instructions, onboarding, migration guides
"""

OPENUI_INSTRUCTIONS = f"""
---OpenUI Lang (Rich UI Components)---

The following tool outputs are rendered automatically by the frontend.
Do NOT emit :::openui blocks for them — the UI is already handled:
{_suppression_list}

For ALL other tool outputs (MCP tools, integrations, anything not in the list above):
render the data using :::openui with the components below.

{OPENUI_COMPONENT_LIBRARY_PROMPT}

Syntax rules:
- Wrap ALL OpenUI output in :::openui and ::: fences
- root = ComponentName(arg1=value1, arg2=value2) is the entry point
- Use Stack([item1, item2]) to compose multiple components
- Always write `root = ...` first — the UI shell appears immediately for streaming
- Plain text before/after the fences is rendered as normal markdown
- Do NOT use OpenUI for greetings, opinions, or conversational text

Quality guidelines:
- DataCard for single records; ResultList for collections; DataTable for multi-column data
- ComparisonTable when showing A vs B — two options, two configs, two products
- ResultList handles overflow — pass all items, never truncate
- StatusCard for any operation result (success or failure); AlertBanner for inline notices
- MetricCard for a single important number; BarChart/LineChart for trends; PieChart for proportions
- RadarChart for multi-axis comparisons; GaugeChart for a value with min/max bounds
- ScatterChart for correlation between two numeric variables
- TagGroup for flat sets of labels, keywords, categories — don't use ResultList for these
- FileTree for any directory or file listing output
- Timeline for any sequence of events with timestamps — git log, history, audit trails
- JsonViewer for raw API responses or deeply nested data — never use DataCard for this
- Steps for anything with an ordered sequence — instructions, setup guides, migration plans
- ActionCard for next-step suggestions after results
- Keep titles short. Don't repeat what you already said in text.
"""
