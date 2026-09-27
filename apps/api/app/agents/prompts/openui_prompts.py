"""OpenUI prompt: GAIA surface policy + generated component vocabulary.

The component vocabulary (syntax rules + every component signature) is generated
from the merged @openuidev/react-ui + GAIA component library by
scripts/openui/generate-prompt.ts and read here from openui_generated.txt.
A pre-commit hook keeps the artifact in sync with the TypeScript specs, so this
module never hand-maintains the component catalog.

The GAIA-owned, Python-stateful pieces (the SURFACE POLICY preamble and the
OPENUI_SUPPRESSED_TOOLS list, derived from tool_fields) live here.
"""

from pathlib import Path

from app.models.chat_models import tool_fields

# Tools already rendered by TOOL_RENDERERS: LLM must NOT emit :::openui for these
OPENUI_SUPPRESSED_TOOLS: list[str] = list(tool_fields)

_suppression_list: str = "\n".join(f"  - {t}" for t in OPENUI_SUPPRESSED_TOOLS)

# Generated component vocabulary (syntax rules + component signatures), produced
# by `pnpm openui:gen-prompt` from the merged TypeScript component library.
_GENERATED_PROMPT_PATH: Path = Path(__file__).parent / "openui_generated.txt"
OPENUI_COMPONENT_PROMPT: str = _GENERATED_PROMPT_PATH.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Surface policy: GAIA-owned, decides WHEN to reach for an openui component.
# ---------------------------------------------------------------------------

OPENUI_SURFACE_POLICY: str = f"""
SURFACE POLICY, pick the FIRST that matches:
1. Tool already renders a native card (the list below) → emit NOTHING extra; a short conversational line is enough. Never wrap these in :::openui (it duplicates the card):
{_suppression_list}
2. Composing/sending an email → use the draft tool (native compose card), never :::openui or a TextDocument.
3. Casual chat, a single-sentence answer, an opinion, emotional support → plain text. No component.
4. A casual reply, or a short UNSTRUCTURED list → plain text/markdown, no component.
5. Structured data shown inline:
   - Plain tabular / comparison / key-value data → a Table component or a MARKDOWN TABLE in prose. Both render natively.
   - Links, or content where links are the point → clickable MARKDOWN links ([label](url)) in your prose.
   - Data with a richer visual form (stats/KPIs, a timeline, steps, a file tree, charts/gauges/maps) → the matching :::openui component below. For these visual types this is a forcing rule, not a preference.
6. Reusable text to copy/paste elsewhere → CopyableContent (mode "inline" for short, "block" for long).
7. A document to review, edit, or reuse → TextDocument (editable, with metadata fields).
8. Longer content that reads better as its own document → an artifact (a file the executor places in artifacts/).

Math renders only inside $$...$$, inline or on its own lines; a single $ is a literal dollar sign, so write prices as-is ($8, $347.53).

OPENUI AND PROSE WORK TOGETHER, NEVER EITHER/OR. The component and your words are LAYERS in the SAME reply: lead-in and takeaway stay as plain text around the :::openui block, which carries the data.

Never put :::openui inside greetings, opinions, or plain conversational replies.

How to emit openui: fence the openui-lang code in a :::openui block and mix freely with text.
Your conversational lines stay as normal text; the component goes between them inside the fence:

  Here are the results:

  :::openui
  root = RadialChart(["CPU", "Memory", "Disk"], [73, 45, 30])
  :::

  Anything else you'd like to see?
"""

# Quality / restraint notes: WHEN to reach for a component and how NOT to
# overdo it. Component names track the current (react-ui) catalog.

OPENUI_QUALITY_NOTES: str = """
Specifics the policy above does not spell out:
  - A single KPI reads well as a Card with TextContent (label + big value) and a Tag for the delta.
  - Depth-on-demand → Accordion / Tabs, ONLY when each section carries substantial content, never for thin one-liners.
  - Media → ImageGallery, VideoBlock, AudioPlayer, MapBlock.
  - Timeline for event sequences with timestamps; Steps for ordered instructions; Callout for inline notices.
  - Prefer one well-chosen component over stacking many. Use Stack only when the content genuinely splits into sections; a `wrap=true` row gives a responsive grid. Do not wrap everything in a Card by default.
  - Buttons CAUTION: next-step suggestion chips already ship via follow-up-actions. Do NOT use Button/Buttons as the reply's "what next" menu; reserve them for an action tied INSIDE a specific card.
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
