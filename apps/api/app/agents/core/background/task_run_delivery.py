"""Terminal delivery for a GAIA task's own background run.

The run's work is logged in its task's chat, and the reply the conversation step
writes for that work is its write-up, guided by write_up_note. What reaches the
user is decided here from that reply: a silent or failed one sends nothing, a
report its task's guidance forms goes as written, and any other goes as the reply
wrote it. The run's record is closed with what came of it either way. A step the
task store fails is finished by a durable job keyed by the run, never by running
the task again.
"""

from typing import NamedTuple

from pydantic import BaseModel, ConfigDict
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app.agents.prompts.comms_prompts import task_delivery_note
from app.constants.log_tags import LogTag
from app.constants.task_notes import (
    CANVAS_KEY_DETAILS_SECTION,
    CANVAS_STANDING_RULES_SECTION,
    DELIVERY_KEY_DETAILS_MAX_CHARS,
    STANDING_RULES_MAX_CHARS,
)
from app.constants.tasks import (
    FINISH_TASK_RUN_JOB,
    FINISH_TASK_RUN_JOB_PREFIX,
    FINISH_TASK_RUN_RETRY_DELAY,
    RECENT_RUNS_READ,
    RUN_SUMMARY_CHARS,
    TaskRunDeliveryOutcome,
    TaskRunStatus,
    TaskRunTrigger,
    WhenKind,
)
from app.db.mongodb.retry import TRANSIENT_MONGO_RETRY
from app.db.repositories.task_runs import task_run_repository
from app.db.repositories.tasks import task_repository
from app.models.chat_models import ConversationSource
from app.models.conversation_log_models import TaskRun, TodoReportForm
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    notification_id,
)
from app.models.task_models import TaskDocument
from app.models.task_run_models import TaskRunUpdate
from app.services.analytics_service import capture
from app.services.canvas_markdown import section_body
from app.services.delivery.chat_channel import ProactiveTarget, proactive_destination
from app.services.notification_service import notification_service
from app.services.tasks.todo_rounds import task_redirect_action
from app.utils.message_breaks import split_message_bubbles
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import TaskRunResultDelivered
from shared.py.conversation_wire import ReplyOutcome
from shared.py.wide_events import log

_NOT_SENT_NOTES: dict[TaskRunDeliveryOutcome, str] = {
    TaskRunDeliveryOutcome.UNDELIVERED: "result not sent: no linked chat app accepted it",
    TaskRunDeliveryOutcome.NOTIFY_OFF: "result not sent: delivery is off for this task",
    TaskRunDeliveryOutcome.NOTHING_TO_REPORT: "result not sent: the run found nothing for the user",
    TaskRunDeliveryOutcome.NARRATION_FAILED: "result not sent: it could not be written up",
    TaskRunDeliveryOutcome.SILENCED: "kept quiet: the write-up found it not worth a message",
}


class _Resolution(NamedTuple):
    """What became of one run's result: outcome, delivery note, platform, and the target it was routed by."""

    outcome: TaskRunDeliveryOutcome
    note: str
    platform: ConversationSource | None = None
    target: ProactiveTarget | None = None


def _not_sent(outcome: TaskRunDeliveryOutcome) -> _Resolution:
    return _Resolution(outcome, _NOT_SENT_NOTES[outcome])


class FinishedTaskRun(BaseModel):
    """A finished GAIA task run's report and write-up, as much as delivering them needs.

    It is the durable job's payload, so it carries what the run's reply settled to, not the reply.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    task_id: str
    user_id: str
    conversation_id: str
    trigger_type: TaskRunTrigger
    report_form: TodoReportForm
    #: The run's own report: what an as-written task sends, and the record's summary.
    result_text: str
    #: The reply that reported the run, and how it settled.
    write_up: str
    reply: ReplyOutcome
    #: The run's own finish_task declaration: result_text is its record, not a message.
    nothing_for_user: bool = False
    #: Set once the message step is done; only closing the run record is left then.
    delivery: str | None = None


def report_form_of(task: TaskDocument) -> TodoReportForm:
    """Return the report a run of the task owes: as written when its kind's guidance forms it, else a write-up."""
    owns_form = task.external_ref is not None and task.external_ref.source.owns_report_form
    return TodoReportForm.AS_WRITTEN if owns_form else TodoReportForm.WRITE_UP


async def write_up_note(run: TaskRun) -> str:
    """Return how the reply that reports a run of the task writes it up: when to send, and in what form.

    Read when the reply is written, so the task's rules and its runs so far are current.
    """
    async for attempt in TRANSIENT_MONGO_RETRY.copy():
        with attempt:
            task = await task_repository.get_any(run.task_id)
    return task_delivery_note(
        run.title,
        _notes_section(task, CANVAS_STANDING_RULES_SECTION, STANDING_RULES_MAX_CHARS),
        _notes_section(task, CANVAS_KEY_DETAILS_SECTION, DELIVERY_KEY_DETAILS_MAX_CHARS),
        runs_once=run.runs_once,
        run_history=await _run_history(task) if task else [],
    )


async def deliver_task_run(finished: FinishedTaskRun) -> FinishedTaskRun | None:
    """Send the run's message once, then close its record; return what is left undone.

    The message goes first because the record says what became of it. None when nothing
    is left, including for a run an earlier attempt already finished.
    """
    log.set_ns("task_delivery", task_id=finished.task_id, reply=finished.reply.value)
    delivery = finished.delivery
    try:
        if delivery is None:
            if (delivery := await _send_once(finished)) is None:
                return None
            finished = finished.model_copy(update={"delivery": delivery})
        await task_run_repository.complete(
            finished.run_id,
            TaskRunUpdate(
                status=TaskRunStatus.SUCCESS,
                summary=finished.result_text.strip()[:RUN_SUMMARY_CHARS],
                delivery=delivery,
            ),
        )
    except PyMongoError as e:
        log.warning(
            f"{LogTag.AGENT} the task store failed a finished run's delivery",
            task_id=finished.task_id,
            run_id=finished.run_id,
            delivered=finished.delivery is not None,
            error=str(e),
            error_type=type(e).__name__,
        )
        return finished
    return None


