from typing import TYPE_CHECKING, cast

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.store.base import BaseStore

from app.agents.tools.core.local_embeddings import FastEmbedEmbeddings
from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers

if TYPE_CHECKING:
    from app.agents.tools.core.local_embeddings import FastEmbedEmbeddings


@lazy_provider(
    name="google_embeddings",
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
)
def init_embeddings() -> "GoogleGenerativeAIEmbeddings | FastEmbedEmbeddings":
    """The embeddings backend for tool/trigger semantic search.

    Google Gemini embeddings when a key is configured (hosted + dev default).
    Under self-host without one, fall back to the LOCAL fastembed model the
    memory pipeline already uses — keyless, so semantic tool discovery works
    on a bare instance instead of hard-failing every store that needs
    embeddings. The two backends have different vector dims, so each carries
    ``embedding_dims`` for collection creation.
    """
    if settings.GOOGLE_API_KEY:
        return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    return FastEmbedEmbeddings()


async def get_tools_store() -> BaseStore:
    tools_store = await providers.aget("chroma_tools_store")
    if tools_store is None:
        raise RuntimeError("Tools store not available")
    # providers.aget declares -> Any | None; the "chroma_tools_store" provider
    # factory (initialize_chroma_tools_store) always returns a ChromaStore(BaseStore).
    return cast(BaseStore, tools_store)
