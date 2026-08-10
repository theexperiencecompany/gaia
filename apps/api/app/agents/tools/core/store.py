from typing import cast

from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.store.base import BaseStore

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.memory.embeddings import embed_batch, embed_batch_sync, embed_query, embed_query_sync


@lazy_provider(
    name="google_embeddings",
    required_keys=[settings.GOOGLE_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
    warning_message="Embeddings not configured. Tool discovery using tool_retrieval tool will fail. "
    "Sometimes agent calls tool_retrieval for tool discovery. This may lead to errors when agent is invoked.",
)
def init_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")


class SidecarEmbeddings(Embeddings):
    """LangChain Embeddings adapter over the memory embedder (sidecar-first).

    The tool-retrieval stores fall back to this when google embeddings are
    unavailable, so tool discovery keeps working with zero external
    dependencies. Uses the same model as the memory pipeline (mxbai-embed-large,
    1024-dim) via ``app.memory.embeddings`` — sidecar HTTP when configured,
    in-process ONNX otherwise.
    """

    def embed_query(self, text: str) -> list[float]:
        return embed_query_sync(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embed_batch_sync(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return await embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await embed_batch(texts)


async def get_store_embeddings() -> tuple[Embeddings, int] | None:
    """Resolve embeddings for the tool-retrieval stores, with dims.

    Google (gemini-embedding-001, 768-dim) when configured; otherwise the local
    memory embedder (mxbai-embed-large, 1024-dim) so the stores boot and serve
    without any external embedding API. Returns None only when the memory
    embedder itself is unavailable.
    """
    google = await providers.aget("google_embeddings")
    if google is not None:
        return cast(Embeddings, google), 768
    return SidecarEmbeddings(), 1024


async def get_tools_store() -> BaseStore:
    tools_store = await providers.aget("chroma_tools_store")
    if tools_store is None:
        raise RuntimeError("Tools store not available")
    # providers.aget declares -> Any | None; the "chroma_tools_store" provider
    # factory (initialize_chroma_tools_store) always returns a ChromaStore(BaseStore).
    return cast(BaseStore, tools_store)
