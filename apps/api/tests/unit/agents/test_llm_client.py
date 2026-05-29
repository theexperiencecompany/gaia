"""Behavior spec for the LLM client + chatbot node.

NOTE ON TARGET: the workflow nominally points at app/agents/core/state.py, but
this file (test_llm_client.py) exercises the LLM client layer. state.py only
supplies the State data carrier used as a chatbot fixture; none of its behavior
is asserted here. The real units under test are the public functions of
app/agents/llm/client.py and app/agents/llm/chatbot.py, so mutation is scoped to
those (see --target-name list in the overhaul run).

=========================================================================
UNIT: app/agents/llm/client.py :: _get_available_providers
EXPECTED: Translate the lazy-provider registry keys (openai_llm / gemini_llm /
          openrouter_llm) into a short-name -> instance dict, omitting any
          provider whose registry entry is None.
MECHANISM: for each (short_name, registry_key) it calls providers.get(key);
           keeps it only when the result is not None.
MUST-CATCH:
  - the three registry keys are exactly openai_llm/gemini_llm/openrouter_llm
  - a None registry entry is dropped (the `is not None` guard)
  - the returned key is the SHORT name (openai), not the registry key
  - returned instance is the exact object from the registry

UNIT: app/agents/llm/client.py :: _get_ordered_providers
EXPECTED: Produce the ordered fallback list of {name, instance} dicts.
          A preferred provider (if present in `available`) goes first and is not
          duplicated; the rest follow PROVIDER_PRIORITY (gemini, openai,
          openrouter). When fallback is disabled AND a preferred provider was
          placed, ONLY the preferred provider is returned. When `ordered` is
          still empty (no preferred placed), all available providers are added by
          priority even if fallback is disabled.
MECHANISM: append preferred first + pop it from a copy; then, iff
           (fallback_enabled OR not ordered), walk sorted(PROVIDER_PRIORITY) and
           append the remaining available providers in that order.
MUST-CATCH:
  - default order is gemini, openai, openrouter (priority, not insertion)
  - preferred goes first and is removed from the remainder (no duplicate)
  - fallback disabled + preferred present -> only the preferred
  - fallback disabled + no preferred -> still returns all by priority (the
    `or not ordered` escape)
  - preferred not in available -> falls through to priority list
  - empty available -> empty list
  - returned entries carry the matching instance object, not a placeholder

UNIT: app/agents/llm/client.py :: _create_configurable_llm
EXPECTED: With no alternatives, return the primary instance untouched. With
          alternatives, return primary.configurable_alternatives(...) wired with
          a "provider" ConfigurableField, default_key=primary name,
          prefix_keys=False, and each alternative keyed by its name.
MECHANISM: early return primary["instance"] when alternatives is falsy; else build
           {alt name: alt instance} and call configurable_alternatives.
MUST-CATCH:
  - empty alternatives returns the primary instance object itself
  - non-empty alternatives passes default_key == primary name
  - prefix_keys is False
  - each alternative is keyed by its own name and mapped to its instance

UNIT: app/agents/llm/client.py :: init_llm
EXPECTED: Validate preferred_provider; resolve available providers; order them;
          build a configurable LLM from the primary + (fallback ? rest : none).
          Raise ValueError on an unknown preferred provider, RuntimeError when no
          providers are configured, RuntimeError when the preferred provider is
          unavailable with fallback off.
MECHANISM: guard preferred not in PROVIDER_MODELS -> ValueError; empty available
           -> RuntimeError; _get_ordered_providers(available, preferred,
           fallback) -> if empty RuntimeError; primary = ordered[0],
           alternatives = ordered[1:] iff fallback else []; return
           _create_configurable_llm(primary, alternatives).
MUST-CATCH:
  - invalid preferred provider -> ValueError naming it
  - empty available registry -> RuntimeError "No LLM providers"
  - empty ordered list -> RuntimeError naming provider + "disabled"/"failed"
  - _get_ordered_providers called with (available, preferred, fallback) exactly
  - primary is ordered[0]; alternatives are ordered[1:] when fallback enabled
  - fallback disabled -> alternatives passed as []
  - the return value is _create_configurable_llm's result

UNIT: app/agents/llm/client.py :: get_free_llm_chain
EXPECTED: Build the free-LLM fallback chain. OpenRouter ChatOpenAI is appended
          first iff OPENROUTER_API_KEY set; direct Gemini appended second iff
          GOOGLE_API_KEY set. With neither key, RuntimeError.
MECHANISM: conditional append per key, in OpenRouter-then-Gemini order; raise if
           the list is empty.
MUST-CATCH:
  - both keys -> 2 entries, OpenRouter constructed then Gemini constructed
  - only OpenRouter -> 1 entry, Gemini NOT constructed
  - only Google -> 1 entry, OpenRouter NOT constructed
  - neither -> RuntimeError "No free LLM providers configured"
  - OpenRouter precedes Gemini in the chain (order is the fallback contract)

UNIT: app/agents/llm/client.py :: invoke_with_fallback
EXPECTED: Try each LLM's ainvoke in order; return the first success; on every
          failure fall through to the next; if all fail raise RuntimeError naming
          the last error. Pass `config` through to ainvoke.
MECHANISM: for i, llm: try return await llm.ainvoke(messages, config=config);
           except: record last_error, log warn (not last) / error (last); after
           loop raise RuntimeError.
MUST-CATCH:
  - first success short-circuits (later LLMs not invoked)
  - first failure -> second invoked and its result returned
  - all fail -> RuntimeError carrying the LAST error text
  - config is forwarded to ainvoke
  - messages are forwarded to ainvoke unchanged
  - the LAST failure is logged as error, an earlier one as warning

UNIT: app/agents/llm/client.py :: register_llm_providers
EXPECTED: Register all three lazy providers exactly once.
MECHANISM: call init_openai_llm(); init_gemini_llm(); init_openrouter_llm().
MUST-CATCH: each of the three registration functions is invoked.

UNIT: app/agents/llm/client.py :: module constants
EXPECTED: PROVIDER_MODELS keys and PROVIDER_PRIORITY values are exactly the three
          providers; priority order is gemini<openai<openrouter; the retryable
          exception tuple holds the transient provider/transport errors and
          excludes programming errors.
MUST-CATCH: priority ordering by key; retryable membership for ResourceExhausted;
            non-membership for ValueError/KeyError.

UNIT: app/agents/llm/chatbot.py :: chatbot
EXPECTED: Free path -> build the free chain and invoke_with_fallback over
          state.messages, returning {"messages": [response]}. Paid path ->
          init_llm() then ainvoke(state.messages), same return shape. Any
          exception -> return a single AIMessage apology, never raise.
MECHANISM: try: branch on use_free_llm; except Exception: log.error + return the
           fallback AIMessage.
MUST-CATCH:
  - free path uses get_free_llm_chain + invoke_with_fallback(chain, messages)
  - paid path uses init_llm() (NO args) + llm.ainvoke(messages)
  - return shape is {"messages": [<response>]} carrying the real response
  - error in the free chain -> apology AIMessage, no raise
  - error in init_llm (paid) -> apology AIMessage, no raise
  - error inside invoke_with_fallback -> apology AIMessage, no raise
  - the apology message is an AIMessage whose content explains the trouble

EQUIVALENT MUTANTS (allowed survivors, all proven behavior-preserving):
  client.py (14 survivors, 57/71 killed):
  - docstring `str -> ''` at L147/203/230/268/296/303/356: docstrings carry no
    runtime behavior.
  - log.set(llm={...}) dict-key / dict-value mutations at L194/195/196
    ("model"/"provider"/"is_free" keys, the False value): `log` is patched at the
    boundary in every init_llm test, so the payload is never inspected and control
    flow is unchanged. These are wide-event observability fields.
  - log warning/error MESSAGE-TEXT `str -> ''` at L382/L384 in invoke_with_fallback:
    the branch that fires (warning vs error) IS asserted via mock_log.warning /
    mock_log.error call counts; only the human-readable message text survives,
    which is a log-only value with no effect on the return/raised value.
  chatbot.py (2 survivors, 6/8 killed):
  - docstring `str -> ''` at L12: no runtime behavior.
  - log.error MESSAGE-TEXT `str -> ''` at L31: the error-log CALL is asserted
    (mock_log.error.assert_called_once); the message text is a log-only value and
    does not change the returned apology AIMessage.
  COMBINED: 79 sites, 63 killed, 16 proven-equivalent survivors. Every
  non-equivalent mutant is killed; the survivors cannot change behavior.
=========================================================================
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
import pytest

from app.agents.core.state import State
from app.agents.llm.chatbot import chatbot
from app.agents.llm.client import (
    _LLM_RETRYABLE_EXCEPTIONS,
    PROVIDER_MODELS,
    PROVIDER_PRIORITY,
    _create_configurable_llm,
    _get_available_providers,
    _get_ordered_providers,
    get_free_llm_chain,
    init_llm,
    invoke_with_fallback,
    register_llm_providers,
)
from app.constants.llm import GEMINI_FREE_FALLBACK_MODELS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_provider(name: str = "fake") -> MagicMock:
    """A MagicMock that quacks like a BaseChatModel for client.py's purposes."""
    mock = MagicMock(name=f"llm-{name}")
    # configurable_alternatives returns a distinct sentinel so we can assert the
    # wired result is what init_llm/_create_configurable_llm hands back.
    mock.configurable_alternatives.return_value = MagicMock(name=f"configured-{name}")
    mock.ainvoke = AsyncMock(return_value=AIMessage(content=f"response-from-{name}"))
    return mock


