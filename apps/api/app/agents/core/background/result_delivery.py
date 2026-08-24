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

from fastapi import HTTPException
from langsmith import traceable

from app.agents.core.background.comms_narrator import narrate_executor_result
from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.session import ExecutorRun
from app.agents.core.background.workflow_platform_delivery import (
    deliver_workflow_result_to_platforms,
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
from app.services.conversation_service import update_messages
from app.services.hil.approvals_store import get_approval
from app.services.platform_message_service import deliver_message_to_platform, is_bot_platform
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import get_trace_id, log, log_context


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
    except Exception as e:  # delivery is best-effort, never propagates
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
    bot_message.tool_data = tool_data

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
    tool_data: list[ToolDataEntry] | None,
    returned_note: str,
) -> tuple[str | None, str | None]:
    """Compose the user-facing message, save it, and route it.

    Returns ``(narrated_text, message_id)`` of the saved bot message, or
    ``(None, None)`` if it could not be saved.
    """
    user_id = run.user.get("user_id", "")

    # A resumed run's report can still describe its gate as pending (the task
    # spec often DEFINED done that way), so the decided statuses are injected
    # mechanically: comms must never re-offer a decision the user already made.
    approval_note = await _approval_outcomes_note(run)
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
    log.set_ns(
        "result_delivery",
        result_type=result_type,
        narrated=narrated,
        text_length=len(notification_text),
    )

    bot_message = MessageModel(
        type="bot",
        response=notification_text,
        date=datetime.now(UTC).isoformat(),
    )
    # A HIL-resumed run reconciles onto the ORIGINAL live turn's message
    # (``run.bot_message_id``, see ``_record_pause``) instead of minting a
    # rival one. Otherwise queued runs share an id with the live placeholder
    # useExecutorStream rendered, so the frontend's existing conversation sync
    # reconciles by id. Other runs have no placeholder, so a fresh id is fine.
    #
    # QUEUED is load-bearing: every LIVE run also carries ``bot_message_id``
    # (threaded for a possible pause), but only ``_record_pause`` writes it
    # into a queue item. On presence alone every live run would take the
    # merge path and race the comms stream's own save.
    is_hil_resume = run.is_queued and bool(run.bot_message_id)
    bot_message.message_id = (
        (run.bot_message_id if is_hil_resume else None)
        or (run.task_id if run.is_queued else None)
        or str(uuid4())
    )
    if tool_data:
        bot_message.tool_data = tool_data

    # Reply-quote only for genuinely queued tasks — live tasks land directly
    # after the user's last message so quoting it is visual noise; a
    # HIL-resumed run merges onto that same live message, so it never had
    # other messages land in between either.
    user_msg_content = ""
    show_reply_quote = run.is_queued and not is_hil_resume and bool(run.user_message_id)
    if show_reply_quote:
        user_msg_content = await _lookup_user_message_content(
            run.conversation_id, run.user_message_id, user_id
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

    fresh_append = not is_hil_resume
    if is_hil_resume:
        merged_tool_data = await _merge_resumed_result(run, bot_message, tool_data)
        if merged_tool_data is not None:
            tool_data = merged_tool_data
        else:
            # Original bubble gone or update matched nothing. The approved
            # action already RAN — append a fresh message rather than discard
            # its report. A deleted conversation still 404s cleanly below.
            log.warning(
                f"{LogTag.AGENT} HIL-resumed delivery: original message unavailable,"
                " appending a fresh one instead",
                conversation_id=run.conversation_id,
                original_message_id=bot_message.message_id,
            )
            bot_message.message_id = str(uuid4())
            fresh_append = True
    if fresh_append:
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
                    f"{LogTag.AGENT} conversation deleted, skipping message save",
                    conversation_id=run.conversation_id,
                )
                return None, None
            log.error(f"{LogTag.AGENT} deliver_result: failed to save message", error=str(e))
            return None, None
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
            await deliver_workflow_result_to_platforms(
                user=run.user,
                user_id=user_id,
                notification_text=notification_text,
                origin=_delivery_origin(run),
            )
        await _dispatch_workflow_notification(
            msg_type=result_type,
            workflow_id=run.workflow_id,
            workflow_title=run.workflow_title,
            conversation_id=run.conversation_id,
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
            emit_task_id=run.is_queued,
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

    # Delivery is the last step that can silently lose a finished run: the answer
    # is saved to the conversation either way, so a failed send leaves a run whose
    # outcome is "success" and whose user got nothing. Put the verdict ON the
    # executor_run wide event (not just this line) so that state is queryable.
    log.set_ns(
        "result_delivery",
        transport=transport,
        delivered=delivered,
        source=conversation_source.value if conversation_source else None,
    )
    if delivered:
        log.info(
            f"{LogTag.AGENT} deliver_result: delivered message",
            message_id=bot_message.message_id,
            task_id=run.task_id,
            conversation_id=run.conversation_id,
            conversation_source=conversation_source.value if conversation_source else None,
            transport=transport,
        )
    else:
        log.error(
            f"{LogTag.AGENT} deliver_result: result saved but NOT delivered to the user",
            message_id=bot_message.message_id,
            task_id=run.task_id,
            conversation_id=run.conversation_id,
            conversation_source=conversation_source.value if conversation_source else None,
            transport=transport,
        )
    return notification_text, bot_message.message_id


async def _merge_resumed_result(
    run: ExecutorRun,
    bot_message: MessageModel,
    new_tool_data: list[ToolDataEntry] | None,
) -> list[ToolDataEntry] | None:
    """In-place update the ORIGINAL live turn's bot message with a HIL-resumed
    run's result, instead of appending a rival one.

    ``update_messages``/``append_messages`` unconditionally ``$push``-es a new
    array element — reusing the original message_id there would create a literal
    duplicate copy of the message, not a merge (the same trap ``_persist_follow_up_actions``
    already guards against). This does targeted in-place field updates instead.

    Returns the FULL merged tool_data (original cards + this run's new cards):
    the WebSocket push replaces the client's stored message wholesale, so a
    delta alone would drop the original cards. ``None`` means the original
    message could not be found or updated — the caller falls back to
    appending a fresh message rather than discarding the result.
    """
    user_id = run.user.get("user_id", "")
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
            run.conversation_id, run.bot_message_id, user_id=run.user.get("user_id", "")
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


def _approval_id(entry: ToolDataEntry) -> str | None:
    if entry.get("tool_name") != APPROVAL_REQUEST_TOOL_NAME:
        return None
    data = entry.get("data")
    if isinstance(data, dict):
        approval_id = data.get("approval_id")
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
        return isinstance(data, dict) and data.get("status") in _SETTLED_APPROVAL_STATUSES

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
            conversation_id=conversation_id,
        )
    except Exception as e:  # follow-ups are best-effort
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
        # The conversation's session_id: without it these one-shots had no
        # sticky-routing key, landed on a random upstream per call, and never
        # chained their prompt head with the graph-path follow-ups (measured:
        # 0% cache hit on every executor-final follow-up). The aux suffix is
        # applied inside ainvoke_structured, matching the node-path calls.
        {"configurable": {"user_id": user_id, "session_id": conversation_id}},
    )


