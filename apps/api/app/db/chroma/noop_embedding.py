"""The shared no-op ChromaDB embedding function.

ChromaStore computes its own embeddings (fastembed) and passes them
explicitly to ``upsert(embeddings=...)``, so the collection-level embedding
function is never used for real. Registering a no-op prevents ChromaDB from
loading its default ONNX model (``all-MiniLM-L6-v2``) in environments where
it is unavailable (CI, minimal containers).

One copy lives here because the two stores that need it (
``app.db.chroma.chroma_store`` and ``app.memory.chroma_store``) drifted
apart once already: the memory copy lost ``name()``/``get_config()`` and
chromadb 1.x turned the missing methods into a hard deprecation error.
"""

from typing import TypeAlias, cast

from chromadb.api.types import EmbeddingFunction, Embeddings
import numpy as np
from numpy.typing import NDArray

from app.constants.memory import EMBEDDING_DIM

NOOP_EMBEDDING_NAME = "gaia-noop"

# ChromaDB's API accepts either plain text or precomputed vectors; the
# parametrization must match the API's own union exactly (protocol type
# params are invariant).
EmbeddingInput: TypeAlias = list[str] | list[NDArray[np.uint64 | np.int64 | np.float64]]


class NoOpEmbeddingFunction(EmbeddingFunction[EmbeddingInput]):
    """Embedding function that bypasses model loading."""

    def __init__(self) -> None:
        # Intentionally empty: the only purpose of this class is to satisfy
        # ChromaDB's EmbeddingFunction protocol so it never attempts to load
        # its default ONNX model.
        pass

    @staticmethod
    def name() -> str:
        """ChromaDB requires embedding functions to declare a name (added in
        0.5.x; a missing name() emits a deprecation warning and will become
        a hard requirement). Called on the class during registration."""
        return NOOP_EMBEDDING_NAME

    def get_config(self) -> dict[str, str]:
        """ChromaDB requires embedding functions to describe their config for
        collection hashing (same deprecation path as name())."""
        return {"name": NOOP_EMBEDDING_NAME}

    @staticmethod
    def build_from_config(config: dict) -> "NoOpEmbeddingFunction":
        """Reconstruct the embedding function from its config dict; the config
        only carries the name, so the no-op constructor suffices."""
        return NoOpEmbeddingFunction()

    def __call__(self, input: EmbeddingInput) -> Embeddings:
        # `input` must keep this exact name: chromadb calls embedding functions
        # as `self._embedding_function(input=input)` (keyword), not positionally.
        # chromadb's own EmbeddingFunction.__call__ contract declares
        # list[numpy.ndarray], but ChromaDB accepts plain float lists at
        # runtime just fine — do NOT convert this to numpy arrays; that broke
        # collection initialization previously. cast() only changes what the
        # type checker sees, not the actual returned values.
        return cast(Embeddings, [[0.0] * EMBEDDING_DIM for _ in input])
