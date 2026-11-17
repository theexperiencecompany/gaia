"""Backfill hosted-model vectors for every live memory that has none.

Safe to run against a live system and to re-run: it only reads live memories
that lack a vector under MEMORY_VECTOR_MODEL, writes nothing else, and bumps each
touched user's vector version so running processes reload that user's set on
their next turn. Also the repair path for a write whose indexing failed.

    uv run python scripts/backfill_memory_vectors.py [--batch 200] [--dry-run]
"""

import argparse
import asyncio
from collections import defaultdict
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.memory import MEMORY_VECTOR_MODEL
from app.db.postgresql import init_postgresql_engine
from app.memory import hosted_embeddings, vector_index
from app.memory.pg_store.vectors import live_memories_without_vector, upsert_vectors
from app.models.memory_db_models import MemoryRecord


async def _embed_and_store(rows: list[MemoryRecord]) -> None:
    vectors = await hosted_embeddings.embed_documents([row.content for row in rows])
    by_user: dict[str, list[tuple[uuid.UUID, list[float]]]] = defaultdict(list)
    for row, vector in zip(rows, vectors, strict=True):
        by_user[row.user_id].append((row.id, vector))
    for user_id, pairs in by_user.items():
        await upsert_vectors(user_id, MEMORY_VECTOR_MODEL, pairs)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", type=int, default=200, help="Memories embedded per round")
    parser.add_argument(
        "--dry-run", action="store_true", help="Count what is missing, write nothing"
    )
    args = parser.parse_args()

    init_postgresql_engine()
    if not hosted_embeddings.configured():
        raise SystemExit("OpenAI is not configured (OPENAI_API_KEY)")

    started = time.perf_counter()
    cursor: uuid.UUID | None = None
    touched: dict[str, int] = defaultdict(int)
    while rows := await live_memories_without_vector(MEMORY_VECTOR_MODEL, cursor, args.batch):
        cursor = rows[-1].id
        if not args.dry_run:
            await _embed_and_store(rows)
        for row in rows:
            touched[row.user_id] += 1
        print(f"{sum(touched.values())} memories, {len(touched)} users", flush=True)

    if not args.dry_run:
        for user_id in touched:
            await vector_index.bump_version(user_id)
    verb = "Would embed" if args.dry_run else "Embedded"
    print(
        f"{verb} {sum(touched.values())} memories for {len(touched)} users under "
        f"{MEMORY_VECTOR_MODEL} in {time.perf_counter() - started:.0f}s"
    )


if __name__ == "__main__":
    asyncio.run(main())
