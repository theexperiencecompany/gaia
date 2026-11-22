"""Stop a conversation: every kind of work it has running."""

from uuid import uuid4

from app.models.work_cancel_models import ConversationStopResponse
from app.services.analytics_service import capture
from app.services.conversation.work_log import record_user_stop
from shared.py.analytics import UserId
from shared.py.analytics.catalog.chat import ChatWorkStopped


async def stop_conversation(conversation_id: str, user_id: str) -> ConversationStopResponse:
    """Log the user's Stop; its CancelWork cancels the work it covers and it settles the reply in flight."""
    logged = await record_user_stop(conversation_id, user_id, uuid4().hex)
    return ConversationStopResponse(conversation_id=conversation_id, work=logged)


async def press_stop(conversation_id: str, user_id: str) -> ConversationStopResponse:
    """Stop the conversation because the user pressed Stop, and count that press."""
    result = await stop_conversation(conversation_id, user_id)
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
