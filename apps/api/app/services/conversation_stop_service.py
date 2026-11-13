"""Stop a conversation: every kind of work it has running."""

from uuid import uuid4

from app.agents.core.background.work_cancel import stop_unlogged_work
from app.models.work_cancel_models import ConversationStopResponse
from app.services.analytics_service import capture
from app.services.browser.job_stop import RequesterChat
from app.services.conversation.work_log import record_user_stop
from shared.py.analytics import UserId
from shared.py.analytics.catalog.chat import ChatWorkStopped


async def stop_conversation(
    conversation_id: str,
    user_id: str,
    requester: RequesterChat | None,
) -> ConversationStopResponse:
    """Log the user's Stop, whose effect cancels the work it covers, then stop what the log never held.

    The logged StopRequested also settles the reply in flight.
    """
    logged = await record_user_stop(conversation_id, user_id, uuid4().hex)
    unlogged = await stop_unlogged_work(conversation_id, requester)
    return ConversationStopResponse(
        conversation_id=conversation_id, work=logged.combined_with(unlogged)
    )


async def press_stop(
    conversation_id: str,
    user_id: str,
    requester: RequesterChat | None,
) -> ConversationStopResponse:
    """Stop the conversation because the user pressed Stop, and count that press."""
    result = await stop_conversation(conversation_id, user_id, requester)
    work = result.work
    capture(
        UserId(user_id),
        ChatWorkStopped(
            executor_stopped=work.executor_stopped,
            pending_tasks=len(work.pending_task_ids),
            subagents=len(work.subagent_ids),
            approvals=len(work.approval_ids),
            browser_jobs=len(work.browser_jobs),
        ),
    )
    return result
