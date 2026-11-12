"""Terminal delivery for background-executor results.

Two entry points share the run's ExecutorRun context: deliver_result narrates,
composes the bot message, persists to MongoDB, then routes over EXACTLY ONE
transport (bot platform / WebSocket / workflow notification); persist_cancelled_run
instead durably persists a self-owning cancelled run's already-streamed cards
(no narration/re-push — frontend sync reconciles by message_id == task_id).
Every terminal path goes through one of these.

deliver_message_to_conversation is the run-free primitive underneath (pushes an
already-voiced proactive message into one conversation, reusing the same
save/route/checkpoint seams). Neither reads the run's session — both take cards
snapshotted before signalling done, since the comms consumer has by then torn it down.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import time
from typing import Any, Literal
from uuid import uuid4

from fastapi import HTTPException
from langsmith import traceable

from app.agents.core.background.comms_narrator import (
    narrate_executor_result,
    record_platform_delivery,
)
from app.agents.core.background.session import ExecutorRun
from app.agents.core.background.todo_run_delivery import deliver_todo_run_result
from app.agents.core.background.workflow_platform_delivery import (
    deliver_workflow_result,
)
from app.agents.core.comms_directive import interpret_comms_output
from app.agents.core.nodes.follow_up_actions_node import generate_follow_up_actions
from app.agents.prompts.comms_prompts import (
    INTERACTIVE_DELIVERY_NOTE,
    PLATFORM_DELIVERY_NOTE,
    SILENCE_NOTE,
)
from app.constants.chat import CONVERSATION_MAX_MESSAGES
from app.constants.comms import CommsDirectiveKind
from app.constants.executor import (
    EXECUTOR_NARRATION_FAILED_ERROR_MESSAGE,
    EXECUTOR_NARRATION_FAILED_MESSAGE,
)
from app.constants.log_tags import LogTag
from app.constants.todos import TODO_CONVERSATION_MAX_MESSAGES
from app.constants.websocket import WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS
from app.core.websocket_manager import websocket_manager
from app.db.repositories.conversations import conversation_repository
from app.models.agent_models import CommsDirective
from app.models.chat_models import (
    ConversationSource,
    MessageKind,
    MessageModel,
    ToolDataEntry,
    UpdateMessagesRequest,
)
from app.models.message_models import ReplyToMessageData, TodoRunWake
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import capture
from app.services.conversation_service import update_messages
from app.services.latency_metrics import observe_delivery_narration, observe_delivery_persist
from app.services.platform_message_service import (
    deliver_message_to_platform,
    deliver_reaction_to_platform,
    is_bot_platform,
)
from app.utils.background_tasks import spawn_background_task
from shared.py.analytics import UserId
from shared.py.analytics.catalog.chat import ChatBackgroundUpdateResolved
from shared.py.wide_events import get_trace_id, log, log_context


@dataclass(frozen=True)
class _DeliveryTarget:
    """Who one run's result is delivered to, and how the client keys it.

    The same cluster — owner, conversation, the task_id-keyed placeholder to
    replace (if any) and the reply-quote the message carries — is threaded
    through every delivery helper, so it travels as one value.
    """

    user_id: str
    conversation_id: str
    task_id: str | None
    emit_task_id: bool
    # No reply quote unless a run answers a user message it can quote.
    show_reply_quote: bool = False
    user_message_id: str | None = None
    user_msg_content: str = ""


@dataclass(frozen=True)
class _WorkflowRef:
    """The workflow whose completion/failure notification is being dispatched."""

    workflow_id: str
    workflow_title: str
    notify_on_completion: bool = True


@traceable(name="bg_notification_delivery", run_type="chain")
async def deliver_result(
    run: ExecutorRun,
    result_text: str,
    result_type: str,
    returned_note: str = "",
    *,
    tool_data: list[ToolDataEntry] | None,
    outcome_note: str = "",
) -> tuple[str | None, str | None]:
    """Narrate a finished executor run through comms, persist it, and deliver it.

    Returns (narrated_text, message_id); (None, None) on failure or for a tracked
    todo's own run, whose report stays in its todo's chat and whose message goes
    through todo delivery. A REACT gives (None, message_id). The message routes over
    EXACTLY ONE transport chosen by the conversation's source.
    """
    try:
        if run.todo_run is not None:
            await _record_todo_run_report(run, result_text, result_type, tool_data)
            await deliver_todo_run_result(run, run.todo_run, result_text, result_type)
            return None, None
        return await _narrate_and_deliver(
            run, result_text + outcome_note, result_type, tool_data, returned_note
        )
    except Exception as e:  # delivery is best-effort, never propagates
        log.error(f"{LogTag.AGENT} Background notification delivery failed", error=str(e))
        return None, None


async def _record_todo_run_report(
    run: ExecutorRun,
    result_text: str,
    result_type: str,
    tool_data: list[ToolDataEntry] | None,
) -> None:
    """Save the executor's own report and cards in the todo's chat, under the placeholder its stream rendered.

    A failed save leaves delivery to go ahead: the user's message does not depend on the record."""
    failed = result_type == "error"
    bot_message = MessageModel(
        type="bot",
        response="" if failed else result_text,
        error=result_text if failed else None,
        date=datetime.now(UTC).isoformat(),
        message_id=run.render_message_id,
        tool_data=tool_data or None,
    )
    if not await _save_message(
        run.conversation_id, run.user, bot_message, max_messages=TODO_CONVERSATION_MAX_MESSAGES
    ):
        return
    await _broadcast_bot_message(
        target=_DeliveryTarget(
            user_id=run.user.user_id,
            conversation_id=run.conversation_id,
            task_id=run.task_id,
            emit_task_id=True,
        ),
        bot_message=bot_message,
        notification_text=bot_message.response,
        tool_data=bot_message.tool_data,
    )


