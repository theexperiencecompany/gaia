"""The OpenAI embedding client: order across batches, and loud failures."""

import json
from unittest.mock import patch

import httpx
import pytest

from app.memory import hosted_embeddings


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def _reply(vectors: list[list[float]], *, reverse: bool = False) -> httpx.Response:
    data = [{"index": i, "embedding": v} for i, v in enumerate(vectors)]
    return httpx.Response(200, json={"data": list(reversed(data)) if reverse else data})


async def test_documents_come_back_in_input_order_across_batches() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        # OpenAI does not promise data in input order; the index field is the contract.
        return _reply([[float(len(t))] for t in texts], reverse=True)

    texts = ["x" * n for n in (9, 3, 8, 4, 7)]
    with (
        patch.object(
            hosted_embeddings, "_client", return_value=_client(httpx.MockTransport(respond))
        ),
        patch.object(hosted_embeddings, "HOSTED_EMBEDDING_BATCH_TEXTS", 2),
    ):
        vectors = await hosted_embeddings.embed_documents(texts)

    assert vectors == [[9.0], [3.0], [8.0], [4.0], [7.0]]


async def test_a_refused_request_raises_with_the_providers_reason() -> None:
    refused = httpx.MockTransport(
        lambda _r: httpx.Response(400, json={"error": {"message": "bad input"}})
    )
    with (
        patch.object(hosted_embeddings, "_client", return_value=_client(refused)),
        pytest.raises(hosted_embeddings.HostedEmbeddingError, match="bad input"),
    ):
        await hosted_embeddings.embed_query("hi")


async def test_fewer_vectors_than_texts_raises_instead_of_shrinking() -> None:
    short = httpx.MockTransport(lambda _r: _reply([[1.0]]))
    with (
        patch.object(hosted_embeddings, "_client", return_value=_client(short)),
        pytest.raises(hosted_embeddings.HostedEmbeddingError, match="1 vectors for 2 texts"),
    ):
        await hosted_embeddings.embed_documents(["a", "b"])
