import pytest
from langchain_core.messages import HumanMessage

from app.agents.core.state import DictLikeModel, State


@pytest.mark.unit
class TestState:
    def test_default_values(self):
        state = State()
        assert state.query == ""
        assert state.messages == []
        assert state.current_datetime is None
        assert state.mem0_user_id is None
        assert state.memories == []
        assert state.memories_stored is False
        assert state.conversation_id is None

    def test_dict_access(self):
        state = State(query="test query")
        assert state["query"] == "test query"

    def test_dict_set(self):
        state = State()
        state["query"] = "updated"
        assert state.query == "updated"
        assert state["query"] == "updated"

    def test_dict_delete(self):
        state = State(query="to delete")
        del state["query"]
        assert not hasattr(state, "query")

    def test_with_messages(self):
        msgs = [HumanMessage(content="hello")]
        state = State(messages=msgs)
        assert len(state.messages) == 1
        assert state.messages[0].content == "hello"

    def test_custom_values(self):
        state = State(
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


@pytest.mark.unit
class TestDictLikeModel:
    def test_len(self):
        state = State()
        assert len(state) > 0
        assert len(state) == len(state.__dict__)
