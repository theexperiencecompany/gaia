"""Unit tests for manage_system_prompts_node pure logic.

These tests call app.agents.core.nodes.manage_system_prompts directly
(input dict → output dict) rather than through the compiled graph, verifying
the node's contract in isolation. Graph-wiring coverage (that the node is
registered as a pre-model hook inside create_agent) lives in
tests/e2e/test_multi_tool_scenario.py (TestMultiToolScenario).
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from prometheus_client import REGISTRY

from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from tests.e2e.conftest import make_gaia_state, make_mock_store, make_node_config


class TestManageSystemPromptsNodeUnit:
    """Unit tests for manage_system_prompts_node pure logic (node called directly).

    These tests verify the node's input→output contract in isolation.
    Graph-wiring coverage lives in TestMultiToolScenario.
    """

    def test_manage_system_prompts_keeps_only_latest_non_memory_prompt(self):
        old_prompt = SystemMessage(content="Old system prompt from turn 1")
        new_prompt = SystemMessage(content="New system prompt from turn 2")
        human = HumanMessage(content="What is the weather?")

        state = make_gaia_state(messages=[old_prompt, human, new_prompt])
        config = make_node_config()
        store = make_mock_store()

        result = manage_system_prompts_node(state, config, store)

        system_messages = [m for m in result["messages"] if isinstance(m, SystemMessage)]
        assert len(system_messages) == 1, (
            "manage_system_prompts_node must keep only the latest non-memory system prompt"
        )
        assert system_messages[0].content == "New system prompt from turn 2"

    def test_manage_system_prompts_preserves_memory_messages(self):
        """Memory messages are marked via additional_kwargs={"memory_message": True}."""
        memory_prompt = SystemMessage(
            content="User prefers concise answers.",
            additional_kwargs={"memory_message": True},
        )
        old_system = SystemMessage(content="Old system prompt")
        new_system = SystemMessage(content="New system prompt")
        human = HumanMessage(content="Tell me something")

        state = make_gaia_state(messages=[memory_prompt, old_system, human, new_system])
        config = make_node_config()
        store = make_mock_store()

        result = manage_system_prompts_node(state, config, store)

        system_messages = [m for m in result["messages"] if isinstance(m, SystemMessage)]
        assert len(system_messages) == 2, (
            "manage_system_prompts_node must keep memory messages AND the latest non-memory prompt"
        )
        memory_msgs = [m for m in system_messages if m.additional_kwargs.get("memory_message")]
        assert len(memory_msgs) == 1
        assert memory_msgs[0].content == "User prefers concise answers."
        non_memory_msgs = [
            m for m in system_messages if not m.additional_kwargs.get("memory_message")
        ]
        assert non_memory_msgs[0].content == "New system prompt"

    def test_manage_system_prompts_no_system_messages_is_noop(self):
        """manage_system_prompts_node must be a no-op when no SystemMessages exist."""
        state = make_gaia_state(
            messages=[
                HumanMessage(content="Hello"),
                AIMessage(content="Hi there!"),
            ]
        )
        config = make_node_config()
        store = make_mock_store()

        result = manage_system_prompts_node(state, config, store)

        assert len(result["messages"]) == 2
        assert result["messages"][0].content == "Hello"
        assert result["messages"][1].content == "Hi there!"

    def test_manage_system_prompts_single_prompt_is_preserved(self):
        """manage_system_prompts_node must keep the single non-memory SystemMessage."""
        state = make_gaia_state(
            messages=[
                SystemMessage(content="Only system prompt"),
                HumanMessage(content="Hello"),
            ]
        )
        config = make_node_config()
        store = make_mock_store()

        result = manage_system_prompts_node(state, config, store)

        system_msgs = [m for m in result["messages"] if isinstance(m, SystemMessage)]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "Only system prompt"

    def test_node_emits_latency_span(self):
        state = make_gaia_state(messages=[HumanMessage(content="Hello")])
        config = make_node_config()
        config["configurable"]["agent_name"] = "node-test-agent"
        before = (
            REGISTRY.get_sample_value(
                "graph_node_seconds_count",
                {"node": "manage_system_prompts", "agent": "node-test-agent"},
            )
            or 0.0
        )

        manage_system_prompts_node(state, config, make_mock_store())

        assert (
            REGISTRY.get_sample_value(
                "graph_node_seconds_count",
                {"node": "manage_system_prompts", "agent": "node-test-agent"},
            )
            == before + 1
        )
