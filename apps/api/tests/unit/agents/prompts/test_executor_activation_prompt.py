"""The activation rewrites must drift loudly, never silently.

build_activation_executor_prompt runs at import time, so a stale anchor skips
with a warning instead of raising: one edited sentence must not keep the API
from starting. The tradeoff is that a skipped rewrite leaves a handoff-era
passage behind, so these tests pin every anchor and every replacement in CI.
"""

import pytest

from app.agents.core.graph_builder.build_graph import EXECUTOR_INITIAL_TOOL_IDS
from app.agents.prompts import executor_activation_prompt
from app.agents.prompts.comms_prompts import EXECUTOR_AGENT_PROMPT
from app.agents.prompts.executor_activation_prompt import (
    _PHRASE_REWRITES,
    build_activation_executor_prompt,
)
from tests.helpers import captured_wide_event


@pytest.fixture(scope="module")
def activation_prompt() -> str:
    return build_activation_executor_prompt()


@pytest.mark.unit
class TestAnchorsStayValid:
    """Every rewrite is anchored to the source prompt, so an edit that moves an anchor fails here."""

    @pytest.mark.parametrize("anchor", [anchor for anchor, _ in _PHRASE_REWRITES])
    def test_phrase_anchor_present_in_source(self, anchor: str) -> None:
        assert anchor in EXECUTOR_AGENT_PROMPT


@pytest.mark.unit
class TestRewritesApply:
    """The built prompt carries every replacement and none of the legacy text it replaced."""

    @pytest.mark.parametrize("anchor", [anchor for anchor, _ in _PHRASE_REWRITES])
    def test_no_phrase_anchor_survives_in_the_built_prompt(
        self, activation_prompt: str, anchor: str
    ) -> None:
        assert anchor not in activation_prompt

    @pytest.mark.parametrize("replacement", [replacement for _, replacement in _PHRASE_REWRITES])
    def test_every_phrase_replacement_lands_in_the_built_prompt(
        self, activation_prompt: str, replacement: str
    ) -> None:
        assert replacement in activation_prompt

    def test_replaced_handoff_sections_are_gone(self, activation_prompt: str) -> None:
        assert "Handoff contract (strict)" not in activation_prompt
        assert "handoff (specialized provider subagents)" not in activation_prompt

    def test_activation_doctrine_replaces_delegation(self, activation_prompt: str) -> None:
        assert "activate_integration(integration_id" in activation_prompt
        assert "Working an activated integration" in activation_prompt


@pytest.mark.unit
class TestNoUnboundToolsTaught:
    """The executor leads with activate_integration and keeps handoff only for per-user MCP."""

    def test_handoff_is_taught_only_as_the_per_user_fallback(self, activation_prompt: str) -> None:
        """Any handoff line the rewrites failed to replace is a handoff-era instruction left standing."""
        handoff_lines = [
            line.strip() for line in activation_prompt.splitlines() if "handoff" in line.lower()
        ]
        assert handoff_lines, "activation prompt must teach the handoff fallback for per-user MCP"
        assert all("per-user" in line for line in handoff_lines), handoff_lines

    def test_no_subagent_routing_id_survives(self, activation_prompt: str) -> None:
        """Catches drift no per-anchor test can: routing text ADDED to the base prompt with no rewrite entry."""
        routing = [
            line.strip() for line in activation_prompt.splitlines() if "subagent:" in line.lower()
        ]
        assert routing == [], f"activation prompt still routes to a subagent: {routing}"

    def test_wait_for_subagents_is_not_taught(self, activation_prompt: str) -> None:
        offending = [
            line.strip()
            for line in activation_prompt.splitlines()
            if "wait_for_subagents" in line.lower() or "collect_subagent_results" in line.lower()
        ]
        assert offending == [], f"activation prompt still names a join tool: {offending}"

    def test_background_outcomes_arrive_without_a_join_call(self, activation_prompt: str) -> None:
        assert "arrive" in activation_prompt

    def test_the_baseline_prompt_does_name_handoff(self) -> None:
        """Guards the rewrites from passing vacuously if the source prompt drops handoff on its own."""
        assert "handoff" in EXECUTOR_AGENT_PROMPT.lower()
        assert "wait_for_subagents" not in EXECUTOR_AGENT_PROMPT.lower()
        assert "collect_subagent_results" not in EXECUTOR_AGENT_PROMPT.lower()

    def test_teaches_activation_and_spawn(self, activation_prompt: str) -> None:
        assert "activate_integration" in activation_prompt
        assert "spawn_subagent" in activation_prompt

    def test_every_tool_it_names_is_one_the_executor_binds(self, activation_prompt: str) -> None:
        bound = set(EXECUTOR_INITIAL_TOOL_IDS) | {
            "activate_integration",
            "spawn_subagent",
            "retrieve_tools",
        }
        for name in ("activate_integration", "spawn_subagent", "retrieve_tools", "handoff"):
            assert name in bound and name in activation_prompt


@pytest.mark.unit
class TestDegradesGracefully:
    """One edited sentence skips just that rewrite with a warning, never blocks startup."""

    def test_stale_phrase_anchor_is_skipped_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        anchor, _ = _PHRASE_REWRITES[0]
        assert anchor in EXECUTOR_AGENT_PROMPT
        monkeypatch.setattr(
            executor_activation_prompt,
            "EXECUTOR_AGENT_PROMPT",
            EXECUTOR_AGENT_PROMPT.replace(anchor, ""),
        )
        prompt = executor_activation_prompt.build_activation_executor_prompt()
        assert "RESEARCH EFFORT LADDER" in prompt
        assert "activate_integration" in prompt


@pytest.mark.unit
def test_prompt_is_rewritten_not_merely_copied(activation_prompt: str) -> None:
    assert activation_prompt != EXECUTOR_AGENT_PROMPT
    assert "CODING WORKSPACE" in activation_prompt
    assert "RESEARCH EFFORT LADDER" in activation_prompt
    assert "YOUR OUTPUT (INTERNAL" in activation_prompt


@pytest.mark.unit
class TestStaleAnchorsAreReported:
    """A skipped rewrite is invisible in the prompt, so its warning is the only trace."""

    async def test_a_stale_phrase_is_named_and_the_rest_still_apply(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stale, _ = max(_PHRASE_REWRITES[:-1], key=lambda rewrite: len(rewrite[0]))
        last_anchor, last_replacement = _PHRASE_REWRITES[-1]
        monkeypatch.setattr(
            executor_activation_prompt,
            "EXECUTOR_AGENT_PROMPT",
            EXECUTOR_AGENT_PROMPT.replace(stale, ""),
        )

        async with captured_wide_event() as event:
            prompt = build_activation_executor_prompt()

        assert len(stale) > 81
        assert event["warnings"] == [
            {"msg": "activation_prompt.stale_phrase_anchor_skipped", "anchor": stale[:80]}
        ]
        assert last_replacement in prompt
        assert last_anchor not in prompt
