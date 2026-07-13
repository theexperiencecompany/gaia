"""Learn a reusable skill from an expensive, successful executor run.

The first time a novel task ("find my support requests") takes many tool calls to
work out, we distill the winning tool sequence into a Skill so the next occurrence
is one or two steps. Only genuinely expensive runs (>= SKILL_INDUCTION_MIN_TOOL_CALLS
successful calls) are worth compiling; cheap runs return None.

`induce_skill_from_trajectory` is pure and fully unit-testable. Persistence reuses
the existing inline-skill installer (`install_from_inline`); no parallel storage.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from pydantic import BaseModel

from app.agents.skills.models import SKILL_NAME_PATTERN

# Only compile a skill from a run that actually cost something to figure out.
SKILL_INDUCTION_MIN_TOOL_CALLS = 5
_MAX_NAME_LEN = 48
# retrieve_tools / plan_tasks are scaffolding, not part of a reusable procedure.
_SCAFFOLDING_TOOLS = {"retrieve_tools", "plan_tasks", "update_tasks", "finish_task"}


class SkillCandidate(BaseModel):
    """A skill distilled from a run, ready to hand to install_from_inline."""

    name: str
    description: str
    instructions: str


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:_MAX_NAME_LEN].strip("-")
    if not slug or not SKILL_NAME_PATTERN.match(slug):
        return "learned-procedure"
    return slug


def _successful_tool_calls(messages: list[BaseMessage]) -> list[tuple[str, list[str]]]:
    """Ordered (tool_name, arg_keys) for tool calls that returned a non-error result.

    Args keys (not values) generalize the procedure: values are request-specific,
    the sequence and which parameters were used is what transfers.
    """
    status_by_id: dict[str, str] = {}
    for m in messages:
        if isinstance(m, ToolMessage):
            status_by_id[m.tool_call_id] = getattr(m, "status", None) or "success"

    steps: list[tuple[str, list[str]]] = []
    for m in messages:
        if not isinstance(m, AIMessage) or not m.tool_calls:
            continue
        for tc in m.tool_calls:
            name = tc.get("name", "")
            if name in _SCAFFOLDING_TOOLS:
                continue
            if status_by_id.get(tc.get("id", "")) == "error":
                continue
            args = tc.get("args") or {}
            steps.append((name, sorted(args.keys())))
    return steps


def induce_skill_from_trajectory(
    task: str,
    messages: list[BaseMessage],
    *,
    min_tool_calls: int = SKILL_INDUCTION_MIN_TOOL_CALLS,
) -> SkillCandidate | None:
    """Distill a reusable skill from a run, or None if it wasn't expensive enough."""
    steps = _successful_tool_calls(messages)
    if len(steps) < min_tool_calls:
        return None

    numbered = "\n".join(
        f"{i}. Call `{name}`" + (f" (args: {', '.join(keys)})" if keys else "")
        for i, (name, keys) in enumerate(steps, 1)
    )
    instructions = (
        f"Use this when the user asks to: {task.strip()}\n\n"
        "Proven tool sequence, learned from a successful run that took "
        f"{len(steps)} steps to work out. Following it directly avoids re-deriving "
        "the approach:\n"
        f"{numbered}\n\n"
        "Adapt the argument values to the specific request; the order and the tools "
        "above are what worked."
    )
    return SkillCandidate(
        name=_slugify(task),
        description=f"Learned procedure for tasks like: {task.strip()[:100]}",
        instructions=instructions,
    )


async def maybe_persist_induced_skill(
    user_id: str,
    task: str,
    messages: list[BaseMessage],
    *,
    min_tool_calls: int = SKILL_INDUCTION_MIN_TOOL_CALLS,
) -> str | None:
    """Best-effort: induce and install a skill for an expensive run. Returns the
    skill name if one was created, else None. Never raises into the caller."""
    from app.agents.skills.installer import install_from_inline

    candidate = induce_skill_from_trajectory(task, messages, min_tool_calls=min_tool_calls)
    if candidate is None:
        return None
    skill = await install_from_inline(
        user_id=user_id,
        name=candidate.name,
        description=candidate.description,
        instructions=candidate.instructions,
        target="executor",
        extra_metadata={"source": "induced", "learned_from_task": task[:200]},
    )
    return skill.name
