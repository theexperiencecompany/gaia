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
from langsmith import traceable
from pydantic import BaseModel, ConfigDict

from app.agents.core.background.comms_narrator import (
    narrate_executor_result,
    record_platform_delivery,
)
from app.agents.core.background.session import ExecutorRun
from app.agents.core.background.workflow_platform_delivery import (
    deliver_result_to_platforms,
)
from app.agents.core.nodes.follow_up_actions_node import generate_follow_up_actions
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import (
    ConversationSource,
    MessageModel,
    ToolDataEntry,
    UpdateMessagesRequest,
)
from app.models.hil_models import HILApprovalStatus
from app.models.message_models import ReplyToMessageData
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import update_messages
from app.services.hil.approvals_store import get_approval
from app.services.latency_metrics import observe_delivery_narration, observe_delivery_persist
from app.services.platform_message_service import deliver_message_to_platform, is_bot_platform
from app.utils.background_tasks import spawn_background_task
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
    show_reply_quote: bool
    user_message_id: str | None
    user_msg_content: str


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
) -> tuple[str | None, str | None]:
    """Narrate, persist, and deliver a finished executor run's result.

    Comms is invoked silently; its text becomes the user-visible message, never the executor's
    terminal text. Returns (narrated_text, message_id), or (None, None) on failure. Delivers
    over EXACTLY ONE transport chosen by the conversation's source, not the run. tool_data is
    None for a live run, whose cards the chat stream attaches — passing them here doubles them.
    """
    try:
        return await _narrate_and_deliver(run, result_text, result_type, tool_data, returned_note)
    except Exception as e:  # delivery is best-effort, never propagates
        log.error(f"{LogTag.AGENT} Background notification delivery failed", error=str(e))
        return None, None


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
) -> ConversationSource | None:
    """Deliver an already-voiced proactive message into one existing conversation.

    Routes over the conversation's own transport (bot platform or WebSocket), then
    appends to the checkpoint so a later turn remembers it. Unlike deliver_result,
    takes no run and doesn't narrate — text is already the user-facing message.
    Best-effort: never raises. Returns the conversation's source, or None.
    """
    if not text.strip():
        return None
    user_id = user.user_id
    bot_message = MessageModel(type="bot", response=text, date=datetime.now(UTC).isoformat())
    bot_message.message_id = str(uuid4())

    if not await _save_bot_message(conversation_id, user, bot_message):
        return None

    source = await _get_conversation_source(conversation_id, user_id)
    target = _DeliveryTarget(
        user_id=user_id,
        conversation_id=conversation_id,
        task_id=None,
        emit_task_id=False,
        show_reply_quote=False,
        user_message_id=None,
        user_msg_content="",
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
            tool_data=None,
            follow_up_actions=[],
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

    notification_text = await _narrate_result(run, result_text, result_type, returned_note)

    # A HIL-resumed run reconciles onto the ORIGINAL message (run.bot_message_id,
    # see _record_pause) instead of minting a rival one. QUEUED is load-bearing:
    # every live run also carries bot_message_id, so presence alone would race the comms stream's save.
    is_hil_resume = run.is_queued and bool(run.bot_message_id)
    bot_message = _build_bot_message(run, notification_text, tool_data, is_hil_resume=is_hil_resume)

    show_reply_quote, user_msg_content = await _attach_reply_quote(
        run, bot_message, is_hil_resume=is_hil_resume
    )
    target = _DeliveryTarget(
        user_id=user_id,
        conversation_id=run.conversation_id,
        task_id=run.task_id,
        emit_task_id=run.is_queued,
        show_reply_quote=show_reply_quote,
        user_message_id=run.user_message_id,
        user_msg_content=user_msg_content,
    )

    # Follow-ups are a second LLM call. The web/mobile path delivers the answer
    # first and generates them in the background so the result isn't gated on
    # them; workflow/bot-platform paths have no spinner to unblock, so attach inline.
    conversation_source = await _get_conversation_source(run.conversation_id, user_id)
    is_ws_path = not run.workflow_id and not is_bot_platform(conversation_source)

    if not is_ws_path:
        follow_up_actions = await _safe_inline_follow_ups(
            result_type=result_type,
            notification_text=notification_text,
            target=target,
            message_id=bot_message.message_id,
        )
        if follow_up_actions:
            bot_message.follow_up_actions = follow_up_actions

    fresh_append, tool_data = await _resolve_append_mode(
        run, bot_message, tool_data, is_hil_resume=is_hil_resume
    )
    if fresh_append and not await _save_bot_message(run.conversation_id, run.user, bot_message):
        return None, None

    # Workflow run: no human is watching, so deliver as the proactive completion
    # notification (multi-channel, "Done with X") instead of one conversation
    # transport. Bot message is already saved above for "View Results".
    if run.workflow_id:
        # Successful, non-silent runs are delivered into the user's real
        # messaging-platform conversations as normal bot messages (GAIA's voice,
        # no notification chrome). The in-app badge below is a web-only heads-up.
        if result_type != "error" and run.workflow_notify_on_completion:
            await deliver_result_to_platforms(
                user=run.user,
                user_id=user_id,
                notification_text=notification_text,
                origin=_delivery_origin(run),
            )
        await _dispatch_workflow_notification(
            msg_type=result_type,
            workflow=_WorkflowRef(
                workflow_id=run.workflow_id,
                workflow_title=run.workflow_title,
                notify_on_completion=run.workflow_notify_on_completion,
            ),
            target=target,
            message_id=bot_message.message_id,
        )
        return notification_text, bot_message.message_id

    # Deliver over exactly one transport, by the conversation's source: bot
    # conversations to their platform API, web/mobile/system to WebSocket (the
    # web list excludes bot sources, so a WebSocket push there would be dropped).
    if is_bot_platform(conversation_source):
        delivered = await deliver_message_to_platform(
            conversation_source,
            user_id,
            notification_text,
            conversation_id=run.conversation_id,
        )
        transport = "platform"
    else:
        # Broadcast the answer NOW so the spinner clears, then generate follow-up
        # actions in the background and push them as a second update on the same
        # message (reuses conversation.new_message — the client upserts by id).
        await _broadcast_bot_message(
            target=target,
            bot_message=bot_message,
            notification_text=notification_text,
            tool_data=tool_data,
            follow_up_actions=[],
        )
        _spawn_deferred_follow_ups(
            bot_message=bot_message,
            result_type=result_type,
            tool_data=tool_data,
            target=target,
        )
        delivered = True
        transport = "websocket"

    _log_delivery_verdict(
        target=target,
        message_id=bot_message.message_id,
        conversation_source=conversation_source,
        transport=transport,
        delivered=delivered,
    )
    return notification_text, bot_message.message_id


async def _narrate_result(
    run: ExecutorRun,
    result_text: str,
    result_type: str,
    returned_note: str,
) -> str:
    """Re-voice the executor's terminal text through comms, falling back to it."""
    # A resumed run's report can still describe its gate as pending (the task
    # spec often DEFINED done that way), so the decided statuses are injected
    # mechanically: comms must never re-offer a decision the user already made.
    approval_note = await _approval_outcomes_note(run)
    narration_start = time.perf_counter()
    notification_text = await narrate_executor_result(
        result_text + approval_note,
        result_type,
        run.conversation_id,
        run.user,
        returned_note=returned_note,
        workflow_id=run.workflow_id,
    )
    # If comms is unavailable, fall back to the raw executor text rather than
    # dropping the message entirely.
    narrated = bool(notification_text)
    if not narrated:
        notification_text = result_text
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
    is_hil_resume: bool,
) -> MessageModel:
    """Build the bot message this run's result is saved and delivered as."""
    bot_message = MessageModel(
        type="bot",
        response=notification_text,
        date=datetime.now(UTC).isoformat(),
    )
    bot_message.message_id = (
        (run.bot_message_id if is_hil_resume else None)
        or (run.task_id if run.is_queued else None)
        or str(uuid4())
    )
    if tool_data:
        bot_message.tool_data = tool_data
    return bot_message


