"""Announce a ledger approval to the user, and remember declines.

The approval's ApprovalRequested entry is its card: every client draws it from the
conversation screen. What is left here is telling the people who are not looking
(a push), counting the card, and keeping a declined call from being asked again
in the same turn.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import cast

from pydantic import BaseModel, ConfigDict

from app.constants.cache import HIL_DECLINED_PREFIX
from app.constants.hil import (
    HIL_CLASSIFIER_MAX_ARG_CHARS,
    HIL_CLASSIFIER_MAX_ARGS,
    HIL_CLASSIFIER_MAX_DETAIL_CHARS,
    HIL_DECLINE_MEMORY_TTL_SECONDS,
    HIL_SUMMARY_MAX_ARG_CHARS,
    HIL_SUMMARY_MAX_ARGS,
)
from app.db.redis import redis_cache
from app.db.repositories.conversations import conversation_repository
from app.models.hil_models import DeclinedCallRecord
from app.services.analytics_service import capture
from app.services.hil.notify import notify_approval_pending
from app.services.hil.utils import GatedApproval
from app.utils.general_utils import clip_text
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import HilCardShown
from shared.py.approvals import ApprovalDecider, ApprovalOutcome
from shared.py.wide_events import log, spawn_logged_task


@dataclass
class GateVerdict:
    """How an earlier decision on the same call ended, optional feedback, and scope."""

    outcome: ApprovalOutcome
    feedback: str | None = None
    scope: str = "once"
    # AUTO when the refusal came from auto mode, never from the user — the
    # retry message must not claim the user declined something they never saw.
    decider: ApprovalDecider = ApprovalDecider.USER


async def announce_approval(approval: GatedApproval, *, background: bool, has_owner: bool) -> None:
    """Count the card the log now shows, list a background owner's conversation, and push it."""
    log.set(
        hil={
            "approval_id": approval.approval_id,
            "tool": approval.tool_call.name,
            "stream_id": approval.stream_id,
        }
    )
    capture(
        UserId(approval.user_id),
        HilCardShown(
            approval_id=approval.approval_id,
            tool_name=approval.tool_call.name,
            ledger_version=0,
            background=background,
        ),
    )
    if has_owner:
        # A background owner's conversation is listed only while its work awaits approval.
        await conversation_repository.mark_background(
            approval.conversation_id, user_id=approval.user_id
        )
    # Detached, since a push failure must never block the gate.
    spawn_logged_task(
        "approval_pending_notification",
        notify_approval_pending(
            approval.user_id, approval.conversation_id, approval.approval_id, approval.summary
        ),
        user={"id": approval.user_id},
        conversation_id=approval.conversation_id,
        approval_id=approval.approval_id,
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
) -> GateVerdict | None:
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
    return GateVerdict(
        outcome=ApprovalOutcome.DENIED,
        feedback=record.get("feedback"),
        decider=ApprovalDecider.AUTO if record.get("auto", False) else ApprovalDecider.USER,
    )


class _BrowserTaskArgs(BaseModel):
    """The one browser_task argument the approval card summarises."""

    model_config = ConfigDict(extra="ignore")

    task: str = ""


def build_summary(
    tool_name: str,
    args: Mapping[str, object],
    integration_name: str | None,
    account: str | None = None,
) -> str:
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
    source = ", ".join(part for part in (integration_name, account) if part)
    if source:
        label = f"{label} ({source})"
    parts = _summary_arg_parts(args)
    return f"{label}; {', '.join(parts)}" if parts else label


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
