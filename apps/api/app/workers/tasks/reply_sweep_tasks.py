"""ARQ cron task: settle replies whose turn died after the user saw them begin."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from app.constants.cache import STREAM_TTL
from app.constants.chat import TURN_INTERRUPTED
from app.core.stream_manager import stream_manager
from app.db.repositories.conversations import conversation_repository
from shared.py.wide_events import log


async def sweep_unfinished_replies(ctx: Mapping[str, object]) -> str:  # noqa: ARG001 -- contract
    """Mark failed every reply in progress for longer than a stream outlives its last refresh, unless its turn still runs.

    A running turn refreshes its conversation's active-stream key, so a reply older
    than STREAM_TTL with no such key belongs to a turn no process is running.
    """
    opened_before = datetime.now(UTC) - timedelta(seconds=STREAM_TTL)
    owners = await conversation_repository.list_unfinished_reply_owners(opened_before=opened_before)
    dead = {
        (user_id, conversation_id)
        for user_id, conversation_id in owners
        if await stream_manager.get_active_stream_id(user_id, conversation_id) is None
    }
    failed = await conversation_repository.fail_unfinished_replies(
        opened_before=opened_before, error=TURN_INTERRUPTED, owners=dead
    )
    log.set(unfinished_reply_conversations=len(owners), failed_reply_count=failed)
    return f"failed={failed}"
