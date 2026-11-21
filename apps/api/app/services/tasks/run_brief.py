"""What a GAIA task's run is briefed with: the task, its notes, its family and its history.

The parent's Standing rules govern a subtask's run, so a failed read of them raises and
the run retries with its rules. The subtasks' states and the referenced tasks' Learnings
only enrich the brief: a failed read of either is logged and left out.
"""

import asyncio
from datetime import datetime
from typing import NamedTuple

from app.agents.prompts.task_prompts import (
    DELIVERED_RESULT_GUIDANCE,
    DELIVERED_RESULT_RULES,
    PARENT_NEXT_RUN_LINE,
    PARENT_STANDING_RULES_LABEL,
    SILENT_RUN_GUIDANCE,
    SUBTASKS_CUT_NOTE,
    SUBTASKS_LABEL,
    TASK_ID_LINE,
    TASK_REARM_BRIEF,
    TASK_WAKES_AGAIN_BRIEF,
    WAKE_REASON_TEXT,
)
from app.constants.tasks import RECENT_RUNS_READ, Assignee, WhenKind
from app.constants.todos import (
    ACTIVITY_PROMPT_TAIL_CHARS,
    CANVAS_CURRENT_STATE_SECTION,
    CANVAS_LEARNINGS_SECTION,
    CANVAS_STANDING_RULES_SECTION,
    MAX_HOLD_CHECK_AHEAD,
    MAX_HOLD_CHECKS,
    REFERENCED_TODOS_PROMPT_LIMIT,
    STANDING_RULES_MAX_CHARS,
    SUB_TODO_STATE_EXCERPT_CHARS,
    SUB_TODOS_PROMPT_LIMIT,
)
from app.db.repositories.task_runs import task_run_repository
from app.db.repositories.tasks import task_repository
from app.models.task_models import RepeatWhen, TaskDocument
from app.services.canvas_markdown import bounded_canvas, section_body
from app.services.tasks.open_state import no_reply_plan_words, wake_reason
from app.services.todo_observations import bounded_observations
from app.utils.general_utils import clip_text
from app.utils.timezone import Timezone
from shared.py.wide_events import log


class RunContext(NamedTuple):
    """What a run reads beyond its own task: its parent's rules, its subtasks, past lessons."""

    parent_rules: str = ""
    #: When the parent runs next, on the user's clock; "" for a task with no scheduled parent.
    parent_next_run: str = ""
    subtasks: str = ""
    learnings: str = ""
    recent_runs: str = ""


async def collect_run_context(task: TaskDocument, user_tz: Timezone) -> RunContext:
    """Gather everything a run reads from the owner's other tasks and the task's own runs."""
    parent_rules, parent_next_run = await _parent_context(task, user_tz)
    enrichments = await asyncio.gather(
        _subtask_states(task),
        _reference_learnings(task),
        _recent_runs(task),
        return_exceptions=True,
    )
    read: list[str] = []
    for name, result in zip(("subtasks", "learnings", "recent_runs"), enrichments, strict=True):
        if isinstance(result, str):
            read.append(result)
            continue
        log.warning(
            "task.run_context_incomplete",
            task_id=task.id,
            section=name,
            error=str(result),
            error_type=type(result).__name__,
        )
        read.append("")
    subtasks, learnings, recent_runs = read
    return RunContext(parent_rules, parent_next_run, subtasks, learnings, recent_runs)


async def _parent_context(task: TaskDocument, user_tz: Timezone) -> tuple[str, str]:
    """Render the parent's Standing rules and its next run on the user's clock."""
    if task.parent_id is None:
        return "", ""
    parent = await task_repository.get(task.parent_id, user_id=task.user_id)
    if parent is None:
        return "", ""
    rules = section_body(parent.notes, CANVAS_STANDING_RULES_SECTION)
    rules_block = (
        f'{PARENT_STANDING_RULES_LABEL}\nFrom "{parent.title}":\n{rules[:STANDING_RULES_MAX_CHARS]}'
        if rules
        else ""
    )
    parent_next = _next_time(parent)
    next_run = (
        PARENT_NEXT_RUN_LINE.format(
            title=parent.title, when=user_tz.format(parent_next, "%a %d %b, %H:%M")
        )
        if parent_next is not None
        else ""
    )
    return rules_block, next_run


def _next_time(task: TaskDocument) -> datetime | None:
    return task.when.next_run if isinstance(task.when, RepeatWhen) else task.next_check_at


