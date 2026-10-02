"""A tracked todo's activity.md as its timeline: the entries code writes.

Every lifecycle event (scheduled, run, delivered, watched, failed, completed)
lands here as "- <iso> [event] detail", so the log is complete whatever the LLM
writes alongside it. Kept below tracked_todo_service so the subscription and
worker layers it imports can record without a cycle.
"""

from datetime import UTC, datetime
from typing import Protocol

from pymongo.errors import PyMongoError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.constants.todos import (
    DURABLE_ACTIVITY_BACKOFF_INITIAL_SECONDS,
    DURABLE_ACTIVITY_BACKOFF_MAX_SECONDS,
    DURABLE_ACTIVITY_WRITE_ATTEMPTS,
    TodoActivityEvent,
)
from app.services.todo_canvas_storage import append_activity
from shared.py.wide_events import log


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


# Copied per write: a tenacity controller carries per-call state.
_DURABLE_WRITE_RETRY = AsyncRetrying(
    stop=stop_after_attempt(DURABLE_ACTIVITY_WRITE_ATTEMPTS),
    wait=wait_exponential_jitter(
        initial=DURABLE_ACTIVITY_BACKOFF_INITIAL_SECONDS, max=DURABLE_ACTIVITY_BACKOFF_MAX_SECONDS
    ),
    retry=retry_if_exception_type(PyMongoError),
    reraise=True,
)


async def record_activity_durably(
    todo_id: str, user_id: str, event: TodoActivityEvent, detail: str
) -> None:
    """Append one entry whose loss matters, retrying a failed write with backoff.

    Raises the last PyMongoError once the attempts run out. A todo deleted
    meanwhile has nowhere to keep the entry, and append_activity says so.
    """
    line = activity_line(event, detail)
    async for attempt in _DURABLE_WRITE_RETRY.copy():
        with attempt:
            await append_activity(todo_id, user_id, line)


class ScheduleFieldChanges(Protocol):
    """The fields of a todo update that change when, whether and how it runs."""

    scheduled_at: datetime | None
    recurrence: str | None
    notify_on_run: bool | None
    expires_at: datetime | None
    due_date: datetime | None

    @property
    def model_fields_set(self) -> set[str]: ...


def _schedule_field_entries(update: ScheduleFieldChanges) -> list[tuple[TodoActivityEvent, str]]:
    """List the activity entries for the scheduling fields an update explicitly set."""
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
    return entries


async def record_field_changes(
    todo_id: str, user_id: str, update: ScheduleFieldChanges, *, by: str
) -> None:
    """Record every scheduling or delivery field an update set, and who set it."""
    for event, detail in _schedule_field_entries(update):
        await record_activity(todo_id, user_id, event, f"{detail}, by {by}")
