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

from typing import Any, NamedTuple

from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from langsmith import traceable

from app.agents.core.background.bg_results import has_bg_subagent_results
from app.agents.core.background.comms_narrator import record_executor_cancellation
from app.agents.core.background.executor_capture import (
    build_returned_to_frontend_note,
    teardown_executor_capture,
)
from app.agents.core.background.executor_queue import (
    LockState,
    PreparedQueuedTask,
    build_run_item,
    enqueue_collection_run,
    extend_lock_if_owned,
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
from app.constants.executor import (
    EXECUTOR_APPROVAL_LOST_MESSAGE,
    EXECUTOR_PAUSED,
    EXECUTOR_STEP_LIMIT_MESSAGE,
    MESSAGE_ID_KEY,
    VOICE_TTS_KEY,
)
from app.constants.hil import HIL_PAUSED_LOCK_TTL_SECONDS, HIL_RESUME_CONFIG_KEY
from app.constants.log_tags import LogTag
from app.core.stream_manager import StreamManager
from app.models.agent_models import AgentConfigurable
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.hil.approvals_store import (
    list_parked_subagents_for_conversation,
    set_resume_item,
)
from app.services.hil.resume_slot import release_resume_dispatch
from app.utils.agent_utils import format_sse_data
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import get_trace_id, log, wide_task

#: Task name for a queued executor run. Tests drain by this name to wait out
#: exactly the runs a turn handed off, not every background task in the process.
QUEUED_EXECUTOR_TASK_NAME = "queued-executor-run"


@traceable(name="executor_background", run_type="chain")
async def run_executor_background(
    run: ExecutorRun,
    task: str,
    configurable: AgentConfigurable,
    resume: Command | None = None,
) -> None:
    """Run (or resume) the executor agent in background and hand its result to delivery.

    Designed for asyncio.create_task(). Never raises — all exceptions
    caught and routed through comms as an ``<executor_error>`` message.

    Tool events stream live to the SSE consumer during execution. When
    execution finishes, _finalize_executor_run signals completion, delivers
    the result, and hands off the queue lock.

    ``resume`` continues a thread paused on a HIL approval. A run that pauses
    ends with ``result_type == "paused"``: it has no result to deliver and it
    keeps the busy lock, because the thread has pending work and no other task
    may run on it until the approval resolves.

    Inherits `langfuse_trace_id` from the parent's `configurable` so this run's
    LLM/tool spans land on the same Langfuse trace as comms.
    """
    # This task outlives the spawning request/turn (queued, resumed and
    # post-timeout runs), so it needs its own wide-event boundary or every
    # log.set() in the run (LLM accounting included) is silently discarded.
    # get_trace_id() reads the spawner's trace_id from the task's copied
    # context, correlating this event with the request that dispatched it.
    async with wide_task(
        "executor_run",
        trace_id=get_trace_id() or None,
        conversation_id=run.conversation_id,
        stream_id=run.stream_id,
        task_id=run.task_id,
    ):
        result_text = ""
        result_type = "final"

        # One lifecycle event per run segment; a resumed run re-enters here.
        executor_user_id = run.user.get("user_id", "")
        run_props = {
            "agent": "executor",
            "mode": "background",
            "conversation_id": run.conversation_id,
        }
        if run.task_id:
            run_props["task_id"] = run.task_id
        if executor_user_id:
            capture_event(executor_user_id, AnalyticsEvents.AGENT_RUN_STARTED, run_props)

        try:
            result = await _execute_executor(task, configurable, run.stream_id, resume)
            result_text, result_type = result.text, result.type
            if result.paused_on and not await _record_pause(
                run, task, configurable, result.paused_on
            ):
                # The pause is checkpointed but we could not record how to restart it, so no
                # decision can ever resume this thread. Finalizing it as paused would hold the
                # conversation's busy lock for its full TTL waiting for a resume that cannot
                # come. Fail the run instead: the lock is released, queued work drains, and the
                # sweep closes the orphaned approval.
                result_text, result_type = EXECUTOR_APPROVAL_LOST_MESSAGE, "error"
            log.info(
                f"{LogTag.AGENT} Background executor finished",
                result_type=result_type,
                task_id=run.task_id,
                stream_id=run.stream_id,
            )
            if executor_user_id:
                if result_type == "final":
                    capture_event(executor_user_id, AnalyticsEvents.AGENT_RUN_COMPLETED, run_props)
                elif result_type == "error":
                    capture_event(executor_user_id, AnalyticsEvents.AGENT_RUN_FAILED, run_props)
        finally:
            await _finalize_executor_run(run, task, result_text, result_type)
            if resume is not None:
                # This run held the conversation's resume slot (claimed at dispatch).
                # Freeing it AFTER finalize means the next decision can dispatch only
                # once this run's pause/completion bookkeeping is fully written.
                await release_resume_dispatch(run.conversation_id)


async def _record_pause(
    run: ExecutorRun, task: str, configurable: AgentConfigurable, approval_ids: tuple[str, ...]
) -> bool:
    """Attach this run's re-dispatch context to every approval it paused on.

    A batch pause (the wait_for_subagents join) carries several approvals; each
    gets the same resume context so whichever decision lands first can re-dispatch
    the run. Returns whether every write landed — it is the only thing that makes
    the pause resumable, so a failure is not something the run can carry on
    through: the caller fails the run rather than parking it forever.
    """
    try:
        item = build_run_item(
            task=task,
            task_id=run.task_id,
            configurable=configurable,
            conversation_id=run.conversation_id,
            user_message_id=run.user_message_id,
            bot_message_id=run.bot_message_id,
        )
        for approval_id in approval_ids:
            await set_resume_item(approval_id, item)
        return True
    except Exception as e:  # a lost pause must fail the run, not the process
        log.error(
            f"{LogTag.HIL} Could not record resume context; failing the paused run",
            approval_ids=list(approval_ids),
            stream_id=run.stream_id,
            task_id=run.task_id,
            error=str(e),
        )
        return False


class _ExecutorResult(NamedTuple):
    """One executor run's terminal shape; ``paused_on`` holds the approval id(s)
    when the run stopped on a HIL interrupt instead of finishing — one for a
    gate pause, several for a wait_for_subagents batch pause."""

    text: str
    type: str
    paused_on: tuple[str, ...] = ()


def _paused_approval_ids(payload: dict[str, Any]) -> tuple[str, ...]:
    """Approval ids from an interrupt payload — batch shape first, then single."""
    batch = payload.get("approval_ids")
    if isinstance(batch, list):
        ids = tuple(str(a) for a in batch if a)
        if ids:
            return ids
    single = str(payload.get("approval_id", ""))
    return (single,) if single else ()


async def _execute_executor(
    task: str,
    configurable: AgentConfigurable,
    stream_id: str,
    resume: Command | None = None,
) -> _ExecutorResult:
    """Run the executor agent graph once. Never raises — errors come back as
    ``_ExecutorResult(text, "error")``.

    Tool events stream to the session's collector via make_redis_stream_writer
    so the terminal path can persist the executor's tool_data.

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
            log.error(f"{LogTag.AGENT} Executor prep failed", error=error)
            return _ExecutorResult(error or "Executor agent not available", "error")
        if resume is not None:
            # Tells the handoff tool to probe its subagent thread for a parked
            # interrupt — only a resume replay can encounter one, so fresh runs
            # skip that per-handoff checkpoint read.
            ctx.configurable[HIL_RESUME_CONFIG_KEY] = True
            ctx.config.setdefault("configurable", {})[HIL_RESUME_CONFIG_KEY] = True
        writer = make_redis_stream_writer(stream_id)
        outcome = await execute_subagent_stream(ctx=ctx, stream_writer=writer, resume=resume)
        if outcome.paused:
            approval_ids = _paused_approval_ids(outcome.interrupt or {})
            if not approval_ids:
                # Unresumable: nothing can ever re-dispatch this thread. Fail the
                # run loudly rather than leave the conversation's lock held.
                log.error(f"{LogTag.HIL} Executor paused with no approval_id", stream_id=stream_id)
                return _ExecutorResult("Approval request was malformed", "error")
            return _ExecutorResult("", EXECUTOR_PAUSED, approval_ids)
        return _ExecutorResult(outcome.text, "final")
    except GraphRecursionError as e:
        # The executor exhausted its recursion budget. Log the real cause loudly,
        # but hand comms a friendly message instead of the raw traceback string so
        # the user sees actionable guidance rather than an internal error.
        log.error(
            f"{LogTag.AGENT} Executor hit recursion limit",
            stream_id=stream_id,
            error=str(e),
        )
        return _ExecutorResult(EXECUTOR_STEP_LIMIT_MESSAGE, "error")
    except Exception as e:
        log.error(f"{LogTag.AGENT} Executor run failed", stream_id=stream_id, error=str(e))
        return _ExecutorResult(str(e), "error")


async def _finalize_executor_run(
    run: ExecutorRun,
    task: str,
    result_text: str,
    result_type: str,
) -> None:
    """Post-run cleanup, in order: signal done → deliver → close stream → hand off lock."""
    if result_type == EXECUTOR_PAUSED:
        await _finalize_paused_run(run)
        return

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
        await _deliver_terminal_outcome(
            run, task, result_text, result_type, was_cancelled, returned_note
        )
        await _close_queued_stream(run, was_cancelled)
    except Exception as e:  # never let delivery failure strand the queue
        log.error(
            f"{LogTag.AGENT} Executor finalize delivery/close failed",
            stream_id=run.stream_id,
            task_id=run.task_id,
            error=str(e),
        )

    # A terminal run that leaves landed-but-uncollected subagent work (a parked
    # approval, or results the model never joined on) queues a collection turn
    # NOW, so the very hand-off below pops and runs it. Without this, a card
    # parked mid-turn has no live collector until some later landing wakes one —
    # and decisions on it would be refused in the meantime.
    await _queue_collection_if_uncollected(run, task)

    prepared = await _hand_off_queue(run)
    if prepared is not None:
        _spawn_queued_run(run, prepared)


async def _queue_collection_if_uncollected(run: ExecutorRun, task: str) -> None:
    """Best-effort wake at turn end; the marker dedups against landing-time wakes."""
    del task
    if run.workflow_id is not None:
        return  # headless: the gate denied destructive work; nothing parked to collect
    try:
        uncollected = await has_bg_subagent_results(run.conversation_id) or bool(
            await list_parked_subagents_for_conversation(run.conversation_id)
        )
        if uncollected:
            await enqueue_collection_run(
                run.conversation_id,
                {
                    "user_id": run.user.get("user_id", ""),
                    "email": run.user.get("email", ""),
                    "user_name": run.user.get("name", ""),
                    "user_timezone": run.user.get("timezone"),
                },
            )
    except Exception as e:  # a failed wake must not strand the queue handoff
        log.error(
            f"{LogTag.AGENT} Post-run collection check failed",
            conversation_id=run.conversation_id,
            error=str(e),
        )


async def _finalize_paused_run(run: ExecutorRun) -> None:
    """Close out a run parked on a HIL approval without ending its turn.

    Deliberately does NOT deliver a result, drain the queue, or release the busy
    lock. The executor thread is checkpointed with pending work, so no other task
    may run on it — the lock stays held until ``resolve_approval`` resumes this
    thread and that run's normal finalize drains the queue. Redis outlives the
    process, so the lock survives a restart exactly as the checkpoint does.

    Holding the lock is not enough on its own: its TTL has been counting down
    since this run started, and a user has hours to answer. Re-arm it to cover the
    approval window, or it lapses mid-pause and the next run takes the thread and
    discards the interrupt.

    The SSE consumer is still signalled: the turn's stream must close so the user
    sees the approval card instead of a spinner that never resolves.
    """
    if not await extend_lock_if_owned(
        run.conversation_id, run.stream_id, run.task_id, HIL_PAUSED_LOCK_TTL_SECONDS
    ):
        # Someone else owns the conversation (or Redis is down), so this pause is
        # already at risk of being trampled. Nothing to do but say so loudly.
        log.warning(
            f"{LogTag.HIL} Could not extend busy lock for paused run; the approval "
            "may be orphaned if the lock lapses",
            task_id=run.task_id,
            conversation_id=run.conversation_id,
            stream_id=run.stream_id,
        )
    signal_executor_done(run.stream_id)
    await _close_queued_stream(run, was_cancelled=False)
    log.info(
        f"{LogTag.HIL} Executor paused on approval; busy lock retained",
        task_id=run.task_id,
        conversation_id=run.conversation_id,
        stream_id=run.stream_id,
    )


async def _deliver_terminal_outcome(
    run: ExecutorRun,
    task: str,
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
        # Regardless of who owns the tool_data, comms' context must record the
        # cancellation — otherwise its last knowledge stays 'Task accepted...
        # I'm on it' and later turns claim the task is still running or done.
        await record_executor_cancellation(run.conversation_id, run.task_id, task)
        if run.executor_owns_tool_data:
            await persist_cancelled_run(run)
        else:
            log.info(
                f"{LogTag.AGENT} Live executor cancelled; comms stream owns tool_data persistence",
                task_id=run.task_id,
                stream_id=run.stream_id,
            )
    elif result_text:
        notification_text, message_id = await deliver_result(
            run, result_text, result_type, returned_note
        )
        await _publish_voice_tts(run.stream_id, notification_text, message_id)


async def _publish_voice_tts(
    stream_id: str, notification_text: str | None, message_id: str | None
) -> None:
    """Push the narrated answer on a voice-mode stream so the agent can speak it
    AND bubble it.

    The frame carries the saved message's ``message_id`` so the voice agent can
    forward it as a display frame keyed by that id: the bubble then renders
    immediately off the data channel instead of waiting on the separate
    WebSocket push from ``deliver_result``, and that same WebSocket message
    (identical id) reconciles in place rather than duplicating. Only live
    streams are ever marked voice mode, so queued/workflow runs never reach here
    with ``session.voice_mode`` set.
    """
    if not notification_text:
        return
    session = get_session(stream_id)
    if session is not None and session.voice_mode:
        await StreamManager.publish_chunk(
            stream_id,
            format_sse_data({VOICE_TTS_KEY: notification_text, MESSAGE_ID_KEY: message_id}),
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
    spawn_background_task(
        run_executor_background(
            run=prepared.run,
            task=prepared.task,
            configurable=prepared.configurable,
        ),
        name=QUEUED_EXECUTOR_TASK_NAME,
    )

    log.info(
        f"{LogTag.AGENT} Queued executor task spawned",
        task_id=prepared.run.task_id,
        conversation_id=run.conversation_id,
        stream_id=prepared.run.stream_id,
    )
