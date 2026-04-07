"""
Canvas quality evaluator — post-write LLM-as-judge for tracked todo canvases.

Inspired by Claude Code's PostToolUse hook + additionalContext pattern (from the
March 2026 source leak). After the agent writes a tracked todo canvas, this evaluator
runs a lightweight LLM call to verify the canvas captured all actionable identifiers
needed for future autonomous execution.

The key insight from Claude Code's architecture:
  PostToolUse hook → evaluate tool output → inject additionalContext into agent's
  next turn if issues are found.

For GAIA, the equivalent is appending a quality note to the tool's return string so
the agent sees it immediately and can self-correct in the same turn.

Unlike rule-based validators, this uses a generic LLM rubric:
  "The canvas says it performed action X — does it contain the identifiers that
   action X would have produced?"

This avoids per-integration prompt engineering while still catching all cases:
  email sent  → thread_id / message_id missing
  issue created → issue ID (GAIA-572) missing
  Slack posted  → channel + message_ts missing
  calendar event → event_id missing
  etc.
"""

import json
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from shared.py.wide_events import log

from app.agents.llm.client import get_free_llm_chain, invoke_with_fallback
from app.services.vfs.mongo_vfs import MongoVFS

_EVALUATOR_SYSTEM = """\
You are a canvas quality evaluator for GAIA's tracked todo system.

A canvas is GAIA's persistent working memory for a task. It must contain every
actionable identifier returned by external tools this session — because in a future
session GAIA will have ONLY the canvas and nothing else. If an ID is missing, GAIA
will be blind when trying to follow up.

EVALUATION RUBRIC

Read the canvas and determine what external actions it claims were performed.
Then check whether the canvas records the identifiers those actions would have produced.

Examples of required identifiers by action type:
• Email sent / drafted    → Gmail thread_id or message_id (16-char hex, e.g. 19d645a2b146c776)
• Linear issue created    → issue identifier (e.g. GAIA-572, ENG-99, ABC-1)
• GitHub PR / issue       → PR number or full URL
• Slack message posted    → channel name AND message_ts (e.g. 1712345678.123456)
• Calendar event created  → event_id or event URL
• Notion page created     → page_id or URL
• Any API object created  → its primary identifier as returned by the API

IMPORTANT: Only flag identifiers for actions that the canvas explicitly claims were
performed. Do not flag missing IDs for actions not yet taken.

Respond with JSON only — no prose, no markdown fences:
{"pass": true, "missing": [], "note": ""}
or
{"pass": false, "missing": ["Gmail thread_id for the sent email"], "note": "one sentence telling the agent what to add"}
"""

_EVALUATOR_USER_TEMPLATE = """\
Evaluate this tracked todo canvas:

---
{canvas}
---

Does it contain all required identifiers for the actions it claims to have performed?
"""


async def evaluate_canvas_quality(
    canvas_path: str,
    user_id: str,
    todo_id: str,
) -> Optional[str]:
    """
    Run a post-write quality evaluation on a tracked todo canvas.

    Reads the canvas, calls a lightweight LLM to check if all actionable
    identifiers are recorded, and returns a quality note string to be appended
    to the tool's return value (or None if the canvas passes).

    Returns:
        None if canvas passes quality check.
        A warning string to inject into the tool result if issues are found.
    """
    try:
        vfs = MongoVFS()
        canvas = await vfs.read(path=canvas_path, user_id=user_id)
        if not canvas or not canvas.strip():
            # Empty canvas — nothing to evaluate yet
            return None

        llm_chain = get_free_llm_chain()
        messages = [
            SystemMessage(content=_EVALUATOR_SYSTEM),
            HumanMessage(content=_EVALUATOR_USER_TEMPLATE.format(canvas=canvas)),
        ]

        response = await invoke_with_fallback(llm_chain, messages)
        content = response.content if hasattr(response, "content") else str(response)
        raw = content if isinstance(content, str) else str(content)

        # Strip markdown fences if the model wrapped the JSON
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)

        if result.get("pass", True):
            return None

        missing = result.get("missing", [])
        note = result.get("note", "")

        if not missing and not note:
            return None

        missing_str = ", ".join(missing) if missing else "some required identifiers"
        log.warning(
            "canvas_quality.fail",
            todo_id=todo_id,
            missing=missing,
        )

        return (
            f"\n\n⚠️ CANVAS QUALITY CHECK: {note or 'Canvas is missing required identifiers.'}\n"
            f"Missing: {missing_str}\n"
            f"Please call update_tracked_todo_canvas (mode='section', section='Key Details') "
            f"to add the missing identifiers before responding to the user."
        )

    except json.JSONDecodeError:
        # LLM returned non-JSON — skip silently, don't break the tool
        log.warning("canvas_quality.json_parse_error", todo_id=todo_id)
        return None
    except Exception as e:
        # Evaluator must never break the tool — log and swallow
        log.warning("canvas_quality.error", todo_id=todo_id, error=str(e))
        return None
