"""Approvals waiting on the user as candidates, from both HIL stores.

Ledger mode registers a gated call in approval_ledger and lets the run finish; the
interrupt gate keeps hil_approvals. A user can have pending rows in either, so both
are read. An approval a tracked todo parked on is that todo's, already a candidate.
"""

from collections.abc import Collection
from datetime import datetime

from app.config.oauth_config import get_integration_by_id, get_integration_by_tool_slug
from app.constants.briefing import GAIA_APP_NAME, GAIA_SOURCE, BriefAction
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.hil import hil_approval_repository
from app.models.brief_candidate_models import BriefCandidate
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


def _candidate(source: str, app: str, summary: str, tool_name: str) -> BriefCandidate:
    return BriefCandidate(
        source=source,
        app=app,
        state="you",
        title=summary.strip() or f"Approve {tool_name}",
        detail="waiting for your approval",
        action=BriefAction.APPROVE,
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
        candidates.append(_candidate(source, app, row.summary, row.tool_name))
    for record in await hil_approval_repository.list_pending_for_user(user_id, now):
        app = record.integration_name or GAIA_APP_NAME
        source = GAIA_SOURCE if record.integration_name is None else app
        candidates.append(_candidate(source, app, record.summary, record.tool_name))
    return candidates
