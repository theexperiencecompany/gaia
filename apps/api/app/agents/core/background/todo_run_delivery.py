"""Terminal delivery for a tracked todo's own background run.

The run executes in its todo's chat, which run_cards has already given the executor's
report. What reaches the user is decided by the outbox: this module files the run's
report with it, and activity.md records that it did. A step the todo store or the queue
fails is finished by a durable job, keyed by the run, never by running the todo again.
"""

from pydantic import BaseModel, ConfigDict
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app.agents.core.background.comms_narrator import record_executor_report
from app.agents.core.background.run_report import RunOutcome, interrupting_policy
from app.agents.core.background.session import ExecutorRun, TodoRun
from app.constants.log_tags import LogTag
from app.constants.outbox import TODO_REPORT_PREFIX
from app.constants.todos import (
    CANVAS_KEY_DETAILS_SECTION,
    CANVAS_STANDING_RULES_SECTION,
    DELIVERY_KEY_DETAILS_MAX_CHARS,
    RUN_SUMMARY_ACTIVITY_CHARS,
    STANDING_RULES_MAX_CHARS,
    TODO_RUN_FINISH_JOB_PREFIX,
    TODO_RUN_FINISH_RETRY_DELAY,
    TODO_RUN_FINISH_TASK,
    TodoRunFinishFailure,
)
from app.db.mongodb.retry import TRANSIENT_MONGO_RETRY
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument
from app.models.workflow_models import TriggerType
from app.services.canvas_markdown import section_body
from app.services.outbox.intake import submit
from app.services.outbox.models import (
    Initiative,
    ProducerGuidance,
    ProducerKind,
    RunReport,
    Subject,
    SubjectKind,
)
from app.services.todo_activity import record_run_finished, run_finished_marker
from app.utils import clock
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


class FinishedTodoRun(BaseModel):
    """A finished tracked-todo run's outcome, as much as delivering it needs once the run is gone.

    It is the durable job's payload, so it carries ids rather than the live run.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    todo_id: str
    #: The run's user until the todo is read, then the todo's owner, whose log the entry joins.
    user_id: str
    conversation_id: str
    trigger_type: TriggerType
    outcome: RunOutcome
    runs_once: bool
    result_text: str
    #: Why the run interrupts the user's quiet hours, when its trigger's gate let it through them.
    interrupt_reason: str | None = None
    #: Set once the report is filed; only the finish entry is left then.
    finish_entry: str | None = None


async def deliver_todo_run_result(
    run: ExecutorRun,
    todo_run: TodoRun,
    outcome: RunOutcome,
    result_text: str,
    result_type: str,
) -> None:
    """File what a finished tracked-todo run reports, and record that it did.

    An error result files nothing: the worker that awaits the run retries it and
    records the failure itself, so the user hears of the attempt that ends it, never
    of one that is retried. What the todo store or the queue leaves undone goes to a
    durable job; the run stands, since running it again repeats its work.
    """
    log.set_ns("todo_delivery", todo_id=todo_run.todo_id, result_type=result_type)
    # The chat shows the run's report, so its next turn must know it whether or not anyone is told.
    await record_executor_report(run.conversation_id, result_text, result_type)
    if result_type == "error":
        return
    finished = FinishedTodoRun(
        run_id=run.stream_id,
        todo_id=todo_run.todo_id,
        user_id=run.user.user_id,
        conversation_id=run.conversation_id,
        trigger_type=todo_run.trigger_type,
        outcome=outcome,
        runs_once=todo_run.runs_once,
        result_text=result_text,
        interrupt_reason=todo_run.interrupt_reason,
    )
    if (undone := await finish_todo_run(finished)) is not None:
        await hand_unfinished_run_to_job(undone)


async def finish_todo_run(finished: FinishedTodoRun) -> FinishedTodoRun | None:
    """File the run's report once, then write its finish entry; return what is left undone.

    The report goes first because the entry records that it was filed. None
    when nothing is left, including for a run an earlier attempt already finished.
    """
    entry = finished.finish_entry
    try:
        if entry is None:
            if (filed := await _file_once(finished)) is None:
                return None
            entry, owner_id = filed
            finished = finished.model_copy(update={"finish_entry": entry, "user_id": owner_id})
        await record_run_finished(finished.todo_id, finished.user_id, finished.run_id, entry)
    except (PyMongoError, RedisError) as e:
        log.warning(
            f"{LogTag.AGENT} the todo store or the queue failed a finished run's delivery",
            todo_id=finished.todo_id,
            run_id=finished.run_id,
            undone=_undone(finished).value,
            error=str(e),
            error_type=type(e).__name__,
        )
        return finished
    return None


def report_unfinished_run(undone: FinishedTodoRun, cause: str) -> None:
    """Report, loudly, a finished run whose delivery nothing will retry any more."""
    failure = _undone(undone)
    log.error(
        f"{LogTag.AGENT} finished todo run given up on",
        failure=failure.value,
        todo_id=undone.todo_id,
        run_id=undone.run_id,
        cause=cause,
    )
    log.fail(failure)


def _undone(finished: FinishedTodoRun) -> TodoRunFinishFailure:
    if finished.finish_entry is None:
        return TodoRunFinishFailure.NOT_DELIVERED
    return TodoRunFinishFailure.NOT_RECORDED


async def hand_unfinished_run_to_job(undone: FinishedTodoRun) -> None:
    """Queue the durable job that finishes the run; loud when even that cannot be queued.

    Keyed by the run and what is undone, so each step of a run has one job at a time.
    """
    try:
        await enqueue_worker_job(
            await RedisPoolManager.get_pool(),
            TODO_RUN_FINISH_TASK,
            undone,
            _job_id=f"{TODO_RUN_FINISH_JOB_PREFIX}{undone.run_id}:{_undone(undone).value}",
            _defer_by=TODO_RUN_FINISH_RETRY_DELAY,
        )
    except RedisError as e:
        report_unfinished_run(undone, f"{type(e).__name__}: {e}")


async def _file_once(finished: FinishedTodoRun) -> tuple[str, str] | None:
    """File the run's report with the outbox; return its finish entry and the todo's owner.

    None when there is no entry to write: the todo is gone, or this run already finished.
    """
    async for attempt in TRANSIENT_MONGO_RETRY.copy():
        with attempt:
            todo = await todo_repository.get_by_id(finished.todo_id)
    if todo is None:
        log.warning(
            f"{LogTag.AGENT} todo run finished for a deleted todo", todo_id=finished.todo_id
        )
        return None
    if todo.activity_content and run_finished_marker(finished.run_id) in todo.activity_content:
        return None

    report = _todo_report(finished, todo)
    await submit(report)
    outcome = finished.outcome.report.outcome
    summary = finished.result_text.strip().replace("\n", " ")[:RUN_SUMMARY_ACTIVITY_CHARS]
    log.set_ns("todo_delivery", outcome=outcome.value if outcome else None)
    return f"reported to the outbox: {outcome.value if outcome else None} (summary={summary!r})", (
        todo.user_id
    )


def _canvas_section(todo: TodoDocument, heading: str, max_chars: int) -> str | None:
    """Return one canvas section's body, bounded, or None when it is missing or empty."""
    body = section_body(todo.canvas_content, heading)
    return body[:max_chars] if body else None


