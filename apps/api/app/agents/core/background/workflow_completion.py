"""Route a successfully finished workflow run's result by the workflow's delivery mode.

The one place both workflow paths (an agent run and a playbook replay) decide
what a finished run does once its result is saved to the workflow's
conversation: push it now, hold it for the next brief, or leave it there.
Failures never come through here; they always notify (see
send_workflow_failure_notification).
"""

from dataclasses import dataclass

from app.agents.core.background.workflow_platform_delivery import deliver_result_to_platforms
from app.constants.log_tags import LogTag
from app.constants.notifications import ProactiveMessageClass
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.models.brief_models import PendingBriefItemDocument
from app.models.user_models import AuthenticatedUser
from app.services.workflow.notifications import send_workflow_completion_notification
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class CompletedWorkflowRun:
    """One successful workflow run, its narrated result saved to its conversation."""

    workflow_id: str
    workflow_title: str
    delivery: WorkflowDelivery
    conversation_id: str
    #: The narrated result, as the user would read it.
    text: str
    #: What produced the result, for the platform thread's record.
    origin: str


async def deliver_workflow_completion(user: AuthenticatedUser, run: CompletedWorkflowRun) -> None:
    """Push, hold for the brief, or keep silent one finished run's narrated result.

    now sends it to the user's preferred chat platform and raises the in-app
    heads-up; brief stores a pending brief item; silent sends nothing.
    """
    log.set(workflow_delivery=run.delivery.value)
    if run.delivery is WorkflowDelivery.NOW:
        await deliver_result_to_platforms(
            user=user,
            user_id=user.user_id,
            notification_text=run.text,
            origin=run.origin,
            message_class=ProactiveMessageClass.ROUTINE,
        )
        await send_workflow_completion_notification(
            workflow_id=run.workflow_id,
            workflow_title=run.workflow_title,
            conversation_id=run.conversation_id,
            user_id=user.user_id,
        )
    elif run.delivery is WorkflowDelivery.BRIEF:
        await pending_brief_items_repository.create(
            PendingBriefItemDocument(
                user_id=user.user_id,
                workflow_id=run.workflow_id,
                workflow_title=run.workflow_title,
                conversation_id=run.conversation_id,
                text=run.text,
            )
        )
        log.info(
            f"{LogTag.WORKFLOW} Workflow result held for the next brief",
            workflow_id=run.workflow_id,
        )
    else:
        log.info(
            f"{LogTag.WORKFLOW} Workflow result kept in its conversation (silent)",
            workflow_id=run.workflow_id,
        )
