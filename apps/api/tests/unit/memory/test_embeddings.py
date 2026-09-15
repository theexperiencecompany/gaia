"""Unit tests for app.memory.embeddings batching/chunking behavior (#918).

The sidecar OOM-killed on large batches because fastembed's default internal
``batch_size=256`` materializes gigabytes of ONNX activations in one forward
pass. The fix bounds every fastembed call with an explicit small batch size
and splits oversized client requests into bounded HTTP calls. These tests pin
the chunking contract and that the sync helpers never invoke fastembed with
its unbounded default.
"""

import asyncio
from collections.abc import Awaitable
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.memory import embeddings
from app.memory.embeddings import chunk_texts
from tests.helpers import captured_wide_event


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

    def test_char_budget_boundary_is_inclusive(self) -> None:
        # A chunk whose total lands exactly on the budget is still valid —
        # the overflow check is strict.
        assert chunk_texts(["ab", "c"], max_texts=99, max_chars=3) == [["ab", "c"]]

    def test_running_total_overflows_across_appends(self) -> None:
        # The budget applies to the chunk's TOTAL length, not the last text.
        assert chunk_texts(["abcd", "abcd", "d"], max_texts=99, max_chars=8) == [
            ["abcd", "abcd"],
            ["d"],
        ]

    def test_counter_resets_after_flush(self) -> None:
        # After a flush the new chunk's count starts from zero, so a text that
        # fits alone (and one more that completes it exactly) share a chunk.
        assert chunk_texts(["abcde", "abcd", "d"], max_texts=99, max_chars=5) == [
            ["abcde"],
            ["abcd", "d"],
        ]

    def test_oversized_single_text_kept_whole_in_own_chunk(self) -> None:
        # A single text over the char budget must still appear exactly once —
        # truncation to the model's token window happens inside fastembed.
        big = "b" * 500
        texts = ["small", big]
        chunks = chunk_texts(texts, max_texts=16, max_chars=100)
        assert chunks == [["small"], [big]]


