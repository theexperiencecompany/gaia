"""The cards and records a background executor run leaves in its conversation.

What the user is told about a run goes through the outbox (run_report); this module keeps
only what the outbox does not carry: the tool cards a self-owning run streamed, the
tracked todo's own record of its run, and what woke it. Neither reads the run's session:
cards are snapshotted before signalling done, since the comms consumer has by then torn it down.
"""

from datetime import UTC, datetime
import time
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from app.agents.core.background.session import ExecutorRun
from app.constants.chat import CONVERSATION_MAX_MESSAGES
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.log_tags import LogTag
from app.constants.todos import TODO_CONVERSATION_MAX_MESSAGES
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import MessageModel, ToolDataEntry, UpdateMessagesRequest
from app.models.message_models import TodoRunWake
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import update_messages
from app.services.hil.approvals_store import get_approval
from app.services.latency_metrics import observe_delivery_persist
from app.services.outbox.transport.ws_speech import publish_conversation_message
from shared.py.wide_events import log


async def record_todo_run_report(
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
    await _broadcast_cards(run, bot_message, replaces_placeholder=True)


async def record_todo_run_wake(
    conversation_id: str, user: AuthenticatedUser, wake: TodoRunWake
) -> None:
    """Lead a tracked todo's run with what woke it, on the user's side of its chat.

    Pushed as an outbox.message so an open chat shows it live; a failed save lets the run go ahead."""
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
    await publish_conversation_message(
        user.user_id,
        conversation_id,
        {
            "type": "user",
            "response": "",
            "message_id": message.message_id,
            "date": message.date,
            "todo_run_wake": wake.model_dump(mode="json"),
        },
    )


async def persist_cancelled_run(run: ExecutorRun, tool_data: list[ToolDataEntry]) -> None:
    """Durably persist the tool cards a cancelled self-owning run already streamed.

    Writes the frontend's already-rendered placeholder cards (keyed by task_id) to
    MongoDB so they survive a cache clear and sync to other devices: no result text,
    no WebSocket re-push of already-streamed data.
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
        if e.status_code == 404:  # conversation deleted mid-run: expected, not an error
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


async def persist_run_cards(run: ExecutorRun, tool_data: list[ToolDataEntry]) -> None:
    """Keep the cards a finished self-owning run streamed, in the conversation they rendered in.

    A run resumed after an approval merges them onto the live message it continues; any
    other run saves them as a message of their own under its placeholder's id, so the client
    replaces the placeholder. The words that tell the result are not here: they come through the outbox.
    """
    if not tool_data:
        return
    if run.is_queued and run.bot_message_id:
        if await _merge_resumed_cards(run, tool_data):
            return
        log.warning(
            f"{LogTag.AGENT} Resumed run's original message is unavailable; saving its cards as a new message",
            conversation_id=run.conversation_id,
            original_message_id=run.bot_message_id,
        )
        message_id = str(uuid4())
    else:
        message_id = (run.task_id if run.is_queued else None) or str(uuid4())
    bot_message = MessageModel(
        type="bot",
        response="",
        date=datetime.now(UTC).isoformat(),
        message_id=message_id,
        tool_data=tool_data,
    )
    if await _save_message(run.conversation_id, run.user, bot_message):
        await _broadcast_cards(run, bot_message, replaces_placeholder=run.is_queued)


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
        if e.status_code == 404:  # conversation deleted mid-run: expected, not an error
            log.info(
                f"{LogTag.AGENT} conversation deleted, skipping message save",
                conversation_id=conversation_id,
            )
            return False
        log.error(f"{LogTag.AGENT} Failed to save a run's message", error=str(e))
        return False
    except Exception as e:
        log.error(f"{LogTag.AGENT} Failed to save a run's message", error=str(e))
        return False
    finally:
        observe_delivery_persist(time.perf_counter() - persist_start, op="save_bot_message")
    return True


async def _merge_resumed_cards(run: ExecutorRun, new_tool_data: list[ToolDataEntry]) -> bool:
    """Update the ORIGINAL live message's cards with a resumed run's; False when that message is gone.

    $push-based append would duplicate the message instead of merging. The client replaces the
    message wholesale on a push, so the FULL merged card set is what goes out.
    """
    user_id = run.user.user_id
    message_id = run.bot_message_id or ""
    existing = await conversation_repository.get_message(
        run.conversation_id, message_id, user_id=user_id
    )
    if existing is None:
        return False
    existing_tool_data = list(existing.tool_data or [])
    merged = await _reconcile_approval_statuses(_merge_tool_data(existing_tool_data, new_tool_data))
    # Gated on the merge changing something: a resumed run with no new cards still settles
    # approval statuses, and skipping that write left a live approve/decline prompt after refresh.
    if merged != existing_tool_data and not await conversation_repository.set_message_tool_data(
        run.conversation_id, user_id=user_id, message_id=message_id, entries=merged
    ):
        log.error(
            f"{LogTag.AGENT} Resumed run's cards matched no message, dropping them",
            conversation_id=run.conversation_id,
            message_id=message_id,
        )
        return False
    existing.tool_data = merged
    await _broadcast_cards(run, existing, replaces_placeholder=run.is_queued)
    return True


async def _broadcast_cards(
    run: ExecutorRun, message: MessageModel, *, replaces_placeholder: bool
) -> None:
    """Push a run's card message to open web/mobile clients over the WebSocket.

    replaces_placeholder: the run streamed into a placeholder keyed by its task_id, which this
    message replaces (useExecutorStream creates one only for a detached or tracked todo run).
    """
    payload: dict[str, Any] = {
        "type": "bot",
        "response": message.response,
        "message_id": message.message_id,
        "date": message.date,
        "kind": message.kind.value,
    }
    if message.error:
        payload["error"] = message.error
    if message.tool_data:
        payload["tool_data"] = message.tool_data
    if run.task_id and replaces_placeholder:
        payload["task_id"] = run.task_id
    await publish_conversation_message(run.user.user_id, run.conversation_id, payload)


# Approval statuses that outrank "pending" when the same approval_id appears
# twice in a merge (the resumed stream replays the gate-time PENDING frame even
# after the decision landed).
_SETTLED_APPROVAL_STATUSES = frozenset(
    {"approved", "denied", "timeout", "abandoned", "auto_approved"}
)


class _ApprovalFrameData(BaseModel):
    """The ``data`` keys of an ``approval_request`` tool_data entry the merge reads.

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
    stream this delivery drains: the merged frame stays "pending" forever. The
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
            entry = {**entry, "data": {**data, "status": record.status}}
        reconciled.append(entry)
    return reconciled
