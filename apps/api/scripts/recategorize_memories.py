"""Re-file existing memories into the corrected folder taxonomy.

A one-off maintenance pass: re-runs the categorize LLM on every live memory
(ignoring the user's current — possibly polluted — folder tree so the canonical
taxonomy decides fresh) and updates ``category_path`` where it changed. Updating
the folder also refreshes the generated FTS column, and the next consolidation
rebuilds the core documents from the corrected folders.

    uv run python -m scripts.recategorize_memories --user-id <id> --dry-run
    uv run python -m scripts.recategorize_memories            # all users, apply
"""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import update  # noqa: E402

from app.agents.llm.client import register_llm_providers  # noqa: E402
from app.db.chroma.chromadb import init_chroma  # noqa: E402
from app.db.mongodb.collections import users_collection  # noqa: E402
from app.db.postgresql import init_postgresql_engine  # noqa: E402
from app.memory import pg_store  # noqa: E402
from app.memory.engine import memory_engine  # noqa: E402
from app.memory.extraction import categorize_fact  # noqa: E402
from app.memory.pg_store._session import memory_session  # noqa: E402
from app.models.memory_db_models import MemoryRecord  # noqa: E402

# Re-file against the canonical taxonomy, not the user's existing folders, so a
# fact wrongly sitting in (say) work/gaia is judged afresh.
_EMPTY_TREE = "(none yet)"


async def recategorize_user(user_id: str, dry_run: bool) -> int:
    rows = await pg_store.get_all_live_memories(user_id)
    if not rows:
        return 0
    now = datetime.now(UTC)
    moved = 0
    for row in rows:
        categorization = await categorize_fact(
            row.content, folder_tree=_EMPTY_TREE, current_date=now
        )
        if categorization is None:
            continue
        new_path = categorization.category_path
        if not new_path or new_path == row.category_path:
            continue
        moved += 1
        print(f"  [{row.category_path}] -> [{new_path}]  {row.content[:60]}")
        if not dry_run:
            async with memory_session() as session:
                await session.execute(
                    update(MemoryRecord)
                    .where(MemoryRecord.id == row.id)
                    .values(category_path=new_path)
                )
                await session.commit()
    if moved and not dry_run:
        # Rebuild the core documents from the corrected folders.
        await memory_engine.consolidate(user_id)
    return moved


async def main() -> None:
    parser = argparse.ArgumentParser(description="Re-file memories into the corrected taxonomy.")
    parser.add_argument("--user-id", help="Only this user (default: all users with memories)")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    init_postgresql_engine()
    init_chroma()
    register_llm_providers()

    if args.user_id:
        user_ids = [args.user_id]
    else:
        user_ids = [str(doc["_id"]) async for doc in users_collection.find({}, {"_id": 1})]

    total = 0
    for user_id in user_ids:
        moved = await recategorize_user(user_id, args.dry_run)
        if moved:
            print(
                f"user {user_id}: {moved} memories re-filed{' (dry run)' if args.dry_run else ''}"
            )
        total += moved
    print(f"\nDone. {total} memories re-filed{' (dry run)' if args.dry_run else ''}.")


if __name__ == "__main__":
    asyncio.run(main())
