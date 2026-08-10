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

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch

from httpx import ASGITransport, AsyncClient
import pytest

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
