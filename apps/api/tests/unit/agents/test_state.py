import pytest
from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages

from app.agents.core.state import State as CoreState
from app.override.langgraph_bigtool.utils import State


@pytest.mark.unit
class TestState:
    """Tests for the override State used by the compiled agent graph.

    State inherits from langgraph_bigtool.graph.State (which extends
    langgraph.graph.MessagesState) and adds a `todos` channel. It is a
    TypedDict with exactly three fields: messages, selected_tool_ids, todos.
    """

    def test_default_values(self):
        state = State(messages=[], selected_tool_ids=[], todos=[])
        assert state["messages"] == []
        assert state["selected_tool_ids"] == []
        assert state["todos"] == []

    def test_with_messages(self):
        msgs = [HumanMessage(content="hello")]
        state = State(messages=msgs, selected_tool_ids=[], todos=[])
        assert len(state["messages"]) == 1
        assert state["messages"][0].content == "hello"

    def test_custom_values(self):
        msgs = [HumanMessage(content="hi")]
        state = State(
            messages=msgs,
            selected_tool_ids=["tool-a", "tool-b"],
            todos=["do something"],
        )
        assert state["selected_tool_ids"] == ["tool-a", "tool-b"]
        assert state["todos"] == ["do something"]

    def test_messages_reducer_accumulates(self):
        # messages uses the add_messages reducer — verify it accumulates across
        # two separate state snapshots rather than replacing.
        state1 = State(
            messages=[HumanMessage(content="hello")],
            selected_tool_ids=[],
            todos=[],
        )
        state2 = State(
            messages=[HumanMessage(content="world")],
            selected_tool_ids=[],
            todos=[],
        )
        combined = add_messages(state1["messages"], state2["messages"])
        assert len(combined) == 2
        assert combined[0].content == "hello"
        assert combined[1].content == "world"

    def test_todos_reducer_last_write_wins(self):
        # todos uses _replace_todos (last-write-wins) — the right list replaces left.
        from app.override.langgraph_bigtool.utils import _replace_todos

        left = ["task-1", "task-2"]
        right = ["task-3"]
        assert _replace_todos(left, right) == ["task-3"]


@pytest.mark.unit
class TestCoreState:
    """Tests for app.agents.core.state.State.

    This is a separate Pydantic/DictLikeModel-based State used outside the
    compiled bigtool graph (e.g. legacy code paths, memory nodes). It is NOT
    the State that create_agent() compiles into the StateGraph.
    """

    def test_default_values(self):
        state = CoreState()
        assert state.query == ""
        assert state.messages == []
        assert state.current_datetime is None
        assert state.mem0_user_id is None
        assert state.memories == []
        assert state.memories_stored is False
        assert state.conversation_id is None

    def test_dict_access(self):
        state = CoreState(query="test query")
        assert state["query"] == "test query"

    def test_dict_delete(self):
        state = CoreState(query="to delete")
        del state["query"]
        assert not hasattr(state, "query")

    def test_with_messages(self):
        msgs = [HumanMessage(content="hello")]
        state = CoreState(messages=msgs)
        assert len(state.messages) == 1
        assert state.messages[0].content == "hello"

    def test_custom_values(self):
        state = CoreState(
            query="what time is it",
            current_datetime="2026-03-03T12:00:00",
            mem0_user_id="user-123",
            memories=["likes python"],
            memories_stored=True,
            conversation_id="conv-456",
        )
        assert state.query == "what time is it"
        assert state.current_datetime == "2026-03-03T12:00:00"
        assert state.mem0_user_id == "user-123"
        assert state.memories == ["likes python"]
        assert state.memories_stored is True
        assert state.conversation_id == "conv-456"
