"""When the briefs run: the daily at 08:00 on the user's clock, the weekly on Sunday.

A daily brief that would land inside quiet hours runs at the hour they end instead.
Provisioning stamps this onto the briefing workflows' crons, and a change to the
user's quiet hours or timezone moves the workflows with it.
"""

from datetime import datetime

from app.constants.briefing import (
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
    DAILY_BRIEFING_HOUR,
    DAILY_BRIEFING_WORKFLOW_KEY,
    WEEKLY_DIGEST_CRON,
    WEEKLY_DIGEST_WORKFLOW_KEY,
)
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.workflows import workflow_repository
from app.models.briefing_models import BriefingKind
from app.models.notification.notification_models import QuietHours
from app.models.user_models import UserDocument
from app.models.workflow_models import UpdateWorkflowRequest
from app.services.briefing import context
from app.services.delivery.quiet_hours import contains_hour
from app.services.workflow.service import WorkflowService
from app.utils.timezone import Timezone
from shared.py.wide_events import log

_KIND_BY_WORKFLOW_KEY: dict[str, BriefingKind] = {
    DAILY_BRIEFING_WORKFLOW_KEY: BRIEFING_KIND_DAILY,
    WEEKLY_DIGEST_WORKFLOW_KEY: BRIEFING_KIND_WEEKLY,
}


def daily_briefing_cron(quiet_hours: QuietHours) -> str:
    """Return the daily brief's cron: 08:00, or the end of quiet hours covering 08:00."""
    hour = (
        quiet_hours.end_hour
        if contains_hour(quiet_hours, DAILY_BRIEFING_HOUR)
        else DAILY_BRIEFING_HOUR
    )
    return f"0 {hour} * * *"


def _briefing_cron(key: str, user: UserDocument) -> str:
    return (
        daily_briefing_cron(user.quiet_hours)
        if key == DAILY_BRIEFING_WORKFLOW_KEY
        else WEEKLY_DIGEST_CRON
    )


async def _next_run_base(user: UserDocument, kind: BriefingKind) -> datetime:
    """Return where the moved schedule's next run is counted from.

    From tomorrow when today's brief already went out, so a same-day move never fires
    a second one; else from the start of today, so a slot moved earlier than now still
    fires today instead of being skipped (a past-due next run fires at once).
    """
    clock = context.resolve_clock(user.timezone)
    delivered = await briefing_repository.was_delivered(user.id, clock.date_str, kind)
    return context.day_start_utc(clock, days_ago=-1 if delivered else 0)


async def resync_briefing_schedules(user: UserDocument) -> None:
    """Move the user's briefing workflows to the hour and timezone their profile now gives."""
    timezone = Timezone.parse(user.timezone).value
    workflows = await workflow_repository.find_system_workflows(
        user.id, tuple(_KIND_BY_WORKFLOW_KEY)
    )
    by_key = {workflow.system_workflow_key: workflow for workflow in workflows}
    for key, kind in _KIND_BY_WORKFLOW_KEY.items():
        workflow = by_key.get(key)
        if workflow is None:
            continue
        cron = _briefing_cron(key, user)
        current = workflow.trigger_config
        if current.cron_expression == cron and current.timezone == timezone:
            continue
        trigger_config = current.model_copy(update={"cron_expression": cron, "timezone": timezone})
        updated = await WorkflowService.update_workflow(
            workflow.id,
            UpdateWorkflowRequest(trigger_config=trigger_config),
            user.id,
            next_run_base=await _next_run_base(user, kind),
        )
        if updated is None:
            raise LookupError(f"Briefing workflow {workflow.id} vanished while it was moved")
        log.info("briefing.schedule_moved", user_id=user.id, key=key, cron=cron, timezone=timezone)
