"""The agent's read tools on tasks: the list, its day views and counts, and one task in full."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.constants.tasks import TASK_SEARCH_EXCERPT_CHARS, Assignee
from app.db.repositories.tasks import task_repository
from app.decorators import with_doc
from app.models.agent_models import get_user_id
from app.models.task_models import DateWhen, RepeatWhen, TaskDocument, TaskQuery
from app.models.todo_models import TodoDayWindow
from app.services.tasks import search_index, task_service
from app.services.tasks.errors import TaskNotFoundError
from app.services.tasks.open_state import describe_open_state
from app.services.user_service import get_profile_timezone
from app.templates.docstrings.task_tool_docs import GET_TASK, LIST_TASKS, SEARCH_TASKS
from app.utils.timezone import Timezone

#: Which slice of the user's tasks list_tasks shows.
TaskView = Literal["open", "today", "upcoming", "overdue", "done"]
#: The most tasks one list_tasks call returns.
LIST_TASKS_LIMIT = 50


def _query(view: TaskView, window: TodoDayWindow, **narrowing: object) -> TaskQuery:
    """The list read behind a view, on the user's own day."""
    by_view: dict[TaskView, dict[str, object]] = {
        "open": {"completed": False},
        "today": {
            "completed": False,
            "due_after": window.today_start,
            "due_before": window.tomorrow_start,
        },
        "upcoming": {
            "completed": False,
            "due_after": window.tomorrow_start,
            "due_before": window.upcoming_end,
        },
        "overdue": {"overdue": True},
        "done": {"completed": True},
    }
    return TaskQuery.model_validate(
        {
            **by_view[view],
            **{k: v for k, v in narrowing.items() if v is not None},
            "day_window": window,
            "per_page": LIST_TASKS_LIMIT,
        }
    )


def _when_text(task: TaskDocument, zone: Timezone) -> str | None:
    match task.when:
        case DateWhen(at=at):
            return f"due {at.astimezone(zone.tzinfo).isoformat(timespec='minutes')}"
        case RepeatWhen(rule=rule, next_run=next_run):
            upcoming = (
                next_run.astimezone(zone.tzinfo).isoformat(timespec="minutes") if next_run else None
            )
            return f"repeats {rule}" + (f", next {upcoming}" if upcoming else "")
    return None


def _line(task: TaskDocument, zone: Timezone, now: datetime) -> str:
    """One task as a list line: done box, title, id, whose, when, checklist, state."""
    parts = [
        f"- [{'x' if task.completed else ' '}] {task.title} (id {task.id})",
        "GAIA's" if task.assignee is Assignee.GAIA else "the user's to-do",
    ]
    if when := _when_text(task, zone):
        parts.append(when)
    if task.subtasks:
        ticked = sum(item.completed for item in task.subtasks)
        parts.append(f"checklist {ticked}/{len(task.subtasks)}")
    if task.parent_id:
        parts.append(f"subtask of {task.parent_id}")
    if task.assignee is Assignee.GAIA and not task.completed:
        parts.append(describe_open_state(task, now))
    return " · ".join(parts)


@tool
@with_doc(LIST_TASKS)
async def list_tasks(
    config: RunnableConfig,
    view: Annotated[
        TaskView,
        "'open' (default), 'today' (due today, the user's day), 'upcoming' (due in the next "
        "days), 'overdue', or 'done'",
    ] = "open",
    query: Annotated[str | None, "Only tasks whose title or details contain this text"] = None,
    assignee: Annotated[
        Assignee | None, "'gaia' for GAIA's work only, 'user' for the user's own to-dos only"
    ] = None,
    parent_id: Annotated[str | None, "Only the subtasks of this task"] = None,
) -> str:
    user_id = get_user_id(config)
    zone = await get_profile_timezone(user_id)
    now = datetime.now(UTC)
    window = TodoDayWindow.for_timezone(zone, now)
    page = await task_service.list_tasks(
        user_id, _query(view, window, q=query, assignee=assignee, parent_id=parent_id)
    )
    counts = await task_service.task_counts(user_id, window)
    header = (
        f"Open: {counts.today} due today, {counts.overdue} overdue, {counts.upcoming} "
        f"upcoming; {counts.completed} done."
    )
    if not page.items:
        return f"{header}\nNo {view} tasks match."
    shown = f"{view} tasks ({len(page.items)} of {page.total}):"
    return "\n".join([header, shown, *(_line(task, zone, now) for task in page.items)])


def _excerpt(task: TaskDocument) -> str | None:
    """What the task holds beyond its title: GAIA's notes, else its details, cut short."""
    text = (task.notes or task.body).strip()
    if not text:
        return None
    cut = text[:TASK_SEARCH_EXCERPT_CHARS]
    return f"  {cut}{'…' if len(text) > len(cut) else ''}"


@tool
@with_doc(SEARCH_TASKS)
async def search_tasks(
    config: RunnableConfig,
    query: Annotated[str, "What to look for, in the user's words or your own: its meaning counts"],
    assignee: Annotated[
        Assignee | None, "'gaia' for GAIA's work only, 'user' for the user's own to-dos only"
    ] = None,
    include_done: Annotated[bool, "Also search finished tasks, for what was learned"] = True,
    parent_id: Annotated[str | None, "Only the subtasks of this task"] = None,
) -> str:
    user_id = get_user_id(config)
    matches = await search_index.search_tasks(
        user_id, query, assignee=assignee, include_done=include_done, parent_id=parent_id
    )
    found = {
        task.id: task
        for task in await task_repository.find_by_ids(user_id, [m.task_id for m in matches])
    }
    ranked = [found[m.task_id] for m in matches if m.task_id in found]
    if not ranked:
        return "No task matches."
    zone = await get_profile_timezone(user_id)
    now = datetime.now(UTC)
    lines = [f"Tasks nearest in meaning, nearest first ({len(ranked)}):"]
    for task in ranked:
        lines.append(_line(task, zone, now))
        if excerpt := _excerpt(task):
            lines.append(excerpt)
    return "\n".join(lines)


@tool
@with_doc(GET_TASK)
async def get_task(
    config: RunnableConfig, task_id: Annotated[str, "Id of the task, from list_tasks"]
) -> str:
    user_id = get_user_id(config)
    try:
        task = await task_service.require_task(user_id, task_id)
    except TaskNotFoundError as missing:
        return f"Error: {missing.message}"
    zone = await get_profile_timezone(user_id)
    lines = [_line(task, zone, datetime.now(UTC))]
    if task.body:
        lines.append(f"Details: {task.body}")
    lines.extend(
        f"  - [{'x' if item.completed else ' '}] {item.title} (item id {item.id})"
        for item in task.subtasks
    )
    lines.extend(
        f"Listens for {sub.trigger_name}: {sub.action.value} (subscription id {sub.id})"
        for sub in task.subscriptions
    )
    for heading, text in (
        ("Notes", task.notes),
        ("Observations", task.observations),
        ("Log", task.log),
    ):
        if text:
            lines.append(f"{heading}:\n{text}")
    return "\n".join(lines)


tools = [list_tasks, search_tasks, get_task]
