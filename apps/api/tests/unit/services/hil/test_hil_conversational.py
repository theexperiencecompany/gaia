"""A chat reply as an approval answer (app/services/hil/conversational.py).

The approvals a reply can answer are the ones the conversation log has pending; JEV is the
one classifier, mocked at its HTTP boundary, so the question building, the approve line and
the mapping onto decisions run for real. Every decision commits through decide_ledger.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.constants.hil import HIL_JEV_REPLY_APPROVE_LINE
from app.models.hil_models import ApprovalLedgerDocument
from app.models.message_models import MessageDict
from app.services.hil.bridge import build_action_detail
from app.services.hil.conversational import ledger_outcome_text, resolve_pending_from_message
from app.services.hil.ledger_decide import LedgerDecision
from shared.py.approvals import ActionResult, ApprovalOutcome

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
def logged() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.log") as mock:
        yield mock


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
    """Each decision taken, after checking it was taken as this user."""
    assert {decided.kwargs["user_id"] for decided in decide.await_args_list} <= {USER_ID}
    return [
        (decided.args[0], decided.kwargs["kind"], decided.kwargs["feedback"])
        for decided in decide.await_args_list
    ]


HISTORY: list[MessageDict] = [
    {"role": "assistant", "content": "Shall I send the email to Bob?"},
    {"role": "user", "content": "let me think"},
]


def _asked_state(jev: AsyncMock) -> object:
    return jev.post.await_args.kwargs["json"]["state"]


def _expected_state(reply: str, *rows: ApprovalLedgerDocument) -> dict[str, object]:
    return {
        "reply": reply,
        "pending_actions": [
            {"number": number, "action": build_action_detail(row.summary, row.args)}
            for number, row in enumerate(rows, start=1)
        ],
        "recent_conversation": HISTORY,
    }


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
        row = _row("ap_1", "Send email")
        with _pending(row), serve_jev(jev_reply_body(("approve", 0.99))):
            outcome = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes send it")

        assert outcome is not None
        assert (outcome.action, outcome.decided, outcome.amended) == ("approve", (row,), ())
        assert _decided(decide) == [("ap_1", "approve", None)]
        assert decide.await_args.kwargs["via"] == "chat"

    async def test_a_decline_carries_the_reply_verbatim(self, decide: AsyncMock) -> None:
        reply = "no, send it to alice@example.com instead"
        with _pending(_row("ap_1", "Send email")), serve_jev(jev_reply_body(("deny", 0.97))):
            outcome = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, reply)

        assert outcome is not None
        assert (outcome.action, outcome.amended) == ("deny", ())
        assert _decided(decide) == [("ap_1", "deny", reply)]

    async def test_a_yes_with_a_change_approves_it_and_carries_the_change(
        self, decide: AsyncMock
    ) -> None:
        """Regression for conversation a0a0b079: "go ahead but make it high priority" was denied."""
        reply = "go ahead but make it high priority"
        row = _row("ap_1", "Create todo")
        with _pending(row), serve_jev(jev_reply_body(("amend", 0.73))):
            outcome = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, reply)

        assert outcome is not None
        assert (outcome.action, outcome.amended) == ("approve", (row,))
        assert _decided(decide) == [("ap_1", "approve", reply)]

    async def test_an_approve_under_the_line_decides_nothing(self, decide: AsyncMock) -> None:
        below = round(HIL_JEV_REPLY_APPROVE_LINE - 0.01, 2)
        with _pending(_row("ap_1", "Send email")), serve_jev(jev_reply_body(("approve", below))):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "maybe")

        assert ("ap_1", "approve", None) not in _decided(decide)

    async def test_moving_on_leaves_the_approval_pending(self, decide: AsyncMock) -> None:
        with (
            _pending(_row("ap_1", "Send email")),
            serve_jev(jev_reply_body(("unrelated", 0.95))),
        ):
            outcome = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "what's the weather"
            )

        assert outcome is not None
        assert outcome.action == "unrelated"
        decide.assert_not_awaited()

    async def test_a_failing_classifier_leaves_the_approval_pending(
        self, decide: AsyncMock
    ) -> None:
        with _pending(_row("ap_1", "Send email")), serve_jev(httpx.ConnectError("down")):
            assert (
                await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "hmm, maybe") is None
            )
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
            outcome = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "yes to A, not B"
            )

        assert outcome is not None
        assert (outcome.action, outcome.decided, outcome.amended) == ("approve", (older, newer), ())
        assert _decided(decide) == [("ap_1", "approve", None), ("ap_2", "deny", "yes to A, not B")]

    async def test_a_yes_with_a_change_to_one_item_approves_it_carrying_the_change(
        self, decide: AsyncMock
    ) -> None:
        reply = "send A, and B but to the team list"
        older, newer = _row("ap_1", "Send A", age_minutes=9), _row("ap_2", "Send B")
        with (
            _pending(older, newer),
            serve_jev(jev_reply_body(("approve", 0.99), ("amend", 0.73))),
        ):
            outcome = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, reply)

        assert outcome is not None
        assert (outcome.action, outcome.amended) == ("approve", (newer,))
        assert _decided(decide) == [("ap_1", "approve", None), ("ap_2", "approve", reply)]

    async def test_declining_every_one_is_a_deny_of_them_all(self, decide: AsyncMock) -> None:
        older, newer = _row("ap_1", "Send A", age_minutes=9), _row("ap_2", "Send B")
        with (
            _pending(older, newer),
            serve_jev(jev_reply_body(("deny", 0.99), ("deny", 0.97))),
        ):
            outcome = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "neither")

        assert outcome is not None
        assert (outcome.action, outcome.decided) == ("deny", (older, newer))

    async def test_a_failing_classifier_decides_none_of_them(self, decide: AsyncMock) -> None:
        with (
            _pending(_row("ap_1", "Send A"), _row("ap_2", "Send B")),
            serve_jev(httpx.ConnectError("down")),
        ):
            assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "hmm") is None
        decide.assert_not_awaited()


class TestWhatTheClassifierReads:
    async def test_one_approval_is_asked_with_the_reply_its_detail_and_the_history(
        self, decide: AsyncMock
    ) -> None:
        row = _row("ap_1", "Send email")
        with _pending(row), serve_jev(jev_reply_body(("approve", 0.99))) as jev:
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes, go", HISTORY)

        assert _asked_state(jev) == _expected_state("yes, go", row)

    async def test_a_batch_is_asked_with_every_detail_and_the_history(
        self, decide: AsyncMock
    ) -> None:
        rows = (_row("ap_1", "Send A"), _row("ap_2", "Send B"))
        with (
            _pending(*rows),
            serve_jev(jev_reply_body(("approve", 0.99), ("approve", 0.99))) as jev,
        ):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "both", HISTORY)

        assert _asked_state(jev) == _expected_state("both", *rows)


class TestMovingOnLeavesEveryApprovalPending:
    @pytest.mark.parametrize("rows", [("ap_1",), ("ap_1", "ap_2")])
    async def test_a_new_request_decides_none_of_them(
        self, decide: AsyncMock, rows: tuple[str, ...]
    ) -> None:
        pending_rows = [_row(approval_id, f"Send {approval_id}") for approval_id in rows]
        verdicts = [("unrelated", 0.95)] * len(rows)
        with _pending(*pending_rows), serve_jev(jev_reply_body(*verdicts)):
            outcome = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "weather?")

        assert outcome is not None
        assert outcome.action == "unrelated"
        decide.assert_not_awaited()


class TestWhatIsLogged:
    @pytest.mark.parametrize("rows", [("ap_1",), ("ap_1", "ap_2")])
    async def test_a_failing_classifier_is_logged_as_an_error(
        self, decide: AsyncMock, logged: MagicMock, rows: tuple[str, ...]
    ) -> None:
        pending_rows = [_row(approval_id, "Send") for approval_id in rows]
        with _pending(*pending_rows), serve_jev(httpx.ConnectError("down")):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "hmm")

        logged.error.assert_called_once_with(
            "[HIL] JEV reply classifier failed; the approvals stay pending",
            error="down",
            error_type="ConnectError",
        )

    @pytest.mark.parametrize(
        ("outcome", "action", "said"),
        [
            (ApprovalOutcome.APPROVED, ActionResult.EXECUTED, "approved by the user and executed"),
            (ApprovalOutcome.DENIED, None, "denied by the user; the action did NOT run"),
        ],
    )
    async def test_a_decision_the_log_already_took_is_logged_with_where_it_stands(
        self,
        logged: MagicMock,
        outcome: ApprovalOutcome,
        action: ActionResult | None,
        said: str,
    ) -> None:
        lost = LedgerDecision(committed=False, approval_id="ap_1", outcome=outcome, action=action)
        with (
            _pending(_row("ap_1", "Send email")),
            serve_jev(jev_reply_body(("approve", 0.99))),
            patch(f"{MODULE}.decide_ledger", new=AsyncMock(return_value=lost)),
        ):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes, go")

        logged.warning.assert_called_once_with(
            "[HIL] Ledger bot decision lost the race",
            approval_id="ap_1",
            outcome=said,
        )


class TestThePromptsOwnGrammarNeedsNoModel:
    """The bot prompt offers yes / no, and "yes 1 and 3" for several: those replies decide with JEV down."""

    @pytest.mark.parametrize("reply", ["yes", "Yes!", "*yes*", " y ", "ok", "approve", "yes 1"])
    async def test_a_plain_yes_approves_the_one_approval(
        self, decide: AsyncMock, reply: str
    ) -> None:
        row = _row("ap_1", "Send email")
        with _pending(row), serve_jev(httpx.HTTPError("402 Payment Required")) as jev:
            outcome = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, reply)

        assert outcome is not None
        assert (outcome.action, outcome.decided) == ("approve", (row,))
        assert _decided(decide) == [("ap_1", "approve", None)]
        jev.post.assert_not_awaited()

    @pytest.mark.parametrize("reply", ["no", "No.", "nope", "cancel"])
    async def test_a_plain_no_denies_the_one_approval_with_no_correction(
        self, decide: AsyncMock, reply: str
    ) -> None:
        with _pending(_row("ap_1", "Send email")), serve_jev(httpx.HTTPError("402")) as jev:
            outcome = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, reply)

        assert outcome is not None
        assert outcome.action == "deny"
        assert _decided(decide) == [("ap_1", "deny", None)]
        jev.post.assert_not_awaited()

    @pytest.mark.parametrize(
        ("reply", "expected"),
        [
            ("yes", [("ap_1", "approve"), ("ap_2", "approve"), ("ap_3", "approve")]),
            ("no", [("ap_1", "deny"), ("ap_2", "deny"), ("ap_3", "deny")]),
            ("yes 1 and 3", [("ap_1", "approve"), ("ap_3", "approve")]),
            ("Yes 3, 1", [("ap_1", "approve"), ("ap_3", "approve")]),
            ("no 2", [("ap_2", "deny")]),
        ],
    )
    async def test_a_batch_reply_in_the_prompts_grammar_decides_the_named_items(
        self, decide: AsyncMock, reply: str, expected: list[tuple[str, str]]
    ) -> None:
        rows = [_row(f"ap_{n}", f"Send {n}", age_minutes=10 - n) for n in (1, 2, 3)]
        with _pending(*rows), serve_jev(httpx.HTTPError("402")) as jev:
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, reply)

        assert [(approval_id, kind) for approval_id, kind, _ in _decided(decide)] == expected
        jev.post.assert_not_awaited()

    @pytest.mark.parametrize(
        ("reply", "pending"),
        [
            ("yes but cc finance", 1),
            ("yes 2", 1),  # no item 2: not the grammar, so the classifier reads it
            ("yes 4", 3),
            ("yes 0", 3),
            ("1", 1),
            ("add a todo called yes", 1),
        ],
    )
    async def test_anything_else_goes_to_the_classifier(
        self, decide: AsyncMock, reply: str, pending: int
    ) -> None:
        rows = [_row(f"ap_{n}", f"Send {n}") for n in range(1, pending + 1)]
        verdicts = [("unrelated", 0.95)] * pending
        with _pending(*rows), serve_jev(jev_reply_body(*verdicts)) as jev:
            outcome = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, reply)

        jev.post.assert_awaited_once()
        assert outcome is not None and outcome.action == "unrelated"
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
