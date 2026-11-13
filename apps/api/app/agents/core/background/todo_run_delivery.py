"""Terminal delivery for a tracked todo's own background run.

The run's work is logged in its todo's chat, and the reply the conversation step
writes for that work is its write-up, guided by write_up_note. What reaches the
user's chat app is decided here from that reply: a silent or failed one sends
nothing, a report its todo's guidance forms goes as written, and any other goes as
the reply wrote it. activity.md records what happened either way. A step the todo
store fails is finished by a durable job, keyed by the run, never by running the
todo again.
"""

from typing import NamedTuple

from pydantic import BaseModel, ConfigDict
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app.agents.prompts.comms_prompts import tracked_todo_delivery_note
from app.constants.log_tags import LogTag
from app.constants.todos import (
    CANVAS_KEY_DETAILS_SECTION,
    CANVAS_STANDING_RULES_SECTION,
    DELIVERY_KEY_DETAILS_MAX_CHARS,
    DELIVERY_RUN_HISTORY_LINES,
    RUN_SUMMARY_ACTIVITY_CHARS,
    STANDING_RULES_MAX_CHARS,
    TODO_RUN_FINISH_JOB_PREFIX,
    TODO_RUN_FINISH_RETRY_DELAY,
    TODO_RUN_FINISH_TASK,
    TodoRunDeliveryOutcome,
    TodoRunFinishFailure,
)
from app.db.mongodb.retry import TRANSIENT_MONGO_RETRY
from app.db.repositories.todos import todo_repository
from app.models.chat_models import ConversationSource
from app.models.conversation_log_models import ReplyOutcome, TodoReportForm, TodoRun
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    notification_id,
)
from app.models.todo_models import TodoDocument
from app.models.workflow_models import TriggerType
from app.services.analytics_service import capture
from app.services.canvas_markdown import section_body
from app.services.delivery.chat_channel import ProactiveTarget, proactive_destination
from app.services.notification_service import notification_service
from app.services.todo_activity import (
    recent_run_outcomes,
    record_run_finished,
    run_finished_marker,
)
from app.utils.message_breaks import split_message_bubbles
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.todos import TodosRunResultDelivered
from shared.py.wide_events import log

_NOT_SENT_NOTES: dict[TodoRunDeliveryOutcome, str] = {
    TodoRunDeliveryOutcome.UNDELIVERED: "result not sent: no linked chat app accepted it",
    TodoRunDeliveryOutcome.NOTIFY_OFF: "result not sent: delivery is off for this todo",
    TodoRunDeliveryOutcome.NOTHING_TO_REPORT: "result not sent: the run found nothing for the user",
    TodoRunDeliveryOutcome.NARRATION_FAILED: "result not sent: it could not be written up",
    TodoRunDeliveryOutcome.SILENCED: "kept quiet: the write-up found it not worth a message",
}


class _Resolution(NamedTuple):
    """What became of one run's result: outcome, activity note, platform, and the target a sent result was routed by."""

    outcome: TodoRunDeliveryOutcome
    note: str
    platform: ConversationSource | None = None
    target: ProactiveTarget | None = None


def _not_sent(outcome: TodoRunDeliveryOutcome) -> _Resolution:
    return _Resolution(outcome, _NOT_SENT_NOTES[outcome])


class FinishedTodoRun(BaseModel):
    """A finished tracked-todo run's report and write-up, as much as delivering them needs.

    It is the durable job's payload, so it carries what the run's reply settled to, not the reply.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    todo_id: str
    #: The run's user until the todo is read, then the todo's owner, whose log the entry joins.
    user_id: str
    conversation_id: str
    trigger_type: TriggerType
    report_form: TodoReportForm
    #: The run's own report: what an as-written todo sends, and the activity summary.
    result_text: str
    #: The reply that reported the run, and how it settled.
    write_up: str
    reply: ReplyOutcome
    #: The run's own finish_task declaration: result_text is its record, not a message.
    nothing_for_user: bool = False
    #: Set once the message step is done; only the finish entry is left then.
    finish_entry: str | None = None


def report_form_of(todo: TodoDocument) -> TodoReportForm:
    """Return the report a run of the todo owes: as written when its kind's guidance forms it, else a write-up."""
    return TodoReportForm.AS_WRITTEN if todo.owns_report_form else TodoReportForm.WRITE_UP


