"""The Inbox desk: one GAIA system task per user that triages mail each morning, owns its threads and briefs.

Its operating contract rides on every run (INBOX_DESK_RUN_GUIDANCE), its notes and
observations are its memory, and the briefing is its run's final report. Nothing here
runs mail.
"""

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from app.agents.prompts.inbox_desk_prompts import (
    INBOX_DESK_DELIVERY_RULE,
    INBOX_DESK_DESCRIPTION,
    INBOX_DESK_OBSERVATIONS_FILE,
)
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.tasks import INBOX_DESK_SYSTEM_KEY, Assignee, TaskLogEvent
from app.constants.todos import (
    CANVAS_OBSERVATIONS_SECTION,
    INBOX_DESK_RECURRENCE,
    INBOX_DESK_TITLE,
    PROVISION_INBOX_DESK_TASK,
)
from app.db.repositories.tasks import task_repository
from app.decorators.entitlements import is_paid
from app.models.task_models import RepeatWhen, TaskDocument, TaskUpdate
from app.models.todo_models import ExternalRef, ExternalRefSource
from app.services.analytics_service import capture
from app.services.canvas_markdown import remove_section
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.services.tasks.arming import arm_task
from app.services.tasks.gaia_tasks import create_gaia_task
from app.services.tasks.notes import starting_canvas
from app.services.tasks.run_records import record_event
from app.services.tasks.todo_rounds import first_repeat
from app.services.todo_observations import with_carried_lines
from app.services.user_service import get_profile_timezone
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import TaskInboxDeskProvisioned
from shared.py.wide_events import log

INBOX_DESK_REF = ExternalRef(source=ExternalRefSource.INBOX_DESK, id=GMAIL_INTEGRATION_ID)

_PROVISIONED_BY = "GAIA, setting up the Inbox desk"


def is_inbox_desk(task: TaskDocument) -> bool:
    """Whether the task is an Inbox desk, the provisioned one or one the user stopped long ago."""
    return (
        task.external_ref is not None and task.external_ref.source is ExternalRefSource.INBOX_DESK
    )


def stopped_by_user(desk: TaskDocument) -> bool:
    """Say whether the user closed or switched off the desk; GAIA's own pauses lift on their own."""
    return desk.completed or (not desk.active and desk.pause_reason is None)


async def provision_inbox_desk(user_id: str) -> None:
    """Make sure a Pro user with Gmail has a scheduled Inbox desk; never revive one they stopped.

    Free users get none, as they get no active system task. Safe to repeat on every
    Gmail connect or plan start: an open desk is re-armed only when it has no next run.
    """
    log.set_ns("inbox_desk", operation="provision", user_id=user_id)
    if not await is_paid(user_id):
        log.set_ns("inbox_desk", outcome="skipped_unpaid")
        return
    if GMAIL_INTEGRATION_ID not in await get_connected_integration_ids(user_id):
        log.set_ns("inbox_desk", outcome="skipped_no_gmail")
        return
    desk = await task_repository.find_system_task(user_id, INBOX_DESK_SYSTEM_KEY)
    if desk is not None and stopped_by_user(desk):
        log.set_ns("inbox_desk", outcome="stopped_by_user", task_id=desk.id)
        return
    zone = (await get_profile_timezone(user_id)).value
    if desk is None:
        desk = await _open_desk(user_id, zone)
    if not isinstance(desk.when, RepeatWhen):
        raise ValueError(f"Inbox desk {desk.id} does not repeat")
    if desk.when.next_run is None:
        desk = await _rearm(desk, desk.when, zone)
    # Each occurrence's job id dedupes one already queued; a lost job is queued again.
    await arm_task(desk)
    next_run = desk.when.next_run if isinstance(desk.when, RepeatWhen) else None
    log.set_ns(
        "inbox_desk",
        outcome="armed",
        task_id=desk.id,
        next_run=next_run.isoformat() if next_run else None,
    )


async def _open_desk(user_id: str, zone: str) -> TaskDocument:
    """Create the desk with its schedule, or return the one a concurrent provisioning created."""
    draft = TaskDocument(
        user_id=user_id,
        title=INBOX_DESK_TITLE,
        body=INBOX_DESK_DESCRIPTION,
        assignee=Assignee.GAIA,
        when=first_repeat(RepeatWhen(rule=INBOX_DESK_RECURRENCE), zone),
        notes=starting_canvas(INBOX_DESK_TITLE, [INBOX_DESK_DELIVERY_RULE]),
        observations=INBOX_DESK_OBSERVATIONS_FILE,
        external_ref=INBOX_DESK_REF,
        notify=True,
        integration_ids=[GMAIL_INTEGRATION_ID],
        system_key=INBOX_DESK_SYSTEM_KEY,
        source_integration=GMAIL_INTEGRATION_ID,
    )
    try:
        desk = await create_gaia_task(draft, by=_PROVISIONED_BY)
    except DuplicateKeyError:
        twin = await task_repository.find_system_task(user_id, INBOX_DESK_SYSTEM_KEY)
        if twin is None:
            raise
        return twin
    capture(UserId(user_id), TaskInboxDeskProvisioned())
    return desk


async def _rearm(desk: TaskDocument, when: RepeatWhen, zone: str) -> TaskDocument:
    """Give a desk left without a next run its daily one back."""
    rearmed = await task_repository.update(
        desk.id,
        user_id=desk.user_id,
        update=TaskUpdate(when=first_repeat(when, zone), retry_count=0),
    )
    if rearmed is None:
        raise LookupError(f"Inbox desk {desk.id} vanished while it was being re-armed")
    next_run = rearmed.when.next_run if isinstance(rearmed.when, RepeatWhen) else None
    await record_event(
        rearmed,
        TaskLogEvent.SCHEDULED,
        f"next run {next_run.isoformat() if next_run else 'none'}, by {_PROVISIONED_BY}",
    )
    return rearmed


async def with_desk_notes(task: TaskDocument) -> TaskDocument:
    """Return the task as its run reads it: an Inbox desk gets its observations first.

    A desk without them is seeded, and the Observations section older desks kept in
    their notes moves into them. Written as a repair, which keeps updated_at; any other
    task comes back as is.
    """
    if not is_inbox_desk(task):
        return task
    notes, carried = remove_section(task.notes, CANVAS_OBSERVATIONS_SECTION)
    if carried is None and task.observations:
        return task
    observations = task.observations or INBOX_DESK_OBSERVATIONS_FILE
    repair = (
        TaskUpdate(observations=observations)
        if carried is None
        else TaskUpdate(
            notes=notes,
            observations=with_carried_lines(observations, carried, datetime.now(UTC).date()),
        )
    )
    repaired = await task_repository.replace_notes(
        task.id, task.user_id, update=repair, expected_updated_at=task.updated_at, touch=False
    )
    if repaired is None:
        raise LookupError(f"Inbox desk {task.id} changed or vanished while its notes were repaired")
    return repaired


async def queue_inbox_desk_provision(user_id: str) -> None:
    """Hand provision_inbox_desk to the worker, which retries it until the desk is armed."""
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(pool, PROVISION_INBOX_DESK_TASK, user_id)