def _make_llm_provider(name: str) -> dict[str, Any]:
    return {"name": name, "instance": _make_fake_provider(name)}


# ---------------------------------------------------------------------------
# _get_available_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAvailableProviders:
    @patch("app.agents.llm.client.providers")
    def test_maps_registry_keys_to_short_names(self, mock_providers: MagicMock) -> None:
        openai_inst = _make_fake_provider("openai")
        gemini_inst = _make_fake_provider("gemini")
        openrouter_inst = _make_fake_provider("openrouter")
        registry = {
            "openai_llm": openai_inst,
            "gemini_llm": gemini_inst,
            "openrouter_llm": openrouter_inst,
        }
        mock_providers.get.side_effect = lambda key: registry.get(key)

        result = _get_available_providers()

        # Short names (not the *_llm registry keys) map to the exact instances.
        assert result == {
            "openai": openai_inst,
            "gemini": gemini_inst,
            "openrouter": openrouter_inst,
        }
        # The registry was queried by the *_llm keys, proving the mapping table.
        assert {c.args[0] for c in mock_providers.get.call_args_list} == {
            "openai_llm",
            "gemini_llm",
            "openrouter_llm",
        }

    @patch("app.agents.llm.client.providers")
    def test_none_entries_dropped(self, mock_providers: MagicMock) -> None:
        gemini_inst = _make_fake_provider("gemini")
        mock_providers.get.side_effect = lambda key: gemini_inst if key == "gemini_llm" else None

        result = _get_available_providers()

        # Only the non-None provider survives the `is not None` guard.
        assert result == {"gemini": gemini_inst}

    @patch("app.agents.llm.client.providers")
    def test_no_providers_available_returns_empty(self, mock_providers: MagicMock) -> None:
        mock_providers.get.return_value = None

        assert _get_available_providers() == {}


