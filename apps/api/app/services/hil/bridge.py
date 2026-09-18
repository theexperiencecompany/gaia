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
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict

from app.agents.core.background.session import get_session
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
from app.db.repositories.conversations import conversation_repository
from app.models.hil_models import DeclinedCallRecord, HILApprovalRecord, HILApprovalStatus
from app.models.stream_events import ApprovalRequestEntry, ApprovalRequestEntryData
from app.services.hil.approvals_store import record_auto_approval, upsert_pending_approval
from app.services.hil.notify import notify_approval_pending
from app.services.hil.utils import GatedCall
from app.services.latency_metrics import observe_hil_pause
from app.utils.general_utils import clip_text
from shared.py.wide_events import log, spawn_logged_task


@dataclass
class ApprovalOutcome:
    """The resolved result of an approval request: status, optional feedback, and scope."""

    status: HILApprovalStatus
    feedback: str | None = None
    scope: str = "once"


@dataclass(frozen=True)
class GatedApproval:
    """Identity of a gated call being surfaced — shared by request and receipt."""

    approval_id: str
    stream_id: str
    user_id: str
    conversation_id: str
    tool_call: GatedCall
    summary: str
    integration_name: str | None


class ApprovalCard(Protocol):
    """What an approval card renders, the slice of GatedApproval the entry reads."""

    @property
    def approval_id(self) -> str: ...
    @property
    def tool_call(self) -> GatedCall: ...
    @property
    def summary(self) -> str: ...
    @property
    def integration_name(self) -> str | None: ...


@dataclass(frozen=True)
class SettledApprovalCard:
    """A decided call's card, rebuilt from its persisted record to redraw it settled."""

    approval_id: str
    tool_call: GatedCall
    summary: str
    integration_name: str | None


async def publish_approval_request(approval: GatedApproval) -> None:
    """Record the pending approval and surface its card — exactly once.

    The gate re-enters this on every resume replay (the node re-runs from the
    top), so the card and the notification are gated on whether the upsert
    actually created the record. A replay is a no-op.
    """
    created = await upsert_pending_approval(
        approval_id=approval.approval_id,
        user_id=approval.user_id,
        conversation_id=approval.conversation_id,
        stream_id=approval.stream_id,
        tool_name=approval.tool_call.name,
        tool_call_id=approval.tool_call.id,
        args=approval.tool_call.args,
        summary=approval.summary,
        integration_name=approval.integration_name,
    )
    if not created:
        return

    # Counted here — the one place a genuine pause is born (gated on `created`,
    # so a resume replay is a no-op) — not at the decision, where it would count
    # decisions and miss still-pending pauses.
    observe_hil_pause()
    log.set(
        hil={
            "approval_id": approval.approval_id,
            "tool": approval.tool_call.name,
            "stream_id": approval.stream_id,
        }
    )
    await _publish_entry(
        approval.stream_id,
        _approval_entry(approval, HILApprovalStatus.PENDING),
    )
    _schedule_pending_notification(
        approval.user_id, approval.conversation_id, approval.approval_id, approval.summary
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
    card = SettledApprovalCard(
        approval_id=record.approval_id,
        tool_call=GatedCall(name=record.tool_name, id=record.tool_call_id, args=record.args),
        summary=record.summary,
        integration_name=record.integration_name,
    )
    await _publish_entry(stream_id, _approval_entry(card, status, feedback=feedback))
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


async def publish_auto_approval(approval: GatedApproval, *, reason: str) -> None:
    """Record and surface an action auto mode ran without asking.

    The card is published already settled, so it needs no decision and wakes nobody — it
    is a receipt, not a request. Auto mode should never mean the user cannot see what was
    done in their name.
    """
    await record_auto_approval(
        approval_id=approval.approval_id,
        user_id=approval.user_id,
        conversation_id=approval.conversation_id,
        stream_id=approval.stream_id,
        tool_name=approval.tool_call.name,
        tool_call_id=approval.tool_call.id,
        args=approval.tool_call.args,
        summary=approval.summary,
        integration_name=approval.integration_name,
        reason=reason,
    )
    await _publish_entry(
        approval.stream_id,
        _approval_entry(approval, HILApprovalStatus.AUTO_APPROVED, auto_reason=reason),
    )


async def remember_declined_call(
    stream_id: str, tool_name: str, args: Mapping[str, object], feedback: str | None
) -> None:
    """Record that the user declined this exact call for the rest of the turn."""
    if not redis_cache.redis:
        return
    record: DeclinedCallRecord = {"feedback": feedback}
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
    return ApprovalOutcome(status=HILApprovalStatus.DENIED, feedback=record.get("feedback"))


class _BrowserTaskArgs(BaseModel):
    """The one browser_task argument the approval card summarises."""

    model_config = ConfigDict(extra="ignore")

    task: str = ""


def build_summary(tool_name: str, args: Mapping[str, object], integration_name: str | None) -> str:
    """Deterministic one-line summary of a gated call (no LLM in the hot path)."""
    if tool_name == "browser_task":
        # A browser task's whole intent is its ``task`` — but a weak model can
        # write a long paragraph, so keep the card scannable: the first sentence,
        # or a clipped lead. Never dump ``start_url`` or truncate mid-word.
        task = _BrowserTaskArgs.model_validate(args).task.strip()
        if not task:
            return "Start a browser task"
        first = task.split(". ")[0].strip().rstrip(".")
        concise = first if 0 < len(first) <= 140 else clip_text(task, 140)
        return f"Start a browser task: {concise}"
    label = tool_name.replace("_", " ").strip().capitalize()
    if integration_name:
        label = f"{label} ({integration_name})"
    parts = _summary_arg_parts(args)
    return f"{label}: {', '.join(parts)}" if parts else label


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


def _approval_entry(
    card: ApprovalCard,
    status: HILApprovalStatus,
    feedback: str | None = None,
    auto_reason: str | None = None,
) -> ApprovalRequestEntry:
    tool_call = card.tool_call
    return ApprovalRequestEntry(
        tool_name=APPROVAL_REQUEST_TOOL_NAME,
        tool_category=APPROVAL_TOOL_CATEGORY,
        data=ApprovalRequestEntryData(
            approval_id=card.approval_id,
            tool_call_id=tool_call.id,
            gated_tool_name=tool_call.name,
            integration_name=card.integration_name,
            summary=card.summary,
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