def _todo_report(finished: FinishedTodoRun, todo: TodoDocument) -> RunReport:
    """Return the todo run's report: the notify flag, rules and form as the todo says now, and whether it runs once as it did when the run started.

    Completing a todo tears its watches down, so reading that at delivery would call a thread todo that resolved itself a one-time answer.
    """
    owns_form = todo.external_ref is not None and todo.external_ref.source.owns_report_form
    return RunReport(
        report_id=f"{TODO_REPORT_PREFIX}{finished.todo_id}:{finished.run_id}",
        recipient=todo.user_id,
        producer=ProducerKind.TODO,
        subject=Subject(
            kind=SubjectKind.TODO_RUN,
            id=f"{finished.todo_id}:{finished.run_id}",
            owner_conversation_id=finished.conversation_id,
            series=f"{TODO_REPORT_PREFIX}{finished.todo_id}",
            label=todo.title,
        ),
        occurred_at=clock.now(),
        initiative=Initiative.ASKED if finished.runs_once else Initiative.SELF_INITIATED,
        delivery_policy=interrupting_policy(
            notify=todo.notify_on_run, reason=finished.interrupt_reason
        ),
        report=finished.outcome.report,
        result=finished.outcome.result,
        review_problem=finished.outcome.review_problem,
        interrupt_reason=finished.interrupt_reason,
        decided_approvals=finished.outcome.decided_approvals,
        guidance=ProducerGuidance(
            title=todo.title,
            standing_rules=_canvas_section(
                todo, CANVAS_STANDING_RULES_SECTION, STANDING_RULES_MAX_CHARS
            ),
            key_details=_canvas_section(
                todo, CANVAS_KEY_DETAILS_SECTION, DELIVERY_KEY_DETAILS_MAX_CHARS
            ),
            runs_once=finished.runs_once,
            verbatim=owns_form,
        ),
    )
