"""Terminal delivery for background-executor results.

Exactly two entry points, both taking the run's ``ExecutorRun`` context:

- ``deliver_result``  — completed/errored run: narrate via comms, compose the
  bot message, persist to MongoDB, then route over EXACTLY ONE transport
  chosen by the conversation's own source (bot platform / WebSocket /
  workflow notification).
- ``persist_cancelled_run`` — cancelled run that self-owns its tool_data:
  durably persist the already-streamed cards (no narration, no re-push; the
  frontend sync reconciles by ``message_id == task_id``).

Every executor terminal path goes through one of these.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langsmith import traceable

from app.agents.core.background.comms_narrator import narrate_executor_result
from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.session import ExecutorRun
from app.agents.core.nodes.follow_up_actions_node import generate_follow_up_actions
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.db.mongodb.collections import conversations_collection
from app.models.chat_models import (
    BOT_CONVERSATION_SOURCES,
    ConversationSource,
    MessageModel,
    UpdateMessagesRequest,
)
from app.models.message_models import ReplyToMessageData
from app.services.bot_service import BotService
from app.services.conversation_service import update_messages
from app.services.outbound_delivery import publish_outbound_message
from app.services.platform_link_service import PlatformLinkService
from app.services.platform_message_service import deliver_message_to_platform, is_bot_platform
from app.utils.notification.channel_preferences import fetch_channel_preferences
from shared.py.wide_events import log


@traceable(name="bg_notification_delivery", run_type="chain")
async def deliver_result(
    run: ExecutorRun,
    result_text: str,
    result_type: str,
    returned_note: str = "",
) -> tuple[str | None, str | None]:
    """Narrate, persist, and deliver a finished executor run's result.

    Comms is invoked silently — no SSE stream. Its generated text becomes the
    user-visible bot message. The executor's terminal text is NOT shown to the
    user directly; it's internal context for comms.

    Returns ``(narrated_text, message_id)`` of the saved bot message (voice mode
    speaks the text and bubbles it by that id). ``(None, None)`` on failure.

    The message is always saved to the conversation, then delivered over EXACTLY
    ONE transport chosen by the conversation's own ``source``:
      - workflow runs → the proactive workflow notification (multi-channel)
      - bot conversations (whatsapp/telegram/discord/slack) → that platform's
        API (bots have no WebSocket — it's their only inbound path)
      - everything else (web/mobile/system) → the WebSocket push web/mobile listen on
    Routing keys on the conversation, not the run that produced the message, so a
    background/scheduled run posting into a bot conversation still reaches it.

    Tool cards: live runs have their tool_data attached to the comms ack by the
    chat stream (the comms path owns it); queued and workflow runs self-attach
    here (``run.executor_owns_tool_data``). Queued runs key the saved message on
    ``message_id == task_id`` so the frontend sync reconciles it with the live
    placeholder by id — the WebSocket push is immediacy only.
    """
    attach_tool_data = (
        drain_executor_tool_data(run.stream_id) if run.executor_owns_tool_data else None
    )
    try:
        return await _narrate_and_deliver(
            run, result_text, result_type, attach_tool_data, returned_note
        )
    except Exception as e:  # noqa: BLE001 — delivery is best-effort, never propagates
        log.error(f"{LogTag.AGENT} Background notification delivery failed", error=str(e))
        return None, None


async def persist_cancelled_run(run: ExecutorRun) -> None:
    """Durably persist the tool cards a cancelled self-owning run already streamed.

    The cards were streamed live and the frontend already rendered + persisted
    them on the placeholder (keyed by task_id). This only writes the same cards
    to MongoDB so they survive a cache clear and reach the user's other devices
    via the normal conversation sync. Deliberately:
      - keyed on ``message_id == task_id`` so sync reconciles with the placeholder
        by id (no duplicate) — no WebSocket re-push of already-streamed data;
      - no comms re-narration (the run was stopped) and no result text, mirroring
        the cards-only placeholder the user saw.
    """
    tool_data = drain_executor_tool_data(run.stream_id)
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
    bot_message.tool_data = tool_data  # type: ignore[assignment]

    try:
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=run.conversation_id,
                messages=[bot_message],
            ),
            user=run.user,
        )
    except Exception as e:  # noqa: BLE001 — best-effort save of a stopped run
        log.error(f"{LogTag.AGENT} Failed to save cancelled executor cards", error=str(e))
        return

    log.info(
        f"{LogTag.AGENT} Persisted cancelled executor cards",
        message_id=bot_message.message_id,
        task_id=run.task_id,
        stream_id=run.stream_id,
        tool_card_count=len(tool_data),
    )


async def _narrate_and_deliver(
    run: ExecutorRun,
    result_text: str,
    result_type: str,
    tool_data: list[dict[str, Any]] | None,
    returned_note: str,
) -> tuple[str | None, str | None]:
    """Compose the user-facing message, save it, and route it.

    Returns ``(narrated_text, message_id)`` of the saved bot message, or
    ``(None, None)`` if it could not be saved.
    """
    user_id = run.user.get("user_id", "")

    notification_text = await narrate_executor_result(
        result_text,
        result_type,
        run.conversation_id,
        run.user,
        returned_note=returned_note,
        workflow_id=run.workflow_id,
    )
    # If comms is unavailable, fall back to the raw executor text rather than
    # dropping the message entirely.
    if not notification_text:
        notification_text = result_text

    bot_message = MessageModel(
        type="bot",
        response=notification_text,
        date=datetime.now(UTC).isoformat(),
    )
    # Queued runs share an id with the live placeholder useExecutorStream
    # rendered — the frontend's existing conversation sync then reconciles
    # them by id (no duplicate, even if the WebSocket push below is missed).
    # Other runs have no placeholder, so a fresh id is fine.
    bot_message.message_id = (run.task_id if run.is_queued else None) or str(uuid4())
    if tool_data:
        bot_message.tool_data = tool_data  # type: ignore[assignment]

    # Reply-quote only for queued tasks — live tasks land directly after the
    # user's last message so quoting it is visual noise; queued tasks may have
    # other messages between them and the original.
    user_msg_content = ""
    show_reply_quote = run.is_queued and bool(run.user_message_id)
    if show_reply_quote:
        user_msg_content = await _lookup_user_message_content(
            run.conversation_id, run.user_message_id
        )
        bot_message.replyToMessage = ReplyToMessageData(
            id=run.user_message_id,
            content=user_msg_content,
            role="user",
        )

    # Follow-up actions are a second LLM call. The interactive web/mobile path
    # delivers the answer first and generates them in the background (see the
    # WebSocket branch) so the user-visible result is never gated behind them.
    # Workflow + bot-platform paths deliver via a single send with no spinner to
    # unblock, so they attach follow-ups inline.
    conversation_source = await _get_conversation_source(run.conversation_id, user_id)
    is_ws_path = not run.workflow_id and not is_bot_platform(conversation_source)

    if not is_ws_path:
        follow_up_actions = await _safe_inline_follow_ups(
            result_type=result_type,
            notification_text=notification_text,
            user_msg_content=user_msg_content,
            user_id=user_id,
            conversation_id=run.conversation_id,
            message_id=bot_message.message_id,
        )
        if follow_up_actions:
            bot_message.follow_up_actions = follow_up_actions

    try:
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=run.conversation_id,
                messages=[bot_message],
            ),
            user=run.user,
        )
    except Exception as e:
        log.error(f"{LogTag.AGENT} deliver_result: failed to save message", error=str(e))
        return None, None

    # Workflow run: the result was produced with no human watching, so deliver it
    # as the proactive completion notification (multi-channel, "Done with X")
    # carrying the real voiced result, instead of pushing to one conversation
    # transport. The bot message is already saved above for "View Results".
    if run.workflow_id:
        # Successful, non-silent runs are delivered into the user's real
        # messaging-platform conversations as normal bot messages (GAIA's voice,
        # no notification chrome). The in-app badge below is a web-only heads-up.
        if result_type != "error" and run.workflow_notify_on_completion:
            await _deliver_workflow_to_platforms(
                user=run.user,
                user_id=user_id,
                notification_text=notification_text,
            )
        await _dispatch_workflow_notification(
            msg_type=result_type,
            workflow_id=run.workflow_id,
            workflow_title=run.workflow_title,
            user_id=user_id,
            message_id=bot_message.message_id,
            notify_on_completion=run.workflow_notify_on_completion,
        )
        return notification_text, bot_message.message_id

    # Deliver over exactly one transport, decided by the conversation's source.
    # Bot conversations go to their platform's API; web/mobile/system go to the
    # WebSocket push. (The web conversation list excludes bot sources, so a
    # WebSocket push for a bot conversation would be dropped anyway.)
    if is_bot_platform(conversation_source):
        delivered = await deliver_message_to_platform(
            conversation_source,
            user_id,
            notification_text,
        )
        transport = "platform"
    else:
        # Broadcast the answer NOW so the spinner clears, then generate follow-up
        # actions in the background and push them as a second update on the same
        # message (reuses conversation.new_message — the client upserts by id).
        await _broadcast_bot_message(
            user_id=user_id,
            conversation_id=run.conversation_id,
            bot_message=bot_message,
            notification_text=notification_text,
            tool_data=tool_data,
            follow_up_actions=[],
            task_id=run.task_id,
            show_reply_quote=show_reply_quote,
            user_message_id=run.user_message_id,
            user_msg_content=user_msg_content,
        )
        _spawn_deferred_follow_ups(
            run=run,
            bot_message=bot_message,
            result_type=result_type,
            tool_data=tool_data,
            show_reply_quote=show_reply_quote,
            user_msg_content=user_msg_content,
        )
        delivered = True
        transport = "websocket"

    log.info(
        f"{LogTag.AGENT} deliver_result: delivered message",
        message_id=bot_message.message_id,
        task_id=run.task_id,
        conversation_id=run.conversation_id,
        conversation_source=conversation_source.value if conversation_source else None,
        transport=transport,
        delivered=delivered,
    )
    return notification_text, bot_message.message_id


async def _safe_inline_follow_ups(
    *,
    result_type: str,
    notification_text: str,
    user_msg_content: str,
    user_id: str,
    conversation_id: str,
    message_id: str,
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
            user_msg_content=user_msg_content,
            user_id=user_id,
        )
    except Exception as e:  # noqa: BLE001 — follow-ups are best-effort
        log.error(
            f"{LogTag.AGENT} deliver_result: failed to generate follow-up actions",
            error=str(e),
            conversation_id=conversation_id,
            message_id=message_id,
        )
        return []


async def _build_follow_up_actions(
    *,
    msg_type: str,
    notification_text: str,
    user_msg_content: str,
    user_id: str,
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
        {"configurable": {"user_id": user_id}},
    )


# Strong refs to in-flight deferred tasks — asyncio.create_task only holds a weak
# reference, so without this the task can be GC'd before it finishes.
_deferred_follow_up_tasks: set[asyncio.Task[None]] = set()


def _spawn_deferred_follow_ups(
    *,
    run: ExecutorRun,
    bot_message: MessageModel,
    result_type: str,
    tool_data: list[dict[str, Any]] | None,
    show_reply_quote: bool,
    user_msg_content: str,
) -> None:
    """Generate follow-up actions off the critical path and push them as a second
    update on the already-delivered message, so the answer isn't gated behind the
    extra LLM call."""
    task = asyncio.create_task(
        _generate_and_push_follow_ups(
            run=run,
            bot_message=bot_message,
            result_type=result_type,
            tool_data=tool_data,
            show_reply_quote=show_reply_quote,
            user_msg_content=user_msg_content,
        )
    )
    _deferred_follow_up_tasks.add(task)
    task.add_done_callback(_deferred_follow_up_tasks.discard)


async def _generate_and_push_follow_ups(
    *,
    run: ExecutorRun,
    bot_message: MessageModel,
    result_type: str,
    tool_data: list[dict[str, Any]] | None,
    show_reply_quote: bool,
    user_msg_content: str,
) -> None:
    user_id = run.user.get("user_id", "")
    try:
        follow_up_actions = await _build_follow_up_actions(
            msg_type=result_type,
            notification_text=bot_message.response,
            user_msg_content=user_msg_content,
            user_id=user_id,
        )
        if not follow_up_actions:
            return

        bot_message.follow_up_actions = follow_up_actions
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=run.conversation_id,
                messages=[bot_message],
            ),
            user=run.user,
        )
        await _broadcast_bot_message(
            user_id=user_id,
            conversation_id=run.conversation_id,
            bot_message=bot_message,
            notification_text=bot_message.response,
            tool_data=tool_data,
            follow_up_actions=follow_up_actions,
            task_id=run.task_id,
            show_reply_quote=show_reply_quote,
            user_message_id=run.user_message_id,
            user_msg_content=user_msg_content,
        )
    except Exception as e:
        # Non-critical enhancement — the answer is already delivered. Log loudly
        # but never let a follow-up failure crash the background task.
        log.error(f"{LogTag.AGENT} deliver_result: deferred follow-up actions failed", error=str(e))


async def _deliver_workflow_to_platforms(
    *,
    user: dict,
    user_id: str,
    notification_text: str,
) -> None:
    """Deliver a finished workflow's result into the user's preferred messaging
    platforms as real, persisted bot messages, split into natural bubbles.

    Only platforms the user has linked AND left enabled in their notification
    channel preferences receive it. This is what makes a workflow result appear
    inline in the user's actual Telegram/WhatsApp/etc. chat (GAIA's voice, no
    notification chrome) so the thread can be continued there, alongside the
    workflow's own conversation. Best-effort: a single platform failing never
    blocks the others or propagates to the caller.
    """
    if not notification_text.strip():
        return

    targets = await _preferred_bot_platforms(user_id)
    if not targets:
        return

    # Comms splits its reply into bubbles with the break sentinel;
    # publish_outbound_message strips blanks and sends them as one ordered message.
    bubbles = notification_text.split(NEW_MESSAGE_BREAKER)
    for source, platform_user_id in targets:
        await _post_workflow_message(
            user=user,
            user_id=user_id,
            source=source,
            platform_user_id=platform_user_id,
            response=notification_text,
            bubbles=bubbles,
        )


async def _preferred_bot_platforms(user_id: str) -> list[tuple[ConversationSource, str]]:
    """Resolve which messaging platforms a workflow result should reach: those the
    user has linked AND left enabled in their notification channel preferences."""
    try:
        linked = await PlatformLinkService.get_linked_platforms(user_id)
        prefs = await fetch_channel_preferences(user_id)
    except Exception as e:  # noqa: BLE001 — proactive side channel, never fatal
        log.error(f"{LogTag.AGENT} workflow platform delivery: target lookup failed", error=str(e))
        return []

    targets: list[tuple[ConversationSource, str]] = []
    for platform_value, info in linked.items():
        source = ConversationSource.coerce(platform_value)
        if source is None or source not in BOT_CONVERSATION_SOURCES:
            continue
        if not prefs.get(platform_value, True):
            continue  # channel disabled in the user's notification preferences
        platform_user_id = info.get("platformUserId")
        if platform_user_id:
            targets.append((source, str(platform_user_id)))
    return targets


async def _post_workflow_message(
    *,
    user: dict,
    user_id: str,
    source: ConversationSource,
    platform_user_id: str,
    response: str,
    bubbles: list[str],
) -> None:
    """Persist the result into the platform's session conversation and deliver it
    as ordered bubbles. Best-effort: logs and swallows any single-platform failure."""
    try:
        conversation_id = await BotService.get_or_create_session(
            platform=source.value,
            platform_user_id=platform_user_id,
            channel_id=None,
            user=user,
        )
        bot_message = MessageModel(
            type="bot",
            response=response,
            date=datetime.now(UTC).isoformat(),
        )
        bot_message.message_id = str(uuid4())
        await update_messages(
            UpdateMessagesRequest(conversation_id=conversation_id, messages=[bot_message]),
            user=user,
        )
        result = await publish_outbound_message(source, user_id, bubbles)
        log.info(
            f"{LogTag.AGENT} workflow result delivered to platform",
            platform=source.value,
            conversation_id=conversation_id,
            message_id=bot_message.message_id,
            bubbles=len([b for b in bubbles if b.strip()]),
            result=result.value,
        )
    except Exception as e:  # noqa: BLE001 — best-effort per platform
        log.error(
            f"{LogTag.AGENT} workflow platform delivery failed",
            platform=source.value,
            error=str(e),
        )


async def _dispatch_workflow_notification(
    *,
    msg_type: str,
    workflow_id: str,
    workflow_title: str,
    user_id: str,
    message_id: str,
    notify_on_completion: bool = True,
) -> None:
    """Send the proactive workflow completion/failure notification.

    Failures always notify — the user must learn their automation broke. The
    success notification respects the workflow's ``notify_on_completion``
    setting: silent workflows keep their result in the conversation and leave
    any user-facing alerting to the agent's own send_notification calls (driven
    by the workflow's instructions).
    """
    # Imported here to avoid the workflow-service → agent import cycle.
    from app.services.workflow.notifications import (
        send_workflow_completion_notification,
        send_workflow_failure_notification,
    )

    if msg_type == "error":
        await send_workflow_failure_notification(
            workflow_id=workflow_id,
            workflow_title=workflow_title,
            user_id=user_id,
        )
    elif not notify_on_completion:
        log.info(
            f"{LogTag.AGENT} deliver_result: completion notification skipped (workflow is silent)",
            workflow_id=workflow_id,
            message_id=message_id,
        )
        return
    else:
        await send_workflow_completion_notification(
            workflow_id=workflow_id,
            workflow_title=workflow_title,
            user_id=user_id,
        )
    log.info(
        f"{LogTag.AGENT} deliver_result: workflow notification dispatched",
        workflow_id=workflow_id,
        message_id=message_id,
    )


async def _broadcast_bot_message(
    *,
    user_id: str,
    conversation_id: str,
    bot_message: MessageModel,
    notification_text: str,
    tool_data: list[dict[str, Any]] | None,
    follow_up_actions: list[str],
    task_id: str | None,
    show_reply_quote: bool,
    user_message_id: str | None,
    user_msg_content: str,
) -> None:
    """Push the bot message to web/mobile/system clients over the WebSocket."""
    ws_payload: dict[str, Any] = {
        "type": "bot",
        "response": notification_text,
        "message_id": bot_message.message_id,
        "date": bot_message.date,
    }
    if tool_data:
        ws_payload["tool_data"] = tool_data
    if follow_up_actions:
        ws_payload["follow_up_actions"] = follow_up_actions
    # Only advertise task_id when the saved message is actually keyed on it
    # (queued runs set message_id == task_id). For live runs message_id is a
    # fresh uuid, so emitting task_id would make the client's
    # replaceMessage(task_id) target a key that doesn't match the persisted
    # message — a latent wrong-key delete.
    if task_id and bot_message.message_id == task_id:
        ws_payload["task_id"] = task_id
    if show_reply_quote:
        ws_payload["replyToMessage"] = {
            "id": user_message_id,
            "content": user_msg_content,
            "role": "user",
        }
    await _broadcast_message(
        user_id,
        {
            "type": "conversation.new_message",
            "conversation_id": conversation_id,
            "message": ws_payload,
        },
    )


async def _broadcast_message(user_id: str, ws_event: dict[str, Any]) -> None:
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
                await asyncio.sleep(0.5)


async def _lookup_user_message_content(
    conversation_id: str,
    user_message_id: str | None,
) -> str:
    """Look up the first 150 chars of a user message for reply-to preview."""
    try:
        conv_doc = await conversations_collection.find_one(
            {
                "conversation_id": conversation_id,
                "messages.message_id": user_message_id,
            },
            {"messages.$": 1},
        )
        if conv_doc and conv_doc.get("messages"):
            return conv_doc["messages"][0].get("response", "")[:150]
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
        doc = await conversations_collection.find_one(
            {"conversation_id": conversation_id, "user_id": user_id},
            {"source": 1},
        )
    except Exception as e:
        log.warning(f"{LogTag.AGENT} _get_conversation_source: lookup failed", error=str(e))
        return None
    return ConversationSource.coerce(doc.get("source")) if doc else None
