"""When the daily brief runs: 08:00 on the user's clock, unless their quiet hours cover it.

A brief that would land inside quiet hours runs at the hour they end instead.
Provisioning stamps this onto the daily briefing workflow's cron, and a change
to the user's quiet hours moves the workflow with it.
"""

from app.constants.briefing import DAILY_BRIEFING_HOUR, DAILY_BRIEFING_WORKFLOW_KEY
from app.db.repositories.workflows import workflow_repository
from app.models.notification.notification_models import QuietHours
from app.models.workflow_models import UpdateWorkflowRequest
from app.services.workflow.service import WorkflowService
from shared.py.wide_events import log


def daily_briefing_cron(quiet_hours: QuietHours) -> str:
    """Return the daily brief's cron: 08:00, or the end of quiet hours covering 08:00."""
    hour = (
        quiet_hours.end_hour
        if quiet_hours.contains_hour(DAILY_BRIEFING_HOUR)
        else DAILY_BRIEFING_HOUR
    )
    return f"0 {hour} * * *"


async def resync_daily_briefing_schedule(user_id: str, quiet_hours: QuietHours) -> None:
    """Move the user's daily brief to the hour their new quiet hours leave it."""
    workflow = await workflow_repository.find_system_workflow(user_id, DAILY_BRIEFING_WORKFLOW_KEY)
    if workflow is None:
        return
    cron = daily_briefing_cron(quiet_hours)
    if workflow.trigger_config.cron_expression == cron:
        return
    trigger_config = workflow.trigger_config.model_copy(update={"cron_expression": cron})
    updated = await WorkflowService.update_workflow(
        workflow.id, UpdateWorkflowRequest(trigger_config=trigger_config), user_id
    )
    if updated is None:
        raise LookupError(f"Daily briefing workflow {workflow.id} vanished while it was moved")
    log.info("briefing.schedule_moved", user_id=user_id, cron=cron)
