"""Entry point: ``uv run python -m scripts.memory_benchmark``.

Bootstrap strategy (mirrors tests/memory/conftest.py):
  The engine's Postgres and ChromaDB accessors sit behind a lazy-provider
  registry that only initialises inside a live FastAPI app.  We bypass the
  registry by directly monkey-patching the two accessor functions before any
  memory code runs, exactly as the memory test conftest does.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import time


async def _bootstrap() -> None:
    """Patch Postgres and Chroma accessors to bypass the lazy-provider registry."""
    import chromadb
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config.settings import settings
    from app.constants.memory import (
        CHROMA_MEMORIES_COLLECTION,
        CHROMA_MEMORY_EPISODES_COLLECTION,
    )
    from app.db.chroma.chromadb import ChromaClient
    import app.db.postgresql as postgresql_module
    from app.db.redis import redis_cache
    from app.memory import chroma_store

    # ── Postgres ─────────────────────────────────────────────────────────────
    assert settings.POSTGRES_URL, "POSTGRES_URL must be set"
    url, connect_args = postgresql_module._adapt_url_for_asyncpg(settings.POSTGRES_URL)
    engine = create_async_engine(url, poolclass=NullPool, connect_args=connect_args)

    # Ensure memory tables exist

    async with engine.begin() as conn:
        await conn.run_sync(postgresql_module.Base.metadata.create_all)

    async def _get_engine():  # type: ignore[return]
        return engine

    postgresql_module.get_postgresql_engine = _get_engine  # type: ignore[assignment]
    print("  [bootstrap] Postgres engine ready", flush=True)

    # ── ChromaDB ─────────────────────────────────────────────────────────────
    chroma_client = await chromadb.AsyncHttpClient(
        host=settings.CHROMADB_HOST, port=settings.CHROMADB_PORT
    )
    for name in (CHROMA_MEMORIES_COLLECTION, CHROMA_MEMORY_EPISODES_COLLECTION):
        await chroma_client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

    async def _get_client(*_args: object, **_kwargs: object):  # type: ignore[return]
        return chroma_client

    ChromaClient.get_client = _get_client  # type: ignore[assignment]
    chroma_store._collections.clear()
    print("  [bootstrap] ChromaDB client ready", flush=True)

    # ── Redis ─────────────────────────────────────────────────────────────────
    from redis.asyncio import Redis

    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    await redis_client.ping()
    redis_cache.redis = redis_client  # type: ignore[assignment]
    print("  [bootstrap] Redis client ready", flush=True)

    # ── fastembed warm-up (loads ONNX models once) ────────────────────────────
    from app.memory.embeddings import _embed_sync, _rerank_sync

    print("  [bootstrap] Warming fastembed models (first run downloads ONNX) …", flush=True)
    _embed_sync(["warmup"])
    _rerank_sync("warmup", ["warmup document"])
    print("  [bootstrap] fastembed models ready", flush=True)


async def main() -> None:
    print("=" * 60)
    print("GAIA Memory Engine — Accuracy Benchmark")
    print("=" * 60)
    print("Using base date: 2026-01-10 UTC")
    print()

    print("Bootstrapping providers …")
    await _bootstrap()
    print()

    from .report import generate_report, print_summary
    from .runner import run_all_scenarios

    wall_start = time.perf_counter()
    results = await run_all_scenarios()
    wall_elapsed = time.perf_counter() - wall_start

    print()
    print(f"Total wall time: {wall_elapsed:.1f}s")
    print()

    report_path = Path(__file__).parent / "benchmark_report.md"
    generate_report(results, output_path=report_path)
    print_summary(results)

    # Exit 1 if overall accuracy < 50% so CI can gate on this
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    pct = (passed / total * 100) if total else 0.0
    if pct < 50.0:
        sys.exit(1)


if __name__ == "__main__":
    os.environ.setdefault("ENV", "development")
    asyncio.run(main())
