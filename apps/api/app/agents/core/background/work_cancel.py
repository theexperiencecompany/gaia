"""Stop a conversation's background work: the executor run, its inbox, subagents, approvals, browser jobs.

cancel_all_work is the one stop every trigger uses: the Stop button, a bot's /stop
and the comms cancel_executor tool. cancel_named_work is the targeted cancel the
tool makes when the user names one task, which leaves everything else running.
"""

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.executor_progress import drop_progress
from app.agents.core.background.executor_queue import decode_raw_item, parse_lock_value
from app.agents.core.background.running_registry import RunningSubagents, stop_stream
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.log_tags import LogTag
from app.constants.streaming import WS_EVENT_EXECUTOR_CANCELLED
from app.core.websocket_manager import websocket_manager
from app.db.redis import redis_cache
from app.models.work_cancel_models import WorkCancelled
from app.services.browser.job_stop import RequesterChat, stop_chat_jobs
from app.services.hil.ledger_decide import cancel_ledger_approvals
from shared.py.wide_events import log

# A placeholder stream id some lock writers use; it names no stream to cancel.
_NO_STREAM_IDS = frozenset({"", "1"})


async def cancel_all_work(
    conversation_id: str,
    user_id: str,
    requester: RequesterChat | None,
    *,
    redirect: str | None = None,
) -> WorkCancelled:
    """Stop everything running for the conversation; an idle one comes back empty and untouched.

    requester widens the browser stop to the job that answers to the user's own bot chat.
    redirect is what the user wants instead, handed to the next executor run with the stop.
    """
    inbox = ExecutorInbox(conversation_id)
    lock_value = await _held_lock(conversation_id)
    task_id = await _stop_running_executor(conversation_id, lock_value) if lock_value else None
    subagents = await RunningSubagents(conversation_id).stop_all()
    approvals = await cancel_ledger_approvals(conversation_id, user_id)
    pending = await inbox.clear()
    # After the clear: a stopped job's notice lands in the inbox and must survive it.
    browser_jobs = await stop_chat_jobs(conversation_id, requester)
    work = WorkCancelled(
        executor_stopped=lock_value is not None,
        executor_task_id=task_id or None,
        pending_tasks=pending,
        subagent_ids=[subagent.subagent_id for subagent in subagents],
        approval_ids=approvals,
        browser_jobs=browser_jobs,
    )
    await _settle(conversation_id, user_id, work, redirect)
    return work


async def cancel_named_work(
    conversation_id: str,
    user_id: str,
    task_ids: list[str],
    *,
    redirect: str | None = None,
) -> WorkCancelled:
    """Cancel only the named executor tasks, running or queued, and the approvals of a stopped run."""
    inbox = ExecutorInbox(conversation_id)
    lock_value = await _held_lock(conversation_id)
    running_task_id = parse_lock_value(lock_value)[1] if lock_value else None
    named = running_task_id is not None and running_task_id in task_ids
    if named and lock_value is not None:
        await _stop_running_executor(conversation_id, lock_value)
    # Only once the RUNNING task is gone: a spared run is still waiting on its approvals.
    approvals = await cancel_ledger_approvals(conversation_id, user_id) if named else []
    work = WorkCancelled(
        executor_stopped=named,
        executor_task_id=running_task_id if named else None,
        executor_spared=lock_value is not None and not named,
        pending_task_ids=await inbox.discard(set(task_ids)),
        approval_ids=approvals,
    )
    await _settle(conversation_id, user_id, work, redirect)
    return work


async def _held_lock(conversation_id: str) -> str | None:
    """Read the executor busy lock's raw "stream_id:task_id" value; None when no run holds it."""
    # Raw client.get(): the value is a plain string, which redis_cache.get() cannot deserialize.
    raw_lock = await redis_cache.client.get(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
    return decode_raw_item(raw_lock) if raw_lock is not None else None


async def _stop_running_executor(conversation_id: str, lock_value: str) -> str:
    """Cancel the run holding the busy lock and free the lock; return its task id."""
    stream_id, task_id = parse_lock_value(lock_value)
    if stream_id not in _NO_STREAM_IDS:
        await stop_stream(conversation_id, stream_id)
    # Freed only once the stream is cancelled: freeing a run that kept going lets two run at once.
    await redis_cache.delete(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
    await drop_progress(conversation_id, lock_value)
    log.info(
        f"{LogTag.TOOL} Stopped the running executor task",
        task_id=task_id,
        stream_id=stream_id,
        conversation_id=conversation_id,
    )
    return task_id


async def _settle(
    conversation_id: str, user_id: str, work: WorkCancelled, redirect: str | None
) -> None:
    """Tell the next executor run the work was stopped, and the user's clients that it ended."""
    if not work.stopped_anything:
        return
    # Only when a run actually died: a spared live executor would drain the notice as its own.
    if work.executor_stopped or work.subagent_ids:
        await ExecutorInbox(conversation_id).announce_interruption(redirect)
    log.set_ns(
        "work_cancel",
        conversation_id=conversation_id,
        executor_stopped=work.executor_stopped,
        pending=work.pending_tasks + len(work.pending_task_ids),
        subagents=len(work.subagent_ids),
        approvals=len(work.approval_ids),
        browser_jobs=len(work.browser_jobs),
    )
    if user_id:
        await _broadcast_executor_cancelled(user_id, conversation_id)


async def _broadcast_executor_cancelled(user_id: str, conversation_id: str) -> None:
    """Tell the user's clients a cancel they may not have made happened, so pending executor state clears."""
    try:
        await websocket_manager.broadcast_to_user(
            user_id,
            {"type": WS_EVENT_EXECUTOR_CANCELLED, "conversation_id": conversation_id},
        )
    except Exception as e:  # best-effort UI signal
        log.warning(f"{LogTag.TOOL} Failed to broadcast executor.cancelled", error=str(e))