async def record_todo_run_wake(
    conversation_id: str, user: AuthenticatedUser, wake: TodoRunWake
) -> None:
    """Lead a tracked todo's run with what woke it, on the user's side of its chat.

    Pushed as conversation.new_message so an open chat shows it live; a failed save lets the run go ahead."""
    message = MessageModel(
        type="user",
        response="",
        date=datetime.now(UTC).isoformat(),
        message_id=str(uuid4()),
        todo_run_wake=wake,
    )
    if not await _save_message(
        conversation_id, user, message, max_messages=TODO_CONVERSATION_MAX_MESSAGES
    ):
        return
    await _broadcast_message(
        user.user_id,
        {
            "type": "conversation.new_message",
            "conversation_id": conversation_id,
            "message": {
                "type": "user",
                "response": "",
                "message_id": message.message_id,
                "date": message.date,
                "todo_run_wake": wake.model_dump(mode="json"),
            },
        },
    )


async def persist_cancelled_run(run: ExecutorRun, tool_data: list[ToolDataEntry]) -> None:
    """Durably persist the tool cards a cancelled self-owning run already streamed.

    Writes the frontend's already-rendered placeholder cards (keyed by task_id) to
    MongoDB so they survive a cache clear and sync to other devices — no
    re-narration, no result text, no WebSocket re-push of already-streamed data.
    """
    if not tool_data:
        log.info(
            f"{LogTag.AGENT} Cancelled executor produced no cards to persist",
            task_id=run.task_id,
            stream_id=run.stream_id,
        )
        return

    bot_message = MessageModel(
        type="bot",
        response="",
        date=datetime.now(UTC).isoformat(),
    )
    bot_message.message_id = run.task_id or str(uuid4())
    bot_message.tool_data = tool_data

    persist_start = time.perf_counter()
    try:
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=run.conversation_id,
                messages=[bot_message],
            ),
            user=run.user,
            # A tracked todo's chat is reused by every run, so a stopped one is capped too.
            max_messages=TODO_CONVERSATION_MAX_MESSAGES
            if run.todo_run
            else CONVERSATION_MAX_MESSAGES,
        )
    except HTTPException as e:
        if e.status_code == 404:  # conversation deleted mid-run — expected, not an error
            log.info(
                f"{LogTag.AGENT} conversation deleted, skipping cancelled card save",
                conversation_id=run.conversation_id,
            )
            return
        log.error(f"{LogTag.AGENT} Failed to save cancelled executor cards", error=str(e))
        return
    except Exception as e:  # best-effort save of a stopped run
        log.error(f"{LogTag.AGENT} Failed to save cancelled executor cards", error=str(e))
        return
    finally:
        observe_delivery_persist(time.perf_counter() - persist_start, op="cancelled_cards")

    log.info(
        f"{LogTag.AGENT} Persisted cancelled executor cards",
        message_id=bot_message.message_id,
        task_id=run.task_id,
        stream_id=run.stream_id,
        tool_card_count=len(tool_data),
    )