async def _subtask_states(task: TaskDocument) -> str:
    """Each open GAIA subtask's Current State: a subtask reports here, not to the user."""
    if task.parent_id is not None:
        return ""  # one level deep: a subtask has no subtasks to read
    # One past the limit tells a full page from a cut one.
    children = await task_repository.list_open_gaia(
        task.user_id, limit=SUB_TODOS_PROMPT_LIMIT + 1, parent_id=task.id
    )
    blocks = [_subtask_block(child) for child in children[:SUB_TODOS_PROMPT_LIMIT]]
    if len(children) > SUB_TODOS_PROMPT_LIMIT:
        blocks.append(SUBTASKS_CUT_NOTE.format(limit=SUB_TODOS_PROMPT_LIMIT, task_id=task.id))
    return _labelled(SUBTASKS_LABEL, blocks, "\n")


def _subtask_block(child: TaskDocument) -> str:
    flags = (
        f" [{', '.join(flag.value for flag in child.status_flags)}]" if child.status_flags else ""
    )
    state = section_body(child.notes, CANVAS_CURRENT_STATE_SECTION)
    return (
        f'- "{child.title}"{flags} (ID: {child.id})\n'
        f"  Current State: {clip_text(state or '(empty)', SUB_TODO_STATE_EXCERPT_CHARS)}"
    )


async def _reference_learnings(task: TaskDocument) -> str:
    """Gather Learnings from the first referenced tasks the user owns."""
    wanted = task.references[:REFERENCED_TODOS_PROMPT_LIMIT]
    if not wanted:
        return ""
    owned = {ref.id: ref for ref in await task_repository.find_by_ids(task.user_id, wanted)}
    learnings = [
        f'From past task "{ref.title}":\n## {CANVAS_LEARNINGS_SECTION}\n{ref_learnings}'
        for ref in (owned[ref_id] for ref_id in wanted if ref_id in owned)
        if (ref_learnings := section_body(ref.notes, CANVAS_LEARNINGS_SECTION))
    ]
    return _labelled("Past experience (from similar completed tasks):", learnings)


async def _recent_runs(task: TaskDocument) -> str:
    """List what came of the task's last runs, oldest first."""
    runs = await task_run_repository.latest_finished(task.id, task.user_id, limit=RECENT_RUNS_READ)
    lines = [
        f"- {run.started_at.isoformat()} {run.status.value if run.status else 'history'}: "
        f"{run.summary or run.error_message or ''}".rstrip()
        for run in reversed(runs)
    ]
    return _labelled("Recent runs:", lines, "\n")


def _labelled(label: str, blocks: list[str], joiner: str = "\n\n") -> str:
    return f"{label}\n" + joiner.join(blocks) if blocks else ""


def _delivery_guidance(task: TaskDocument) -> str:
    """State where the run's final report goes; a kind that sets its own report form gets no second one."""
    if not task.notify:
        return SILENT_RUN_GUIDANCE
    if task.external_ref is not None and task.external_ref.source.owns_report_form:
        return DELIVERED_RESULT_RULES
    return DELIVERED_RESULT_GUIDANCE


def wake_text(task: TaskDocument) -> str:
    """Say why this scheduled run woke, with what was decided earlier and the budget left."""
    asked = task.waiting.question if task.waiting else None
    return WAKE_REASON_TEXT[wake_reason(task)].format(
        question=asked.text if asked else "",
        plan=no_reply_plan_words(task),
        hold_checks=asked.hold_checks if asked else 0,
        max_hold_checks=MAX_HOLD_CHECKS,
        hold_days=MAX_HOLD_CHECK_AHEAD.days,
    )


def build_scheduled_brief(task: TaskDocument, context: RunContext) -> str:
    """Assemble a scheduled run's brief from the task, its notes and what it reads beyond them."""
    if task.assignee is not Assignee.GAIA:
        raise ValueError(f"task {task.id} is a to-do; only GAIA's tasks are run")
    parts = [
        f"Execute the following scheduled task: {task.title}",
        TASK_ID_LINE.format(task_id=task.id),
    ]
    if task.body:
        parts.append(f"Details: {task.body}")
    if task.notes:
        parts.append(f"Notes (canvas.md):\n{bounded_canvas(task.notes)}")
    if task.observations:
        parts.append(f"Observations (observations.md):\n{bounded_observations(task.observations)}")
    parts.extend(
        part for part in (context.parent_rules, context.parent_next_run, context.subtasks) if part
    )
    if task.log:
        tail = task.log[-ACTIVITY_PROMPT_TAIL_CHARS:]
        label = "Recent activity (activity.md)"
        if len(task.log) > len(tail):
            label += " (older entries omitted; read activity.md for the full log)"
        parts.append(f"{label}:\n{tail}")
    parts.extend(part for part in (context.recent_runs, context.learnings) if part)
    # Only a repeat wakes the task again on a schedule; a one-off's check is spent by this run.
    if task.when.kind is WhenKind.REPEAT:
        parts.append(TASK_WAKES_AGAIN_BRIEF)
    else:
        parts.append(TASK_REARM_BRIEF.format(why=wake_text(task)))
    parts.append(_delivery_guidance(task))
    return "\n\n".join(parts)
