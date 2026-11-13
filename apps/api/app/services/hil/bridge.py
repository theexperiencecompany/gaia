"""Surface an approval request to the user's clients.

Nothing here waits or decides. This module only *publishes*: it pushes the
approval_request tool_data card onto the turn's SSE stream, holds a live run's
cards until the run ends, and wakes clients that aren't watching it. Decisions
are applied by app/services/hil/ledger_decide.py.

Frame delivery mirrors make_redis_stream_writer: every frame is both published
to the replayable stream event log (live + reload) AND appended to the stream
session's tool-event collector so the executor drain path persists it. The gate
only fires inside the detached executor/subagent (comms holds no gated tools),
where get_stream_writer is unavailable — so this dual write, keyed purely by
stream_id, is what makes the card work at every nesting depth.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any, Protocol, TypedDict, cast

from pydantic import TypeAdapter

from app.agents.core.background.session import RunKind, get_session
from app.constants.hil import (
    APPROVAL_REQUEST_TOOL_NAME,
    APPROVAL_TOOL_CATEGORY,
    HIL_CLASSIFIER_MAX_ARG_CHARS,
    HIL_CLASSIFIER_MAX_ARGS,
    HIL_CLASSIFIER_MAX_DETAIL_CHARS,
)
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.conversations import conversation_repository
from app.models.hil_models import (
    ApprovalDescription,
    ApprovalLedgerDocument,
    LedgerState,
)
from app.models.stream_events import (
    ApprovalRequestEntry,
    PendingApprovalCardData,
    SettledApprovalCardData,
    SettledApprovalStatus,
)
from app.services.analytics_service import capture
from app.services.hil.describe import describe_call
from app.services.hil.notify import notify_approval_pending
from app.services.hil.policy import asks_every_time
from app.services.hil.utils import GatedCall
from app.utils.general_utils import clip_text
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import HilCardShown
from shared.py.wide_events import log, spawn_logged_task


class _SessionFrame(TypedDict, total=False):
    """A session.tool_events frame as read here; other writers share the list, so values are unchecked."""

    tool_data: object
    _held_approval: object


class _FrameToolData(TypedDict, total=False):
    tool_name: object
    data: object


class _ApprovalFrameData(TypedDict, total=False):
    """An approval_request frame's data object, mutated in place when its card settles."""

    approval_id: object
    status: str
    feedback: str
    expires_at: object


@dataclass(frozen=True)
class GatedApproval:
    """Identity of a gated call being surfaced — shared by request and receipt."""

    approval_id: str
    stream_id: str
    user_id: str
    conversation_id: str
    tool_call: GatedCall
    description: ApprovalDescription
    integration_name: str | None

    @property
    def summary(self) -> str:
        """The one-line form of the description, for the model and notifications."""
        return self.description.headline


class ApprovalCard(Protocol):
    """What an approval card renders, the slice of GatedApproval the entry reads."""

    @property
    def approval_id(self) -> str: ...
    @property
    def tool_call(self) -> GatedCall: ...
    @property
    def description(self) -> ApprovalDescription: ...
    @property
    def integration_name(self) -> str | None: ...


@dataclass(frozen=True)
class SettledApprovalCard:
    """A decided call's card, rebuilt from its persisted record to redraw it settled."""

    approval_id: str
    tool_call: GatedCall
    description: ApprovalDescription
    integration_name: str | None


