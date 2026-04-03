"""Unit tests for the token counter module.

Covers:
- get_token_counter: provider-specific lookups and default fallback
"""

from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from app.agents.llm.token_counter import get_token_counter


# ---------------------------------------------------------------------------
# get_token_counter
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetTokenCounter:
    @patch("app.agents.llm.token_counter.providers")
    def test_openai_provider(self, mock_providers: MagicMock) -> None:
        openai_llm = MagicMock(name="openai_llm_instance")

        def _get(key: str) -> Optional[MagicMock]:
            if key == "openai_llm":
                return openai_llm
            return None

        mock_providers.get.side_effect = _get

        result = get_token_counter(provider="openai")

        mock_providers.get.assert_called_once_with("openai_llm")
        assert result is openai_llm

    @patch("app.agents.llm.token_counter.providers")
    def test_gemini_provider(self, mock_providers: MagicMock) -> None:
        gemini_llm = MagicMock(name="gemini_llm_instance")

        def _get(key: str) -> Optional[MagicMock]:
            if key == "gemini_llm":
                return gemini_llm
            return None

        mock_providers.get.side_effect = _get

        result = get_token_counter(provider="gemini")

        mock_providers.get.assert_called_once_with("gemini_llm")
        assert result is gemini_llm

    @patch("app.agents.llm.token_counter.providers")
    def test_default_falls_back_to_openai(self, mock_providers: MagicMock) -> None:
        openai_llm = MagicMock(name="openai_llm_instance")

        def _get(key: str) -> Optional[MagicMock]:
            if key == "openai_llm":
                return openai_llm
            return None

        mock_providers.get.side_effect = _get

        result = get_token_counter(provider=None)

        mock_providers.get.assert_called_once_with("openai_llm")
        assert result is openai_llm

    @patch("app.agents.llm.token_counter.providers")
    def test_no_provider_arg_falls_back_to_openai(
        self, mock_providers: MagicMock
    ) -> None:
        openai_llm = MagicMock(name="openai_llm_instance")

        def _get(key: str) -> Optional[MagicMock]:
            if key == "openai_llm":
                return openai_llm
            return None

        mock_providers.get.side_effect = _get

        result = get_token_counter()

        mock_providers.get.assert_called_once_with("openai_llm")
        assert result is openai_llm

    @patch("app.agents.llm.token_counter.providers")
    def test_unknown_provider_falls_back_to_openai(
        self, mock_providers: MagicMock
    ) -> None:
        openai_llm = MagicMock(name="openai_llm_instance")

        def _get(key: str) -> Optional[MagicMock]:
            if key == "openai_llm":
                return openai_llm
            return None

        mock_providers.get.side_effect = _get

        result = get_token_counter(provider="cerebras")

        # Unknown provider hits neither "openai" nor "gemini" branch,
        # falls through to default return which calls providers.get("openai_llm")
        mock_providers.get.assert_called_once_with("openai_llm")
        assert result is openai_llm

    @patch("app.agents.llm.token_counter.providers")
    def test_openai_provider_not_registered_returns_none(
        self, mock_providers: MagicMock
    ) -> None:
        mock_providers.get.return_value = None

        result = get_token_counter(provider="openai")

        assert result is None

    @patch("app.agents.llm.token_counter.providers")
    def test_gemini_provider_not_registered_returns_none(
        self, mock_providers: MagicMock
    ) -> None:
        mock_providers.get.return_value = None

        result = get_token_counter(provider="gemini")

        assert result is None

    @patch("app.agents.llm.token_counter.providers")
    def test_default_not_registered_returns_none(
        self, mock_providers: MagicMock
    ) -> None:
        mock_providers.get.return_value = None

        result = get_token_counter()

        assert result is None

    @patch("app.agents.llm.token_counter.providers")
    def test_openai_and_gemini_return_different_instances(
        self, mock_providers: MagicMock
    ) -> None:
        openai_llm = MagicMock(name="openai_instance")
        gemini_llm = MagicMock(name="gemini_instance")

        def _get(key: str) -> Optional[MagicMock]:
            mapping = {
                "openai_llm": openai_llm,
                "gemini_llm": gemini_llm,
            }
            return mapping.get(key)

        mock_providers.get.side_effect = _get

        openai_result = get_token_counter(provider="openai")
        # Reset side_effect for the next call
        mock_providers.get.side_effect = _get
        gemini_result = get_token_counter(provider="gemini")

        assert openai_result is openai_llm
        assert gemini_result is gemini_llm
        assert openai_result is not gemini_result
