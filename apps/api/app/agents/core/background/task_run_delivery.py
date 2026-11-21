"""Terminal delivery for a GAIA task's own background run.

The run executes in its task's chat, which result_delivery has already given the
executor's report. What reaches the user is decided here: comms decides whether it is
worth a message at all, and their chat app (or the app) gets it only if so. The run's
record is closed with what came of it either way. A step the task store fails is
finished by a durable job keyed by the run, never by running the task again.
"""

import asyncio
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app.agents.core.background.comms_narrator import (
    narrate_executor_result,
    record_executor_report,
)
from app.agents.core.background.session import ExecutorRun, TaskRun
from app.agents.core.background.workflow_platform_delivery import deliver_result_to_platforms
from app.agents.core.comms_directive import interpret_comms_output
from app.agents.prompts.comms_prompts import tracked_todo_delivery_note
from app.constants.comms import CommsDirectiveKind
from app.constants.log_tags import LogTag
from app.constants.tasks import (
    FINISH_TASK_RUN_JOB,
    FINISH_TASK_RUN_JOB_PREFIX,
    RECENT_RUNS_READ,
    RUN_SUMMARY_CHARS,
    TaskRunDeliveryOutcome,
    TaskRunStatus,
    WhenKind,
)
from app.constants.todos import (
    CANVAS_KEY_DETAILS_SECTION,
    CANVAS_STANDING_RULES_SECTION,
    DELIVERY_KEY_DETAILS_MAX_CHARS,
    STANDING_RULES_MAX_CHARS,
    TODO_RUN_FINISH_RETRY_DELAY,
)
from app.db.mongodb.retry import TRANSIENT_MONGO_RETRY
from app.db.repositories.task_runs import task_run_repository
from app.db.repositories.tasks import task_repository
from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.models.task_models import TaskDocument
from app.models.task_run_models import TaskRunUpdate
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import capture
from app.services.canvas_markdown import section_body
from app.services.delivery.chat_channel import (
    ProactiveTarget,
    proactive_destination,
    resolve_proactive_target,
)
from app.services.notification_service import notification_service
from app.services.tasks.todo_rounds import task_redirect_action
from app.utils.message_breaks import split_message_bubbles
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import TaskRunResultDelivered
from shared.py.wide_events import log

