"""init_embeddings picks Gemini when a Google key exists and the keyless local model otherwise."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from google.genai.errors import APIError, ClientError, ServerError
from google.genai.types import EmbedContentConfig
from pydantic import SecretStr
import pytest

from app.agents.tools.core import store as store_module
from app.agents.tools.core.local_embeddings import FastEmbedEmbeddings
from app.agents.tools.core.store import RetryingGeminiEmbeddings, embedding_dims, init_embeddings
from app.config.settings import settings
from app.constants.chroma import (
    GEMINI_EMBED_QUERY_RETRIES,
    GEMINI_EMBEDDING_DIMS,
    GEMINI_EMBEDDING_MODEL,
)
from app.constants.log_tags import LogTag
from app.constants.memory import EMBEDDING_DIM
from shared.py.retry import RetryPolicy
from tests.helpers import captured_wide_event

_VECTOR = [0.25, 0.5]


def test_a_google_key_selects_gemini_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "google-test-key")  # pragma: allowlist secret

    embeddings = init_embeddings().loader_func()

    assert isinstance(embeddings, RetryingGeminiEmbeddings)
    assert embeddings.model == GEMINI_EMBEDDING_MODEL
    assert embedding_dims(embeddings) == GEMINI_EMBEDDING_DIMS


def test_no_google_key_falls_back_to_the_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)

    embeddings = init_embeddings().loader_func()

    assert isinstance(embeddings, FastEmbedEmbeddings)
    assert embedding_dims(embeddings) == EMBEDDING_DIM


def _rate_limited() -> ClientError:
    return ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})


def _gemini(
    monkeypatch: pytest.MonkeyPatch, *answers: object
) -> tuple[RetryingGeminiEmbeddings, AsyncMock]:
    """Gemini embeddings whose SDK call answers each of answers in turn, with no wait between tries."""
    monkeypatch.setattr(
        store_module,
        "_EMBED_QUERY_RETRY",
        RetryPolicy(retries=GEMINI_EMBED_QUERY_RETRIES, min_s=0.0, max_s=0.0),
    )
    embeddings = RetryingGeminiEmbeddings(
        model=GEMINI_EMBEDDING_MODEL,
        api_key=SecretStr("google-test-key"),  # pragma: allowlist secret
    )
    embed_content = AsyncMock(
        side_effect=[
            answer
            if isinstance(answer, APIError)
            else SimpleNamespace(embeddings=[SimpleNamespace(values=answer)])
            for answer in answers
        ]
    )
    embeddings.client = MagicMock()
    embeddings.client.aio.models.embed_content = embed_content
    return embeddings, embed_content


@pytest.mark.regression
async def test_a_rate_limited_query_embed_is_retried_until_it_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for #1171: one 429 failed every namespace search and tool discovery with them."""
    embeddings, embed_content = _gemini(monkeypatch, _rate_limited(), ServerError(503, {}), _VECTOR)

    async with captured_wide_event() as event:
        assert await embeddings.aembed_query("email my boss") == _VECTOR

    assert embed_content.await_count == 3
    assert [(w["msg"], w["attempt"]) for w in event["warnings"]] == [
        (f"{LogTag.CHROMA} Gemini query embed failed, retrying", 1),
        (f"{LogTag.CHROMA} Gemini query embed failed, retrying", 2),
    ]


async def test_a_refused_query_embed_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    embeddings, embed_content = _gemini(monkeypatch, ClientError(400, {}), _VECTOR)

    with pytest.raises(Exception, match="400"):
        await embeddings.aembed_query("email my boss")

    assert embed_content.await_count == 1


async def test_a_quota_that_stays_exhausted_fails_after_the_last_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = GEMINI_EMBED_QUERY_RETRIES + 1
    embeddings, embed_content = _gemini(monkeypatch, *(_rate_limited() for _ in range(attempts)))

    with pytest.raises(Exception, match="429"):
        await embeddings.aembed_query("email my boss")

    assert embed_content.await_count == attempts


async def test_a_retried_query_embed_sends_the_text_and_options_it_was_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embeddings, embed_content = _gemini(monkeypatch, _rate_limited(), _VECTOR)

    await embeddings.aembed_query(
        "email my boss", task_type="retrieval_document", title="Inbox", output_dimensionality=2
    )

    sent = EmbedContentConfig(
        task_type="RETRIEVAL_DOCUMENT", title="Inbox", output_dimensionality=2
    )
    assert [call.kwargs for call in embed_content.await_args_list] == [
        {"model": GEMINI_EMBEDDING_MODEL, "contents": "email my boss", "config": sent}
    ] * 2
