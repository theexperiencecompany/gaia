"""Direct-store seed/inspect helpers for the memory engine suite.

Seeding goes through the production storage layer (pg_store + chroma_store
+ real fastembed embeddings) so retrieval tests exercise the same persisted
shape ingestion produces. Inspection helpers read Postgres/Chroma directly
so tests assert on persisted state, not on return values.
"""

import asyncio
from datetime import datetime
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Any, TypedDict
import uuid
import warnings
import zipfile

import numpy as np
from sqlalchemy import func, select

from app.constants.memory import (
    CHROMA_MEMORIES_COLLECTION,
    EMBEDDING_DIM,
    EMBEDDING_MODEL_NAME,
    MODEL_CACHE_DIR,
    MemoryKind,
    MemoryShelfLife,
    MemorySourceType,
)
from app.memory import chroma_store, pg_store
from app.memory.chroma_store import MemoryVectorItem
from app.memory.embeddings import embed_batch
from app.memory.pg_store._session import memory_session
from app.models.memory_db_models import (
    MemoryDocument,
    MemoryEntity,
    MemoryEntityLink,
    MemoryEpisode,
    MemoryGraphEdge,
    MemoryRecord,
)


class MemorySpec(TypedDict, total=False):
    """One memory to seed: content plus optional storage attributes."""

    content: str
    category: str
    kind: MemoryKind
    shelf_life: MemoryShelfLife
    importance: float
    forget_after: datetime | None
    entities: list[tuple[str, str]]  # (name, entity_type)


# Passage embedding is a pure function of (model, text), and the seeded corpora
# are fixed module constants re-planted under a fresh uuid user for every test.
# The vectors ARE the real model's output, nothing is synthesized — but the
# same 60-memory corpus is not re-embedded on every test, nor cold by every
# xdist worker on every run: an in-process dict sits in front of an on-disk
# per-model archive under the fastembed weights cache, so only the first run
# ever pays the sidecar round-trip. The seed path is not what these tests
# assert on; recall still runs real embed_query, real Chroma ANN, real
# Postgres FTS and the real cross-encoder rerank.
_seed_embedding_cache: dict[str, list[float]] = {}

# Override for the on-disk archive's directory; defaults to a subdirectory of
# MEMORY_MODEL_CACHE_DIR. Unset both and only the in-process dict is used.
_SEED_EMBED_CACHE_DIR_ENV = "MEMORY_TEST_EMBED_CACHE_DIR"
_SEED_EMBED_CACHE_SUBDIR = ".test-embed-cache"


def _seed_cache_path() -> Path | None:
    """One .npz per embedding model, so a model swap never serves stale vectors."""
    override = os.getenv(_SEED_EMBED_CACHE_DIR_ENV, "").strip()
    if override:
        root = Path(override)
    elif MODEL_CACHE_DIR:
        root = Path(MODEL_CACHE_DIR) / _SEED_EMBED_CACHE_SUBDIR
    else:
        return None
    return root / f"{EMBEDDING_MODEL_NAME.replace('/', '__')}.npz"


def _seed_cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_seed_cache(path: Path) -> dict[str, np.ndarray]:
    """Read the archive; a missing, corrupt or wrong-dim file just means embed again."""
    try:
        with np.load(path) as archive:
            keys, vectors = archive["keys"], archive["vectors"]
    except (OSError, ValueError, EOFError, KeyError, zipfile.BadZipFile):
        # A half-written or truncated archive must cost a re-embed, never a
        # test failure — the cache is an optimisation, not a fixture.
        return {}
    if vectors.ndim != 2 or vectors.shape[1] != EMBEDDING_DIM or len(keys) != len(vectors):
        return {}
    return dict(zip(keys.tolist(), vectors))


def _store_seed_cache(path: Path, vectors: dict[str, np.ndarray]) -> None:
    """Merge into the archive atomically (temp file + os.replace) so concurrent
    xdist writers never leave a torn file; last writer wins on the merge."""
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {**_load_seed_cache(path), **vectors}
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".npz.tmp")
    with os.fdopen(fd, "wb") as handle:
        np.savez(
            handle,
            keys=np.array(list(merged), dtype=str),
            vectors=np.stack(list(merged.values())).astype(np.float32),
        )
    Path(tmp_path).replace(path)


