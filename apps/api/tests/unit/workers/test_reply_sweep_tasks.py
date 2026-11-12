"""The unfinished-reply sweep fails only the replies no running turn owns, opened before a stream's lifetime."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.constants.cache import STREAM_TTL
from app.constants.chat import TURN_INTERRUPTED
from app.workers.tasks.reply_sweep_tasks import sweep_unfinished_replies

MODULE = "app.workers.tasks.reply_sweep_tasks"
DEAD = ("user-1", "conv-dead")
LIVE = ("user-1", "conv-live")


async def _sweep(owners: set[tuple[str, str]], failed: int) -> tuple[str, MagicMock, datetime]:
    repo = MagicMock()
    repo.list_unfinished_reply_owners = AsyncMock(return_value=owners)
    repo.fail_unfinished_replies = AsyncMock(return_value=failed)
    streams = MagicMock()
    streams.get_active_stream_id = AsyncMock(
        side_effect=lambda user_id, conversation_id: (
            "stream-live" if (user_id, conversation_id) == LIVE else None
        )
    )
    before = datetime.now(UTC)
    with (
        patch(f"{MODULE}.conversation_repository", repo),
        patch(f"{MODULE}.stream_manager", streams),
    ):
        result = await sweep_unfinished_replies({})
    return result, repo, before


async def test_only_replies_without_a_live_stream_are_failed_with_the_interruption_text() -> None:
    result, repo, before = await _sweep({DEAD, LIVE}, failed=1)

    assert result == "failed=1"
    kwargs = repo.fail_unfinished_replies.await_args.kwargs
    assert kwargs["owners"] == {DEAD}
    assert kwargs["error"] == TURN_INTERRUPTED
    cutoff = before - timedelta(seconds=STREAM_TTL)
    assert abs((kwargs["opened_before"] - cutoff).total_seconds()) < 5
    assert repo.list_unfinished_reply_owners.await_args.kwargs == {
        "opened_before": kwargs["opened_before"]
    }


async def test_a_sweep_with_every_turn_still_running_fails_nothing() -> None:
    result, repo, _ = await _sweep({LIVE}, failed=0)

    assert result == "failed=0"
    assert repo.fail_unfinished_replies.await_args.kwargs["owners"] == set()
