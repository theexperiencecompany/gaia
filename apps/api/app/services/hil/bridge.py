"""Surface an approval request to the user's clients, and remember declines.

The gate pauses its run with LangGraph's interrupt(); nothing here waits. This
module only *publishes*: it records the pending approval durably, pushes the
approval_request tool_data card onto the turn's SSE stream, and wakes clients
that aren't watching it. The decision arrives out-of-band and is applied by
app/services/hil/resolution.py, which resumes the paused thread.

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
import hashlib
import json
from typing import Any, TypedDict, cast

from app.agents.core.background.session import RunKind, get_session
from app.constants.cache import HIL_DECLINED_PREFIX
from app.constants.hil import (
    APPROVAL_REQUEST_TOOL_NAME,
    APPROVAL_TOOL_CATEGORY,
    HIL_APPROVAL_TIMEOUT_SECONDS,
    HIL_CLASSIFIER_MAX_ARG_CHARS,
    HIL_CLASSIFIER_MAX_ARGS,
    HIL_CLASSIFIER_MAX_DETAIL_CHARS,
    HIL_DECLINE_MEMORY_TTL_SECONDS,
    HIL_SUMMARY_MAX_ARG_CHARS,
    HIL_SUMMARY_MAX_ARGS,
)
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.conversations import conversation_repository
from app.models.agent_config import SubagentResumeItem
from app.models.hil_models import (
    DeclinedCallRecord,
    HILApprovalRecord,
    HILApprovalStatus,
    LedgerState,
)
from app.models.stream_events import ApprovalRequestEntry, ApprovalRequestEntryData
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.hil.approvals_store import record_auto_approval, upsert_pending_approval
from app.services.hil.notify import notify_approval_pending
from app.services.hil.utils import GatedCall
from app.services.latency_metrics import observe_hil_pause
from app.utils.general_utils import clip_text
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


@dataclass
class ApprovalOutcome:
    """The resolved result of an approval request: status, optional feedback, and scope."""

    status: HILApprovalStatus
    feedback: str | None = None
    scope: str = "once"
    # True when the refusal came from auto mode, never from the user — the
    # retry message must not claim the user declined something they never saw.
    auto: bool = False


async def publish_approval_request(
    *,
    approval_id: str,
    stream_id: str,
    user_id: str,
    conversation_id: str,
    tool_call: GatedCall,
    summary: str,
    integration_name: str | None,
    auto_reason: str | None = None,
    subagent_resume: SubagentResumeItem | None = None,
    subagent_thread_id: str | None = None,
) -> None:
    """Record the pending approval and surface its card — exactly once.

    The gate re-enters this on every resume replay (the node re-runs from the
    top), so the card and the notification are gated on whether the upsert
    actually created the record. A replay is a no-op.
    """
    created = await upsert_pending_approval(
        approval_id=approval_id,
        user_id=user_id,
        conversation_id=conversation_id,
        stream_id=stream_id,
        tool_name=tool_call.name,
        tool_call_id=tool_call.id,
        args=tool_call.args,
        summary=summary,
        integration_name=integration_name,
        subagent_thread_id=subagent_thread_id,
        subagent_resume=subagent_resume,
    )
    if not created:
        return

    # Counted here — the one place a genuine pause is born (gated on `created`,
    # so a resume replay is a no-op) — not at the decision, where it would count
    # decisions and miss still-pending pauses.
    observe_hil_pause()
    log.set(hil={"approval_id": approval_id, "tool": tool_call.name, "stream_id": stream_id})
    await _publish_entry(
        stream_id,
        _approval_entry(
            approval_id,
            tool_call,
            HILApprovalStatus.PENDING,
            summary,
            integration_name,
            auto_reason=auto_reason,
        ),
    )
    _schedule_pending_notification(user_id, conversation_id, approval_id, summary)


async def publish_ledger_request(
    *,
    approval_id: str,
    stream_id: str,
    user_id: str,
    conversation_id: str,
    tool_call: GatedCall,
    summary: str,
    integration_name: str | None,
    rationale: str | None = None,
    auto_reason: str | None = None,
    live: bool = True,
    owner_run_type: str = "",
    owner_id: str = "",
) -> None:
    """Surface a ledger PENDING card exactly once per registration.

    Same approval_request wire shape as the barrier path, so clients render it
    unchanged. On a live run the card is HELD (recorded on the session for the
    end-of-run drain, no SSE until then); background runs publish immediately,
    nobody being there to watch the stream.
    """
    log.set(hil={"approval_id": approval_id, "tool": tool_call.name, "stream_id": stream_id})
    entry = _approval_entry(
        approval_id,
        tool_call,
        HILApprovalStatus.PENDING,
        summary,
        integration_name,
        auto_reason=auto_reason,
    )
    entry.data.rationale = rationale
    entry.data.age_seconds = 0
    entry.data.ledger_version = 0
    # Server-owned funnel event: exactly once per registration, held or
    # streamed — the card exists either way. Explicit user_id: bridge paths
    # carry no request context to attribute from.
    capture_event(
        user_id,
        AnalyticsEvents.HIL_CARD_SHOWN,
        {
            "approval_id": approval_id,
            "tool_name": tool_call.name,
            "ledger_version": 0,
            "background": not live,
        },
    )
    session = get_session(stream_id)
    held = live and session is not None and session.kind is RunKind.LIVE
    if owner_run_type and owner_id:
        # Background owner parked here: surface its conversation in the
        # sidebar while the approval lives (hidden otherwise).
        await conversation_repository.mark_background_with_live_approval(
            conversation_id, user_id=user_id
        )
    if not held:
        # Background, detached-queued, and session-less runs publish immediately:
        # nobody is watching this stream (or there is none to drain), so holding
        # would hide the card until a drain that never comes.
        await _publish_entry(stream_id, entry)
        _schedule_pending_notification(user_id, conversation_id, approval_id, summary)
        return
    frame = {"tool_data": entry.model_dump(), "_held_approval": True}
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


async def publish_decision(
    record: HILApprovalRecord, status: HILApprovalStatus, *, stream_id: str, feedback: str | None
) -> None:
    """Settle this approval's card, on the stream the user is watching NOW.

    Never record.stream_id: that is the stream the request was raised on, and a run
    that paused resumes on a fresh one (prepare_run_from_item), leaving the original
    closed. The client follows the new stream via executor.stream_started, so a card
    settled on the old one resolves where nobody is looking.
    """
    await _publish_entry(
        stream_id,
        _approval_entry(
            record.approval_id,
            GatedCall(name=record.tool_name, id=record.tool_call_id, args=record.args),
            status,
            record.summary,
            record.integration_name,
            feedback,
        ),
    )
    # Settle the PERSISTED frame now too, since a later pause before final delivery
    # reconciles would otherwise show a dead pending card. Isolated: the caller
    # (the gate) fails CLOSED, so a write error here must not become a denial.
    try:
        await conversation_repository.set_message_approval_status(
            record.conversation_id,
            user_id=record.user_id,
            approval_id=record.approval_id,
            status=status.value,
        )
    except Exception as e:
        log.error(
            f"{LogTag.HIL} Could not settle persisted approval frame; delivery will reconcile",
            approval_id=record.approval_id,
            error=str(e),
            error_type=type(e).__name__,
        )


async def publish_auto_approval(
    *,
    approval_id: str,
    stream_id: str,
    user_id: str,
    conversation_id: str,
    tool_call: GatedCall,
    summary: str,
    integration_name: str | None,
    reason: str,
) -> None:
    """Record and surface an action auto mode ran without asking.

    The card is published already settled, so it needs no decision and wakes nobody — it
    is a receipt, not a request. Auto mode should never mean the user cannot see what was
    done in their name.
    """
    await record_auto_approval(
        approval_id=approval_id,
        user_id=user_id,
        conversation_id=conversation_id,
        stream_id=stream_id,
        tool_name=tool_call.name,
        tool_call_id=tool_call.id,
        args=tool_call.args,
        summary=summary,
        integration_name=integration_name,
        reason=reason,
    )
    await _publish_entry(
        stream_id,
        _approval_entry(
            approval_id,
            tool_call,
            HILApprovalStatus.AUTO_APPROVED,
            summary,
            integration_name,
            auto_reason=reason,
        ),
    )


async def remember_declined_call(
    stream_id: str,
    tool_name: str,
    args: Mapping[str, object],
    feedback: str | None,
    auto: bool = False,
) -> None:
    """Record that this exact call was declined for the rest of the turn."""
    if not redis_cache.redis:
        return
    record: DeclinedCallRecord = {"feedback": feedback, "auto": auto}
    await redis_cache.set(
        _declined_key(stream_id, tool_name, args),
        record,
        ttl=HIL_DECLINE_MEMORY_TTL_SECONDS,
    )


async def recall_declined_call(
    stream_id: str, tool_name: str, args: Mapping[str, object]
) -> ApprovalOutcome | None:
    """Return the prior decline for this exact call in this turn, if any.

    Lets the gate auto-deny a retry with the user's original feedback and never re-prompt.
    """
    if not redis_cache.redis:
        return None
    raw = await redis_cache.get(_declined_key(stream_id, tool_name, args))
    if not raw:
        return None
    # Correct by construction: the only writer is ``remember_declined_call`` above.
    record: DeclinedCallRecord = cast(DeclinedCallRecord, raw)
    return ApprovalOutcome(
        status=HILApprovalStatus.DENIED,
        feedback=record.get("feedback"),
        auto=record.get("auto", False),
    )


def build_summary(tool_name: str, args: Mapping[str, object], integration_name: str | None) -> str:
    """Deterministic one-line summary of a gated call (no LLM in the hot path)."""
    label = tool_name.replace("_", " ").strip().capitalize()
    if integration_name:
        label = f"{label} ({integration_name})"
    parts = _summary_arg_parts(args)
    return f"{label} — {', '.join(parts)}" if parts else label


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
    frame = {"tool_data": entry.model_dump()}
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


def _approval_entry(
    approval_id: str,
    tool_call: GatedCall,
    status: HILApprovalStatus,
    summary: str,
    integration_name: str | None,
    feedback: str | None = None,
    auto_reason: str | None = None,
) -> ApprovalRequestEntry:
    return ApprovalRequestEntry(
        tool_name=APPROVAL_REQUEST_TOOL_NAME,
        tool_category=APPROVAL_TOOL_CATEGORY,
        data=ApprovalRequestEntryData(
            approval_id=approval_id,
            tool_call_id=tool_call.id,
            gated_tool_name=tool_call.name,
            integration_name=integration_name,
            summary=summary,
            args_preview=tool_call.args,
            status=status,
            feedback=feedback,
            auto_reason=auto_reason,
            timeout_seconds=int(HIL_APPROVAL_TIMEOUT_SECONDS),
        ),
        timestamp=datetime.now(UTC).isoformat(),
    )


def _summary_arg_parts(args: Mapping[str, object]) -> list[str]:
    """Build a few short key: value scalars for the card's one-line summary."""
    parts: list[str] = []
    for key, value in (args or {}).items():
        if len(parts) >= HIL_SUMMARY_MAX_ARGS:
            break
        if isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}: {clip_text(str(value), HIL_SUMMARY_MAX_ARG_CHARS)}")
    return parts


def _declined_key(stream_id: str, tool_name: str, args: Mapping[str, object]) -> str:
    return f"{HIL_DECLINED_PREFIX}{stream_id}:{tool_name}:{_args_hash(args)}"


def _args_hash(args: Mapping[str, object]) -> str:
    # md5 over the canonical args — a cache key, not a security boundary.
    payload = json.dumps(args or {}, sort_keys=True, default=str)
    return hashlib.md5(payload.encode(), usedforsecurity=False).hexdigest()  # nosec B324
