"""The OpenAI embedding client: order across batches, retries, and loud failures."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.constants.memory import HOSTED_EMBEDDING_RETRIES, MEMORY_VECTOR_MODEL
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


def _scripted(*outcomes: httpx.Response | Exception) -> tuple[httpx.AsyncClient, list[object]]:
    """Answer each request with the next outcome, recording each request's body."""
    remaining = list(outcomes)
    bodies: list[object] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return _client(httpx.MockTransport(respond)), bodies


async def test_documents_retry_a_retryable_status_with_exponential_backoff() -> None:
    client, bodies = _scripted(httpx.Response(503), httpx.Response(429), _reply([[1.0], [2.0]]))
    with (
        patch.object(hosted_embeddings, "_client", return_value=client),
        patch.object(asyncio, "sleep", AsyncMock()) as sleep,
    ):
        vectors = await hosted_embeddings.embed_documents(["a", "b"])

    assert vectors == [[1.0], [2.0]]
    assert [call.args[0] for call in sleep.await_args_list] == [1, 2]
    assert bodies == [{"model": MEMORY_VECTOR_MODEL, "input": ["a", "b"]}] * 3


async def test_documents_retry_a_dropped_connection_then_raise_the_last_one() -> None:
    client, bodies = _scripted(*(httpx.ConnectError(f"down {n}") for n in range(3)))
    with (
        patch.object(hosted_embeddings, "_client", return_value=client),
        patch.object(asyncio, "sleep", AsyncMock()) as sleep,
        pytest.raises(httpx.ConnectError, match="down 2"),
    ):
        await hosted_embeddings.embed_documents(["a"])

    assert len(bodies) == HOSTED_EMBEDDING_RETRIES + 1
    assert [call.args[0] for call in sleep.await_args_list] == [1, 2]


async def test_a_status_still_retryable_on_the_last_try_raises_it() -> None:
    client, bodies = _scripted(*(httpx.Response(502) for _ in range(3)))
    with (
        patch.object(hosted_embeddings, "_client", return_value=client),
        patch.object(asyncio, "sleep", AsyncMock()),
        pytest.raises(hosted_embeddings.HostedEmbeddingError, match="HTTP 502"),
    ):
        await hosted_embeddings.embed_documents(["a"])

    assert len(bodies) == HOSTED_EMBEDDING_RETRIES + 1


async def test_a_query_is_sent_alone_and_never_retried() -> None:
    """The reply path's budget bounds a query; a backoff sleep would only burn it."""
    client, bodies = _scripted(httpx.Response(503), _reply([[1.0]]))
    with (
        patch.object(hosted_embeddings, "_client", return_value=client),
        patch.object(asyncio, "sleep", AsyncMock()) as sleep,
        pytest.raises(hosted_embeddings.HostedEmbeddingError, match="HTTP 503"),
    ):
        await hosted_embeddings.embed_query("hi")

    assert bodies == [{"model": MEMORY_VECTOR_MODEL, "input": ["hi"]}]
    sleep.assert_not_awaited()


async def test_a_refusal_quotes_a_bounded_slice_of_the_providers_body() -> None:
    client, _ = _scripted(httpx.Response(400, text="x" * 1000))
    with (
        patch.object(hosted_embeddings, "_client", return_value=client),
        pytest.raises(hosted_embeddings.HostedEmbeddingError) as raised,
    ):
        await hosted_embeddings.embed_query("hi")

    assert str(raised.value).endswith(" " + "x" * 300)
