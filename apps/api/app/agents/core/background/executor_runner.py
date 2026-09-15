"""Background executor lifecycle: execute → finalize → hand off the queue.

Spawned by the call_executor tool (live runs) or the previous run's finalize
step (queued runs) via asyncio.create_task(). Runs the executor agent graph
with a Redis stream writer for tool events, then finalizes: signals
executor-done so a waiting chat stream can close its SSE; routes the terminal
outcome through exactly one delivery entry point (deliver_result, or
persist_cancelled_run for self-owned tool_data — see result_delivery); for
queued runs tears down the session and closes the stream; then hands the busy
lock to the next queued task, or releases it.

The executor:busy Redis key prevents concurrent executor spawns per
conversation. TTL of 30 minutes is a safety net — released explicitly.
"""

from dataclasses import dataclass, replace
import time
from typing import Any, NamedTuple

from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from langsmith import traceable

from app.agents.core.background.bg_results import has_bg_subagent_results
from app.agents.core.background.comms_narrator import record_executor_cancellation
from app.agents.core.background.executor_capture import (
    build_returned_to_frontend_note,
    drain_executor_tool_data,
    teardown_executor_capture,
)
from app.agents.core.background.executor_queue import (
    PreparedQueuedTask,
    build_run_item,
    enqueue_collection_run,
    extend_lock_if_owned,
    reclaim_stranded_task,
    release_lock_if_owned,
)
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.result_delivery import deliver_result, persist_cancelled_run
from app.agents.core.background.session import (
    ExecutorRun,
    executor_abandoned,
    get_session,
    signal_executor_done,
)
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
from app.models.chat_models import ToolDataEntry
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.hil.approvals_store import (
    list_parked_subagents_for_conversation,
    set_resume_item,
)
from app.services.hil.resume_slot import release_resume_dispatch
from app.services.latency_metrics import (
    observe_executor_active,
    observe_executor_e2e,
    observe_executor_queue_wait,
    observe_executor_run_total,
    observe_executor_ttft,
    span,
)
from app.utils.agent_utils import format_sse_data
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import WorkflowContext, get_trace_id, log, wide_task

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

    Never raises — exceptions route through comms as an <executor_error> message.
    A paused run (resume continuing a HIL approval) keeps the busy lock instead of
    delivering, since the thread has pending work until the approval resolves.
    """
    # This task outlives the spawning request/turn, so it needs its own
    # wide-event boundary or every log.set() (LLM accounting included) is
    # silently discarded. get_trace_id() correlates it back to the dispatcher.
    run_start = time.perf_counter()
    # The busy-lock queue origin, not ``kind``: a HIL resume is RunKind.QUEUED
    # but never waited on the lock, so it must not label as queued.
    queued = run.queued
    async with wide_task(
        "executor_run",
        trace_id=get_trace_id() or None,
        conversation_id=run.conversation_id,
        stream_id=run.stream_id,
        task_id=run.task_id,
        # Surface the turn came from, carried so auxiliary calls inside this run
        # (handed a bare config) can still name it — without it a web turn is
        # metered as "system", undercounting COGS exactly where it matters most.
        conversation_source=configurable.get("conversation_source"),
        # The workflow run this executor is part of; the workflow task stamped it
        # on ITS boundary, this one is fresh. Without it every model call lands in
        # the ledger with no execution, so "what did this run cost" reads only comms.
        **(
            {
                "workflow": WorkflowContext(
                    id=run.workflow_id, execution_id=run.workflow_execution_id
                )
            }
            if run.workflow_id and run.workflow_execution_id
            else {}
        ),
    ):
        result_text = ""
        result_type = "final"
        queue_wait_ms = _queue_wait_ms(run, run_start, configurable, queued=queued)
        ttft_ms: float | None = None
        active_ms: float | None = None

        # One lifecycle event per run segment; a resumed run re-enters here.
        executor_user_id = run.user.get("user_id", "")
        run_props = _run_props(run)
        if executor_user_id:
            capture_event(executor_user_id, AnalyticsEvents.AGENT_RUN_STARTED, run_props)

        try:
            with span() as elapsed_active:
                result = await _execute_executor(task, configurable, run.stream_id, resume)
            active_ms = round(elapsed_active() * 1000.0, 2)
            result_text, result_type = result.text, result.type
            ttft_ms = _executor_ttft_ms(run, run_start)
            if ttft_ms is not None:
                observe_executor_ttft(ttft_ms / 1000.0, queued=queued)
            timing_fields = _timing_fields(queue_wait_ms, ttft_ms, active_ms)
            log.set(executor={"queued": queued, **timing_fields})
            if result.paused_on and not await _record_pause(
                run, task, configurable, result.paused_on
            ):
                # Recording failed, so no decision can ever resume this thread; finalizing
                # as paused would hold the busy lock for its full TTL waiting for a resume
                # that can't come. Fail instead: the lock releases and the sweep closes it.
                result_text, result_type = EXECUTOR_APPROVAL_LOST_MESSAGE, "error"
            # Cancellation and the pause-record outcome are only known here, so
            # read both after the pause decision: the span must carry the same
            # status finalize records, not the pre-pause guess.
            run_cancelled = bool(run.stream_id) and await StreamManager.is_cancelled(run.stream_id)
            observe_executor_active(
                active_ms / 1000.0, status=_active_status(result_type, run_cancelled)
            )
            log.info(
                f"{LogTag.AGENT} Background executor finished",
                result_type=result_type,
                task_id=run.task_id,
                stream_id=run.stream_id,
            )
            _capture_executor_terminal(
                run,
                run_props=run_props,
                queued=queued,
                timing_fields=timing_fields,
                result_type=result_type,
            )
        finally:
            await _finalize_executor_run(run, task, result_text, result_type)
            if resume is not None:
                # This run held the conversation's resume slot (claimed at dispatch).
                # Freeing it AFTER finalize means the next decision can dispatch only
                # once this run's pause/completion bookkeeping is fully written.
                await release_resume_dispatch(run.conversation_id)


def _run_props(run: ExecutorRun) -> dict[str, Any]:
    """Build the lifecycle props shared by the start and terminal events."""
    props: dict[str, Any] = {
        "agent": "executor",
        "mode": "background",
        "conversation_id": run.conversation_id,
    }
    if run.task_id:
        props["task_id"] = run.task_id
    return props


def _timing_fields(
    queue_wait_ms: float | None, ttft_ms: float | None, active_ms: float | None
) -> dict[str, float]:
    """Collect the measured executor timings, omitting spans that never happened."""
    fields: dict[str, float] = {}
    if queue_wait_ms is not None:
        fields["queue_wait_ms"] = queue_wait_ms
    if ttft_ms is not None:
        fields["executor_ttft_ms"] = ttft_ms
    if active_ms is not None:
        fields["executor_active_ms"] = active_ms
    return fields


def _queue_wait_ms(
    run: ExecutorRun, run_start: float, configurable: AgentConfigurable, *, queued: bool
) -> float | None:
    """Observe dispatch-to-start queue wait, or None without a usable stamp.

    A queued run can survive a restart inside its 1h TTL, mixing monotonic
    epochs — a negative delta is garbage, not a measurement.
    """
    if run.t_dispatch_perf is None:
        return None
    queue_wait_s = run_start - run.t_dispatch_perf
    if queue_wait_s < 0.0:
        return None
    observe_executor_queue_wait(
        queue_wait_s,
        source=str(configurable.get("conversation_source") or "unknown"),
        queued=queued,
    )
    return round(queue_wait_s * 1000.0, 2)


def _active_status(result_type: str, cancelled: bool) -> str:
    """Label the active span with the same statuses finalize records."""
    if result_type == "error":
        return "error"
    if result_type == EXECUTOR_PAUSED:
        return "paused"
    return "cancelled" if cancelled else "success"


def _capture_executor_terminal(
    run: ExecutorRun,
    *,
    run_props: dict[str, Any],
    queued: bool,
    timing_fields: dict[str, float],
    result_type: str,
) -> None:
    """Emit the run's terminal lifecycle event with its measured timings."""
    user_id = run.user.get("user_id", "")
    if not user_id or result_type not in ("final", "error"):
        return
    event = (
        AnalyticsEvents.AGENT_RUN_COMPLETED
        if result_type == "final"
        else AnalyticsEvents.AGENT_RUN_FAILED
    )
    capture_event(
        user_id,
        event,
        {**run_props, "queued": queued, **timing_fields},
        dedupe_key=run.task_id or run.stream_id,
    )