# ---------------------------------------------------------------------------
# _get_ordered_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetOrderedProviders:
    def test_default_priority_order(self) -> None:
        g, o, r = (
            _make_fake_provider("gemini"),
            _make_fake_provider("openai"),
            _make_fake_provider("openrouter"),
        )
        available: dict[str, Any] = {"openai": o, "gemini": g, "openrouter": r}

        ordered = _get_ordered_providers(available, preferred_provider=None, fallback_enabled=True)

        # Priority order gemini<openai<openrouter, NOT the dict insertion order.
        assert [p["name"] for p in ordered] == ["gemini", "openai", "openrouter"]
        # Each entry carries the matching instance.
        assert ordered[0]["instance"] is g
        assert ordered[1]["instance"] is o
        assert ordered[2]["instance"] is r

    def test_preferred_provider_is_first_then_priority(self) -> None:
        available: dict[str, Any] = {
            "openai": _make_fake_provider("openai"),
            "gemini": _make_fake_provider("gemini"),
            "openrouter": _make_fake_provider("openrouter"),
        }

        ordered = _get_ordered_providers(
            available, preferred_provider="openai", fallback_enabled=True
        )

        names = [p["name"] for p in ordered]
        assert names[0] == "openai"
        # Remainder follows priority; openai is NOT duplicated.
        assert names == ["openai", "gemini", "openrouter"]

    def test_preferred_not_available_falls_through_to_priority(self) -> None:
        available: dict[str, Any] = {"gemini": _make_fake_provider("gemini")}

        ordered = _get_ordered_providers(
            available, preferred_provider="openai", fallback_enabled=True
        )

        # openai absent -> nothing placed as preferred; gemini comes from priority.
        assert [p["name"] for p in ordered] == ["gemini"]

    def test_fallback_disabled_no_preferred_still_returns_all(self) -> None:
        available: dict[str, Any] = {
            "openai": _make_fake_provider("openai"),
            "gemini": _make_fake_provider("gemini"),
        }

        ordered = _get_ordered_providers(available, preferred_provider=None, fallback_enabled=False)

        # No preferred -> `ordered` empty -> `not ordered` escape adds all by priority.
        assert [p["name"] for p in ordered] == ["gemini", "openai"]

    def test_fallback_disabled_with_preferred_returns_only_preferred(self) -> None:
        available: dict[str, Any] = {
            "openai": _make_fake_provider("openai"),
            "gemini": _make_fake_provider("gemini"),
        }

        ordered = _get_ordered_providers(
            available, preferred_provider="openai", fallback_enabled=False
        )

        # Preferred placed -> `ordered` non-empty -> priority loop skipped.
        assert [p["name"] for p in ordered] == ["openai"]

    def test_empty_available_returns_empty(self) -> None:
        assert _get_ordered_providers({}, preferred_provider=None, fallback_enabled=True) == []


