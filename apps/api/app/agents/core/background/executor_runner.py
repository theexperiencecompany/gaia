"""Background executor lifecycle: execute → finalize → hand off the queue.

Spawned by the call_executor tool (live runs) or the previous run's finalize
step (queued runs) via asyncio.create_task(). Runs the executor agent graph
with a Redis stream writer for tool events, then finalizes: signals
executor-done so a waiting chat stream can close its SSE; routes the terminal
outcome to its cards (run_cards) and to the outbox (run_report); for
queued runs tears down the session and closes the stream; then hands the busy
lock to the next queued task, or releases it.

The executor:busy Redis key prevents concurrent executor spawns per
conversation. TTL of 30 minutes is a safety net — released explicitly.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
import time
from typing import NamedTuple
from uuid import uuid4

from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from langsmith import traceable

from app.agents.core.background.comms_narrator import record_executor_cancellation
from app.agents.core.background.confirmation_gate import record_confirmation_asked
from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.executor_channel import ExecutorInbox, decide_drain
from app.agents.core.background.executor_progress import ProgressRecorder
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
from app.agents.core.background.run_cards import (
    persist_cancelled_run,
    persist_run_cards,
    record_todo_run_report,
)
from app.agents.core.background.run_report import failed_outcome, finished_outcome, run_report
from app.agents.core.background.session import (
    ExecutorRun,
    RunIdentity,
    executor_abandoned,
    get_session,
    signal_executor_done,
)
from app.agents.core.background.todo_run_delivery import deliver_todo_run_result
from app.agents.core.outcome_review import OutcomeReview, registered_is_write, review_run
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    execute_subagent_stream,
    paused_approval_ids,
    prepare_executor_execution,
    thread_messages,
)
from app.constants.agents import NON_WAKING_TAGS, AgentTag, OutcomeState
from app.constants.chat import SourceCategory
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
from app.db.repositories.conversations import conversation_repository
from app.models.agent_models import (
    AgentConfigurable,
    AgentConfigurableView,
    run_analytics_context,
)
from app.models.chat_models import ToolDataEntry
from app.models.run_trace_models import RunState
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import agent_run_lifecycle
from app.services.browser.job_stop import stop_browser_job
from app.services.executor_trace.recorder import RunOwner, begin_run, end_run
from app.services.hil.approvals_store import set_resume_item
from app.services.hil.resume_slot import release_resume_dispatch
from app.services.latency_metrics import (
    observe_executor_active,
    observe_executor_e2e,
    observe_executor_queue_wait,
    observe_executor_run_total,
    observe_executor_ttft,
    span,
)
from app.services.outbox.intake import submit
from app.utils.background_tasks import spawn_background_task
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
        error_type: str | None = None
        # Equivalent under mutation: read only if execute raised, when result_type is still
        # "final" and finalize's `if ctx` treats any falsy placeholder alike.
        run_ctx: SubagentExecutionContext | None = None  # pragma: no mutate
        queue_wait_ms = _queue_wait_ms(run, run_start, configurable, queued=queued)
        ttft_ms: float | None = None
        active_ms: float | None = None
        trace_owner = RunOwner.of(
            user_id=run.user.user_id,
            conversation_id=run.conversation_id,
            run_id=run.stream_id,
            todo_id=run.active_todo_id,
        )
        # A run cut off before it has a result (cancelled mid-flight) ended without one.
        trace_state = RunState.CANCELLED

        # One lifecycle per run segment; a resumed run re-enters here. Opened before
        # keep_alive so a lost liveness write is a failed run, not an untracked one.
        with agent_run_lifecycle(
            run.user.user_id, _run_props(run), dedupe=run.analytics_dedupe
        ) as lifecycle:
            alive = await keep_alive(
                run.conversation_id, build_lock_value(run.stream_id, run.task_id or "")
            )
            if trace_owner is not None:
                await begin_run(trace_owner)
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
                if result.paused_on and not await _record_pause(
                    run, task, configurable, result.paused_on
                ):
                    # Recording failed, so no decision can ever resume this thread; finalizing
                    # as paused would hold the busy lock for its full TTL waiting for a resume
                    # that can't come. Fail instead: the lock releases and the sweep closes it.
                    result_text, result_type = EXECUTOR_APPROVAL_LOST_MESSAGE, "error"
                    error_type = EXECUTOR_ERROR_APPROVAL_LOST
                trace_state = _trace_state(result_type, stopped=stopped)
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
                if trace_owner is not None:
                    await end_run(trace_owner, trace_state)
                async with _holding_resume_slot(run.conversation_id, resume):
                    await _finalize_executor_run(
                        run,
                        task,
                        result_text,
                        result_type,
                        run_ctx,
                        end=RunEnd(stopped=stopped, error_type=error_type),
                    )


@asynccontextmanager
async def _holding_resume_slot(conversation_id: str, resume: Command | None) -> AsyncIterator[None]:
    """Hold the conversation's resume slot (claimed at dispatch) until the run's bookkeeping is written.

    Freeing it only after finalize means the next decision can dispatch once this run's
    pause or completion is fully recorded, and a finalize that raises still frees it.
    """
    try:
        yield
    finally:
        if resume is not None:
            await release_resume_dispatch(conversation_id)


def _trace_state(result_type: str, *, stopped: bool) -> RunState:
    """Return the state a run's trace ends in, from how the run ended."""
    if result_type == EXECUTOR_PAUSED:
        return RunState.PAUSED
    if result_type == "error":
        return RunState.FAILED
    return RunState.CANCELLED if stopped else RunState.FINISHED


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
        writer = progress.wrap(make_redis_stream_writer(stream_id))
        try:
            outcome = await execute_subagent_stream(ctx=ctx, stream_writer=writer, resume=resume)
        finally:
            # Before finalize renews (a pause) or deletes (an ending) the record.
            await progress.settle()
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


