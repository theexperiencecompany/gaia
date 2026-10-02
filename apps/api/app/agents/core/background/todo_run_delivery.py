"""Terminal delivery for a tracked todo's own background run.

The run's conversation is a throwaway with no transport, so its result is never
saved there: comms decides whether it is worth a message at all, the user's chat
app gets it only if so, and activity.md records what happened either way.
"""

from typing import NamedTuple

from app.agents.core.background.comms_narrator import narrate_executor_result
from app.agents.core.background.session import ExecutorRun, TodoRun
from app.agents.core.background.workflow_platform_delivery import deliver_result_to_platforms
from app.agents.core.comms_directive import interpret_comms_output
from app.agents.prompts.comms_prompts import tracked_todo_delivery_note
from app.constants.comms import CommsDirectiveKind
from app.constants.log_tags import LogTag
from app.constants.todos import (
    CANVAS_KEY_DETAILS_SECTION,
    CANVAS_STANDING_RULES_SECTION,
    DELIVERY_KEY_DETAILS_MAX_CHARS,
    RUN_SUMMARY_ACTIVITY_CHARS,
    STANDING_RULES_MAX_CHARS,
    TodoActivityEvent,
    TodoRunDeliveryOutcome,
)
from app.db.repositories.todos import todo_repository
from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.models.todo_models import TodoDocument
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.canvas_markdown import section_body
from app.services.notification_service import notification_service
from app.services.todo_activity import record_activity
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


async def deliver_todo_run_result(
    run: ExecutorRun, todo_run: TodoRun, result_text: str, result_type: str
) -> None:
    """Decide, deliver and record what a finished tracked-todo run tells the user.

    An error result delivers nothing: the worker that awaits the run retries it
    and records the failure itself.
    """
    log.set_ns("todo_delivery", todo_id=todo_run.todo_id, result_type=result_type)
    if result_type == "error":
        return
    todo = await todo_repository.get_by_id(todo_run.todo_id)
    if todo is None:
        log.warning(
            f"{LogTag.AGENT} todo run finished for a deleted todo", todo_id=todo_run.todo_id
        )
        return

    # Read now, not when the run started: the run itself may have turned it off.
    resolution = (
        await _narrate_and_send(run, todo, result_text)
        if todo.notify_on_run
        else _not_sent(TodoRunDeliveryOutcome.NOTIFY_OFF)
    )

    log.set_ns("todo_delivery", outcome=resolution.outcome.value)
    summary = result_text.strip().replace("\n", " ")[:RUN_SUMMARY_ACTIVITY_CHARS]
    await record_activity(
        todo.id,
        todo.user_id,
        TodoActivityEvent.RUN_FINISHED,
        f"{resolution.note} (summary={summary!r})",
    )
    # A worker has no request context: the explicit user id keeps the event off
    # an anonymous profile.
    capture_event(
        todo.user_id,
        AnalyticsEvents.TODO_RUN_RESULT_DELIVERED,
        {
            "outcome": resolution.outcome.value,
            "delivered": resolution.outcome is TodoRunDeliveryOutcome.DELIVERED,
            "platform": resolution.platform.value if resolution.platform else None,
            "trigger_type": todo_run.trigger_type.value,
            "recurring": bool(todo.recurrence),
        },
    )


def _canvas_section(todo: TodoDocument, heading: str, max_chars: int) -> str | None:
    """Return one canvas section's body, bounded, or None when it is missing or empty."""
    body = section_body(todo.canvas_content, heading)
    return body[:max_chars] if body else None


async def _send_in_app(todo: TodoDocument, text: str) -> _Resolution:
    """Deliver a result as an in-app notification, for a user with no chat app linked."""
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=todo.user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                content=NotificationContent(title=todo.title, body=text),
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


async def _narrate_and_send(run: ExecutorRun, todo: TodoDocument, result_text: str) -> _Resolution:
    """Have comms write the result up (or decline to), then send it to the chat app."""
    text = await narrate_executor_result(
        result_text,
        "result",
        run.conversation_id,
        run.user,
        preamble=tracked_todo_delivery_note(
            todo.title,
            _canvas_section(todo, CANVAS_STANDING_RULES_SECTION, STANDING_RULES_MAX_CHARS),
            _canvas_section(todo, CANVAS_KEY_DETAILS_SECTION, DELIVERY_KEY_DETAILS_MAX_CHARS),
        ),
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
        user=run.user,
        user_id=todo.user_id,
        notification_text=directive.payload,
        origin=f'tracked todo "{todo.title}" (id {todo.id})',
    )
    if platform is None:
        return await _send_in_app(todo, directive.payload)
    return _Resolution(
        TodoRunDeliveryOutcome.DELIVERED, f"result sent on {platform.value}", platform
    )
