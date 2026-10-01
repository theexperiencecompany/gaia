"""The Inbox desk: one tracked todo per user that triages mail, owns its threads and briefs each morning.

Its operating contract rides on every run (INBOX_DESK_RUN_GUIDANCE), its canvas is its
memory, and the briefing is its run's final report. Nothing here runs mail.
"""

from datetime import datetime

from app.agents.prompts.todo_prompts import INBOX_DESK_DELIVERY_RULE, INBOX_DESK_DESCRIPTION
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.todos import INBOX_DESK_RECURRENCE, INBOX_DESK_TITLE
from app.db.repositories.todos import todo_repository
from app.decorators.entitlements import is_paid
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument, TodoUpdate
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.services.todos.errors import ExternalRefTakenError
from app.services.tracked_todo_service import starting_canvas, tracked_todo_service
from app.services.user_service import get_profile_timezone
from app.utils.cron_utils import get_next_run_time
from shared.py.wide_events import log

INBOX_DESK_REF = ExternalRef(source=ExternalRefSource.INBOX_DESK, id=GMAIL_INTEGRATION_ID)

_PROVISIONED_BY = "GAIA, setting up the Inbox desk"


async def provision_inbox_desk(user_id: str) -> None:
    """Make sure a Pro user with Gmail has a scheduled Inbox desk; never revive one they stopped.

    Free users get none, as they get no active system workflow. Safe to call on every
    Gmail connect: an open desk is only re-armed when it has no schedule.
    """
    log.set_ns("inbox_desk", operation="provision", user_id=user_id)
    if not await is_paid(user_id):
        log.set_ns("inbox_desk", outcome="skipped_unpaid")
        return
    existing = await todo_repository.find_latest_by_external_ref(user_id, INBOX_DESK_REF)
    if existing is not None and existing.completed:
        log.set_ns("inbox_desk", outcome="stopped_by_user", todo_id=existing.id)
        return
    desk = existing or await _open_desk(user_id)
    if desk.scheduled_at is not None:
        log.set_ns("inbox_desk", outcome="exists", todo_id=desk.id)
        return
    first_run = await _arm(desk.id, user_id)
    log.set_ns("inbox_desk", outcome="armed", todo_id=desk.id, first_run=first_run.isoformat())


async def provision_inbox_desk_for_gmail_user(user_id: str) -> None:
    """Give a user who connected Gmail before paying the desk their connect could not open."""
    if GMAIL_INTEGRATION_ID in await get_connected_integration_ids(user_id):
        await provision_inbox_desk(user_id)


async def _open_desk(user_id: str) -> TodoDocument:
    """Create the desk, or return the one a concurrent provisioning created first."""
    try:
        created = await tracked_todo_service.create_tracked_todo(
            user_id,
            INBOX_DESK_TITLE,
            description=INBOX_DESK_DESCRIPTION,
            initial_canvas=starting_canvas(INBOX_DESK_TITLE, [INBOX_DESK_DELIVERY_RULE]),
            external_ref=INBOX_DESK_REF,
            notify_on_run=True,
        )
    except ExternalRefTakenError as taken:
        return taken.existing
    capture_event(user_id, AnalyticsEvents.INBOX_DESK_PROVISIONED)
    desk = await todo_repository.get(created.id, user_id=user_id)
    if desk is None:
        raise LookupError(f"Inbox desk {created.id} vanished right after it was created")
    return desk


async def _arm(desk_id: str, user_id: str) -> datetime:
    """Give the desk its daily recurrence and queue its next morning run."""
    first_run = get_next_run_time(INBOX_DESK_RECURRENCE, tz=await get_profile_timezone(user_id))
    schedule = TodoUpdate(recurrence=INBOX_DESK_RECURRENCE, scheduled_at=first_run)
    await tracked_todo_service.set_creation_fields(desk_id, user_id, schedule, by=_PROVISIONED_BY)
    await tracked_todo_service.schedule_execution(desk_id, first_run)
    return first_run