async def publish_ledger_request(
    approval: GatedApproval,
    *,
    asked_at: datetime,
    auto_reason: str | None = None,
    live: bool = True,
    owner_run_type: str = "",
    owner_id: str = "",
) -> None:
    """Surface a ledger PENDING card exactly once per registration.

    On a live run the card is HELD (recorded on the session for the
    end-of-run drain, no SSE until then); background runs publish immediately,
    nobody being there to watch the stream.
    """
    stream_id = approval.stream_id
    log.set(
        hil={
            "approval_id": approval.approval_id,
            "tool": approval.tool_call.name,
            "stream_id": stream_id,
        }
    )
    entry = _entry(
        await _pending_data(approval, auto_reason=auto_reason, asked_at=asked_at, ledger_version=0)
    )
    # Server-owned funnel event: exactly once per registration, held or
    # streamed — the card exists either way. Explicit user_id: bridge paths
    # carry no request context to attribute from.
    capture(
        UserId(approval.user_id),
        HilCardShown(
            approval_id=approval.approval_id,
            tool_name=approval.tool_call.name,
            ledger_version=0,
            background=not live,
        ),
    )
    session = get_session(stream_id)
    held = live and session is not None and session.kind is RunKind.LIVE
    if owner_run_type and owner_id:
        # Background owner parked here: surface its conversation in the
        # sidebar while the approval lives (hidden otherwise).
        await conversation_repository.mark_background_with_live_approval(
            approval.conversation_id, user_id=approval.user_id
        )
    if not held:
        # Background, detached-queued, and session-less runs publish immediately:
        # nobody is watching this stream (or there is none to drain), so holding
        # would hide the card until a drain that never comes.
        await _publish_entry(stream_id, entry)
        _schedule_pending_notification(
            approval.user_id, approval.conversation_id, approval.approval_id, approval.summary
        )
        return
    frame = {"tool_data": entry.model_dump(mode="json"), "_held_approval": True}
    session.tool_events.append(frame)


async def sync_conversation_approval_flag(conversation_id: str, user_id: str) -> None:
    """Rewrite one conversation's sidebar flag from its pending ledger rows.

    Called wherever a row leaves the pending set (decide, revoke, cancel,
    reconcile): the flag follows the ledger, never leads it. Pending-only, since
    the flag tracks "needs the user" and a decided approval needs nothing.
    Best-effort — a stale flag only mislists a conversation, never misdecides.
    """
    try:
        rows = await approval_ledger_repository.list_open(conversation_id)
        live = any(row.user_id == user_id and row.state is LedgerState.PENDING for row in rows)
        await conversation_repository.refresh_live_approval_flag(
            conversation_id, user_id=user_id, live=live
        )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} approval-flag sync failed",
            conversation_id=conversation_id,
            error=str(e),
            error_type=type(e).__name__,
        )


def build_action_detail(summary: str, args: Mapping[str, object]) -> str:
    """Richer rendering of a gated call for the conversational classifier.

    Adds every argument up to a bound (non-scalars as compact JSON) so the
    classifier sees content the one-line summary omits. Capped by
    HIL_CLASSIFIER_MAX_DETAIL_CHARS; the per-value clip stops one pathological
    arg from eating the whole budget. No LLM here.
    """
    lines = [summary]
    arg_lines = []
    for key, value in list((args or {}).items())[:HIL_CLASSIFIER_MAX_ARGS]:
        rendered = (
            value if isinstance(value, (str, int, float, bool)) else json.dumps(value, default=str)
        )
        arg_lines.append(f"  {key}: {clip_text(str(rendered), HIL_CLASSIFIER_MAX_ARG_CHARS)}")
    if arg_lines:
        lines.append("Arguments:")
        lines.extend(arg_lines)
    return clip_text("\n".join(lines), HIL_CLASSIFIER_MAX_DETAIL_CHARS)


# --- internals -----------------------------------------------------------------


def _schedule_pending_notification(
    user_id: str, conversation_id: str, approval_id: str, summary: str
) -> None:
    """Wake clients not watching the stream.

    Detached, since a notify failure must never block the gate.
    """
    spawn_logged_task(
        "approval_pending_notification",
        notify_approval_pending(user_id, conversation_id, approval_id, summary),
        user={"id": user_id},
        conversation_id=conversation_id,
        approval_id=approval_id,
    )


