"""Behavior tests for app.agents.middleware.runtime_adapter.

Locks: AgentState conversion (jump_to/structured_response passthrough),
ModelRequest construction (system-message extraction, tools/model/runtime
carried through), ToolCallRequest construction from a raw tool-call dict, and
the two runtime adapters' from_graph_context factories.
"""

from typing import Any
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, SystemMessage

from app.agents.middleware.runtime_adapter import (
    BigtoolRuntime,
    BigtoolToolRuntime,
    create_model_request,
    create_tool_call_request,
    to_agent_state,
)

SYSTEM = SystemMessage(content="You are GAIA.")
HUMAN = AIMessage(content="hello")


def _state(**extra: Any) -> dict[str, Any]:
    return {"messages": [SYSTEM, HUMAN], **extra}


class TestToAgentState:
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
        state = {"messages": [HUMAN]}
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


class TestCreateToolCallRequest:
    def test_raw_dict_is_converted_to_a_tool_call(self) -> None:
        tool = MagicMock()
        runtime = BigtoolToolRuntime.from_graph_context({"configurable": {}}, tool_name="my_tool")
        request = create_tool_call_request(
            {"name": "my_tool", "args": {"x": 1}, "id": "call_9"}, tool, _state(), runtime
        )

        assert request.tool_call == {"name": "my_tool", "args": {"x": 1}, "id": "call_9"}
        assert request.tool is tool
        assert request.runtime is runtime
        assert request.state["messages"] == [SYSTEM, HUMAN]

    def test_missing_id_and_args_default(self) -> None:
        runtime = BigtoolToolRuntime.from_graph_context({"configurable": {}})
        request = create_tool_call_request({"name": "bare"}, None, _state(), runtime)

        assert request.tool_call["id"] is None
        assert request.tool_call["args"] == {}


class TestRuntimeFactories:
    def test_bigtool_runtime_preserves_graph_context(self) -> None:
        config = {"configurable": {"thread_id": "t1"}}
        store = MagicMock()
        writer = MagicMock()
        runtime = BigtoolRuntime.from_graph_context(config, store=store, stream_writer=writer)

        assert runtime.config == config
        assert runtime.store is store
        assert runtime.stream_writer is writer
        assert runtime.previous is None

    def test_bigtool_tool_runtime_preserves_tool_identity(self) -> None:
        config = {"configurable": {"thread_id": "t1"}}
        runtime = BigtoolToolRuntime.from_graph_context(
            config, tool_name="search", tool_call_id="call_1", state={"messages": []}
        )

        assert runtime.tool_name == "search"
        assert runtime.tool_call_id == "call_1"
        assert runtime.state == {"messages": []}
        assert runtime.config == config

    def test_tool_runtime_defaults_state_to_empty_dict(self) -> None:
        runtime = BigtoolToolRuntime.from_graph_context({"configurable": {}})
        assert runtime.state == {}
        assert runtime.tool_name is None