async def deliver_message_to_conversation(
    *,
    conversation_id: str,
    user: AuthenticatedUser,
    text: str,
    origin: str,
    tool_data: list[ToolDataEntry] | None = None,
) -> ConversationSource | None:
    """Deliver an already-voiced proactive message into one existing conversation.

    Routes over the conversation's own transport (bot platform or WebSocket), then
    appends to the checkpoint so a later turn remembers it. Takes no run and does
    not narrate: text is the user-facing message already, and tool_data the cards
    of work that ran outside any turn. Never raises; returns the source, or None.
    """
    if not text.strip():
        return None
    user_id = user.user_id
    # An empty card list is "no cards", not a card set: kept as None so a plain
    # proactive message never persists an empty tool_data array.
    cards = tool_data or None
    bot_message = MessageModel(
        type="bot", response=text, date=datetime.now(UTC).isoformat(), tool_data=cards
    )
    bot_message.message_id = str(uuid4())

    if not await _save_message(conversation_id, user, bot_message):
        return None

    source = await _get_conversation_source(conversation_id, user_id)
    target = _DeliveryTarget(
        user_id=user_id,
        conversation_id=conversation_id,
        task_id=None,
        emit_task_id=False,
    )
    if is_bot_platform(source):
        delivered = await deliver_message_to_platform(
            source, user_id, text, conversation_id=conversation_id
        )
        transport = "platform"
    else:
        await _broadcast_bot_message(
            target=target,
            bot_message=bot_message,
            notification_text=text,
            tool_data=cards,
        )
        delivered = True
        transport = "websocket"

    # No narration ran, so nothing wrote this into the comms checkpoint. Record it
    # (only once actually delivered) so the next turn here remembers it.
    if delivered:
        await record_platform_delivery(
            conversation_id, f"[Delivered to the user ({origin})]: {text}"
        )

    _log_delivery_verdict(
        target=target,
        message_id=bot_message.message_id,
        conversation_source=source,
        transport=transport,
        delivered=delivered,
    )
    return source if delivered else None


async def _narrate_and_deliver(
    run: ExecutorRun,
    result_text: str,
    result_type: str,
    tool_data: list[ToolDataEntry] | None,
    returned_note: str,
) -> tuple[str | None, str | None]:
    """Compose the user-facing message, save it, and route it.

    Returns (narrated_text, message_id) of the saved bot message, or
    (None, None) if it could not be saved.
    """
    user_id = run.user.user_id

    # Narration is the slow LLM call; the routing read, which does not depend on it, runs alongside.
    notification_text, conversation_source = await asyncio.gather(
        _narrate_result(run, result_text, result_type, returned_note),
        _get_conversation_source(run.conversation_id, user_id),
    )

    # Comms may answer with a control tag instead of a message: SILENCE (deliver
    # nothing) or REACT (one-emoji ack). One event records the outcome and the
    # emoji (never reason/text); the delivery prop says how the ack landed.
    directive = interpret_comms_output(notification_text)
    is_react = directive.kind is CommsDirectiveKind.REACT

    message_kind = MessageKind.TEXT
    if directive.kind is CommsDirectiveKind.SILENCE:
        log.set(comms_delivery="silenced", silence_reason=directive.payload)
        _capture_resolution(run, directive)
        return None, None
    # A reply's payload is its text without any directive bubble written beside it.
    notification_text = directive.payload
    if is_react:
        log.set(comms_delivery="reacted")
        message_kind = MessageKind.EMOJI_ACK
    else:
        log.set(comms_delivery="message")

    bot_message = _build_bot_message(
        run,
        notification_text,
        tool_data,
        kind=message_kind,
        reacts_to=run.user_message_id if is_react else None,
    )

    show_reply_quote, user_msg_content = await _attach_reply_quote(run, bot_message)
    target = _DeliveryTarget(
        user_id=user_id,
        conversation_id=run.conversation_id,
        task_id=run.task_id,
        emit_task_id=run.is_queued,
        show_reply_quote=show_reply_quote,
        user_message_id=run.user_message_id,
        user_msg_content=user_msg_content,
    )

    # Follow-ups are a second LLM call: web/mobile get them after the answer, a
    # workflow run attaches them inline, and a bot reply gets none (no bot renders them).
    if run.workflow_id and not is_react:
        follow_up_actions = await _safe_inline_follow_ups(
            result_type=result_type,
            notification_text=notification_text,
            target=target,
            message_id=bot_message.message_id,
        )
        if follow_up_actions:
            bot_message.follow_up_actions = follow_up_actions

    if not await _save_message(run.conversation_id, run.user, bot_message):
        return None, None

    # The bot message is already saved above, for the notification's "View Results".
    if run.workflow_id:
        await _deliver_workflow_result(
            run,
            target=target,
            message_id=bot_message.message_id,
            notification_text=notification_text,
            result_type=result_type,
        )
        _capture_resolution(run, directive, "fallback_text" if is_react else "message")
        return None if is_react else notification_text, bot_message.message_id

    # Deliver over exactly one transport, by the conversation's source: bot
    # conversations to their platform API, web/mobile/system to WebSocket (the
    # web list excludes bot sources, so a WebSocket push there would be dropped).
    if is_bot_platform(conversation_source):
        delivered, transport = await _deliver_to_platform(
            run, conversation_source, notification_text, is_react=is_react
        )
    else:
        await _broadcast_and_defer_follow_ups(
            target=target,
            bot_message=bot_message,
            notification_text=notification_text,
            tool_data=tool_data,
            result_type=result_type,
            is_react=is_react,
        )
        delivered, transport = True, "websocket"

    _log_delivery_verdict(
        target=target,
        message_id=bot_message.message_id,
        conversation_source=conversation_source,
        transport=transport,
        delivered=delivered,
    )
    _capture_resolution(run, directive, _react_delivery(transport) if is_react else "message")
    # A reaction has no speakable text: voice must not read the emoji aloud,
    # so it resolves to None here (the ack itself is saved and routed above).
    return None if is_react else notification_text, bot_message.message_id