async def _attach_reply_quote(
    run: ExecutorRun,
    bot_message: MessageModel,
    *,
    is_hil_resume: bool,
) -> tuple[bool, str]:
    """Quote the user's message on the bot message; returns (shown, content)."""
    # Reply-quote only for genuinely queued tasks — live tasks land directly
    # after the user's last message (quoting would be noise), and a HIL-resumed
    # run merges onto that same live message, so it never had messages land between.
    user_msg_content = ""
    show_reply_quote = run.is_queued and not is_hil_resume and bool(run.user_message_id)
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


async def _resolve_append_mode(
    run: ExecutorRun,
    bot_message: MessageModel,
    tool_data: list[ToolDataEntry] | None,
    *,
    is_hil_resume: bool,
) -> tuple[bool, list[ToolDataEntry] | None]:
    """Merge a HIL-resumed result onto the original message where possible.

    Returns (fresh_append, tool_data) — fresh_append False only when the
    merge landed, in which case tool_data is the FULL merged card set.
    """
    if not is_hil_resume:
        return True, tool_data
    merged_tool_data = await _merge_resumed_result(run, bot_message, tool_data)
    if merged_tool_data is not None:
        return False, merged_tool_data
    # Original bubble gone or update matched nothing. The approved action
    # already RAN — append a fresh message rather than discard its report. A
    # deleted conversation still 404s cleanly in the save.
    log.warning(
        f"{LogTag.AGENT} HIL-resumed delivery: original message unavailable,"
        " appending a fresh one instead",
        conversation_id=run.conversation_id,
        original_message_id=bot_message.message_id,
    )
    bot_message.message_id = str(uuid4())
    return True, tool_data


