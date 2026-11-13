"""Background executor lifecycle: execute → finalize → hand off the queue.

Spawned by the call_executor tool (live runs) or the previous run's finalize
step (queued runs) via asyncio.create_task(). Runs the executor agent graph
with a Redis stream writer for tool events, then finalizes: signals
executor-done so a waiting todo run can read the result; logs the run's end as
WorkFinished, which the conversation step narrates; for queued runs tears down
the session and closes the stream; then hands the busy lock to the next queued
task, or releases it.

The executor:busy Redis key prevents concurrent executor spawns per
conversation. TTL of 30 minutes is a safety net — released explicitly.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
import time
from typing import NamedTuple
from uuid import uuid4

from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from langsmith import traceable

from app.agents.core.background.confirmation_gate import record_confirmation_asked
from app.agents.core.background.executor_capture import (
    drain_executor_image,
    drain_executor_tool_data,
)
from app.agents.core.background.executor_channel import ExecutorInbox, decide_drain
from app.agents.core.background.executor_progress import ProgressRecorder, StreamWriter
from app.agents.core.background.executor_queue import (
    LockClaim,
    PreparedQueuedTask,
    build_lock_value,
    build_run_item,
    close_detached_stream,
    extend_lock_if_owned,
    hold_run_alive,
    keep_alive,
    prepare_run_from_item,
    reclaim_dead_lock,
    release_lock_if_owned,
)
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.session import (
    ExecutorRun,
    RunIdentity,
    executor_abandoned,
    get_session,
    signal_executor_done,
    teardown_session,
)
from app.agents.core.outcome_review import NOT_REVIEWED, OutcomeReview, review_run
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    execute_subagent_stream,
    paused_approval_ids,
    prepare_executor_execution,
    thread_messages,
)
from app.agents.prompts.comms_prompts import outcome_delivery_note
from app.constants.agents import NON_WAKING_TAGS, AgentTag, OutcomeState
from app.constants.conversation import WORK_STOPPED_REPORT
from app.constants.executor import (
    EXECUTOR_APPROVAL_LOST_MESSAGE,
    EXECUTOR_CARRY_TASK,
    EXECUTOR_CRASH_MESSAGE,
    EXECUTOR_ERROR_APPROVAL_LOST,
    EXECUTOR_ERROR_MALFORMED_APPROVAL,
    EXECUTOR_ERROR_NO_ANSWER,
    EXECUTOR_ERROR_PREP_FAILED,
    EXECUTOR_PAUSED,
    EXECUTOR_STEP_LIMIT_MESSAGE,
)
from app.constants.hil import HIL_PAUSED_LOCK_TTL_SECONDS, HIL_RESUME_CONFIG_KEY
from app.constants.log_tags import LogTag
from app.core.stream_manager import StreamManager
from app.models.agent_models import (
    AgentConfigurable,
    AgentConfigurableView,
    run_analytics_context,
)
from app.models.chat_models import ImageData, ToolDataEntry
from app.models.conversation_log_models import WorkOutcome
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import agent_run_lifecycle
from app.services.browser.job_stop import stop_browser_job
from app.services.conversation.work_deltas import WorkDeltas
from app.services.conversation.work_log import (
    WorkReport,
    record_approval_requested,
    record_work_carried,
    record_work_finished,
)
from app.services.hil.approvals_store import get_approval, set_resume_item
from app.services.hil.resume_slot import release_resume_dispatch
from app.services.latency_metrics import (
    observe_executor_active,
    observe_executor_e2e,
    observe_executor_queue_wait,
    observe_executor_run_total,
    observe_executor_ttft,
    span,
)
from app.utils.background_tasks import spawn_background_task
from app.utils.errors import ConversationNotFoundError
from shared.py.analytics.catalog.agents import AgentRunStarted
from shared.py.analytics.context import analytics_context
from shared.py.wide_events import WorkflowContext, get_trace_id, log, wide_task

#: Task name for a queued executor run. Tests drain by this name to wait out
#: exactly the runs a turn handed off, not every background task in the process.
DETACHED_EXECUTOR_TASK_NAME = "detached-executor-run"


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
    Attributed to the turn that started the run tree, wherever it is resumed.
    """
    with analytics_context(run_analytics_context(configurable)):
        await _run_executor(run, task, configurable, resume)


