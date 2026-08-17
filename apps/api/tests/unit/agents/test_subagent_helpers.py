"""``create_agent_context_message`` — the executor/subagent context split.

Every other test of this function patches it away, so its real assembly has
never run: the split into a byte-stable message and a per-turn volatile tail is
the whole point of the layout change, and the markers it stamps are what
``manage_system_prompts_node`` routes on. Wrong markers or a tail folded back
into the stable half costs the prompt-cache prefix silently — nothing fails,
requests just stop hitting the cache.

Hermetic: with ``skills_text`` supplied and no user/query/integration, every
fetch inside the function short-circuits before touching Chroma or Mongo.
"""

from typing import cast
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.subagents import subagent_helpers
from app.agents.core.subagents.subagent_helpers import create_agent_context_message
from app.helpers.message_helpers import DYNAMIC_CONTEXT_MARKER, MEMORY_VOLATILE_MARKER
from app.models.agent_models import AgentConfigurable
from shared.py.wide_events import log

pytestmark = pytest.mark.unit


def _configurable(**overrides: str) -> AgentConfigurable:
    return cast(
        AgentConfigurable, {"user_name": "Ada", "user_timezone": "Europe/London", **overrides}
    )


class ProviderLookupFailed(RuntimeError):
    """A distinctly-named failure so the logged error_type cannot be a coincidence."""


class InstructionsLookupFailed(RuntimeError):
    """A distinctly-named failure so the logged error_type cannot be a coincidence."""


def _warning(needle: str) -> dict[str, object]:
    """The single wide-event warning whose message contains ``needle``."""
    matches = [w for w in log.get().get("warnings", []) if needle in w["msg"]]
    assert len(matches) == 1, matches
    return matches[0]


class TestCreateAgentContextMessage:
    async def test_the_stable_half_joins_its_parts_one_per_line(self) -> None:
        messages = await create_agent_context_message(_configurable(), skills_text="")

        assert messages.stable.content == "User Name: Ada\nUser Timezone: Europe/London"

    async def test_the_stable_half_carries_the_dynamic_context_marker(self) -> None:
        # manage_system_prompts_node keeps only the latest message per slot and
        # routes on this marker; unmarked, the block is dropped from the request.
        messages = await create_agent_context_message(_configurable(), skills_text="")

        assert messages.stable.additional_kwargs[DYNAMIC_CONTEXT_MARKER] is True

    async def test_the_volatile_tail_starts_at_its_content(self) -> None:
        # The separator between sections belongs to the assembly, so a single
        # section gets none in front of it. When each section carried its own,
        # the first one's had nothing before it and every request opened its
        # tail with a blank line unless something scraped it back off.
        messages = await create_agent_context_message(
            _configurable(), skills_text="Installable skills:\n- alpha"
        )

        assert messages.volatile_tail is not None
        assert messages.volatile_tail.content == "Installable skills:\n- alpha"

    async def test_two_sections_are_separated_by_exactly_one_blank_line(self) -> None:
        messages = await create_agent_context_message(
            _configurable(),
            memories_text="Based on our previous conversations:\n- likes tea",
            skills_text="Installable skills:\n- alpha",
        )

        assert messages.volatile_tail is not None
        assert messages.volatile_tail.content == (
            "Based on our previous conversations:\n- likes tea\n\nInstallable skills:\n- alpha"
        )

    async def test_a_sections_own_text_is_joined_verbatim(self) -> None:
        # The assembly adds a separator and nothing else — it never edits what a
        # section chose to send. A block that deliberately opens with a blank
        # line keeps it, which the old blunt lstrip of the concatenation ate.
        messages = await create_agent_context_message(
            _configurable(), skills_text="\nIndented block:\n  - alpha"
        )

        assert messages.volatile_tail is not None
        assert messages.volatile_tail.content == "\nIndented block:\n  - alpha"

    async def test_the_volatile_tail_carries_the_memory_volatile_marker(self) -> None:
        messages = await create_agent_context_message(_configurable(), skills_text="skills")

        assert messages.volatile_tail is not None
        assert messages.volatile_tail.additional_kwargs[MEMORY_VOLATILE_MARKER] is True

    async def test_the_integrations_manifest_rides_the_stable_half(self) -> None:
        # Executor-only, and deliberately NOT in the volatile tail: the list
        # changes on connect/disconnect, not per turn, so it belongs inside the
        # cacheable prefix. Putting it in the tail would re-send it every turn
        # for nothing; dropping it leaves the executor unable to name the
        # subagent_ids it hands off to.
        with patch.object(
            subagent_helpers,
            "build_connected_integrations_manifest",
            AsyncMock(return_value="Connected:\n- Slack (slack)"),
        ):
            messages = await create_agent_context_message(
                _configurable(user_id="u1"),
                skills_text="",
                include_connected_integrations=True,
            )

        assert "Connected:\n- Slack (slack)" in messages.stable.content
        assert messages.volatile_tail is None

    async def test_nothing_volatile_this_turn_sends_no_tail_at_all(self) -> None:
        # An empty SystemMessage would still cost a request slot and, worse,
        # change the request's bytes turn to turn as sections come and go.
        messages = await create_agent_context_message(_configurable(), skills_text="")

        assert messages.volatile_tail is None


