"""Resilience wrapper for the shared Gemini embeddings provider.

Every ChromaDB vector path — tool retrieval, public-integration search, notes,
triggers — resolves the one ``google_embeddings`` provider and calls
``aembed_query`` on it. A single ``retrieve_tools`` turn fans out one similarity
search per namespace (tool space, ``general``, desktop, subagents, public
integrations), and each search embeds the *same* query text independently. So
one user turn spent 2–5 identical calls against the Vertex per-minute quota for
``gemini-embedding``, and when the quota tripped the 429 killed the whole tool
call instead of degrading to a partial tool list.

This wrapper fixes both halves at the provider level, so every consumer inherits
the fix without touching the search fan-out or the LangGraph store API:

- **Coalescing**: concurrent ``aembed_query`` calls for the same text share one
  in-flight embed (single-flight), so the namespace fan-out embeds once per turn.
- **Retry**: a transient 429 (quota) or 5xx is retried with bounded exponential
  backoff, so a quota blip costs latency instead of the whole tool call.

Coalescing covers only the async query path — the one that fans out concurrently.
Document embedding batches are unique, so they are retried but never coalesced.
"""

import asyncio
from collections.abc import Awaitable, Callable
import hashlib
from typing import TypeVar

from google.genai.errors import APIError
from langchain_core.embeddings import Embeddings
from langchain_google_genai._common import GoogleGenerativeAIError

from app.constants.chroma import (
    EMBEDDING_RETRY_BASE_DELAY_SECONDS,
    EMBEDDING_RETRY_MAX_ATTEMPTS,
    EMBEDDING_RETRY_MAX_DELAY_SECONDS,
)
from app.constants.log_tags import LogTag
from app.utils.request_coalescing import coalesce_request
from shared.py.wide_events import log

_RATE_LIMIT_CODE = 429

_EmbedResult = TypeVar("_EmbedResult", list[float], list[list[float]])


def _is_retryable_embed_error(exc: BaseException) -> bool:
    """True for a transient embedding failure worth retrying: a Vertex 429
    (per-minute quota) or a 5xx. ``GoogleGenerativeAIEmbeddings`` wraps the SDK's
    ``APIError`` in ``GoogleGenerativeAIError``, so the real status lives on the
    wrapper's ``__cause__``. Permanent 4xx (400/401/404) are not retried."""
    err = exc.__cause__ if isinstance(exc, GoogleGenerativeAIError) and exc.__cause__ else exc
    if isinstance(err, APIError):
        return err.code == _RATE_LIMIT_CODE or (isinstance(err.code, int) and err.code >= 500)
    return False


class ResilientEmbeddings(Embeddings):
    """Coalescing + retrying decorator over the shared Gemini embeddings.

    Implements the ``Embeddings`` interface so it drops in wherever the raw
    provider was used (the LangGraph ``ChromaStore`` index and the LangChain
    ``Chroma`` client both accept any ``Embeddings``).
    """

    def __init__(self, wrapped: Embeddings, *, model: str) -> None:
        self._wrapped = wrapped
        self._model = model

    async def _aretry(
        self, operation: str, coro_factory: Callable[[], Awaitable[_EmbedResult]]
    ) -> _EmbedResult:
        delay = EMBEDDING_RETRY_BASE_DELAY_SECONDS
        for attempt in range(1, EMBEDDING_RETRY_MAX_ATTEMPTS + 1):
            try:
                return await coro_factory()
            except Exception as exc:
                if attempt >= EMBEDDING_RETRY_MAX_ATTEMPTS or not _is_retryable_embed_error(exc):
                    raise
                log.warning(
                    f"{LogTag.CHROMA} embedding call transient failure, retrying",
                    operation=operation,
                    attempt=attempt,
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, EMBEDDING_RETRY_MAX_DELAY_SECONDS)
        # range() guarantees a return or raise above; this satisfies the type checker.
        raise AssertionError("unreachable")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._wrapped.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._wrapped.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._aretry("aembed_documents", lambda: self._wrapped.aembed_documents(texts))

    async def aembed_query(self, text: str) -> list[float]:
        # Key on model + text so the concurrent namespace searches in one
        # retrieve_tools turn share a single embed. Hashed so the raw query text
        # never lands in a coalescing log line or dict key.
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        key = f"embed_query:{self._model}:{text_hash}"
        return await coalesce_request(
            key,
            lambda: self._aretry("aembed_query", lambda: self._wrapped.aembed_query(text)),
        )
