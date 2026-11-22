"""The task search index on a real in-process Chroma, with an embedding that knows a few meanings.

Words of one concept land on one axis, so "tooth ache" sits next to "dentist" and far from
"passport", as a real embedding model places them; only the model is doubled, never Chroma's
filters, upserts or deletes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import re
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import chromadb
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

#: Each concept's words; a text's vector counts its words per concept.
CONCEPTS: tuple[frozenset[str], ...] = (
    frozenset({"tooth", "teeth", "dentist", "dental", "toothache", "check-up"}),
    frozenset({"passport", "visa", "flight", "flights", "trip", "travel", "embassy"}),
    frozenset({"bank", "invoice", "bill", "bills", "pay", "tax", "refund", "money"}),
    frozenset({"plants", "garden", "water", "watering", "bins", "flat", "move", "movers"}),
    frozenset({"car", "garage", "tyres", "mot", "service"}),
    frozenset({"mum", "birthday", "gift", "present", "party", "anniversary"}),
)
#: Every text gets a little of this axis, so a text of no concept is not a zero vector.
_BASE = 0.05
_WORD = re.compile(r"[a-z-]+")
INDEX_MODULE = "app.services.tasks.search_index"


class ConceptEmbeddings(Embeddings):
    def _vector(self, text: str) -> list[float]:
        words = _WORD.findall(text.lower())
        return [_BASE, *(float(sum(w in concept for w in words)) for concept in CONCEPTS)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


@contextmanager
def task_search_index() -> Iterator[Chroma]:
    """Serve the task search index from a fresh collection on an in-process Chroma."""
    client = chromadb.EphemeralClient()
    name = f"tasks-{uuid4().hex}"
    client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})
    index = Chroma(client=client, collection_name=name, embedding_function=ConceptEmbeddings())
    try:
        with patch(f"{INDEX_MODULE}.task_index", new=AsyncMock(return_value=index)):
            yield index
    finally:
        client.delete_collection(name)