def _capture_resolution(
    run: ExecutorRun,
    directive: CommsDirective,
    delivery: Literal["message", "reaction", "badge", "fallback_text"] | None = None,
) -> None:
    """Record how one background update resolved; delivery says how the ack landed."""
    capture(
        UserId(run.user.user_id),
        ChatBackgroundUpdateResolved(
            outcome=directive.kind.value,
            emoji=directive.payload if directive.kind is CommsDirectiveKind.REACT else None,
            delivery=delivery,
        ),
        dedupe=run.analytics_dedupe,
    )


def _react_delivery(transport: str) -> Literal["reaction", "badge", "fallback_text"]:
    """How a REACT ack actually reached the user, by the transport that carried it."""
    if transport == "reaction":
        return "reaction"
    return "badge" if transport == "websocket" else "fallback_text"


async def _deliver_workflow_result(
    run: ExecutorRun,
    *,
    target: _DeliveryTarget,
    message_id: str,
    notification_text: str,
    result_type: str,
) -> None:
    """Route a workflow run's result: platform messages plus the in-app badge.

    No human is watching a workflow run, so it goes out as the proactive
    completion notification rather than one conversation transport.
    """
    # Successful, non-silent runs land in the user's real messaging-platform
    # conversations as normal bot messages (GAIA's voice, no notification
    # chrome). The badge is a web-only heads-up, dispatched alongside.
    in_app = _dispatch_workflow_notification(
        msg_type=result_type,
        workflow=_WorkflowRef(
            workflow_id=run.workflow_id,
            workflow_title=run.workflow_title,
            notify_on_completion=run.workflow_notify_on_completion,
        ),
        target=target,
        message_id=message_id,
    )
    if result_type == "error" or not run.workflow_notify_on_completion:
        await in_app
        return
    # The chat-app message and the in-app badge are independent sends.
    await asyncio.gather(
        deliver_workflow_result(
            user=run.user,
            workflow_id=run.workflow_id,
            notification_text=notification_text,
            origin=_delivery_origin(run),
        ),
        in_app,
    )


async def _deliver_to_platform(
    run: ExecutorRun,
    conversation_source: ConversationSource | None,
    notification_text: str,
    *,
    is_react: bool,
) -> tuple[bool, str]:
    """Send the update over the conversation's bot platform; returns (delivered, transport)."""
    user_id = run.user.user_id
    # None takes the same branches: every falsy path reassigns it before the return.
    delivered = False  # pragma: no mutate
    transport = "platform"
    if is_react:
        # Native reaction anchored to the user's message; falls back to the
        # one-emoji text bubble when there is no recorded platform id or the
        # publish fails, so the acknowledgment is never lost.
        platform_message_id = await _lookup_platform_message_id(
            run.conversation_id, run.user_message_id, user_id
        )
        if platform_message_id is not None:
            delivered = await deliver_reaction_to_platform(
                conversation_source,
                user_id,
                platform_message_id,
                notification_text,
                conversation_id=run.conversation_id,
            )
            if delivered:
                transport = "reaction"
                log.set(platform_reaction="attached")
        if not delivered:
            log.set(platform_reaction="fallback_text")
    if not delivered:
        delivered = await deliver_message_to_platform(
            conversation_source,
            user_id,
            notification_text,
            conversation_id=run.conversation_id,
        )
    return delivered, transport


