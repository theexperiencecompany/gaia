"""Stop a conversation's background work: the executor run, its inbox, subagents, approvals, browser jobs, replays.

cancel_named_work cancels exactly the tasks it is given: a logged Stop's CancelWork
names the work it covers, and the cancel_executor tool names the one task the user means.
"""

from collections.abc import Collection

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.executor_progress import drop_progress
from app.agents.core.background.executor_queue import decode_raw_item, parse_lock_value
from app.agents.core.background.run_stop import request_stop
from app.agents.core.background.running_registry import RunningSubagents, stop_stream
from app.constants.agents import PLAYBOOK_REPLAY_STREAM_ID_PREFIX
from app.constants.browser import BrowserStopOutcome
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import RunningSubagent
from app.models.work_cancel_models import WorkCancelled
from app.services.browser.job_stop import stop_named_jobs, stop_run_jobs
from app.services.hil.ledger_decide import cancel_ledger_approvals
from shared.py.wide_events import log

# A placeholder stream id some lock writers use; it names no stream to cancel.
_NO_STREAM_IDS = frozenset({"", "1"})


async def cancel_named_work(
    conversation_id: str,
    user_id: str,
    task_ids: Collection[str],
    *,
    approval_ids: Collection[str],
    redirect: str | None = None,
) -> WorkCancelled:
    """Cancel only the named executor tasks, running or queued, and close the approvals they wait on."""
    inbox = ExecutorInbox(conversation_id)
    lock_value = await _held_lock(conversation_id)
    running_task_id = parse_lock_value(lock_value)[1] if lock_value else None
    named = running_task_id is not None and running_task_id in task_ids
    subagents: list[RunningSubagent] = []
    browser_jobs: dict[str, BrowserStopOutcome] = {}
    if named and lock_value is not None:
        subagents = (await _stop_running_executor(conversation_id, lock_value))[1]
        browser_jobs = await stop_run_jobs(conversation_id)
    # Detached work is logged under its own stream: a background subagent's, or a browser job's relay.
    subagents.extend(await RunningSubagents(conversation_id).stop_streams(task_ids))
    browser_jobs.update(await stop_named_jobs(task_ids))
    replays = await _stop_named_replays(task_ids)
    # Only once a running named task is gone: closing first would let it ask again.
    approvals = await _close_approvals(conversation_id, user_id, approval_ids)
    work = WorkCancelled(
        executor_stopped=named,
        executor_task_id=running_task_id if named else None,
        executor_spared=lock_value is not None and not named,
        pending_task_ids=await inbox.discard(set(task_ids)),
        subagent_ids=[subagent.subagent_id for subagent in subagents],
        approval_ids=approvals,
        browser_jobs=browser_jobs,
        replay_ids=replays,
    )
    await _settle(conversation_id, work, redirect)
    return work


async def _stop_named_replays(task_ids: Collection[str]) -> list[str]:
    """Cancel the playbook replays these logged task ids name; each stops before its next call."""
    replays = [
        task_id for task_id in task_ids if task_id.startswith(PLAYBOOK_REPLAY_STREAM_ID_PREFIX)
    ]
    for stream_id in replays:
        await request_stop(stream_id)
    return replays


async def _held_lock(conversation_id: str) -> str | None:
    """Read the executor busy lock's raw "stream_id:task_id" value; None when no run holds it."""
    # Raw client.get(): the value is a plain string, which redis_cache.get() cannot deserialize.
    raw_lock = await redis_cache.client.get(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
    return decode_raw_item(raw_lock) if raw_lock is not None else None


async def _stop_running_executor(
    conversation_id: str, lock_value: str
) -> tuple[str, list[RunningSubagent]]:
    """Cancel the lock-holding run and free its lock; return its task id and the subagents it stopped."""
    stream_id, task_id = parse_lock_value(lock_value)
    subagents = (
        await stop_stream(conversation_id, stream_id) if stream_id not in _NO_STREAM_IDS else []
    )
    # Freed only once the stream is cancelled: freeing a run that kept going lets two run at once.
    await redis_cache.delete(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
    await drop_progress(conversation_id, lock_value)
    log.info(
        f"{LogTag.TOOL} Stopped the running executor task",
        task_id=task_id,
        stream_id=stream_id,
        conversation_id=conversation_id,
    )
    return task_id, subagents


async def _close_approvals(
    conversation_id: str, user_id: str, approval_ids: Collection[str]
) -> list[str]:
    """Close these pending approvals on the ledger, so no Approve revives stopped work."""
    if not approval_ids:
        return []
    return await cancel_ledger_approvals(conversation_id, user_id, approval_ids)


async def _settle(conversation_id: str, work: WorkCancelled, redirect: str | None) -> None:
    """Tell the next executor run the work was stopped."""
    if not work.stopped_anything:
        return
    # Only when a run actually died: a spared live executor would drain the notice as its own.
    if work.executor_stopped or work.subagent_ids:
        await ExecutorInbox(conversation_id).announce_interruption(redirect)
    log.set_ns(
        "work_cancel",
        conversation_id=conversation_id,
        executor_stopped=work.executor_stopped,
        pending=len(work.pending_task_ids),
        subagents=len(work.subagent_ids),
        approvals=len(work.approval_ids),
        browser_jobs=len(work.browser_jobs),
    )
