"""Silent classification of newly created user todos.

Fire-and-forget after capture (never blocks or fails creation): one small
structured LLM call decides whether GAIA can take the todo over entirely
(``offer`` — a quiet affordance appears on the todo), help with part of it
(``prep`` — supporting material lands in the todo's work log), or do nothing
(``silent`` — no UI change, no message). The not-doable case stays silent by
design: an "I can't help" banner is noise.
"""

import asyncio

from app.agents.llm.client import get_default_llm
from app.agents.llm.exceptions import LLMNotConfiguredError
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoClassificationOutput, TodoUpdate
from shared.py.wide_events import log

_CLASSIFY_TIMEOUT_SECONDS = 20

_CLASSIFY_PROMPT = """You are GAIA, a proactive personal assistant. A user just added a todo.
Decide whether GAIA can do it for them.

- disposition "offer": GAIA can do the WHOLE thing autonomously — research, drafting,
  triage, scheduling, sending (with approval), digital work with clear inputs.
  Write `offer` as one short line, e.g. "I can draft this email — want me to take it?"
- disposition "prep": GAIA can meaningfully help with PART of it (prep notes, research,
  a checklist) but the core act is the user's. Write `prep_note` with that material.
- disposition "silent": physical, personal, ambiguous, or trivial todos ("hit the gym",
  "think about pricing"). No output.

Todo title: {title}
Description: {description}"""


async def classify_new_todo(
    todo_id: str, user_id: str, title: str, description: str | None
) -> None:
    """Classify one user todo and persist the offer/prep outcome onto it."""
    try:
        llm = get_default_llm()
    except LLMNotConfiguredError:
        return
    try:
        structured = llm.with_structured_output(TodoClassificationOutput)
        raw = await asyncio.wait_for(
            structured.ainvoke(
                _CLASSIFY_PROMPT.format(title=title, description=description or "—")
            ),
            timeout=_CLASSIFY_TIMEOUT_SECONDS,
        )
        result = (
            raw
            if isinstance(raw, TodoClassificationOutput)
            else TodoClassificationOutput.model_validate(raw)
        )
    except Exception as e:
        # Classification is a best-effort enhancement over an already-created
        # todo — a miss only costs the offer, so log and stay silent.
        log.warning("todo_classification.failed", todo_id=todo_id, error=str(e))
        return

    if result.disposition == "offer" and result.offer:
        update = TodoUpdate(gaia_offer=result.offer.strip())
    elif result.disposition == "prep" and result.prep_note:
        update = TodoUpdate(notes_content=f"## Prep from GAIA\n\n{result.prep_note.strip()}\n")
    else:
        return
    await todo_repository.update(todo_id, user_id=user_id, update=update)
    log.info("todo_classification.applied", todo_id=todo_id, disposition=result.disposition)


# Strong refs to in-flight classification tasks (asyncio holds only weak refs,
# so an unreferenced task can be garbage-collected mid-flight).
_background_tasks: set[asyncio.Task[None]] = set()


def schedule_classification(
    todo_id: str, user_id: str, title: str, description: str | None
) -> None:
    """Fire-and-forget hook for the create path — never blocks capture."""
    task = asyncio.create_task(classify_new_todo(todo_id, user_id, title, description))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
