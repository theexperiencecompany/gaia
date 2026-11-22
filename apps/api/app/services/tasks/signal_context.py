"""Render a user's open GAIA tasks as signal-matching prompt context for a workflow's trigger run.

It reads tasks and nothing else, so the trigger dispatch path can build this context
without importing the task lifecycle, which imports the trigger stack back.
"""

import re

from app.db.repositories.tasks import task_repository
from app.models.task_models import TaskDocument

_KEY_DETAILS_RE = re.compile(r"## Key Details\n((?:(?!\n## ).)*)", re.DOTALL)
_KEY_DETAILS_MAX_LINES = 5
_SIGNAL_CONTEXT_TASK_LIMIT = 15


def _key_details(task: TaskDocument) -> str:
    match = _KEY_DETAILS_RE.search(task.notes or "")
    return match.group(1).strip() if match else ""


def _format_signal_entry(task: TaskDocument) -> str:
    """Render one GAIA task as a signal-matching bullet, with its key details indented under it."""
    flags = f" [{', '.join(flag.value for flag in task.status_flags)}]" if task.status_flags else ""
    entry = f'- "{task.title}"{flags} (ID: {task.id})'
    if details := _key_details(task):
        for line in details.split("\n")[:_KEY_DETAILS_MAX_LINES]:
            entry += f"\n    {line.strip()}"
    return entry


async def get_signal_matching_context(user_id: str) -> str:
    """List the user's open GAIA tasks with the ids an incoming signal can be matched by.

    Each carries its Key Details (thread ids, email addresses, event ids) from its notes.
    """
    tasks = await task_repository.list_open_gaia(user_id, limit=_SIGNAL_CONTEXT_TASK_LIMIT)
    if not tasks:
        return ""
    lines = [_format_signal_entry(task) for task in tasks]
    return "OPEN GAIA TASKS (check if incoming signal relates to any):\n" + "\n".join(lines)
