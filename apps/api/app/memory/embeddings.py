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
from collections.abc import Awaitable
import os
import threading
import time
from typing import Any, TypedDict, TypeVar, cast

from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
import httpx

from app.constants.memory import (
    EMBEDDING_MODEL_NAME,
    EMBEDDING_SIDECAR_MAX_BATCH_CHARS,
    EMBEDDING_SIDECAR_MAX_BATCH_TEXTS,
    EMBEDDING_SIDECAR_RETRIES,
    EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS,
    EMBEDDING_SIDECAR_TIMEOUT_SECONDS,
    EMBEDDING_SIDECAR_URL_ENV,
    MODEL_CACHE_DIR,
    ONNX_ENABLE_CPU_MEM_ARENA,
    ONNX_INTRA_OP_THREADS,
    RERANKER_MODEL_NAME,
)
from shared.py.wide_events import log

_embedding_model: TextEmbedding | None = None
_embedding_lock = threading.Lock()

_reranker_model: TextCrossEncoder | None = None
_reranker_lock = threading.Lock()

# One HTTP connection pool for the process instead of a fresh AsyncClient per
# call. Keyed by running loop: pytest-asyncio gives every test a new loop, and
# pooled connections from an old loop are unusable in the new one.
_http_client: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None
_http_client_lock = threading.Lock()

_T = TypeVar("_T")


class EmbedQueryResponse(TypedDict):
    vector: list[float]


class EmbedBatchResponse(TypedDict):
    vectors: list[list[float]]


class RerankResponse(TypedDict):
    scores: list[float]


def chunk_texts(texts: list[str], max_texts: int, max_chars: int) -> list[list[str]]:
    """Greedy split under both caps; an oversized single text keeps its own chunk."""
    chunks: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for text in texts:
        if current and (len(current) >= max_texts or current_chars + len(text) > max_chars):
            chunks.append(current)
            current, current_chars = [], 0
        current.append(text)
        current_chars += len(text)
    if current:
        chunks.append(current)
    return chunks