async def _run_executor(
    run: ExecutorRun,
    task: str,
    configurable: AgentConfigurable,
    resume: Command | None,
) -> None:
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
        conversation_source=AgentConfigurableView.model_validate(configurable).conversation_source,
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
        # Equivalent under mutation: read only if execute raised, when result_text is
        # still empty and finalize has nothing to deliver either way.
        stopped = False  # pragma: no mutate
        # Equivalent under mutation: read only if execute raised, when result_type is still
        # "final" and finalize's `if ctx` treats any falsy placeholder alike.
        run_ctx: SubagentExecutionContext | None = None  # pragma: no mutate
        queue_wait_ms = _queue_wait_ms(run, run_start, configurable, queued=queued)
        ttft_ms: float | None = None
        active_ms: float | None = None

        # One lifecycle per run segment; a resumed run re-enters here. Opened before
        # keep_alive so a lost liveness write is a failed run, not an untracked one.
        with agent_run_lifecycle(
            run.user.user_id, _run_props(run), dedupe=run.analytics_dedupe
        ) as lifecycle:
            alive = await keep_alive(
                run.conversation_id, build_lock_value(run.stream_id, run.task_id or "")
            )
            try:
                with span() as elapsed_active:
                    result = await _execute_executor(task, configurable, run, resume)
                active_ms = round(elapsed_active() * 1000.0, 2)
                result_text, result_type, run_ctx = result.text, result.type, result.ctx
                stopped = result.stopped
                error_type = result.error_type
                ttft_ms = _executor_ttft_ms(run, run_start)
                if ttft_ms is not None:
                    observe_executor_ttft(ttft_ms / 1000.0, queued=queued)
                timing_fields = _timing_fields(queue_wait_ms, ttft_ms, active_ms)
                log.set(executor={"queued": queued, **timing_fields})
                if result.paused_on and await _record_pause(
                    run, task, configurable, result.paused_on
                ):
                    await _log_approvals_requested(run, result.paused_on)
                elif result.paused_on:
                    # Recording failed, so no decision can ever resume this thread; finalizing
                    # as paused would hold the busy lock for its full TTL waiting for a resume
                    # that can't come. Fail instead: the lock releases and the sweep closes it.
                    result_text, result_type = EXECUTOR_APPROVAL_LOST_MESSAGE, "error"
                    error_type = EXECUTOR_ERROR_APPROVAL_LOST
                # Cancellation and the pause-record outcome are only known here, so
                # read both after the pause decision: the span must carry the same
                # status finalize records, not the pre-pause guess.
                run_cancelled = bool(run.stream_id) and await StreamManager.is_cancelled(
                    run.stream_id
                )
                observe_executor_active(
                    active_ms / 1000.0, status=_active_status(result_type, run_cancelled)
                )
                log.info(
                    f"{LogTag.AGENT} Background executor finished",
                    result_type=result_type,
                    task_id=run.task_id,
                    stream_id=run.stream_id,
                )
                lifecycle.queued = queued
                lifecycle.queue_wait_ms = queue_wait_ms
                lifecycle.executor_ttft_ms = ttft_ms
                lifecycle.executor_active_ms = active_ms
                lifecycle.paused = result_type == EXECUTOR_PAUSED
                if result_type == "error":
                    lifecycle.failure_reason = error_type
            finally:
                alive.cancel()
                await _finalize_executor_run(
                    run, result_text, result_type, run_ctx, stopped=stopped
                )
                if resume is not None:
                    # This run held the conversation's resume slot (claimed at dispatch).
                    # Freeing it AFTER finalize means the next decision can dispatch only
                    # once this run's pause/completion bookkeeping is fully written.
                    await release_resume_dispatch(run.conversation_id)


def _run_props(run: ExecutorRun) -> AgentRunStarted:
    """Build the start event; its props are the ones the terminal event carries too."""
    return AgentRunStarted(
        agent="executor",
        mode="background",
        conversation_id=run.conversation_id,
        task_id=run.task_id or None,
    )


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