async def write_up_note(run: TodoRun) -> str:
    """Return how the reply that reports a run of the todo writes it up: when to send, and in what form.

    Read when the reply is written, so the todo's rules and its runs so far are current.
    """
    async for attempt in TRANSIENT_MONGO_RETRY.copy():
        with attempt:
            todo = await todo_repository.get_by_id(run.todo_id)
    return tracked_todo_delivery_note(
        run.title,
        _canvas_section(todo, CANVAS_STANDING_RULES_SECTION, STANDING_RULES_MAX_CHARS),
        _canvas_section(todo, CANVAS_KEY_DETAILS_SECTION, DELIVERY_KEY_DETAILS_MAX_CHARS),
        runs_once=run.runs_once,
        run_history=recent_run_outcomes(
            todo.activity_content if todo else None, DELIVERY_RUN_HISTORY_LINES
        ),
    )


async def finish_todo_run(finished: FinishedTodoRun) -> FinishedTodoRun | None:
    """Send the run's message once, then write its finish entry; return what is left undone.

    The message goes first because the entry records what became of it. None
    when nothing is left, including for a run an earlier attempt already finished.
    """
    log.set_ns("todo_delivery", todo_id=finished.todo_id, reply=finished.reply.value)
    entry = finished.finish_entry
    try:
        if entry is None:
            if (sent := await _send_once(finished)) is None:
                return None
            entry, owner_id = sent
            finished = finished.model_copy(update={"finish_entry": entry, "user_id": owner_id})
        await record_run_finished(finished.todo_id, finished.user_id, finished.run_id, entry)
    except PyMongoError as e:
        log.warning(
            f"{LogTag.AGENT} the todo store failed a finished run's delivery",
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


async def _send_once(finished: FinishedTodoRun) -> tuple[str, str] | None:
    """Decide on and send the run's message; return its finish entry and the todo's owner.

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

    held_back = _held_back(finished, todo)
    resolution = await _send(finished, todo) if held_back is None else _not_sent(held_back)
    log.set_ns("todo_delivery", outcome=resolution.outcome.value)
    # A worker has no request context: the explicit user id keeps the event off
    # an anonymous profile.
    capture(
        UserId(todo.user_id),
        TodosRunResultDelivered(
            outcome=resolution.outcome.value,
            delivered=resolution.outcome is TodoRunDeliveryOutcome.DELIVERED,
            platform=resolution.platform.value if resolution.platform else None,
            trigger_type=finished.trigger_type.value,
            recurring=bool(todo.recurrence),
            **proactive_destination(resolution.target),
        ),
    )
    summary = finished.result_text.strip().replace("\n", " ")[:RUN_SUMMARY_ACTIVITY_CHARS]
    return f"{resolution.note} (summary={summary!r})", todo.user_id


def _held_back(finished: FinishedTodoRun, todo: TodoDocument) -> TodoRunDeliveryOutcome | None:
    """Name why a run's result goes nowhere, or None when it is sent."""
    # Read now, not when the run started: the run itself may have turned it off.
    if not todo.notify_on_run:
        return TodoRunDeliveryOutcome.NOTIFY_OFF
    # Only a kind whose run guidance defines the declaration may silence itself with it.
    if finished.nothing_for_user and finished.report_form is TodoReportForm.AS_WRITTEN:
        return TodoRunDeliveryOutcome.NOTHING_TO_REPORT
    if finished.reply is ReplyOutcome.FAILED:
        return TodoRunDeliveryOutcome.NARRATION_FAILED
    if finished.reply is not ReplyOutcome.ANSWERED:
        return TodoRunDeliveryOutcome.SILENCED
    return None


def _canvas_section(todo: TodoDocument | None, heading: str, max_chars: int) -> str | None:
    """Return one canvas section's body, bounded, or None when it, or the todo, is missing or empty."""
    if todo is None:
        return None
    body = section_body(todo.canvas_content, heading)
    return body[:max_chars] if body else None


async def _send(finished: FinishedTodoRun, todo: TodoDocument) -> _Resolution:
    """Send the write-up, or the report itself when the todo's guidance forms it, through the one notify pipeline.

    Keyed by the run, so the durable job that retries a finish sends nothing twice.
    """
    # A retelling drops the headings an as-written todo's guidance requires.
    as_written = finished.report_form is TodoReportForm.AS_WRITTEN
    message = finished.result_text if as_written else finished.write_up
    notified = await notification_service.notify(
        NotificationRequest(
            id=notification_id(todo.user_id, "todo_run", finished.run_id),
            user_id=todo.user_id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            content=NotificationContent(
                title=todo.title, body="\n\n".join(split_message_bubbles(message))
            ),
            metadata={"todo_id": todo.id},
            message=message,
        )
    )
    if notified.record.status is not NotificationStatus.DELIVERED:
        return _not_sent(TodoRunDeliveryOutcome.UNDELIVERED)._replace(target=notified.target)
    platform = notified.chat_app
    note = (
        f"result sent on {platform.value}" if platform else "result sent as an in-app notification"
    )
    return _Resolution(TodoRunDeliveryOutcome.DELIVERED, note, platform, notified.target)
