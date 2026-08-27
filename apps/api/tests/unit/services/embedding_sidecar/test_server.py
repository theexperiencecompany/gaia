"""Unit tests for the embedding sidecar service (app.services.embedding_sidecar.server).

The sidecar is a standalone FastAPI app that reuses the in-process
``_embed_sync`` / ``_embed_query_sync`` / ``_rerank_sync`` helpers from
``app.memory.embeddings``. The server module binds those helpers into its own
namespace at import time, so the tests patch that binding — the exact seam the
production code calls — and drive the app over ASGI to exercise the real
routing, request validation, and response contract (the response keys
``vectors`` / ``vector`` / ``scores`` are what the HTTP client in
``app.memory.embeddings`` reads back). Model weights never load; the
``/health``, happy-path, empty-input, validation, and error paths are all
covered hermetically.
"""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch

import httpx
from httpx import ASGITransport, AsyncClient
import pytest

from app.memory import embeddings
from app.services.embedding_sidecar import server

TEXTS = ["first passage", "second passage"]
VECTORS = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
QUERY = "what is gaia"
QUERY_VECTOR = [0.7, 0.8, 0.9]
DOCUMENTS = ["doc one", "doc two", "doc three"]
SCORES = [0.95, 0.62, 0.41]


@pytest.fixture
async def sidecar_client() -> AsyncGenerator[AsyncClient, None]:
    """Async client for the real sidecar app.

    ASGITransport never runs the lifespan, so no model-warmup call happens
    here; the lifespan (and its failure mode) is covered by the direct
    ``_lifespan`` tests below.
    """
    transport = ASGITransport(app=server.app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestHealth:
    async def test_health_returns_ok(self, sidecar_client: AsyncClient) -> None:
        response = await sidecar_client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestEmbed:
    @patch.object(server, "_embed_sync", return_value=VECTORS)
    async def test_embeds_texts_and_returns_vectors(
        self, mock_embed: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        response = await sidecar_client.post("/embed", json={"texts": TEXTS})

        assert response.status_code == 200
        assert response.json() == {"vectors": VECTORS}
        mock_embed.assert_called_once_with(TEXTS)

    @patch.object(server, "_embed_sync", return_value=VECTORS)
    async def test_empty_texts_returns_empty_without_calling_model(
        self, mock_embed: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        response = await sidecar_client.post("/embed", json={"texts": []})

        assert response.status_code == 200
        assert response.json() == {"vectors": []}
        mock_embed.assert_not_called()

    async def test_missing_texts_is_rejected(self, sidecar_client: AsyncClient) -> None:
        response = await sidecar_client.post("/embed", json={})

        assert response.status_code == 422

    @patch.object(server, "_embed_sync", side_effect=RuntimeError("model failed"))
    async def test_model_failure_surfaces_as_500(
        self, mock_embed: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        response = await sidecar_client.post("/embed", json={"texts": TEXTS})

        assert response.status_code == 500


class TestEmbedQuery:
    @patch.object(server, "_embed_query_sync", return_value=QUERY_VECTOR)
    async def test_embeds_query_and_returns_vector(
        self, mock_embed_query: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        response = await sidecar_client.post("/embed_query", json={"text": QUERY})

        assert response.status_code == 200
        assert response.json() == {"vector": QUERY_VECTOR}
        mock_embed_query.assert_called_once_with(QUERY)

    async def test_missing_text_is_rejected(self, sidecar_client: AsyncClient) -> None:
        response = await sidecar_client.post("/embed_query", json={})

        assert response.status_code == 422

    @patch.object(server, "_embed_query_sync", side_effect=RuntimeError("model failed"))
    async def test_model_failure_surfaces_as_500(
        self, mock_embed_query: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        response = await sidecar_client.post("/embed_query", json={"text": QUERY})

        assert response.status_code == 500


class TestRerank:
    @patch.object(server, "_rerank_sync", return_value=SCORES)
    async def test_scores_documents_and_returns_scores(
        self, mock_rerank: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        response = await sidecar_client.post(
            "/rerank", json={"query": QUERY, "documents": DOCUMENTS}
        )

        assert response.status_code == 200
        assert response.json() == {"scores": SCORES}
        mock_rerank.assert_called_once_with(QUERY, DOCUMENTS)

    @patch.object(server, "_rerank_sync", return_value=SCORES)
    async def test_empty_documents_returns_empty_without_calling_model(
        self, mock_rerank: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        response = await sidecar_client.post("/rerank", json={"query": QUERY, "documents": []})

        assert response.status_code == 200
        assert response.json() == {"scores": []}
        mock_rerank.assert_not_called()

    async def test_missing_documents_is_rejected(self, sidecar_client: AsyncClient) -> None:
        response = await sidecar_client.post("/rerank", json={"query": QUERY})

        assert response.status_code == 422

    @patch.object(server, "_rerank_sync", side_effect=RuntimeError("model failed"))
    async def test_model_failure_surfaces_as_500(
        self, mock_rerank: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        response = await sidecar_client.post(
            "/rerank", json={"query": QUERY, "documents": DOCUMENTS}
        )

        assert response.status_code == 500


class TestLifespan:
    @patch.object(server.log, "info")
    @patch.object(server, "_rerank_sync", return_value=SCORES)
    @patch.object(server, "_embed_sync", return_value=VECTORS)
    async def test_warmup_calls_both_models_before_start(
        self, mock_embed: MagicMock, mock_rerank: MagicMock, mock_log: MagicMock
    ) -> None:
        async with server._lifespan(server.app):
            pass

        mock_embed.assert_called_once_with(["warmup"])
        mock_rerank.assert_called_once_with("warmup", ["warmup"])
        mock_log.assert_called_once_with("embedding sidecar ready")

    @patch.object(server, "_rerank_sync", return_value=SCORES)
    @patch.object(server, "_embed_sync", side_effect=RuntimeError("model download failed"))
    async def test_broken_model_fails_startup(
        self, mock_embed: MagicMock, mock_rerank: MagicMock
    ) -> None:
        with pytest.raises(RuntimeError, match="model download failed"):
            async with server._lifespan(server.app):
                pass

        mock_rerank.assert_not_called()


class TestRequestBounds:
    @patch.object(server, "_embed_sync", return_value=VECTORS)
    async def test_oversized_single_text_rejected_with_413(
        self, mock_embed: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        oversized = "x" * (server.EMBEDDING_SIDECAR_MAX_TEXT_CHARS + 1)
        response = await sidecar_client.post("/embed", json={"texts": [oversized]})

        assert response.status_code == 413
        assert "MAX_TEXT_CHARS" in response.json()["detail"]
        mock_embed.assert_not_called()

    @patch.object(server, "_embed_query_sync", return_value=QUERY_VECTOR)
    async def test_oversized_single_query_rejected_with_413(
        self, mock_embed_query: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        response = await sidecar_client.post(
            "/embed_query", json={"text": "x" * (server.EMBEDDING_SIDECAR_MAX_TEXT_CHARS + 1)}
        )

        assert response.status_code == 413
        mock_embed_query.assert_not_called()

    @patch.object(server, "_rerank_sync", return_value=SCORES)
    async def test_oversized_rerank_query_rejected_with_413(
        self, mock_rerank: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        # The query is model input too — an uncapped one must not reach it.
        response = await sidecar_client.post(
            "/rerank",
            json={
                "query": "x" * (server.EMBEDDING_SIDECAR_MAX_TEXT_CHARS + 1),
                "documents": DOCUMENTS,
            },
        )

        assert response.status_code == 413
        mock_rerank.assert_not_called()

    @patch.object(server, "_embed_sync", return_value=VECTORS)
    async def test_text_exactly_at_cap_is_accepted(
        self, mock_embed: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        # The cap is exclusive (>), not inclusive (>=): a text at exactly the
        # limit is legitimate input.
        text = "x" * server.EMBEDDING_SIDECAR_MAX_TEXT_CHARS
        response = await sidecar_client.post("/embed", json={"texts": [text]})

        assert response.status_code == 200

    @patch.object(server, "_embed_sync", return_value=VECTORS)
    async def test_large_batch_passes_through_in_one_call(
        self, mock_embed: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        # Memory bounding happens inside _embed_sync's explicit fastembed
        # batch_size; the endpoint forwards the full list unchanged.
        texts = [f"t{i}" * 10 for i in range(100)]
        response = await sidecar_client.post("/embed", json={"texts": texts})

        assert response.status_code == 200
        mock_embed.assert_called_once_with(texts)


class TestSaturationBackpressure:
    async def test_full_slots_return_503_after_bounded_wait(
        self, sidecar_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # One-slot pool so holding it truly saturates the sidecar.
        monkeypatch.setattr(server, "_slot_wait_seconds", 0.05)
        monkeypatch.setattr(server, "_inference_slots", asyncio.Semaphore(1))

        async with server._inference_slots:
            response = await sidecar_client.post("/embed", json={"texts": TEXTS})

        assert response.status_code == 503
        assert response.json()["detail"] == "embedding sidecar busy; retry shortly"

    async def test_503_exception_carries_exact_backoff_contract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 503's shape is a contract clients rely on: exact status, detail
        text, and Retry-After header name/value."""
        monkeypatch.setattr(server, "_slot_wait_seconds", 0.0)
        monkeypatch.setattr(server, "_inference_slots", asyncio.Semaphore(1))
        async with server._inference_slots:
            with pytest.raises(server.HTTPException) as exc_info:
                await server.embed(server.EmbedRequest(texts=TEXTS))

        exc = exc_info.value
        assert exc.status_code == 503
        assert exc.detail == "embedding sidecar busy; retry shortly"
        assert exc.headers == {"Retry-After": "5"}

    @patch.object(server, "_embed_sync", return_value=VECTORS)
    async def test_slot_released_after_success(
        self, _mock_embed: MagicMock, sidecar_client: AsyncClient
    ) -> None:
        for _ in range(3):
            response = await sidecar_client.post("/embed", json={"texts": TEXTS})
            assert response.status_code == 200


class TestClientRetryContract:
    """Pinned here as well as in tests/unit/memory/test_embeddings.py: the
    retry budget is what keeps memory saves alive through a sidecar blip."""

    async def test_rerank_splits_and_preserves_scores(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Second home for the chunked-rerank contract so the mutation lane
        attributes it from both covering files."""
        calls: list[dict] = []

        async def fake_post(path: str, payload: dict) -> dict:
            assert path == "/rerank"
            assert set(payload) == {"query", "documents"}
            calls.append({"q": payload["query"], "n": len(payload["documents"])})
            return {"scores": [float(len(calls))] * len(payload["documents"])}

        observed: list[tuple[str, str, int]] = []

        async def fake_observed(operation: str, backend: str, count: int, awaitable):
            observed.append((operation, backend, count))
            return await awaitable

        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: "http://sidecar.test")
        monkeypatch.setattr(embeddings, "_sidecar_post", fake_post)
        monkeypatch.setattr(embeddings, "_observed", fake_observed)
        monkeypatch.setattr(embeddings, "EMBEDDING_SIDECAR_MAX_BATCH_TEXTS", 30)

        scores = await embeddings.rerank("the query", [f"doc {i}" for i in range(45)])

        assert calls == [
            {"q": "the query", "n": 30},
            {"q": "the query", "n": 15},
        ]
        assert observed == [("rerank", "sidecar", 30), ("rerank", "sidecar", 15)]
        assert scores == [1.0] * 30 + [2.0] * 15

    async def test_exhausted_budget_raises_after_exact_attempts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts: list[httpx.Request] = []
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            return httpx.Response(503)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(embeddings, "EMBEDDING_SIDECAR_RETRIES", 2)
        max_wait = embeddings.EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS

        # Exhausted budget hands back the last response; _sidecar_post turns
        # it into a loud failure via raise_for_status.
        response = await embeddings._post_with_retry(
            client, "http://sidecar.test/embed", {"texts": ["a"]}
        )

        assert response.status_code == 503
        assert len(attempts) == 3
        assert sleeps == [max_wait, max_wait]

    async def test_retry_succeeds_within_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        attempts: list[httpx.Request] = []

        async def fake_sleep(delay: float) -> None:
            pass

        responses = [httpx.Response(503), httpx.Response(200, json={"ok": True})]

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            return responses.pop(0)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        response = await embeddings._post_with_retry(
            client, "http://sidecar.test/embed", {"texts": ["a"]}
        )

        assert response.status_code == 200
        assert len(attempts) == 2
