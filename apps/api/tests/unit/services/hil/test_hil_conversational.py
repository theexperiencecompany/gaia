"""A chat reply as an approval answer (app/services/hil/conversational.py).

The approvals a reply can answer are the ones the conversation log has pending; JEV is the
one classifier, mocked at its HTTP boundary, so the question building, the approve line and
the mapping onto decisions run for real. Every decision commits through decide_ledger.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.constants.hil import HIL_JEV_REPLY_APPROVE_LINE, UNRELATED_FEEDBACK
from app.models.hil_models import ApprovalLedgerDocument
from app.services.hil.conversational import ledger_outcome_text, resolve_pending_from_message
from app.services.hil.ledger_decide import LedgerDecision
from shared.py.analytics.catalog.hil import ActionResult, ApprovalOutcome

from .conftest import CONVERSATION_ID, USER_ID, jev_reply_body, serve_jev

MODULE = "app.services.hil.conversational"


def _row(approval_id: str, summary: str, *, age_minutes: int = 1) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id=approval_id,
        conversation_id=CONVERSATION_ID,
        user_id=USER_ID,
        fingerprint=f"fp-{approval_id}",
        tool_name="GMAIL_SEND_EMAIL",
        args={"to": "bob@example.com"},
        summary=summary,
        created_at=datetime.now(UTC) - timedelta(minutes=age_minutes),
    )


@pytest.fixture(autouse=True)
def _quiet_log() -> Iterator[None]:
    with patch(f"{MODULE}.log"):
        yield


@pytest.fixture
def decide() -> Iterator[AsyncMock]:
    """Patch the one sink a classified reply reaches; every decision commits."""

    async def _commit(approval_id: str, **kwargs: Any) -> LedgerDecision:
        outcome = (
            ApprovalOutcome.APPROVED if kwargs["kind"] == "approve" else ApprovalOutcome.DENIED
        )
        return LedgerDecision(committed=True, approval_id=approval_id, outcome=outcome, action=None)

    with patch(f"{MODULE}.decide_ledger", new=AsyncMock(side_effect=_commit)) as mock:
        yield mock


def _pending(*rows: ApprovalLedgerDocument) -> Any:
    return patch(f"{MODULE}.pending_approvals", new=AsyncMock(return_value=list(rows)))


def _decided(decide: AsyncMock) -> list[tuple[str, str, str | None]]:
    return [
        (call.args[0], call.kwargs["kind"], call.kwargs["feedback"])
        for call in decide.await_args_list
    ]


class TestNothingPending:
    async def test_a_message_with_nothing_pending_asks_no_one(self, decide: AsyncMock) -> None:
        with _pending(), serve_jev(jev_reply_body(("approve", 0.99))) as jev:
            assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes") is None
        jev.post.assert_not_awaited()
        decide.assert_not_awaited()

    async def test_the_pending_set_is_read_for_this_conversation_and_user(
        self, decide: AsyncMock
    ) -> None:
        with _pending() as pending:
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "hey")
        pending.assert_awaited_once_with(CONVERSATION_ID, USER_ID)


class TestSingleApproval:
    async def test_a_confident_yes_approves_it(self, decide: AsyncMock) -> None:
        with _pending(_row("ap_1", "Send email")), serve_jev(jev_reply_body(("approve", 0.99))):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes send it")

        assert action == "approve"
        assert _decided(decide) == [("ap_1", "approve", None)]
        assert decide.await_args.kwargs["via"] == "chat"

    async def test_a_decline_carries_the_reply_verbatim(self, decide: AsyncMock) -> None:
        reply = "no, send it to alice@example.com instead"
        with _pending(_row("ap_1", "Send email")), serve_jev(jev_reply_body(("deny", 0.97))):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, reply)

        assert action == "deny"
        assert _decided(decide) == [("ap_1", "deny", reply)]

    async def test_an_approve_under_the_line_decides_nothing(self, decide: AsyncMock) -> None:
        below = round(HIL_JEV_REPLY_APPROVE_LINE - 0.01, 2)
        with _pending(_row("ap_1", "Send email")), serve_jev(jev_reply_body(("approve", below))):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "maybe")

        assert ("ap_1", "approve", None) not in _decided(decide)

    async def test_moving_on_denies_every_pending_approval_with_the_moved_on_note(
        self, decide: AsyncMock
    ) -> None:
        with (
            _pending(_row("ap_1", "Send email")),
            serve_jev(jev_reply_body(("unrelated", 0.95))),
        ):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "what's the weather"
            )

        assert action == "unrelated"
        assert _decided(decide) == [("ap_1", "deny", UNRELATED_FEEDBACK)]

    async def test_a_failing_classifier_leaves_the_approval_pending(
        self, decide: AsyncMock
    ) -> None:
        with _pending(_row("ap_1", "Send email")), serve_jev(httpx.ConnectError("down")):
            assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes") is None
        decide.assert_not_awaited()


class TestBatch:
    async def test_each_pending_approval_takes_its_own_verdict_oldest_first(
        self, decide: AsyncMock
    ) -> None:
        older, newer = _row("ap_1", "Send A", age_minutes=9), _row("ap_2", "Send B")
        with (
            _pending(older, newer),
            serve_jev(jev_reply_body(("approve", 0.99), ("deny", 0.97))),
        ):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes to A, not B")

        assert action == "approve"
        assert _decided(decide) == [("ap_1", "approve", None), ("ap_2", "deny", "yes to A, not B")]

    async def test_a_failing_classifier_decides_none_of_them(self, decide: AsyncMock) -> None:
        with (
            _pending(_row("ap_1", "Send A"), _row("ap_2", "Send B")),
            serve_jev(httpx.ConnectError("down")),
        ):
            assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes") is None
        decide.assert_not_awaited()


class TestLedgerOutcomeText:
    @pytest.mark.parametrize(
        ("outcome", "action", "said"),
        [
            (None, None, "still pending"),
            (ApprovalOutcome.DENIED, None, "denied by the user; the action did NOT run"),
            (ApprovalOutcome.APPROVED, ActionResult.EXECUTED, "approved by the user and executed"),
        ],
    )
    def test_names_where_the_approval_stands(
        self, outcome: ApprovalOutcome | None, action: ActionResult | None, said: str
    ) -> None:
        assert ledger_outcome_text(outcome, action) == said
