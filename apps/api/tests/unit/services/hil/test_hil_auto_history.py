"""Auto mode's memory (app/services/hil/intent.py: AutoHistory).

Past decisions bias the judge: a tool the user keeps denying stops
auto-approving until the pattern flips. A history the store cannot produce
reads as "no signal", never as authorization.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.hil_models import ApprovalLedgerDocument
from app.services.hil.intent import (
    AutoContext,
    AutoHistory,
    IntentDecision,
    JudgedCall,
    history_line,
    judge_intent,
    summarize_history,
)
from shared.py.analytics.catalog.hil import ActionResult, ApprovalOutcome
from tests.helpers import ledger_facts

MODULE = "app.services.hil.intent"
USER_TURNS = ["draft an email to bob about the deck", "looks good, send it"]


def _row(state: ApprovalOutcome | ActionResult | None, **overrides: Any) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        **{
            "approval_id": "ap_x",
            "conversation_id": "c",
            "user_id": "u",
            "fingerprint": "f",
            "tool_name": "send_email",
            "args": {},
            "summary": "s",
            **ledger_facts(state),
            "decided_at": datetime.now(UTC),
            **overrides,
        }
    )


def test_counts_and_last_deny_come_from_the_rows() -> None:
    now = datetime.now(UTC)
    rows = [
        _row(ApprovalOutcome.DENIED, feedback="too pricey", decided_at=now),
        _row(ActionResult.EXECUTED, decided_at=now - timedelta(days=1)),
        _row(ApprovalOutcome.DENIED, feedback="older", decided_at=now - timedelta(days=2)),
    ]
    h = summarize_history(rows)
    assert (h.approved_recent, h.denied_recent) == (1, 2)
    assert h.last_deny_feedback == "too pricey"


def test_blank_rows_are_no_signal() -> None:
    assert summarize_history([]) == AutoHistory()


class _AllowingJudge:
    """A judge that authorizes every call it is asked about, so only the history can hold one back."""

    async def decide(self, **_: object) -> IntentDecision:
        return IntentDecision(outcome="accept", reason="You asked to email Bob the deck.")


async def _judge(history: AutoHistory) -> IntentDecision:
    """Real judge_intent with a judge that allows: what comes back is the history's doing."""
    return await judge_intent(
        AutoContext(user_id="u", history=history),
        user_messages=USER_TURNS,
        call=JudgedCall(
            tool_name="send_email",
            description="Send an email.",
            args={"to": "bob@example.com"},
            summary="Send email",
        ),
        prior_calls=[],
        judge=_AllowingJudge(),
    )


async def test_mostly_approved_history_leaves_an_allowed_call_accepted() -> None:
    history = AutoHistory(approved_recent=5, denied_recent=1)
    d = await _judge(history)
    assert d.outcome == "accept"


async def test_no_history_is_no_signal_and_leaves_an_allowed_call_accepted() -> None:
    d = await _judge(AutoHistory())
    assert d.outcome == "accept"


def test_the_newest_deny_wins_whatever_the_row_order() -> None:
    now = datetime.now(UTC)
    rows = [
        _row(ApprovalOutcome.DENIED, feedback="undated", decided_at=None),
        _row(ApprovalOutcome.DENIED, feedback="older", decided_at=now - timedelta(days=2)),
        _row(ApprovalOutcome.DENIED, feedback="newest", decided_at=now),
    ]

    h = summarize_history(rows)

    assert (h.last_deny_feedback, h.last_deny_at) == ("newest", now)


def test_known_targets_come_only_from_approved_runs_capped_at_twenty() -> None:
    approved = [_row(ActionResult.EXECUTED, args={"to": f"friend{i}@x.com"}) for i in range(25)]
    denied = _row(ApprovalOutcome.DENIED, args={"to": "stranger@x.com"})

    h = summarize_history([denied, *approved])

    assert h.known_targets == tuple(f"friend{i}@x.com" for i in range(20))


def test_history_line_with_only_approvals_still_reports_counts() -> None:
    line = history_line(AutoHistory(approved_recent=2), "send_email")

    assert line == "Recent decisions on send_email: 2 approved, 0 denied."


def test_history_line_carries_the_last_reason_and_eight_known_targets() -> None:
    targets = tuple(f"t{i}@x.com" for i in range(9))
    history = AutoHistory(
        approved_recent=3, denied_recent=1, last_deny_feedback="too pricey", known_targets=targets
    )

    line = history_line(history, "send_email")

    assert line == (
        "Recent decisions on send_email: 3 approved, 1 denied. Latest deny reason: "
        "'too pricey'. Known from past runs: " + ", ".join(targets[:8]) + "."
    )
