"""Unit tests for `app.agents.core.subagents.builtin_subagents`.

These tests pin invariants on the `BUILTIN_SUBAGENTS` tuple so future edits
don't silently break the registry's assumptions.
"""

import pytest

from app.agents.core.subagents.builtin_subagents import BUILTIN_SUBAGENTS
from app.agents.prompts.subagent_prompts import GAIA_AGENT_SYSTEM_PROMPT
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.models.subagent_models import Subagent


@pytest.mark.unit
class TestBuiltinSubagentsTuple:
    def test_is_non_empty_tuple(self) -> None:
        assert isinstance(BUILTIN_SUBAGENTS, tuple)
        assert len(BUILTIN_SUBAGENTS) > 0

    def test_all_entries_are_subagent_instances(self) -> None:
        for entry in BUILTIN_SUBAGENTS:
            assert isinstance(entry, Subagent)

    def test_all_managed_by_internal(self) -> None:
        # Builtins are always internally managed. If this ever stops being
        # true, the assumption needs revisiting (and likely a new managed_by
        # value documented in the Subagent type).
        for entry in BUILTIN_SUBAGENTS:
            assert entry.managed_by == "internal", (
                f"Builtin {entry.id!r} has managed_by={entry.managed_by!r}, "
                "expected 'internal'"
            )

    def test_all_have_subagent_enabled(self) -> None:
        for entry in BUILTIN_SUBAGENTS:
            assert entry.config.has_subagent is True, (
                f"Builtin {entry.id!r} has has_subagent=False"
            )

    def test_ids_are_unique(self) -> None:
        ids = [entry.id for entry in BUILTIN_SUBAGENTS]
        assert len(ids) == len(set(ids)), f"Duplicate ids in BUILTIN_SUBAGENTS: {ids}"

    def test_providers_are_unique(self) -> None:
        # The module docstring warns: provider strings must not collide with
        # any future OAuth integration. Within builtins they must also be
        # unique.
        providers = [entry.provider for entry in BUILTIN_SUBAGENTS]
        assert len(providers) == len(set(providers)), (
            f"Duplicate providers in BUILTIN_SUBAGENTS: {providers}"
        )

    def test_providers_do_not_collide_with_oauth(self) -> None:
        # The registry merges OAuth-derived subagents with builtins and
        # de-duplicates by provider. A collision would silently shadow an
        # OAuth integration's subagent with a builtin (or vice versa).
        builtin_providers = {entry.provider for entry in BUILTIN_SUBAGENTS}
        oauth_providers = {integ.provider for integ in OAUTH_INTEGRATIONS}
        overlap = builtin_providers & oauth_providers
        assert not overlap, (
            f"Builtin providers collide with OAUTH_INTEGRATIONS providers: "
            f"{sorted(overlap)}"
        )

    def test_ids_do_not_collide_with_oauth(self) -> None:
        # Same rationale as providers — id collisions would let one entry
        # silently shadow another in `get_subagent_by_id`.
        builtin_ids = {entry.id for entry in BUILTIN_SUBAGENTS}
        oauth_ids = {integ.id for integ in OAUTH_INTEGRATIONS}
        overlap = builtin_ids & oauth_ids
        assert not overlap, (
            f"Builtin ids collide with OAUTH_INTEGRATIONS ids: {sorted(overlap)}"
        )


@pytest.mark.unit
class TestGaiaBuiltin:
    """Pin the GAIA Knowledge Guide builtin entry."""

    @pytest.fixture
    def gaia(self) -> Subagent:
        match = next(
            (s for s in BUILTIN_SUBAGENTS if s.id == "gaia_knowledge_guide"), None
        )
        assert match is not None, (
            "GAIA Knowledge Guide builtin missing from BUILTIN_SUBAGENTS"
        )
        return match

    def test_gaia_id_and_provider(self, gaia: Subagent) -> None:
        assert gaia.id == "gaia_knowledge_guide"
        assert gaia.provider == "gaia_knowledge_guide"
        assert gaia.managed_by == "internal"

    def test_gaia_config_agent_name(self, gaia: Subagent) -> None:
        assert gaia.config.agent_name == "gaia_knowledge_guide_agent"

    def test_gaia_config_tool_space(self, gaia: Subagent) -> None:
        assert gaia.config.tool_space == "gaia_knowledge_guide"

    def test_gaia_uses_direct_tools(self, gaia: Subagent) -> None:
        assert gaia.config.use_direct_tools is True

    def test_gaia_disables_retrieve_tools(self, gaia: Subagent) -> None:
        assert gaia.config.disable_retrieve_tools is True

    def test_gaia_auto_binds_fetch_webpages(self, gaia: Subagent) -> None:
        assert gaia.config.auto_bind_tools == ["fetch_webpages"]

    def test_gaia_system_prompt_is_imported_constant(self, gaia: Subagent) -> None:
        assert gaia.config.system_prompt is GAIA_AGENT_SYSTEM_PROMPT
        assert isinstance(gaia.config.system_prompt, str)
        assert gaia.config.system_prompt.strip() != ""

    def test_gaia_system_prompt_references_llms_txt(self, gaia: Subagent) -> None:
        # GAIA's grounding strategy depends on heygaia.io/llms.txt and
        # docs.heygaia.io/llms.txt as discovery surfaces. If these references
        # are removed from the prompt, GAIA loses its primary entry points.
        prompt = gaia.config.system_prompt or ""
        assert "llms.txt" in prompt
