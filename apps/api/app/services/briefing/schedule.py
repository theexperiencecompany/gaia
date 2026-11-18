"""Keep the briefing workflows on the user's schedule: their crons, timezone and on/off state.

When each brief lands is run_times'; this moves the workflows onto it. Provisioning
stamps the crons, and a change to the schedule, quiet hours or timezone moves them.
A schedule without a daily brief first moves every brief-delivery workflow off it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.constants.briefing import (
    BRIEF_RUN_DAYS,
    BRIEFING_KIND_BY_WORKFLOW_KEY,
    DAILY_BRIEFING_WORKFLOW_KEY,
    BriefingFrequency,
    BriefingKind,
)
from app.constants.error_codes import BRIEF_DELIVERY_WORKFLOWS_EXIST
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.workflows import workflow_repository
from app.decorators.entitlements import is_paid
from app.models.brief_settings_models import (
    BriefDeliveryWorkflow,
    BriefFreeDelivery,
    BriefingSchedule,
    BriefingScheduleState,
)
from app.models.briefing_state_models import BriefingStateUpdate
from app.models.scheduler_models import DeactivationReason
from app.models.user_models import UserDocument
from app.models.workflow_models import UpdateWorkflowRequest, Workflow, WorkflowDocument
from app.services.analytics_service import capture
from app.services.briefing.clock import resolve_clock
from app.services.briefing.held import brief_will_carry, release_held_items
from app.services.briefing.run_times import (
    BriefSlot,
    brief_slots,
    briefing_cron,
    inbox_desk_recurrence,
)
from app.services.todos.inbox_desk import follow_the_brief
from app.services.user_service import require_user
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


async def briefs_paused_for_plan(user_id: str, schedule: BriefingSchedule) -> bool:
    """Whether the user's schedule has briefs that do not run because they are not on Pro."""
    return schedule.frequency is not BriefingFrequency.OFF and not await is_paid(user_id)


async def briefing_schedule_state(user_id: str) -> BriefingScheduleState:
    """Return the user's schedule as it runs: paused while they are not on Pro, and the next daily."""
    user = await require_user(user_id)
    schedule = (await briefing_state_repository.state_for(user_id)).schedule
    paused = await briefs_paused_for_plan(user_id, schedule)
    daily = brief_slots(schedule, user.effective_quiet_hours).get(DAILY_BRIEFING_WORKFLOW_KEY)
    return BriefingScheduleState(
        **schedule.model_dump(),
        paused_for_plan=paused,
        next_daily_brief_at=None if paused else await _next_daily_brief_at(user_id, daily),
        has_daily_brief=daily is not None,
        daily_brief_hour=daily.hour if daily is not None else None,
    )


async def _next_daily_brief_at(user_id: str, slot: BriefSlot | None) -> datetime | None:
    """Return when the daily brief's workflow next runs, or None when the schedule runs none."""
    if slot is None:
        return None
    workflows = await workflow_repository.find_system_workflows(
        user_id, tuple(BRIEFING_KIND_BY_WORKFLOW_KEY)
    )
    daily = next(
        (w for w in workflows if w.system_workflow_key == DAILY_BRIEFING_WORKFLOW_KEY), None
    )
    return daily.trigger_config.next_run if daily and daily.activated else None


async def _next_run_base(user: UserDocument, kind: BriefingKind) -> datetime:
    """Return where the moved schedule's next run is counted from.

    From tomorrow when today's brief already went out, so a same-day move never fires
    a second one; else from the start of today, so a slot moved earlier than now still
    fires today instead of being skipped (a past-due next run fires at once).
    """
    clock = resolve_clock(user.timezone)
    delivered = await briefing_repository.was_delivered(user.id, clock.date_str, kind)
    return clock.day_start(days_ago=-1 if delivered else 0)


async def _apply_frequency(workflow: Workflow, user: UserDocument, enabled: bool) -> None:
    """Switch the workflow on when the frequency runs it and off when it drops it.

    On a free plan one the frequency runs waits for Pro, paused as SUBSCRIPTION_LAPSED so the
    restore on upgrade switches it on; one it drops carries no reason, so nothing revives it.
    """
    on = enabled and await is_paid(user.id)
    reason = DeactivationReason.SUBSCRIPTION_LAPSED if enabled and not on else None
    if workflow.activated == on and (on or workflow.deactivated_reason == reason):
        return
    switched = (
        await WorkflowService.activate_workflow(workflow.id, user.id)
        if on
        else await WorkflowService.deactivate_workflow(workflow.id, user.id, reason=reason)
    )
    if switched is None:
        raise LookupError(f"Briefing workflow {workflow.id} vanished while it was switched")
    log.info(
        "briefing.schedule_switched",
        user_id=user.id,
        workflow_id=workflow.id,
        on=on,
        reason=reason.value if reason else None,
    )