@dataclass(frozen=True)
class RunEnd:
    """How a run ended beyond its result: the user stopped it, or the type of the error it ended in."""

    stopped: bool = False
    error_type: str | None = None


async def _finalize_executor_run(
    run: ExecutorRun,
    task: str,
    result_text: str,
    result_type: str,
    ctx: SubagentExecutionContext | None = None,
    *,
    end: RunEnd = RunEnd(),
) -> None:
    """Post-run cleanup, in order: signal done → report to the outbox → free the lock → hand it on.

    A Stop discards only what it cut short: a run that finished its answer before
    the cancel landed (stopped False, a final result) is delivered whatever the flag says.
    """
    if result_type == EXECUTOR_PAUSED:
        await _finalize_paused_run(run)
        return

    finished = result_type == "final" and not end.stopped
    was_cancelled = (
        bool(run.stream_id) and not finished and await StreamManager.is_cancelled(run.stream_id)
    )

    # Snapshot cards delivery will persist BEFORE signalling done: every comms consumer
    # tears the session down the moment done_event fires, so a read from inside
    # delivery comes back empty. None means a live run, whose cards comms owns.
    tool_data = drain_executor_tool_data(run.stream_id) if run.executor_owns_tool_data else None

    # Held approval cards go live here, before the done signal so the session is
    # still alive; failure only skips the live push, never finalize: the drain
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
    # and publish [DONE]. The result reaches the user through the outbox.
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

    # The report is submitted before the lock is released, and a failed submit raises, but only
    # after the lock lifecycle below has run: queued tasks must not strand behind a lost report.
    try:
        if not abandoned:
            await _deliver_terminal_outcome(
                run,
                task,
                TerminalOutcome(
                    result_text=result_text,
                    result_type=result_type,
                    was_cancelled=was_cancelled,
                    tool_data=tool_data,
                    ctx=ctx,
                    error_type=end.error_type,
                ),
            )
    finally:
        await _release_and_hand_on(run, ctx, result_type=result_type, was_cancelled=was_cancelled)


async def _release_and_hand_on(
    run: ExecutorRun,
    ctx: SubagentExecutionContext | None,
    *,
    result_type: str,
    was_cancelled: bool,
) -> None:
    """Free the busy lock and close a detached stream, record the run's end, and carry pending work on."""
    # Release the busy lock now, not at end of finalize: held longer, comms'
    # turn-start executor status keeps reading "still running," and a mid-finalize
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


