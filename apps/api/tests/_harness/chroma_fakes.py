"""An in-memory Chroma collection and client, for tests that cannot fork a real one.

chromadb's in-process client does not survive fork(), which every mutmut mutant
does, so unit tests drive ChromaStore against this instead. It answers get,
upsert, delete and query in Chroma's result shapes and keeps rows in insert
order; query ranks by cosine distance and honours a namespace $eq / $and where.
"""

from collections.abc import Sequence
import math
import pickle  # nosec B403 - the fake stores exactly what ChromaStore pickled


def pickled_document(value: object) -> str:
    return pickle.dumps(value).decode("latin1")


class FakeChromaCollection:
    """Rows keyed by id, answering get/upsert/delete/query in Chroma's result shapes."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[list[float] | None, dict[str, str], str | None]] = {}
        self.queries: list[dict[str, object]] = []
        self.gets: list[dict[str, object]] = []
        self.fail_upsert_for: set[str] = set()
        self.fail_delete_for: set[str] = set()
        #: The ids of each upsert and delete request, in the order they arrived.
        self.upserts: list[list[str]] = []
        self.deletes: list[list[str]] = []

    def add(self, doc_id: str, metadata: dict[str, str], value: object = None) -> None:
        self.rows[doc_id] = (None, metadata, pickled_document(value) if value is not None else None)

    async def get(
        self, ids: Sequence[str] | None = None, include: Sequence[str] = ()
    ) -> dict[str, object]:
        self.gets.append({"ids": ids, "include": list(include)})
        selected = [doc_id for doc_id in self.rows if ids is None or doc_id in ids]
        return {
            "ids": selected,
            "metadatas": [self.rows[i][1] for i in selected] if "metadatas" in include else None,
            "documents": [self.rows[i][2] for i in selected] if "documents" in include else None,
        }

    async def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]] | None,
        metadatas: list[dict[str, str]],
        documents: list[str],
    ) -> None:
        self.upserts.append(list(ids))
        if self.fail_upsert_for & set(ids):
            raise ConnectionError("chroma down")
        if embeddings is not None and len(embeddings) != len(ids):
            raise ValueError("Chroma takes a vector for every row or for none")
        for i, doc_id in enumerate(ids):
            self.rows[doc_id] = (embeddings[i] if embeddings else None, metadatas[i], documents[i])

    async def delete(self, ids: list[str]) -> None:
        self.deletes.append(list(ids))
        if self.fail_delete_for & set(ids):
            raise ConnectionError("chroma down")
        for doc_id in ids:
            self.rows.pop(doc_id, None)

    async def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int,
        include: Sequence[str],
        where: dict[str, object] | None,
    ) -> dict[str, object]:
        self.queries.append({"n_results": n_results, "include": list(include), "where": where})
        query = query_embeddings[0]
        scored = []
        for doc_id, (embedding, metadata, document) in self.rows.items():
            if embedding is None or not _where_matches(where, metadata):
                continue
            dot = sum(a * b for a, b in zip(query, embedding))
            norm = math.sqrt(sum(a * a for a in query)) * math.sqrt(sum(b * b for b in embedding))
            scored.append((1.0 - dot / norm, doc_id, metadata, document))
        scored.sort()
        scored = scored[:n_results]
        return {
            "ids": [[s[1] for s in scored]],
            "metadatas": [[s[2] for s in scored]],
            "distances": [[s[0] for s in scored]],
            "documents": [[s[3] for s in scored]],
        }


def _where_matches(where: dict[str, object] | None, metadata: dict[str, str]) -> bool:
    if where is None:
        return True
    if "$and" in where:
        return all(_where_matches(part, metadata) for part in where["$and"])
    return all(
        metadata.get(key) == (cond["$eq"] if isinstance(cond, dict) else cond)
        for key, cond in where.items()
    )


class FakeChromaClient:
    def __init__(self, collection: FakeChromaCollection) -> None:
        self.collection = collection
        self.created: list[str] = []

    async def get_or_create_collection(self, name: str, **_: object) -> FakeChromaCollection:
        self.created.append(name)
        return self.collection
