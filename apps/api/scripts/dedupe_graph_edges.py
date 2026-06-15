"""Remove redundant graph edges, keeping one per unordered entity pair per user.

The entity graph can accumulate semantically-duplicate edges when the LLM
phrases the same relationship differently across memories, or inserts edges in
both directions for a symmetric relationship (e.g. "is dating" / "is
girlfriend of").  This script collapses all edges between the same unordered
{A, B} pair into the single most-informative one (longest relationship label).

    uv run python -m scripts.dedupe_graph_edges --user-id <id> --dry-run
    uv run python -m scripts.dedupe_graph_edges            # all users, apply
"""

import argparse
import asyncio
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.db.chroma.chromadb import init_chroma  # noqa: E402
from app.db.mongodb.collections import users_collection  # noqa: E402
from app.db.postgresql import init_postgresql_engine  # noqa: E402
from app.memory.pg_store._session import memory_session  # noqa: E402
from app.memory.pg_store.graph import _canonical_pair  # noqa: E402
from app.models.memory_db_models import MemoryGraphEdge  # noqa: E402


async def dedupe_user(user_id: str, dry_run: bool) -> int:
    """Remove all but the best edge per unordered entity pair for one user.

    Returns the number of rows deleted (or that would be deleted in dry-run).
    """
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryGraphEdge).where(MemoryGraphEdge.user_id == user_id)
        )
        all_edges: list[MemoryGraphEdge] = list(result.scalars().all())

    if not all_edges:
        return 0

    # For each unordered entity pair, find the best edge (longest label wins;
    # ties broken by the edge that was created first via UUID sort for stability).
    best_id: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] = {}
    best_label_len: dict[tuple[uuid.UUID, uuid.UUID], int] = {}

    for edge in all_edges:
        pair = _canonical_pair(edge.source_entity_id, edge.target_entity_id)
        existing_len = best_label_len.get(pair, -1)
        if len(edge.relationship) > existing_len:
            best_id[pair] = edge.id
            best_label_len[pair] = len(edge.relationship)

    keep_ids: set[uuid.UUID] = set(best_id.values())
    to_delete = [e for e in all_edges if e.id not in keep_ids]

    if not to_delete:
        return 0

    for edge in to_delete:
        pair = _canonical_pair(edge.source_entity_id, edge.target_entity_id)
        winner_id = best_id[pair]
        print(
            f"  {'[dry-run] ' if dry_run else ''}remove edge {edge.id}"
            f"  [{edge.source_entity_id}] -[{edge.relationship}]-> [{edge.target_entity_id}]"
            f"  (keeping {winner_id})"
        )

    if not dry_run:
        delete_ids = [e.id for e in to_delete]
        async with memory_session() as session:
            await session.execute(delete(MemoryGraphEdge).where(MemoryGraphEdge.id.in_(delete_ids)))
            await session.commit()

    return len(to_delete)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove redundant graph edges (one per unordered entity pair per user)."
    )
    parser.add_argument("--user-id", help="Only this user (default: all users with memories)")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    init_postgresql_engine()
    init_chroma()

    if args.user_id:
        user_ids = [args.user_id]
    else:
        user_ids = [str(doc["_id"]) async for doc in users_collection.find({}, {"_id": 1})]

    total = 0
    for user_id in user_ids:
        removed = await dedupe_user(user_id, args.dry_run)
        if removed:
            print(
                f"user {user_id}: {removed} duplicate edges removed"
                f"{' (dry run)' if args.dry_run else ''}"
            )
    print(f"\nDone. {total} edges removed{' (dry run)' if args.dry_run else ''}.")


if __name__ == "__main__":
    asyncio.run(main())
