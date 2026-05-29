"""Behavior spec for `app.agents.core.subagents.builtin_subagents`.

UNIT: app/agents/core/subagents/builtin_subagents.py :: BUILTIN_SUBAGENTS
EXPECTED: A frozen tuple holding the single built-in (non-OAuth) subagent — the
          GAIA Knowledge Guide. Every field is a load-bearing contract consumed
          by `registry.get_all_subagents()` (which concatenates builtins with
          OAuth-derived subagents) and by `provider_subagents` / `base_subagent`
          (which turn the config into a handoff tool + tool bindings).
MECHANISM: `BUILTIN_SUBAGENTS = (Subagent(id=..., provider=..., managed_by=...,
           config=SubAgentConfig(...)),)`. No functions, no branches — the
           "behavior" is the exact data each downstream consumer reads.
MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - the tuple is non-empty (registry concatenation would silently drop the
    builtin if it were emptied)                                  [registry contract]
  - id / provider / managed_by are the exact discovery keys the registry
    de-duplicates on; a wrong value shadows or orphans the entry  [lookup contract]
  - id and provider do NOT collide with any OAUTH_INTEGRATIONS entry, or the
    registry merge silently shadows one with the other          [merge invariant]
  - config.agent_name is the exact lazy-provider key the runner resolves
  - config.tool_space is the exact ChromaDB tool namespace
  - config.handoff_tool_name is the exact tool name the executor agent calls
  - config.domain / capabilities / use_cases are the exact routing copy that
    drives delegation decisions (emptying any of them breaks routing)
  - config.has_subagent is True (registry assumes builtins are real subagents)
  - config.use_direct_tools is True (GAIA binds tools directly, skips retrieval)
  - config.disable_retrieve_tools is True
  - config.auto_bind_tools is exactly ["fetch_webpages"] (the grounding tool)
  - config.include_finish_task is False (GAIA is answer-only; finish_task omitted)
  - config.system_prompt IS the imported GAIA_AGENT_SYSTEM_PROMPT (same object,
    not a copy) and carries the llms.txt discovery surfaces
EQUIVALENT MUTANTS (allowed survivors, justified):
  - L1 module docstring `str -> ''`: a module docstring has no runtime behavior;
    `builtin_subagents.__doc__` is never read anywhere in app/ or tests/ (verified
    by grep). Emptying it changes no observable behavior of the unit, so it is a
    true equivalent mutant excluded from the effective kill denominator. The
    effective kill rate over behavior-bearing mutants is 15/15 = 100%.
"""

import pytest

from app.agents.core.subagents.builtin_subagents import BUILTIN_SUBAGENTS
from app.agents.prompts.subagent_prompts import GAIA_AGENT_SYSTEM_PROMPT
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.models.subagent_models import Subagent

GAIA_ID = "gaia_knowledge_guide"


@pytest.fixture
def gaia() -> Subagent:
    """The single GAIA Knowledge Guide builtin, looked up by id."""
    match = next((s for s in BUILTIN_SUBAGENTS if s.id == GAIA_ID), None)
    assert match is not None, "GAIA Knowledge Guide builtin missing from BUILTIN_SUBAGENTS"
    return match


@pytest.mark.unit
class TestRegistryInvariants:
    """Invariants the registry merge (`get_all_subagents`) depends on."""

    def test_tuple_is_non_empty_and_holds_subagents(self) -> None:
        # Emptying the tuple would make the registry concatenation drop the
        # builtin without any error — the GAIA guide would simply vanish.
        assert isinstance(BUILTIN_SUBAGENTS, tuple)
        assert len(BUILTIN_SUBAGENTS) == 1
        assert all(isinstance(entry, Subagent) for entry in BUILTIN_SUBAGENTS)

    def test_all_builtins_managed_internally(self) -> None:
        # Builtins are not OAuth-derived; `managed_by` must stay "internal" so
        # downstream code never treats them as composio/mcp/self integrations.
        assert all(entry.managed_by == "internal" for entry in BUILTIN_SUBAGENTS)

    def test_all_builtins_are_real_subagents(self) -> None:
        # The registry assumes every builtin is an actual delegatable subagent.
        assert all(entry.config.has_subagent is True for entry in BUILTIN_SUBAGENTS)

    def test_ids_and_providers_unique_within_builtins(self) -> None:
        ids = [entry.id for entry in BUILTIN_SUBAGENTS]
        providers = [entry.provider for entry in BUILTIN_SUBAGENTS]
        assert len(ids) == len(set(ids)), f"Duplicate ids: {ids}"
        assert len(providers) == len(set(providers)), f"Duplicate providers: {providers}"

    def test_ids_do_not_collide_with_oauth(self) -> None:
        # An id collision lets a builtin silently shadow an OAuth subagent (or
        # vice versa) in `get_subagent_by_id`.
        builtin_ids = {entry.id for entry in BUILTIN_SUBAGENTS}
        oauth_ids = {integ.id for integ in OAUTH_INTEGRATIONS}
        assert not (builtin_ids & oauth_ids), sorted(builtin_ids & oauth_ids)

    def test_providers_do_not_collide_with_oauth(self) -> None:
        # Same shadowing hazard, keyed on provider (the registry de-dupes on it).
        builtin_providers = {entry.provider for entry in BUILTIN_SUBAGENTS}
        oauth_providers = {integ.provider for integ in OAUTH_INTEGRATIONS}
        assert not (builtin_providers & oauth_providers), sorted(
            builtin_providers & oauth_providers
        )