async def _broadcast_and_defer_follow_ups(
    *,
    target: _DeliveryTarget,
    bot_message: MessageModel,
    notification_text: str,
    tool_data: list[ToolDataEntry] | None,
    result_type: str,
    is_react: bool,
) -> None:
    """Push the answer to the client now, then generate follow-ups in the background.

    The second push reuses conversation.new_message — the client upserts by id.
    A reaction gets none: there is no rendered message to attach chips to.
    """
    await _broadcast_bot_message(
        target=target,
        bot_message=bot_message,
        notification_text=notification_text,
        tool_data=tool_data,
    )
    if not is_react:
        _spawn_deferred_follow_ups(
            bot_message=bot_message,
            result_type=result_type,
            tool_data=tool_data,
            target=target,
        )


def _delivery_preamble(run: ExecutorRun, returned_note: str) -> str:
    """Pick the delivery instructions comms writes this run's reply under."""
    if run.workflow_id:
        # Text-only platform delivery: comms must restate everything. The
        # card-suppression note is deliberately dropped — it would tell comms
        # NOT to list data that has no card to fall back on.
        return PLATFORM_DELIVERY_NOTE
    # Interactive chat: "already shown as a card" first, so comms doesn't
    # re-narrate data the frontend rendered, then the bubble-split instruction.
    return f"{returned_note}{INTERACTIVE_DELIVERY_NOTE}{SILENCE_NOTE}"


async def _narrate_result(
    run: ExecutorRun,
    result_text: str,
    result_type: str,
    returned_note: str,
) -> str:
    """Re-voice the executor's terminal text through comms, falling back to it."""
    narration_start = time.perf_counter()
    notification_text = await narrate_executor_result(
        result_text,
        result_type,
        run.conversation_id,
        run.user,
        preamble=_delivery_preamble(run, returned_note),
    )
    # Never fall back to result_text: it is the executor's internal monologue,
    # and on the error path a raw exception string (executor_runner `str(e)`).
    narrated = bool(notification_text)
    if not narrated:
        notification_text = (
            EXECUTOR_NARRATION_FAILED_ERROR_MESSAGE
            if result_type == "error"
            else EXECUTOR_NARRATION_FAILED_MESSAGE
        )
    observe_delivery_narration(
        time.perf_counter() - narration_start, status="success" if narrated else "fallback"
    )
    log.set_ns(
        "result_delivery",
        result_type=result_type,
        narrated=narrated,
        text_length=len(notification_text),
    )
    return notification_text


def _build_bot_message(
    run: ExecutorRun,
    notification_text: str,
    tool_data: list[ToolDataEntry] | None,
    *,
    kind: MessageKind = MessageKind.TEXT,
    reacts_to: str | None = None,
) -> MessageModel:
    """Build the bot message this run's result is saved and delivered as."""
    bot_message = MessageModel(
        type="bot",
        response=notification_text,
        date=datetime.now(UTC).isoformat(),
        kind=kind,
        reacts_to_message_id=reacts_to,
    )
    bot_message.message_id = (run.task_id if run.is_queued else None) or str(uuid4())
    if tool_data:
        bot_message.tool_data = tool_data
    return bot_message


async def _attach_reply_quote(
    run: ExecutorRun,
    bot_message: MessageModel,
) -> tuple[bool, str]:
    """Quote the user's message on the bot message; returns (shown, content)."""
    # Reply-quote only for genuinely queued tasks — live tasks land directly
    # after the user's last message, where quoting would be noise.
    user_msg_content = ""
    show_reply_quote = run.is_queued and bool(run.user_message_id)
    if show_reply_quote:
        user_msg_content = await _lookup_user_message_content(
            run.conversation_id, run.user_message_id, run.user.user_id
        )
        bot_message.replyToMessage = ReplyToMessageData(
            id=run.user_message_id,
            content=user_msg_content,
            role="user",
        )
    return show_reply_quote, user_msg_content


