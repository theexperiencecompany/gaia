"""Terminal delivery for a tracked todo's own background run.

The run executes in its todo's chat, which result_delivery has already given the
executor's report. What reaches the user is decided here, by one rule: what can
wait until tomorrow morning goes into the next brief, the rest is sent now. Code
decides what may wait at all; comms decides whether a result is worth anything,
and for one that may wait, whether it can. activity.md records what happened either way. A step the todo store fails is
finished by a durable job, keyed by the run, never by running the todo again.
"""

import asyncio
from collections.abc import Iterable
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app.agents.core.background.comms_narrator import (
    narrate_executor_result,
    record_executor_report,
)
from app.agents.core.background.session import ExecutorRun, TodoRun
from app.agents.core.background.workflow_platform_delivery import deliver_result_to_platforms
from app.agents.core.comms_directive import interpret_comms_output
from app.agents.prompts.comms_prompts import tracked_todo_delivery_note
from app.constants.briefing import DAILY_BRIEFING_WORKFLOW_KEY, BriefItemSource
from app.constants.comms import CommsDirectiveKind
from app.constants.log_tags import LogTag
from app.constants.notifications import QUIET_HOURS_EXEMPT, ProactiveMessageClass
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
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_models import PendingBriefItemDocument
from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.models.todo_models import ExternalRefSource, TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services.analytics_service import capture
from app.services.canvas_markdown import section_body
from app.services.delivery.chat_channel import (
    ProactiveTarget,
    proactive_destination,
    resolve_proactive_target,
)
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
    TodoRunDeliveryOutcome.NARRATION_FAILED: "result not sent: it could not be written up",
    TodoRunDeliveryOutcome.INVALID_DIRECTIVE: "result not sent: the write-up was a reaction",
    TodoRunDeliveryOutcome.HELD_FOR_BRIEF: "result held for the next brief",
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
    #: Defaulted for a job queued before the class was carried.
    message_class: ProactiveMessageClass = ProactiveMessageClass.ROUTINE
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
        # Not narrated, but the chat shows it, so the chat's next turn must know it.
        await record_executor_report(run.conversation_id, result_text, result_type)
        return
    finished = FinishedTodoRun(
        run_id=run.stream_id,
        todo_id=todo_run.todo_id,
        user_id=run.user.user_id,
        conversation_id=run.conversation_id,
        trigger_type=todo_run.trigger_type,
        result_text=result_text,
        message_class=todo_run.message_class,
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
    if todo.notify_on_run:
        resolution = await _narrate_and_deliver(finished, user, todo)
    else:
        await record_executor_report(finished.conversation_id, finished.result_text, "result")
        resolution = _not_sent(TodoRunDeliveryOutcome.NOTIFY_OFF)
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


def _is_desk_sweep(todo: TodoDocument, finished: FinishedTodoRun) -> bool:
    """Return whether this is the inbox desk's scheduled sweep, whose findings feed the brief."""
    return (
        todo.external_ref is not None
        and todo.external_ref.source is ExternalRefSource.INBOX_DESK
        and finished.trigger_type is TriggerType.SCHEDULED_TODO
    )


def _can_wait(todo: TodoDocument, finished: FinishedTodoRun, *, runs_once: bool) -> bool:
    """Whether code lets this result wait for the brief; comms still decides if it can.

    Never a one-time todo's answer, a watch the user set, a reminder they timed, a reply
    to what they just did, or a run the trigger gate let through as urgent. A thread
    the inbox desk opened alerts only when the user cannot wait, so comms judges it.
    """
    if runs_once or finished.message_class in QUIET_HOURS_EXEMPT:
        return False
    desk_thread = (
        todo.external_ref is not None and todo.external_ref.source is ExternalRefSource.GMAIL_THREAD
    )
    return desk_thread or finished.trigger_type is TriggerType.SCHEDULED_TODO


async def _has_live_daily_brief(user_id: str) -> bool:
    """Whether a daily brief will run for the user: its workflow exists and is switched on.

    Without one, holding a result for "the brief" would mean nobody ever sees it.
    """
    workflow = await workflow_repository.find_system_workflow(user_id, DAILY_BRIEFING_WORKFLOW_KEY)
    return workflow is not None and workflow.activated


def _canvas_section(todo: TodoDocument, heading: str, max_chars: int) -> str | None:
    """Return one canvas section's body, bounded, or None when it is missing or empty."""
    body = section_body(todo.canvas_content, heading)
    return body[:max_chars] if body else None


async def _send_in_app(todo: TodoDocument, text: str) -> _Resolution:
    """Deliver a result as an in-app notification: the fallback, or the target for an in-app user."""
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=todo.user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                content=NotificationContent(
                    title=todo.title, body="\n\n".join(split_message_bubbles(text))
                ),
                metadata={"todo_id": todo.id},
            )
        )
    except Exception as e:
        log.error(
            f"{LogTag.AGENT} todo run result could not be sent in the app",
            todo_id=todo.id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return _not_sent(TodoRunDeliveryOutcome.UNDELIVERED)
    return _Resolution(TodoRunDeliveryOutcome.DELIVERED, "result sent as an in-app notification")


async def _lookup_target(todo: TodoDocument) -> ProactiveTarget | None:
    """Resolve where the result goes; None (logged) when the lookup fails, so it falls back in-app."""
    try:
        return await resolve_proactive_target(todo.user_id)
    except Exception as e:
        log.error(
            f"{LogTag.AGENT} todo run target lookup failed, falling back to in-app",
            todo_id=todo.id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


async def _hold_for_brief(
    finished: FinishedTodoRun, todo: TodoDocument, lines: Iterable[str]
) -> _Resolution:
    """Hold each line as one item of the user's next brief.

    A retry that writes a line twice is harmless: the brief carries one item per text.
    """
    for line in lines:
        if text := line.strip().removeprefix("- ").strip():
            await pending_brief_items_repository.create(
                PendingBriefItemDocument(
                    user_id=todo.user_id,
                    source=BriefItemSource.TODO,
                    source_id=todo.id,
                    source_title=todo.title,
                    conversation_id=finished.conversation_id,
                    text=text,
                )
            )
    return _not_sent(TodoRunDeliveryOutcome.HELD_FOR_BRIEF)


async def _narrate_and_deliver(
    finished: FinishedTodoRun, user: AuthenticatedUser, todo: TodoDocument
) -> _Resolution:
    """Have comms write the result up (or decline to), then send it or hold it for the brief.

    A report whose form its todo's guidance sets is delivered as written: comms decides
    only whether. The inbox desk's scheduled findings go into the next brief, never a message.
    """
    runs_once = not (todo.recurrence or todo.trigger_subscriptions)
    desk_sweep = _is_desk_sweep(todo, finished)
    may_wait = (
        desk_sweep or _can_wait(todo, finished, runs_once=runs_once)
    ) and await _has_live_daily_brief(todo.user_id)
    # Where it goes is looked up while comms writes it up: neither waits on the other.
    text, target = await asyncio.gather(
        narrate_executor_result(
            finished.result_text,
            "result",
            finished.conversation_id,
            user,
            preamble=tracked_todo_delivery_note(
                todo.title,
                _canvas_section(todo, CANVAS_STANDING_RULES_SECTION, STANDING_RULES_MAX_CHARS),
                _canvas_section(todo, CANVAS_KEY_DETAILS_SECTION, DELIVERY_KEY_DETAILS_MAX_CHARS),
                runs_once=runs_once,
                run_history=recent_run_outcomes(todo.activity_content, DELIVERY_RUN_HISTORY_LINES),
                may_wait=may_wait and not desk_sweep,
            ),
        ),
        _lookup_target(todo),
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

    # comms' retelling dropped the headings a report-form owner's guidance requires.
    owns_form = todo.external_ref is not None and todo.external_ref.source.owns_report_form
    message = finished.result_text if owns_form else directive.payload
    if desk_sweep and may_wait:
        return await _hold_for_brief(finished, todo, message.splitlines())
    if directive.kind is CommsDirectiveKind.BRIEF:
        if may_wait:
            return await _hold_for_brief(finished, todo, [directive.payload])
        log.warning(
            f"{LogTag.AGENT} comms held a result that must go now; it is sent",
            todo_id=todo.id,
        )
    platform = (
        await deliver_result_to_platforms(
            user=user,
            notification_text=message,
            origin=f'tracked todo "{todo.title}" (id {todo.id})',
            message_class=finished.message_class,
            target=target,
        )
        if target is not None
        else None
    )
    if platform is None:
        return (await _send_in_app(todo, message))._replace(target=target)
    return _Resolution(
        TodoRunDeliveryOutcome.DELIVERED, f"result sent on {platform.value}", platform, target
    )
