"""The section table, and the sections whose bodies live beside it.

A section with no logic of its own is registered straight against its read in
``fetchers`` and is covered there. What is left here branches before rendering —
a tier-dependent header, a provider lookup, two sources of skills — and this is
the tier at which that branching is cheap to pin: the table and the branch, with
every store mocked one layer down.

``test_context_sections.py`` covers the two sections with real service logic
behind them against un-mocked production code; this file covers the branching,
the ordering, and the failure paths that never reach a service at all.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from tests.helpers import captured_wide_event

from app.agents.context.section_context import SectionContext
from app.agents.context.sections import SECTIONS, Section, sections_for
from app.agents.context.slots import PromptSlot
from app.agents.context.text import (
    CONNECTED_INTEGRATIONS_HEADER,
    EXECUTOR_CONNECTED_INTEGRATIONS_HEADER,
)
from app.agents.context.tiers import ALL_TIERS, AgentTier
from app.config.oauth_config import get_integration_by_id
from app.constants.log_tags import LogTag

#: A real, registered integration, so ``get_integration_by_id`` resolves and the
#: provider-metadata and custom-instruction sections are genuinely reachable
#: rather than short-circuiting on an unknown id.
INTEGRATION_ID = "gmail"


def section(section_id: str) -> Section:
    return next(s for s in SECTIONS if s.id == section_id)


def ctx(
    tier: AgentTier = AgentTier.COMMS,
    *,
    user_id: str | None = "user1",
    user_name: str | None = None,
    user_timezone: str | None = None,
    user_preferences: dict[str, Any] | None = None,
    writing_style: dict[str, Any] | None = None,
    subagent_id: str | None = None,
    integration_id: str | None = None,
) -> SectionContext:
    return SectionContext(
        tier=tier,
        user_id=user_id,
        user_name=user_name,
        user_timezone=user_timezone,
        user_preferences=user_preferences,
        writing_style=writing_style,
        subagent_id=subagent_id,
        integration_id=integration_id,
    )


@pytest.mark.unit
class TestTheTableIsWellFormed:
    def test_every_section_id_is_unique(self) -> None:
        """Results are read back by id, so a duplicate would silently drop one
        section's text and render the other's twice."""
        ids = [s.id for s in SECTIONS]

        assert len(ids) == len(set(ids))

    def test_every_section_applies_to_at_least_one_tier(self) -> None:
        """A section no tier receives is dead weight that still runs its fetch."""
        for entry in SECTIONS:
            assert entry.applies_to, f"{entry.id} is registered against no tier"
            assert entry.applies_to <= ALL_TIERS

    @pytest.mark.parametrize("tier", list(AgentTier))
    @pytest.mark.parametrize("slot", [PromptSlot.DYNAMIC_STABLE, PromptSlot.MEMORY_RECALL])
    def test_sections_for_returns_only_that_tier_and_slot(
        self, tier: AgentTier, slot: PromptSlot
    ) -> None:
        for entry in sections_for(tier, slot):
            assert entry.slot is slot
            assert entry.applies(tier)

    @pytest.mark.parametrize("tier", list(AgentTier))
    @pytest.mark.parametrize("slot", [PromptSlot.DYNAMIC_STABLE, PromptSlot.MEMORY_RECALL])
    def test_sections_come_back_in_declared_order(self, tier: AgentTier, slot: PromptSlot) -> None:
        orders = [entry.order for entry in sections_for(tier, slot)]

        assert orders == sorted(orders)

    def test_comms_receives_exactly_these_sections_in_this_order(self) -> None:
        """Spelled out rather than merely "sorted": the two run banners sort
        LAST on purpose, so their directives land with recency immediately
        before the conversation begins, and a reversed or unsorted result still
        satisfies a weaker check on a short list."""
        assert [s.id for s in sections_for(AgentTier.COMMS, PromptSlot.DYNAMIC_STABLE)] == [
            "user_identity",
            "user_prefs",
            "integrations_manifest",
        ]
        assert [s.id for s in sections_for(AgentTier.COMMS, PromptSlot.MEMORY_RECALL)] == [
            "core_memory",
            "memory_recall",
            "gaia_knowledge",
            "tracked_todos",
            "bg_banner",
            "active_todo_banner",
        ]

    def test_the_executor_receives_its_own_stable_set(self) -> None:
        assert [s.id for s in sections_for(AgentTier.EXECUTOR, PromptSlot.DYNAMIC_STABLE)] == [
            "user_identity",
            "user_prefs",
            "workspace_session",
            "integrations_manifest",
        ]
        assert [s.id for s in sections_for(AgentTier.EXECUTOR, PromptSlot.MEMORY_RECALL)] == [
            "core_memory",
            "memory_recall",
            "gaia_knowledge",
            "skills",
            "tracked_todos",
            "bg_banner",
            "active_todo_banner",
        ]

    def test_a_section_excludes_the_tiers_it_was_not_registered_against(self) -> None:
        """``applies`` is what keeps comms — which holds no file or shell tools —
        from being handed the skills listing."""
        assert not section("skills").applies(AgentTier.COMMS)
        assert section("skills").applies(AgentTier.EXECUTOR)

    async def test_user_prefs_reaches_every_tier_because_configurable_carries_it(self) -> None:
        """``user_prefs`` applies to every tier — proven against the actual data
        path, not just the registry entry: ``from_configurable`` reads
        ``user_preferences`` / ``writing_style`` off ``configurable`` (set once
        by ``build_agent_config`` at a run's root, inherited by every child), so
        a worker tier built the way production actually builds one renders the
        section rather than silently getting an empty string forever."""
        assert section("user_prefs").applies_to == ALL_TIERS
        worker_ctx = SectionContext.from_configurable(
            AgentTier.EXECUTOR,
            {"user_preferences": {"profession": "engineer"}, "writing_style": None},
        )
        assert await section("user_prefs").fetch(worker_ctx) != ""

    def test_workspace_session_is_scoped_to_tiers_that_build_from_a_configurable(self) -> None:
        """Comms never calls ``SectionContext.from_configurable`` — it constructs
        the context directly in ``messages.py`` with no ``vfs_session_id`` — so
        ``build_workspace_session_banner`` would always render "" for it.
        Mirrors ``test_user_prefs_is_scoped_to_the_only_tier_that_populates_it``
        from the other direction."""
        assert AgentTier.COMMS not in section("workspace_session").applies_to


@pytest.mark.unit
class TestUserIdentity:
    async def test_it_states_the_name_and_the_home_zone(self) -> None:
        rendered = await section("user_identity").fetch(
            ctx(user_name="Ada", user_timezone="Asia/Kolkata")
        )

        assert rendered == "User Name: Ada\nUser Timezone: Asia/Kolkata"

    async def test_a_missing_field_is_omitted_rather_than_rendered_blank(self) -> None:
        assert await section("user_identity").fetch(ctx(user_name="Ada")) == "User Name: Ada"
        assert (
            await section("user_identity").fetch(ctx(user_timezone="Asia/Kolkata"))
            == "User Timezone: Asia/Kolkata"
        )

    async def test_an_unknown_user_yields_nothing(self) -> None:
        assert await section("user_identity").fetch(ctx()) == ""

    async def test_it_carries_no_clock(self) -> None:
        """Only the static home zone belongs here. A minute-ticking byte in this
        block would reset the cache boundary on every call."""
        rendered = await section("user_identity").fetch(
            ctx(user_name="Ada", user_timezone="Asia/Kolkata")
        )

        assert ":" not in rendered.replace("User Name:", "").replace("User Timezone:", "")


@pytest.mark.unit
class TestUserPreferences:
    async def test_it_renders_the_formatted_preferences(self) -> None:
        with patch(
            "app.agents.context.sections.format_user_preferences_for_agent",
            return_value="- Prefers short answers",
        ):
            rendered = await section("user_prefs").fetch(ctx(user_preferences={"tone": "short"}))

        assert rendered == "User Preferences:\n- Prefers short answers"

    async def test_writing_style_alone_is_enough_to_render(self) -> None:
        with patch(
            "app.agents.context.sections.format_user_preferences_for_agent",
            return_value="- Writes in lowercase",
        ):
            rendered = await section("user_prefs").fetch(ctx(writing_style={"case": "lower"}))

        assert rendered == "User Preferences:\n- Writes in lowercase"

    async def test_both_sources_reach_the_formatter(self) -> None:
        """Preferences and writing style are separate onboarding answers. Drop
        either on the way to the formatter and the agent silently stops honouring
        half of what the user told it during onboarding."""
        with patch(
            "app.agents.context.sections.format_user_preferences_for_agent", return_value="- x"
        ) as formatter:
            await section("user_prefs").fetch(
                ctx(user_preferences={"tone": "formal"}, writing_style={"case": "lower"})
            )

        formatter.assert_called_once_with({"tone": "formal"}, writing_style={"case": "lower"})

    async def test_a_writing_style_only_user_reaches_the_formatter_intact(self) -> None:
        """With no preferences the formatter still needs an empty mapping, not
        ``None`` — and the style must survive the substitution."""
        with patch(
            "app.agents.context.sections.format_user_preferences_for_agent", return_value="- x"
        ) as formatter:
            await section("user_prefs").fetch(ctx(writing_style={"case": "lower"}))

        formatter.assert_called_once_with({}, writing_style={"case": "lower"})

    async def test_no_preferences_at_all_yields_nothing(self) -> None:
        assert await section("user_prefs").fetch(ctx()) == ""

    async def test_preferences_that_format_to_nothing_yield_no_bare_header(self) -> None:
        """A lone header tells the agent it has preferences and that they are
        empty, which reads like a fetch failure."""
        with patch(
            "app.agents.context.sections.format_user_preferences_for_agent", return_value=""
        ):
            assert await section("user_prefs").fetch(ctx(user_preferences={"tone": "short"})) == ""


@pytest.mark.unit
class TestIntegrationsManifest:
    """The executor performs the handoffs, so its header states the list is live
    and names the parenthesised id as the ``subagent_id``. Comms only hands off,
    so it gets the short form."""

    @staticmethod
    def _connected() -> AsyncMock:
        return AsyncMock(return_value=[{"id": "gmail", "name": "Gmail"}])

    async def test_the_executor_gets_the_handoff_instructions(self) -> None:
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named", self._connected()
        ):
            rendered = await section("integrations_manifest").fetch(ctx(AgentTier.EXECUTOR))

        assert rendered.startswith(EXECUTOR_CONNECTED_INTEGRATIONS_HEADER)

    async def test_comms_gets_the_capability_awareness_header(self) -> None:
        with patch(
            "app.agents.context.fetchers.get_connected_integrations_named", self._connected()
        ):
            rendered = await section("integrations_manifest").fetch(ctx(AgentTier.COMMS))

        assert rendered.startswith(CONNECTED_INTEGRATIONS_HEADER)

    async def test_an_unknown_user_is_asked_for_no_manifest_at_all(self) -> None:
        connected = self._connected()
        with patch("app.agents.context.fetchers.get_connected_integrations_named", connected):
            assert (
                await section("integrations_manifest").fetch(SectionContext(AgentTier.COMMS)) == ""
            )

        connected.assert_not_awaited()


@pytest.mark.unit
class TestProviderMetadata:
    async def test_it_names_who_the_user_is_on_that_provider(self) -> None:
        """Two fields, not one: with a single entry the ``\\n`` joining them is
        unobservable, and a separator that stopped separating would run the
        provider's identity fields together into one unreadable line."""
        with patch(
            "app.agents.context.sections.get_provider_metadata",
            AsyncMock(return_value={"email": "ada@example.com", "login": "ada"}),
        ):
            rendered = await section("provider_metadata").fetch(
                ctx(AgentTier.PROVIDER_SUBAGENT, integration_id=INTEGRATION_ID)
            )

        assert rendered == "USER CONTEXT FOR GMAIL:\n- email: ada@example.com\n- login: ada"

    async def test_it_asks_about_this_user_on_this_provider(self) -> None:
        """The provider comes from the resolved integration, not the raw id —
        asking the wrong provider returns another account's identity."""
        metadata = AsyncMock(return_value={})
        with patch("app.agents.context.sections.get_provider_metadata", metadata):
            await section("provider_metadata").fetch(
                ctx(AgentTier.PROVIDER_SUBAGENT, integration_id=INTEGRATION_ID)
            )

        metadata.assert_awaited_once_with("user1", get_integration_by_id(INTEGRATION_ID).provider)

    async def test_an_unknown_user_is_never_looked_up(self) -> None:
        metadata = AsyncMock(return_value={"email": "ada@example.com"})
        with patch("app.agents.context.sections.get_provider_metadata", metadata):
            rendered = await section("provider_metadata").fetch(
                SectionContext(AgentTier.PROVIDER_SUBAGENT, integration_id=INTEGRATION_ID)
            )

        assert rendered == ""
        metadata.assert_not_awaited()

    async def test_an_unregistered_integration_is_never_looked_up(self) -> None:
        """A subagent id that resolves to no integration has no provider to ask
        about; querying anyway would be a lookup on a guess."""
        metadata = AsyncMock(return_value={"email": "ada@example.com"})
        with patch("app.agents.context.sections.get_provider_metadata", metadata):
            rendered = await section("provider_metadata").fetch(
                ctx(AgentTier.PROVIDER_SUBAGENT, integration_id="not-a-real-integration")
            )

        assert rendered == ""
        metadata.assert_not_awaited()

    async def test_no_metadata_yields_no_block(self) -> None:
        with patch("app.agents.context.sections.get_provider_metadata", AsyncMock(return_value={})):
            assert (
                await section("provider_metadata").fetch(
                    ctx(AgentTier.PROVIDER_SUBAGENT, integration_id=INTEGRATION_ID)
                )
                == ""
            )

    async def test_a_failed_lookup_is_visible_in_the_wide_event(self) -> None:
        async with captured_wide_event() as event:
            with patch(
                "app.agents.context.sections.get_provider_metadata",
                AsyncMock(side_effect=RuntimeError("composio down")),
            ):
                rendered = await section("provider_metadata").fetch(
                    ctx(AgentTier.PROVIDER_SUBAGENT, integration_id=INTEGRATION_ID)
                )

        assert rendered == ""
        (warning,) = event["warnings"]
        assert warning["msg"] == f"{LogTag.AGENT} Failed to fetch provider metadata"
        assert warning["provider"]
        assert warning["user_id"] == "user1"
        assert warning["error"] == "composio down"
        assert warning["error_type"] == "RuntimeError"


@pytest.mark.unit
class TestCustomInstructions:
    async def test_it_injects_the_users_instructions_in_full(self) -> None:
        """Injected rather than pointed at, so the subagent honours "focus on
        #eng" without spending a file read to discover it."""
        with patch(
            "app.agents.context.sections.get_instructions",
            AsyncMock(return_value="  Always archive newsletters.  "),
        ):
            rendered = await section("custom_instructions").fetch(
                ctx(AgentTier.PROVIDER_SUBAGENT, integration_id=INTEGRATION_ID)
            )

        assert rendered == (
            "CUSTOM INSTRUCTIONS FOR GMAIL (set by the user — honor these):\n"
            "Always archive newsletters."
        )

    async def test_a_spawned_subagent_is_looked_up_by_its_own_id(self) -> None:
        """With no integration, ``subagent_id`` is the key — otherwise a spawned
        worker silently never receives instructions set for it."""
        instructions = AsyncMock(return_value="Stay terse.")
        with patch("app.agents.context.sections.get_instructions", instructions):
            rendered = await section("custom_instructions").fetch(
                ctx(AgentTier.PROVIDER_SUBAGENT, subagent_id="docgen")
            )

        instructions.assert_awaited_once_with("user1", "docgen")
        assert rendered.startswith("CUSTOM INSTRUCTIONS FOR DOCGEN")

    async def test_no_instructions_yields_no_block(self) -> None:
        with patch("app.agents.context.sections.get_instructions", AsyncMock(return_value="")):
            assert (
                await section("custom_instructions").fetch(
                    ctx(AgentTier.PROVIDER_SUBAGENT, integration_id=INTEGRATION_ID)
                )
                == ""
            )

    async def test_a_failed_lookup_is_visible_in_the_wide_event(self) -> None:
        async with captured_wide_event() as event:
            with patch(
                "app.agents.context.sections.get_instructions",
                AsyncMock(side_effect=RuntimeError("mongo down")),
            ):
                rendered = await section("custom_instructions").fetch(
                    ctx(AgentTier.PROVIDER_SUBAGENT, integration_id=INTEGRATION_ID)
                )

        assert rendered == ""
        (warning,) = event["warnings"]
        assert warning["msg"] == f"{LogTag.AGENT} Failed to fetch custom instructions"
        assert warning["integration_id"] == INTEGRATION_ID
        assert warning["user_id"] == "user1"
        assert warning["error"] == "mongo down"
        assert warning["error_type"] == "RuntimeError"


@pytest.mark.unit
class TestSkills:
    async def test_it_lists_the_installable_skills(self) -> None:
        with patch(
            "app.agents.context.sections.get_available_skills_text",
            AsyncMock(return_value="## Available skills\n- inbox-triage"),
        ):
            rendered = await section("skills").fetch(ctx(AgentTier.EXECUTOR))

        assert rendered == "## Available skills\n- inbox-triage"

    async def test_the_executor_is_the_default_lookup_key(self) -> None:
        skills = AsyncMock(return_value="")
        with patch("app.agents.context.sections.get_available_skills_text", skills):
            await section("skills").fetch(ctx(AgentTier.EXECUTOR))

        skills.assert_awaited_once_with(user_id="user1", agent_name="executor")

    async def test_a_named_subagent_is_looked_up_under_its_own_name(self) -> None:
        """Falling back to the executor key here would hand every subagent the
        executor's skills instead of its own."""
        skills = AsyncMock(return_value="")
        with (
            patch("app.agents.context.sections.get_available_skills_text", skills),
            patch("app.agents.context.sections.integration_skills_block", return_value=""),
        ):
            await section("skills").fetch(
                ctx(AgentTier.PROVIDER_SUBAGENT, subagent_id="docgen_agent")
            )

        skills.assert_awaited_once_with(user_id="user1", agent_name="docgen_agent")

    async def test_an_unknown_user_is_never_looked_up(self) -> None:
        skills = AsyncMock(return_value="## Available skills\n- inbox-triage")
        with patch("app.agents.context.sections.get_available_skills_text", skills):
            rendered = await section("skills").fetch(SectionContext(AgentTier.EXECUTOR))

        assert rendered == ""
        skills.assert_not_awaited()

    async def test_a_subagents_integration_skills_are_appended(self) -> None:
        """``subagent_id`` carries the agent_name ("docgen_agent") while the
        skills map is keyed by the subagent id ("docgen"); mapped wrong this
        silently finds nothing."""
        with (
            patch(
                "app.agents.context.sections.get_available_skills_text",
                AsyncMock(return_value="## Available skills\n- inbox-triage"),
            ),
            patch(
                "app.agents.context.sections.integration_skills_block",
                return_value="## Gmail skills\n- archive",
            ) as block,
        ):
            rendered = await section("skills").fetch(
                ctx(AgentTier.PROVIDER_SUBAGENT, subagent_id="docgen_agent")
            )

        block.assert_called_once_with("docgen")
        assert rendered == "## Available skills\n- inbox-triage\n\n## Gmail skills\n- archive"

    async def test_integration_skills_stand_alone_when_there_are_no_installable_ones(self) -> None:
        with (
            patch(
                "app.agents.context.sections.get_available_skills_text", AsyncMock(return_value="")
            ),
            patch(
                "app.agents.context.sections.integration_skills_block",
                return_value="## Gmail skills\n- archive",
            ),
        ):
            rendered = await section("skills").fetch(
                ctx(AgentTier.PROVIDER_SUBAGENT, subagent_id="docgen_agent")
            )

        assert rendered == "## Gmail skills\n- archive"

    async def test_a_failed_skills_read_still_yields_the_integration_ones(self) -> None:
        """The two sources are independent — losing one must not cost the other."""
        async with captured_wide_event() as event:
            with (
                patch(
                    "app.agents.context.sections.get_available_skills_text",
                    AsyncMock(side_effect=RuntimeError("workspace down")),
                ),
                patch(
                    "app.agents.context.sections.integration_skills_block",
                    return_value="## Gmail skills\n- archive",
                ),
            ):
                rendered = await section("skills").fetch(
                    ctx(AgentTier.PROVIDER_SUBAGENT, subagent_id="docgen_agent")
                )

        assert rendered == "## Gmail skills\n- archive"
        (warning,) = event["warnings"]
        assert warning["msg"] == f"{LogTag.AGENT} Error injecting installable skills"
        assert warning["user_id"] == "user1"
        assert warning["error"] == "workspace down"
        assert warning["error_type"] == "RuntimeError"

    async def test_a_failed_skills_read_with_no_integration_ones_yields_empty_text(self) -> None:
        """Exactly ``""``, not ``None``: a section's contract is text, and a
        ``None`` here would reach the assembler as a non-string."""
        with patch(
            "app.agents.context.sections.get_available_skills_text",
            AsyncMock(side_effect=RuntimeError("workspace down")),
        ):
            rendered = await section("skills").fetch(ctx(AgentTier.EXECUTOR))

        assert rendered == ""
        assert isinstance(rendered, str)
