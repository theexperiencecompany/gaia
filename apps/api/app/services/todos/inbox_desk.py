"""The Inbox desk: one tracked todo per user that triages mail, owns its threads and briefs each morning.

Its description is its operating prompt and its canvas its memory; the briefing is
its run's final report, delivered like any tracked todo's. Nothing here runs mail.
"""

from app.agents.prompts.todo_prompts import INBOX_DESK_PROMPT
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.todos import INBOX_DESK_RECURRENCE, INBOX_DESK_TITLE
from app.decorators.entitlements import is_paid
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoUpdate
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.todos.errors import ExternalRefTakenError
from app.services.tracked_todo_service import tracked_todo_service
from app.services.user_service import get_profile_timezone
from app.utils.cron_utils import get_next_run_time
from shared.py.wide_events import log

INBOX_DESK_REF = ExternalRef(source=ExternalRefSource.INBOX_DESK, id=GMAIL_INTEGRATION_ID)

_PROVISIONED_BY = "GAIA when Gmail was connected"


async def provision_inbox_desk(user_id: str) -> None:
    """Open the user's Inbox desk, armed for its next morning run; once per user, Pro only.

    Free users get none, as they get no active system workflow: a tracked todo has
    no dormant state, and nothing gates its runs on the plan.
    """
    log.set_ns("inbox_desk", operation="provision", user_id=user_id)
    if not await is_paid(user_id):
        log.set_ns("inbox_desk", outcome="skipped_unpaid")
        return
    # Resolved before the insert, so a failed lookup cannot leave a desk that never runs.
    first_run = get_next_run_time(INBOX_DESK_RECURRENCE, tz=await get_profile_timezone(user_id))
    try:
        desk = await tracked_todo_service.create_tracked_todo(
            user_id,
            INBOX_DESK_TITLE,
            description=INBOX_DESK_PROMPT,
            external_ref=INBOX_DESK_REF,
            notify_on_run=True,
        )
    except ExternalRefTakenError as taken:
        log.set_ns("inbox_desk", outcome="exists", todo_id=taken.existing.id)
        return

    schedule = TodoUpdate(recurrence=INBOX_DESK_RECURRENCE, scheduled_at=first_run)
    await tracked_todo_service.set_creation_fields(desk.id, user_id, schedule, by=_PROVISIONED_BY)
    await tracked_todo_service.schedule_execution(desk.id, first_run)

    log.set_ns(
        "inbox_desk", outcome="provisioned", todo_id=desk.id, first_run=first_run.isoformat()
    )
    capture_event(user_id, AnalyticsEvents.INBOX_DESK_PROVISIONED)