async def _record_pause(
    run: ExecutorRun, task: str, configurable: AgentConfigurable, approval_ids: tuple[str, ...]
) -> bool:
    """Attach this run's re-dispatch context to every approval it paused on.

    Each paused approval gets the same resume context so whichever decision lands
    first can re-dispatch the run. Returns whether every write landed — it is the only thing that makes
    the pause resumable, so a failure is not something the run can carry on
    through: the caller fails the run rather than parking it forever.
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
    instead of finishing. ctx is the prepared execution context, kept so finalize
    can read the thread this run wrote; None when preparation itself failed, in
    which case no model call happened and nothing was committed. error_type is
    the cause of an error result, reported as the run's failure reason. stopped
    is True when the user's Stop cut the graph off before it finished.
    """

    text: str
    type: str
    paused_on: tuple[str, ...] = ()
    ctx: SubagentExecutionContext | None = None
    error_type: str | None = None
    stopped: bool = False


async def _cancel_orphaned_browser_job(conversation_id: str, stream_id: str) -> None:
    """Stop the browser job a failed run left in flight, so it cannot speak a second ending.

    The job outlives the turn, so without this its result wakes a new run
    minutes after comms said this one failed.
    """
    try:
        job_id = await stop_browser_job(conversation_id)
    except Exception as e:  # the run's own error message must still reach comms
        log.error(
            f"{LogTag.AGENT} Could not cancel the browser job left by a failed executor run",
            conversation_id=conversation_id,
            stream_id=stream_id,
            error=str(e),
        )
        return
    if job_id is not None:
        log.warning(
            f"{LogTag.AGENT} Cancelled the browser job orphaned by a failed executor run",
            conversation_id=conversation_id,
            stream_id=stream_id,
            browser={"job_id": job_id},
        )


async def _execute_executor(
    task: str,
    configurable: AgentConfigurable,
    run: ExecutorRun,
    resume: Command | None = None,
) -> _ExecutorResult:
    """Run the executor agent graph once. Never raises on error.

    Errors return as _ExecutorResult(text, "error"). Tool events stream to the
    session's collector via make_redis_stream_writer. The executor inherits comms'
    model/provider/reasoning from configurable (free -> Gemini, paid -> MiniMax M3).
    """
    ctx: SubagentExecutionContext | None = None
    stream_id = run.stream_id
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
            return _ExecutorResult(
                error or "Executor agent not available",
                "error",
                error_type=EXECUTOR_ERROR_PREP_FAILED,
            )
        # Equivalent under mutation: build_agent_config always sets "configurable".
        run_configurable = ctx.config.setdefault("configurable", {})  # pragma: no mutate
        if resume is not None:
            # Tells spawn_subagent to probe its spawn's thread for a parked
            # interrupt — only a resume replay can encounter one, so fresh runs
            # skip that per-spawn checkpoint read.
            ctx.configurable[HIL_RESUME_CONFIG_KEY] = True
            run_configurable[HIL_RESUME_CONFIG_KEY] = True
        if message_id := run.render_message_id:
            ctx.configurable["bot_message_id"] = message_id
            run_configurable["bot_message_id"] = message_id
        progress = ProgressRecorder(
            run.conversation_id, build_lock_value(stream_id, run.task_id or "")
        )
        writer, drain_deltas = _stream_writer(run)
        try:
            outcome = await execute_subagent_stream(
                ctx=ctx, stream_writer=progress.wrap(writer), resume=resume
            )
        finally:
            # Before finalize renews (a pause) or deletes (an ending) the record.
            await progress.settle()
            # The task's live cards reach the stream before its WorkFinished.
            await drain_deltas()
        if outcome.paused:
            approval_ids = paused_approval_ids(outcome.interrupt or {})
            if not approval_ids:
                # Unresumable: nothing can ever re-dispatch this thread. Fail the
                # run loudly rather than leave the conversation's lock held.
                log.error(f"{LogTag.HIL} Executor paused with no approval_id", stream_id=stream_id)
                return _ExecutorResult(
                    "Approval request was malformed",
                    "error",
                    ctx=ctx,
                    error_type=EXECUTOR_ERROR_MALFORMED_APPROVAL,
                )
            return _ExecutorResult("", EXECUTOR_PAUSED, approval_ids, ctx=ctx)
        if not outcome.answered and not outcome.stopped:
            # Nothing reported means nothing confirmed: the worst case, never "done".
            log.error(f"{LogTag.AGENT} Executor ended without an answer", stream_id=stream_id)
            await _cancel_orphaned_browser_job(run.conversation_id, stream_id)
            return _ExecutorResult(
                EXECUTOR_CRASH_MESSAGE, "error", ctx=ctx, error_type=EXECUTOR_ERROR_NO_ANSWER
            )
        return _ExecutorResult(outcome.text, "final", ctx=ctx, stopped=outcome.stopped)
    except GraphRecursionError as e:
        # The executor exhausted its recursion budget. Log the real cause loudly,
        # but hand comms a friendly message instead of the raw traceback string so
        # the user sees actionable guidance rather than an internal error.
        log.error(
            f"{LogTag.AGENT} Executor hit recursion limit",
            stream_id=stream_id,
            error=str(e),
        )
        await _cancel_orphaned_browser_job(run.conversation_id, stream_id)
        return _ExecutorResult(
            EXECUTOR_STEP_LIMIT_MESSAGE, "error", ctx=ctx, error_type=type(e).__name__
        )
    except Exception as e:
        # The raw exception is for the log, never for comms: a bare string (often
        # empty) is not a story, so comms invented one and offered to re-run work
        # that may have half-landed. Say what happened and ask instead.
        log.error(f"{LogTag.AGENT} Executor run failed", stream_id=stream_id, error=str(e))
        await _cancel_orphaned_browser_job(run.conversation_id, stream_id)
        return _ExecutorResult(
            EXECUTOR_CRASH_MESSAGE, "error", ctx=ctx, error_type=type(e).__name__
        )


