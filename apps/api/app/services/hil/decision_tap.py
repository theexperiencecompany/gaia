"""One approval decision tapped on a card, on whichever HIL path the user is on.

The web card's decision route and a messaging-bot button both land here, so a
tap behaves the same wherever the card was shown.
"""

from app.schemas.hil_schemas import ApprovalDecisionRequest, ApprovalDecisionResponse
from app.services.analytics_service import capture
from app.services.feature_flags import is_hil_ledger_enabled
from app.services.hil.ledger_decide import decide_ledger_card
from app.services.hil.resolution import resolve_approval
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import ApprovalDecided
from shared.py.wide_events import log


async def decide_approval_tap(
    approval_id: str, user_id: str, tap: ApprovalDecisionRequest
) -> ApprovalDecisionResponse:
    """Apply a card tap and resume or wake the run waiting on it.

    Raises ApprovalRequestNotFoundError (410) or ApprovalRequestForbiddenError
    (403) on both paths, so a late, duplicate or cross-user tap never
    double-resolves a request.
    """
    if await is_hil_ledger_enabled(user_id):
        # Executor-free path: CAS commit on the ledger, instant-eligible
        # execution, agent wake; no paused run to resume.
        outcome = await decide_ledger_card(approval_id, user_id=user_id, tap=tap)
        log.set(hil={"resolved": outcome.committed})
        # Honest, not optimistic: a stale-v tap committed nothing, and the
        # client must refresh the row instead of believing its tap landed.
        # "stale" (row may still be live) is never "not_found" (row is gone).
        if outcome.committed:
            return ApprovalDecisionResponse(success=True, status=outcome.state.value)
        return ApprovalDecisionResponse(
            success=False,
            reason="stale" if outcome.stale else "not_found",
            status=outcome.state.value,
        )
    await resolve_approval(
        approval_id=approval_id,
        user_id=user_id,
        kind=tap.decision,
        feedback=tap.feedback,
        scope=tap.scope,
    )
    log.set(hil={"resolved": True})
    capture(UserId(user_id), ApprovalDecided(decision=tap.decision))
    return ApprovalDecisionResponse(success=True)
