from typing import cast

from google.genai.errors import APIError
from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.store.base import BaseStore

from app.agents.tools.core.local_embeddings import FastEmbedEmbeddings
from app.config.settings import settings
from app.constants.chroma import (
    GEMINI_EMBED_QUERY_RETRIES,
    GEMINI_EMBED_QUERY_RETRY_MAX_SECONDS,
    GEMINI_EMBED_QUERY_RETRY_MIN_SECONDS,
    GEMINI_EMBEDDING_DIMS,
    GEMINI_EMBEDDING_MODEL,
)
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from shared.py.retry import RetryPolicy, is_retryable_status, retrying
from shared.py.wide_events import log

_EMBED_QUERY_RETRY = RetryPolicy(
    retries=GEMINI_EMBED_QUERY_RETRIES,
    min_s=GEMINI_EMBED_QUERY_RETRY_MIN_SECONDS,
    max_s=GEMINI_EMBED_QUERY_RETRY_MAX_SECONDS,
)


def _is_transient_embed_error(error: BaseException) -> bool:
    """Whether Gemini answered with a status a resend may pass (429, 408, 5xx); langchain wraps it."""
    cause = error.__cause__
    return isinstance(cause, APIError) and is_retryable_status(cause.code)


def _log_embed_retry(attempt: int, error: BaseException) -> None:
    log.warning(
        f"{LogTag.CHROMA} Gemini query embed failed, retrying",
        attempt=attempt,
        error_type=type(error).__name__,
        error=str(error),
    )


class RetryingGeminiEmbeddings(GoogleGenerativeAIEmbeddings):
    """Gemini embeddings whose query embed survives a rate-limit or server blip."""

    async def aembed_query(
        self,
        text: str,
        *,
        task_type: str | None = None,
        title: str | None = None,
        output_dimensionality: int | None = None,
    ) -> list[float]:
        embed = super().aembed_query
        return await retrying(_EMBED_QUERY_RETRY, _is_transient_embed_error, _log_embed_retry)(
            embed,
            text,
            task_type=task_type,
            title=title,
            output_dimensionality=output_dimensionality,
        )


@lazy_provider(
    name="google_embeddings",
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
)
def init_embeddings() -> RetryingGeminiEmbeddings | FastEmbedEmbeddings:
    """The embeddings backend for tool/trigger semantic search.

    Google Gemini embeddings when a key is configured (hosted + dev default).
    Under self-host without one, fall back to the LOCAL fastembed model the
    memory pipeline already uses — keyless, so semantic tool discovery works
    on a bare instance instead of hard-failing every store that needs
    embeddings. The two backends have different vector dims; embedding_dims
    says which a collection declares.
    """
    if settings.GOOGLE_API_KEY:
        return RetryingGeminiEmbeddings(model=GEMINI_EMBEDDING_MODEL)
    return FastEmbedEmbeddings()


def embedding_dims(embeddings: Embeddings) -> int:
    """Return the vector size a collection indexed by this init_embeddings backend declares."""
    if isinstance(embeddings, FastEmbedEmbeddings):
        return embeddings.embedding_dims
    return GEMINI_EMBEDDING_DIMS


async def get_tools_store() -> BaseStore:
    tools_store = await providers.aget("chroma_tools_store")
    if tools_store is None:
        raise RuntimeError("Tools store not available")
    # providers.aget declares -> Any | None; the "chroma_tools_store" provider
    # factory (initialize_chroma_tools_store) always returns a ChromaStore(BaseStore).
    return cast(BaseStore, tools_store)
