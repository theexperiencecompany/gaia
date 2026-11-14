"""Todoist through Composio: tasks in Todoist's v1 shape, filters evaluated in the user's local dates."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

from briefsim.world.model import AppState, TodoistTask

JsonObject = dict[str, object]
PROJECTS = {"2300": "Inbox", "2302": "Company"}


def _stamp(at: datetime | None) -> str | None:
    return at.strftime("%Y-%m-%dT%H:%M:%S.000000Z") if at else None


def _render(task: TodoistTask) -> JsonObject:
    due: JsonObject | None = None
    if task.due_date is not None:
        due = {
            "date": task.due_date.isoformat(),
            "string": task.due_date.isoformat(),
            "lang": "en",
            "is_recurring": False,
            "timezone": None,
        }
        if task.due_datetime is not None:
            due["datetime"] = _stamp(task.due_datetime)
    rendered: JsonObject = {
        "id": task.id,
        "description": "",
        "project_id": task.project_id,
        "section_id": None,
        "parent_id": None,
        "labels": [],
        "priority": task.priority,
        "due": due,
        "checked": task.completed_at is not None,
        "is_deleted": task.deleted,
        "added_at": _stamp(task.created),
        "updated_at": _stamp(task.updated),
        "completed_at": _stamp(task.completed_at),
        "user_id": "51234567",
        "note_count": 0,
    }
    if task.content is not None:
        rendered["content"] = task.content
    return rendered


def _open(state: AppState) -> list[TodoistTask]:
    return [t for t in state.todoist.values() if t.completed_at is None and not t.deleted]


def _filter(tasks: list[TodoistTask], query: str, today: date) -> list[TodoistTask]:
    q = query.lower().strip()
    if q in {"", "all", "*"}:
        return tasks
    hits: list[TodoistTask] = []
    for task in tasks:
        due = task.due_date
        days = re.search(r"(\d+)\s*days", q)
        if (
            ("overdue" in q and due is not None and due < today)
            or ("today" in q and due == today)
            or ("tomorrow" in q and due == today + timedelta(days=1))
            or (
                days is not None
                and due is not None
                and today <= due <= today + timedelta(int(days.group(1)))
            )
            or ("no date" in q and due is None)
            or (re.search(r"\bp1\b", q) is not None and task.priority == 4)
        ):
            hits.append(task)
    return hits


def _local_today(timezone: str) -> date:
    return datetime.now(ZoneInfo(timezone)).date()


def _all_tasks(state: AppState, args: JsonObject, timezone: str) -> JsonObject:
    tasks = _open(state)
    if args.get("filter"):
        tasks = _filter(tasks, str(args["filter"]), _local_today(timezone))
    return {"tasks": [_render(t) for t in tasks], "next_cursor": None}


def _filter_tasks(state: AppState, args: JsonObject, timezone: str) -> JsonObject:
    hits = _filter(_open(state), str(args.get("query") or ""), _local_today(timezone))
    return {"results": [_render(t) for t in hits], "next_cursor": None}


def _projects(_state: AppState, _args: JsonObject, _timezone: str) -> JsonObject:
    return {
        "projects": [
            {"id": pid, "name": name, "inbox_project": pid == "2300", "is_archived": False}
            for pid, name in PROJECTS.items()
        ],
        "next_cursor": None,
    }


def _user(_state: AppState, _args: JsonObject, timezone: str) -> JsonObject:
    return {"id": "51234567", "full_name": "Sim Founder", "tz_info": {"timezone": timezone}}


HANDLERS: dict[str, Callable[[AppState, JsonObject, str], JsonObject]] = {
    "TODOIST_GET_ALL_TASKS": _all_tasks,
    "TODOIST_FILTER_TASKS": _filter_tasks,
    "TODOIST_GET_ALL_PROJECTS": _projects,
    "TODOIST_GET_USER": _user,
}
