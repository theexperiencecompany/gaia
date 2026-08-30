"""Fixtures for the memory engine suite — real stores, mocked LLM only.

Postgres, ChromaDB and Redis are the real local docker services from
``apps/api/.env``; fastembed embedding/reranker models are real and warmed
once per worker. The only mocked boundary is the LLM:
``app.memory.extraction._invoke_structured`` (see ``tests/integration/real/memory/llm.py``).

Because the suite's event loop is function-scoped, each test gets its own
Postgres engine (NullPool), Chroma HTTP client and Redis client patched
into the production accessors — loop-bound connections never leak between
tests.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable
import fcntl
import os
from pathlib import Path
import tempfile
import time
import uuid

import chromadb
from chromadb.api import AsyncClientAPI
import httpx
from langchain_core.messages import BaseMessage
from pydantic import BaseModel
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config.settings import settings
from app.constants.memory import (
    CHROMA_MEMORIES_COLLECTION,
    CHROMA_MEMORY_EPISODES_COLLECTION,
    CONSOLIDATION_PENDING_KEY,
    EMBEDDING_SIDECAR_URL_ENV,
)
from app.db.chroma.chromadb import ChromaClient
import app.db.postgresql as postgresql_module
from app.db.redis import redis_cache
from app.memory import chroma_store, consolidation, management
from app.memory.embeddings import _embed_sync, _rerank_sync
import app.memory.extraction as extraction_module
from tests.integration.real.memory.llm import FakeMemoryLLM

_SCHEMA_ADVISORY_LOCK_ID = 743_001_993  # serializes create_all across xdist workers

_schema_ready = False
_chroma_collections_ready = False


@pytest.fixture(scope="session", autouse=True)
def warm_embedding_models() -> None:
    """Load fastembed models once per worker so latency tests measure warm paths.

    Serialized across xdist workers by a file lock, for the same reason
    ``pg_engine`` takes an advisory lock around ``create_all``: every worker
    shares one fastembed cache directory, and a concurrent first load has them
    all downloading the same HuggingFace snapshot at once. The loser observes
    the snapshot directory its sibling just created, decides the model is
    present, and hands onnxruntime a ``model.onnx`` that has not finished
    downloading — ``NO_SUCHFILE``, which took out 24 memory tests and then the
    live-server suite that reuses the same cache. The winner downloads; the
    rest block here and read a complete cache.
    """
    # With the shared sidecar configured (CI sets MEMORY_EMBEDDING_SIDECAR_URL),
    # the weights live in ONE process and the app's embed/rerank calls go over
    # HTTP — loading them here as well would put ~1.8 GB into every xdist
    # worker and serialize sixteen model loads behind the lock below, which is
    # exactly the cost the sidecar exists to remove. Warm the sidecar instead.
    sidecar = os.getenv(EMBEDDING_SIDECAR_URL_ENV, "").strip()
    if sidecar:
        deadline = time.monotonic() + 120
        while True:
            try:
                r = httpx.get(f"{sidecar}/health", timeout=5.0)
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError(f"embedding sidecar at {sidecar} not healthy after 120s")
            time.sleep(1)

    lock_path = Path(tempfile.gettempdir()) / "gaia-fastembed-warmup.lock"
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        _embed_sync(["warmup"])
        _rerank_sync("warmup", ["warmup document"])


@pytest.fixture
async def pg_engine(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncEngine, None]:
    """Per-test Postgres engine patched into the production session accessor."""
    global _schema_ready
    assert settings.POSTGRES_URL, "POSTGRES_URL must be configured for memory tests"
    url, connect_args = postgresql_module._adapt_url_for_asyncpg(settings.POSTGRES_URL)
    engine = create_async_engine(url, poolclass=NullPool, connect_args=connect_args)

    if not _schema_ready:
        async with engine.begin() as conn:
            await conn.execute(text(f"SELECT pg_advisory_xact_lock({_SCHEMA_ADVISORY_LOCK_ID})"))
            await conn.run_sync(postgresql_module.Base.metadata.create_all)
        _schema_ready = True

    async def _get_engine() -> AsyncEngine:
        # Must be async: replaces get_postgresql_engine which is awaited by callers.
        await asyncio.sleep(0)
        return engine

    monkeypatch.setattr(postgresql_module, "get_postgresql_engine", _get_engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def chroma(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClientAPI, None]:
    """Per-test Chroma client patched into ChromaClient; collection cache reset."""
    global _chroma_collections_ready
    client = await chromadb.AsyncHttpClient(
        host=settings.CHROMADB_HOST, port=settings.CHROMADB_PORT
    )
    if not _chroma_collections_ready:
        for name in (CHROMA_MEMORIES_COLLECTION, CHROMA_MEMORY_EPISODES_COLLECTION):
            await client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
        _chroma_collections_ready = True

    async def _get_client(*_args: object, **_kwargs: object) -> AsyncClientAPI:
        # Must be async: replaces ChromaClient.get_client which is awaited by callers.
        await asyncio.sleep(0)
        return client

    monkeypatch.setattr(ChromaClient, "get_client", _get_client)
    chroma_store._loop_collections.clear()
    chroma_store._loop_locks.clear()
    yield client
    chroma_store._loop_collections.clear()
    chroma_store._loop_locks.clear()


@pytest.fixture
async def real_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[Redis, None]:
    """Fresh Redis client patched into the redis_cache singleton (loop-safe)."""
    client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    await client.ping()
    monkeypatch.setattr(redis_cache, "redis", client)
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard guard: any un-canned memory LLM call fails the test loudly."""

    async def _fail(
        output_model: type[BaseModel],
        messages: list[BaseMessage],
        *,
        operation: str,
        user_id: str,
    ) -> BaseModel | None:
        raise AssertionError(
            f"memory LLM call '{operation}' reached the real provider; use the fake_llm fixture"
        )

    monkeypatch.setattr(extraction_module, "_invoke_structured", _fail)


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch, no_real_llm: None) -> FakeMemoryLLM:
    """Canned LLM boundary — the only mock in this suite."""
    fake = FakeMemoryLLM()
    monkeypatch.setattr(extraction_module, "_invoke_structured", fake.invoke)
    return fake


@pytest.fixture(autouse=True)
async def cleanup_consolidation_waiters() -> AsyncGenerator[None, None]:
    """Cancel debounce waiters retain() spawned so no task outlives the test loop."""
    yield
    tasks = list(consolidation._waiters.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    consolidation._waiters.clear()


@pytest.fixture
async def make_memory_user(
    pg_engine: AsyncEngine,
    chroma: AsyncClientAPI,
    real_redis: Redis,
) -> AsyncGenerator[Callable[[], str], None]:
    """Factory for isolated test users, each hard-wiped from every store on teardown."""
    created: list[str] = []

    def _make() -> str:
        user_id = f"test-mem-{uuid.uuid4().hex[:12]}"
        created.append(user_id)
        return user_id

    try:
        yield _make
    finally:
        for user_id in created:
            await management.delete_all(user_id)
            await real_redis.delete(CONSOLIDATION_PENDING_KEY.format(user_id=user_id))


@pytest.fixture
def memory_user(make_memory_user: Callable[[], str]) -> str:
    """A dedicated, auto-cleaned user id for the test."""
    return make_memory_user()