async def _observed(operation: str, backend: str, count: int, awaitable: Awaitable[_T]) -> _T:
    """Await an embed/rerank call; on failure emit a structured error and re-raise.

    The embedding sidecar (HTTP) and the local ONNX model are the most
    failure-prone parts of the memory path (timeouts, 5xx, OOM, dimension
    mismatch). This makes those failures queryable by ``backend``/``error_type``
    instead of propagating as an opaque exception with no memory context.
    """
    started = time.perf_counter()
    try:
        return await awaitable
    except Exception as exc:
        log.error(
            "memory_embedding_failed",
            operation=operation,
            backend=backend,
            batch_size=count,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


def _get_embedding_model() -> TextEmbedding:
    """Return the singleton embedding model, loading it on first call."""
    global _embedding_model
    if _embedding_model is None:
        with _embedding_lock:
            if _embedding_model is None:
                started = time.perf_counter()
                _embedding_model = TextEmbedding(
                    model_name=EMBEDDING_MODEL_NAME,
                    cache_dir=MODEL_CACHE_DIR,
                    threads=ONNX_INTRA_OP_THREADS,
                    enable_cpu_mem_arena=ONNX_ENABLE_CPU_MEM_ARENA,
                )
                log.info(
                    "Loaded memory embedding model",
                    model_name=EMBEDDING_MODEL_NAME,
                    duration_s=round(time.perf_counter() - started, 2),
                )
    return _embedding_model


def _get_reranker_model() -> TextCrossEncoder:
    """Return the singleton cross-encoder reranker, loading it on first call."""
    global _reranker_model
    if _reranker_model is None:
        with _reranker_lock:
            if _reranker_model is None:
                started = time.perf_counter()
                _reranker_model = TextCrossEncoder(
                    model_name=RERANKER_MODEL_NAME,
                    cache_dir=MODEL_CACHE_DIR,
                    threads=ONNX_INTRA_OP_THREADS,
                    enable_cpu_mem_arena=ONNX_ENABLE_CPU_MEM_ARENA,
                )
                log.info(
                    "Loaded memory reranker model",
                    model_name=RERANKER_MODEL_NAME,
                    duration_s=round(time.perf_counter() - started, 2),
                )
    return _reranker_model


def _embed_sync(texts: list[str]) -> list[list[float]]:
    """Embed passage texts synchronously (CPU-bound; call from a thread).

    ``batch_size`` bounds the ONNX forward pass — fastembed's default of 256
    texts per pass materializes multi-GB activations and OOM-killed the
    sidecar (#918).
    """
    model = _get_embedding_model()
    return [
        vector.tolist()
        for vector in model.embed(texts, batch_size=EMBEDDING_SIDECAR_MAX_BATCH_TEXTS)
    ]


def _embed_query_sync(text: str) -> list[float]:
    """Embed a query with the model's query instruction (CPU-bound).

    BGE models are asymmetric: queries must be prefixed with the model's
    retrieval instruction ("Represent this sentence for searching relevant
    passages: ...") to match against plain passage embeddings.
    ``query_embed`` applies it; plain ``embed`` does not — using the latter
    for queries measurably degrades ANN recall on paraphrased questions.
    """
    model = _get_embedding_model()
    return cast(list[float], next(iter(model.query_embed([text]))).tolist())


def _rerank_sync(query: str, documents: list[str]) -> list[float]:
    """Score documents against the query synchronously (CPU-bound)."""
    model = _get_reranker_model()
    return [
        float(score)
        for score in model.rerank(query, documents, batch_size=EMBEDDING_SIDECAR_MAX_BATCH_TEXTS)
    ]


def _sidecar_url() -> str | None:
    """The shared sidecar base URL, or None to use the in-process model."""
    url = os.getenv(EMBEDDING_SIDECAR_URL_ENV, "").strip()
    return url.rstrip("/") or None


def _retire_client(old: httpx.AsyncClient, old_loop: asyncio.AbstractEventLoop) -> None:
    """Best-effort close of a replaced client on its own loop; if that loop is
    gone its sockets died with it and GC finishes the rest."""
    try:
        if old_loop.is_running():
            asyncio.run_coroutine_threadsafe(old.aclose(), old_loop)
    except RuntimeError:
        pass


def _get_http_client() -> httpx.AsyncClient:
    """The process-wide sidecar connection pool (per running loop)."""
    global _http_client
    loop = asyncio.get_running_loop()
    with _http_client_lock:
        stale = _http_client is None or _http_client[0] is not loop or _http_client[1].is_closed
        if stale:
            if _http_client is not None:
                _retire_client(_http_client[1], _http_client[0])
            _http_client = (
                loop,
                httpx.AsyncClient(timeout=EMBEDDING_SIDECAR_TIMEOUT_SECONDS),
            )
    return _http_client[1]


async def _post_with_retry(client: httpx.AsyncClient, url: str, payload: dict) -> httpx.Response:
    """POST until success, a non-retryable status, or the retry budget runs
    out — with a short fixed backoff between attempts. A 503 means the sidecar
    was overloaded right now (it already waited out its own slot budget) and a
    connection error means it is mid-restart; dropping the memory operation
    over either blip would lose data. Exhausted retries still fail loud."""
    remaining = EMBEDDING_SIDECAR_RETRIES
    while True:
        try:
            response = await client.post(url, json=payload)
        except httpx.TransportError:
            if remaining == 0:
                raise
            remaining -= 1
            await asyncio.sleep(EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS)
            continue
        if response.status_code not in (429, 503):
            return response
        if remaining == 0:
            return response
        remaining -= 1
        await asyncio.sleep(EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS)


async def _sidecar_post(path: str, payload: dict) -> dict[str, Any]:
    client = _get_http_client()
    response = await _post_with_retry(client, f"{_sidecar_url()}{path}", payload)
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def embed_query(text: str) -> list[float]:
    """Embed a single query string (with the model's query instruction)."""
    if _sidecar_url():
        result = await _observed(
            "embed_query", "sidecar", 1, _sidecar_post("/embed_query", {"text": text})
        )
        return cast(EmbedQueryResponse, result)["vector"]
    return await _observed("embed_query", "local", 1, asyncio.to_thread(_embed_query_sync, text))


async def _sidecar_embed(texts: list[str]) -> list[list[float]]:
    """POST /embed in bounded chunks; a giant batch can't hold one slot forever
    (#918) and chunk order preserves vector order."""
    vectors: list[list[float]] = []
    for chunk in chunk_texts(
        texts, EMBEDDING_SIDECAR_MAX_BATCH_TEXTS, EMBEDDING_SIDECAR_MAX_BATCH_CHARS
    ):
        result = await _observed(
            "embed", "sidecar", len(chunk), _sidecar_post("/embed", {"texts": chunk})
        )
        vectors.extend(cast(EmbedBatchResponse, result)["vectors"])
    return vectors


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts in one fastembed pass."""
    if not texts:
        return []
    if _sidecar_url():
        return await _sidecar_embed(texts)
    return await _observed("embed", "local", len(texts), asyncio.to_thread(_embed_sync, texts))


async def rerank(query: str, documents: list[str]) -> list[float]:
    """Return relevance scores for documents, aligned with input order."""
    if not documents:
        return []
    if _sidecar_url():
        scores: list[float] = []
        # The query is sent with every chunk, so it consumes char budget too.
        char_budget = EMBEDDING_SIDECAR_MAX_BATCH_CHARS - len(query)
        for chunk in chunk_texts(documents, EMBEDDING_SIDECAR_MAX_BATCH_TEXTS, char_budget):
            result = await _observed(
                "rerank",
                "sidecar",
                len(chunk),
                _sidecar_post("/rerank", {"query": query, "documents": chunk}),
            )
            scores.extend(cast(RerankResponse, result)["scores"])
        return scores
    return await _observed(
        "rerank", "local", len(documents), asyncio.to_thread(_rerank_sync, query, documents)
    )
