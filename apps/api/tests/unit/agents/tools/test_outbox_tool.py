"""Comms' view of the outbox, and its hand on an untold update."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.outbox_tool import DROP_REASONS, HOLD_REASONS, change_update
from app.constants.outbox_attention import HoldReason
from app.models.user_models import AuthenticatedUser
from app.services.outbox.models import DropReason

USER = "6812f0b3c9a14e2b7d5a91cc"
MODULE = "app.agents.tools.outbox_tool"
CONFIG = {"configurable": {"user_id": USER}}


def test_every_hold_and_drop_reason_has_words_comms_can_explain() -> None:
    assert set(HOLD_REASONS) == set(HoldReason)
    assert set(DROP_REASONS) == set(DropReason)


@pytest.mark.parametrize(
    ("action", "service"), [("send_now", "send_now"), ("cancel", "cancel_update")]
)
async def test_each_action_reaches_its_service_for_the_ref(action: str, service: str) -> None:
    called = AsyncMock(return_value=True)
    with patch(f"{MODULE}.{service}", called):
        reply = await change_update.ainvoke({"ref": "run-1", "action": action}, config=CONFIG)

    called.assert_awaited_once_with(USER, "run-1")
    assert reply == "Done."


async def test_a_time_without_a_zone_is_on_the_users_own_clock() -> None:
    tell = AsyncMock(return_value=True)
    with (
        patch(f"{MODULE}.tell_at", tell),
        patch(
            f"{MODULE}.load_user_context",
            AsyncMock(return_value=AuthenticatedUser(user_id=USER, timezone="Asia/Kolkata")),
        ),
    ):
        await change_update.ainvoke(
            {"ref": "run-1", "action": "tell_at", "at": "2026-11-10T21:00:00"}, config=CONFIG
        )

    assert tell.await_args.args[2] == datetime(2026, 11, 10, 15, 30, tzinfo=UTC)


async def test_tell_at_without_a_time_changes_nothing_and_says_why() -> None:
    reply = await change_update.ainvoke({"ref": "run-1", "action": "tell_at"}, config=CONFIG)

    assert reply.startswith("Not changed")


async def test_an_update_already_told_is_said_to_be_unchanged() -> None:
    with patch(f"{MODULE}.cancel_update", AsyncMock(return_value=False)):
        reply = await change_update.ainvoke({"ref": "run-1", "action": "cancel"}, config=CONFIG)

    assert reply.startswith("Not changed")