async def _nothing_to_drain() -> None:
    return None


def _stream_writer(run: ExecutorRun) -> tuple[StreamWriter, Callable[[], Awaitable[None]]]:
    """Return the run's stream writer and what drains it; a step-dispatched run also publishes its cards."""
    writer = make_redis_stream_writer(run.stream_id)
    if not run.task_id:
        return writer, _nothing_to_drain
    deltas = WorkDeltas(run.conversation_id, run.task_id)
    return deltas.wrap(writer), deltas.drain


async def _finalize_executor_run(
    run: ExecutorRun,
    result_text: str,
    result_type: str,
    ctx: SubagentExecutionContext | None = None,
    *,
    stopped: bool = False,
) -> None:
    """Post-run cleanup, in order: signal done → deliver → free the lock → hand it on.

    A Stop discards only what it cut short: a run that finished its answer before
    the cancel landed (stopped False, a final result) is delivered whatever the flag says.
    """
    if result_type == EXECUTOR_PAUSED:
        await _finalize_paused_run(run)
        return

    finished = result_type == "final" and not stopped
    was_cancelled = (
        bool(run.stream_id) and not finished and await StreamManager.is_cancelled(run.stream_id)
    )

    # Snapshot the cards WorkFinished carries BEFORE signalling done: a waiting todo
    # run tears the session down the moment done_event fires.
    tool_data = drain_executor_tool_data(run.stream_id)
    image = drain_executor_image(run.stream_id)

    # Held approval cards go live here, before the done signal so the session is
    # still alive; failure only skips the live push, never finalize — the drain
    # above already persisted the frames.
    try:
        from app.services.hil.bridge import (  # noqa: PLC0415 -- runner is imported too broadly for a top-level hil import
            flush_held_approval_cards,
        )

        await flush_held_approval_cards(run.stream_id)
    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Held card flush failed",
            stream_id=run.stream_id,
            error_type=type(e).__name__,
        )

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

    outcome: TerminalOutcome | None = None
    if not abandoned:
        review = (
            await _review_outcome(run.conversation_id, ctx)
            if ctx is not None and result_type == "final"
            else NOT_REVIEWED
        )
        outcome = TerminalOutcome(
            result_text=result_text,
            result_type=result_type,
            was_cancelled=was_cancelled,
            tool_data=tool_data,
            image=image,
            review=review,
        )

    # Release the busy lock now, not at end of finalize: held longer, comms'
    # turn-start executor status keeps reading "still running," and a mid-finalize
    # exception would strand it for the full 30-min TTL. Ownership-checked.
    try:
        await release_lock_if_owned(run.conversation_id, run.stream_id, run.task_id)
        await _close_run_stream(run, was_cancelled)
    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Executor finalize lock release / stream close failed",
            stream_id=run.stream_id,
            task_id=run.task_id,
            error=str(e),
        )

    await _log_work_finished(run, outcome, stopped=stopped)

    end_status = (
        "error" if result_type == "error" else ("cancelled" if was_cancelled else "success")
    )
    queued = run.queued
    if run.t_dispatch_perf is not None:
        e2e_s = time.perf_counter() - run.t_dispatch_perf
        if e2e_s >= 0.0:  # mixed-epoch guard, same as queue wait above
            observe_executor_e2e(e2e_s, status=end_status, queued=queued)
    observe_executor_run_total(status=end_status, queued=queued)

    # Work landing after this run's LAST model call has no further reasoning step
    # to absorb it, so carry it into a fresh run. Runs on EVERY terminal path,
    # cancelled included: a Stop targets the running task, not later work.

    # Failed before it had a context: carried work would fail setup identically, forever.
    if result_type == "error" and ctx is None:
        log.warning(
            f"{LogTag.AGENT} Executor setup failed; pending work left for the next run",
            conversation_id=run.conversation_id,
            task_id=run.task_id,
        )
        return
    await _carry_pending_into_new_run(run, ctx)


