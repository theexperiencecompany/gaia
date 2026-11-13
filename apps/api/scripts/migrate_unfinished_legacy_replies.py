"""One-time migration: settle the legacy chat replies left in progress when the chat stream was removed.

The deleted /chat-stream path saved a bot message as in_progress when the user saw it
begin, and a per-minute cron failed the ones whose turn had died. Nothing writes
in_progress any more, so every reply still marked so belongs to a turn that died with
the old stream: each one is marked failed with the interrupted-turn error, as the cron
would have. Replies on the conversation log are settled by the step's own sweeper.

Run once after the deploy that removes the chat stream:

    cd apps/api && uv run python scripts/migrate_unfinished_legacy_replies.py [--apply]

Re-running is safe: a settled reply is no longer in progress.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.chat import TURN_INTERRUPTED
from app.db.repositories.conversations import conversation_repository


async def migrate(*, apply: bool) -> None:
    now = datetime.now(UTC)
    owners = await conversation_repository.list_unfinished_reply_owners(opened_before=now)
    print(f"{len(owners)} conversations hold a legacy reply still in progress")
    if not apply:
        print("Re-run with --apply to settle them as failed.")
        return
    failed = await conversation_repository.fail_unfinished_replies(
        opened_before=now, error=TURN_INTERRUPTED, owners=owners
    )
    print(f"settled {failed} replies as failed")


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
