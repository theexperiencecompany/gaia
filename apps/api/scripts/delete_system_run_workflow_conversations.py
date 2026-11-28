#!/usr/bin/env python3
"""Delete the empty chats that system workflows with their own pipeline were given.

Until the fire skipped it, every briefing fire opened a chat titled after its workflow
("Daily Briefing") that nothing was ever written to, beside the real Briefings chat.
Only a chat nothing was ever committed to (log_head 0, outbox included) is deleted, and the
delete re-checks that, so a message landing meanwhile keeps its chat. Nothing ran in these
chats, so there are no links, artifacts, files or checkpoints to clean.

Run from the api directory (or /app inside the container):

    python scripts/delete_system_run_workflow_conversations.py           # report only
    python scripts/delete_system_run_workflow_conversations.py --apply   # delete them
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import get_async_collection
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import SystemPurpose
from app.services.system_workflows.runs import SYSTEM_RUNS
from scripts._cli import apply_requested


@dataclass(frozen=True)
class BoundChat:
    """A workflow-execution chat bound to a self-running system workflow."""

    conversation_id: str
    user_id: str
    title: str
    log_head: int


async def bound_chats() -> list[BoundChat]:
    """Every workflow-execution chat whose workflow runs its own pipeline, with its log head."""
    workflow_ids = await get_async_collection("workflows").distinct(
        "_id", {"system_workflow_key": {"$in": sorted(SYSTEM_RUNS)}}
    )
    cursor = get_async_collection("conversations").find(
        {
            "system_purpose": SystemPurpose.WORKFLOW_EXECUTION.value,
            "metadata.workflow_id": {"$in": workflow_ids},
        },
        {"_id": 0, "conversation_id": 1, "user_id": 1, "description": 1, "log_head": 1},
    )
    return [
        BoundChat(
            conversation_id=row["conversation_id"],
            user_id=row["user_id"],
            title=row.get("description", ""),
            log_head=row.get("log_head") or 0,
        )
        async for row in cursor
    ]


async def main() -> None:
    apply = apply_requested(__doc__)
    chats = await bound_chats()
    empty = [chat for chat in chats if chat.log_head == 0]
    print("APPLYING" if apply else "DRY RUN: nothing will be written")
    print(f"{len(chats)} bound chat(s), {len(empty)} empty")
    for chat in chats:
        verdict = "delete" if chat.log_head == 0 else f"keep (log head {chat.log_head})"
        print(f"  {chat.conversation_id}  user={chat.user_id}  {chat.title!r}  {verdict}")
    if not apply:
        print("\nRe-run with --apply to delete the empty ones.")
        return
    deleted = 0
    for chat in empty:
        deleted += await conversation_repository.delete_if_never_written(
            chat.conversation_id, user_id=chat.user_id
        )
    print(f"\ndeleted {deleted} of {len(empty)}")
    if deleted != len(empty):
        print(f"{len(empty) - deleted} chat(s) were written to since the scan and were kept")


if __name__ == "__main__":
    asyncio.run(main())