_NOT_SENT_NOTES: dict[TaskRunDeliveryOutcome, str] = {
    TaskRunDeliveryOutcome.UNDELIVERED: "result not sent: no linked chat app accepted it",
    TaskRunDeliveryOutcome.NOTIFY_OFF: "result not sent: delivery is off for this task",
    TaskRunDeliveryOutcome.NARRATION_FAILED: "result not sent: it could not be written up",
    TaskRunDeliveryOutcome.INVALID_DIRECTIVE: "result not sent: the write-up was a reaction",
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
    """A finished GAIA task run's result, as much as delivering it needs once the run is gone.

    It is the durable job's payload, so it carries ids rather than the live run.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    task_id: str
    user_id: str
    conversation_id: str
    trigger_type: str
    runs_once: bool
    result_text: str
    #: Set once the message step is done; only closing the run record is left then.
    delivery: str | None = None


async def deliver_task_run_result(
    run: ExecutorRun, task_run: TaskRun, result_text: str, result_type: str
) -> None:
    """Decide, deliver and record what a finished GAIA task run tells the user.

    An error result delivers nothing: the engine awaiting the run retries it and closes
    the record itself. What the task store leaves undone goes to a durable job.
    """
    log.set_ns("task_delivery", task_id=task_run.task_id, result_type=result_type)
    if result_type == "error":
        # Not narrated, but the chat shows it, so the chat's next turn must know it.
        await record_executor_report(run.conversation_id, result_text, result_type)
        return
    finished = FinishedTaskRun(
        run_id=task_run.run_id,
        task_id=task_run.task_id,
        user_id=run.user.user_id,
        conversation_id=run.conversation_id,
        trigger_type=task_run.trigger_type,
        runs_once=task_run.runs_once,
        result_text=result_text,
    )
    if (undone := await complete_delivery(finished, run.user)) is not None:
        await hand_unfinished_run_to_job(undone)


async def complete_delivery(
    finished: FinishedTaskRun, user: AuthenticatedUser
) -> FinishedTaskRun | None:
    """Send the run's message once, then close its record; return what is left undone.

    The message goes first because the record says what became of it. None when nothing
    is left, including for a run an earlier attempt already finished.
    """
    delivery = finished.delivery
    try:
        if delivery is None:
            if (delivery := await _send_once(finished, user)) is None:
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
            _defer_by=TODO_RUN_FINISH_RETRY_DELAY,
        )
    except RedisError as e:
        report_unfinished_run(undone, f"{type(e).__name__}: {e}")


async def _send_once(finished: FinishedTaskRun, user: AuthenticatedUser) -> str | None:
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

    # Read now, not when the run started: the run itself may have turned it off.
    if task.notify:
        resolution = await _narrate_and_send(finished, user, task)
    else:
        await record_executor_report(finished.conversation_id, finished.result_text, "result")
        resolution = _not_sent(TaskRunDeliveryOutcome.NOTIFY_OFF)
    log.set_ns("task_delivery", outcome=resolution.outcome.value)
    capture(
        UserId(task.user_id),
        TaskRunResultDelivered(
            task_id=task.id,
            outcome=resolution.outcome.value,
            delivered=resolution.outcome is TaskRunDeliveryOutcome.DELIVERED,
            platform=resolution.platform.value if resolution.platform else None,
            trigger_type=finished.trigger_type,
            repeats=task.when.kind is WhenKind.REPEAT,
            **proactive_destination(resolution.target),
        ),
    )
    return resolution.note


def _notes_section(task: TaskDocument, heading: str, max_chars: int) -> str | None:
    """Return one section of GAIA's notes, bounded, or None when it is missing or empty."""
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


async def _send_in_app(task: TaskDocument, text: str) -> _Resolution:
    """Deliver a result as an in-app notification: the fallback, or the target for an in-app user."""
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=task.user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                content=NotificationContent(
                    title=task.title,
                    body="\n\n".join(split_message_bubbles(text)),
                    actions=[task_redirect_action(task.id)],
                ),
                metadata={"task_id": task.id},
            )
        )
    except Exception as e:  # the record says it was not sent; nothing else depends on it
        log.error(
            f"{LogTag.AGENT} task run result could not be sent in the app",
            task_id=task.id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return _not_sent(TaskRunDeliveryOutcome.UNDELIVERED)
    return _Resolution(TaskRunDeliveryOutcome.DELIVERED, "result sent as an in-app notification")


async def _lookup_target(task: TaskDocument) -> ProactiveTarget | None:
    """Resolve where the result goes; None (logged) when the lookup fails, so it falls back in-app."""
    try:
        return await resolve_proactive_target(task.user_id)
    except Exception as e:  # falls back to in-app, said in the log
        log.error(
            f"{LogTag.AGENT} task run target lookup failed, falling back to in-app",
            task_id=task.id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


async def _narrate_and_send(
    finished: FinishedTaskRun, user: AuthenticatedUser, task: TaskDocument
) -> _Resolution:
    """Have comms write the result up (or decline to), then send it to the user.

    A report whose form its task's guidance sets is sent as written: comms decides only whether.
    """
    history = await _run_history(task)
    text, target = await asyncio.gather(
        narrate_executor_result(
            finished.result_text,
            "result",
            finished.conversation_id,
            user,
            preamble=tracked_todo_delivery_note(
                task.title,
                _notes_section(task, CANVAS_STANDING_RULES_SECTION, STANDING_RULES_MAX_CHARS),
                _notes_section(task, CANVAS_KEY_DETAILS_SECTION, DELIVERY_KEY_DETAILS_MAX_CHARS),
                runs_once=finished.runs_once,
                run_history=history,
            ),
        ),
        _lookup_target(task),
    )
    if not text:
        log.error(f"{LogTag.AGENT} task run result narration failed", task_id=task.id)
        return _not_sent(TaskRunDeliveryOutcome.NARRATION_FAILED)

    directive = interpret_comms_output(text)
    if directive.kind is CommsDirectiveKind.SILENCE:
        log.set_ns("task_delivery", silence_reason=directive.payload)
        return _Resolution(TaskRunDeliveryOutcome.SILENCED, f"kept quiet: {directive.payload}")
    if directive.kind is CommsDirectiveKind.REACT:
        # There is no user message to react to; a lone emoji would arrive as noise.
        log.error(
            f"{LogTag.AGENT} task run result narrated as a reaction; not sent",
            task_id=task.id,
            emoji=directive.payload,
        )
        return _not_sent(TaskRunDeliveryOutcome.INVALID_DIRECTIVE)

    # comms' retelling dropped the headings a report-form owner's guidance requires.
    owns_form = task.external_ref is not None and task.external_ref.source.owns_report_form
    message = finished.result_text if owns_form else directive.payload
    platform = (
        await deliver_result_to_platforms(
            user=user,
            user_id=task.user_id,
            notification_text=message,
            origin=f'GAIA task "{task.title}" (id {task.id})',
            target=target,
        )
        if target is not None
        else None
    )
    if platform is None:
        return (await _send_in_app(task, message))._replace(target=target)
    return _Resolution(
        TaskRunDeliveryOutcome.DELIVERED, f"result sent on {platform.value}", platform, target
    )
