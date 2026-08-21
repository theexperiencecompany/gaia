"""``get_helper_llm`` — the small-output cap for one-shot helper calls.

Its own file, not a class in ``test_llm_client.py``, because ``get_helper_llm``
and ``HELPER_MAX_OUTPUT_TOKENS`` are introduced by this branch: importing them
at the top of a module that also holds a regression-marked test makes that file
uncollectable on the base revision, and the regression-proof lane then reports a
harness error instead of the proof it went looking for.

The marker is named indirectly above on purpose: regression-proof.sh selects
files with a plain text grep, so spelling the decorator out in prose enlists
this file into the lane it exists to document.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.agents.llm.client import _build_default_llm, get_helper_llm
from app.constants.llm import HELPER_MAX_OUTPUT_TOKENS, OPENROUTER_MAX_OUTPUT_TOKENS

pytestmark = pytest.mark.unit


class TestGetHelperLlm:
    @pytest.fixture(autouse=True)
    def _fresh_cache(self):
        # get_helper_llm is built on the same cached get_default_llm instance.
        _build_default_llm.cache_clear()
        yield
        _build_default_llm.cache_clear()

    @patch("app.agents.llm.client.ChatOpenRouter")
    @patch("app.agents.llm.client.settings")
    def test_helper_request_carries_the_helper_cap(
        self, mock_settings: MagicMock, mock_chat_openrouter: MagicMock
    ) -> None:
        mock_settings.GAIA_SIM_MODE = False
        mock_settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
        mock_chat_openrouter.return_value = MagicMock()

        helper_llm = get_helper_llm()

        # Exactly one ChatOpenRouter construction — the helper path reuses the
        # same cached instance/HTTP client as the graph path instead of opening
        # a second connection pool.
        mock_chat_openrouter.assert_called_once()
        assert mock_chat_openrouter.call_args.kwargs["max_tokens"] == OPENROUTER_MAX_OUTPUT_TOKENS

        # The helper's own request carries the smaller cap via model_copy, not
        # the constructed instance's max_tokens.
        mock_chat_openrouter.return_value.model_copy.assert_called_once_with(
            update={"max_tokens": HELPER_MAX_OUTPUT_TOKENS}
        )
        assert helper_llm is mock_chat_openrouter.return_value.model_copy.return_value

    @patch("app.agents.llm.client.ChatOpenRouter")
    @patch("app.agents.llm.client.settings")
    def test_a_callers_temperature_reaches_the_model(
        self, mock_settings: MagicMock, mock_chat_openrouter: MagicMock
    ) -> None:
        mock_settings.GAIA_SIM_MODE = False
        mock_settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
        mock_chat_openrouter.return_value = MagicMock()

        get_helper_llm(temperature=0.9)

        # The cap is the only thing this factory overrides; a creative caller's
        # temperature has to survive the hop through get_default_llm untouched.
        assert mock_chat_openrouter.call_args.kwargs["temperature"] == 0.9

    @patch("app.agents.llm.client.get_default_llm")
    @patch("app.agents.llm.client.settings")
    def test_sim_mode_returns_default_llm_untouched(
        self, mock_settings: MagicMock, mock_get_default: MagicMock
    ) -> None:
        mock_settings.GAIA_SIM_MODE = True
        mock_model = MagicMock()
        mock_get_default.return_value = mock_model

        result = get_helper_llm()

        assert result is mock_model
        mock_model.model_copy.assert_not_called()
