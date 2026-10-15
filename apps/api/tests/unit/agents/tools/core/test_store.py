"""init_embeddings picks Gemini when a Google key exists and the keyless local model otherwise."""

from langchain_google_genai import GoogleGenerativeAIEmbeddings
import pytest

from app.agents.tools.core.local_embeddings import FastEmbedEmbeddings
from app.agents.tools.core.store import init_embeddings
from app.config.settings import settings


def test_a_google_key_selects_gemini_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "google-test-key")  # pragma: allowlist secret

    embeddings = init_embeddings().loader_func()

    assert isinstance(embeddings, GoogleGenerativeAIEmbeddings)
    assert embeddings.model == "models/gemini-embedding-001"


def test_no_google_key_falls_back_to_the_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)

    assert isinstance(init_embeddings().loader_func(), FastEmbedEmbeddings)
