"""Embedding + reranking sidecar service (FastAPI).

Loads the fastembed models ONCE for the whole deployment and exposes them over
HTTP. It reuses the exact _embed_sync / _embed_query_sync /
_rerank_sync helpers from app.memory.embeddings, so the vectors and
rerank scores are byte-for-byte identical to the in-process path — the tuned
retrieval thresholds keep working unchanged.

Run it as its own process (one replica), with the embedding URL UNSET so it
uses the local models:

    uv run uvicorn app.services.embedding_sidecar.server:app --host 0.0.0.0 --port 8200

The API and worker then set MEMORY_EMBEDDING_SIDECAR_URL to its address and
call it instead of loading their own copy.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import UJSONResponse
from pydantic import BaseModel

from app.constants.http import RETRY_AFTER_HEADER
from app.constants.memory import (
    EMBEDDING_SIDECAR_MAX_CONCURRENCY,
    EMBEDDING_SIDECAR_MAX_TEXT_CHARS,
    EMBEDDING_SIDECAR_RETRY_AFTER_SECONDS,
    EMBEDDING_SIDECAR_SLOT_WAIT_SECONDS,
)
from app.core.exception_handlers import register_exception_handlers
from app.memory.embeddings import _embed_query_sync, _embed_sync, _rerank_sync
from app.schemas.errors import ERROR_RESPONSES, error_responses
from shared.py.wide_events import log

# fastembed is sync and CPU-bound; running it directly here would freeze /health
# too, which made Swarm kill the container as unhealthy under load. Offload to a
# thread and bound concurrency; /health deliberately takes neither slot.
_inference_slots = asyncio.Semaphore(EMBEDDING_SIDECAR_MAX_CONCURRENCY)
_slot_wait_seconds = EMBEDDING_SIDECAR_SLOT_WAIT_SECONDS


@asynccontextmanager
async def _inference_slot() -> AsyncIterator[None]:
    """One bounded-inference slot; 503s instead of queueing forever when full.

    Memory bounding itself lives inside the sync helpers (explicit fastembed
    batch_size) — this only keeps concurrent forward passes within the CPU
    budget and makes overload visible instead of silently piling up until
    clients time out.
    """
    try:
        await asyncio.wait_for(_inference_slots.acquire(), timeout=_slot_wait_seconds)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail="embedding sidecar busy; retry shortly",
            headers={RETRY_AFTER_HEADER: str(EMBEDDING_SIDECAR_RETRY_AFTER_SECONDS)},
        ) from exc
    try:
        yield
    finally:
        _inference_slots.release()


# The sidecar is a second FastAPI app, so it needs the envelope declared and
# its handlers registered explicitly — a hand-rolled responses dict here is how
# a second error shape gets onto the wire without anyone noticing.
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    **error_responses(
        {
            413: "A text exceeds EMBEDDING_SIDECAR_MAX_TEXT_CHARS.",
            503: "All inference slots stayed busy for the slot-wait budget.",
        }
    ),
}
_ERROR_RESPONSES[503]["headers"] = {RETRY_AFTER_HEADER: {"schema": {"type": "integer"}}}


def _reject_oversized(texts: list[str]) -> None:
    """Reject a text beyond EMBEDDING_SIDECAR_MAX_TEXT_CHARS instead of truncating.

    It would truncate to the model's 512-token window anyway while its JSON body,
    tokenization, and validation still cost real memory and CPU.
    """
    for text in texts:
        if len(text) > EMBEDDING_SIDECAR_MAX_TEXT_CHARS:
            raise HTTPException(
                status_code=413,
                detail=f"text exceeds EMBEDDING_SIDECAR_MAX_TEXT_CHARS "
                f"({EMBEDDING_SIDECAR_MAX_TEXT_CHARS} chars); split it before sending",
            )


class EmbedRequest(BaseModel):
    """Passage texts to embed; oversized batches are bounded internally."""

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


app = FastAPI(
    title="GAIA Embedding Sidecar", lifespan=_lifespan, default_response_class=UJSONResponse
)
register_exception_handlers(app)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — must never block, so it takes no inference slot."""
    return {"status": "ok"}


# evlog-map-disable-next-line wide-event -- standalone uvicorn app without LoggingMiddleware; log.set() would never be emitted
@app.post("/embed", responses=_ERROR_RESPONSES)
async def embed(request: EmbedRequest) -> dict[str, list[list[float]]]:
    """Embed a batch of passage texts."""
    if not request.texts:
        return {"vectors": []}
    _reject_oversized(request.texts)
    async with _inference_slot():
        return {"vectors": await asyncio.to_thread(_embed_sync, request.texts)}


# evlog-map-disable-next-line wide-event -- standalone uvicorn app without LoggingMiddleware; log.set() would never be emitted
@app.post("/embed_query", responses=_ERROR_RESPONSES)
async def embed_query(request: EmbedQueryRequest) -> dict[str, list[float]]:
    """Embed a single query with the model's query instruction."""
    _reject_oversized([request.text])
    async with _inference_slot():
        return {"vector": await asyncio.to_thread(_embed_query_sync, request.text)}


# evlog-map-disable-next-line wide-event -- standalone uvicorn app without LoggingMiddleware; log.set() would never be emitted
@app.post("/rerank", responses=_ERROR_RESPONSES)
async def rerank(request: RerankRequest) -> dict[str, list[float]]:
    """Score documents against the query, aligned with input order."""
    if not request.documents:
        return {"scores": []}
    _reject_oversized([request.query, *request.documents])
    async with _inference_slot():
        return {"scores": await asyncio.to_thread(_rerank_sync, request.query, request.documents)}
