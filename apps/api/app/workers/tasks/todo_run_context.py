"""What a tracked-todo run reads from the owner's other todos.

The parent's Standing rules govern the run; the sub-todo states and reference
Learnings enrich its prompt. A failed enrichment read degrades to empty and is
logged; a failed parent-rules read raises so the run retries with its rules.
"""

import asyncio

from app.agents.prompts.todo_prompts import (
    PARENT_STANDING_RULES_LABEL,
    SUB_TODOS_CUT_NOTE,
    SUB_TODOS_LABEL,
)
from app.constants.todos import (
    CANVAS_CURRENT_STATE_SECTION,
    CANVAS_LEARNINGS_SECTION,
    CANVAS_STANDING_RULES_SECTION,
    GAIA_TRACKED_LABEL,
    REFERENCED_TODOS_PROMPT_LIMIT,
    STANDING_RULES_MAX_CHARS,
    SUB_TODO_STATE_EXCERPT_CHARS,
    SUB_TODOS_PROMPT_LIMIT,
)
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument, TodoRunContext
from app.services.canvas_markdown import section_body
from app.utils.general_utils import clip_text


class TodoRunContext(NamedTuple):
    """What a run reads from other todos: its parent's rules, its sub-todos, past lessons."""

    parent_rules: str = ""
    sub_todos: str = ""
    learnings: str = ""


async def collect_run_context(doc: TodoDocument) -> TodoRunContext:
    """Gather everything a run reads from the owner's other todos.

    The parent's Standing rules govern the run, so their read failure raises
    and the run retries with backoff rather than acting without instructions
    it must obey. The other two reads are enrichment: a failed one degrades
    to "" and is logged, so a Mongo blip does not burn the run's retries.
    """
    parent_rules = await collect_parent_rules(doc.parent_todo_id, doc.user_id)
    sub_todos, learnings = await asyncio.gather(
        collect_sub_todo_states(doc),
        collect_reference_learnings(doc.references, doc.user_id),
        return_exceptions=True,
    )
    context = {"sub_todos": sub_todos, "learnings": learnings}
    degraded: dict[str, str] = {}
    for name, result in context.items():
        if isinstance(result, str):
            degraded[name] = result
            continue
        log.warning(
            "tracked_todo.run_context_incomplete",
            todo_id=doc.id,
            section=name,
            error=str(result),
            error_type=type(result).__name__,
        )
        degraded[name] = ""
    return TodoRunContext(parent_rules=parent_rules, **degraded)


async def collect_parent_rules(parent_todo_id: str | None, user_id: str) -> str:
    """Render the parent's Standing rules, which a sub-todo's run obeys like its own."""
    if parent_todo_id is None:
        return ""
    parent = await todo_repository.get(parent_todo_id, user_id=user_id)
    if parent is None:
        return ""
    rules = section_body(parent.canvas_content, CANVAS_STANDING_RULES_SECTION)
    if not rules:
        return ""
    return (
        f'{PARENT_STANDING_RULES_LABEL}\nFrom "{parent.title}":\n{rules[:STANDING_RULES_MAX_CHARS]}'
    )


async def collect_sub_todo_states(doc: TodoDocument) -> str:
    """Each open sub-todo's Current State: a sub-todo reports here, not to the user."""
    if doc.parent_todo_id is not None:
        return ""  # one level deep: a sub-todo has no sub-todos to read
    # One past the limit tells a full page from a cut one.
    children = await todo_repository.list_active_tracked(
        doc.user_id, limit=SUB_TODOS_PROMPT_LIMIT + 1, parent_todo_id=doc.id
    )
    blocks = [sub_todo_block(child) for child in children[:SUB_TODOS_PROMPT_LIMIT]]
    if len(children) > SUB_TODOS_PROMPT_LIMIT:
        blocks.append(SUB_TODOS_CUT_NOTE.format(limit=SUB_TODOS_PROMPT_LIMIT, todo_id=doc.id))
    return labelled(SUB_TODOS_LABEL, blocks, "\n")


def sub_todo_block(child: TodoDocument) -> str:
    labels = [label for label in child.labels if label != GAIA_TRACKED_LABEL]
    labels_str = f" [{', '.join(labels)}]" if labels else ""
    state = section_body(child.canvas_content, CANVAS_CURRENT_STATE_SECTION)
    return (
        f'- "{child.title}"{labels_str} (ID: {child.id})\n'
        f"  Current State: {clip_text(state or '(empty)', SUB_TODO_STATE_EXCERPT_CHARS)}"
    )


async def collect_reference_learnings(ref_ids: list[str], user_id: str) -> str:
    """Gather Learnings from the first referenced todos the user owns."""
    wanted = [
        ref for ref in ref_ids[:REFERENCED_TODOS_PROMPT_LIMIT] if todo_repository.is_valid_id(ref)
    ]
    if not wanted:
        return ""
    owned = {doc.id: doc for doc in await todo_repository.find_by_ids(user_id, wanted)}
    learnings = [
        f'From past todo "{doc.title}":\n## {CANVAS_LEARNINGS_SECTION}\n{ref_learnings}'
        for doc in (owned[ref] for ref in wanted if ref in owned)
        if (ref_learnings := section_body(doc.canvas_content, CANVAS_LEARNINGS_SECTION))
    ]
    return labelled("Past experience (from similar completed todos):", learnings)


def labelled(label: str, blocks: list[str], joiner: str = "\n\n") -> str:
    """Join blocks under their label, or nothing when there are none."""
    return f"{label}\n" + joiner.join(blocks) if blocks else ""


NO_CONTEXT = TodoRunContext()
