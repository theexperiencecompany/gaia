"""Embedding + reranking for the memory engine.

Wraps fastembed's ONNX ``TextEmbedding`` (mxbai-embed-large, 1024-dim) and
``TextCrossEncoder`` reranker behind lazy process-wide singletons. Unlike the
providers in ``app.core.lazy_loader`` these do not depend on settings keys or
the registry's startup registration step, so they work identically in the API
process and any background context.

Two backends, chosen at call time:

- **Sidecar** (``MEMORY_EMBEDDING_SIDECAR_URL`` set): embed/rerank are HTTP
  calls to the shared sidecar process, so the model weights load ONCE for the
  whole deployment instead of in every container (~1.8 GB each). The sidecar
  reuses these exact ``*_sync`` helpers, so the numbers are identical.
- **Local** (default / dev): each process loads its own model on first use.

fastembed is sync and CPU-bound; the async API runs it in a thread so the
event loop is never blocked. The locks are ``threading.Lock`` (not
``asyncio.Lock``) because loading happens inside ``asyncio.to_thread``.
"""

import asyncio
import os
import threading
import time

from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
import httpx

from app.constants.memory import (
    EMBEDDING_MODEL_NAME,
    EMBEDDING_SIDECAR_TIMEOUT_SECONDS,
    EMBEDDING_SIDECAR_URL_ENV,
    RERANKER_MODEL_NAME,
)
from shared.py.wide_events import log

_embedding_model: TextEmbedding | None = None
_embedding_lock = threading.Lock()

_reranker_model: TextCrossEncoder | None = None
_reranker_lock = threading.Lock()


def _get_embedding_model() -> TextEmbedding:
    """Return the singleton embedding model, loading it on first call."""
    global _embedding_model
    if _embedding_model is None:
        with _embedding_lock:
            if _embedding_model is None:
                started = time.perf_counter()
                _embedding_model = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
                log.info(
                    f"Loaded memory embedding model {EMBEDDING_MODEL_NAME} "
                    f"in {time.perf_counter() - started:.2f}s"
                )
    return _embedding_model


def _get_reranker_model() -> TextCrossEncoder:
    """Return the singleton cross-encoder reranker, loading it on first call."""
    global _reranker_model
    if _reranker_model is None:
        with _reranker_lock:
            if _reranker_model is None:
                started = time.perf_counter()
                _reranker_model = TextCrossEncoder(model_name=RERANKER_MODEL_NAME)
                log.info(
                    f"Loaded memory reranker model {RERANKER_MODEL_NAME} "
                    f"in {time.perf_counter() - started:.2f}s"
                )
    return _reranker_model


def _embed_sync(texts: list[str]) -> list[list[float]]:
    """Embed passage texts synchronously (CPU-bound; call from a thread)."""
    model = _get_embedding_model()
    return [vector.tolist() for vector in model.embed(texts)]


def _embed_query_sync(text: str) -> list[float]:
    """Embed a query with the model's query instruction (CPU-bound).

    BGE models are asymmetric: queries must be prefixed with the model's
    retrieval instruction ("Represent this sentence for searching relevant
    passages: ...") to match against plain passage embeddings.
    ``query_embed`` applies it; plain ``embed`` does not — using the latter
    for queries measurably degrades ANN recall on paraphrased questions.
    """
    model = _get_embedding_model()
    return next(iter(model.query_embed([text]))).tolist()


def _rerank_sync(query: str, documents: list[str]) -> list[float]:
    """Score documents against the query synchronously (CPU-bound)."""
    model = _get_reranker_model()
    return [float(score) for score in model.rerank(query, documents)]


def _sidecar_url() -> str | None:
    """The shared sidecar base URL, or None to use the in-process model."""
    url = os.getenv(EMBEDDING_SIDECAR_URL_ENV, "").strip()
    return url.rstrip("/") or None


async def _sidecar_post(path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=EMBEDDING_SIDECAR_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{_sidecar_url()}{path}", json=payload)
        response.raise_for_status()
        return response.json()


async def embed_query(text: str) -> list[float]:
    """Embed a single query string (with the model's query instruction)."""
    if _sidecar_url():
        return (await _sidecar_post("/embed_query", {"text": text}))["vector"]
    return await asyncio.to_thread(_embed_query_sync, text)


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts in one fastembed pass."""
    if not texts:
        return []
    if _sidecar_url():
        return (await _sidecar_post("/embed", {"texts": texts}))["vectors"]
    return await asyncio.to_thread(_embed_sync, texts)


async def rerank(query: str, documents: list[str]) -> list[float]:
    """Return relevance scores for documents, aligned with input order."""
    if not documents:
        return []
    if _sidecar_url():
        return (await _sidecar_post("/rerank", {"query": query, "documents": documents}))["scores"]
    return await asyncio.to_thread(_rerank_sync, query, documents)
