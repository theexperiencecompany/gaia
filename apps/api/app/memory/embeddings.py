"""Local embedding + reranking models for the memory engine.

Wraps fastembed's ONNX ``TextEmbedding`` (``BAAI/bge-small-en-v1.5``,
384-dim) and ``TextCrossEncoder`` reranker behind lazy process-wide
singletons. Unlike the providers in ``app.core.lazy_loader`` these do not
depend on settings keys or the registry's startup registration step, so
they work identically in the API process and any background context — each
model loads on first use in whichever process calls it.

fastembed is sync and CPU-bound; the async API runs it in a thread so the
event loop is never blocked. The locks are ``threading.Lock`` (not
``asyncio.Lock``) because loading happens inside ``asyncio.to_thread``.
"""

import asyncio
import threading
import time

from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from app.constants.memory import EMBEDDING_MODEL_NAME, RERANKER_MODEL_NAME
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


async def embed_query(text: str) -> list[float]:
    """Embed a single query string (with the model's query instruction)."""
    return await asyncio.to_thread(_embed_query_sync, text)


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts in one fastembed pass."""
    if not texts:
        return []
    return await asyncio.to_thread(_embed_sync, texts)


async def rerank(query: str, documents: list[str]) -> list[float]:
    """Return relevance scores for documents, aligned with input order."""
    if not documents:
        return []
    return await asyncio.to_thread(_rerank_sync, query, documents)
