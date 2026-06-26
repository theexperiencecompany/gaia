"""OpenUI prompt — GAIA surface policy + generated component vocabulary.

The component vocabulary (syntax rules + every component signature) is generated
from the merged `@openuidev/react-ui` + GAIA component library by
`scripts/openui/generate-prompt.ts` and read here from `openui_generated.txt`.
A pre-commit hook keeps the artifact in sync with the TypeScript specs, so this
module never hand-maintains the component catalog.

The GAIA-owned, Python-stateful pieces — the SURFACE POLICY preamble and the
`OPENUI_SUPPRESSED_TOOLS` list (derived from `tool_fields`) — live here.
"""

from pathlib import Path

from app.models.chat_models import tool_fields

# Tools already rendered by TOOL_RENDERERS — LLM must NOT emit :::openui for these
OPENUI_SUPPRESSED_TOOLS: list[str] = list(tool_fields)

_suppression_list: str = "\n".join(f"  - {t}" for t in OPENUI_SUPPRESSED_TOOLS)

# Generated component vocabulary (syntax rules + component signatures), produced
# by `pnpm openui:gen-prompt` from the merged TypeScript component library.
_GENERATED_PROMPT_PATH: Path = Path(__file__).parent / "openui_generated.txt"
OPENUI_COMPONENT_PROMPT: str = _GENERATED_PROMPT_PATH.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Surface policy — GAIA-owned, decides WHEN to reach for an openui component.
# ---------------------------------------------------------------------------

OPENUI_SURFACE_POLICY: str = f"""
SURFACE POLICY — pick the FIRST that matches:
1. Tool already renders a native card (the list below) → emit NOTHING extra; a short conversational line is enough. Never wrap these in :::openui (it duplicates the card):
{_suppression_list}
2. Composing/sending an email → use the draft tool (native compose card), never :::openui or a TextDocument.
3. Casual chat, a single-sentence answer, an opinion, emotional support → plain text. No component.
4. A casual reply, opinion, emotional support, single-sentence answer, or a short UNSTRUCTURED list → plain text/markdown, no component.
5. Structured data shown inline:
   - Plain tabular / comparison / key-value data (rows × columns) → a Table component, or a MARKDOWN TABLE in prose. GAIA renders both natively.
   - Links, or content where links are the point (URLs, sources, references) → clickable MARKDOWN links ([label](url)) in your prose.
   - Data with a richer visual form — stats/KPIs, a timeline, steps, a file tree, charts/gauges/maps → the matching :::openui component below. These are interactive and native to GAIA's cards; for these visual types this is a forcing rule, not a preference.
6. Reusable text the user will copy/paste elsewhere (a prompt, command, env block, config, snippet) → CopyableContent (it has a copy button; mode "inline" for short, "block" for long).
7. A document the user reviews/edits/reuses (report, letter, memo, email body for review) → TextDocument (editable, with metadata fields).
8. Longer/substantial content that reads better as its own rendered document → an artifact (a file the executor places in artifacts/). Better for length + readability than cramming a chat bubble.

OPENUI AND PROSE WORK TOGETHER — NOT EITHER/OR. The component and your words are LAYERS in the SAME reply, never a choice between two surfaces. Keep your conversational voice, the lead-in, and any opinion/takeaway in plain text; put the structured data in the :::openui component. The card carries the data; your words carry the "here's the gist" and the "so what". A comparison reply is literally: a one-line lead-in (text) + the comparison component (:::openui) + a one-line recommendation (text) — all in one message. Markdown carries links; :::openui carries the visual components (stats, charts, timelines, steps, gauges, tables); prose always wraps whichever you pick — you write prose AND the component, together.

Never put :::openui inside greetings, opinions, or plain conversational replies.

How to emit openui — fence the openui-lang code in a :::openui block and mix freely with text.
Your conversational lines stay as normal text; the component goes between them inside the fence:

  Here are the results:

  :::openui
  root = RadialChart(["CPU", "Memory", "Disk"], [73, 45, 30])
  :::

  Anything else you'd like to see?
"""

# ---------------------------------------------------------------------------
# Quality / restraint notes — GAIA-owned. WHEN to reach for a component and how
# NOT to overdo it. Component names track the current (react-ui) catalog; the
# ingestion philosophy is unchanged from develop.
# ---------------------------------------------------------------------------

OPENUI_QUALITY_NOTES: str = """
Capability-aware component picks (use the one whose affordance matches the intent):
  - Copyable, paste-elsewhere text (prompt/command/env/config/snippet) → CopyableContent.
  - Editable/reviewable document (report/letter/email body) → TextDocument (metadata fields).
  - Numbers / trends / KPIs → BarChart / LineChart / AreaChart / PieChart / RadarChart /
    RadialChart / NumberTicker; a single KPI reads well as a Card with TextContent
    (label + big value) and a Tag for the delta.
  - Records / hierarchies / sequences → Card (+ CardHeader), Table (+ Col), FileTree,
    Timeline, Steps, TagBlock.
  - Depth-on-demand → Accordion / Tabs, ONLY when each section/tab carries substantial
    content (never for thin one-liners).
  - Media → ImageGallery, VideoBlock, AudioPlayer, MapBlock.
  - Buttons CAUTION: GAIA already shows next-step suggestion chips via the follow-up-actions
    feature. Do NOT use Button/Buttons as the reply's "what next" menu — that duplicates it.
    Reserve Button/Buttons for an action tied INSIDE a specific card (e.g. a link on one item).

Quality notes:
  - Tabular / comparison / key-value data → a Table (Col per column; cells can be Tags), or a
    plain markdown table in prose. Both render natively.
  - Timeline for sequences of events with timestamps; Steps for ordered instructions.
  - Callout for inline notices; operation-result banners are just a Callout.
  - Prefer one well-chosen component over stacking many. Use Stack only when the content
    genuinely splits into sections (rows/columns); a `wrap=true` row gives a responsive grid.
  - Don't reach for a Card by default. Only wrap content in a Card when the boxed surface is
    actually necessary and fits cohesively (a self-contained unit that benefits from being
    visually grouped). Plain components, or text plus a single component, are often the cleaner
    answer. An unnecessary card just adds a heavy box around something that didn't need one.
"""

# ---------------------------------------------------------------------------
# Full instructions (what the LLM actually sees)
# ---------------------------------------------------------------------------

OPENUI_INSTRUCTIONS: str = f"""
---OpenUI Lang (Rich UI Components)---
{OPENUI_SURFACE_POLICY}
{OPENUI_COMPONENT_PROMPT}
{OPENUI_QUALITY_NOTES}
"""
