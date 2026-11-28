#!/usr/bin/env python3
"""Delete the empty chats that system workflows with their own pipeline were given.

Until the fire skipped it, every briefing fire opened a chat titled after its workflow
("Daily Briefing") that nothing was ever written to, beside the real Briefings chat.
Only a chat with no log entries is deleted; one with entries is reported, never touched.
Nothing ran in these chats, so there are no links, artifacts, files or checkpoints to clean.

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
    entries: int


async def bound_chats() -> list[BoundChat]:
    """Every workflow-execution chat whose workflow runs its own pipeline, with its entry count."""
    workflow_ids = await get_async_collection("workflows").distinct(
        "_id", {"system_workflow_key": {"$in": sorted(SYSTEM_RUNS)}}
    )
    cursor = get_async_collection("conversations").find(
        {
            "system_purpose": SystemPurpose.WORKFLOW_EXECUTION.value,
            "metadata.workflow_id": {"$in": workflow_ids},
        },
        {"_id": 0, "conversation_id": 1, "user_id": 1, "description": 1},
    )
    entries = get_async_collection("conversation_entries")
    return [
        BoundChat(
            conversation_id=row["conversation_id"],
            user_id=row["user_id"],
            title=row.get("description", ""),
            entries=await entries.count_documents({"conversation_id": row["conversation_id"]}),
        )
        async for row in cursor
    ]


async def main() -> None:
    apply = apply_requested(__doc__)
    chats = await bound_chats()
    empty = [chat for chat in chats if chat.entries == 0]
    print("APPLYING" if apply else "DRY RUN: nothing will be written")
    print(f"{len(chats)} bound chat(s), {len(empty)} empty")
    for chat in chats:
        verdict = "delete" if chat.entries == 0 else f"keep ({chat.entries} entries)"
        print(f"  {chat.conversation_id}  user={chat.user_id}  {chat.title!r}  {verdict}")
    if not apply:
        print("\nRe-run with --apply to delete the empty ones.")
        return
    deleted = 0
    for chat in empty:
        deleted += await conversation_repository.delete(chat.conversation_id, user_id=chat.user_id)
    print(f"\ndeleted {deleted} of {len(empty)}")
    if deleted != len(empty):
        raise RuntimeError(f"{len(empty) - deleted} empty chat(s) were not deleted")


if __name__ == "__main__":
    asyncio.run(main())
