"""init_embeddings picks Gemini when a Google key exists and the keyless local model otherwise."""

from langchain_google_genai import GoogleGenerativeAIEmbeddings
import pytest

from app.agents.tools.core.local_embeddings import FastEmbedEmbeddings
from app.agents.tools.core.store import embedding_dims, init_embeddings
from app.config.settings import settings
from app.constants.chroma import GEMINI_EMBEDDING_DIMS, GEMINI_EMBEDDING_MODEL
from app.constants.memory import EMBEDDING_DIM


def test_a_google_key_selects_gemini_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "google-test-key")  # pragma: allowlist secret

    embeddings = init_embeddings().loader_func()

    assert isinstance(embeddings, GoogleGenerativeAIEmbeddings)
    assert embeddings.model == GEMINI_EMBEDDING_MODEL
    assert embedding_dims(embeddings) == GEMINI_EMBEDDING_DIMS


def test_no_google_key_falls_back_to_the_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)

    embeddings = init_embeddings().loader_func()

    assert isinstance(embeddings, FastEmbedEmbeddings)
    assert embedding_dims(embeddings) == EMBEDDING_DIM