async def _review_outcome(
    conversation_id: str, ctx: SubagentExecutionContext
) -> OutcomeReview | None:
    """Check the run's declared outcome against its own tool calls; None when its thread cannot be read.

    A run whose thread cannot be read is reported as unverified, never as done.
    """
    try:
        review = review_run(await thread_messages(ctx), registered_is_write)
    except Exception:  # the thread read is a checkpointer call
        log.error(f"{LogTag.AGENT} Executor outcome review failed")
        return None
    if review.verified and review.declared is OutcomeState.NEEDS_YOU:
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
    tool_data: list[ToolDataEntry] | None
    ctx: SubagentExecutionContext | None = None
    error_type: str | None = None


async def _deliver_terminal_outcome(
    run: ExecutorRun,
    task: str,
    outcome: TerminalOutcome,
) -> None:
    """Hand the run's terminal outcome on: its cards to its conversation, what it did to the outbox.

    A cancelled run's already-streamed cards must not vanish: self-owning runs
    persist them here, live runs defer to comms' attach step (None means that) and
    persisting here too would duplicate cards. A finished run reports to the outbox,
    which decides whether, when and where the user hears of it.
    """
    if outcome.was_cancelled:
        # Regardless of who owns the tool_data, comms' context must record the
        # cancellation: otherwise its last knowledge stays 'Started...' and later turns claim the task is still running or done.
        await record_executor_cancellation(run.conversation_id, run.task_id, task)
        if outcome.tool_data is None:
            log.info(
                f"{LogTag.AGENT} Live executor cancelled; comms stream owns tool_data persistence",
                task_id=run.task_id,
                stream_id=run.stream_id,
            )
        else:
            await persist_cancelled_run(run, outcome.tool_data)
        return
    if not outcome.result_text:
        return
    review = (
        await _review_outcome(run.conversation_id, outcome.ctx)
        if outcome.ctx is not None and outcome.result_type == "final"
        else None
    )
    run_outcome = (
        failed_outcome(outcome.error_type)
        if outcome.result_type == "error"
        else finished_outcome(review, outcome.result_text)
    )
    if run.todo_run is not None:
        await record_todo_run_report(
            run, outcome.result_text, outcome.result_type, outcome.tool_data
        )
        await deliver_todo_run_result(
            run, run.todo_run, run_outcome, outcome.result_text, outcome.result_type
        )
        return
    if outcome.tool_data is not None:
        await persist_run_cards(run, outcome.tool_data)
    await submit(run_report(run, run_outcome))


async def _close_queued_stream(run: ExecutorRun, was_cancelled: bool) -> None:
    """Tear down a queued run's session and close the SSE stream it owns.

    Only queued runs own a stream the frontend subscribed to via
    executor.stream_started; live sessions are torn down by the chat path. A
    cancelled queued stream closes silently — the cancel already told the client
    — so no [DONE] / complete_stream.
    """
    if not run.is_queued:
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
    *,
    workflow_execution_id: str | None = None,
) -> PreparedQueuedTask | None:
    """Claim the conversation and materialize a detached run for the task.

    Built from the user and the conversation's run context: a caller's configurable
    belongs to the run that held it (its thread, subagent id, turn hints), never to
    the run started here. None means another run holds the conversation (or Redis is down).
    """
    run_context = await conversation_repository.get_run_context(
        conversation_id, user_id=user.user_id
    )
    configurable: AgentConfigurable = {
        "user_id": user.user_id,
        "email": user.email or "",
        "user_name": user.name or "",
        "user_timezone": run_context.user_timezone or user.timezone,
        "thread_id": conversation_id,
        "execution_mode": "interactive",
    }
    if source := run_context.conversation_source:
        configurable["conversation_source"] = source
        configurable["source_category"] = SourceCategory.from_source(source).value
    task_id = str(uuid4())
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
            configurable=configurable,
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
    """Materialize and spawn a detached run for the task. Returns whether it started."""
    prepared = await _prepare_executor_run(
        conversation_id, user, task, workflow_execution_id=workflow_execution_id
    )
    if prepared is None:
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
