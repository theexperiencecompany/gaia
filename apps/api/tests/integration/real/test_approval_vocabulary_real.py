"""Every way a ledger approval ends reads the same in its log entry, on the row that follows it, and in its event."""

from collections.abc import Awaitable, Callable
from unittest.mock import MagicMock

from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.db.repositories.approval_ledger import (
    LIVE_ROW_FILTER,
    LIVE_ROW_INDEX_NAME,
    approval_ledger_repository,
    new_approval_id,
)
from app.models.hil_models import ApprovalProposal
from app.services.hil import ledger_decide
from shared.py.analytics.catalog.hil import HilDecisionSubmitted, HilRevoked
from shared.py.approvals import ApprovalDecider, ApprovalOutcome
from tests.integration.real.ledger_fixtures import Edges

USER_ID = "65f1a2b3c4d5e6f708192a3b"
CONVERSATION_ID = "conv-vocabulary"
OWNER = "gmail_conv-vocabulary"

pytestmark = [pytest.mark.integration, pytest.mark.service]


async def _propose() -> str:
    return await approval_ledger_repository.register(
        ApprovalProposal(
            conversation_id=CONVERSATION_ID,
            user_id=USER_ID,
            fingerprint="fp-send",
            tool_name="GMAIL_SEND_EMAIL",
            summary="Send it",
            owner_agent=OWNER,
            task_id="t1",
        ),
        new_approval_id(),
    )


async def _approve(approval_id: str) -> None:
    await ledger_decide.decide_ledger(approval_id, user_id=USER_ID, kind="approve", via="card")


async def _deny(approval_id: str) -> None:
    await ledger_decide.decide_ledger(approval_id, user_id=USER_ID, kind="deny", via="card")


async def _stop(approval_id: str) -> None:
    await ledger_decide.cancel_ledger_approvals(CONVERSATION_ID, USER_ID, [approval_id])


async def _withdraw(approval_id: str) -> None:
    await ledger_decide.revoke_ticket(
        approval_id, user_id=USER_ID, conversation_id=CONVERSATION_ID, caller=OWNER
    )


async def _expire(approval_id: str) -> None:
    row = await approval_ledger_repository.get_by_approval_id(approval_id)
    assert row is not None
    assert await ledger_decide.expire_ledger_approval(row)


def _event_outcome(edges: Edges) -> ApprovalOutcome:
    [event] = [
        call.args[1]
        for call in edges.events.call_args_list
        if isinstance(call.args[1], HilDecisionSubmitted | HilRevoked)
    ]
    return event.decision if isinstance(event, HilDecisionSubmitted) else event.outcome


@pytest.mark.parametrize(
    ("end", "outcome", "decider"),
    [
        (_approve, ApprovalOutcome.APPROVED, ApprovalDecider.USER),
        (_deny, ApprovalOutcome.DENIED, ApprovalDecider.USER),
        (_stop, ApprovalOutcome.CANCELLED, None),
        (_withdraw, ApprovalOutcome.WITHDRAWN, None),
        (_expire, ApprovalOutcome.EXPIRED, None),
    ],
    ids=["approved-by-user", "denied", "cancelled-by-stop", "withdrawn", "expired"],
)
async def test_each_ending_reads_the_same_everywhere(
    mongo_db: AsyncIOMotorDatabase,
    edges: Edges,
    end: Callable[[str], Awaitable[None]],
    outcome: ApprovalOutcome,
    decider: ApprovalDecider | None,
) -> None:
    approval_id = await _propose()

    await end(approval_id)

    row = await mongo_db["approval_ledger"].find_one({"approval_id": approval_id})
    assert row is not None and (row["outcome"], row["action"]) == (outcome, None)
    assert _event_outcome(edges) is outcome
    # The log takes every ending first; the row only follows it.
    edges.logged.assert_awaited_once_with(
        CONVERSATION_ID, USER_ID, approval_id, outcome, decider, feedback=None
    )


async def test_an_approved_action_that_fails_says_so_beside_the_approval(
    mongo_db: AsyncIOMotorDatabase, edges: Edges
) -> None:
    approval_id = await _propose()
    await _approve(approval_id)
    edges.dispatch.return_value = MagicMock(ok=False, output=None, error=None)

    await ledger_decide.redeem_approved(
        approval_id,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        caller=OWNER,
        run_config={},
    )

    row = await mongo_db["approval_ledger"].find_one({"approval_id": approval_id})
    assert row is not None and (row["outcome"], row["action"]) == ("approved", "failed")
    edges.acted.assert_awaited_once_with(CONVERSATION_ID, USER_ID, approval_id, "failed")


async def test_only_one_open_row_per_call_even_with_explicit_nulls(
    mongo_db: AsyncIOMotorDatabase, edges: Edges
) -> None:
    del edges
    await mongo_db["approval_ledger"].create_index(
        [("conversation_id", 1), ("fingerprint", 1)],
        unique=True,
        partialFilterExpression=LIVE_ROW_FILTER,
        name=LIVE_ROW_INDEX_NAME,
    )
    first = await _propose()

    assert await _propose() == first
    await _withdraw(first)
    assert await _propose() != first
    assert await mongo_db["approval_ledger"].count_documents(LIVE_ROW_FILTER) == 1
