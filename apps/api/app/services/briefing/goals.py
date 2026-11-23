"""The goals a user stated: what memory says they work toward."""

from dataclasses import dataclass

from app.constants.memory import MemoryKind
from app.memory.engine import memory_engine
from app.models.memory_models import MemoryEntry
from app.services.briefing.formats import dated


@dataclass(frozen=True)
class StatedGoal:
    """A goal the user stated, and the names it is about, which link their todos to it."""

    statement: str
    terms: tuple[str, ...] = ()


async def stated_goals(user_id: str) -> list[StatedGoal]:
    """Return what memory says the user works toward."""
    goals: list[StatedGoal] = []
    result = await memory_engine.recall(
        user_id, "what is the user currently working on and their goals", limit=5
    )
    # A weak fallback recall is whatever memory sat nearest, and an experience is something
    # that happened: neither is what the user works toward.
    recalled = result.memories if result.has_confident_match else []
    for entry in (e for e in recalled if e.kind is MemoryKind.FACT):
        statement = _remembered(entry)
        if statement and statement not in {g.statement for g in goals}:
            terms = tuple(entity.name for entity in entry.entities)
            goals.append(StatedGoal(statement, terms))
    return goals


def _remembered(entry: MemoryEntry) -> str:
    """Say a remembered goal with the day it was mentioned, as the brief writes a day, so prose may quote it."""
    content = entry.content.strip()
    mentioned = entry.mentioned_at or entry.created_at
    return f"{content} [mentioned {dated(mentioned.date())}]" if content and mentioned else content


def format_goal_block(goals: list[StatedGoal]) -> str:
    """Return the goal block the voice reads; with no goal, the ask to discover one."""
    if not goals:
        return "No stated goal on record yet — treat goal discovery as part of today's job."
    return "\n".join(f"- {g.statement}" for g in goals)