async def resync_briefing_schedules(user: UserDocument) -> None:
    """Fit the user's briefing workflows to their stored schedule, quiet hours and timezone."""
    timezone = Timezone.parse(user.timezone).value
    schedule = (await briefing_state_repository.state_for(user.id)).schedule
    enabled_keys = BRIEF_RUN_DAYS[schedule.frequency]
    workflows = await workflow_repository.find_system_workflows(
        user.id, tuple(BRIEFING_KIND_BY_WORKFLOW_KEY)
    )
    by_key = {workflow.system_workflow_key: workflow for workflow in workflows}
    for key, kind in BRIEFING_KIND_BY_WORKFLOW_KEY.items():
        workflow = by_key.get(key)
        if workflow is None:
            continue
        await _move(workflow, user, briefing_cron(key, user, schedule), kind, timezone)
        await _apply_frequency(workflow, user, key in enabled_keys)


async def _move(
    workflow: Workflow, user: UserDocument, cron: str, kind: BriefingKind, timezone: str
) -> None:
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
    log.info(
        "briefing.schedule_moved",
        user_id=user.id,
        key=workflow.system_workflow_key,
        cron=cron,
        timezone=timezone,
    )


#: Where a brief-delivery workflow goes, per schedule with no daily brief, when none was chosen:
#: weekly-only already sends its results at once; with briefs off it has nowhere to go, so refuse.
_UNCHOSEN_DELIVERY: dict[BriefingFrequency, BriefFreeDelivery | None] = {
    BriefingFrequency.WEEKLY_ONLY: WorkflowDelivery.NOW,
    BriefingFrequency.OFF: None,
}


@dataclass(frozen=True)
class _BriefWorkflowMoves:
    """Where brief-delivery workflows go when the daily brief stops: chosen per id, the rest to rest."""

    chosen: Mapping[str, BriefFreeDelivery]
    rest: BriefFreeDelivery | None


async def _move_off_the_brief(
    user_id: str,
    frequency: BriefingFrequency,
    moves: _BriefWorkflowMoves,
    via: BriefingScheduleChangedVia,
) -> None:
    """Give every brief-delivery workflow its new delivery; refuse, changing nothing, if one has none."""
    on_brief = await workflow_repository.find_brief_delivery_for_user(user_id)
    fallback = moves.rest or _UNCHOSEN_DELIVERY[frequency]
    deliveries = {workflow.id: moves.chosen.get(workflow.id, fallback) for workflow in on_brief}
    unresolved = [workflow for workflow in on_brief if deliveries[workflow.id] is None]
    if unresolved:
        capture(UserId(user_id), SettingsBriefsOffBlocked(workflow_count=len(unresolved), via=via))
        raise BriefDeliveryWorkflowsError(unresolved)
    for workflow in on_brief:
        moved = await WorkflowService.update_workflow(
            workflow.id, UpdateWorkflowRequest(delivery=deliveries[workflow.id]), user_id
        )
        if moved is None:
            raise LookupError(f"Workflow {workflow.id} vanished while it was moved off the brief")
    if on_brief and frequency is BriefingFrequency.OFF:
        moved_to = list(deliveries.values())
        capture(
            UserId(user_id),
            SettingsBriefsOffResolved(
                moved_to_now=moved_to.count(WorkflowDelivery.NOW),
                moved_to_silent=moved_to.count(WorkflowDelivery.SILENT),
                via=via,
            ),
        )


async def set_briefing_schedule(
    user_id: str,
    frequency: BriefingFrequency,
    via: BriefingScheduleChangedVia,
    *,
    hour: int | None = None,
    workflow_deliveries: Mapping[str, BriefFreeDelivery] | None = None,
    brief_workflows_to: BriefFreeDelivery | None = None,
) -> BriefingSchedule:
    """Store the user's briefing frequency, and hour unless None keeps theirs, and move the briefs onto it.

    A schedule with no daily brief first moves each brief-delivery workflow off the brief:
    to its delivery in workflow_deliveries, else brief_workflows_to, else (weekly-only) Tell
    me now, raising BriefDeliveryWorkflowsError while any has none. It releases what was held.
    """
    user = await require_user(user_id)
    before = (await briefing_state_repository.state_for(user_id)).schedule
    schedule = BriefingSchedule(frequency=frequency, hour=before.hour if hour is None else hour)
    if schedule.frequency in _UNCHOSEN_DELIVERY:
        moves = _BriefWorkflowMoves(chosen=workflow_deliveries or {}, rest=brief_workflows_to)
        await _move_off_the_brief(user_id, schedule.frequency, moves, via)
    await briefing_state_repository.upsert(user_id, BriefingStateUpdate(schedule=schedule))
    await resync_briefing_schedules(user)
    quiet_hours = user.effective_quiet_hours
    await follow_the_brief(
        user_id,
        inbox_desk_recurrence(before, quiet_hours),
        inbox_desk_recurrence(schedule, quiet_hours),
    )
    if not await brief_will_carry(user_id):
        await release_held_items(user_id)
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
    return schedule
