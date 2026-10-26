"""Embedding + reranking for the memory engine.

Wraps fastembed's ONNX TextEmbedding (mxbai-embed-large, 1024-dim) and
TextCrossEncoder reranker behind lazy process-wide singletons, independent of
app.core.lazy_loader's settings/registration requirements.

Two backends, chosen at call time: **Sidecar** (MEMORY_EMBEDDING_SIDECAR_URL
set) makes embed/rerank HTTP calls to a shared process so weights load ONCE
per deployment (~1.8 GB each) instead of per container; **Local** (default)
loads its own model per process on first use.

fastembed is sync/CPU-bound; the async API runs it in a thread, using
threading.Lock (not asyncio.Lock) since loading happens inside asyncio.to_thread.
"""

import asyncio
from collections.abc import Awaitable
import os
from pathlib import Path
import threading
import time
from typing import TypeVar, cast

from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
import httpx
from pydantic import BaseModel

from app.constants.memory import (
    BAKED_MODELS_DIR,
    EMBEDDING_MODEL_NAME,
    EMBEDDING_SIDECAR_INTERACTIVE_TIMEOUT_SECONDS,
    EMBEDDING_SIDECAR_MAX_BATCH_CHARS,
    EMBEDDING_SIDECAR_MAX_BATCH_TEXTS,
    EMBEDDING_SIDECAR_RETRIES,
    EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS,
    EMBEDDING_SIDECAR_RETRYABLE_STATUS_CODES,
    EMBEDDING_SIDECAR_TIMEOUT_SECONDS,
    EMBEDDING_SIDECAR_URL_ENV,
    MODEL_CACHE_DIR,
    ONNX_ENABLE_CPU_MEM_ARENA,
    ONNX_INTRA_OP_THREADS,
    RERANKER_MODEL_NAME,
)
from app.models.embedding_sidecar_models import (
    EmbedQueryRequest,
    EmbedQueryResponse,
    EmbedRequest,
    EmbedResponse,
    RerankRequest,
    RerankResponse,
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
_ResponseT = TypeVar("_ResponseT", bound=BaseModel)

# What an interactive sidecar call raises when it fails fast; recall degrades on exactly these.
FAIL_FAST_ERRORS: tuple[type[Exception], ...] = (httpx.HTTPError, TimeoutError)


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


async def _observed(
    operation: str,
    backend: str,
    count: int,
    awaitable: Awaitable[_T],
    *,
    interactive: bool = False,
) -> _T:
    """Await an embed/rerank call; record an unhandled failure at error level and re-raise.

    An interactive fail-fast error is recall's to report: it degrades and logs a
    warning, so recording an error here would page Sentry for a handled timeout.
    """
    started = time.perf_counter()
    try:
        return await awaitable
    except Exception as exc:
        if interactive and isinstance(exc, FAIL_FAST_ERRORS):
            raise
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


def _baked_model_path(model_name: str) -> str | None:
    """Return the image-baked directory for this model, or None when it must come from the cache."""
    if BAKED_MODELS_DIR is None:
        return None
    path = Path(BAKED_MODELS_DIR) / model_name
    return str(path) if path.is_dir() else None


def _get_embedding_model() -> TextEmbedding:
    """Return the singleton embedding model, loading it on first call."""
    global _embedding_model
    if _embedding_model is None:
        with _embedding_lock:
            if _embedding_model is None:
                started = time.perf_counter()
                baked_path = _baked_model_path(EMBEDDING_MODEL_NAME)
                _embedding_model = TextEmbedding(
                    model_name=EMBEDDING_MODEL_NAME,
                    cache_dir=MODEL_CACHE_DIR,
                    specific_model_path=baked_path,
                    threads=ONNX_INTRA_OP_THREADS,
                    enable_cpu_mem_arena=ONNX_ENABLE_CPU_MEM_ARENA,
                )
                log.info(
                    "Loaded memory embedding model",
                    model_name=EMBEDDING_MODEL_NAME,
                    source="baked" if baked_path else "cache",
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
                baked_path = _baked_model_path(RERANKER_MODEL_NAME)
                _reranker_model = TextCrossEncoder(
                    model_name=RERANKER_MODEL_NAME,
                    cache_dir=MODEL_CACHE_DIR,
                    specific_model_path=baked_path,
                    threads=ONNX_INTRA_OP_THREADS,
                    enable_cpu_mem_arena=ONNX_ENABLE_CPU_MEM_ARENA,
                )
                log.info(
                    "Loaded memory reranker model",
                    model_name=RERANKER_MODEL_NAME,
                    source="baked" if baked_path else "cache",
                    duration_s=round(time.perf_counter() - started, 2),
                )
    return _reranker_model


def _embed_sync(texts: list[str]) -> list[list[float]]:
    """Embed passage texts synchronously (CPU-bound; call from a thread).

    batch_size bounds the ONNX forward pass — fastembed's default of 256
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

    BGE models are asymmetric: query_embed prefixes the retrieval instruction
    needed to match plain passage embeddings; plain embed does not, and using
    it for queries measurably degrades ANN recall on paraphrased questions.
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
    """Return the shared sidecar base URL, or None to use the in-process model."""
    url = os.getenv(EMBEDDING_SIDECAR_URL_ENV, "").strip()
    return url.rstrip("/") or None


def _retire_client(old: httpx.AsyncClient, old_loop: asyncio.AbstractEventLoop) -> None:
    """Best-effort close a replaced client on its own loop; a gone loop's sockets already died with it."""
    try:
        if old_loop.is_running():
            asyncio.run_coroutine_threadsafe(old.aclose(), old_loop)
    except RuntimeError:
        pass


def _get_http_client() -> httpx.AsyncClient:
    """Return the process-wide sidecar connection pool (per running loop)."""
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


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    request: BaseModel,
    *,
    retries: int = EMBEDDING_SIDECAR_RETRIES,
    timeout: float = EMBEDDING_SIDECAR_TIMEOUT_SECONDS,
) -> httpx.Response:
    """POST with a bounded retry budget and a fixed backoff between attempts.

    A transient failure (retryable status or a mid-restart connection error) is
    retried so a background memory save survives the blip; interactive recall
    passes retries=0 to fail fast into its retrieval-order fallback instead of
    stacking backoffs onto the user's turn.
    """
    for _ in range(retries):
        try:
            response = await client.post(url, json=request.model_dump(), timeout=timeout)
        except httpx.TransportError:
            pass  # transient — fall through to the backoff and retry
        else:
            if response.status_code not in EMBEDDING_SIDECAR_RETRYABLE_STATUS_CODES:
                return response
        await asyncio.sleep(EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS)
    # Budget exhausted (or none): the final attempt is authoritative — its
    # response (including a 503) is returned, or its connection error propagates.
    return await client.post(url, json=request.model_dump(), timeout=timeout)


def _call_budget(interactive: bool) -> tuple[int, float]:
    """(retries, timeout_seconds) for a sidecar call by path criticality."""
    if interactive:
        return 0, EMBEDDING_SIDECAR_INTERACTIVE_TIMEOUT_SECONDS
    return EMBEDDING_SIDECAR_RETRIES, EMBEDDING_SIDECAR_TIMEOUT_SECONDS


async def _sidecar_post(
    path: str,
    request: BaseModel,
    response_model: type[_ResponseT],
    *,
    interactive: bool = False,
) -> _ResponseT:
    retries, timeout = _call_budget(interactive)
    client = _get_http_client()
    response = await _post_with_retry(
        client, f"{_sidecar_url()}{path}", request, retries=retries, timeout=timeout
    )
    response.raise_for_status()
    return response_model.model_validate(response.json())


async def embed_query(text: str, *, interactive: bool = False) -> list[float]:
    """Embed a single query string (with the model's query instruction).

    interactive=True (memory recall on a user turn) uses the fail-fast
    budget; the default background budget is for ingestion.
    """
    if _sidecar_url():
        result = await _observed(
            "embed_query",
            "sidecar",
            1,
            _sidecar_post(
                "/embed_query",
                EmbedQueryRequest(text=text),
                EmbedQueryResponse,
                interactive=interactive,
            ),
        )
        return result.vector
    return await _observed("embed_query", "local", 1, asyncio.to_thread(_embed_query_sync, text))


async def _sidecar_embed(texts: list[str]) -> list[list[float]]:
    """POST /embed in bounded chunks (#918) so a giant batch can't hold one slot forever.

    Chunk order preserves vector order.
    """
    vectors: list[list[float]] = []
    for chunk in chunk_texts(
        texts, EMBEDDING_SIDECAR_MAX_BATCH_TEXTS, EMBEDDING_SIDECAR_MAX_BATCH_CHARS
    ):
        result = await _observed(
            "embed",
            "sidecar",
            len(chunk),
            _sidecar_post("/embed", EmbedRequest(texts=chunk), EmbedResponse),
        )
        vectors.extend(result.vectors)
    return vectors


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts in one fastembed pass."""
    if not texts:
        return []
    if _sidecar_url():
        return await _sidecar_embed(texts)
    return await _observed("embed", "local", len(texts), asyncio.to_thread(_embed_sync, texts))


async def _sidecar_rerank(
    query: str, documents: list[str], *, interactive: bool = False
) -> list[float]:
    """POST /rerank in bounded chunks, preserving document order."""
    scores: list[float] = []
    # The query is sent with every chunk, so it consumes char budget too.
    char_budget = EMBEDDING_SIDECAR_MAX_BATCH_CHARS - len(query)
    for chunk in chunk_texts(documents, EMBEDDING_SIDECAR_MAX_BATCH_TEXTS, char_budget):
        result = await _observed(
            "rerank",
            "sidecar",
            len(chunk),
            _sidecar_post(
                "/rerank",
                RerankRequest(query=query, documents=chunk),
                RerankResponse,
                interactive=interactive,
            ),
        )
        scores.extend(result.scores)
    return scores


async def rerank(query: str, documents: list[str], *, interactive: bool = False) -> list[float]:
    """Return relevance scores for documents, aligned with input order.

    interactive=True (recall on a user turn) uses the fail-fast per-request
    budget and one deadline across all chunks: a large candidate set splits into
    several requests, so a per-chunk timeout alone would let the total exceed the
    turn budget. On expiry it raises into the caller's retrieval-order fallback.
    """
    if not documents:
        return []
    if _sidecar_url():
        if interactive:
            async with asyncio.timeout(EMBEDDING_SIDECAR_INTERACTIVE_TIMEOUT_SECONDS):
                return await _sidecar_rerank(query, documents, interactive=True)
        return await _sidecar_rerank(query, documents)
    return await _observed(
        "rerank", "local", len(documents), asyncio.to_thread(_rerank_sync, query, documents)
    )
