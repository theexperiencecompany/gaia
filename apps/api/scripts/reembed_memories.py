"""Re-embed every stored memory and episode summary with the current model.

Run after changing EMBEDDING_MODEL_NAME / EMBEDDING_DIM: vector dimensions are
fixed per Chroma collection, so both memory collections are dropped, recreated,
and refilled from the canonical Postgres rows (live facts and summarized
episodes; superseded/forgotten rows are not re-indexed — recall never returns
them).

    uv run python -m scripts.reembed_memories            # all users
    uv run python -m scripts.reembed_memories --user-id <id>
"""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from app.constants.memory import (  # noqa: E402
    CHROMA_MEMORIES_COLLECTION,
    CHROMA_MEMORY_EPISODES_COLLECTION,
)
from app.db.chroma.chromadb import ChromaClient, init_chroma  # noqa: E402
from app.db.postgresql import init_postgresql_engine  # noqa: E402
from app.memory import chroma_store  # noqa: E402
from app.memory.chroma_store import EpisodeVectorItem, MemoryVectorItem  # noqa: E402
from app.memory.embeddings import embed_batch  # noqa: E402
from app.memory.pg_store._session import memory_session  # noqa: E402
from app.models.memory_db_models import MemoryEpisode, MemoryRecord  # noqa: E402

_BATCH = 64


async def _drop_collections() -> None:
    client = await ChromaClient.get_client()
    existing = {collection.name for collection in await client.list_collections()}
    for name in (CHROMA_MEMORIES_COLLECTION, CHROMA_MEMORY_EPISODES_COLLECTION):
        if name in existing:
            await client.delete_collection(name)
            print(f"dropped collection {name}")


async def _reembed_memories(user_id: str | None) -> int:
    async with memory_session() as session:
        query = select(MemoryRecord).where(
            MemoryRecord.is_latest.is_(True), MemoryRecord.is_forgotten.is_(False)
        )
        if user_id:
            query = query.where(MemoryRecord.user_id == user_id)
        rows = list((await session.execute(query)).scalars().all())

    for start in range(0, len(rows), _BATCH):
        batch = rows[start : start + _BATCH]
        embeddings = await embed_batch([row.content for row in batch])
        items: list[MemoryVectorItem] = [
            {
                "id": str(row.id),
                "embedding": embedding,
                "document": row.content,
                "metadata": {
                    "user_id": row.user_id,
                    "kind": row.kind,
                    "category_path": row.category_path,
                    "is_latest": True,
                    "is_forgotten": False,
                },
            }
            for row, embedding in zip(batch, embeddings)
        ]
        await chroma_store.upsert_memories(items)
    return len(rows)


async def _reembed_episodes(user_id: str | None) -> int:
    async with memory_session() as session:
        query = select(MemoryEpisode).where(MemoryEpisode.summary.is_not(None))
        if user_id:
            query = query.where(MemoryEpisode.user_id == user_id)
        episodes = list((await session.execute(query)).scalars().all())

    for episode in episodes:
        if not episode.summary:
            continue
        embedding = (await embed_batch([episode.summary]))[0]
        item: EpisodeVectorItem = {
            "id": f"{episode.user_id}:{episode.date.isoformat()}",
            "embedding": embedding,
            "document": episode.summary,
            "metadata": {"user_id": episode.user_id, "date": episode.date.isoformat()},
        }
        await chroma_store.upsert_episode(item)
    return len(episodes)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Re-embed memory vectors with the current model.")
    parser.add_argument("--user-id", help="Only this user (default: all users)")
    args = parser.parse_args()

    init_postgresql_engine()
    init_chroma()

    # A model change always changes every vector, so collections are rebuilt
    # wholesale (drop only when re-embedding all users).
    if not args.user_id:
        await _drop_collections()
    memories = await _reembed_memories(args.user_id)
    episodes = await _reembed_episodes(args.user_id)
    print(f"Done. Re-embedded {memories} memories and {episodes} episode summaries.")


if __name__ == "__main__":
    asyncio.run(main())
