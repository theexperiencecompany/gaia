"""Behaviour spec for the token-counter provider selector.

UNIT: app/agents/llm/token_counter.py :: get_token_counter
EXPECTED: Map a provider name to the lazy-loaded LLM client used for token
          counting. "gemini" resolves the Gemini client; every other value
          (including "openai", None, and unknown providers) resolves the
          OpenAI client, which is the default. The resolved client (or None
          when the provider is not registered) is returned unchanged.
MECHANISM:
    if provider == "openai":  return providers.get("openai_llm")
    if provider == "gemini":  return providers.get("gemini_llm")
    return providers.get("openai_llm")
    `providers` is the lazy-loader registry singleton (I/O boundary —
    patched here so no real client is constructed).
MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - "gemini" resolves the Gemini client via the EXACT key "gemini_llm",
    not the OpenAI client and not an empty key. Kills the gemini-branch
    compare flip (== -> !=), the "gemini" literal blanking, the
    "gemini_llm" key blanking, and return-None on the gemini branch.
  - "openai" resolves the OpenAI client via the EXACT key "openai_llm".
    Kills the "openai_llm" key blanking and return-None on the openai branch.
  - An unrecognised / None provider falls back to the OpenAI client via the
    EXACT key "openai_llm". Kills the default-branch key blanking and
    return-None on the default branch.
  - The function returns the registry's value verbatim; when the registry
    has no client for the key it returns None (frontend/caller contract:
    no substitution, no raising).
EQUIVALENT MUTANTS (allowed survivors, justified, proven empirically):
  - L5 const_str (docstring -> ""): the docstring is not behaviour; blanking
    it changes no return value or call.
  - L6 const_str (`provider == "openai"` -> `provider == ""`): the "openai"
    branch and the default branch are byte-identical
    (`return providers.get("openai_llm")`), so re-routing "openai" through the
    default — or routing "" through the openai branch — yields an identical
    return value AND an identical `providers.get("openai_llm")` call for every
    possible input. Verified across {"openai","gemini","","cerebras",None}:
    identical return and identical call list. The "openai" branch is in fact
    redundant production code (prod_smell). No test can distinguish this
    mutant; it is excluded from the denominator.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.agents.llm.token_counter import get_token_counter

# Distinct sentinel instances so a wrong-branch / wrong-key resolution is
# observable as a different object (never just "truthy").
_OPENAI_LLM = MagicMock(name="openai_llm_client")
_GEMINI_LLM = MagicMock(name="gemini_llm_client")

# Registry behaviour at the I/O boundary: only the two real keys resolve to a
# client; any other key (e.g. the "" produced by a literal-blanking mutant)
# resolves to None, exactly like an unregistered provider.
_REGISTRY = {"openai_llm": _OPENAI_LLM, "gemini_llm": _GEMINI_LLM}


def _registry_get(key: str) -> MagicMock | None:
    return _REGISTRY.get(key)


@pytest.mark.unit
class TestGetTokenCounter:
    @patch("app.agents.llm.token_counter.providers")
    def test_gemini_resolves_gemini_client(self, mock_providers: MagicMock) -> None:
        """gemini -> Gemini client via key "gemini_llm", distinct from default."""
        mock_providers.get.side_effect = _registry_get

        result = get_token_counter(provider="gemini")

        assert result is _GEMINI_LLM
        assert result is not _OPENAI_LLM
        mock_providers.get.assert_called_once_with("gemini_llm")

    @patch("app.agents.llm.token_counter.providers")
    def test_openai_resolves_openai_client(self, mock_providers: MagicMock) -> None:
        """openai -> OpenAI client via key "openai_llm"."""
        mock_providers.get.side_effect = _registry_get

        result = get_token_counter(provider="openai")

        assert result is _OPENAI_LLM
        mock_providers.get.assert_called_once_with("openai_llm")

    @pytest.mark.parametrize("provider", [None, "cerebras"])
    @patch("app.agents.llm.token_counter.providers")
    def test_default_branch_falls_back_to_openai_client(
        self, mock_providers: MagicMock, provider: str | None
    ) -> None:
        """No provider and any unrecognised name fall through to the OpenAI default."""
        mock_providers.get.side_effect = _registry_get

        result = get_token_counter(provider=provider)

        assert result is _OPENAI_LLM
        mock_providers.get.assert_called_once_with("openai_llm")

    @patch("app.agents.llm.token_counter.providers")
    def test_unregistered_client_returns_none_verbatim(self, mock_providers: MagicMock) -> None:
        """When the registry has no client, the registry's None is returned as-is."""
        mock_providers.get.return_value = None

        result = get_token_counter(provider="gemini")

        assert result is None
