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
from typing import Any

from langsmith import traceable

from app.agents.core.background.executor_capture import (
    build_returned_to_frontend_note,
    teardown_executor_capture,
)
from app.agents.core.background.executor_queue import (
    LockState,
    PreparedQueuedTask,
    get_lock_state,
    pop_next_queued_run,
    reclaim_stranded_task,
    release_lock_if_owned,
)
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.result_delivery import deliver_result, persist_cancelled_run
from app.agents.core.background.session import ExecutorRun, get_session, signal_executor_done
from app.agents.core.subagents.subagent_runner import (
    execute_subagent_stream,
    prepare_executor_execution,
)
from app.constants.executor import VOICE_TTS_KEY
from app.core.stream_manager import StreamManager
from app.utils.agent_utils import format_sse_data
from shared.py.wide_events import log

# Prevent GC of background tasks spawned from the queue
_queued_executor_tasks: set[asyncio.Task] = set()


@traceable(name="executor_background", run_type="chain")
async def run_executor_background(
    run: ExecutorRun,
    task: str,
    configurable: dict[str, Any],
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
        result_text, result_type = await _execute_executor(task, configurable, run.stream_id)
        log.info("Background executor completed", task_id=run.task_id, stream_id=run.stream_id)
    finally:
        await _finalize_executor_run(run, result_text, result_type)


async def _execute_executor(
    task: str,
    configurable: dict[str, Any],
    stream_id: str,
) -> tuple[str, str]:
    """Run the executor agent graph once. Returns (result_text, result_type).

    Tool events stream to the session's collector via make_redis_stream_writer
    so the terminal path can persist the executor's tool_data. Never raises —
    errors come back as ("...", "error").

    The executor inherits the comms agent's model/provider/reasoning from
    ``configurable`` (free -> Gemini, paid -> MiniMax M3), so no override here.
    """
    try:
        ctx, error = await prepare_executor_execution(
            task=task,
            configurable=configurable,
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
    """Post-run cleanup, in order: signal done → deliver → close stream → hand off lock."""
    was_cancelled = bool(run.stream_id) and await StreamManager.is_cancelled(run.stream_id)

    # Snapshot which native cards were returned to the frontend BEFORE signalling
    # done — for live streams the chat path drains + tears down the session in
    # parallel once done_event fires, so reading it after would race teardown.
    returned_note = "" if was_cancelled else build_returned_to_frontend_note(run.stream_id)

    # Signal SSE consumer that tool events are done so it can drain the session
    # into the comms ack and publish [DONE]. Comms re-narration runs in parallel.
    signal_executor_done(run.stream_id)

    # Delivery and stream-close are best-effort: a failure here must NOT skip the
    # queue handoff below, or queued tasks strand and the busy lock leaks until
    # its TTL. The lock lifecycle is the load-bearing step — always run it.
    try:
        await _deliver_terminal_outcome(run, result_text, result_type, was_cancelled, returned_note)
        await _close_queued_stream(run, was_cancelled)
    except Exception as e:  # noqa: BLE001 — never let delivery failure strand the queue
        log.error(
            "Executor finalize delivery/close failed",
            stream_id=run.stream_id,
            task_id=run.task_id,
            error=str(e),
        )

    prepared = await _hand_off_queue(run)
    if prepared is not None:
        _spawn_queued_run(run, prepared)


async def _deliver_terminal_outcome(
    run: ExecutorRun,
    result_text: str,
    result_type: str,
    was_cancelled: bool,
    returned_note: str,
) -> None:
    """Route the run's terminal outcome to exactly one delivery entry point.

    A cancelled run's already-streamed cards must not vanish: self-owning runs
    (queued / background workflow) persist them here, while live runs defer to
    the comms path's attach step (persisting here too would duplicate cards). A
    completed run with text narrates and delivers.
    """
    if was_cancelled:
        if run.executor_owns_tool_data:
            await persist_cancelled_run(run)
        else:
            log.info(
                "Live executor cancelled; comms stream owns tool_data persistence",
                task_id=run.task_id,
                stream_id=run.stream_id,
            )
    elif result_text:
        notification_text = await deliver_result(run, result_text, result_type, returned_note)
        await _publish_voice_tts(run.stream_id, notification_text)


async def _publish_voice_tts(stream_id: str, notification_text: str | None) -> None:
    """Speak the narrated answer on a voice-mode stream.

    Voice mode pushes the comms-narrated answer back through the SSE channel so
    the voice agent speaks it. The frontend still renders it from the WebSocket
    push delivered by ``deliver_result``, so this is TTS-only (never forwarded to
    the UI). Only live streams are ever marked voice mode, so queued/workflow
    runs never reach here with ``session.voice_mode`` set.
    """
    if not notification_text:
        return
    session = get_session(stream_id)
    if session is not None and session.voice_mode:
        await StreamManager.publish_chunk(
            stream_id,
            format_sse_data({VOICE_TTS_KEY: notification_text}),
        )


async def _close_queued_stream(run: ExecutorRun, was_cancelled: bool) -> None:
    """Tear down a queued run's session and close the SSE stream it owns.

    Only queued runs own a stream the frontend subscribed to via
    ``executor.stream_started``; live sessions are torn down by the chat path. A
    cancelled queued stream closes silently — the cancel already told the client
    — so no [DONE] / complete_stream.
    """
    if not run.is_queued:
        return
    teardown_executor_capture(run.stream_id)
    if not was_cancelled:
        await StreamManager.publish_chunk(run.stream_id, "data: [DONE]\n\n")
        await StreamManager.complete_stream(run.stream_id)


async def _hand_off_queue(run: ExecutorRun) -> PreparedQueuedTask | None:
    """Pop and prepare the next queued task for this conversation, or None.

    Runs on EVERY terminal path, cancelled included: a Stop targets the running
    task only — queued tasks were acknowledged ("I'll handle it right after") and
    must still run. (cancel_executor with cancel-all clears the queue itself, so
    this pops nothing in that case.)

    Ownership-checked against the busy lock:
      - FOREIGN — a newer run already owns the lock; a stale finalize must not
        touch it or the queue (the owner's finalize drains it).
      - OURS    — pop the next task (pop overwrites the lock before returning, so
        a concurrent call_executor can't grab it via SET NX in a delete→re-set
        gap); release the lock if the queue was empty.
      - FREE    — fall through to the NX reclaim below.

    The reclaim closes the strand window: a task enqueued between the empty pop
    and the release (or left behind a cancel-freed lock) is NX-claimed and
    returned instead of sitting in Redis until the queue TTL.
    """
    lock_state = await get_lock_state(run.conversation_id, run.stream_id, run.task_id)
    if lock_state is LockState.FOREIGN:
        return None

    prepared = None
    if lock_state is LockState.OURS:
        prepared = await pop_next_queued_run(run.conversation_id)
        if prepared is None:
            await release_lock_if_owned(run.conversation_id, run.stream_id, run.task_id)
    if prepared is None:
        prepared = await reclaim_stranded_task(run.conversation_id)
    return prepared


def _spawn_queued_run(run: ExecutorRun, prepared: PreparedQueuedTask) -> None:
    """Spawn the next queued run as a GC-tracked background task."""
    bg_task = asyncio.create_task(
        run_executor_background(
            run=prepared.run,
            task=prepared.task,
            configurable=prepared.configurable,
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
