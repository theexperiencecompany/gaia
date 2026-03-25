# OpenUI — How it works & how to test it

## What this is

OpenUI lets the LLM generate rich UI components inline in chat — for tool outputs that don't have a native renderer (MCP tools, third-party integrations, anything not in `tool_fields`).

Known tools (weather, todos, calendar, email, etc.) are suppressed — the LLM is told not to emit OpenUI for them because the frontend already handles those with native `TOOL_RENDERERS`.

---

## The two rendering paths

```
Tool output
    │
    ├─► tool_fields entry? ──yes──► TOOL_RENDERERS (native card, always)
    │
    └─► not in tool_fields? ──────► LLM emits :::openui block ──► genericLibrary renders it
```

The suppression list in `openui_prompts.py` is derived directly from `tool_fields` in `chat_models.py` — add a tool to `tool_fields` and it's automatically suppressed in the prompt. No separate config.

---

## The 37 generic components

The LLM can use any of these for unknown tool output:

**Layout & Data** — DataCard, ResultList, DataTable, ComparisonTable, StatusCard, ActionCard, TagGroup, FileTree, Accordion, TabsBlock, ProgressList, StatRow, SelectableList, AvatarList, KbdBlock

**Analytics** — MetricCard, BarChart, LineChart, AreaChart, PieChart, ScatterChart, RadarChart, GaugeChart

**Content** — ImageBlock, ImageGallery, VideoBlock, AudioPlayer, DiffBlock, MapBlock, CalendarMini, NumberTicker, Carousel, TreeView

**Timeline & Notifications** — Timeline, JsonViewer, AlertBanner, Steps

Zero new dependencies — recharts, react-day-picker, animated-number-react, and motion were already in `package.json`.

---

## How to test

### 1. Visual preview (no backend needed)

```bash
nx dev web
```

Visit `http://localhost:3000/openui-preview` — renders all 37 components with realistic mock data.

---

### 2. Sanity check the assembled prompt

```bash
cd apps/api && uv run python -c "
from app.agents.prompts.openui_prompts import OPENUI_INSTRUCTIONS, OPENUI_SUPPRESSED_TOOLS
print('Suppressed tools:', len(OPENUI_SUPPRESSED_TOOLS))
print(OPENUI_SUPPRESSED_TOOLS)
print('---')
print(OPENUI_INSTRUCTIONS[:500])
"
```

Shows exactly what the LLM sees — the suppression list and component signatures.

---

### 3. Live prompt test

Start the stack:

```bash
cd infra/docker && docker compose up
nx dev api
nx dev web
```

Then try these prompts in chat. Known tools (weather, todos, email) will still use their native cards — these prompts target things without a native renderer:

| Prompt | Expected component |
|---|---|
| "Show me a summary of my system config as a card" | `DataCard` |
| "List 5 open source LLM projects with descriptions" | `ResultList` |
| "Compare Python, Go, Rust across speed, memory, and ecosystem in a table" | `DataTable` |
| "Show monthly revenue for Q1 2025: Jan 42k, Feb 38k, Mar 51k" | `BarChart` |
| "Show a git-style timeline of the last 5 Linux kernel releases" | `Timeline` |
| "Give me a step-by-step guide to set up a PostgreSQL replica" | `Steps` |
| "Show CPU usage at 73% as a gauge" | `GaugeChart` |
| "Run a health check and show the result" | `StatusCard` |

The LLM responds with `:::openui` blocks and the frontend renders them using the generic component library.

---

## Adding a new generic component

1. Read `apps/web/src/features/chat/components/bubbles/bot/CLAUDE.md` — the authoritative styling guide
2. Add a zod schema and React component to `apps/web/src/config/openui/genericLibrary.tsx`
3. Add it to the correct `componentGroups` entry in `createLibrary`
4. Add its signature to `OPENUI_COMPONENT_LIBRARY_PROMPT` in `openui_prompts.py`
5. Add a section to the preview page at `apps/web/src/app/(dev)/openui-preview/page.tsx`

## Adding a new native tool card

Use this path when the backend emits structured data for a known tool (i.e., the tool is in `tool_fields`).

1. Add the field name to `tool_fields` in `apps/api/app/models/chat_models.py` — this automatically suppresses OpenUI for it
2. Create the React component in `apps/web/src/features/chat/components/bubbles/bot/`
3. Register it in `TOOL_RENDERERS` in `TextBubble.tsx`

See `CLAUDE.md` for the styling contract and a copy-paste component template.
