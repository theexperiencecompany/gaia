"""The Inbox desk: one tracked todo per user that triages mail, owns its threads and briefs each morning.

Its operating contract rides on every run (INBOX_DESK_RUN_GUIDANCE), its canvas and
observations.md are its memory, and the briefing is its run's final report. Nothing here
runs mail.
"""

from datetime import UTC, datetime
from typing import NamedTuple

from app.agents.prompts.todo_prompts import (
    INBOX_DESK_DELIVERY_RULE,
    INBOX_DESK_DESCRIPTION,
    INBOX_DESK_OBSERVATIONS_FILE,
)
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.todos import (
    CANVAS_OBSERVATIONS_SECTION,
    INBOX_DESK_RECURRENCE,
    INBOX_DESK_TITLE,
    PROVISION_INBOX_DESK_TASK,
)
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.decorators.entitlements import is_paid
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument, TodoUpdate
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.canvas_markdown import remove_section
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.services.todo_activity import record_field_changes
from app.services.todo_canvas_storage import repair_notes
from app.services.todo_observations import with_carried_lines
from app.services.todos.errors import ExternalRefTakenError
from app.services.tracked_todo_service import starting_canvas, tracked_todo_service
from app.services.user_service import get_profile_timezone
from app.utils.cron_utils import get_next_run_time
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log

INBOX_DESK_REF = ExternalRef(source=ExternalRefSource.INBOX_DESK, id=GMAIL_INTEGRATION_ID)

_PROVISIONED_BY = "GAIA, setting up the Inbox desk"


async def provision_inbox_desk(user_id: str) -> None:
    """Make sure a Pro user with Gmail has a scheduled Inbox desk; never revive one they stopped.

    Free users get none, as they get no active system workflow. Safe to repeat on every
    Gmail connect or plan start: an open desk is re-armed only when it has no schedule.
    """
    log.set_ns("inbox_desk", operation="provision", user_id=user_id)
    if not await is_paid(user_id):
        log.set_ns("inbox_desk", outcome="skipped_unpaid")
        return
    if GMAIL_INTEGRATION_ID not in await get_connected_integration_ids(user_id):
        log.set_ns("inbox_desk", outcome="skipped_no_gmail")
        return
    existing = await todo_repository.find_latest_by_external_ref(user_id, INBOX_DESK_REF)
    if existing is not None and existing.completed:
        log.set_ns("inbox_desk", outcome="stopped_by_user", todo_id=existing.id)
        return
    desk = existing or await _open_desk(user_id, await _next_morning(user_id))
    if desk.scheduled_at is None:
        desk = await _rearm(desk, await _next_morning(user_id))
    next_run = desk.scheduled_at
    if next_run is None:
        raise LookupError(f"Inbox desk {desk.id} has no next run after it was armed")
    # The job id dedupes an occurrence already queued; a lost job is queued again.
    await tracked_todo_service.schedule_execution(desk.id, next_run)
    log.set_ns("inbox_desk", outcome="armed", todo_id=desk.id, next_run=next_run.isoformat())


class DeskReconcile(NamedTuple):
    """How a reconcile sweep went: the paying Gmail users it visited, and how many failed."""

    users: int
    failures: int


async def reconcile_inbox_desks() -> DeskReconcile:
    """Provision the desk for every paying user who added Gmail; one failure does not stop the rest.

    Catches a provisioning job that never reached the queue, and users whose plan and
    Gmail predate the desk. Safe to repeat: provisioning is idempotent.
    """
    gmail_users = set(
        await user_integration_repository.user_ids_with_integration(GMAIL_INTEGRATION_ID)
    )
    paying = [
        user_id
        for user_id in await subscription_repository.active_user_ids()
        if user_id in gmail_users
    ]
    failures = 0
    for user_id in paying:
        try:
            await provision_inbox_desk(user_id)
        except Exception as e:
            # The error is on the record, and the next daily sweep tries this user again.
            log.error(
                "inbox_desk.reconcile_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            failures += 1
    return DeskReconcile(users=len(paying), failures=failures)


async def with_desk_notes(doc: TodoDocument) -> TodoDocument:
    """Return the todo as its run reads it: an Inbox desk gets its observations.md first.

    A desk without one is seeded, and the Observations section older desks kept in
    canvas.md moves into it. Written as a repair, which keeps updated_at; any other
    todo comes back as is.
    """
    if doc.external_ref is None or doc.external_ref.source is not ExternalRefSource.INBOX_DESK:
        return doc
    canvas, carried = remove_section(doc.canvas_content or "", CANVAS_OBSERVATIONS_SECTION)
    if carried is None and doc.observations_content:
        return doc
    observations = doc.observations_content or INBOX_DESK_OBSERVATIONS_FILE
    if carried is None:
        notes = TodoUpdate(observations_content=observations)
    else:
        today = datetime.now(UTC).date()
        notes = TodoUpdate(
            canvas_content=canvas,
            observations_content=with_carried_lines(observations, carried, today),
        )
    repaired = await repair_notes(doc.id, doc.user_id, notes, expected_updated_at=doc.updated_at)
    if repaired is None:
        raise LookupError(f"Inbox desk {doc.id} changed or vanished while its notes were repaired")
    return repaired


async def queue_inbox_desk_provision(user_id: str) -> None:
    """Hand provision_inbox_desk to the worker, which retries it until the desk is armed."""
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(pool, PROVISION_INBOX_DESK_TASK, user_id)


async def _next_morning(user_id: str) -> datetime:
    return get_next_run_time(INBOX_DESK_RECURRENCE, tz=await get_profile_timezone(user_id))


async def _open_desk(user_id: str, first_run: datetime) -> TodoDocument:
    """Create the desk with its schedule, or return the one a concurrent provisioning created."""
    try:
        created = await tracked_todo_service.create_tracked_todo(
            user_id,
            INBOX_DESK_TITLE,
            description=INBOX_DESK_DESCRIPTION,
            initial_canvas=starting_canvas(INBOX_DESK_TITLE, [INBOX_DESK_DELIVERY_RULE]),
            external_ref=INBOX_DESK_REF,
            notify_on_run=True,
            schedule=TodoUpdate(recurrence=INBOX_DESK_RECURRENCE, scheduled_at=first_run),
        )
    except ExternalRefTakenError as taken:
        return taken.existing
    capture_event(user_id, AnalyticsEvents.INBOX_DESK_PROVISIONED)
    desk = await todo_repository.get(created.id, user_id=user_id)
    if desk is None:
        raise LookupError(f"Inbox desk {created.id} vanished right after it was created")
    return desk


async def _rearm(desk: TodoDocument, next_run: datetime) -> TodoDocument:
    """Give a desk left without a schedule its daily recurrence back, on its timeline."""
    schedule = TodoUpdate(recurrence=INBOX_DESK_RECURRENCE, scheduled_at=next_run)
    rearmed = await todo_repository.update(desk.id, user_id=desk.user_id, update=schedule)
    if rearmed is None:
        raise LookupError(f"Inbox desk {desk.id} vanished while it was being re-armed")
    await record_field_changes(desk.id, desk.user_id, schedule, by=_PROVISIONED_BY)
    return rearmed