async def _save_message(
    conversation_id: str,
    user: AuthenticatedUser,
    message: MessageModel,
    *,
    max_messages: int = CONVERSATION_MAX_MESSAGES,
) -> bool:
    """Append the message, keeping the conversation's newest max_messages; False when it wasn't saved."""
    persist_start = time.perf_counter()
    try:
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=conversation_id,
                messages=[message],
            ),
            user=user,
            max_messages=max_messages,
        )
    except HTTPException as e:
        if e.status_code == 404:  # conversation deleted mid-run — expected, not an error
            log.info(
                f"{LogTag.AGENT} conversation deleted, skipping message save",
                conversation_id=conversation_id,
            )
            return False
        log.error(f"{LogTag.AGENT} deliver_result: failed to save message", error=str(e))
        return False
    except Exception as e:
        log.error(f"{LogTag.AGENT} deliver_result: failed to save message", error=str(e))
        return False
    finally:
        observe_delivery_persist(time.perf_counter() - persist_start, op="save_bot_message")
    return True


def _log_delivery_verdict(
    *,
    target: _DeliveryTarget,
    message_id: str | None,
    conversation_source: ConversationSource | None,
    transport: str,
    delivered: bool,
) -> None:
    """Record whether the saved result actually reached the user."""
    # Delivery is the last step that can silently lose a finished run: the answer
    # saves either way, so a failed send leaves a "success" run whose user got
    # nothing. Verdict goes on the executor_run wide event so it's queryable.
    log.set_ns(
        "result_delivery",
        transport=transport,
        delivered=delivered,
        source=conversation_source.value if conversation_source else None,
    )
    if delivered:
        log.info(
            f"{LogTag.AGENT} deliver_result: delivered message",
            message_id=message_id,
            task_id=target.task_id,
            conversation_id=target.conversation_id,
            conversation_source=conversation_source.value if conversation_source else None,
            transport=transport,
        )
    else:
        log.error(
            f"{LogTag.AGENT} deliver_result: result saved but NOT delivered to the user",
            message_id=message_id,
            task_id=target.task_id,
            conversation_id=target.conversation_id,
            conversation_source=conversation_source.value if conversation_source else None,
            transport=transport,
        )


async def _safe_inline_follow_ups(
    *,
    result_type: str,
    notification_text: str,
    target: _DeliveryTarget,
    message_id: str | None,
) -> list[str]:
    """Build follow-up actions for the single-send path, swallowing failures.

    Follow-ups are a best-effort enhancement. A failure in this second LLM call
    must not abort delivery — the outer deliver_result handler turns any exception
    into (None, None) and drops the result, so guard it here and ship the message
    without suggestions instead.
    """
    try:
        return await _build_follow_up_actions(
            msg_type=result_type,
            notification_text=notification_text,
            user_msg_content=target.user_msg_content,
            user_id=target.user_id,
            conversation_id=target.conversation_id,
        )
    except Exception as e:  # follow-ups are best-effort
        log.error(
            f"{LogTag.AGENT} deliver_result: failed to generate follow-up actions",
            error=str(e),
            conversation_id=target.conversation_id,
            message_id=message_id,
        )
        return []


async def _build_follow_up_actions(
    *,
    msg_type: str,
    notification_text: str,
    user_msg_content: str,
    user_id: str,
    conversation_id: str | None,
) -> list[str]:
    """Generate follow-up suggestions on the executor's final answer.

    Suggestions are computed on the real result (not the intermediate comms ack)
    so they appear once. Only successful results get suggestions — an error
    message gets none.
    """
    if msg_type != "final":
        return []
    follow_up_context = (
        f"User request: {user_msg_content}\n\nAssistant response: {notification_text}"
        if user_msg_content
        else notification_text
    )
    return await generate_follow_up_actions(
        follow_up_context,
        user_id,
        # The conversation's session_id: without it, one-shots had no sticky-routing
        # key (measured: 0% cache hit on executor-final follow-ups). aux suffix is
        # applied inside ainvoke_structured, matching the node-path calls.
        {"configurable": {"user_id": user_id, "session_id": conversation_id}},
    )


def _spawn_deferred_follow_ups(
    *,
    bot_message: MessageModel,
    result_type: str,
    tool_data: list[ToolDataEntry] | None,
    target: _DeliveryTarget,
) -> None:
    """Generate follow-up actions off the critical path and push a second update.

    Runs after the message is already delivered, so the answer isn't gated
    behind the extra LLM call.
    """
    spawn_background_task(
        _generate_and_push_follow_ups(
            bot_message=bot_message,
            result_type=result_type,
            tool_data=tool_data,
            target=target,
        )
    )