# ---------------------------------------------------------------------------
# _create_configurable_llm
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateConfigurableLlm:
    def test_no_alternatives_returns_primary_instance(self) -> None:
        primary = _make_llm_provider("gemini")

        result = _create_configurable_llm(primary, [])  # type: ignore[arg-type]

        assert result is primary["instance"]
        # No wiring happens on the empty-alternatives path.
        primary["instance"].configurable_alternatives.assert_not_called()

    def test_with_alternatives_wires_configurable_alternatives(self) -> None:
        primary = _make_llm_provider("gemini")
        alt1 = _make_llm_provider("openai")
        alt2 = _make_llm_provider("openrouter")

        result = _create_configurable_llm(primary, [alt1, alt2])  # type: ignore[arg-type]

        # Returns the configured runnable, not the bare primary.
        assert result is primary["instance"].configurable_alternatives.return_value
        primary["instance"].configurable_alternatives.assert_called_once()
        call = primary["instance"].configurable_alternatives.call_args
        # The selector field is keyed on "provider" (LangGraph reads this id at
        # runtime to switch providers) — passed positionally as a ConfigurableField.
        assert call.args[0].id == "provider"
        kwargs = call.kwargs
        assert kwargs["default_key"] == "gemini"
        assert kwargs["prefix_keys"] is False
        # Each alternative is keyed by its own name -> its own instance.
        assert kwargs["openai"] is alt1["instance"]
        assert kwargs["openrouter"] is alt2["instance"]


