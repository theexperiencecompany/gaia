"""A tracked todo's activity.md as its timeline: the entries code writes.

Every lifecycle event (scheduled, run, delivered, watched, failed, completed)
lands here as "- <iso> [event] detail", so the log is complete whatever the LLM
writes alongside it. Kept below tracked_todo_service so the subscription and
worker layers it imports can record without a cycle.
"""

from datetime import UTC, datetime
import re
from typing import Protocol

from app.constants.todos import TodoActivityEvent
from app.services.todo_canvas_storage import append_activity
from shared.py.wide_events import log

#: An activity.md line that opens with its own date and time is one record: the same line
#: twice is the same entry twice, whoever wrote it.
TIMESTAMPED_ENTRY = re.compile(r"^- \d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def activity_line(event: TodoActivityEvent, detail: str, at: datetime | None = None) -> str:
    """Format one code-written activity.md entry: "- <iso> [event] detail"."""
    stamp = (at or datetime.now(UTC)).isoformat()
    return f"- {stamp} [{event.value}] {detail}".rstrip()


async def record_activity(
    todo_id: str, user_id: str, event: TodoActivityEvent, detail: str
) -> bool:
    """Append one timestamped lifecycle entry to activity.md; never raises.

    A failed append costs the entry, not the operation it records.
    """
    try:
        return await append_activity(todo_id, user_id, activity_line(event, detail))
    except Exception as e:
        log.warning(
            "tracked_todo.activity_append_failed",
            todo_id=todo_id,
            activity_event=event.value,
            error_type=type(e).__name__,
        )
        return False


class ScheduleFieldChanges(Protocol):
    """The fields of a todo update that change when, whether and how it runs."""

    scheduled_at: datetime | None
    recurrence: str | None
    notify_on_run: bool | None
    expires_at: datetime | None
    due_date: datetime | None

    @property
    def model_fields_set(self) -> set[str]: ...


def _schedule_field_entries(
    update: ScheduleFieldChanges, *, by: str
) -> list[tuple[TodoActivityEvent, str]]:
    """List the activity entries for the scheduling fields an update explicitly set, and who set them."""
    fields = update.model_fields_set
    entries: list[tuple[TodoActivityEvent, str]] = []
    if "scheduled_at" in fields:
        entries.append(
            (TodoActivityEvent.SCHEDULED, f"run at {update.scheduled_at.isoformat()}")
            if update.scheduled_at
            else (TodoActivityEvent.SCHEDULE_CLEARED, "no run scheduled")
        )
    if "recurrence" in fields:
        detail = f"repeats {update.recurrence}" if update.recurrence else "no longer repeats"
        entries.append((TodoActivityEvent.RECURRENCE_CHANGED, detail))
    if "notify_on_run" in fields and update.notify_on_run is not None:
        detail = (
            "runs may message the user" if update.notify_on_run else "runs never message the user"
        )
        entries.append((TodoActivityEvent.DELIVERY_CHANGED, detail))
    if "expires_at" in fields:
        detail = f"expires {update.expires_at.isoformat()}" if update.expires_at else "no expiry"
        entries.append((TodoActivityEvent.EXPIRY_CHANGED, detail))
    if "due_date" in fields:
        detail = f"due {update.due_date.isoformat()}" if update.due_date else "no due date"
        entries.append((TodoActivityEvent.DUE_DATE_CHANGED, detail))
    return [(event, f"{detail}, by {by}") for event, detail in entries]


async def record_field_changes(
    todo_id: str, user_id: str, update: ScheduleFieldChanges, *, by: str
) -> None:
    """Record every scheduling or delivery field an update set, and who set it."""
    for event, detail in _schedule_field_entries(update, by=by):
        await record_activity(todo_id, user_id, event, detail)


def field_change_lines(update: ScheduleFieldChanges, *, by: str, at: datetime) -> list[str]:
    """Format the entries record_field_changes appends, for a write that saves them itself."""
    return [
        activity_line(event, detail, at=at)
        for event, detail in _schedule_field_entries(update, by=by)
    ]


def agent_actor(conversation_id: str | None) -> str:
    """Name who made a change from inside an agent run, for the todo's activity log."""
    return f"GAIA in conversation {conversation_id[:8]}" if conversation_id else "GAIA"