def report_unfinished_run(undone: FinishedTaskRun, cause: str) -> None:
    """Report, loudly, a finished run whose delivery nothing will retry any more."""
    log.error(
        f"{LogTag.AGENT} finished task run given up on",
        delivered=undone.delivery is not None,
        task_id=undone.task_id,
        run_id=undone.run_id,
        cause=cause,
    )
    log.fail("task_run_result_not_recorded" if undone.delivery else "task_run_result_not_delivered")


async def hand_unfinished_run_to_job(undone: FinishedTaskRun) -> None:
    """Queue the durable job that finishes the run; loud when even that cannot be queued."""
    step = "record" if undone.delivery else "deliver"
    try:
        await enqueue_worker_job(
            await RedisPoolManager.get_pool(),
            FINISH_TASK_RUN_JOB,
            undone,
            _job_id=f"{FINISH_TASK_RUN_JOB_PREFIX}{undone.run_id}:{step}",
            _defer_by=FINISH_TASK_RUN_RETRY_DELAY,
        )
    except RedisError as e:
        report_unfinished_run(undone, f"{type(e).__name__}: {e}")


async def _send_once(finished: FinishedTaskRun) -> str | None:
    """Decide on and send the run's message; return the note its record keeps.

    None when there is nothing to record: the task is gone, or this run already finished.
    """
    async for attempt in TRANSIENT_MONGO_RETRY.copy():
        with attempt:
            task = await task_repository.get_any(finished.task_id)
            record = await task_run_repository.get(finished.run_id)
    if task is None:
        log.warning(
            f"{LogTag.AGENT} task run finished for a deleted task", task_id=finished.task_id
        )
        return None
    if record is None or record.status is not TaskRunStatus.RUNNING:
        return None

    held_back = _held_back(finished, task)
    resolution = await _send(finished, task) if held_back is None else _not_sent(held_back)
    log.set_ns("task_delivery", outcome=resolution.outcome.value)
    capture(
        UserId(task.user_id),
        TaskRunResultDelivered(
            task_id=task.id,
            outcome=resolution.outcome.value,
            delivered=resolution.outcome is TaskRunDeliveryOutcome.DELIVERED,
            platform=resolution.platform.value if resolution.platform else None,
            trigger_type=finished.trigger_type.value,
            repeats=task.when.kind is WhenKind.REPEAT,
            **proactive_destination(resolution.target),
        ),
    )
    return resolution.note


def _held_back(finished: FinishedTaskRun, task: TaskDocument) -> TaskRunDeliveryOutcome | None:
    """Name why a run's result goes nowhere, or None when it is sent."""
    # Read now, not when the run started: the run itself may have turned it off.
    if not task.notify:
        return TaskRunDeliveryOutcome.NOTIFY_OFF
    # Only a kind whose run guidance defines the declaration may silence itself with it.
    if finished.nothing_for_user and finished.report_form is TodoReportForm.AS_WRITTEN:
        return TaskRunDeliveryOutcome.NOTHING_TO_REPORT
    if finished.reply is ReplyOutcome.FAILED:
        return TaskRunDeliveryOutcome.NARRATION_FAILED
    if finished.reply is not ReplyOutcome.ANSWERED:
        return TaskRunDeliveryOutcome.SILENCED
    return None


def _notes_section(task: TaskDocument | None, heading: str, max_chars: int) -> str | None:
    """Return one section of GAIA's notes, bounded, or None when it, or the task, is missing or empty."""
    if task is None:
        return None
    body = section_body(task.notes, heading)
    return body[:max_chars] if body else None


async def _run_history(task: TaskDocument) -> list[str]:
    """List the last runs' outcomes, oldest first, one line each."""
    runs = await task_run_repository.latest_finished(task.id, task.user_id, limit=RECENT_RUNS_READ)
    return [
        f"- {run.started_at.isoformat()} [{run.status.value if run.status else 'history'}] "
        f"{run.summary or run.error_message or ''}".rstrip()
        for run in reversed(runs)
    ]


async def _send(finished: FinishedTaskRun, task: TaskDocument) -> _Resolution:
    """Send the write-up, or the report itself when the task's guidance forms it, through the one notify pipeline.

    Keyed by the run, so the durable job that retries a finish sends nothing twice.
    """
    # A retelling drops the headings an as-written task's guidance requires.
    as_written = finished.report_form is TodoReportForm.AS_WRITTEN
    message = finished.result_text if as_written else finished.write_up
    notified = await notification_service.notify(
        NotificationRequest(
            id=notification_id(task.user_id, "task_run", finished.run_id),
            user_id=task.user_id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            content=NotificationContent(
                title=task.title,
                body="\n\n".join(split_message_bubbles(message)),
                actions=[task_redirect_action(task.id)],
            ),
            metadata={"task_id": task.id},
            message=message,
        )
    )
    if notified.record.status is not NotificationStatus.DELIVERED:
        return _not_sent(TaskRunDeliveryOutcome.UNDELIVERED)._replace(target=notified.target)
    platform = notified.chat_app
    note = (
        f"result sent on {platform.value}" if platform else "result sent as an in-app notification"
    )
    return _Resolution(TaskRunDeliveryOutcome.DELIVERED, note, platform, notified.target)
