"""Stop a conversation: cancel its live streams, then every kind of work it has running."""

from uuid import uuid4

from app.agents.core.background.work_cancel import cancel_all_work
from app.core.stream_manager import stream_manager
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
    *,
    held_stream_id: str | None = None,
) -> ConversationStopResponse:
    """Cancel the conversation's live turn and the stream the caller holds, then all its work.

    Only the newest turn is indexed per conversation, so an older concurrent turn is
    reached only when the caller names it as held_stream_id.
    """
    live_turn = await stream_manager.get_resumable_stream_id(user_id, conversation_id)
    stream_ids = list(dict.fromkeys(s for s in (held_stream_id, live_turn) if s))
    for stream_id in stream_ids:
        await stream_manager.cancel_stream(stream_id)
    # The turns alone: the sweep stops their subagents and counts only what it stopped itself.
    work = await cancel_all_work(conversation_id, user_id, requester)
    return ConversationStopResponse(
        conversation_id=conversation_id, stream_ids=stream_ids, work=work
    )


async def press_stop(
    conversation_id: str,
    user_id: str,
    requester: RequesterChat | None,
    *,
    held_stream_id: str | None = None,
) -> ConversationStopResponse:
    """Stop the conversation because the user pressed Stop, and count that press."""
    await record_user_stop(conversation_id, user_id, uuid4().hex)
    result = await stop_conversation(
        conversation_id, user_id, requester, held_stream_id=held_stream_id
    )
    work = result.work
    capture(
        UserId(user_id),
        ChatWorkStopped(
            streams=len(result.stream_ids),
            executor_stopped=work.executor_stopped,
            pending_tasks=work.pending_tasks,
            subagents=len(work.subagent_ids),
            approvals=len(work.approval_ids),
            browser_jobs=len(work.browser_jobs),
        ),
    )
    return result
