"""The Inbox desk: one tracked todo per user that triages mail each morning, owns its threads and briefs.

Its operating contract rides on every run (INBOX_DESK_RUN_GUIDANCE), its canvas and
observations.md are its memory, and the briefing is its run's final report. Nothing here
runs mail.
"""

from datetime import UTC, datetime

from app.agents.prompts.todo_prompts import (
    INBOX_DESK_DELIVERY_RULE,
    INBOX_DESK_DESCRIPTION,
    INBOX_DESK_OBSERVATIONS_FILE,
)
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.todos import (
    CANVAS_OBSERVATIONS_SECTION,
    INBOX_DESK_TITLE,
    PROVISION_INBOX_DESK_TASK,
)
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.decorators.entitlements import is_paid
from app.models.todo_models import (
    ExternalRef,
    ExternalRefSource,
    TodoDocument,
    TodoUpdate,
)
from app.models.user_models import UserDocument
from app.services.analytics_service import capture
from app.services.briefing.run_times import inbox_desk_recurrence
from app.services.canvas_markdown import remove_section
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.services.todo_activity import record_field_changes
from app.services.todo_canvas_storage import repair_notes
from app.services.todo_observations import with_carried_lines
from app.services.todos.errors import ExternalRefTakenError
from app.services.tracked_todo_service import starting_canvas, tracked_todo_service
from app.utils.cron_utils import get_next_run_time
from app.utils.redis_utils import RedisPoolManager
from app.utils.timezone import Timezone
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.todos import TodosInboxDeskProvisioned
from shared.py.wide_events import log

INBOX_DESK_REF = ExternalRef(source=ExternalRefSource.INBOX_DESK, id=GMAIL_INTEGRATION_ID)

_PROVISIONED_BY = "GAIA, setting up the Inbox desk"
_FOLLOWED_BY = "GAIA, keeping the Inbox desk ahead of the daily brief"


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
    desk = existing or await _open_desk(user_id, await _desk_schedule(user_id))
    if desk.scheduled_at is None:
        desk = await _rearm(desk, await _desk_schedule(user_id))
    next_run = desk.scheduled_at
    if next_run is None:
        raise LookupError(f"Inbox desk {desk.id} has no next run after it was armed")
    # The job id dedupes an occurrence already queued; a lost job is queued again.
    await tracked_todo_service.schedule_execution(desk.id, next_run)
    log.set_ns("inbox_desk", outcome="armed", todo_id=desk.id, next_run=next_run.isoformat())


async def with_desk_notes(doc: TodoDocument) -> TodoDocument:
    """Return the todo as its run reads it: an Inbox desk gets its observations.md first.

    A desk without one is seeded, and the Observations section older desks kept in
    canvas.md moves into it. Written as a repair, which keeps updated_at; any other
    todo comes back as is.
    """
    if doc.external_ref is None or doc.external_ref.source is not ExternalRefSource.INBOX_DESK:
        return doc
    canvas, carried = remove_section(doc.canvas_content, CANVAS_OBSERVATIONS_SECTION)
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


async def follow_the_brief(user_id: str, before: str, after: str) -> None:
    """Move an open desk sweeping on before, the old brief hour's recurrence, onto after.

    A desk the user moved to a recurrence of their own stays where they put it.
    """
    if before == after:
        return
    desk = await todo_repository.find_latest_by_external_ref(user_id, INBOX_DESK_REF)
    if desk is None or desk.completed or desk.recurrence != before:
        return
    user = await user_repository.get(user_id)
    if user is None:
        raise LookupError(f"Inbox desk {desk.id} belongs to no user {user_id}")
    schedule = _schedule_on(after, user)
    moved = await todo_repository.update(desk.id, user_id=user_id, update=schedule)
    if moved is None or moved.scheduled_at is None:
        raise LookupError(f"Inbox desk {desk.id} vanished while it followed the brief")
    await record_field_changes(desk.id, user_id, schedule, by=_FOLLOWED_BY)
    await tracked_todo_service.schedule_execution(desk.id, moved.scheduled_at)
    log.info("inbox_desk.followed_the_brief", todo_id=desk.id, recurrence=after)


async def _desk_schedule(user_id: str) -> TodoUpdate:
    """Return the desk's daily recurrence, ahead of the user's daily brief, and its next run."""
    user = await user_repository.get(user_id)
    if user is None:
        raise LookupError(f"Cannot schedule an Inbox desk for unknown user {user_id}")
    return _schedule_on(inbox_desk_recurrence(user), user)


def _schedule_on(recurrence: str, user: UserDocument) -> TodoUpdate:
    next_run = get_next_run_time(recurrence, tz=Timezone.parse(user.timezone))
    return TodoUpdate(recurrence=recurrence, scheduled_at=next_run)


async def _open_desk(user_id: str, schedule: TodoUpdate) -> TodoDocument:
    """Create the desk with its schedule, or return the one a concurrent provisioning created."""
    try:
        created = await tracked_todo_service.create_tracked_todo(
            user_id,
            INBOX_DESK_TITLE,
            description=INBOX_DESK_DESCRIPTION,
            initial_canvas=starting_canvas(INBOX_DESK_TITLE, [INBOX_DESK_DELIVERY_RULE]),
            external_ref=INBOX_DESK_REF,
            delivery=WorkflowDelivery.BRIEF,
            schedule=schedule,
        )
    except ExternalRefTakenError as taken:
        return taken.existing
    capture(UserId(user_id), TodosInboxDeskProvisioned())
    desk = await todo_repository.get(created.todo.id, user_id=user_id)
    if desk is None:
        raise LookupError(f"Inbox desk {created.todo.id} vanished right after it was created")
    return desk


async def _rearm(desk: TodoDocument, schedule: TodoUpdate) -> TodoDocument:
    """Give a desk left without a schedule its daily recurrence back, on its timeline."""
    rearmed = await todo_repository.update(desk.id, user_id=desk.user_id, update=schedule)
    if rearmed is None:
        raise LookupError(f"Inbox desk {desk.id} vanished while it was being re-armed")
    await record_field_changes(desk.id, desk.user_id, schedule, by=_PROVISIONED_BY)
    return rearmed