async def _log_approvals_requested(run: ExecutorRun, approval_ids: tuple[str, ...]) -> None:
    """Log each approval a step-dispatched run paused on, so the conversation shows it awaiting the user."""
    if not run.task_id:
        return
    for approval_id in approval_ids:
        record = await get_approval(approval_id)
        if record is None:
            raise LookupError(f"approval {approval_id} the run paused on has no record")
        await record_approval_requested(
            run.conversation_id,
            run.user.user_id,
            run.task_id,
            approval_id,
            summary=record.summary,
            expires_at=record.expires_at,
        )


async def _review_outcome(conversation_id: str, ctx: SubagentExecutionContext) -> OutcomeReview:
    """Check the run's declared outcome against its own tool calls; delivery reads the review.

    The review is an addition to the result, so one that cannot run is dropped, never the result.
    """
    try:
        review = review_run(await thread_messages(ctx))
    except Exception:  # the thread read is a checkpointer call; the result still delivers
        log.error(f"{LogTag.AGENT} Executor outcome review failed")
        return NOT_REVIEWED
    if review.verified and review.declared is OutcomeState.ASK:
        await record_confirmation_asked(conversation_id)
    log.set(
        executor={
            "outcome": review.declared.value if review.declared else None,
            "outcome_verified": review.verified,
        }
    )
    if review.problem:
        log.warning(f"{LogTag.AGENT} Executor outcome not verified", problem=review.problem)
    return review


async def _finalize_paused_run(run: ExecutorRun) -> None:
    """Close out a run parked on a HIL approval without ending its turn.

    Doesn't deliver a result, drain the queue, or release the busy lock — it stays
    held until resolve_approval resumes this thread. Re-arms the lock's TTL to
    cover the approval window, and still signals SSE so the user sees the approval card.
    """
    # A parked run has no process to beat for it: it lives as long as its park.
    await hold_run_alive(
        run.conversation_id,
        build_lock_value(run.stream_id, run.task_id or ""),
        HIL_PAUSED_LOCK_TTL_SECONDS,
    )
    # Work handed over until the resume must still be there when it reads.
    await ExecutorInbox(run.conversation_id).keep_for(HIL_PAUSED_LOCK_TTL_SECONDS)
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
    await _close_run_stream(run, was_cancelled=False)
    observe_executor_run_total(status="paused", queued=run.queued)
    log.info(
        f"{LogTag.HIL} Executor paused on approval; busy lock retained",
        task_id=run.task_id,
        conversation_id=run.conversation_id,
        stream_id=run.stream_id,
    )


