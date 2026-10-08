"""Terminal delivery for a tracked todo's own background run.

The run's conversation is a throwaway with no transport, so its result is never
saved there: comms decides whether it is worth a message at all, the user's chat
app gets it only if so, and activity.md records what happened either way. A step
the todo store fails is finished by a durable job, keyed by the run, never by
running the todo again.
"""

from typing import NamedTuple

from pydantic import BaseModel, ConfigDict
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app.agents.core.background.comms_narrator import narrate_executor_result
from app.agents.core.background.session import ExecutorRun, TodoRun
from app.agents.core.background.workflow_platform_delivery import deliver_result_to_platforms
from app.agents.core.comms_directive import interpret_comms_output
from app.agents.prompts.comms_prompts import tracked_todo_delivery_note
from app.constants.comms import CommsDirectiveKind
from app.constants.log_tags import LogTag
from app.constants.todos import (
    DELIVERY_KEY_DETAILS_MAX_CHARS,
    RUN_SUMMARY_ACTIVITY_CHARS,
    TODO_RUN_FINISH_JOB_PREFIX,
    TODO_RUN_FINISH_RETRY_DELAY,
    TODO_RUN_FINISH_TASK,
    TodoRunDeliveryOutcome,
    TodoRunFinishFailure,
)
from app.db.mongodb.retry import TRANSIENT_MONGO_RETRY
from app.db.repositories.todos import todo_repository
from app.models.chat_models import ConversationSource
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services.analytics_service import capture
from app.services.canvas_markdown import section_body
from app.services.todo_activity import record_run_finished, run_finished_marker
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.todos import TodosRunResultDelivered
from shared.py.wide_events import log

_NOT_SENT_NOTES: dict[TodoRunDeliveryOutcome, str] = {
    TodoRunDeliveryOutcome.UNDELIVERED: "result not sent: no linked chat app accepted it",
    TodoRunDeliveryOutcome.NOTIFY_OFF: "result not sent: delivery is off for this todo",
    TodoRunDeliveryOutcome.NARRATION_FAILED: "result not sent: it could not be written up",
    TodoRunDeliveryOutcome.INVALID_DIRECTIVE: "result not sent: the write-up was a reaction",
}


class _Resolution(NamedTuple):
    """What became of one run's result: the outcome, its activity note, and the platform."""

    outcome: TodoRunDeliveryOutcome
    note: str
    platform: ConversationSource | None = None


def _not_sent(outcome: TodoRunDeliveryOutcome) -> _Resolution:
    return _Resolution(outcome, _NOT_SENT_NOTES[outcome])


class FinishedTodoRun(BaseModel):
    """A finished tracked-todo run's result, as much as delivering it needs once the run is gone.

    It is the durable job's payload, so it carries ids rather than the live run.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    todo_id: str
    #: The run's user until the todo is read, then the todo's owner, whose log the entry joins.
    user_id: str
    conversation_id: str
    trigger_type: TriggerType
    result_text: str
    #: Set once the message step is done; only the finish entry is left then.
    finish_entry: str | None = None


async def deliver_todo_run_result(
    run: ExecutorRun, todo_run: TodoRun, result_text: str, result_type: str
) -> None:
    """Decide, deliver and record what a finished tracked-todo run tells the user.

    An error result delivers nothing: the worker that awaits the run retries it
    and records the failure itself. What the todo store leaves undone goes to a
    durable job; the run stands, since running it again repeats its work.
    """
    log.set_ns("todo_delivery", todo_id=todo_run.todo_id, result_type=result_type)
    if result_type == "error":
        return
    finished = FinishedTodoRun(
        run_id=run.stream_id,
        todo_id=todo_run.todo_id,
        user_id=run.user.user_id,
        conversation_id=run.conversation_id,
        trigger_type=todo_run.trigger_type,
        result_text=result_text,
    )
    if (undone := await finish_todo_run(finished, run.user)) is not None:
        await hand_unfinished_run_to_job(undone)


async def finish_todo_run(
    finished: FinishedTodoRun, user: AuthenticatedUser
) -> FinishedTodoRun | None:
    """Send the run's message once, then write its finish entry; return what is left undone.

    The message goes first because the entry records what became of it. None
    when nothing is left, including for a run an earlier attempt already finished.
    """
    entry = finished.finish_entry
    try:
        if entry is None:
            if (sent := await _send_once(finished, user)) is None:
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


async def _send_once(finished: FinishedTodoRun, user: AuthenticatedUser) -> tuple[str, str] | None:
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

    # Read now, not when the run started: the run itself may have turned it off.
    resolution = (
        await _narrate_and_send(finished, user, todo)
        if todo.notify_on_run
        else _not_sent(TodoRunDeliveryOutcome.NOTIFY_OFF)
    )
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
        ),
    )
    summary = finished.result_text.strip().replace("\n", " ")[:RUN_SUMMARY_ACTIVITY_CHARS]
    return f"{resolution.note} (summary={summary!r})", todo.user_id


def _standing_requests(todo: TodoDocument) -> str | None:
    """Return the todo's Key Details, bounded, or None when it has none."""
    canvas = todo.canvas_content
    key_details = section_body(canvas, "Key Details") if canvas else None
    return key_details[:DELIVERY_KEY_DETAILS_MAX_CHARS] if key_details else None


async def _narrate_and_send(
    finished: FinishedTodoRun, user: AuthenticatedUser, todo: TodoDocument
) -> _Resolution:
    """Have comms write the result up (or decline to), then send it to the chat app."""
    text = await narrate_executor_result(
        finished.result_text,
        "result",
        finished.conversation_id,
        user,
        preamble=tracked_todo_delivery_note(todo.title, _standing_requests(todo)),
    )
    if not text:
        log.error(f"{LogTag.AGENT} todo run result narration failed", todo_id=todo.id)
        return _not_sent(TodoRunDeliveryOutcome.NARRATION_FAILED)

    directive = interpret_comms_output(text)
    if directive.kind is CommsDirectiveKind.SILENCE:
        log.set_ns("todo_delivery", silence_reason=directive.payload)
        return _Resolution(TodoRunDeliveryOutcome.SILENCED, f"kept quiet: {directive.payload}")
    if directive.kind is CommsDirectiveKind.REACT:
        # There is no user message to react to; a lone emoji would arrive as noise.
        log.error(
            f"{LogTag.AGENT} todo run result narrated as a reaction; not sent",
            todo_id=todo.id,
            emoji=directive.payload,
        )
        return _not_sent(TodoRunDeliveryOutcome.INVALID_DIRECTIVE)

    platform = await deliver_result_to_platforms(
        user=user,
        user_id=todo.user_id,
        notification_text=directive.payload,
        origin=f'tracked todo "{todo.title}" (id {todo.id})',
    )
    if platform is None:
        return _not_sent(TodoRunDeliveryOutcome.UNDELIVERED)
    return _Resolution(
        TodoRunDeliveryOutcome.DELIVERED, f"result sent on {platform.value}", platform
    )
