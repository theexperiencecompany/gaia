"""Completion-report next-step nudge (retention-loop spec: "Completion reports
carry the next step").

At most one contextual suggestion is appended to a released GAIA-todo's
completion message, only during the user's waking hours. The suggestion is
sourced deterministically — no LLM call — so it never gates or delays
delivery of the completion itself.
"""

from app.constants.todos import (
    NUDGE_OFFER_CANDIDATE_LIMIT,
    is_waking_hour,
)
from app.db.repositories.todos import todo_repository
from app.models.todo_models import ExecutionStatus, Priority, TodoDocument, TodoUpdate

_PRIORITY_RANK: dict[Priority, int] = {
    Priority.HIGH: 3,
    Priority.MEDIUM: 2,
    Priority.LOW: 1,
    Priority.NONE: 0,
}


def _phrase(doc: TodoDocument) -> str:
    """Lowercase-led action phrase for the 'Want me to <phrase>?' template."""
    text = (doc.title or "this").strip().rstrip(".?!")
    if not text:
        return "this"
    return text[0].lower() + text[1:]


async def _find_candidate(user_id: str) -> TodoDocument | None:
    """The next-step suggestion candidate: the oldest open proposal, else the
    highest-priority open user todo GAIA has offered to take over."""
    proposal = await todo_repository.find_oldest_open_proposal(user_id)
    if proposal:
        return proposal
    offers = await todo_repository.list_open_user_todos_with_gaia_offer(
        user_id, limit=NUDGE_OFFER_CANDIDATE_LIMIT
    )
    if not offers:
        return None
    return max(offers, key=lambda doc: _PRIORITY_RANK[doc.priority])


async def maybe_build_completion_nudge(
    *, user_id: str, completed_todo_id: str | None, user_timezone: str | None
) -> str | None:
    """The next-step nudge line for a just-delivered GAIA-todo completion
    message, or ``None`` when the completion doesn't qualify.

    Only fires for a released (user-approved) GAIA todo that finished
    ``done``, during the user's waking hours. Marks the chosen candidate
    ``nudge_shown`` so it is never repeated in a later completion message,
    whether the user acts on it or ignores it.
    """
    if not completed_todo_id or not is_waking_hour(user_timezone):
        return None
    completed = await todo_repository.get(completed_todo_id, user_id=user_id)
    if (
        not completed
        or completed.execution_intent != "release"
        or completed.execution_status != ExecutionStatus.DONE
    ):
        return None
    candidate = await _find_candidate(user_id)
    if not candidate:
        return None
    await todo_repository.update(candidate.id, user_id=user_id, update=TodoUpdate(nudge_shown=True))
    return f"Want me to {_phrase(candidate)}?"
