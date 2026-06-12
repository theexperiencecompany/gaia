"""Background executor lifecycle: execute → finalize → hand off the queue.

Spawned by the call_executor tool (live runs) or by the previous run's
finalize step (queued runs) via asyncio.create_task(). Runs the executor
agent graph with a Redis stream writer for tool events, then finalizes:

  1. Signal the executor-done event so any waiting chat stream can close
     its SSE.
  2. Route the terminal outcome through exactly one delivery entry point
     (``deliver_result`` for finished runs, ``persist_cancelled_run`` for
     cancelled runs that self-own their tool_data — see result_delivery).
  3. For queued runs, tear down the session and close the stream.
  4. Hand the busy lock to the next queued task, or release it.

The executor:busy Redis key prevents concurrent executor spawns per
conversation. TTL of 30 minutes is a safety net — released explicitly.
"""

import asyncio
from datetime import datetime

from langsmith import traceable

from app.agents.core.background.executor_capture import (
    build_returned_to_frontend_note,
    teardown_executor_capture,
)
from app.agents.core.background.executor_queue import (
    LockState,
    get_lock_state,
    pop_next_queued_run,
    reclaim_stranded_task,
    release_lock_if_owned,
)
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.result_delivery import deliver_result, persist_cancelled_run
from app.agents.core.background.session import ExecutorRun, signal_executor_done
from app.agents.core.subagents.subagent_runner import (
    execute_subagent_stream,
    prepare_executor_execution,
)
from app.core.stream_manager import StreamManager
from shared.py.wide_events import log

# Prevent GC of background tasks spawned from the queue
_queued_executor_tasks: set[asyncio.Task] = set()


@traceable(name="executor_background", run_type="chain")
async def run_executor_background(
    run: ExecutorRun,
    task: str,
    configurable: dict,
    user_time: datetime,
) -> None:
    """Run the executor agent in background and hand its result to delivery.

    Designed for asyncio.create_task(). Never raises — all exceptions
    caught and routed through comms as an [EXECUTOR_ERROR] message.

    Tool events stream live to the SSE consumer during execution. When
    execution finishes, _finalize_executor_run signals completion, delivers
    the result, and hands off the queue lock.

    Inherits `langfuse_trace_id` from the parent's `configurable` so this run's
    LLM/tool spans land on the same Langfuse trace as comms.
    """
    result_text = ""
    result_type = "final"

    try:
        result_text, result_type = await _execute_executor(
            task, configurable, user_time, run.stream_id
        )
        log.info("Background executor completed", task_id=run.task_id, stream_id=run.stream_id)
    finally:
        await _finalize_executor_run(run, result_text, result_type)


async def _execute_executor(
    task: str,
    configurable: dict,
    user_time: datetime,
    stream_id: str,
) -> tuple[str, str]:
    """Run the executor agent graph once. Returns (result_text, result_type).

    Tool events stream to the session's collector via make_redis_stream_writer
    so the terminal path can persist the executor's tool_data. Never raises —
    errors come back as ("...", "error").
    """
    try:
        ctx, error = await prepare_executor_execution(
            task=task,
            configurable=configurable,
            user_time=user_time,
            stream_id=stream_id,
        )
        if error or ctx is None:
            log.error("Executor prep failed", error=error)
            return (error or "Executor agent not available"), "error"
        writer = make_redis_stream_writer(stream_id)
        result_text = await execute_subagent_stream(ctx=ctx, stream_writer=writer)
        return result_text, "final"
    except Exception as e:
        log.error("Executor run failed", stream_id=stream_id, error=str(e))
        return str(e), "error"


async def _finalize_executor_run(
    run: ExecutorRun,
    result_text: str,
    result_type: str,
) -> None:
    """The full post-run cleanup: signal done, deliver, tear down, hand off lock."""
    was_cancelled = bool(run.stream_id) and await StreamManager.is_cancelled(run.stream_id)

    # Snapshot which native cards were returned to the frontend BEFORE signalling
    # done — for live streams the chat path drains + tears down the session in
    # parallel once done_event fires, so reading it after would race teardown.
    returned_note = "" if was_cancelled else build_returned_to_frontend_note(run.stream_id)

    # Signal SSE consumer that tool events are done so it can drain the session
    # into the comms ack and publish [DONE]. Comms re-narration runs in parallel.
    signal_executor_done(run.stream_id)

    if was_cancelled:
        # The run was stopped, but cards already produced must not vanish.
        # Self-owning runs (queued/workflow) persist them here BEFORE teardown
        # below; live streams are owned by the comms path's attach step, so we
        # skip here to avoid duplicate cards.
        if run.executor_owns_tool_data:
            await persist_cancelled_run(run)
        else:
            log.info(
                "Live executor cancelled; comms stream owns tool_data persistence",
                task_id=run.task_id,
                stream_id=run.stream_id,
            )
    elif result_text:
        await deliver_result(run, result_text, result_type, returned_note)

    if run.is_queued:
        teardown_executor_capture(run.stream_id)
        if not was_cancelled:
            await StreamManager.publish_chunk(run.stream_id, "data: [DONE]\n\n")
            await StreamManager.complete_stream(run.stream_id)

    # ── Queue / lock handoff ──────────────────────────────────────────
    # Runs on EVERY terminal path, cancelled included: a Stop targets the
    # running task only — queued tasks were acknowledged ("I'll handle it right
    # after") and must still run. (cancel_executor with cancel-all clears the
    # queue itself, so this pops nothing in that case.)
    #
    # The handoff is ownership-checked: pop/release only while this run still
    # holds the busy lock — a stale finalize (cancelled and already replaced by
    # a newer run) must never delete or overwrite the new holder's lock. A FREE
    # lock (TTL expiry / cancel released it) goes through the NX reclaim so a
    # concurrent call_executor acquirer always wins cleanly.
    lock_state = await get_lock_state(run.conversation_id, run.stream_id, run.task_id)
    if lock_state is LockState.FOREIGN:
        return

    prepared = None
    if lock_state is LockState.OURS:
        # pop overwrites the lock before returning, so a concurrent
        # call_executor cannot grab it via SET NX in a delete→re-set gap.
        prepared = await pop_next_queued_run(run.conversation_id)
        if prepared is None:
            await release_lock_if_owned(run.conversation_id, run.stream_id, run.task_id)
    if prepared is None:
        # Closes the strand window: a task enqueued between the empty pop and
        # the release above (or left behind a freed lock) is claimed via NX
        # and spawned instead of sitting in Redis until the queue TTL.
        prepared = await reclaim_stranded_task(run.conversation_id)
    if prepared is None:
        return

    bg_task = asyncio.create_task(
        run_executor_background(
            run=prepared.run,
            task=prepared.task,
            configurable=prepared.configurable,
            user_time=prepared.user_time,
        )
    )
    _queued_executor_tasks.add(bg_task)
    bg_task.add_done_callback(_queued_executor_tasks.discard)

    log.info(
        "Queued executor task spawned",
        task_id=prepared.run.task_id,
        conversation_id=run.conversation_id,
        stream_id=prepared.run.stream_id,
    )
