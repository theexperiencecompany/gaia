"""FastEmbedEmbeddings drives the memory pipeline's fastembed model through the Embeddings interface."""

from collections.abc import Iterable, Iterator

import numpy as np
import pytest

from app.agents.tools.core.local_embeddings import FastEmbedEmbeddings
from app.memory import embeddings as memory_embeddings


class _FakeFastEmbedModel:
    """A fastembed stand-in whose passage and query vectors differ, so a swapped call shows."""

    def embed(self, texts: Iterable[str], batch_size: int) -> Iterator[np.ndarray]:
        for text in texts:
            yield np.array([float(len(text)), 0.0])

    def query_embed(self, texts: Iterable[str]) -> Iterator[np.ndarray]:
        for text in texts:
            yield np.array([0.0, float(len(text))])


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_embeddings, "_get_embedding_model", _FakeFastEmbedModel)


@pytest.mark.usefixtures("fake_model")
def test_documents_embed_as_passages_one_vector_per_text() -> None:
    assert FastEmbedEmbeddings().embed_documents(["ab", "abcd"]) == [[2.0, 0.0], [4.0, 0.0]]


@pytest.mark.usefixtures("fake_model")
def test_a_query_embeds_with_the_query_instruction() -> None:
    assert FastEmbedEmbeddings().embed_query("abc") == [0.0, 3.0]
