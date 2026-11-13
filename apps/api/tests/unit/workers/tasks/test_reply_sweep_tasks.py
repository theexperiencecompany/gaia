"""Unit tests for app.workers.tasks.reply_sweep_tasks."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.chat import TURN_INTERRUPTED
from app.workers.tasks.reply_sweep_tasks import sweep_unfinished_replies

MODULE = "app.workers.tasks.reply_sweep_tasks"


@pytest.mark.unit
async def test_the_sweep_fails_only_the_replies_whose_turn_is_dead() -> None:
    owners = {("u1", "c1"), ("u2", "c2"), ("u3", "c3")}

    async def active(user_id: str, conversation_id: str) -> str | None:
        return "stream" if conversation_id == "c2" else None

    with (
        patch(
            f"{MODULE}.conversation_repository.list_unfinished_reply_owners",
            AsyncMock(return_value=owners),
        ) as list_owners,
        patch(f"{MODULE}.stream_manager.get_active_stream_id", side_effect=active),
        patch(
            f"{MODULE}.conversation_repository.fail_unfinished_replies",
            AsyncMock(return_value=2),
        ) as fail,
        patch(f"{MODULE}.log", MagicMock()) as log,
    ):
        assert await sweep_unfinished_replies({}) == "failed=2"

    list_owners.assert_awaited_once()
    opened_before = list_owners.await_args.kwargs["opened_before"]
    assert datetime.now(UTC) - timedelta(minutes=6) <= opened_before < datetime.now(UTC)
    fail.assert_awaited_once()
    assert fail.await_args.kwargs["error"] == TURN_INTERRUPTED
    assert fail.await_args.kwargs["owners"] == {("u1", "c1"), ("u3", "c3")}
    assert fail.await_args.kwargs["opened_before"] == opened_before
    log.set.assert_called_once_with(unfinished_reply_conversations=3, failed_reply_count=2)
