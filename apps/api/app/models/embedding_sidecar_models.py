"""Wire models of the embedding sidecar, shared by its server and the memory engine's client."""

from pydantic import BaseModel


class EmbedRequest(BaseModel):
    """Passage texts to embed; oversized batches are bounded internally."""

    texts: list[str]


class EmbedQueryRequest(BaseModel):
    """A single query string to embed with the model's query instruction."""

    text: str


class RerankRequest(BaseModel):
    """A query and the documents to score against it."""

    query: str
    documents: list[str]


class EmbedResponse(BaseModel):
    """One vector per input text, in input order."""

    vectors: list[list[float]]


class EmbedQueryResponse(BaseModel):
    """The query's vector."""

    vector: list[float]


class RerankResponse(BaseModel):
    """One relevance score per document, in input order."""

    scores: list[float]
