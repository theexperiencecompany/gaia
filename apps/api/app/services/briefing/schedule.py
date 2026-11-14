"""When the briefs run: the daily at the user's hour on their clock, the weekly on Sunday.

The user's briefing frequency decides which briefs run at all (weekdays keeps the
daily to Monday-Friday) and their hour when the daily lands; a daily brief that
would land inside quiet hours runs at the hour they end instead. Provisioning
stamps this onto the briefing workflows' crons, and a change to the schedule,
quiet hours or timezone moves the workflows with it.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from app.constants.briefing import (
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
    DAILY_BRIEFING_WORKFLOW_KEY,
    ENABLED_BRIEFING_KEYS,
    EVERY_DAY_CRON_DAYS,
    WEEKDAYS_CRON_DAYS,
    WEEKLY_DIGEST_CRON,
    WEEKLY_DIGEST_WORKFLOW_KEY,
    BriefingFrequency,
)
from app.constants.error_codes import BRIEF_DELIVERY_WORKFLOWS_EXIST
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.decorators.entitlements import is_paid
from app.models.briefing_models import (
    BriefDeliveryWorkflow,
    BriefFreeDelivery,
    BriefingKind,
    BriefingSchedule,
)
from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS, QuietHours
from app.models.user_models import UserDocument
from app.models.workflow_models import UpdateWorkflowRequest, Workflow, WorkflowDocument
from app.services.analytics_service import capture
from app.services.briefing import context
from app.services.workflow.service import WorkflowService
from app.utils.errors import AppError
from app.utils.timezone import Timezone
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import (
    BriefingScheduleChangedVia,
    SettingsBriefingScheduleUpdated,
    SettingsBriefsOffBlocked,
    SettingsBriefsOffResolved,
)
from shared.py.wide_events import log

_KIND_BY_WORKFLOW_KEY: dict[str, BriefingKind] = {
    DAILY_BRIEFING_WORKFLOW_KEY: BRIEFING_KIND_DAILY,
    WEEKLY_DIGEST_WORKFLOW_KEY: BRIEFING_KIND_WEEKLY,
}


_FREQUENCY_DESCRIPTIONS: dict[BriefingFrequency, str] = {
    BriefingFrequency.DAILY: "a daily brief every day at {time}, plus the Sunday evening weekly digest",
    BriefingFrequency.WEEKDAYS: (
        "a daily brief Monday to Friday at {time}, plus the Sunday evening weekly digest"
    ),
    BriefingFrequency.WEEKLY_ONLY: "only the Sunday evening weekly digest, no daily brief",
    BriefingFrequency.OFF: "no briefs at all",
}


class BriefDeliveryWorkflowsError(AppError):
    """Briefs cannot turn off while these workflows still deliver their results to the brief."""

    def __init__(self, workflows: list[WorkflowDocument]) -> None:
        count = len(workflows)
        named = [BriefDeliveryWorkflow(id=w.id, title=w.title) for w in workflows]
        super().__init__(
            message=(
                "1 workflow sends its results to your brief"
                if count == 1
                else f"{count} workflows send their results to your brief"
            ),
            why="With briefs off, their results would go nowhere",
            fix=f"Set {', '.join(w.title for w in named)} to Tell me now or Don't notify me, "
            "then turn briefs off",
            status_code=409,
            code=BRIEF_DELIVERY_WORKFLOWS_EXIST,
            public={"workflows": [w.model_dump() for w in named]},
        )


def daily_briefing_hour(schedule: BriefingSchedule, quiet_hours: QuietHours) -> int:
    """Return the daily brief's local hour: the user's, or the end of quiet hours covering it."""
    # Quiet hours read only the hour on the clock; any day stands in for the brief's.
    slot = datetime.min.replace(hour=schedule.hour, tzinfo=UTC)
    return quiet_hours.end_after(slot).hour


def daily_briefing_cron(schedule: BriefingSchedule, quiet_hours: QuietHours) -> str:
    """Return the daily brief's cron: its hour, every day or Monday to Friday."""
    days = (
        WEEKDAYS_CRON_DAYS
        if schedule.frequency == BriefingFrequency.WEEKDAYS
        else EVERY_DAY_CRON_DAYS
    )
    return f"0 {daily_briefing_hour(schedule, quiet_hours)} * * {days}"


def describe_briefing_schedule(user: UserDocument) -> str:
    """Say in plain words which briefs the user gets and when the daily one lands."""
    hour = daily_briefing_hour(user.briefing_schedule, user.quiet_hours or DEFAULT_QUIET_HOURS)
    return _FREQUENCY_DESCRIPTIONS[user.briefing_schedule.frequency].format(time=f"{hour:02d}:00")


