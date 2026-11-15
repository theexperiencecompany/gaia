"""The approval reply port: an answer acknowledging what was decided, otherwise None, and a failing resolver propagates."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.hil import HIL_ACK_APPROVED, HIL_ACK_DENIED, HIL_CLASSIFIER_HISTORY_TURNS
from app.models.hil_models import ApprovalLedgerDocument
from app.models.message_models import MessageDict
from app.services.conversation.approval_replies import HilApprovalReplies
from app.services.conversation.ports import ApprovalAnswer
from app.services.hil.conversational import ApprovalReplyOutcome

_HISTORY: list[MessageDict] = [
    {"role": "user" if n % 2 == 0 else "assistant", "content": f"turn {n}"} for n in range(6)
]
_RESOLVE = "app.services.conversation.approval_replies.resolve_pending_from_message"


def _row(approval_id: str, tool_name: str) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id=approval_id,
        conversation_id="c1",
        user_id="u1",
        fingerprint=f"fp-{approval_id}",
        tool_name=tool_name,
        args={"to": "bob@example.com"},
        created_at=datetime.now(UTC),
    )


_EMAIL = _row("ap1", "GMAIL_SEND_EMAIL")
_OTHER = _row("ap2", "NOTION_CREATE_PAGE")


@pytest.mark.parametrize(
    ("outcome", "ack"),
    [
        (ApprovalReplyOutcome("approve", (_EMAIL,)), "Got it, I'll send an email."),
        (ApprovalReplyOutcome("deny", (_EMAIL,)), "Understood, I won't send an email."),
        (ApprovalReplyOutcome("approve", (_EMAIL, _OTHER)), HIL_ACK_APPROVED),
        (ApprovalReplyOutcome("deny", (_EMAIL, _OTHER)), HIL_ACK_DENIED),
    ],
)
async def test_a_reply_that_decided_one_action_is_acknowledged_by_name(
    outcome: ApprovalReplyOutcome, ack: str
) -> None:
    with patch(_RESOLVE, AsyncMock(return_value=outcome)) as resolve:
        answer = await HilApprovalReplies().resolve("c1", "u1", "yes", _HISTORY)

    assert answer == ApprovalAnswer(ack=ack)
    resolve.assert_awaited_once_with("c1", "u1", "yes", _HISTORY[-HIL_CLASSIFIER_HISTORY_TURNS:])


@pytest.mark.parametrize("outcome", [ApprovalReplyOutcome("unrelated"), None])
async def test_a_reply_that_decided_nothing_is_no_answer(
    outcome: ApprovalReplyOutcome | None,
) -> None:
    with patch(_RESOLVE, AsyncMock(return_value=outcome)):
        assert await HilApprovalReplies().resolve("c1", "u1", "hi", _HISTORY) is None


async def test_a_yes_with_a_change_answers_with_no_words_of_its_own() -> None:
    """Run 4 bug 20: the work asks again with the change, and that ask is the reply."""
    amend = ApprovalReplyOutcome("approve", (_EMAIL,), amended=(_EMAIL,))

    with patch(_RESOLVE, AsyncMock(return_value=amend)):
        answer = await HilApprovalReplies().resolve("c1", "u1", "yes but cc sam", _HISTORY)

    assert answer == ApprovalAnswer(ack=None)


async def test_a_resolver_failure_propagates_instead_of_reading_as_no_decision() -> None:
    with (
        patch(_RESOLVE, AsyncMock(side_effect=RuntimeError("classifier down"))),
        pytest.raises(RuntimeError, match="classifier down"),
    ):
        await HilApprovalReplies().resolve("c1", "u1", "yes", [])
