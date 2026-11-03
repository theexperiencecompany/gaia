"""Behavior tests for app.agents.middleware.runtime_adapter.

Locks: AgentState conversion (jump_to/structured_response passthrough),
ModelRequest construction (system-message extraction, tools/model/runtime
carried through), and the two runtime adapters' from_graph_context factories.
"""

from typing import Any
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.middleware.runtime_adapter import (
    BigtoolRuntime,
    BigtoolToolRuntime,
    create_model_request,
    to_agent_state,
)
from app.override.langgraph_bigtool.utils import State

SYSTEM = SystemMessage(content="You are GAIA.")
HUMAN = AIMessage(content="hello")


def _state(**extra: Any) -> State:
    fields: dict[str, Any] = {"messages": [SYSTEM, HUMAN], **extra}
    return State(**fields)


class TestToAgentState:
    def test_a_state_with_no_messages_channel_yet_reads_as_no_messages(self) -> None:
        assert to_agent_state(State()) == {"messages": []}

    def test_copies_messages(self) -> None:
        agent_state = to_agent_state(_state())
        assert agent_state["messages"] == [SYSTEM, HUMAN]

    def test_valid_jump_to_is_carried_through(self) -> None:
        for jump_to in ("tools", "model", "end"):
            agent_state = to_agent_state(_state(jump_to=jump_to))
            assert agent_state["jump_to"] == jump_to

    def test_invalid_jump_to_is_dropped(self) -> None:
        agent_state = to_agent_state(_state(jump_to="nope"))
        assert "jump_to" not in agent_state

    def test_structured_response_is_carried_through(self) -> None:
        agent_state = to_agent_state(_state(structured_response={"answer": 42}))
        assert agent_state["structured_response"] == {"answer": 42}


class TestCreateModelRequest:
    def test_system_message_is_extracted_from_messages(self) -> None:
        model = MagicMock()
        runtime = BigtoolRuntime.from_graph_context({"configurable": {}})
        request = create_model_request(model, _state(), runtime, [])

        assert request.system_message is SYSTEM
        assert request.messages == [HUMAN]
        assert request.model is model
        assert request.runtime is runtime
        assert request.tool_choice is None

    def test_explicit_system_message_wins_over_extracted(self) -> None:
        explicit = SystemMessage(content="Explicit.")
        model = MagicMock()
        runtime = BigtoolRuntime.from_graph_context({"configurable": {}})
        request = create_model_request(model, _state(), runtime, [], system_message=explicit)

        assert request.system_message is explicit
        assert request.messages == [HUMAN]

    def test_no_system_message_leaves_messages_untouched(self) -> None:
        state = _state(messages=[HUMAN])
        request = create_model_request(
            MagicMock(), state, BigtoolRuntime.from_graph_context({"configurable": {}}), []
        )

        assert request.system_message is None
        assert request.messages == [HUMAN]

    def test_tools_and_state_are_carried_through(self) -> None:
        tool = MagicMock()
        request = create_model_request(
            MagicMock(), _state(), BigtoolRuntime.from_graph_context({"configurable": {}}), [tool]
        )

        assert request.tools == [tool]
        assert request.state["messages"] == [SYSTEM, HUMAN]


class TestRuntimeFactories:
    def test_bigtool_runtime_preserves_graph_context(self) -> None:
        config: RunnableConfig = {"configurable": {"thread_id": "t1"}}
        store = MagicMock()
        writer = MagicMock()
        runtime = BigtoolRuntime.from_graph_context(config, store=store, stream_writer=writer)

        assert runtime.config == config
        assert runtime.store is store
        assert runtime.stream_writer is writer
        assert runtime.previous is None

    def test_bigtool_tool_runtime_preserves_tool_identity(self) -> None:
        config: RunnableConfig = {"configurable": {"thread_id": "t1"}}
        runtime = BigtoolToolRuntime.from_graph_context(
            config, tool_name="search", tool_call_id="call_1"
        )

        assert runtime.tool_name == "search"
        assert runtime.tool_call_id == "call_1"
        assert runtime.state == {}
        assert runtime.config == config

    def test_tool_runtime_defaults_state_to_empty_dict(self) -> None:
        runtime = BigtoolToolRuntime.from_graph_context({"configurable": {}})
        assert runtime.state == {}
        assert runtime.tool_name is None
