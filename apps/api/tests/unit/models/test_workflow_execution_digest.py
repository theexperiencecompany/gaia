"""The recorded result digest: bounded without lying about what came back."""

import json

import pytest

from app.models.workflow_execution_models import (
    RECORD_CUT_MARKER,
    _bounded_json,
    _fit_elements,
    _largest_sequence,
    _trim_strings,
    build_result_digest,
    largest_list_len,
)

pytestmark = pytest.mark.unit


class TestADigestNeverShedsAListToNothing:
    def test_one_oversized_element_is_cut_harder_rather_than_dropped(self) -> None:
        """Five wide messages under a 1.2 KB bound used to come out as
        ``{"data":{"messages":[]}}``: the first element did not fit even after
        the first string trim, so every element was shed and a full result was
        recorded as an empty one, which the empty-result checks then believed."""
        wide = {"id": "m1", **{f"field_{n}": "x" * 9_000 for n in range(8)}}
        huge = {"data": {"messages": [wide] * 5}}

        digest = build_result_digest(json.dumps(huge), max_chars=1_200)

        assert len(digest) <= 1_200
        assert largest_list_len(json.loads(digest)) >= 1

    def test_a_result_that_fits_is_recorded_whole(self) -> None:
        small = {"data": {"messages": [{"id": "m1"}, {"id": "m2"}]}}

        assert json.loads(build_result_digest(json.dumps(small), max_chars=1_200)) == small


class TestTheBoundIsInclusive:
    """Every ``<=`` here decides what a result exactly at its limit becomes. Off by
    one and a result that fits is re-serialised, re-trimmed, or marked as cut —
    which is a digest that says the tool returned something it did not."""

    def test_a_non_string_result_is_rendered_from_the_value_itself(self) -> None:
        assert build_result_digest({"count": 2}) == "{'count': 2}"

    def test_a_json_result_exactly_at_the_bound_is_kept_as_written(self) -> None:
        # Re-serialising would drop the spaces and hand back a different document.
        assert build_result_digest('{"a": 1}', max_chars=8) == '{"a": 1}'

    def test_a_string_exactly_at_the_trim_limit_keeps_all_of_itself(self) -> None:
        assert _trim_strings("abcde", 5) == "abcde"
        assert _trim_strings("abcdef", 5) == "abcde" + RECORD_CUT_MARKER

    def test_an_element_that_lands_exactly_on_the_bound_is_kept(self) -> None:
        assert _fit_elements([1, 2], lambda items: items, len("[1,2]")) == "[1,2]"
        assert _fit_elements([1, 2], lambda items: items, len("[1,2]") - 1) == "[1]"

    def test_a_value_exactly_at_the_bound_is_not_trimmed_at_all(self) -> None:
        whole = '{"a":"' + "x" * 300 + '"}'
        assert _bounded_json({"a": "x" * 300}, len(whole)) == whole

    def test_a_trimmed_value_exactly_at_the_bound_is_not_trimmed_again(self) -> None:
        # The cut marker is escaped by the compact encoder, so it costs six
        # characters inside the JSON string, not one.
        trimmed = '{"a":"' + "x" * 200 + '\\u2026[cut]"}'
        assert _bounded_json({"a": "x" * 300}, len(trimmed)) == trimmed


class TestTheStringLimitLaddersDownToZero:
    def test_the_last_rung_cuts_strings_away_entirely_before_slicing_as_text(
        self,
    ) -> None:
        """A dict of short values can never be shed (no list) and never fits, so the
        ladder runs to its end. Stopping a rung early records the one-character
        prefixes instead of the fully cut ones."""
        assert _bounded_json({"a": "PQ", "b": "RS"}, 10) == '{"a":"\\u20'

    def test_the_limit_halves_rather_than_stepping_by_any_other_ratio(self) -> None:
        # 50 chars fits at limit 12 but not at 25 — a different ratio lands on a
        # different rung and records a shorter value than the bound allows.
        assert _bounded_json({"a": "x" * 50}, 35) == '{"a":"' + "x" * 12 + '\\u2026[cut]"}'


class TestTheSheddableListIsChosenOnce:
    def test_a_value_with_no_list_hands_back_a_rebuild_that_is_still_usable(
        self,
    ) -> None:
        items, rebuild = _largest_sequence({"a": 1})

        assert items is None
        assert rebuild(["kept"]) == ["kept"]

    def test_the_first_of_two_equally_large_lists_wins(self) -> None:
        items, rebuild = _largest_sequence({"a": [1, 2], "b": [3, 4]})

        assert items == [1, 2]
        assert rebuild([9]) == {"a": [9], "b": [3, 4]}