class TestEmbedBatchSplitsRequests:
    @pytest.fixture
    def recorder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[list[dict], list[tuple[str, str, int]]]:
        """Strict sidecar stand-in: unexpected paths/payloads fail loudly, and
        every _observed(operation, backend, count) annotation is captured."""
        calls: list[dict] = []
        observed: list[tuple[str, str, int]] = []

        async def fake_observed(
            operation: str, backend: str, count: int, awaitable: Awaitable[Any]
        ) -> Any:
            observed.append((operation, backend, count))
            return await awaitable

        async def fake_post(path: str, payload: dict, *, interactive: bool = False) -> dict:
            if path == "/embed_query":
                assert set(payload) == {"text"}
                calls.append({"path": path, "text": payload["text"]})
                return {"vector": [0.0]}
            if path == "/embed":
                assert set(payload) == {"texts"}
                calls.append({"path": path, "n": len(payload["texts"])})
                return {"vectors": [[0.0]] * len(payload["texts"])}
            if path == "/rerank":
                assert set(payload) == {"query", "documents"}
                calls.append(
                    {"path": path, "query": payload["query"], "n": len(payload["documents"])}
                )
                return {"scores": [0.5 * len(calls)] * len(payload["documents"])}
            raise AssertionError(f"unexpected sidecar path: {path}")

        monkeypatch.setattr(embeddings, "_observed", fake_observed)
        monkeypatch.setattr(embeddings, "_sidecar_post", fake_post)
        return calls, observed

    async def test_embed_query_sidecar_call_is_annotated_and_typed(
        self,
        recorder: tuple[list[dict], list[tuple[str, str, int]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls, observed = recorder
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: "http://sidecar:8200")

        vector = await embeddings.embed_query("what was decided")

        assert calls == [{"path": "/embed_query", "text": "what was decided"}]
        assert observed == [("embed_query", "sidecar", 1)]
        assert vector == [0.0]

    @patch.object(embeddings, "_sidecar_url", return_value="http://sidecar:8200")
    async def test_embed_batch_splits_into_bounded_http_calls(
        self,
        _mock_url: MagicMock,
        recorder: tuple[list[dict], list[tuple[str, str, int]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls, observed = recorder
        monkeypatch.setattr(embeddings, "EMBEDDING_SIDECAR_MAX_BATCH_TEXTS", 16)
        texts = [f"text {i}" for i in range(40)]

        vectors = await embeddings.embed_batch(texts)

        assert [(c["path"], c["n"]) for c in calls] == [
            ("/embed", 16),
            ("/embed", 16),
            ("/embed", 8),
        ]
        assert observed == [
            ("embed", "sidecar", 16),
            ("embed", "sidecar", 16),
            ("embed", "sidecar", 8),
        ]
        assert len(vectors) == 40

    @patch.object(embeddings, "_sidecar_url", return_value="http://sidecar:8200")
    async def test_rerank_splits_documents_preserving_order_and_query(
        self,
        _mock_url: MagicMock,
        recorder: tuple[list[dict], list[tuple[str, str, int]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls, observed = recorder
        monkeypatch.setattr(embeddings, "EMBEDDING_SIDECAR_MAX_BATCH_TEXTS", 30)
        documents = [f"doc {i}" for i in range(45)]

        scores = await embeddings.rerank("what was decided", documents)

        assert [(c["path"], c["query"], c["n"]) for c in calls] == [
            ("/rerank", "what was decided", 30),
            ("/rerank", "what was decided", 15),
        ]
        assert observed == [("rerank", "sidecar", 30), ("rerank", "sidecar", 15)]
        assert scores == [0.5 * 1] * 30 + [0.5 * 2] * 15

    @patch.object(embeddings, "_sidecar_url", return_value="http://sidecar:8200")
    async def test_rerank_query_consumes_char_budget(
        self,
        _mock_url: MagicMock,
        recorder: tuple[list[dict], list[tuple[str, str, int]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The query rides with every chunk, so it must shrink the document
        allowance — a 10-char query against a 50-char budget caps chunks at
        40 chars."""
        calls, observed = recorder
        monkeypatch.setattr(embeddings, "EMBEDDING_SIDECAR_MAX_BATCH_TEXTS", 99)
        monkeypatch.setattr(embeddings, "EMBEDDING_SIDECAR_MAX_BATCH_CHARS", 50)
        documents = ["d" * 30, "d" * 30, "d" * 5]

        await embeddings.rerank("q" * 10, documents)

        # Budget 40 after the query: one 30-char doc per chunk until a 5-char
        # tag-along fits beside it.
        assert [c["n"] for c in calls] == [1, 2]
        assert observed == [("rerank", "sidecar", 1), ("rerank", "sidecar", 2)]


class TestSharedHttpClient:
    async def test_same_loop_reuses_one_client(self) -> None:
        embeddings._http_client = None
        first = embeddings._get_http_client()
        second = embeddings._get_http_client()
        assert first is second
        assert first.timeout == httpx.Timeout(embeddings.EMBEDDING_SIDECAR_TIMEOUT_SECONDS)

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


class TestTransientRetry:
    """A 503 means the sidecar was briefly overloaded; memory operations must
    survive that blip instead of being dropped."""

    def _client(
        self, monkeypatch: pytest.MonkeyPatch, responses: list[httpx.Response]
    ) -> list[httpx.Request]:
        attempts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            # Strict contract: retried requests must still carry the JSON body.
            assert request.content.startswith(b'{"')
            attempts.append(request)
            return responses.pop(0) if len(responses) > 1 else responses[0]

        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            embeddings,
            "_get_http_client",
            lambda: httpx.AsyncClient(transport=transport),
        )
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: "http://sidecar.test")
        return attempts

    async def test_503_is_retried_with_backoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        attempts = self._client(
            monkeypatch,
            [
                httpx.Response(503),
                httpx.Response(200, json={"ok": True}),
            ],
        )

        result = await embeddings._sidecar_post("/embed", {"texts": ["a"]})

        assert result == {"ok": True}
        assert len(attempts) == 2
        assert sleeps == [embeddings.EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS]

    async def test_exhausted_retries_fail_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        attempts = self._client(monkeypatch, [httpx.Response(503)])

        with pytest.raises(httpx.HTTPStatusError):
            await embeddings._sidecar_post("/embed", {"texts": ["a"]})

        assert len(attempts) == embeddings.EMBEDDING_SIDECAR_RETRIES + 1
        assert sleeps == [embeddings.EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS] * (
            embeddings.EMBEDDING_SIDECAR_RETRIES
        )

    async def test_429_is_retried_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        attempts = self._client(
            monkeypatch,
            [
                httpx.Response(429),
                httpx.Response(200, json={"ok": True}),
            ],
        )
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        result = await embeddings._sidecar_post("/embed", {"texts": ["a"]})

        assert result == {"ok": True}
        assert len(attempts) == 2
        assert sleeps == [embeddings.EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS]

    async def test_connection_error_is_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        failures_left = 1

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal failures_left
            if failures_left > 0:
                failures_left -= 1
                raise httpx.ConnectError("sidecar restarting", request=request)
            return httpx.Response(200, json={"ok": True})

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(
            embeddings,
            "_get_http_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: "http://sidecar.test")

        result = await embeddings._sidecar_post("/embed_query", {"text": "q"})

        assert result == {"ok": True}
        assert sleeps == [embeddings.EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS]

    async def test_transport_budget_is_consumed_per_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two connection errors must consume exactly two budget units: a third
        error would exceed the budget and fail loudly, while the retry that
        follows still succeeds. This pins the countdown, not just 'it retried'."""
        sleeps: list[float] = []
        failures_left = 2

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal failures_left
            if failures_left > 0:
                failures_left -= 1
                raise httpx.ConnectError("sidecar restarting", request=request)
            return httpx.Response(200, json={"ok": True})

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(
            embeddings,
            "_get_http_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: "http://sidecar.test")

        result = await embeddings._sidecar_post("/embed_query", {"text": "q"})

        assert result == {"ok": True}
        assert sleeps == [
            embeddings.EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS,
            embeddings.EMBEDDING_SIDECAR_RETRY_MAX_WAIT_SECONDS,
        ]

    async def test_transport_budget_exhaustion_fails_loud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Three consecutive connection errors exhaust the default budget of
        two retries: the original connection error propagates instead of the
        operation being silently dropped."""
        failures_left = 99

        async def fake_sleep(delay: float) -> None:
            pass

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal failures_left
            if failures_left > 0:
                failures_left -= 1
                raise httpx.ConnectError("sidecar restarting", request=request)
            return httpx.Response(200, json={"ok": True})

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(
            embeddings,
            "_get_http_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: "http://sidecar.test")

        with pytest.raises(httpx.ConnectError):
            await embeddings._sidecar_post("/embed_query", {"text": "q"})


class TestPooledClientThroughPublicApi:
    async def test_embed_query_reuses_one_pooled_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The public path must go through the shared pool: one client for
        repeated calls, our configured timeout, and a fresh client when the
        previous one was closed."""
        embeddings._http_client = None
        made: list[httpx.AsyncClient] = []
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"vector": [0.0]})

        transport = httpx.MockTransport(handler)
        real_cls = httpx.AsyncClient

        class Tracking(real_cls):
            def __init__(self, **kwargs: object) -> None:
                super().__init__(transport=transport, **kwargs)
                made.append(self)

        monkeypatch.setattr(embeddings.httpx, "AsyncClient", Tracking)
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: "http://sidecar.test")

        await embeddings.embed_query("one")
        await embeddings.embed_query("two")

        assert len(made) == 1
        assert calls["n"] == 2
        assert made[0].timeout == httpx.Timeout(embeddings.EMBEDDING_SIDECAR_TIMEOUT_SECONDS)

        closed = made[0]
        await closed.aclose()
        await embeddings.embed_query("three")
        assert len(made) == 2  # closed pools are replaced, not reused


class TestInteractiveBudget:
    """Recall on a user turn fails fast; ingestion keeps the durable budget."""

    def test_call_budget_interactive_drops_retries_and_shortens_timeout(self) -> None:
        assert embeddings._call_budget(interactive=True) == (
            0,
            embeddings.EMBEDDING_SIDECAR_INTERACTIVE_TIMEOUT_SECONDS,
        )
        assert embeddings._call_budget(interactive=False) == (
            embeddings.EMBEDDING_SIDECAR_RETRIES,
            embeddings.EMBEDDING_SIDECAR_TIMEOUT_SECONDS,
        )

    async def test_interactive_call_uses_short_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[float] = []

        class RecordingClient:
            async def post(self, url: str, json: dict, timeout: float) -> httpx.Response:
                seen.append(timeout)
                return httpx.Response(
                    200, json={"vector": [0.1]}, request=httpx.Request("POST", url)
                )

        monkeypatch.setattr(embeddings, "_get_http_client", RecordingClient)
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: "http://sidecar.test")

        await embeddings.embed_query("q", interactive=True)
        await embeddings.embed_query("q", interactive=False)

        assert seen == [
            embeddings.EMBEDDING_SIDECAR_INTERACTIVE_TIMEOUT_SECONDS,
            embeddings.EMBEDDING_SIDECAR_TIMEOUT_SECONDS,
        ]

    async def test_interactive_503_fails_fast_without_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts: list[httpx.Request] = []
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            return httpx.Response(503)

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(
            embeddings,
            "_get_http_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: "http://sidecar.test")

        with pytest.raises(httpx.HTTPStatusError):
            await embeddings.rerank("q", ["doc"], interactive=True)

        assert len(attempts) == 1  # no retry on the interactive path
        assert sleeps == []

    async def test_interactive_rerank_deadline_spans_all_chunks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A large candidate set splits into several chunks; the interactive
        # budget must bound the WHOLE rerank, not reset per chunk. Each chunk
        # sleeps under the deadline, but two of them together exceed it.
        monkeypatch.setattr(embeddings, "EMBEDDING_SIDECAR_INTERACTIVE_TIMEOUT_SECONDS", 0.1)
        monkeypatch.setattr(embeddings, "EMBEDDING_SIDECAR_MAX_BATCH_TEXTS", 1)
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: "http://sidecar.test")

        async def slow_post(path: str, payload: dict, *, interactive: bool = False) -> dict:
            await asyncio.sleep(0.06)
            return {"scores": [0.0] * len(payload["documents"])}

        monkeypatch.setattr(embeddings, "_sidecar_post", slow_post)

        with pytest.raises(TimeoutError):
            await embeddings.rerank("q", ["a", "b"], interactive=True)

    async def test_background_rerank_keeps_the_durable_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Background rerank (interactive=False) must retry a transient 503 —
        # the opposite of the interactive path's fail-fast.
        attempts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            return (
                httpx.Response(503)
                if len(attempts) == 1
                else httpx.Response(200, json={"scores": [0.4]})
            )

        async def fake_sleep(delay: float) -> None:
            pass

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(
            embeddings,
            "_get_http_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: "http://sidecar.test")

        scores = await embeddings.rerank("q", ["doc"], interactive=False)

        assert scores == [0.4]
        assert len(attempts) == 2  # retried, unlike the interactive path

    async def test_embed_query_local_path_returns_the_model_vector(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With no sidecar URL, embed_query runs the in-process model helper with
        # the real query text.
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: None)
        seen: dict[str, str] = {}

        def fake_sync(text: str) -> list[float]:
            seen["text"] = text
            return [0.1, 0.2]

        monkeypatch.setattr(embeddings, "_embed_query_sync", fake_sync)

        assert await embeddings.embed_query("the query") == [0.1, 0.2]
        assert seen["text"] == "the query"

    async def test_embed_query_local_failure_is_annotated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A local-model failure is annotated with operation/backend/batch_size so
        # it is queryable, then re-raised.
        monkeypatch.setattr(embeddings, "_sidecar_url", lambda: None)

        def boom(text: str) -> list[float]:
            raise RuntimeError("model down")

        monkeypatch.setattr(embeddings, "_embed_query_sync", boom)

        async with captured_wide_event() as event:
            with pytest.raises(RuntimeError):
                await embeddings.embed_query("the query")

        (error,) = event["errors"]
        assert error["msg"] == "memory_embedding_failed"
        assert error["operation"] == "embed_query"
        assert error["backend"] == "local"
        assert error["batch_size"] == 1
