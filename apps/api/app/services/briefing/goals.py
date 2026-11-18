"""The goals a user stated: their onboarding focus and what memory says they work toward."""

from dataclasses import dataclass

from app.constants.memory import MemoryKind
from app.memory.engine import memory_engine
from app.memory.mappers import entry_to_note
from app.models.brief_pool_models import GoalOrigin
from app.models.user_models import UserDocument

# Users type junk into onboarding ("nothing", "n/a"); junk is not a goal.
_JUNK_FOCUS_VALUES = {"nothing", "none", "n/a", "na", "-", "idk", "no"}


def has_meaningful_focus(focus: str | None) -> bool:
    """Whether the onboarding focus is a real stated goal (not blank or junk)."""
    cleaned = (focus or "").strip()
    return bool(cleaned) and cleaned.lower() not in _JUNK_FOCUS_VALUES


@dataclass(frozen=True)
class StatedGoal:
    """A goal the user stated, and the names it is about, which link their todos to it."""

    statement: str
    origin: GoalOrigin
    terms: tuple[str, ...] = ()


async def stated_goals(user_id: str, user: UserDocument) -> list[StatedGoal]:
    """Return the onboarding focus, when it is a real goal, then what memory says they work toward."""
    focus = (user.onboarding.focus if user.onboarding else "").strip()
    goals = [StatedGoal(focus, GoalOrigin.ONBOARDING)] if has_meaningful_focus(focus) else []
    result = await memory_engine.recall(
        user_id, "what is the user currently working on and their goals", limit=5
    )
    # A weak fallback recall is whatever memory sat nearest, and an experience is something
    # that happened: neither is what the user works toward.
    recalled = result.memories if result.has_confident_match else []
    for entry in (e for e in recalled if e.kind is MemoryKind.FACT):
        statement = entry_to_note(entry).strip()
        if statement and statement not in {g.statement for g in goals}:
            terms = tuple(entity.name for entity in entry.entities)
            goals.append(StatedGoal(statement, GoalOrigin.MEMORY, terms))
    return goals


def format_goal_block(goals: list[StatedGoal]) -> str:
    """Return the goal block the voice reads; with no goal, the ask to discover one."""
    if not goals:
        return "No stated goal on record yet — treat goal discovery as part of today's job."
    return "\n".join(
        f"Stated goal: {g.statement}" if g.origin is GoalOrigin.ONBOARDING else f"- {g.statement}"
        for g in goals
    )
