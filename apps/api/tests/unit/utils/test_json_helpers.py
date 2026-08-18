"""The typed bag accessors — the boundary this PR's foreign-JSON reads cross.

Each accessor promises: the value when it has the right type, the default on
absence AND on the wrong type, and never a raise. Wrong-type is asserted
beside absent everywhere because `bag.get(k, d)` — what these replaced —
only handles absent; silently passing a wrong-typed value through is the
regression these exist to prevent.
"""

import pytest

from app.utils.json_helpers import (
    bool_bag,
    dict_bag,
    float_bag,
    float_opt_bag,
    int_bag,
    int_opt_bag,
    int_str_bag,
    list_bag,
    text_bag,
    text_opt_bag,
)

BAG: dict[str, object] = {
    "obj": {"a": 1},
    "seq": [1, 2],
    "text": "hello",
    "num": 7,
    "real": 1.5,
    "flag": True,
    "millis": "1700000000000",
}


class TestPresentAndTyped:
    def test_each_accessor_returns_the_value_it_names(self) -> None:
        assert dict_bag(BAG, "obj") == {"a": 1}
        assert list_bag(BAG, "seq") == [1, 2]
        assert text_bag(BAG, "text") == "hello"
        assert text_opt_bag(BAG, "text") == "hello"
        assert int_bag(BAG, "num") == 7
        assert int_opt_bag(BAG, "num") == 7
        assert float_bag(BAG, "real") == 1.5
        assert float_opt_bag(BAG, "real") == 1.5
        assert bool_bag(BAG, "flag") is True
        assert int_str_bag(BAG, "millis") == 1700000000000

    def test_floats_accept_ints_because_json_does(self) -> None:
        assert float_bag(BAG, "num") == 7.0
        assert float_opt_bag(BAG, "num") == 7.0

    def test_int_str_bag_accepts_a_real_int_unchanged(self) -> None:
        assert int_str_bag(BAG, "num") == 7


@pytest.mark.parametrize("key", ["missing", "text"])
class TestAbsentOrWrongType:
    """'text' stands in for wrong-typed for every non-str accessor; str
    accessors use 'num' instead."""

    def test_container_accessors_default_to_empty(self, key: str) -> None:
        assert dict_bag(BAG, key) == {}
        assert list_bag(BAG, key) == []

    def test_numeric_accessors_take_their_defaults(self, key: str) -> None:
        assert int_bag(BAG, key) == 0
        assert int_bag(BAG, key, default=9) == 9
        assert int_opt_bag(BAG, key) is None
        assert float_bag(BAG, key) == 0.0
        assert float_bag(BAG, key, default=2.5) == 2.5
        assert float_opt_bag(BAG, key) is None
        assert bool_bag(BAG, key) is False
        assert bool_bag(BAG, key, default=True) is True


class TestStringAccessors:
    def test_wrong_type_and_absent_take_the_default(self) -> None:
        assert text_bag(BAG, "num") == ""
        assert text_bag(BAG, "num", default="d") == "d"
        assert text_bag(BAG, "missing") == ""
        assert text_opt_bag(BAG, "num") is None
        assert text_opt_bag(BAG, "missing") is None

    def test_empty_string_is_a_value_not_an_absence(self) -> None:
        bag: dict[str, object] = {"text": ""}
        assert text_bag(bag, "text", default="d") == ""
        assert text_opt_bag(bag, "text") == ""


class TestIntStrBag:
    def test_a_non_numeric_string_takes_the_default(self) -> None:
        assert int_str_bag({"v": "12a"}, "v") == 0
        assert int_str_bag({"v": "12a"}, "v", default=5) == 5

    def test_absent_and_wrong_type_take_the_default(self) -> None:
        assert int_str_bag({}, "v", default=3) == 3
        assert int_str_bag({"v": [1]}, "v", default=3) == 3

    def test_a_negative_numeric_string_converts(self) -> None:
        assert int_str_bag({"v": "-42"}, "v") == -42


class TestBoolIsNotInt:
    """bool is an int subclass; these accessors must not conflate them."""

    def test_int_accessors_accept_bool_as_python_does(self) -> None:
        # Documented behaviour: isinstance(True, int) is True, so int_bag
        # passes a bool through. Callers needing strict ints must not feed
        # bool-carrying keys here.
        assert int_bag({"v": True}, "v") == 1

    def test_bool_bag_rejects_plain_ints(self) -> None:
        assert bool_bag({"v": 1}, "v") is False
        assert bool_bag({"v": 0}, "v", default=True) is True
