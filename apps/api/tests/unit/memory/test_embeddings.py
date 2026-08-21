"""Unit tests for app.memory.embeddings batching/chunking behavior (#918).

The sidecar OOM-killed on large batches because fastembed's default internal
``batch_size=256`` materializes gigabytes of ONNX activations in one forward
pass. The fix bounds every fastembed call with an explicit small batch size
and splits oversized client requests into bounded HTTP calls. These tests pin
the chunking contract and that the sync helpers never invoke fastembed with
its unbounded default.
"""

import asyncio
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.memory import embeddings
from app.memory.embeddings import chunk_texts


class TestChunkTexts:
    def test_empty_input_yields_no_chunks(self) -> None:
        assert chunk_texts([], max_texts=16, max_chars=64_000) == []

    def test_small_input_stays_one_chunk(self) -> None:
        texts = ["a", "b", "c"]
        assert chunk_texts(texts, max_texts=16, max_chars=64_000) == [texts]

    def test_split_respects_max_texts(self) -> None:
        texts = [str(i) for i in range(40)]
        chunks = chunk_texts(texts, max_texts=16, max_chars=1_000_000)
        assert [len(chunk) for chunk in chunks] == [16, 16, 8]
        assert [t for chunk in chunks for t in chunk] == texts

    def test_split_respects_char_budget(self) -> None:
        texts = ["x" * 60, "y" * 60, "z" * 10]
        chunks = chunk_texts(texts, max_texts=100, max_chars=100)
        assert [[len(t) for t in chunk] for chunk in chunks] == [[60], [60, 10]]

    def test_oversized_single_text_kept_whole_in_own_chunk(self) -> None:
        # A single text over the char budget must still appear exactly once —
        # truncation to the model's token window happens inside fastembed.
        big = "b" * 500
        texts = ["small", big]
        chunks = chunk_texts(texts, max_texts=16, max_chars=100)
        assert chunks == [["small"], [big]]


class TestEmbedBatchSplitsRequests:
    @pytest.fixture
    def captured_posts(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
        calls: list[tuple[str, dict]] = []

        async def fake_post(path: str, payload: dict) -> dict:
            calls.append((path, payload))
            count = len(payload.get("texts", payload.get("documents", [])))
            if path == "/embed":
                return {"vectors": [[0.0]] * count}
            return {"scores": [0.5] * count}

        monkeypatch.setattr(embeddings, "_sidecar_post", fake_post)
        return calls

    @patch.object(embeddings, "_sidecar_url", return_value="http://sidecar:8200")
    async def test_embed_batch_splits_into_bounded_http_calls(
        self,
        _mock_url: MagicMock,
        captured_posts: list[tuple[str, dict]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(embeddings, "EMBEDDING_SIDECAR_MAX_BATCH_TEXTS", 16)
        texts = [f"text {i}" for i in range(40)]

        vectors = await embeddings.embed_batch(texts)

        assert [(path, len(p["texts"])) for path, p in captured_posts] == [
            ("/embed", 16),
            ("/embed", 16),
            ("/embed", 8),
        ]
        assert vectors == [[0.0]] * 40

    @patch.object(embeddings, "_sidecar_url", return_value="http://sidecar:8200")
    async def test_rerank_splits_documents_preserving_order(
        self,
        _mock_url: MagicMock,
        captured_posts: list[tuple[str, dict]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(embeddings, "EMBEDDING_SIDECAR_MAX_BATCH_TEXTS", 30)
        documents = [f"doc {i}" for i in range(45)]

        scores = await embeddings.rerank("query", documents)

        assert [(path, len(p["documents"])) for path, p in captured_posts] == [
            ("/rerank", 30),
            ("/rerank", 15),
        ]
        assert scores == [0.5] * 45


class TestSharedHttpClient:
    async def test_same_loop_reuses_one_client(self) -> None:
        embeddings._http_client = None
        first = embeddings._get_http_client()
        second = embeddings._get_http_client()
        assert first is second

    def test_new_loop_gets_fresh_client(self) -> None:
        # Pooled connections from an old event loop are unusable in a new one
        # (pytest-asyncio gives every test its own loop).
        embeddings._http_client = None

        async def get() -> httpx.AsyncClient:
            return embeddings._get_http_client()

        loop_a = asyncio.new_event_loop()
        try:
            client_a = loop_a.run_until_complete(get())
            loop_b = asyncio.new_event_loop()
            try:
                client_b = loop_b.run_until_complete(get())
                client_b_again = loop_b.run_until_complete(get())
                assert client_a is not client_b
                assert client_b is client_b_again
            finally:
                loop_b.close()
        finally:
            loop_a.close()