class TestProviderMetadataSection:
    """The per-integration USER CONTEXT block, in the volatile tail.

    ``github`` is a real entry in ``oauth_config`` (name "GitHub", provider
    "github"), so the block's header exercises the real casing rather than a
    stand-in whose upper- and lower-case spellings would be indistinguishable.
    """

    async def test_the_block_is_assembled_verbatim(self) -> None:
        with patch.object(subagent_helpers, "get_instructions", AsyncMock(return_value=None)):
            messages = await create_agent_context_message(
                _configurable(user_id="u1"),
                skills_text="",
                integration_id="github",
                provider_metadata={"login": "ada", "email": "ada@example.com"},
            )

        assert messages.volatile_tail is not None
        assert messages.volatile_tail.content == (
            "USER CONTEXT FOR GITHUB:\n- login: ada\n- email: ada@example.com\n"
        )

    async def test_a_failed_lookup_drops_the_section_and_names_the_cause(self) -> None:
        # The provider lookup is the one section that hits Mongo on the request
        # path. Losing it must degrade to "no section", and the wide event is
        # the only place that says WHY — an unnamed cause here is an outage that
        # reads as a user who simply has no provider metadata.
        log.reset()
        with (
            patch.object(
                subagent_helpers,
                "get_provider_metadata",
                AsyncMock(side_effect=ProviderLookupFailed("mongo unreachable")),
            ),
            patch.object(subagent_helpers, "get_instructions", AsyncMock(return_value=None)),
        ):
            messages = await create_agent_context_message(
                _configurable(user_id="u1"),
                skills_text="",
                integration_id="github",
            )

        assert messages.volatile_tail is None
        warning = _warning("Failed to fetch provider metadata")
        assert warning["error_type"] == "ProviderLookupFailed"
        assert warning["error"] == "mongo unreachable"
        assert warning["provider"] == "github"


class TestCustomInstructionsSection:
    """The user's per-integration instructions, in the volatile tail."""

    async def test_the_block_is_assembled_verbatim(self) -> None:
        with (
            patch.object(
                subagent_helpers, "get_instructions", AsyncMock(return_value="  focus on #eng  ")
            ),
            patch.object(subagent_helpers, "get_provider_metadata", AsyncMock(return_value=None)),
        ):
            messages = await create_agent_context_message(
                _configurable(user_id="u1"),
                skills_text="",
                integration_id="github",
            )

        assert messages.volatile_tail is not None
        assert messages.volatile_tail.content == (
            "CUSTOM INSTRUCTIONS FOR GITHUB (set by the user — honor these):\nfocus on #eng\n"
        )

    async def test_a_failed_lookup_drops_the_section_and_names_the_cause(self) -> None:
        log.reset()
        with (
            patch.object(
                subagent_helpers,
                "get_instructions",
                AsyncMock(side_effect=InstructionsLookupFailed("mongo unreachable")),
            ),
            patch.object(subagent_helpers, "get_provider_metadata", AsyncMock(return_value=None)),
        ):
            messages = await create_agent_context_message(
                _configurable(user_id="u1"),
                skills_text="",
                integration_id="github",
            )

        assert messages.volatile_tail is None
        warning = _warning("Failed to fetch custom instructions")
        assert warning["error_type"] == "InstructionsLookupFailed"
        assert warning["error"] == "mongo unreachable"
        assert warning["integration_id"] == "github"