async def _generate_and_push_follow_ups(
    *,
    bot_message: MessageModel,
    result_type: str,
    tool_data: list[ToolDataEntry] | None,
    target: _DeliveryTarget,
) -> None:
    # Runs detached from the executor's boundary and typically finishes after
    # that event has emitted — without its own boundary, the follow-up LLM
    # call's context (and any log.error below) is silently discarded.
    async with log_context(
        "follow_up_generation",
        trace_id=get_trace_id() or None,
        conversation_id=target.conversation_id,
        task_id=target.task_id,
    ):
        try:
            follow_up_actions = await _build_follow_up_actions(
                msg_type=result_type,
                notification_text=bot_message.response,
                user_msg_content=target.user_msg_content,
                user_id=target.user_id,
                conversation_id=target.conversation_id,
            )
            if not follow_up_actions:
                return

            bot_message.follow_up_actions = follow_up_actions
            persisted = await _persist_follow_up_actions(
                user_id=target.user_id,
                conversation_id=target.conversation_id,
                message_id=bot_message.message_id,
                follow_up_actions=follow_up_actions,
            )
            if not persisted:
                # Broadcasting unpersisted suggestions would show them in the UI
                # only to vanish on reload — drop them instead.
                return
            await _broadcast_bot_message(
                target=target,
                bot_message=bot_message,
                notification_text=bot_message.response,
                tool_data=tool_data,
                follow_up_actions=follow_up_actions,
            )
        except Exception as e:
            # Non-critical enhancement — the answer is already delivered. Log loudly
            # but never let a follow-up failure crash the background task.
            log.error(
                f"{LogTag.AGENT} deliver_result: deferred follow-up actions failed", error=str(e)
            )


async def _persist_follow_up_actions(
    *,
    user_id: str,
    conversation_id: str,
    message_id: str | None,
    follow_up_actions: list[str],
) -> bool:
    """Attach deferred follow-up suggestions to the already-saved bot message.

    Must be an in-place update matched by id — re-saving via update_messages
    ($push-based) would append a duplicate answer. Returns True only when written,
    so the caller doesn't broadcast follow-ups that won't survive a reload.
    """
    if not message_id:
        log.warning(
            f"{LogTag.AGENT} _persist_follow_up_actions: missing message_id, dropping follow-ups",
            conversation_id=conversation_id,
        )
        return False
    matched = await conversation_repository.set_message_follow_up_actions(
        conversation_id, user_id=user_id, message_id=message_id, actions=follow_up_actions
    )
    if not matched:
        log.error(
            f"{LogTag.AGENT} _persist_follow_up_actions: no message matched, dropping follow-ups",
            conversation_id=conversation_id,
            message_id=message_id,
        )
        return False
    return True


async def _dispatch_workflow_notification(
    *,
    msg_type: str,
    workflow: _WorkflowRef,
    target: _DeliveryTarget,
    message_id: str | None,
) -> None:
    """Send the proactive workflow completion/failure notification.

    Failures always notify. Success respects notify_on_completion: silent
    workflows keep their result in the conversation, leaving user-facing alerting
    to the agent's own send_notification calls.
    """
    # Imported here to avoid the workflow-service → agent import cycle.
    from app.services.workflow.notifications import (
        send_workflow_completion_notification,
        send_workflow_failure_notification,
    )

    if msg_type == "error":
        await send_workflow_failure_notification(
            workflow_id=workflow.workflow_id,
            workflow_title=workflow.workflow_title,
            user_id=target.user_id,
        )
    elif not workflow.notify_on_completion:
        log.info(
            f"{LogTag.AGENT} deliver_result: completion notification skipped (workflow is silent)",
            workflow_id=workflow.workflow_id,
            message_id=message_id,
        )
        return
    else:
        await send_workflow_completion_notification(
            workflow_id=workflow.workflow_id,
            workflow_title=workflow.workflow_title,
            conversation_id=target.conversation_id,
            user_id=target.user_id,
        )
    log.info(
        f"{LogTag.AGENT} deliver_result: workflow notification dispatched",
        workflow_id=workflow.workflow_id,
        message_id=message_id,
    )


