"""Approvals waiting on the user as candidates, from both HIL stores.

Ledger mode registers a gated call in approval_ledger and lets the run finish; the
interrupt gate keeps hil_approvals. A user can have pending rows in either, so both
are read. An approval a tracked todo parked on is that todo's, already a candidate.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from app.config.oauth_config import get_integration_by_id, get_integration_by_tool_slug
from app.config.settings import settings
from app.constants.briefing import GAIA_APP_NAME, GAIA_SOURCE, BriefAction
from app.constants.chat import CONVERSATION_PATH
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.hil import hil_approval_repository
from app.models.brief_candidate_models import (
    BriefCandidate,
    CandidateOrigin,
    GaiaRef,
    GaiaRefKind,
)
from app.models.brief_item_models import ItemState
from app.models.hil_models import ApprovalLedgerDocument
from app.services.hil.tool_key import parse_hil_tool_key


def _ledger_app(row: ApprovalLedgerDocument) -> tuple[str, str]:
    """Name the app a ledger approval acts in, read off its tool; GAIA's own tools are GAIA's."""
    identity = parse_hil_tool_key(row.tool_key) if row.tool_key else None
    integration = (
        get_integration_by_id(identity.integration_id)
        if identity is not None
        else get_integration_by_tool_slug(row.tool_name)
    )
    if integration is None:
        return GAIA_SOURCE, GAIA_APP_NAME
    return integration.id, integration.name


@dataclass(frozen=True)
class _Pending:
    """One pending approval as either store holds it."""

    approval_id: str
    conversation_id: str
    tool_name: str
    summary: str


def _candidate(source: str, app: str, pending: _Pending) -> BriefCandidate:
    """Return the approval as a candidate that opens the conversation its card waits in."""
    return BriefCandidate(
        origin=CandidateOrigin.APPROVAL,
        source=source,
        app=app,
        seen_as=GaiaRef(kind=GaiaRefKind.APPROVAL, id=pending.approval_id),
        state=ItemState.YOU,
        title=pending.summary.strip() or f"Approve {pending.tool_name}",
        detail="waiting for your approval",
        action=BriefAction.APPROVE,
        url=settings.FRONTEND_URL
        + CONVERSATION_PATH.format(conversation_id=pending.conversation_id),
    )


async def approval_candidates(
    user_id: str, now: datetime, covered_todo_ids: Collection[str]
) -> list[BriefCandidate]:
    """Return every approval still waiting on the user that no tracked todo already stands for."""
    candidates: list[BriefCandidate] = []
    for row in await approval_ledger_repository.list_pending_for_user(user_id):
        if row.owner_id and row.owner_id in covered_todo_ids:
            continue
        source, app = _ledger_app(row)
        candidates.append(
            _candidate(
                source,
                app,
                _Pending(row.approval_id, row.conversation_id, row.tool_name, row.summary),
            )
        )
    for record in await hil_approval_repository.list_pending_for_user(user_id, now):
        app = record.integration_name or GAIA_APP_NAME
        source = GAIA_SOURCE if record.integration_name is None else app
        candidates.append(
            _candidate(
                source,
                app,
                _Pending(
                    record.approval_id, record.conversation_id, record.tool_name, record.summary
                ),
            )
        )
    return candidates
