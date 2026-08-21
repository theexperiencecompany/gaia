"""The two auxiliary-model accessors must stay distinct.

``get_summarization_llm`` (whole-history summarization — rewrites the
conversation the user reads) only ever runs on the default model and is dropped
when that is unconfigured. ``get_compaction_summary_llm`` (bulk tool-output
digests) may additionally ride the DEV_LLM_* custom endpoint in development.
These tests pin that boundary so a refactor cannot quietly widen it.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.llm.exceptions import LLMNotConfiguredError
from app.agents.middleware import factory as factory_mod
from app.agents.middleware.factory import (
    get_compaction_summary_llm,
    get_summarization_llm,
)


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch: pytest.MonkeyPatch):
    """Both accessors memoize module globals; isolate every test from the others."""
    monkeypatch.setattr(factory_mod, "_summarization_llm", None)
    monkeypatch.setattr(factory_mod, "_compaction_summary_llm", None)


class TestGetSummarizationLlm:
    def test_default_model_wins_when_configured(self) -> None:
        sentinel = object()
        with patch.object(factory_mod, "get_default_llm", return_value=sentinel) as mock_default:
            assert get_summarization_llm() is sentinel
        mock_default.assert_called_once()

    def test_dropped_without_the_default_model_even_in_dev(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # DEV_LLM_* present and ENV=development: history summarization must STILL
        # be dropped — the dev endpoint never rewrites user-visible history.
        monkeypatch.setattr(factory_mod.settings, "ENV", "development")
        with (
            patch.object(
                factory_mod,
                "get_default_llm",
                side_effect=LLMNotConfiguredError("no openrouter"),
            ),
            patch.object(factory_mod.providers, "is_available", return_value=True),
            patch.object(factory_mod.providers, "get", return_value=object()),
        ):
            assert get_summarization_llm() is None


class TestGetCompactionSummaryLlm:
    def test_default_model_wins_when_configured(self) -> None:
        sentinel = object()
        with patch.object(factory_mod, "get_default_llm", return_value=sentinel) as mock_default:
            assert get_compaction_summary_llm() is sentinel
        mock_default.assert_called_once()

    def test_dev_custom_endpoint_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dev_instance = object()
        monkeypatch.setattr(factory_mod.settings, "ENV", "development")
        with (
            patch.object(
                factory_mod,
                "get_default_llm",
                side_effect=LLMNotConfiguredError("no openrouter"),
            ),
            patch.object(factory_mod.providers, "is_available", return_value=True),
            patch.object(factory_mod.providers, "get", return_value=dev_instance),
        ):
            assert get_compaction_summary_llm() is dev_instance

    def test_no_fallback_outside_development(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(factory_mod.settings, "ENV", "production")
        with (
            patch.object(
                factory_mod,
                "get_default_llm",
                side_effect=LLMNotConfiguredError("no openrouter"),
            ),
            patch.object(factory_mod.providers, "is_available", return_value=True),
        ):
            assert get_compaction_summary_llm() is None

    def test_no_fallback_when_custom_provider_unregistered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(factory_mod.settings, "ENV", "development")
        with (
            patch.object(
                factory_mod,
                "get_default_llm",
                side_effect=LLMNotConfiguredError("no openrouter"),
            ),
            patch.object(factory_mod.providers, "is_available", return_value=False),
        ):
            assert get_compaction_summary_llm() is None

    def test_result_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(factory_mod.settings, "ENV", "production")
        with patch.object(factory_mod, "get_default_llm", return_value=object()) as mock_default:
            first = get_compaction_summary_llm()
            second = get_compaction_summary_llm()
        assert first is second
        mock_default.assert_called_once()