async def _broadcast_bot_message(
    *,
    target: _DeliveryTarget,
    bot_message: MessageModel,
    notification_text: str,
    tool_data: list[ToolDataEntry] | None,
    follow_up_actions: list[str] | None = None,
) -> None:
    """Push the bot message to web/mobile/system clients over the WebSocket."""
    ws_payload: dict[str, Any] = {
        "type": "bot",
        "response": notification_text,
        "message_id": bot_message.message_id,
        "date": bot_message.date,
        "kind": bot_message.kind.value,
    }
    if bot_message.error:
        ws_payload["error"] = bot_message.error
    # An emoji-ack renders as a reaction badge on the message it answers,
    # not a new bubble — the client needs the target GAIA message id.
    if bot_message.kind is MessageKind.EMOJI_ACK and bot_message.reacts_to_message_id:
        ws_payload["reacts_to_message_id"] = bot_message.reacts_to_message_id
    if tool_data:
        ws_payload["tool_data"] = tool_data
    if follow_up_actions:
        ws_payload["follow_up_actions"] = follow_up_actions
    # Only advertise task_id when a placeholder exists to replace (useExecutorStream
    # creates one only for queued-kind dispatch). A plain live run's task_id has no
    # placeholder, so emitting it would make replaceMessage(task_id) target the wrong key.
    if target.task_id and target.emit_task_id:
        ws_payload["task_id"] = target.task_id
    if target.show_reply_quote:
        ws_payload["replyToMessage"] = {
            "id": target.user_message_id,
            "content": target.user_msg_content,
            "role": "user",
        }
    await _broadcast_message(
        target.user_id,
        {
            "type": "conversation.new_message",
            "conversation_id": target.conversation_id,
            "message": ws_payload,
        },
    )


async def _broadcast_message(user_id: str, ws_event: dict[str, object]) -> None:
    """Best-effort WebSocket broadcast with one retry."""
    for attempt in range(2):
        try:
            await websocket_manager.broadcast_to_user(user_id, ws_event)
            return
        except Exception as ws_err:
            log.warning(
                f"{LogTag.AGENT} _broadcast_message: broadcast attempt failed",
                attempt=attempt + 1,
                user_id=user_id,
                error=str(ws_err),
            )
            if attempt == 0:
                await asyncio.sleep(WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS)


async def _lookup_platform_message_id(
    conversation_id: str,
    user_message_id: str | None,
    user_id: str,
) -> str | None:
    """Return the platform-native id of a user message, for anchoring a reaction.

    Returns None when there is no triggering user message (scheduled runs) or the
    turn predates platform-id recording — the caller falls back to a text bubble.
    """
    if not user_message_id:
        return None
    try:
        message = await conversation_repository.get_message(
            conversation_id, user_message_id, user_id=user_id
        )
        if message is not None:
            return message.platform_message_id
    except Exception as e:
        log.warning(f"{LogTag.AGENT} _lookup_platform_message_id: failed", error=str(e))
    return None


async def _lookup_user_message_content(
    conversation_id: str,
    user_message_id: str | None,
    user_id: str,
) -> str:
    """Look up the first 150 chars of a user message for reply-to preview."""
    if not user_message_id:
        return ""
    try:
        message = await conversation_repository.get_message(
            conversation_id, user_message_id, user_id=user_id
        )
        if message is not None:
            return (message.response or "")[:150]
    except Exception as e:
        log.warning(f"{LogTag.AGENT} _lookup_user_message_content: failed", error=str(e))
    return ""


async def _get_conversation_source(conversation_id: str, user_id: str) -> ConversationSource | None:
    """Return the conversation's persisted originating source (web/whatsapp/...).

    This is the authoritative delivery-routing key: it says which channel the
    conversation belongs to, independent of the run that produced the message
    (so a scheduled/workflow run posting into a bot conversation still routes to
    that platform). Returns None on miss/error — treated as a non-bot conversation.
    """
    try:
        return await conversation_repository.get_source(conversation_id, user_id=user_id)
    except Exception as e:
        log.warning(f"{LogTag.AGENT} _get_conversation_source: lookup failed", error=str(e))
        return None


def _delivery_origin(run: ExecutorRun) -> str:
    """Name what produced this run's result, with machine ids.

    Lets a delivered message recorded in a platform thread trace back to its source.
    """
    name = f' "{run.workflow_title}"' if run.workflow_title else ""
    origin = f"workflow{name} (id {run.workflow_id})"
    if run.active_todo_id:
        origin += f", tracked todo (id {run.active_todo_id})"
    return origin
