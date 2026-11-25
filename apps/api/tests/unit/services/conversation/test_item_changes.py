"""The changes between two JSON values, and their application, as the conversation stream's patches use them."""

import json

from hypothesis import given, strategies as st
from pydantic import JsonValue
import pytest

from app.services.conversation.item_changes import changes_between
from shared.py.conversation_wire import ChangeOp, ItemChange
from tests.unit.services.conversation.change_helpers import ChangeNotApplicable, with_changes

pytestmark = pytest.mark.unit

_SCALARS = st.one_of(
    st.none(), st.booleans(), st.integers(-3, 3), st.text("ab", max_size=4), st.just(1.5)
)
_JSON: st.SearchStrategy[JsonValue] = st.recursive(
    _SCALARS,
    lambda inner: st.one_of(
        st.lists(inner, max_size=4), st.dictionaries(st.text("xyz", max_size=2), inner, max_size=4)
    ),
    max_leaves=12,
)


@given(before=_JSON, after=_JSON)
def test_applying_the_changes_between_two_values_gives_the_second(
    before: JsonValue, after: JsonValue
) -> None:
    changed = with_changes(before, changes_between(before, after))
    # 1 == True in Python, so the JSON text is compared: it must match in type too.
    assert json.dumps(changed, sort_keys=True) == json.dumps(after, sort_keys=True)


@given(value=_JSON)
def test_a_value_that_did_not_change_has_no_changes(value: JsonValue) -> None:
    assert changes_between(value, value) == []


def _timeline(outputs: int, calls: int = 3) -> JsonValue:
    return {
        "steps": [
            {"key": f"tc-{i}", "data": {"id": i} | ({"output": "x" * 50} if i < outputs else {})}
            for i in range(calls)
        ]
    }


def test_an_output_landing_on_one_call_is_sent_as_that_output_alone() -> None:
    assert changes_between(_timeline(1), _timeline(2)) == [
        ItemChange(op=ChangeOp.SET, path=("steps", 1, "data", "output"), value="x" * 50)
    ]


def test_a_new_last_element_is_set_at_the_index_past_the_end() -> None:
    assert changes_between([1], [1, {"a": 2}]) == [
        ItemChange(op=ChangeOp.SET, path=(1,), value={"a": 2})
    ]


def test_text_that_grew_is_sent_as_what_was_added() -> None:
    assert changes_between({"reasoning": "think"}, {"reasoning": "thinking"}) == [
        ItemChange(op=ChangeOp.APPEND, path=("reasoning",), value="ing")
    ]


def test_text_that_grew_from_empty_is_set_whole() -> None:
    assert changes_between("", "text") == [ItemChange(op=ChangeOp.SET, path=(), value="text")]


def test_a_shorter_list_drops_its_last_elements_from_the_end() -> None:
    assert changes_between([1, 2, 3], [1]) == [
        ItemChange(op=ChangeOp.REMOVE, path=(2,)),
        ItemChange(op=ChangeOp.REMOVE, path=(1,)),
    ]


def test_true_becoming_one_is_a_change() -> None:
    assert changes_between({"n": True}, {"n": 1}) == [
        ItemChange(op=ChangeOp.SET, path=("n",), value=1)
    ]


def test_a_changed_path_is_copied_and_everything_off_it_is_shared() -> None:
    held: JsonValue = {"steps": [{"data": {"id": 0}}, {"data": {"id": 1}}], "other": {"k": 1}}
    change = ItemChange(op=ChangeOp.SET, path=("steps", 1, "data", "output"), value="out")
    changed = with_changes(held, [change])
    assert isinstance(held, dict) and isinstance(changed, dict)
    assert held["steps"] == [{"data": {"id": 0}}, {"data": {"id": 1}}]
    assert changed["other"] is held["other"]
    assert isinstance(changed["steps"], list) and isinstance(held["steps"], list)
    assert changed["steps"][0] is held["steps"][0]
    assert changed["steps"][1] == {"data": {"id": 1, "output": "out"}}


@pytest.mark.parametrize(
    "change",
    [
        ItemChange(op=ChangeOp.SET, path=("steps", 5, "data"), value=1),
        ItemChange(op=ChangeOp.SET, path=("steps", 3), value=1),
        ItemChange(op=ChangeOp.SET, path=("missing", "key"), value=1),
        ItemChange(op=ChangeOp.APPEND, path=("steps",), value="x"),
        ItemChange(op=ChangeOp.APPEND, path=("missing",), value="x"),
        ItemChange(op=ChangeOp.REMOVE, path=("steps", 0)),
        ItemChange(op=ChangeOp.SET, path=("steps", "key"), value=1),
        ItemChange(op=ChangeOp.REMOVE, path=()),
    ],
)
def test_a_change_the_held_value_has_no_place_for_is_refused(change: ItemChange) -> None:
    with pytest.raises(ChangeNotApplicable):
        with_changes({"steps": [{"data": 0}, {"data": 1}]}, [change])
