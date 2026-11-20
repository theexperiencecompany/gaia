"""The ledger decision path's edges, recorded instead of reached: the log writes, events, dispatch and wakes."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.models.conversation_log_models import ApprovalDecided
from app.services.conversation.screen import decided_status
from app.services.conversation.work_log import DecisionTaken
from app.services.hil import ledger_decide
from shared.py.approvals import ApprovalDecider, ApprovalOutcome, ApprovalStatus


@dataclass
class Edges:
    """What left the ledger path: the log entries and the analytics events."""

    logged: AsyncMock
    events: MagicMock
    dispatch: AsyncMock
    acted: AsyncMock


@pytest.fixture
async def edges(mongo_db: AsyncIOMotorDatabase) -> AsyncIterator[Edges]:
    await mongo_db["approval_ledger"].delete_many({})
    decided: dict[str, ApprovalDecided] = {}

    async def _decide(
        conversation_id: str,
        user_id: str,
        approval_id: str,
        outcome: ApprovalOutcome,
        decider: ApprovalDecider | None,
        *,
        feedback: str | None = None,
    ) -> DecisionTaken:
        taken = approval_id not in decided
        decided.setdefault(
            approval_id,
            ApprovalDecided(
                id=f"approval:{approval_id}:decided",
                approval_id=approval_id,
                outcome=outcome,
                decider=decider,
                feedback=feedback,
            ),
        )
        return DecisionTaken(stands=decided[approval_id], taken=taken)

    async def _read(conversation_id: str, user_id: str, approval_id: str) -> ApprovalDecided | None:
        return decided.get(approval_id)

    async def _status(
        conversation_id: str, user_id: str, approval_id: str, now: datetime
    ) -> ApprovalStatus:
        decision = decided.get(approval_id)
        return ApprovalStatus.WAITING if decision is None else decided_status(decision)

    with (
        patch.object(
            ledger_decide, "record_approval_decided", new=AsyncMock(side_effect=_decide)
        ) as logged,
        patch.object(ledger_decide, "logged_decision", new=AsyncMock(side_effect=_read)),
        patch.object(ledger_decide, "logged_status", new=AsyncMock(side_effect=_status)),
        patch.object(ledger_decide, "record_approved_action_ended", new=AsyncMock()) as acted,
        patch.object(ledger_decide, "capture") as events,
        patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
        patch.object(ledger_decide, "_deliver_verdict", new=AsyncMock()),
        patch.object(ledger_decide, "_wake_agent", new=AsyncMock()),
        patch.object(ledger_decide, "resume_owner_after_approval", new=AsyncMock()),
        patch.object(ledger_decide, "record_owner_deny", new=AsyncMock()),
        patch.object(ledger_decide, "dispatch_tool", new=AsyncMock()) as dispatch,
        patch.object(ledger_decide, "dispatch_config_for", return_value={}),
    ):
        yield Edges(logged, events, dispatch, acted)
    await mongo_db["approval_ledger"].delete_many({})
