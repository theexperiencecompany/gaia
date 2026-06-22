"""Embedding + reranking sidecar service (FastAPI).

Loads the fastembed models ONCE for the whole deployment and exposes them over
HTTP. It reuses the exact ``_embed_sync`` / ``_embed_query_sync`` /
``_rerank_sync`` helpers from ``app.memory.embeddings``, so the vectors and
rerank scores are byte-for-byte identical to the in-process path — the tuned
retrieval thresholds keep working unchanged.

Run it as its own process (one replica), with the embedding URL UNSET so it
uses the local models:

    uv run uvicorn app.services.embedding_sidecar.server:app --host 0.0.0.0 --port 8200

The API and worker then set ``MEMORY_EMBEDDING_SIDECAR_URL`` to its address and
call it instead of loading their own copy.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from app.constants.memory import EMBEDDING_SIDECAR_MAX_CONCURRENCY
from app.memory.embeddings import _embed_query_sync, _embed_sync, _rerank_sync
from shared.py.wide_events import log

# fastembed is sync and CPU-bound. Running it directly in these async handlers
# would block the single uvicorn event loop, so one batch embed would freeze
# every other request AND the /health check — which is what made Swarm kill the
# container as unhealthy under load. Offload to a thread (like the in-process
# path in app.memory.embeddings) and bound concurrency so the CPU isn't
# oversubscribed. /health deliberately takes neither, so it always responds.
_inference_slots = asyncio.Semaphore(EMBEDDING_SIDECAR_MAX_CONCURRENCY)


class EmbedRequest(BaseModel):
    """Passage texts to embed in one fastembed pass."""

    texts: list[str]


class EmbedQueryRequest(BaseModel):
    """A single query string to embed with the model's query instruction."""

    text: str


class RerankRequest(BaseModel):
    """A query and the documents to score against it."""

    query: str
    documents: list[str]


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Warm both models at startup so the first real request is fast and a
    # broken model surfaces immediately rather than on first use.
    _embed_sync(["warmup"])
    _rerank_sync("warmup", ["warmup"])
    log.info("embedding sidecar ready")
    yield


app = FastAPI(title="GAIA Embedding Sidecar", lifespan=_lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — must never block, so it takes no inference slot."""
    return {"status": "ok"}


@app.post("/embed")
async def embed(request: EmbedRequest) -> dict[str, list[list[float]]]:
    """Embed a batch of passage texts."""
    if not request.texts:
        return {"vectors": []}
    async with _inference_slots:
        return {"vectors": await asyncio.to_thread(_embed_sync, request.texts)}


@app.post("/embed_query")
async def embed_query(request: EmbedQueryRequest) -> dict[str, list[float]]:
    """Embed a single query with the model's query instruction."""
    async with _inference_slots:
        return {"vector": await asyncio.to_thread(_embed_query_sync, request.text)}


@app.post("/rerank")
async def rerank(request: RerankRequest) -> dict[str, list[float]]:
    """Score documents against the query, aligned with input order."""
    if not request.documents:
        return {"scores": []}
    async with _inference_slots:
        return {"scores": await asyncio.to_thread(_rerank_sync, request.query, request.documents)}
