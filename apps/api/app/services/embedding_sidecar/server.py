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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from app.memory.embeddings import _embed_query_sync, _embed_sync, _rerank_sync
from shared.py.wide_events import log


class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedQueryRequest(BaseModel):
    text: str


class RerankRequest(BaseModel):
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
    return {"status": "ok"}


@app.post("/embed")
async def embed(request: EmbedRequest) -> dict[str, list[list[float]]]:
    return {"vectors": _embed_sync(request.texts) if request.texts else []}


@app.post("/embed_query")
async def embed_query(request: EmbedQueryRequest) -> dict[str, list[float]]:
    return {"vector": _embed_query_sync(request.text)}


@app.post("/rerank")
async def rerank(request: RerankRequest) -> dict[str, list[float]]:
    return {"scores": _rerank_sync(request.query, request.documents) if request.documents else []}