async def _embed_seed_contents(contents: list[str]) -> list[list[float]]:
    """Embed seed contents through the real model, once per distinct string."""
    missing = list(dict.fromkeys(text for text in contents if text not in _seed_embedding_cache))
    if not missing:
        return [_seed_embedding_cache[text] for text in contents]

    path = _seed_cache_path()
    on_disk = await asyncio.to_thread(_load_seed_cache, path) if path else {}
    for text in missing:
        vector = on_disk.get(_seed_cache_key(text))
        if vector is not None:
            _seed_embedding_cache[text] = vector.tolist()

    uncached = [text for text in missing if text not in _seed_embedding_cache]
    if uncached:
        embedded = await embed_batch(uncached)
        _seed_embedding_cache.update(zip(uncached, embedded))
        if path:
            fresh = {
                _seed_cache_key(text): np.asarray(vector, dtype=np.float32)
                for text, vector in zip(uncached, embedded)
            }
            try:
                await asyncio.to_thread(_store_seed_cache, path, fresh)
            except OSError as exc:  # a cache that cannot be written must not fail a test
                warnings.warn(f"seed embedding cache not written to {path}: {exc}", stacklevel=2)
    return [_seed_embedding_cache[text] for text in contents]


async def seed_memories(user_id: str, specs: list[MemorySpec]) -> list[MemoryRecord]:
    """Insert memories into Postgres + Chroma exactly as ingestion would."""
    embeddings = await _embed_seed_contents([spec["content"] for spec in specs])
    records = [
        MemoryRecord(
            user_id=user_id,
            kind=spec.get("kind", MemoryKind.FACT).value,
            shelf_life=spec.get("shelf_life", MemoryShelfLife.DURABLE).value,
            content=spec["content"],
            category_path=spec.get("category", "general"),
            importance=spec.get("importance", 0.5),
            forget_after=spec.get("forget_after"),
            source_type=MemorySourceType.MANUAL.value,
        )
        for spec in specs
    ]
    await pg_store.insert_memories(records)
    items: list[MemoryVectorItem] = [
        {
            "id": str(record.id),
            "embedding": embedding,
            "document": record.content,
            "metadata": {
                "user_id": user_id,
                "kind": record.kind,
                "category_path": record.category_path,
                "is_latest": True,
                "is_forgotten": False,
            },
        }
        for record, embedding in zip(records, embeddings)
    ]
    await chroma_store.upsert_memories(items)

    for spec, record in zip(specs, records):
        entities = spec.get("entities")
        if entities:
            id_map = await pg_store.upsert_entities(user_id, entities)
            await pg_store.link_entities(record.id, list(id_map.values()))
    return records


async def fetch_memory_rows(user_id: str) -> list[MemoryRecord]:
    """Every memory row for a user (including superseded/forgotten), oldest first."""
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryRecord)
            .where(MemoryRecord.user_id == user_id)
            .order_by(MemoryRecord.created_at, MemoryRecord.version)
        )
        return list(result.scalars().all())


async def fetch_entities(user_id: str) -> list[MemoryEntity]:
    async with memory_session() as session:
        result = await session.execute(select(MemoryEntity).where(MemoryEntity.user_id == user_id))
        return list(result.scalars().all())


async def fetch_edges(user_id: str) -> list[MemoryGraphEdge]:
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryGraphEdge).where(MemoryGraphEdge.user_id == user_id)
        )
        return list(result.scalars().all())


async def fetch_episode_rows(user_id: str) -> list[MemoryEpisode]:
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryEpisode)
            .where(MemoryEpisode.user_id == user_id)
            .order_by(MemoryEpisode.date)
        )
        return list(result.scalars().all())


async def fetch_document_rows(user_id: str) -> list[MemoryDocument]:
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryDocument).where(MemoryDocument.user_id == user_id)
        )
        return list(result.scalars().all())


async def count_entity_links(user_id: str) -> int:
    """Entity links attached to a user's memories (the link table has no user_id)."""
    async with memory_session() as session:
        result = await session.execute(
            select(func.count())
            .select_from(MemoryEntityLink)
            .join(MemoryRecord, MemoryRecord.id == MemoryEntityLink.memory_id)
            .where(MemoryRecord.user_id == user_id)
        )
        return result.scalar_one()


async def linked_entity_ids(memory_id: uuid.UUID) -> set[uuid.UUID]:
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryEntityLink.entity_id).where(MemoryEntityLink.memory_id == memory_id)
        )
        return {entity_id for (entity_id,) in result.all()}


async def chroma_user_vector_ids(
    user_id: str, collection_name: str = CHROMA_MEMORIES_COLLECTION
) -> list[str]:
    """All vector ids stored for a user in one Chroma collection."""
    collection = await chroma_store._get_collection(collection_name)
    result = await collection.get(where={"user_id": user_id})
    return list(result["ids"])


async def chroma_vector_metadata(
    vector_id: str, collection_name: str = CHROMA_MEMORIES_COLLECTION
) -> dict[str, Any] | None:
    """Metadata for one vector, or None when the vector does not exist."""
    collection = await chroma_store._get_collection(collection_name)
    result = await collection.get(ids=[vector_id], include=["metadatas"])
    metadatas = result.get("metadatas") or []
    if not result["ids"] or not metadatas:
        return None
    return dict(metadatas[0])
