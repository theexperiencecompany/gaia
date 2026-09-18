from typing import cast

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.store.base import BaseStore

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.db.chroma.resilient_embeddings import ResilientEmbeddings

GOOGLE_EMBEDDING_MODEL = "models/gemini-embedding-001"


@lazy_provider(
    name="google_embeddings",
    required_keys=[settings.GOOGLE_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
    warning_message="Embeddings not configured. Tool discovery using tool_retrieval tool will fail. "
    "Sometimes agent calls tool_retrieval for tool discovery. This may lead to errors when agent is invoked.",
)
def init_embeddings() -> ResilientEmbeddings:
    # Wrap the raw Gemini embeddings so every ChromaDB consumer (tool retrieval,
    # public integrations, notes, triggers) coalesces the concurrent same-text
    # embeds a single turn fans out and rides out transient Vertex 429s.
    return ResilientEmbeddings(
        GoogleGenerativeAIEmbeddings(model=GOOGLE_EMBEDDING_MODEL),
        model=GOOGLE_EMBEDDING_MODEL,
    )


async def get_tools_store() -> BaseStore:
    tools_store = await providers.aget("chroma_tools_store")
    if tools_store is None:
        raise RuntimeError("Tools store not available")
    # providers.aget declares -> Any | None; the "chroma_tools_store" provider
    # factory (initialize_chroma_tools_store) always returns a ChromaStore(BaseStore).
    return cast(BaseStore, tools_store)
