"""Stop everything that runs on a removed self-host member's behalf; their data stays.

Workflows go through WorkflowService so their Composio triggers are unregistered
too. Every pause carries DeactivationReason.MEMBER_REMOVED, which no automatic
resume owns. Each item is attempted even when another fails, so a repeated
removal finishes what an earlier one left.
"""

from collections.abc import Awaitable, Callable
from functools import partial

from app.constants.error_codes import MEMBER_OFFBOARDING_INCOMPLETE
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.models.scheduler_models import DeactivationReason
from app.models.todo_models import TodoUpdate
from app.services.platform_link_service import PlatformLinkService, disconnect_platform_account
from app.services.reminder_service import reminder_scheduler
from app.services.workflow.service import WorkflowService
from app.utils.errors import AppError
from shared.py.wide_events import log

_REASON = DeactivationReason.MEMBER_REMOVED


async def stop_acting_for_removed_member(user_id: str) -> None:
    """Deactivate workflows, pause reminders and tracked todos, and unlink every bot platform."""
    steps: list[tuple[str, Callable[[], Awaitable[object]]]] = []
    for workflow in await workflow_repository.find_activated_for_user(user_id):
        steps.append(
            (
                f"workflow:{workflow.id}",
                partial(WorkflowService.deactivate_workflow, workflow.id, user_id, reason=_REASON),
            )
        )
    for reminder in await reminder_repository.find_scheduled_for_user(user_id):
        steps.append(
            (
                f"reminder:{reminder.id}",
                partial(reminder_scheduler.pause_for_reason, reminder, _REASON),
            )
        )
    for todo in await todo_repository.find_running_tracked_for_user(user_id):
        steps.append(
            (
                f"tracked_todo:{todo.id}",
                partial(
                    todo_repository.update,
                    todo.id,
                    user_id=user_id,
                    update=TodoUpdate(pause_reason=_REASON),
                ),
            )
        )
    for platform in await PlatformLinkService.get_linked_platforms(user_id):
        steps.append(
            (f"platform:{platform}", partial(disconnect_platform_account, user_id, platform))
        )

    failed: list[str] = []
    for item, step in steps:
        try:
            await step()
        except Exception as e:  # the rest must still stop; the failures are raised below
            failed.append(item)
            log.warning(
                "[members] could not stop an item for a removed member",
                user_id=user_id,
                item=item,
                error=str(e),
                error_type=type(e).__name__,
            )
    log.set(member_offboarding={"stopped": len(steps) - len(failed), "failed": len(failed)})
    if failed:
        raise AppError(
            message="The member was removed, but some of their automation is still running",
            why=f"Could not stop: {', '.join(failed)}",
            fix="Remove the member again; each removal retries whatever is still running",
            status_code=503,
            code=MEMBER_OFFBOARDING_INCOMPLETE,
            meta={"user_id": user_id, "failed": failed},
        )
