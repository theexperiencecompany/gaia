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
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from app.constants.log_tags import LogTag
from app.constants.websocket import WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS
from app.core.websocket_manager import websocket_manager
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import (
    ConversationSource,
    MessageModel,
    ToolDataEntry,
    UpdateMessagesRequest,
)
from app.models.conversation_log_models import Notice
from app.models.conversation_models import ConversationEntry
from app.models.hil_models import HILApprovalStatus
from app.models.user_models import AuthenticatedUser
from app.services.conversation.log import accept
from app.services.conversation.runtime import runtime_ports
from app.services.conversation_service import update_messages
from app.services.latency_metrics import observe_delivery_persist
from app.services.platform_message_service import (
    deliver_message_to_platform,
    is_bot_platform,
)
from shared.py.wide_events import log


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
    logs it as a Notice so the conversation's next reply knows it was sent. Takes no run and does
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

    saved = await _save_message(conversation_id, user, bot_message)
    if saved is None:
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
            bot_message=saved,
            notification_text=text,
            tool_data=cards,
        )
        delivered = True
        transport = "websocket"

    # Logged only once actually delivered, so the conversation's next reply knows it was sent.
    if delivered:
        notice = Notice(id=f"notice:{bot_message.message_id}", text=text, origin=origin)
        await accept(runtime_ports(), conversation_id, user_id, notice)

    _log_delivery_verdict(
        target=target,
        message_id=bot_message.message_id,
        conversation_source=source,
        transport=transport,
        delivered=delivered,
    )
    return source if delivered else None


async def _save_message(
    conversation_id: str,
    user: AuthenticatedUser,
    message: MessageModel,
) -> ConversationEntry | None:
    """Append the message to the conversation, returning it at its seq; None when it wasn't saved."""
    persist_start = time.perf_counter()
    try:
        saved = await update_messages(
            UpdateMessagesRequest(
                conversation_id=conversation_id,
                messages=[message],
            ),
            user=user,
        )
    except HTTPException as e:
        if e.status_code == 404:  # conversation deleted mid-run — expected, not an error
            log.info(
                f"{LogTag.AGENT} conversation deleted, skipping message save",
                conversation_id=conversation_id,
            )
            return None
        log.error(f"{LogTag.AGENT} deliver_result: failed to save message", error=str(e))
        return None
    except Exception as e:
        log.error(f"{LogTag.AGENT} deliver_result: failed to save message", error=str(e))
        return None
    finally:
        observe_delivery_persist(time.perf_counter() - persist_start, op="save_bot_message")
    return ConversationEntry.committed(message, saved.message_seqs[0])


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


# Approval statuses that outrank "pending" when the same approval_id appears
# twice in a merge (the resumed stream replays the gate-time PENDING frame even
# after the decision landed).
_SETTLED_APPROVAL_STATUSES = frozenset(
    {"approved", "denied", "timeout", "abandoned", "auto_approved"}
)


_APPROVAL_OUTCOME_PHRASES: dict[HILApprovalStatus, str] = {
    HILApprovalStatus.APPROVED: "approved by the user; the action ran",
    HILApprovalStatus.AUTO_APPROVED: "auto-approved; the action ran",
    HILApprovalStatus.DENIED: "denied by the user; the action did NOT run",
    HILApprovalStatus.TIMEOUT: "expired with no decision; the action did NOT run",
    HILApprovalStatus.ABANDONED: "abandoned; the action did NOT run",
}


class _ApprovalFrameData(BaseModel):
    """The ``data`` keys of an ``approval_request`` tool_data entry delivery reads.

    ``object``: the frame is emitter-owned JSON, so the readers below keep their
    own guards instead of letting validation reject a malformed card.
    """

    model_config = ConfigDict(extra="ignore")

    approval_id: object = None
    status: object = None


async def _broadcast_bot_message(
    *,
    target: _DeliveryTarget,
    bot_message: ConversationEntry,
    notification_text: str,
    tool_data: list[ToolDataEntry] | None,
    follow_up_actions: list[str] | None = None,
) -> None:
    """Push the bot message, at its seq, to web/mobile/system clients over the WebSocket."""
    ws_payload: dict[str, Any] = {
        "type": "bot",
        "response": notification_text,
        "message_id": bot_message.message_id,
        "seq": bot_message.seq,
        "date": bot_message.date,
    }
    if bot_message.error:
        ws_payload["error"] = bot_message.error
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