async def _record_pause(
    run: ExecutorRun, task: str, configurable: AgentConfigurable, approval_ids: tuple[str, ...]
) -> bool:
    """Attach this run's re-dispatch context to every approval it paused on.

    A batch pause (wait_for_subagents) carries several approvals; each gets the
    same resume context so whichever decision lands first can re-dispatch. A
    failed write means the caller fails the run rather than parking it forever.
    """
    try:
        item = build_run_item(
            task=task,
            configurable=configurable,
            # A pause re-dispatch is a new incarnation: drop the original stamp
            # so the resumed run measures no queue wait for user decision time,
            # and clear the queue origin — it did not wait on the busy lock.
            identity=replace(run.identity, t_dispatch_perf=None, queued=False),
            workflow_execution_id=run.workflow_execution_id,
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


def _executor_ttft_ms(run: ExecutorRun, run_start: float) -> float | None:
    """First executor frame minus dispatch (or run start without a stamp).

    None when no frame was written, or the delta is negative (mixed
    monotonic epochs across a restart) — missing beats zero-filled.
    """
    session = get_session(run.stream_id)
    first_frame = session.executor_first_frame_perf if session is not None else None
    if first_frame is None:
        return None
    base = run.t_dispatch_perf if run.t_dispatch_perf is not None else run_start
    ttft_ms = round((first_frame - base) * 1000.0, 2)
    return ttft_ms if ttft_ms >= 0.0 else None


class _ExecutorResult(NamedTuple):
    """One executor run's terminal shape.

    paused_on holds the approval id(s) when the run stopped on a HIL interrupt
    instead of finishing — one for a gate pause, several for a batch pause.
    """

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
    """Run the executor agent graph once. Never raises on error.

    Errors return as _ExecutorResult(text, "error"). Tool events stream to the
    session's collector via make_redis_stream_writer. The executor inherits comms'
    model/provider/reasoning from configurable (free -> Gemini, paid -> MiniMax M3).
    """
    try:
        with span() as elapsed_prep:
            ctx, error = await prepare_executor_execution(
                task=task,
                configurable=configurable,
                stream_id=stream_id,
            )
        log.set(executor={"prep_ms": round(elapsed_prep() * 1000.0, 2)})
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
    """Post-run cleanup, in order: signal done → deliver → free the lock → hand it on."""
    if result_type == EXECUTOR_PAUSED:
        await _finalize_paused_run(run)
        return

    was_cancelled = bool(run.stream_id) and await StreamManager.is_cancelled(run.stream_id)

    # Snapshot returned-cards BEFORE signalling done: live streams tear down the
    # session in parallel once done_event fires, so reading after would race it.
    # Only meaningful where cards render — a bot/workflow delivery has no card to fall back on.
    build_note = not was_cancelled and run.renders_native_cards
    returned_note = build_returned_to_frontend_note(run.stream_id) if build_note else ""

    # Snapshot cards delivery will persist, same reason: every comms consumer
    # tears the session down the moment done_event fires, so a read from inside
    # delivery comes back empty. None means a live run — comms owns those cards.
    tool_data = drain_executor_tool_data(run.stream_id) if run.executor_owns_tool_data else None

    # Signal SSE consumer that tool events are done so it can drain the session
    # into the comms ack and publish [DONE]. Comms re-narration runs in parallel.
    signal_executor_done(
        run.stream_id,
        failed=result_type == "error",
        reason=result_text if result_type == "error" else None,
    )

    # The waiter gave up on this executor and closed its run as failed. A result
    # delivered now would answer a turn that is over, and a collection queued
    # now would start work on it; only the lock release below is still owed.
    abandoned = executor_abandoned(run.stream_id)
    if abandoned:
        log.warning(
            f"{LogTag.AGENT} Executor finished after its waiter gave up; result not delivered",
            stream_id=run.stream_id,
            task_id=run.task_id,
            result_type=result_type,
        )

    # Delivery is best-effort: a failure here must NOT skip the lock release and
    # queue handoff below, or queued tasks strand and the busy lock leaks until
    # its TTL. The lock lifecycle is the load-bearing step — always run it.
    try:
        if not abandoned:
            await _deliver_terminal_outcome(
                run,
                task,
                TerminalOutcome(
                    result_text=result_text,
                    result_type=result_type,
                    was_cancelled=was_cancelled,
                    returned_note=returned_note,
                    tool_data=tool_data,
                ),
            )
    except Exception as e:  # never let delivery failure strand the queue
        log.error(
            f"{LogTag.AGENT} Executor finalize delivery failed",
            stream_id=run.stream_id,
            task_id=run.task_id,
            error=str(e),
        )

    # Release the busy lock now, not at end of finalize: held longer, comms'
    # executor_status hook keeps reading "still running," and a mid-finalize
    # exception would strand it for the full 30-min TTL. Ownership-checked.
    try:
        await release_lock_if_owned(run.conversation_id, run.stream_id, run.task_id)
        await _close_queued_stream(run, was_cancelled)
    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Executor finalize lock release / stream close failed",
            stream_id=run.stream_id,
            task_id=run.task_id,
            error=str(e),
        )

    end_status = (
        "error" if result_type == "error" else ("cancelled" if was_cancelled else "success")
    )
    queued = run.queued
    if run.t_dispatch_perf is not None:
        e2e_s = time.perf_counter() - run.t_dispatch_perf
        if e2e_s >= 0.0:  # mixed-epoch guard, same as queue wait above
            observe_executor_e2e(e2e_s, status=end_status, queued=queued)
    observe_executor_run_total(status=end_status, queued=queued)

    # A terminal run leaving landed-but-uncollected subagent work queues a
    # collection turn NOW, so the hand-off below claims it — otherwise a parked
    # card has no live collector until a later landing, and decisions refuse meanwhile.
    if not abandoned:
        await _queue_collection_if_uncollected(run, task)

    # Hand the conversation on via NX re-acquire (lock is already free). Runs on
    # every terminal path, cancelled included — a Stop targets only the running
    # task, so queued tasks must still run; claims nothing if a concurrent call_executor won first.
    prepared = await reclaim_stranded_task(run.conversation_id)
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
                workflow_execution_id=run.workflow_execution_id,
            )
    except Exception as e:  # a failed wake must not strand the queue handoff
        log.error(
            f"{LogTag.AGENT} Post-run collection check failed",
            conversation_id=run.conversation_id,
            error=str(e),
        )