async def _publish_entry(stream_id: str, entry: ApprovalRequestEntry) -> None:
    """Deliver a frame live (replayable event log) AND record it for persistence.

    The session append mirrors make_redis_stream_writer so the executor
    drain path persists the card; the SSE publish reaches live/reloaded clients.
    Both carry the same plain-dict frame the rest of the tool_data pipeline
    (stream_utils, the bot bridge, the frontend parser) reads.
    """
    frame = {"tool_data": entry.model_dump(mode="json")}
    await stream_manager.publish_chunk(stream_id, f"data: {json.dumps(frame)}\n\n")
    session = get_session(stream_id)
    if session is not None:
        session.tool_events.append(frame)


def settle_session_approval_frame(
    stream_id: str,
    approval_id: str,
    status: str,
    feedback: str | None = None,
    *,
    drop_if_unpublished: bool = False,
) -> bool:
    """Flip an already-recorded card frame to its terminal status, in place.

    Mutating in place keeps the drain upsert a no-op safety net, not a path that
    resurrects a settled card from a stale PENDING frame. With drop_if_unpublished
    a still-held frame is removed instead (the user never saw it, so there is
    nothing to tombstone). Returns whether a frame was settled or dropped.
    """
    try:
        session = get_session(stream_id)
        if session is None:
            return False
        settled = False
        kept: list[dict[str, Any]] = []
        for event in session.tool_events:
            tool_data: _FrameToolData | None = _frame_tool_data(event)
            if tool_data is None:
                kept.append(event)
                continue
            if tool_data.get("tool_name") != APPROVAL_REQUEST_TOOL_NAME:
                kept.append(event)
                continue
            data: _ApprovalFrameData | None = _frame_approval_data(tool_data)
            if data is None or data.get("approval_id") != approval_id:
                kept.append(event)
                continue
            if drop_if_unpublished and _is_held(event):
                settled = True
                continue
            data["status"] = status
            # A decided card cannot expire; leaving the pending card's expiry would contradict it.
            data.pop("expires_at", None)
            if feedback is not None:
                data["feedback"] = feedback
            kept.append(event)
            settled = True
        session.tool_events[:] = kept
        return settled
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Approval frame settle failed",
            approval_id=approval_id,
            error_type=type(e).__name__,
        )
        return False


async def flush_held_approval_cards(stream_id: str) -> int:
    """Publish held PENDING cards at run end so the open client renders them.

    Without this they surface only after a full refresh re-fetches messages.
    Only rows still PENDING go live; decided or revoked ones are dropped unseen.
    Each frame clears its held marker as it publishes, so a second flush is a
    no-op. A card whose row read or publish fails stays held for the drain.
    """
    session = get_session(stream_id)
    if session is None:
        return 0
    flushed = 0
    kept: list[dict[str, Any]] = []
    for event in session.tool_events:
        if not _is_held(event):
            kept.append(event)
            continue
        tool_data: _FrameToolData | None = _frame_tool_data(event)
        data: _ApprovalFrameData | None = _frame_approval_data(tool_data)
        approval_id = data.get("approval_id") if data is not None else None
        try:
            row = (
                await approval_ledger_repository.get_by_approval_id(approval_id)
                if isinstance(approval_id, str)
                else None
            )
        except Exception as e:
            log.error(
                f"{LogTag.HIL} Held card ledger read failed",
                approval_id=approval_id,
                error_type=type(e).__name__,
            )
            kept.append(event)
            continue
        if row is None or row.state not in (
            LedgerState.PENDING,
            LedgerState.APPROVED,
        ):
            # Decided, revoked, or gone: a card the user never saw needs
            # no tombstone — drop it so the drain cannot resurrect it.
            continue
        try:
            frame = {"tool_data": tool_data}
            await stream_manager.publish_chunk(stream_id, f"data: {json.dumps(frame)}\n\n")
            _schedule_pending_notification(
                row.user_id, row.conversation_id, row.approval_id, row.summary
            )
        except Exception as e:
            log.warning(
                f"{LogTag.HIL} Held card flush missed its stream",
                approval_id=row.approval_id,
                error_type=type(e).__name__,
            )
            kept.append(event)
            continue
        # Marker stripped, frame kept: the end-of-run drain still persists
        # it (reload-safe), while a second flush sees no marker and stays
        # a no-op — live frames can never duplicate.
        kept.append(frame)
        flushed += 1
    session.tool_events[:] = kept
    return flushed


