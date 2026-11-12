"""The approval reply port: approve or deny, otherwise None, and a failing classifier never raises."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.conversation.approval_replies import HilApprovalReplies

_RESOLVE = "app.services.conversation.approval_replies.resolve_pending_from_message"


@pytest.mark.parametrize(
    ("action", "decision"),
    [("approve", "approve"), ("deny", "deny"), ("unrelated", None), (None, None)],
)
async def test_only_an_approve_or_deny_is_a_decision(
    action: str | None, decision: str | None
) -> None:
    with patch(_RESOLVE, AsyncMock(return_value=action)) as resolve:
        assert await HilApprovalReplies().classify("c1", "u1", "yes") == decision
    resolve.assert_awaited_once_with("c1", "u1", "yes")


async def test_a_classifier_failure_reads_as_no_decision() -> None:
    with patch(_RESOLVE, AsyncMock(side_effect=RuntimeError("classifier down"))):
        assert await HilApprovalReplies().classify("c1", "u1", "yes") is None
