"""LangChain-compatible embeddings backed by the LOCAL fastembed model.

Self-host instances may have no Google key at all; tool/trigger semantic
search still needs an embedder. This wraps the exact sync functions the
memory pipeline uses (``mxbai-embed-large``, 1024-dim, query instruction
handled) in the minimal ``Embeddings`` interface Chroma's index expects.

The class carries embedding_dims, the memory pipeline's vector size, for
collection creation.
"""

from langchain_core.embeddings import Embeddings

from app.constants.memory import EMBEDDING_DIM
from app.memory.embeddings import _embed_query_sync, _embed_sync


class FastEmbedEmbeddings(Embeddings):
    """Local, keyless embeddings matching the memory pipeline's model."""

    embedding_dims = EMBEDDING_DIM

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return _embed_sync(texts)

    def embed_query(self, text: str) -> list[float]:
        return _embed_query_sync(text)
