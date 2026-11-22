"""Attacks on the approval bridge (app/services/hil/bridge.py)."""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from app.services.hil.bridge import announce_approval
from app.services.hil.utils import GatedApproval, GatedCall

from .conftest import CONVERSATION_ID, USER_ID

MODULE = "app.services.hil.bridge"

APPROVAL = GatedApproval(
    approval_id="ap_1",
    stream_id="stream_1",
    user_id=USER_ID,
    conversation_id=CONVERSATION_ID,
    tool_call=GatedCall(name="send_email", id="call_1", args={"to": "ada@example.com"}),
    summary="Send an email to ada@example.com",
    question="OK to email ada@example.com?",
    integration_name="Gmail",
)


@dataclass
class _Seams:
    push: MagicMock
    spawn: MagicMock


@pytest.fixture
def seams() -> Iterator[_Seams]:
    with (
        patch(f"{MODULE}.capture"),
        patch(f"{MODULE}.notify_approval_pending", MagicMock(return_value="push")) as push,
        patch(f"{MODULE}.spawn_logged_task") as spawn,
    ):
        yield _Seams(push=push, spawn=spawn)


class TestAnnounceApproval:
    async def test_the_push_names_this_approval_and_runs_detached(self, seams: _Seams) -> None:
        """Detached, so a push that fails can never hold the gate."""
        await announce_approval(APPROVAL, background=False)

        seams.push.assert_called_once_with(APPROVAL)
        seams.spawn.assert_called_once_with(
            "approval_pending_notification",
            "push",
            user={"id": USER_ID},
            conversation_id=CONVERSATION_ID,
            approval_id="ap_1",
        )
