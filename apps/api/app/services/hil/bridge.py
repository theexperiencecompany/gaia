"""Announce a ledger approval to the user, and remember declines.

The approval's ApprovalRequested entry is its card: every client draws it from the
conversation screen. What is left here is telling the people who are not looking
(a push), counting the card, and keeping a declined call from being asked again
in the same turn.
"""

from collections.abc import Mapping
import json

from app.constants.hil import (
    HIL_CLASSIFIER_MAX_ARG_CHARS,
    HIL_CLASSIFIER_MAX_ARGS,
    HIL_CLASSIFIER_MAX_DETAIL_CHARS,
)
from app.services.analytics_service import capture
from app.services.hil.notify import notify_approval_pending
from app.services.hil.utils import GatedApproval
from app.utils.general_utils import clip_text
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import HilCardShown
from shared.py.wide_events import log, spawn_logged_task


async def announce_approval(approval: GatedApproval, *, background: bool) -> None:
    """Count the card the log now shows, and push it."""
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