def _frame_tool_data(event: object) -> _FrameToolData | None:
    """Return a session frame's tool_data object, or None when it carries none."""
    if not isinstance(event, dict):
        return None
    frame: _SessionFrame = cast(_SessionFrame, event)
    tool_data = frame.get("tool_data")
    return cast(_FrameToolData, tool_data) if isinstance(tool_data, dict) else None


def _frame_approval_data(tool_data: _FrameToolData | None) -> _ApprovalFrameData | None:
    """Return the data object inside a frame's tool_data, or None when it carries none."""
    data = tool_data.get("data") if tool_data is not None else None
    return cast(_ApprovalFrameData, data) if isinstance(data, dict) else None


def _is_held(event: object) -> bool:
    """Whether a session frame is a live-run card still held for the end-of-run flush."""
    if not isinstance(event, dict):
        return False
    frame: _SessionFrame = cast(_SessionFrame, event)
    return frame.get("_held_approval") is True


async def pending_card(record: ApprovalLedgerDocument) -> PendingApprovalCardData:
    """Rebuild a still-pending approval's card from its ledger row, as the bot prompt lists it."""
    card = SettledApprovalCard(
        approval_id=record.approval_id,
        tool_call=GatedCall(name=record.tool_name, id="", args=record.args),
        description=describe_call(record.tool_name, record.args, None, record.account),
        integration_name=None,
    )
    return await _pending_data(
        card, auto_reason=None, asked_at=record.created_at, ledger_version=record.v
    )


async def _pending_data(
    card: ApprovalCard,
    *,
    auto_reason: str | None,
    asked_at: datetime,
    ledger_version: int | None = None,
) -> PendingApprovalCardData:
    """Build a PENDING card, stamped with whether its call asks every time."""
    return PendingApprovalCardData(
        **_card_fields(card, asked_at=asked_at, feedback=None, auto_reason=auto_reason),
        status="pending",
        ledger_version=ledger_version,
        always_asks=await asks_every_time(card.tool_call.name, card.tool_call.args),
    )


def _approval_entry(
    card: ApprovalCard,
    status: LedgerState,
    *,
    asked_at: datetime,
    feedback: str | None = None,
) -> ApprovalRequestEntry:
    """Build a decided card; a pending status here is a bug and raises."""
    data = SettledApprovalCardData(
        **_card_fields(card, asked_at=asked_at, feedback=feedback, auto_reason=None),
        status=_SETTLED_STATUS.validate_python(status.value),
    )
    return _entry(data)


_SETTLED_STATUS: TypeAdapter[SettledApprovalStatus] = TypeAdapter(SettledApprovalStatus)


class _CardFields(TypedDict):
    approval_id: str
    tool_call_id: str
    gated_tool_name: str
    integration_name: str | None
    summary: str
    description: ApprovalDescription
    args_preview: dict[str, Any]
    feedback: str | None
    auto_reason: str | None
    asked_at: datetime


def _card_fields(
    card: ApprovalCard, *, asked_at: datetime, feedback: str | None, auto_reason: str | None
) -> _CardFields:
    tool_call = card.tool_call
    return {
        "approval_id": card.approval_id,
        "tool_call_id": tool_call.id,
        "gated_tool_name": tool_call.name,
        "integration_name": card.integration_name,
        "summary": card.description.headline,
        "description": card.description,
        "args_preview": tool_call.args,
        "feedback": feedback,
        "auto_reason": auto_reason,
        "asked_at": asked_at,
    }


def _entry(data: PendingApprovalCardData | SettledApprovalCardData) -> ApprovalRequestEntry:
    return ApprovalRequestEntry(
        tool_name=APPROVAL_REQUEST_TOOL_NAME,
        tool_category=APPROVAL_TOOL_CATEGORY,
        data=data,
        timestamp=datetime.now(UTC).isoformat(),
    )