async def _save_bot_message(
    conversation_id: str, user: AuthenticatedUser, bot_message: MessageModel
) -> bool:
    """Append the bot message to the conversation; False when it wasn't saved."""
    persist_start = time.perf_counter()
    try:
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=conversation_id,
                messages=[bot_message],
            ),
            user=user,
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


async def _merge_resumed_result(
    run: ExecutorRun,
    bot_message: MessageModel,
    new_tool_data: list[ToolDataEntry] | None,
) -> list[ToolDataEntry] | None:
    """In-place update the ORIGINAL live message with a HIL-resumed run's result.

    $push-based append would duplicate the message instead of merging (the trap
    _persist_follow_up_actions also guards against). Returns the FULL merged
    tool_data, since the WebSocket push replaces the client's message wholesale.
    """
    user_id = run.user.user_id
    message_id = bot_message.message_id
    existing = await conversation_repository.get_message(
        run.conversation_id, message_id, user_id=user_id
    )
    if existing is None:
        log.error(
            f"{LogTag.AGENT} HIL-resumed delivery: original message not found, dropping result",
            conversation_id=run.conversation_id,
            message_id=message_id,
        )
        return None

    if not await conversation_repository.set_message_response(
        run.conversation_id, user_id=user_id, message_id=message_id, response=bot_message.response
    ):
        log.error(
            f"{LogTag.AGENT} HIL-resumed delivery: response update matched no message",
            conversation_id=run.conversation_id,
            message_id=message_id,
        )
        return None

    existing_tool_data = list(existing.tool_data or [])
    merged = await _reconcile_approval_statuses(
        _merge_tool_data(existing_tool_data, list(new_tool_data or []))
    )
    # Gate on the merge changing something, not on new cards: a resumed run
    # with no cards still settles approval statuses, and skipping that write
    # left a live approve/decline prompt after refresh.
    if merged != existing_tool_data and not await conversation_repository.set_message_tool_data(
        run.conversation_id, user_id=user_id, message_id=message_id, entries=merged
    ):
        log.error(
            f"{LogTag.AGENT} HIL-resumed delivery: tool_data attach matched no message, dropping"
            " cards",
            conversation_id=run.conversation_id,
            message_id=message_id,
        )
        merged = existing_tool_data

    if bot_message.follow_up_actions:
        await conversation_repository.set_message_follow_up_actions(
            run.conversation_id,
            user_id=user_id,
            message_id=message_id,
            actions=bot_message.follow_up_actions,
        )

    return merged


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