# ---------------------------------------------------------------------------
# init_llm
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInitLlm:
    def test_invalid_provider_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid preferred_provider 'cerebras'"):
            init_llm(preferred_provider="cerebras")

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._get_available_providers")
    def test_no_providers_raises_runtime_error(
        self, mock_available: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_available.return_value = {}

        with pytest.raises(RuntimeError, match="No LLM providers are properly configured"):
            init_llm()

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_preferred_unavailable_no_fallback_full_message(
        self, mock_available: MagicMock, mock_ordered: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_available.return_value = {"gemini": _make_fake_provider("gemini")}
        mock_ordered.return_value = []

        with pytest.raises(RuntimeError) as exc:
            init_llm(preferred_provider="openai", fallback_enabled=False)

        # The whole message text is the contract: it names the provider, states it
        # is not available, and that fallback was 'disabled' (the `not
        # fallback_enabled` branch). Asserting the full string kills mutations of
        # every message segment and the `not` operator.
        assert (
            str(exc.value)
            == "Preferred provider 'openai' is not available and fallback is disabled."
        )

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_ordered_empty_with_fallback_says_failed(
        self, mock_available: MagicMock, mock_ordered: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_available.return_value = {"gemini": _make_fake_provider("gemini")}
        mock_ordered.return_value = []

        with pytest.raises(RuntimeError) as exc:
            init_llm(preferred_provider="openai", fallback_enabled=True)

        # fallback enabled but ordering produced nothing -> message says 'failed',
        # exercising the else side of `'disabled' if not fallback_enabled else 'failed'`.
        assert (
            str(exc.value) == "Preferred provider 'openai' is not available and fallback is failed."
        )

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_default_selection_uses_primary_and_rest_as_alternatives(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_create: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        primary = _make_llm_provider("gemini")
        alt = _make_llm_provider("openai")
        available = {"gemini": primary["instance"], "openai": alt["instance"]}
        mock_available.return_value = available
        mock_ordered.return_value = [primary, alt]
        configured = MagicMock(name="configured")
        mock_create.return_value = configured

        result = init_llm()

        # Default args: no preferred, fallback enabled.
        mock_ordered.assert_called_once_with(available, None, True)
        # Primary is ordered[0]; alternatives are ordered[1:].
        mock_create.assert_called_once_with(primary, [alt])
        # init_llm returns exactly what _create_configurable_llm produced.
        assert result is configured

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_fallback_disabled_passes_empty_alternatives(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_create: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        primary = _make_llm_provider("openai")
        extra = _make_llm_provider("gemini")
        mock_available.return_value = {"openai": primary["instance"]}
        # Even if ordered had a tail, fallback off forces alternatives == [].
        mock_ordered.return_value = [primary, extra]
        mock_create.return_value = MagicMock()

        init_llm(preferred_provider="openai", fallback_enabled=False)

        mock_ordered.assert_called_once_with(mock_available.return_value, "openai", False)
        mock_create.assert_called_once_with(primary, [])

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_preferred_provider_forwarded_to_ordering(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_create: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        primary = _make_llm_provider("openrouter")
        mock_available.return_value = {"openrouter": primary["instance"]}
        mock_ordered.return_value = [primary]
        mock_create.return_value = MagicMock()

        init_llm(preferred_provider="openrouter")

        # preferred_provider and the default fallback=True are forwarded verbatim.
        mock_ordered.assert_called_once_with(mock_available.return_value, "openrouter", True)


# ---------------------------------------------------------------------------
# get_free_llm_chain
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetFreeLlmChain:
    @patch("app.agents.llm.client.ChatGoogleGenerativeAI")
    @patch("app.agents.llm.client.ChatOpenAI")
    @patch("app.agents.llm.client.settings")
    def test_both_providers_openrouter_first(
        self,
        mock_settings: MagicMock,
        mock_chat_openai: MagicMock,
        mock_chat_google: MagicMock,
    ) -> None:
        mock_settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
        mock_settings.GOOGLE_API_KEY = "google-key"  # pragma: allowlist secret
        mock_settings.FRONTEND_URL = "http://localhost:3000"
        openrouter_llm = MagicMock(name="openrouter")
        google_llm = MagicMock(name="google")
        mock_chat_openai.return_value = openrouter_llm
        mock_chat_google.return_value = google_llm

        chain = get_free_llm_chain()

        # OpenRouter is primary (index 0), Gemini is the fallback (index 1).
        assert chain == [openrouter_llm, google_llm]
        mock_chat_openai.assert_called_once()
        mock_chat_google.assert_called_once()
        # The OpenRouter free client is configured with the contract the backend
        # relies on: non-streaming, the GAIA attribution headers, and the
        # automatic free-model fallback list in extra_body.
        or_kwargs = mock_chat_openai.call_args.kwargs
        assert or_kwargs["streaming"] is False
        assert or_kwargs["default_headers"]["HTTP-Referer"] == "http://localhost:3000"
        assert or_kwargs["default_headers"]["X-Title"] == "GAIA"
        assert "models" in or_kwargs["extra_body"]
        assert or_kwargs["extra_body"]["models"] == GEMINI_FREE_FALLBACK_MODELS

    @patch("app.agents.llm.client.ChatGoogleGenerativeAI")
    @patch("app.agents.llm.client.ChatOpenAI")
    @patch("app.agents.llm.client.settings")
    def test_only_openrouter_skips_gemini(
        self,
        mock_settings: MagicMock,
        mock_chat_openai: MagicMock,
        mock_chat_google: MagicMock,
    ) -> None:
        mock_settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
        mock_settings.GOOGLE_API_KEY = None
        mock_settings.FRONTEND_URL = "http://localhost:3000"
        openrouter_llm = MagicMock(name="openrouter")
        mock_chat_openai.return_value = openrouter_llm

        chain = get_free_llm_chain()

        assert chain == [openrouter_llm]
        mock_chat_google.assert_not_called()

    @patch("app.agents.llm.client.ChatGoogleGenerativeAI")
    @patch("app.agents.llm.client.ChatOpenAI")
    @patch("app.agents.llm.client.settings")
    def test_only_google_skips_openrouter(
        self,
        mock_settings: MagicMock,
        mock_chat_openai: MagicMock,
        mock_chat_google: MagicMock,
    ) -> None:
        mock_settings.OPENROUTER_API_KEY = None
        mock_settings.GOOGLE_API_KEY = "google-key"  # pragma: allowlist secret
        google_llm = MagicMock(name="google")
        mock_chat_google.return_value = google_llm

        chain = get_free_llm_chain()

        assert chain == [google_llm]
        mock_chat_openai.assert_not_called()

    @patch("app.agents.llm.client.settings")
    def test_no_providers_raises(self, mock_settings: MagicMock) -> None:
        mock_settings.OPENROUTER_API_KEY = None
        mock_settings.GOOGLE_API_KEY = None

        with pytest.raises(RuntimeError, match="No free LLM providers configured"):
            get_free_llm_chain()


# ---------------------------------------------------------------------------
# invoke_with_fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInvokeWithFallback:
    async def test_first_llm_succeeds_short_circuits(self) -> None:
        llm1 = MagicMock()
        llm1.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
        llm2 = MagicMock()
        llm2.ainvoke = AsyncMock(return_value=AIMessage(content="fallback"))

        result = await invoke_with_fallback([llm1, llm2], [HumanMessage(content="hi")])

        assert result.content == "ok"
        # Success on the first LLM must not reach the second.
        llm2.ainvoke.assert_not_called()

    @patch("app.agents.llm.client.log")
    async def test_first_fails_second_succeeds(self, mock_log: MagicMock) -> None:
        llm1 = MagicMock()
        llm1.ainvoke = AsyncMock(side_effect=Exception("rate limit"))
        llm2 = MagicMock()
        llm2.ainvoke = AsyncMock(return_value=AIMessage(content="fallback-ok"))

        result = await invoke_with_fallback([llm1, llm2], [HumanMessage(content="hi")])

        assert result.content == "fallback-ok"
        # The non-final failure is a warning, not an error.
        mock_log.warning.assert_called_once()
        mock_log.error.assert_not_called()

    @patch("app.agents.llm.client.log")
    async def test_all_fail_raises_with_last_error(self, mock_log: MagicMock) -> None:
        llm1 = MagicMock()
        llm1.ainvoke = AsyncMock(side_effect=Exception("error1"))
        llm2 = MagicMock()
        llm2.ainvoke = AsyncMock(side_effect=Exception("error-last"))

        with pytest.raises(RuntimeError, match="All LLM providers failed") as exc:
            await invoke_with_fallback([llm1, llm2], [HumanMessage(content="hi")])

        # The RuntimeError surfaces the LAST error, not the first.
        assert "error-last" in str(exc.value)
        # The final failure is logged as error (the earlier one as warning).
        mock_log.error.assert_called_once()
        mock_log.warning.assert_called_once()

    @patch("app.agents.llm.client.log")
    async def test_single_llm_failure_raises(self, mock_log: MagicMock) -> None:
        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=ValueError("bad"))

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await invoke_with_fallback([llm], [HumanMessage(content="hi")])

        # A single LLM IS the last element -> logged as error, never warning.
        mock_log.error.assert_called_once()
        mock_log.warning.assert_not_called()

    async def test_forwards_messages_and_config(self) -> None:
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
        messages = [HumanMessage(content="hi")]
        config = {"configurable": {"thread_id": "t1"}}

        await invoke_with_fallback([llm], messages, config=config)  # type: ignore[arg-type]

        llm.ainvoke.assert_called_once()
        args, kwargs = llm.ainvoke.call_args
        # messages forwarded positionally, config forwarded as keyword.
        assert args[0] is messages
        assert kwargs["config"] == config

    @patch("app.agents.llm.client.log")
    async def test_walks_full_chain_until_success(self, mock_log: MagicMock) -> None:
        llm1 = MagicMock()
        llm1.ainvoke = AsyncMock(side_effect=Exception("fail1"))
        llm2 = MagicMock()
        llm2.ainvoke = AsyncMock(side_effect=Exception("fail2"))
        llm3 = MagicMock()
        llm3.ainvoke = AsyncMock(return_value=AIMessage(content="third-ok"))

        result = await invoke_with_fallback([llm1, llm2, llm3], [HumanMessage(content="hi")])

        assert result.content == "third-ok"
        # Two failures before success -> two warnings, no error (none was last).
        assert mock_log.warning.call_count == 2
        mock_log.error.assert_not_called()


# ---------------------------------------------------------------------------
# register_llm_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterLlmProviders:
    @patch("app.agents.llm.client.init_openrouter_llm")
    @patch("app.agents.llm.client.init_gemini_llm")
    @patch("app.agents.llm.client.init_openai_llm")
    def test_registers_all_three(
        self,
        mock_openai: MagicMock,
        mock_gemini: MagicMock,
        mock_openrouter: MagicMock,
    ) -> None:
        register_llm_providers()

        mock_openai.assert_called_once()
        mock_gemini.assert_called_once()
        mock_openrouter.assert_called_once()


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstants:
    def test_provider_models_keys(self) -> None:
        assert set(PROVIDER_MODELS.keys()) == {"gemini", "openai", "openrouter"}

    def test_provider_priority_is_ordered(self) -> None:
        sorted_keys = sorted(PROVIDER_PRIORITY.keys())
        providers_in_order = [PROVIDER_PRIORITY[k] for k in sorted_keys]
        assert providers_in_order == ["gemini", "openai", "openrouter"]

    def test_retryable_exceptions_membership(self) -> None:
        from google.api_core.exceptions import (
            DeadlineExceeded,
            InternalServerError,
            ResourceExhausted,
            ServiceUnavailable,
        )

        assert set(_LLM_RETRYABLE_EXCEPTIONS) == {
            ResourceExhausted,
            ServiceUnavailable,
            DeadlineExceeded,
            InternalServerError,
            ConnectionError,
            TimeoutError,
        }
        # Transient provider error is retryable; programming errors are not.
        assert isinstance(ResourceExhausted("rate limited"), _LLM_RETRYABLE_EXCEPTIONS)
        assert not isinstance(ValueError("bad"), _LLM_RETRYABLE_EXCEPTIONS)
        assert not isinstance(KeyError("missing"), _LLM_RETRYABLE_EXCEPTIONS)


# ---------------------------------------------------------------------------
# chatbot (from chatbot.py)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestChatbot:
    @patch("app.agents.llm.chatbot.invoke_with_fallback")
    @patch("app.agents.llm.chatbot.get_free_llm_chain")
    async def test_free_path_invokes_chain_with_messages(
        self,
        mock_get_chain: MagicMock,
        mock_invoke: AsyncMock,
    ) -> None:
        mock_chain = [MagicMock()]
        mock_get_chain.return_value = mock_chain
        mock_invoke.return_value = AIMessage(content="free response")
        state = State(messages=[HumanMessage(content="hello")])

        result = await chatbot(state, use_free_llm=True)

        mock_get_chain.assert_called_once()
        # The free chain is invoked over the state's messages.
        mock_invoke.assert_called_once_with(mock_chain, state.messages)
        assert result == {"messages": [mock_invoke.return_value]}
        assert result["messages"][0].content == "free response"

    @patch("app.agents.llm.chatbot.init_llm")
    async def test_paid_path_invokes_init_llm_with_no_args(self, mock_init_llm: MagicMock) -> None:
        mock_llm = MagicMock()
        response = AIMessage(content="paid response")
        mock_llm.ainvoke = AsyncMock(return_value=response)
        mock_init_llm.return_value = mock_llm
        state = State(messages=[HumanMessage(content="hello")])

        result = await chatbot(state, use_free_llm=False)

        # Paid path: init_llm() is called with NO arguments (the current contract).
        mock_init_llm.assert_called_once_with()
        mock_llm.ainvoke.assert_called_once_with(state.messages)
        assert result == {"messages": [response]}

    @patch("app.agents.llm.chatbot.invoke_with_fallback")
    @patch("app.agents.llm.chatbot.get_free_llm_chain")
    async def test_default_use_free_true_takes_free_path(
        self, mock_get_chain: MagicMock, mock_invoke: AsyncMock
    ) -> None:
        mock_get_chain.return_value = [MagicMock()]
        mock_invoke.return_value = AIMessage(content="defaulted-free")
        state = State(messages=[HumanMessage(content="hi")])

        # No use_free_llm passed -> default True -> free path (not init_llm).
        result = await chatbot(state)

        mock_get_chain.assert_called_once()
        assert result["messages"][0].content == "defaulted-free"

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.get_free_llm_chain")
    async def test_free_chain_error_returns_apology(
        self, mock_get_chain: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_get_chain.side_effect = RuntimeError("no providers")
        state = State(messages=[HumanMessage(content="hello")])

        result = await chatbot(state, use_free_llm=True)

        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert "trouble processing" in msg.content
        mock_log.error.assert_called_once()

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.init_llm")
    async def test_paid_init_error_returns_apology(
        self, mock_init_llm: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_init_llm.side_effect = RuntimeError("no providers")
        state = State(messages=[HumanMessage(content="hello")])

        result = await chatbot(state, use_free_llm=False)

        assert isinstance(result["messages"][0], AIMessage)
        assert "trouble processing" in result["messages"][0].content

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.invoke_with_fallback")
    @patch("app.agents.llm.chatbot.get_free_llm_chain")
    async def test_invoke_fallback_error_returns_apology(
        self,
        mock_get_chain: MagicMock,
        mock_invoke: AsyncMock,
        mock_log: MagicMock,
    ) -> None:
        mock_get_chain.return_value = [MagicMock()]
        mock_invoke.side_effect = RuntimeError("all failed")
        state = State(messages=[HumanMessage(content="hello")])

        result = await chatbot(state, use_free_llm=True)

        assert "trouble processing" in result["messages"][0].content
