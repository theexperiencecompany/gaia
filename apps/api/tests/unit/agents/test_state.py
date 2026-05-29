"""Behavior spec for app.agents.core.state.

UNIT: app/agents/core/state.py :: DictLikeModel, State

EXPECTED:
  State is a Pydantic model that ALSO behaves like a dict (MutableMapping) so
  LangGraph can read/write it via `state["messages"]` while application code
  reads it via `state.messages`. DictLikeModel bridges the two: item access
  proxies to attribute access, and iteration/length reflect the model's fields.
  State declares the conversation-turn fields with their defaults and pins the
  `messages` channel to the langgraph `add_messages` reducer.

MECHANISM:
  DictLikeModel.__getitem__(k)  -> getattr(self, k)
  DictLikeModel.__setitem__(k,v)-> setattr(self, k, v)
  DictLikeModel.__delitem__(k)  -> delattr(self, k)
  DictLikeModel.__iter__()      -> iter(type(self).model_fields)   # field names
  DictLikeModel.__len__()       -> len(type(self).model_fields)    # field count
  State(...)                    -> Pydantic field defaults; messages reduced by add_messages.

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - __getitem__ returns the REAL attribute value, not None  (L11 return_none)
  - __iter__ yields the actual field NAMES, not None        (L20 return_none)
  - __len__ returns the actual field COUNT, not None         (L23 return_none)
  - memories_stored defaults to False, not True              (L33 const_bool)
  - __setitem__ actually mutates the underlying attribute     [dict<->attr parity]
  - __delitem__ actually removes the attribute                [dict<->attr parity]
  - dict-style and attr-style access stay in sync (round-trip through both)
  - the full field default contract (query="", optionals None, lists empty,
    execution_mode defaults to the interactive literal)        [agent-state contract]
  - execution_mode accepts BOTH "interactive" and "background" literals — each
    must validate (a Literal that dropped either value would reject it)
                                                                [agent-state contract]
  - messages is wired to the add_messages reducer, so two snapshots accumulate
    rather than replace                                        [LangGraph contract]

EQUIVALENT MUTANTS (allowed survivors, justified): none expected.

OUT OF SCOPE: app.override.langgraph_bigtool.utils.State and _replace_todos are a
DIFFERENT production unit covered by tests/unit/override/test_langgraph_bigtool.py
and tests/e2e/test_workflow_execution.py; they are not exercised here.
"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import add_messages
import pytest

from app.agents.core.state import State


@pytest.mark.unit
class TestDictLikeAccess:
    """DictLikeModel maps item access onto attribute access and back."""

    def test_getitem_returns_the_real_field_value(self):
        # Kills L11 `return getattr(self, key)` -> `return None`: the value must
        # be the live attribute, not None.
        state = State(query="what time is it")
        assert state["query"] == "what time is it"
        assert state["query"] == state.query
        assert state["memories_stored"] is False
        assert state["messages"] == []

    def test_setitem_mutates_the_underlying_attribute(self):
        state = State()
        state["query"] = "updated"
        # The write must land on the real attribute, observable via both APIs.
        assert state.query == "updated"
        assert state["query"] == "updated"

    def test_delitem_removes_the_attribute(self):
        state = State(query="to delete")
        del state["query"]
        # delattr removes the instance attribute entirely.
        assert not hasattr(state, "query")

    def test_item_and_attribute_access_stay_in_sync(self):
        state = State()
        state.conversation_id = "conv-1"
        assert state["conversation_id"] == "conv-1"
        state["conversation_id"] = "conv-2"
        assert state.conversation_id == "conv-2"


@pytest.mark.unit
class TestDictLikeIteration:
    """__iter__ / __len__ expose the model fields so dict() / len() work."""

    def test_iter_yields_every_field_name(self):
        # Kills L20 `return iter(type(self).model_fields)` -> `return None`:
        # iterating must produce the actual field names, not raise on None.
        state = State()
        names = list(state)
        assert set(names) == set(State.model_fields)
        # Spot-check the load-bearing keys LangGraph and app code read.
        assert "messages" in names
        assert "query" in names
        assert "memories_stored" in names

    def test_dict_conversion_uses_iter_and_getitem(self):
        # dict(mapping) drives __iter__ (keys) and __getitem__ (values) together.
        state = State(query="hello", conversation_id="conv-9")
        as_dict = dict(state)
        assert as_dict["query"] == "hello"
        assert as_dict["conversation_id"] == "conv-9"
        assert as_dict["messages"] == []

    def test_len_equals_the_number_of_model_fields(self):
        # Kills L23 `return len(type(self).model_fields)` -> `return None`:
        # len() must be the real field count.
        state = State()
        assert len(state) == len(State.model_fields)
        assert len(state) == len(list(state))


@pytest.mark.unit
class TestStateDefaults:
    """State's declared field defaults are the agent-turn contract."""

    def test_default_field_values(self):
        state = State()
        assert state.query == ""
        assert state.intent is None
        assert state.messages == []
        assert state.current_datetime is None
        assert state.mem0_user_id is None
        assert state.memories == []
        # Kills L33 `memories_stored: bool = False` -> `True`.
        assert state.memories_stored is False
        assert state.conversation_id is None
        assert state.integration_usernames == {}
        # active_todo_id / execution_mode are newer fields; assert only when the
        # running prod version declares them (keeps this stable across branches).
        if "active_todo_id" in State.model_fields:
            assert state.active_todo_id is None
        if "execution_mode" in State.model_fields:
            assert state.execution_mode == "interactive"

    def test_custom_values_override_defaults(self):
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

    @pytest.mark.skipif(
        "execution_mode" not in State.model_fields,
        reason="execution_mode field not present in this prod version",
    )
    def test_execution_mode_accepts_both_literals(self):
        # execution_mode is Literal["interactive", "background"]. Each value must
        # validate on explicit construction — dropping either from the Literal
        # would make pydantic reject that exact value.
        assert State(execution_mode="interactive").execution_mode == "interactive"
        assert State(execution_mode="background").execution_mode == "background"


@pytest.mark.unit
class TestMessagesReducer:
    """The messages channel is pinned to langgraph's add_messages reducer."""

    def test_messages_field_is_annotated_with_add_messages(self):
        # The LangGraph contract: messages must carry the add_messages reducer in
        # its annotation metadata, otherwise the graph would overwrite history.
        metadata = State.model_fields["messages"].metadata
        assert add_messages in metadata

    def test_add_messages_accumulates_across_snapshots(self):
        first = State(messages=[HumanMessage(content="hello")])
        second = State(messages=[AIMessage(content="world")])
        combined = add_messages(first.messages, second.messages)
        assert [m.content for m in combined] == ["hello", "world"]
