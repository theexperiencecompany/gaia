"""Unit tests for ``manage_system_prompts_node`` pure logic.

These tests call ``app.agents.core.nodes.manage_system_prompts`` directly
(input dict → output dict) rather than through the compiled graph, verifying
the node's contract in isolation. Graph-wiring coverage (that the node is
registered as a pre-model hook inside ``create_agent``) lives in
``tests/e2e/test_multi_tool_scenario.py`` (``TestMultiToolScenario``).
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from tests.e2e.conftest import make_gaia_state, make_mock_store, make_node_config


class TestManageSystemPromptsNodeUnit:
    """Unit tests for manage_system_prompts_node pure logic (node called directly).

    These tests verify the node's input→output contract in isolation.
    Graph-wiring coverage lives in TestMultiToolScenario.
    """

    def test_manage_system_prompts_keeps_only_latest_non_memory_prompt(self):
        """manage_system_prompts_node must remove all but the latest non-memory SystemMessage.

        Given two non-memory SystemMessages, only the last one should remain.
        This is the core contract of manage_system_prompts_node.
        """
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
        """manage_system_prompts_node must preserve SystemMessages marked as memory.

        Memory system messages use additional_kwargs={'memory_message': True}.
        They must never be removed, even when there are multiple non-memory prompts.
        """
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
