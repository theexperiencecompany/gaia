"""The executor prompt teaches activation for every integration, per-user MCP included."""

import pytest

from app.agents.core.graph_builder.build_graph import EXECUTOR_INITIAL_TOOL_IDS
from app.agents.prompts.comms_prompts import EXECUTOR_AGENT_PROMPT


def _lines_containing(needle: str) -> list[str]:
    return [line.strip() for line in EXECUTOR_AGENT_PROMPT.splitlines() if needle in line.lower()]


@pytest.mark.unit
class TestExecutorPromptDoctrine:
    def test_no_handoff_is_taught(self) -> None:
        assert _lines_containing("handoff") == []

    def test_no_subagent_routing_id_survives(self) -> None:
        assert _lines_containing("subagent:") == []

    def test_no_join_tool_is_taught(self) -> None:
        assert _lines_containing("wait_for_subagents") == []
        assert _lines_containing("collect_subagent_results") == []

    def test_mcp_integrations_are_activated_like_any_other(self) -> None:
        mcp_lines = _lines_containing("mcp")
        assert mcp_lines
        assert any("activate" in line and "execute" in line for line in mcp_lines)

    def test_built_ins_are_activated(self) -> None:
        assert 'activate_integration("todos")' in EXECUTOR_AGENT_PROMPT
        assert 'activate_integration("gaia_knowledge_guide")' in EXECUTOR_AGENT_PROMPT
        assert 'activate_integration("docgen")' in EXECUTOR_AGENT_PROMPT

    def test_background_outcomes_arrive_without_a_join_call(self) -> None:
        assert "arrive" in EXECUTOR_AGENT_PROMPT

    def test_teaches_activation_spawn_and_execute(self) -> None:
        for name in ("activate_integration", "spawn_subagent", "retrieve_tools", "execute"):
            assert name in EXECUTOR_AGENT_PROMPT

    def test_handoff_is_not_bound(self) -> None:
        assert "handoff" not in EXECUTOR_INITIAL_TOOL_IDS
