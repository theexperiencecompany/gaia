"""A to-do coming round: a repeat reopening on its schedule, and the nudge it owes the user.

A to-do is never run. At a repeat's next time it goes back on the list and the next time
is armed; when a dated to-do falls due, or a repeat comes back, the user is nudged once.
A nudge inside the user's quiet hours waits for their end; notify off sends nothing.
"""

from datetime import UTC, datetime

from app.agents.core.background.workflow_platform_delivery import deliver_result_to_platforms
from app.constants.tasks import (
    TASK_DEEP_LINK,
    TODO_DUE_NUDGE_BODY,
    TODO_REPEAT_NUDGE_BODY,
    VIEW_TASK_LABEL,
    Assignee,
    WhenKind,
)
from app.db.repositories.tasks import task_repository
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    RedirectConfig,
)
from app.models.task_models import DateWhen, RepeatWhen, TaskDocument, TaskUpdate
from app.services.analytics_service import capture
from app.services.delivery.chat_channel import ChatChannel, resolve_proactive_target
from app.services.notification_service import notification_service
from app.services.tasks.arming import arm_at, arm_task
from app.services.tasks.schedule import next_occurrence
from app.services.user_service import get_profile_timezone, get_quiet_hours
from app.utils.auth_utils import require_owner
from app.utils.occurrence import occurrence_stamp
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import NudgeChannel, TaskNudged
from shared.py.wide_events import log


def task_redirect_action(task_id: str) -> NotificationAction:
    """Build the notification button that opens the task in the app."""
    return NotificationAction(
        type=ActionType.REDIRECT,
        label=VIEW_TASK_LABEL,
        style=ActionStyle.PRIMARY,
        config=ActionConfig(
            redirect=RedirectConfig(
                url=TASK_DEEP_LINK.format(task_id=task_id),
                open_in_new_tab=False,
                close_notification=True,
            )
        ),
    )


def with_round_fields(current: TaskDocument, update: TaskUpdate) -> TaskUpdate:
    """Add the nudge a to-do owes once update lands, when update touches when it comes round."""
    touched = {"when", "completed", "notify"} & update.model_fields_set
    if current.assignee is not Assignee.USER or not touched:
        return update
    after = current.updated_by(update)
    nudge = first_nudge_at(after)
    if isinstance(after.when, RepeatWhen) and current.nudge_at and not after.completed:
        nudge = current.nudge_at
    return update.model_copy(update={"nudge_at": nudge})


def first_nudge_at(task: TaskDocument) -> datetime | None:
    """Return the nudge a to-do owes from its own date: its due time while that is still ahead."""
    if not task.notify or task.completed or not isinstance(task.when, DateWhen):
        return None
    return task.when.at if task.when.at > datetime.now(UTC) else None


def first_repeat(when: RepeatWhen, user_timezone: str | None) -> RepeatWhen:
    """Give a repeat its first next time when it has none yet."""
    if when.next_run is not None:
        return when
    return when.model_copy(
        update={"next_run": next_occurrence(when.rule, when.timezone or user_timezone)}
    )


async def bring_todo_round(task: TaskDocument, armed_for: datetime) -> str:
    """Do what a to-do owes at armed_for: reopen a repeat, then send its nudge."""
    stamp = occurrence_stamp(armed_for)
    if (
        isinstance(task.when, RepeatWhen)
        and task.when.next_run is not None
        and occurrence_stamp(task.when.next_run) == stamp
    ):
        reopened = await _reopen_repeat(task, task.when)
        if reopened is None:
            return f"stale_occurrence:{task.id}"
        task = reopened
        if task.nudge_at is None:
            return f"reopened:{task.id}"
    if task.nudge_at is None:
        return f"stale_occurrence:{task.id}"
    return await _nudge(task, repeats=task.when.kind is WhenKind.REPEAT)


async def _reopen_repeat(task: TaskDocument, when: RepeatWhen) -> TaskDocument | None:
    """Put the repeat back on the list and arm its next time; None when it moved meanwhile."""
    expected = when.next_run
    if expected is None:
        return None
    zone = when.timezone or (await get_profile_timezone(task.user_id)).value
    upcoming = next_occurrence(when.rule, zone, anchor=expected)
    reopened = await task_repository.update_if_next_run(
        task.id,
        task.user_id,
        expected=expected,
        update=TaskUpdate(
            completed=False,
            completed_at=None,
            when=when.model_copy(update={"next_run": upcoming}),
            nudge_at=datetime.now(UTC) if task.notify else None,
        ),
    )
    if reopened is None:
        log.info("task.repeat_moved_during_round", task_id=task.id)
        return None
    await arm_task(reopened)
    log.set_ns("task", reopened=True, next_run=upcoming.isoformat() if upcoming else None)
    return reopened


async def _nudge(task: TaskDocument, *, repeats: bool) -> str:
    """Send the owed nudge now, or hold it to the end of the user's quiet hours."""
    owed = task.nudge_at
    if owed is None:
        return f"stale_occurrence:{task.id}"
    local_now = datetime.now((await get_profile_timezone(task.user_id)).tzinfo)
    quiet = await get_quiet_hours(task.user_id)
    if quiet.contains(local_now):
        until = quiet.end_after(local_now).astimezone(UTC)
        held = await task_repository.update_if_nudge_at(
            task.id, task.user_id, expected=owed, update=TaskUpdate(nudge_at=until)
        )
        if held is None:
            return f"stale_occurrence:{task.id}"
        await arm_at(task.id, until)
        log.set_ns("task", nudge_held_until=until.isoformat())
        return f"held:{task.id} (quiet hours)"
    # Claimed before it is sent: a crash loses one nudge rather than sending two.
    claimed = await task_repository.update_if_nudge_at(
        task.id, task.user_id, expected=owed, update=TaskUpdate(nudge_at=None)
    )
    if claimed is None:
        return f"stale_occurrence:{task.id}"
    if claimed.completed:
        return f"completed:{task.id}"
    channel = await _send_nudge(claimed, repeats=repeats)
    held_for_quiet_hours = occurrence_stamp(owed) != occurrence_stamp(_due_time(claimed, owed))
    capture(
        UserId(task.user_id),
        TaskNudged(
            task_id=task.id,
            repeats=repeats,
            channel=channel,
            held_for_quiet_hours=held_for_quiet_hours,
        ),
    )
    log.set_ns("task", nudged=channel)
    return f"nudged:{task.id}"


def _due_time(task: TaskDocument, owed: datetime) -> datetime:
    return task.when.at if isinstance(task.when, DateWhen) else owed


async def _send_nudge(task: TaskDocument, *, repeats: bool) -> NudgeChannel:
    """Tell the user on their chat app when that is where they are, else in the app."""
    body = TODO_REPEAT_NUDGE_BODY if repeats else TODO_DUE_NUDGE_BODY
    target = await resolve_proactive_target(task.user_id)
    if isinstance(target, ChatChannel):
        sent = await deliver_result_to_platforms(
            user=await require_owner(task.user_id),
            user_id=task.user_id,
            notification_text=f"{task.title}: {body}",
            origin=f'to-do "{task.title}" (id {task.id})',
            target=target,
        )
        if sent is not None:
            return "chat_app"
    await notification_service.create_notification(
        NotificationRequest(
            user_id=task.user_id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            content=NotificationContent(
                title=task.title, body=body, actions=[task_redirect_action(task.id)]
            ),
            metadata={"task_id": task.id},
        )
    )
    return "in_app"