def _spawn_deferred_follow_ups(
    *,
    run: ExecutorRun,
    bot_message: MessageModel,
    result_type: str,
    tool_data: list[ToolDataEntry] | None,
    show_reply_quote: bool,
    user_msg_content: str,
) -> None:
    """Generate follow-up actions off the critical path and push them as a second
    update on the already-delivered message, so the answer isn't gated behind the
    extra LLM call."""
    spawn_background_task(
        _generate_and_push_follow_ups(
            run=run,
            bot_message=bot_message,
            result_type=result_type,
            tool_data=tool_data,
            show_reply_quote=show_reply_quote,
            user_msg_content=user_msg_content,
        )
    )


async def _generate_and_push_follow_ups(
    *,
    run: ExecutorRun,
    bot_message: MessageModel,
    result_type: str,
    tool_data: list[ToolDataEntry] | None,
    show_reply_quote: bool,
    user_msg_content: str,
) -> None:
    # Runs detached from the executor's boundary and typically finishes after
    # that event has emitted — without its own boundary, the follow-up LLM
    # call's context (and any log.error below) is silently discarded.
    async with log_context(
        "follow_up_generation",
        trace_id=get_trace_id() or None,
        conversation_id=run.conversation_id,
        task_id=run.task_id,
    ):
        user_id = run.user.get("user_id", "")
        try:
            follow_up_actions = await _build_follow_up_actions(
                msg_type=result_type,
                notification_text=bot_message.response,
                user_msg_content=user_msg_content,
                user_id=user_id,
                conversation_id=run.conversation_id,
            )
            if not follow_up_actions:
                return

            bot_message.follow_up_actions = follow_up_actions
            persisted = await _persist_follow_up_actions(
                user_id=user_id,
                conversation_id=run.conversation_id,
                message_id=bot_message.message_id,
                follow_up_actions=follow_up_actions,
            )
            if not persisted:
                # Broadcasting unpersisted suggestions would show them in the UI
                # only to vanish on reload — drop them instead.
                return
            await _broadcast_bot_message(
                user_id=user_id,
                conversation_id=run.conversation_id,
                bot_message=bot_message,
                notification_text=bot_message.response,
                tool_data=tool_data,
                follow_up_actions=follow_up_actions,
                task_id=run.task_id,
                emit_task_id=run.is_queued,
                show_reply_quote=show_reply_quote,
                user_message_id=run.user_message_id,
                user_msg_content=user_msg_content,
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

    The answer was persisted and broadcast without suggestions to unblock the UI;
    this sets them on that SAME message, matched by id. It MUST be an in-place
    field update — re-saving the whole message through ``update_messages`` (which
    ``$push``-es) would append a duplicate copy of the answer to the conversation.

    Returns ``True`` when the suggestions were written to the stored message, so
    the caller only broadcasts follow-ups that will survive a reload.
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
    workflow_id: str,
    workflow_title: str,
    conversation_id: str,
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
            conversation_id=conversation_id,
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
    tool_data: list[ToolDataEntry] | None,
    follow_up_actions: list[str],
    task_id: str | None,
    emit_task_id: bool,
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
    # Only advertise task_id when a live task_id-keyed placeholder actually
    # exists to replace (``useExecutorStream`` only creates one for queued-kind
    # dispatch — real queue pops AND HIL resumes, both prepared through
    # ``prepare_run_from_item``). A plain live run's task_id never had a
    # placeholder, so emitting it would make the client's replaceMessage(task_id)
    # target a key that doesn't match the persisted message — a wrong-key delete.
    if task_id and emit_task_id:
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
    """Name what produced this run's result, with machine ids, so a delivered
    message recorded in a platform thread can be traced back to its source."""
    name = f' "{run.workflow_title}"' if run.workflow_title else ""
    origin = f"workflow{name} (id {run.workflow_id})"
    if run.active_todo_id:
        origin += f", tracked todo (id {run.active_todo_id})"
    return origin