def briefing_cron(key: str, user: UserDocument) -> str:
    """Return the cron the user's profile gives the briefing workflow under key."""
    return (
        daily_briefing_cron(user.briefing_schedule, user.quiet_hours or DEFAULT_QUIET_HOURS)
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


async def _apply_frequency(workflow: Workflow, user: UserDocument, enabled: bool) -> None:
    """Switch the workflow off when the frequency drops it, back on when it returns.

    Switching back on stays a paid-plan privilege: a free user's briefs remain off.
    """
    if enabled == workflow.activated:
        return
    if enabled and not await is_paid(user.id):
        return
    switch = WorkflowService.activate_workflow if enabled else WorkflowService.deactivate_workflow
    if await switch(workflow.id, user.id) is None:
        raise LookupError(f"Briefing workflow {workflow.id} vanished while it was switched")
    log.info("briefing.schedule_switched", user_id=user.id, workflow_id=workflow.id, on=enabled)


async def resync_briefing_schedules(user: UserDocument) -> None:
    """Fit the user's briefing workflows to the frequency, hour and timezone their profile gives."""
    timezone = Timezone.parse(user.timezone).value
    enabled_keys = ENABLED_BRIEFING_KEYS[user.briefing_schedule.frequency]
    workflows = await workflow_repository.find_system_workflows(
        user.id, tuple(_KIND_BY_WORKFLOW_KEY)
    )
    by_key = {workflow.system_workflow_key: workflow for workflow in workflows}
    for key, kind in _KIND_BY_WORKFLOW_KEY.items():
        workflow = by_key.get(key)
        if workflow is None:
            continue
        await _move(workflow, user, key, kind, timezone)
        await _apply_frequency(workflow, user, key in enabled_keys)


async def _move(
    workflow: Workflow, user: UserDocument, key: str, kind: BriefingKind, timezone: str
) -> None:
    cron = briefing_cron(key, user)
    current = workflow.trigger_config
    if current.cron_expression == cron and current.timezone == timezone:
        return
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


async def _move_off_the_brief(
    user_id: str,
    deliveries: Mapping[str, BriefFreeDelivery],
    via: BriefingScheduleChangedVia,
) -> None:
    """Give every brief-delivery workflow its new delivery; refuse, changing nothing, if one has none."""
    on_brief = await workflow_repository.find_brief_delivery_for_user(user_id)
    unresolved = [workflow for workflow in on_brief if workflow.id not in deliveries]
    if unresolved:
        capture(UserId(user_id), SettingsBriefsOffBlocked(workflow_count=len(unresolved), via=via))
        raise BriefDeliveryWorkflowsError(unresolved)
    for workflow in on_brief:
        moved = await WorkflowService.update_workflow(
            workflow.id, UpdateWorkflowRequest(delivery=deliveries[workflow.id]), user_id
        )
        if moved is None:
            raise LookupError(f"Workflow {workflow.id} vanished while it was moved off the brief")
    if on_brief:
        chosen = [deliveries[workflow.id] for workflow in on_brief]
        capture(
            UserId(user_id),
            SettingsBriefsOffResolved(
                moved_to_now=chosen.count(WorkflowDelivery.NOW),
                moved_to_silent=chosen.count(WorkflowDelivery.SILENT),
                via=via,
            ),
        )


async def set_briefing_schedule(
    user_id: str,
    schedule: BriefingSchedule,
    via: BriefingScheduleChangedVia,
    workflow_deliveries: Mapping[str, BriefFreeDelivery] | None = None,
) -> UserDocument:
    """Store the user's briefing schedule and move their briefing workflows onto it.

    Turning briefs off first moves each brief-delivery workflow to its delivery in
    workflow_deliveries, and raises BriefDeliveryWorkflowsError while any has none.
    """
    if schedule.frequency is BriefingFrequency.OFF:
        await _move_off_the_brief(user_id, workflow_deliveries or {}, via)
    await user_repository.set_briefing_schedule(user_id, schedule)
    user = await user_repository.get(user_id)
    if user is None:
        raise LookupError(f"Cannot schedule briefs for unknown user {user_id}")
    await resync_briefing_schedules(user)
    log.audit(
        "briefing schedule updated",
        actor=user_id,
        frequency=schedule.frequency,
        hour=schedule.hour,
        via=via,
    )
    capture(
        UserId(user_id),
        SettingsBriefingScheduleUpdated(frequency=schedule.frequency, hour=schedule.hour, via=via),
    )
    return user
