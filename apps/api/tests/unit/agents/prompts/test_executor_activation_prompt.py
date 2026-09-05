"""The activation executor prompt must only teach tools the executor can call.

Under ENABLE_INTEGRATION_ACTIVATION the executor leads with `activate_integration`
and keeps `handoff` bound solely for per-user MCP integrations that cannot be
activated in-context. So the prompt teaches handoff only as that fallback, and
never teaches `wait_for_subagents` (bound but not model-facing here). Anything
else would produce calls that mislead the model, invisible until someone reads a
transcript, so it is pinned here instead.
"""

import pytest

from app.agents.core.graph_builder.build_graph import EXECUTOR_INITIAL_TOOL_IDS
from app.agents.prompts.comms_prompts import EXECUTOR_AGENT_PROMPT
from app.agents.prompts.executor_activation_prompt import (
    _PHRASE_REWRITES,
    _SECTION_REWRITES,
    ActivationPromptAnchorError,
    _replace_section,
    build_activation_executor_prompt,
)


@pytest.fixture(scope="module")
def activation_prompt() -> str:
    return build_activation_executor_prompt()


class TestNoUnboundToolsTaught:
    def test_handoff_is_taught_only_as_the_per_user_fallback(self, activation_prompt) -> None:
        """handoff is bound under the flag for per-user MCP, so the prompt may name
        it — but only as that fallback, never as the generic delegation path the
        rewrites replaced with activation."""
        handoff_lines = [
            line.strip() for line in activation_prompt.splitlines() if "handoff(" in line
        ]
        assert handoff_lines, "activation prompt must teach the handoff fallback for per-user MCP"
        assert all("per-user" in line for line in handoff_lines), handoff_lines

    def test_wait_for_subagents_is_not_taught(self, activation_prompt) -> None:
        offending = [
            line.strip()
            for line in activation_prompt.splitlines()
            if "wait_for_subagents" in line.lower()
        ]
        assert offending == [], f"activation prompt still names wait_for_subagents: {offending}"

    def test_the_baseline_prompt_does_name_them(self) -> None:
        """Guards the rewrites from passing vacuously if the source prompt drops
        handoff on its own — then these rewrites are dead code, not protection."""
        assert "handoff" in EXECUTOR_AGENT_PROMPT.lower()
        assert "wait_for_subagents" in EXECUTOR_AGENT_PROMPT.lower()

    def test_teaches_activation_and_spawn(self, activation_prompt) -> None:
        assert "activate_integration" in activation_prompt
        assert "spawn_subagent" in activation_prompt

    def test_every_tool_it_names_is_one_the_executor_binds(self, activation_prompt) -> None:
        bound = set(EXECUTOR_INITIAL_TOOL_IDS) | {
            "activate_integration",
            "spawn_subagent",
            "retrieve_tools",
        }
        for name in ("activate_integration", "spawn_subagent", "retrieve_tools", "handoff"):
            assert name in bound and name in activation_prompt


class TestAnchorsStayValid:
    """Every rewrite is anchored to the source prompt. When someone edits that
    prompt and an anchor stops matching, this fails instead of the executor
    silently keeping a handoff passage."""

    @pytest.mark.parametrize("anchor", [a for a, _ in _PHRASE_REWRITES])
    def test_phrase_anchor_present_in_source(self, anchor: str) -> None:
        assert anchor in EXECUTOR_AGENT_PROMPT

    @pytest.mark.parametrize("start,end", [(s, e) for s, e, _ in _SECTION_REWRITES])
    def test_section_markers_present_and_ordered(self, start: str, end: str) -> None:
        start_idx = EXECUTOR_AGENT_PROMPT.find(start)
        assert start_idx != -1
        assert EXECUTOR_AGENT_PROMPT.find(end, start_idx + len(start)) != -1

    def test_a_missing_anchor_raises_rather_than_shipping(self) -> None:
        with pytest.raises(ActivationPromptAnchorError):
            _replace_section("nothing to match here", "DELEGATION MODEL", "END", "x")


def test_prompt_is_rewritten_not_merely_copied(activation_prompt) -> None:
    assert activation_prompt != EXECUTOR_AGENT_PROMPT
    # The untouched parts must survive: this is a targeted rewrite, not a fork.
    assert "CODING WORKSPACE" in activation_prompt
    assert "RESEARCH EFFORT LADDER" in activation_prompt
    assert "YOUR OUTPUT (INTERNAL" in activation_prompt
