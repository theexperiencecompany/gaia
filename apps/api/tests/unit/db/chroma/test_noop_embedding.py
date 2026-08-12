"""Unit tests for the shared no-op ChromaDB embedding function.

The class exists to satisfy ChromaDB's EmbeddingFunction protocol so
collections never trigger the default ONNX model download. ChromaDB 1.x
requires ``name()``/``get_config()`` — a missing implementation is a hard
deprecation error — so the contract is pinned here.
"""

from chromadb.api.types import EmbeddingFunction

from app.constants.memory import EMBEDDING_DIM
from app.db.chroma.noop_embedding import NOOP_EMBEDDING_NAME, NoOpEmbeddingFunction


def test_satisfies_the_embedding_function_protocol() -> None:
    assert isinstance(NoOpEmbeddingFunction(), EmbeddingFunction)


def test_name_is_stable() -> None:
    assert NoOpEmbeddingFunction.name() == NOOP_EMBEDDING_NAME


def test_get_config_round_trips_the_name() -> None:
    assert NoOpEmbeddingFunction().get_config() == {"name": NOOP_EMBEDDING_NAME}


def test_build_from_config_reconstructs() -> None:
    rebuilt = NoOpEmbeddingFunction.build_from_config({"name": NOOP_EMBEDDING_NAME})
    assert isinstance(rebuilt, NoOpEmbeddingFunction)


def test_call_returns_zero_vectors_of_the_embedding_dim() -> None:
    vectors = NoOpEmbeddingFunction()(["a", "b"])
    assert len(vectors) == 2
    assert all(len(vector) == EMBEDDING_DIM for vector in vectors)
    assert all(value == 0.0 for vector in vectors for value in vector)
