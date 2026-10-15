from typing import cast

from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.store.base import BaseStore

from app.agents.tools.core.local_embeddings import FastEmbedEmbeddings
from app.config.settings import settings
from app.constants.chroma import GEMINI_EMBEDDING_DIMS, GEMINI_EMBEDDING_MODEL
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers


@lazy_provider(
    name="google_embeddings",
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
)
def init_embeddings() -> GoogleGenerativeAIEmbeddings | FastEmbedEmbeddings:
    """The embeddings backend for tool/trigger semantic search.

    Google Gemini embeddings when a key is configured (hosted + dev default).
    Under self-host without one, fall back to the LOCAL fastembed model the
    memory pipeline already uses — keyless, so semantic tool discovery works
    on a bare instance instead of hard-failing every store that needs
    embeddings. The two backends have different vector dims; embedding_dims
    says which a collection declares.
    """
    if settings.GOOGLE_API_KEY:
        return GoogleGenerativeAIEmbeddings(model=GEMINI_EMBEDDING_MODEL)
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