@dataclass(frozen=True)
class TerminalOutcome:
    """The terminal facts of one executor run, as _finalize_run snapshotted them."""

    result_text: str
    result_type: str
    was_cancelled: bool
    tool_data: list[ToolDataEntry]
    image: ImageData | None = None
    review: OutcomeReview = NOT_REVIEWED


def _work_outcome(outcome: TerminalOutcome, *, stopped: bool) -> WorkOutcome:
    """Name how the run ended for the conversation log."""
    if outcome.was_cancelled or stopped:
        return WorkOutcome.CANCELLED
    if outcome.result_type == "error":
        return WorkOutcome.FAILED
    return WorkOutcome.DONE


async def _log_work_finished(
    run: ExecutorRun, outcome: TerminalOutcome | None, *, stopped: bool
) -> None:
    """Log the run's end once its busy lock is free; the step narrates it in the task's reply."""
    if outcome is None or not run.task_id:
        return
    review = outcome.review
    ended_as = _work_outcome(outcome, stopped=stopped)
    try:
        await record_work_finished(
            run.conversation_id,
            run.user.user_id,
            run.task_id,
            ended_as,
            WorkReport(
                WORK_STOPPED_REPORT if ended_as is WorkOutcome.CANCELLED else outcome.result_text,
                outcome.tool_data,
                note=outcome_delivery_note(review.declared, review.problem),
                nothing_for_user=review.nothing_for_user,
                image=outcome.image,
            ),
            continued_by_decision=run.active_todo_id is None and run.workflow_execution_id is None,
        )
    except ConversationNotFoundError:
        # The user deleted the conversation while its work ran: the result has nowhere to land.
        log.info(
            "work finished after its conversation was deleted",
            conversation_id=run.conversation_id,
            task_id=run.task_id,
        )


async def _close_run_stream(run: ExecutorRun, was_cancelled: bool) -> None:
    """Tear down the run's session once its cards are drained; a queued run also closes the stream it owns."""
    if not run.is_queued:
        teardown_session(run.stream_id)
        return
    await close_detached_stream(run.stream_id, cancelled=was_cancelled)


def _spawn_detached_run(prepared: PreparedQueuedTask, conversation_id: str) -> None:
    """Spawn a run that owns its own stream, as a GC-tracked background task."""
    spawn_background_task(
        run_executor_background(
            run=prepared.run,
            task=prepared.task,
            configurable=prepared.configurable,
        ),
        name=DETACHED_EXECUTOR_TASK_NAME,
    )

    log.info(
        f"{LogTag.AGENT} Detached executor run spawned",
        task_id=prepared.run.task_id,
        conversation_id=conversation_id,
        stream_id=prepared.run.stream_id,
    )


async def deliver_to_executor(
    conversation_id: str,
    user: AuthenticatedUser,
    task: str,
    *,
    tag: AgentTag | None = None,
    workflow_execution_id: str | None = None,
) -> None:
    """Give the executor work from outside a comms turn — the one way to do it.

    A live run absorbs the task through its inbox, an idle one gets a run started
    to carry it; never a second parallel answer. Tagged work (a subagent result)
    always travels through the inbox so it arrives framed. A free (or freed) lock is
    a fast path — the claim inside _start_executor_run is the atomic decision.
    """
    if (
        tag is None
        and await reclaim_dead_lock(conversation_id)
        and await _start_executor_run(
            conversation_id, user, task, workflow_execution_id=workflow_execution_id
        )
    ):
        return
    await ExecutorInbox(conversation_id).append(str(uuid4()), task, tag)
    log.info(
        f"{LogTag.AGENT} Work handed to the live executor run",
        conversation_id=conversation_id,
    )
    await wake_executor_for_inbox(
        conversation_id, user, workflow_execution_id=workflow_execution_id
    )


async def wake_executor_for_inbox(
    conversation_id: str,
    user: AuthenticatedUser,
    *,
    workflow_execution_id: str | None = None,
) -> None:
    """Start a run to read work already in the inbox when no live run will drain it.

    Checked after the append: only a free lock needs a rescue, and the rescue
    carries EXECUTOR_CARRY_TASK because the entry already holds the real work.
    A lock whose run died with its process is reclaimed first, or it would hold
    the work back for the lock's whole TTL.
    """
    if await reclaim_dead_lock(conversation_id) and await _start_executor_run(
        conversation_id,
        user,
        EXECUTOR_CARRY_TASK,
        workflow_execution_id=workflow_execution_id,
    ):
        log.info(
            f"{LogTag.AGENT} Work landed with no live run; started a carry run",
            conversation_id=conversation_id,
        )


