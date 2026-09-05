"""Unit tests for the resilient embeddings wrapper.

Two behaviours are pinned here, both learned from a real incident: a single
``retrieve_tools`` turn fanned out one similarity search per namespace, each
embedding the *same* query text, so one turn spent 2–5 identical calls against
the Vertex per-minute quota; when the quota tripped, the 429 killed the whole
tool call.

- **Coalescing**: concurrent ``aembed_query`` calls for the same text embed once.
- **Retry**: a transient 429/5xx is retried with backoff; a permanent 4xx is not.
"""

import asyncio

from google.genai.errors import ClientError, ServerError
from langchain_core.embeddings import Embeddings
from langchain_google_genai._common import GoogleGenerativeAIError
import pytest

from app.db.chroma import resilient_embeddings
from app.db.chroma.resilient_embeddings import ResilientEmbeddings

_MODEL = "models/gemini-embedding-001"


def _wrapped_api_error(code: int) -> GoogleGenerativeAIError:
    """A GoogleGenerativeAIError wrapping an SDK APIError, exactly as
    ``GoogleGenerativeAIEmbeddings`` raises it (real status on ``__cause__``)."""
    body = {"error": {"code": code, "status": "STATUS", "message": "boom"}}
    sdk_error = ServerError(code, body) if code >= 500 else ClientError(code, body)
    wrapper = GoogleGenerativeAIError(f"Error embedding content ({code})")
    wrapper.__cause__ = sdk_error
    return wrapper


class _GatedEmbeddings(Embeddings):
    """Counts calls and blocks ``aembed_query`` on a gate so concurrent callers
    are guaranteed to overlap in flight."""

    def __init__(self) -> None:
        self.query_calls = 0
        self.gate = asyncio.Event()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    async def aembed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        await self.gate.wait()
        return [float(len(text))]


class _FlakyEmbeddings(Embeddings):
    """Raises the queued errors on successive ``aembed_query`` calls, then
    returns a fixed vector."""

    def __init__(self, errors: list[BaseException]) -> None:
        self.errors = errors
        self.query_calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    async def aembed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return [1.0]


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep retries instant so the tests don't sleep for real."""
    monkeypatch.setattr(resilient_embeddings, "EMBEDDING_RETRY_BASE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(resilient_embeddings, "EMBEDDING_RETRY_MAX_DELAY_SECONDS", 0.0)


@pytest.mark.unit
class TestCoalescing:
    async def test_concurrent_same_query_embeds_once(self) -> None:
        fake = _GatedEmbeddings()
        wrapper = ResilientEmbeddings(fake, model=_MODEL)
        query = "list github pull requests — coalesce-once"

        tasks = [asyncio.create_task(wrapper.aembed_query(query)) for _ in range(5)]
        # Let every caller register on the shared in-flight embed before it finishes.
        await asyncio.sleep(0.05)
        assert fake.query_calls == 1

        fake.gate.set()
        results = await asyncio.gather(*tasks)

        assert fake.query_calls == 1
        assert all(r == [float(len(query))] for r in results)

    async def test_distinct_queries_are_not_coalesced(self) -> None:
        fake = _GatedEmbeddings()
        fake.gate.set()
        wrapper = ResilientEmbeddings(fake, model=_MODEL)

        await asyncio.gather(
            wrapper.aembed_query("send an email — distinct-a"),
            wrapper.aembed_query("create a github issue — distinct-b"),
        )

        assert fake.query_calls == 2


@pytest.mark.unit
class TestRetry:
    async def test_transient_rate_limit_is_retried(self) -> None:
        fake = _FlakyEmbeddings(errors=[_wrapped_api_error(429)])
        wrapper = ResilientEmbeddings(fake, model=_MODEL)

        result = await wrapper.aembed_query("retry-me-429")

        assert result == [1.0]
        assert fake.query_calls == 2

    async def test_transient_server_error_is_retried(self) -> None:
        fake = _FlakyEmbeddings(errors=[_wrapped_api_error(503)])
        wrapper = ResilientEmbeddings(fake, model=_MODEL)

        result = await wrapper.aembed_query("retry-me-503")

        assert result == [1.0]
        assert fake.query_calls == 2

    async def test_permanent_error_is_not_retried(self) -> None:
        fake = _FlakyEmbeddings(errors=[_wrapped_api_error(400)])
        wrapper = ResilientEmbeddings(fake, model=_MODEL)

        with pytest.raises(GoogleGenerativeAIError):
            await wrapper.aembed_query("do-not-retry-400")

        assert fake.query_calls == 1

    async def test_retry_budget_is_bounded(self) -> None:
        attempts = resilient_embeddings.EMBEDDING_RETRY_MAX_ATTEMPTS
        fake = _FlakyEmbeddings(errors=[_wrapped_api_error(429) for _ in range(attempts + 2)])
        wrapper = ResilientEmbeddings(fake, model=_MODEL)

        with pytest.raises(GoogleGenerativeAIError):
            await wrapper.aembed_query("always-429")

        assert fake.query_calls == attempts

    async def test_document_batches_are_retried(self) -> None:
        class _FlakyDocs(Embeddings):
            def __init__(self) -> None:
                self.calls = 0

            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.0] for _ in texts]

            def embed_query(self, text: str) -> list[float]:
                return [0.0]

            async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
                self.calls += 1
                if self.calls == 1:
                    raise _wrapped_api_error(429)
                return [[1.0] for _ in texts]

            async def aembed_query(self, text: str) -> list[float]:
                return [0.0]

        fake = _FlakyDocs()
        wrapper = ResilientEmbeddings(fake, model=_MODEL)

        result = await wrapper.aembed_documents(["a", "b"])

        assert result == [[1.0], [1.0]]
        assert fake.calls == 2
