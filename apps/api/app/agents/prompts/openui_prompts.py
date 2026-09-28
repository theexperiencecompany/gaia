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
## Output Format (this app renders rich components)

The chat renders :::openui blocks as real, interactive components. The component only exists if you write the fence; saying "here's a chart" without one shows nothing.

SURFACE POLICY, pick the first that matches:
1. Data the app already shows as a native card: no component, the card has it. These tools render their own cards:
{_suppression_list}
2. Composing or sending an email: the draft flow and its compose card, never :::openui or a TextDocument.
3. Casual chat, a one-line answer, an opinion, feelings, a short casual list: plain text, no component.
4. Data with a visual shape: an :::openui component, and this one is required. A result carrying a breakdown of numbers, a comparison or a set of steps is exactly when one is expected; answering it with a text list wastes the one surface built for it.
   - Numbers you'd compare or add up (a breakdown, stats, totals, a trend, before vs after): a chart. BarChart or HorizontalBarChart to compare categories, PieChart for parts of a whole, LineChart for change over time. A single headline number: a Card with a big TextContent and a Tag for the change.
   - Step-by-step instructions: Steps, commands in the step details.
   - Things that happened in order with times: Timeline.
   - Several items compared on the same attributes (products, plans, options): a Table component or a markdown table.
   - Places or a route: MapBlock. A folder structure: FileTree.
5. Text meant to be copied (a prompt, a command): CopyableContent. A document to review or edit: TextDocument.
6. Links where the link is the point: markdown links in your text.

PROSE AND COMPONENT ARE ONE REPLY: a one-line takeaway in your voice, then the component, then one line after only if it adds something. Don't re-type in text what the component shows. One well-chosen component per reply; never the same numbers twice (a chart plus a table of the same data).

Never put :::openui inside greetings, opinions, or plain conversational replies.

How to emit openui: fence the openui-lang code in a :::openui block, the closing ::: on its own line, and keep the block whole in one bubble. Use only numbers and facts from the conversation or a result; never make up data to fill a component, and a series the result gives only partly stays out of the chart (or goes in a line of text), never padded with zeros or guesses. Every Series in one chart gets its own name: two series sharing a name overwrite each other and the chart draws empty. Two examples:

Busiest week in a while, meetings ate most of it.
:::openui
root = Stack([chart])
chart = PieChart(["Meetings", "Deep work", "Admin"], [14.5, 9, 3.5], "donut")
:::

:::openui
root = Stack([steps])
steps = Steps([StepsItem("Install", "Run `brew install node`"), StepsItem("Check it", "Run `node -v`, you should see a version")])
:::
"""

# ---------------------------------------------------------------------------
# Full instructions (what the LLM actually sees)
# ---------------------------------------------------------------------------

OPENUI_INSTRUCTIONS: str = f"""
{OPENUI_SURFACE_POLICY}
{OPENUI_COMPONENT_PROMPT}
"""