async def _finalize_paused_run(run: ExecutorRun) -> None:
    """Close out a run parked on a HIL approval without ending its turn.

    Doesn't deliver a result, drain the queue, or release the busy lock — it stays
    held until resolve_approval resumes this thread. Re-arms the lock's TTL to
    cover the approval window, and still signals SSE so the user sees the approval card.
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
    observe_executor_run_total(status="paused", queued=run.queued)
    log.info(
        f"{LogTag.HIL} Executor paused on approval; busy lock retained",
        task_id=run.task_id,
        conversation_id=run.conversation_id,
        stream_id=run.stream_id,
    )


@dataclass(frozen=True)
class TerminalOutcome:
    """The terminal facts of one executor run, as _finalize_run snapshotted them.

    tool_data is None for a live run, whose cards the comms stream owns.
    """

    result_text: str
    result_type: str
    was_cancelled: bool
    returned_note: str
    tool_data: list[ToolDataEntry] | None


async def _deliver_terminal_outcome(
    run: ExecutorRun,
    task: str,
    outcome: TerminalOutcome,
) -> None:
    """Route the run's terminal outcome to exactly one delivery entry point.

    A cancelled run's already-streamed cards must not vanish: self-owning runs
    persist them here, live runs defer to comms' attach step (None means that) —
    persisting here too would duplicate cards. A completed run with text narrates and delivers.
    """
    if outcome.was_cancelled:
        # Regardless of who owns the tool_data, comms' context must record the
        # cancellation — otherwise its last knowledge stays 'Task accepted...
        # I'm on it' and later turns claim the task is still running or done.
        await record_executor_cancellation(run.conversation_id, run.task_id, task)
        if outcome.tool_data is None:
            log.info(
                f"{LogTag.AGENT} Live executor cancelled; comms stream owns tool_data persistence",
                task_id=run.task_id,
                stream_id=run.stream_id,
            )
        else:
            await persist_cancelled_run(run, outcome.tool_data)
    elif outcome.result_text:
        notification_text, message_id = await deliver_result(
            run,
            outcome.result_text,
            outcome.result_type,
            outcome.returned_note,
            tool_data=outcome.tool_data,
        )
        await _publish_voice_tts(run.stream_id, notification_text, message_id)


async def _publish_voice_tts(
    stream_id: str, notification_text: str | None, message_id: str | None
) -> None:
    """Push the narrated answer on a voice-mode stream so the agent speaks AND bubbles it.

    The frame carries the message_id so the voice agent forwards it as a display
    frame, rendering off the data channel immediately; the later WebSocket push
    (same id) then reconciles in place instead of duplicating. Only live streams are ever voice mode.
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
    executor.stream_started; live sessions are torn down by the chat path. A
    cancelled queued stream closes silently — the cancel already told the client
    — so no [DONE] / complete_stream.
    """
    if not run.is_queued:
        return
    teardown_executor_capture(run.stream_id)
    if not was_cancelled:
        await StreamManager.publish_chunk(run.stream_id, "data: [DONE]\n\n")
        await StreamManager.complete_stream(run.stream_id)


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