async def _approval_outcomes_note(run: ExecutorRun) -> str:
    """Ground-truth note listing this run's decided approval gates, or ""."""
    if not run.bot_message_id:
        return ""
    try:
        message = await conversation_repository.get_message(
            run.conversation_id, run.bot_message_id, user_id=run.user.user_id
        )
    except Exception as e:
        log.warning(f"{LogTag.AGENT} _approval_outcomes_note: message lookup failed", error=str(e))
        return ""
    if message is None or not message.tool_data:
        return ""
    lines: list[str] = []
    for entry in message.tool_data:
        approval_id = _approval_id(entry)
        if approval_id is None:
            continue
        record = await get_approval(approval_id)
        if record is None or record.status not in _APPROVAL_OUTCOME_PHRASES:
            continue
        lines.append(f"- {record.tool_name}: {_APPROVAL_OUTCOME_PHRASES[record.status]}")
    if not lines:
        return ""
    return (
        "\n\n[APPROVAL OUTCOMES] Final, decided by the user; this overrides anything above "
        "that says an action is waiting for approval. Report each action by its outcome; "
        "never say it is pending and never re-offer approve/decline.\n" + "\n".join(lines)
    )


class _ApprovalFrameData(BaseModel):
    """The ``data`` keys of an ``approval_request`` tool_data entry delivery reads.

    ``object``: the frame is emitter-owned JSON, so the readers below keep their
    own guards instead of letting validation reject a malformed card.
    """

    model_config = ConfigDict(extra="ignore")

    approval_id: object = None
    status: object = None


def _approval_id(entry: ToolDataEntry) -> str | None:
    if entry.get("tool_name") != APPROVAL_REQUEST_TOOL_NAME:
        return None
    data = entry.get("data")
    if isinstance(data, dict):
        approval_id = _ApprovalFrameData.model_validate(data).approval_id
        return approval_id if isinstance(approval_id, str) else None
    return None


def _merge_tool_data(
    existing: list[ToolDataEntry], new: list[ToolDataEntry]
) -> list[ToolDataEntry]:
    """Append a resumed run's cards, upserting approval frames by approval_id.

    A blind append kept the replayed gate-time PENDING approval frame alongside
    its settled twin, resurrecting an already-decided card. Settled always wins;
    pending never overwrites settled.
    """

    def _is_settled(entry: ToolDataEntry) -> bool:
        data = entry.get("data")
        return (
            isinstance(data, dict)
            and _ApprovalFrameData.model_validate(data).status in _SETTLED_APPROVAL_STATUSES
        )

    merged = list(existing)
    index_by_approval = {
        approval_id: i for i, entry in enumerate(merged) if (approval_id := _approval_id(entry))
    }
    for entry in new:
        approval_id = _approval_id(entry)
        if approval_id is None or approval_id not in index_by_approval:
            merged.append(entry)
            if approval_id is not None:
                index_by_approval[approval_id] = len(merged) - 1
            continue
        i = index_by_approval[approval_id]
        if _is_settled(merged[i]) and not _is_settled(entry):
            continue  # pending replay never downgrades a settled decision
        merged[i] = entry
    return merged


async def _reconcile_approval_statuses(entries: list[ToolDataEntry]) -> list[ToolDataEntry]:
    """Stamp every approval entry with its record's authoritative status.

    A decision's resolved frame is published to whichever stream the user is
    watching at that moment, so an earlier gate's resolution never reaches the
    stream this delivery drains — the merged frame stays "pending" forever. The
    hil_approvals record is the single source of truth; read it.
    """
    reconciled: list[ToolDataEntry] = []
    entry: ToolDataEntry
    for entry in entries:
        approval_id = _approval_id(entry)
        data = entry.get("data")
        if approval_id is None or not isinstance(data, dict):
            reconciled.append(entry)
            continue
        record = await get_approval(approval_id)
        if record is not None:
            # Restamp unconditionally. Comparing against the current status
            # first only skipped a dict copy when they already matched, and no
            # caller can tell the two apart.
            entry = {**entry, "data": {**data, "status": record.status}}
        reconciled.append(entry)
    return reconciled


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
    follow_up_actions: list[str],
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
                await asyncio.sleep(0.5)


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