async def _prepare_executor_run(
    conversation_id: str,
    user: AuthenticatedUser,
    task: str,
    task_id: str,
    *,
    workflow_execution_id: str | None = None,
) -> PreparedQueuedTask | None:
    """Claim the conversation and materialize a detached run for the task, its work on the log.

    Built from the user alone: a caller's configurable belongs to the run that
    held it (its thread, subagent id, turn hints), never to the run started here.
    None means another run holds the conversation (or Redis is down).
    """
    # Equivalent under mutation: prepare_run_from_item claims the conversation it is
    # handed, never this item's copy, and the item is never stored.
    identity = RunIdentity(  # pragma: no mutate
        conversation_id=conversation_id,
        task_id=task_id,
        user_message_id=None,
    )
    return await prepare_run_from_item(
        conversation_id,
        build_run_item(
            task=task,
            configurable={
                "user_id": user.user_id,
                "email": user.email or "",
                "user_name": user.name or "",
                "user_timezone": user.timezone,
                "thread_id": conversation_id,
                "execution_mode": "interactive",
            },
            identity=identity,
            workflow_execution_id=workflow_execution_id,
        ),
        claim=LockClaim.ACQUIRE,
    )


async def _start_executor_run(
    conversation_id: str,
    user: AuthenticatedUser,
    task: str,
    *,
    workflow_execution_id: str | None = None,
) -> bool:
    """Materialize, log and spawn a detached run for the task. Returns whether it started.

    Logged once the conversation is claimed, so the step narrates its end and a Stop cancels it.
    """
    task_id = str(uuid4())
    prepared = await _prepare_executor_run(
        conversation_id, user, task, task_id, workflow_execution_id=workflow_execution_id
    )
    if prepared is None:
        return False
    if not await record_work_carried(conversation_id, user.user_id, task_id):
        await release_lock_if_owned(conversation_id, prepared.run.stream_id, task_id)
        await close_detached_stream(prepared.run.stream_id, cancelled=True)
        return False
    # Equivalent under mutation: the spawn reads conversation_id only for its log.info.
    _spawn_detached_run(prepared, conversation_id)  # pragma: no mutate
    return True


async def _carry_pending_into_new_run(
    run: ExecutorRun, ctx: SubagentExecutionContext | None
) -> None:
    """Start a run for work this one finished too early to absorb.

    Absorbed is read off the thread, not a marker: an entry injected on a model
    call that then FAILED was never committed. Only WORK starts a run — a bare
    stop notice stays pending for the next run's drain instead of spawning one.
    """
    try:
        inbox = ExecutorInbox(run.conversation_id)
        pending = await inbox.read()
        if not pending:
            return
        drain = decide_drain(pending, await thread_messages(ctx) if ctx else [])
        for entry in drain.retire:
            await inbox.retire(entry)
        carry = drain.inject
        if all(entry.tag in NON_WAKING_TAGS for entry in carry):
            return

        # Leave the carried entries in the inbox: the new run's drain hook injects
        # each (framed with its INBOX_ENTRY_ID) and retires it only once committed —
        # the crash-safe path. Concatenating + retiring here first lost work on a crash.
        started = await _start_executor_run(
            run.conversation_id,
            run.user,
            EXECUTOR_CARRY_TASK,
            workflow_execution_id=run.workflow_execution_id,
        )
        # Equivalent under mutation: the branch guards only a log.info.
        if not started:  # pragma: no mutate
            log.info(
                f"{LogTag.AGENT} Pending work left for the run that holds the conversation",
                conversation_id=run.conversation_id,
                pending=len(carry),
            )
    except Exception as e:  # a failed carry must not break finalize
        log.error(
            f"{LogTag.AGENT} Could not carry pending work into a new run",
            conversation_id=run.conversation_id,
            error_type=type(e).__name__,
        )