@pytest.mark.unit
class TestGaiaIdentity:
    """The discovery keys the registry indexes the GAIA guide under."""

    def test_id_provider_name_managed_by(self, gaia: Subagent) -> None:
        assert gaia.id == GAIA_ID
        assert gaia.provider == GAIA_ID
        assert gaia.name == "GAIA Knowledge Guide"
        assert gaia.managed_by == "internal"


@pytest.mark.unit
class TestGaiaConfigContract:
    """The SubAgentConfig fields each downstream consumer reads verbatim."""

    def test_agent_name_is_lazy_provider_key(self, gaia: Subagent) -> None:
        # Resolved via providers.aget(agent_name) by the subagent runner.
        assert gaia.config.agent_name == "gaia_knowledge_guide_agent"

    def test_tool_space_is_chromadb_namespace(self, gaia: Subagent) -> None:
        assert gaia.config.tool_space == GAIA_ID

    def test_handoff_tool_name_is_executor_tool(self, gaia: Subagent) -> None:
        # This is the exact tool name the executor agent invokes to delegate.
        assert gaia.config.handoff_tool_name == "call_gaia_knowledge_guide"

    def test_domain_routing_copy(self, gaia: Subagent) -> None:
        # Routing copy the model reads to decide whether to delegate here.
        assert gaia.config.domain == (
            "any question about GAIA itself — the product, company, agent system, "
            "integrations, pricing, architecture, philosophy, or anything else"
        )

    def test_capabilities_routing_copy(self, gaia: Subagent) -> None:
        assert gaia.config.capabilities == (
            "exploring GAIA's own documentation to answer any question "
            "about GAIA, grounding every claim in fetched content rather "
            "than training-data knowledge"
        )

    def test_use_cases_routing_copy(self, gaia: Subagent) -> None:
        assert gaia.config.use_cases == (
            "any meta question about GAIA the product — what it is, "
            "what it does, what it supports, how it works, why it was "
            "built, who built it, what it costs, how it compares to "
            "alternatives, what it does NOT do, troubleshooting, "
            "onboarding, account questions. Use this whenever the user "
            "asks ABOUT GAIA. Do NOT use this for action requests "
            "(send email, schedule, build a workflow) — those belong "
            "to other subagents."
        )

    def test_tool_binding_flags(self, gaia: Subagent) -> None:
        # GAIA binds tools directly and skips ChromaDB retrieval; both flags
        # must be True or the subagent loses its tool set / gains retrieval it
        # is explicitly meant to skip.
        assert gaia.config.use_direct_tools is True
        assert gaia.config.disable_retrieve_tools is True

    def test_auto_binds_only_fetch_webpages(self, gaia: Subagent) -> None:
        # fetch_webpages is GAIA's sole grounding tool; the list content and
        # length both matter (extra/missing entries change the bound tool set).
        assert gaia.config.auto_bind_tools == ["fetch_webpages"]

    def test_finish_task_is_disabled(self, gaia: Subagent) -> None:
        # GAIA is answer-only: it must terminate with a plain AIMessage, so
        # finish_task is omitted from its tool set (include_finish_task=False).
        assert gaia.config.include_finish_task is False

    def test_system_prompt_is_imported_constant(self, gaia: Subagent) -> None:
        # Same object identity — not a forked copy — so prompt edits propagate.
        assert gaia.config.system_prompt is GAIA_AGENT_SYSTEM_PROMPT
        assert isinstance(gaia.config.system_prompt, str)
        assert gaia.config.system_prompt.strip() != ""

    def test_system_prompt_carries_llms_txt_discovery_surface(self, gaia: Subagent) -> None:
        # GAIA's grounding strategy depends on heygaia.io/llms.txt and
        # docs.heygaia.io/llms.txt as discovery entry points. Losing these
        # references strips GAIA's primary way to find its own docs.
        assert "llms.txt" in gaia.config.system_prompt
