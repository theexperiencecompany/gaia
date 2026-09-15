"""The activation checklist.

Every ``done`` is derived from a real signal at read time — there is no way to
mark a step done, so nothing a browser sends can fake progress. Only the
collapse is persisted, on the user document.
"""

import asyncio

from app.db.repositories.conversations import conversation_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.first_steps_models import FirstStep, FirstStepKey, FirstStepsResponse
from app.models.user_models import UserDocument
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.integrations.integration_status import get_all_integrations_status
from app.services.platform_link_service import linked_platforms_of
from app.utils.errors import AppError


async def get_first_steps(user_id: str) -> FirstStepsResponse:
    """The checklist with each step's ``done`` derived from live data."""
    user = await user_repository.get(user_id)
    if user is None:
        raise _user_not_found(user_id)
    return await _build_checklist(user)


async def set_first_steps_collapsed(user_id: str, collapsed: bool) -> FirstStepsResponse:
    """Collapse or expand the checklist; idempotent. Returns it as it stands."""
    if not await user_repository.set_first_steps_collapsed(user_id, collapsed):
        raise _user_not_found(user_id)
    checklist = await get_first_steps(user_id)
    capture_context_event(
        AnalyticsEvents.FIRST_STEPS_COLLAPSED,
        {
            "collapsed": collapsed,
            "steps_done": sum(step.done for step in checklist.steps),
            "steps_total": len(FirstStepKey),
        },
    )
    return checklist


async def _build_checklist(user: UserDocument) -> FirstStepsResponse:
    sent_message, integration_status, created = await asyncio.gather(
        conversation_repository.has_sent_message(user.id),
        # The canonical connected-set reader: it covers the self-managed
        # Google integrations (Gmail) and Composio accounts that predate a
        # ``user_integrations`` row, which a raw collection count would miss.
        get_all_integrations_status(user.id),
        # Auto-provisioned system workflows and todo-backed ones are not the
        # user authoring a workflow.
        workflow_repository.count_for_user(
            user.id, exclude_todo_workflows=True, exclude_system_workflows=True
        ),
    )
    return FirstStepsResponse(
        steps=[
            FirstStep(key=FirstStepKey.SAY_HI, done=sent_message),
            FirstStep(key=FirstStepKey.CONNECT_INTEGRATION, done=any(integration_status.values())),
            FirstStep(key=FirstStepKey.LINK_PLATFORM, done=bool(linked_platforms_of(user))),
            FirstStep(key=FirstStepKey.CREATE_WORKFLOW, done=created > 0),
        ],
        collapsed=user.first_steps is not None and user.first_steps.collapsed,
    )


def _user_not_found(user_id: str) -> AppError:
    return AppError(
        message="User not found",
        why="no user document matches the authenticated session's id",
        status_code=404,
        meta={"user_id": user_id},
    )
