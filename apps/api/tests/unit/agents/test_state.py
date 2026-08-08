from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
import pytest

from app.override.langgraph_bigtool.utils import State, messages_delta_reducer


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
class TestMessagesDeltaReducer:
    """Tests for the messages channel reducer.

    ``SummarizationMiddleware`` clears history by writing a ``RemoveMessage``
    carrying the ``REMOVE_ALL_MESSAGES`` sentinel. LangGraph's stock
    ``_messages_delta_reducer`` documents that it does NOT implement that
    sentinel, so it would silently pass the tombstone through as a message —
    the exact object that crashed the Gemini serializer in production
    ("Unexpected message with type RemoveMessage at the position 0").
    """

    def test_ordinary_writes_accumulate(self):
        state = [HumanMessage(content="hello", id="h1")]
        result = messages_delta_reducer(state, [[AIMessage(content="hi", id="a1")]])

        assert [m.id for m in result] == ["h1", "a1"]

    def test_remove_all_sentinel_clears_history_and_is_consumed(self):
        state = [
            HumanMessage(content="old 1", id="h1"),
            AIMessage(content="old 2", id="a1"),
        ]

        result = messages_delta_reducer(
            state,
            [
                [
                    RemoveMessage(id=REMOVE_ALL_MESSAGES),
                    HumanMessage(content="summary", id="s1"),
                    AIMessage(content="kept", id="a2"),
                ]
            ],
        )

        assert not any(isinstance(m, RemoveMessage) for m in result), (
            "the REMOVE_ALL_MESSAGES tombstone must be consumed, never passed through"
        )
        assert [m.id for m in result] == ["s1", "a2"]

    def test_remove_all_sentinel_is_batching_invariant(self):
        """DeltaChannel replays writes in arbitrary batch sizes and requires
        ``reducer(reducer(s, xs), ys) == reducer(s, xs + ys)``. A REMOVE_ALL
        write that is not applied in stream order breaks that invariant, and the
        channel then reconstructs a different history on replay than it had live.
        """
        state = [HumanMessage(content="old", id="h1")]
        xs = [[RemoveMessage(id=REMOVE_ALL_MESSAGES), HumanMessage(content="summary", id="s1")]]
        ys = [[AIMessage(content="new", id="a1")]]

        split = messages_delta_reducer(messages_delta_reducer(state, xs), ys)
        batched = messages_delta_reducer(state, xs + ys)

        assert [m.id for m in split] == [m.id for m in batched] == ["s1", "a1"]

    def test_targeted_remove_message_still_tombstones_one_message(self):
        state = [
            HumanMessage(content="keep", id="h1"),
            AIMessage(content="drop", id="a1"),
        ]

        result = messages_delta_reducer(state, [[RemoveMessage(id="a1")]])

        assert [m.id for m in result] == ["h1"]
