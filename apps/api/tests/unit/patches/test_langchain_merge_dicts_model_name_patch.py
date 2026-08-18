"""Tests for the merge_dicts model_name idempotency patch.

``AIMessageChunk.__add__`` merges chunk ``response_metadata`` via
``langchain_core.utils._merge.merge_dicts``, which concatenates equal string
values for any key outside its small idempotent set (id/output_version/
model_provider). ChatOpenRouter can stamp ``model_name`` on more than one
chunk of the same stream, so two equal model names get concatenated into a
name matching no pricing entry ("modelmodel"). The patch adds "model_name" to
the idempotent set.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from langchain_core.messages import AIMessageChunk
from langchain_core.utils import _merge as merge_module
import pytest

# Importing the patch module rebinds merge_dicts at import time.
import app.patches.langchain_merge_dicts_model_name_patch as patch_module


def _load_pristine_upstream() -> Any:
    """Load ``langchain_core.utils._merge`` straight off disk, unpatched.

    ``apply()`` has already rebound the installed module's ``merge_dicts``, so
    the only way to reach the original is to execute the source file into a
    fresh module object. This is what makes the parity suite below a real
    differential test rather than a re-statement of our own copy.
    """
    spec = importlib.util.spec_from_file_location("_upstream_merge", merge_module.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


upstream = _load_pristine_upstream()

#: Merge inputs that exercise every branch of ``merge_dicts`` and involve no
#: identity key, so the patch must leave every one of them alone.
NON_IDENTITY_CASES: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("key present only on the right", {"a": 1}, {"b": "x"}),
    ("left value is None", {"a": None}, {"a": "x"}),
    ("right value is None", {"a": "x"}, {"a": None}),
    (
        "a None value does not stop the keys after it",
        {"a": "x", "b": "y"},
        {"a": None, "b": "z"},
    ),
    ("both values None", {"a": None}, {"a": None}),
    ("ordinary strings concatenate", {"finish_reason": "stop"}, {"finish_reason": "stop"}),
    ("lc_-prefixed index is idempotent", {"index": "lc_1"}, {"index": "lc_1"}),
    ("plain index string concatenates", {"index": "0"}, {"index": "1"}),
    ("nested dicts merge recursively", {"m": {"n": 1}}, {"m": {"n": 2}}),
    (
        "lists merge by index",
        {"c": [{"index": 0, "text": "a"}]},
        {"c": [{"index": 0, "text": "b"}]},
    ),
    ("equal non-string scalars stay single", {"f": True}, {"f": True}),
    ("token counters add", {"tokens": 3}, {"tokens": 4}),
    ("index int is replaced", {"index": 3}, {"index": 7}),
    ("created int is replaced", {"created": 100}, {"created": 200}),
    ("timestamp int is replaced", {"timestamp": 100}, {"timestamp": 200}),
]

#: Inputs both implementations must reject, and with the same error.
REJECTED_CASES: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("str against int", {"a": "x"}, {"a": 1}),
    ("bool against int", {"a": True}, {"a": 1}),
    ("two unequal floats", {"a": 1.5}, {"a": 2.5}),
]


class TestMergeDicts:
    def test_equal_model_name_values_are_not_concatenated(self) -> None:
        merged = patch_module.merge_dicts(
            {"model_name": "deepseek/deepseek-v4-flash-0731"},
            {"model_name": "deepseek/deepseek-v4-flash-0731"},
        )
        assert merged["model_name"] == "deepseek/deepseek-v4-flash-0731"

    def test_differing_model_name_values_still_concatenate(self) -> None:
        # Unchanged from upstream: idempotency only applies when both sides agree.
        merged = patch_module.merge_dicts({"model_name": "a"}, {"model_name": "b"})
        assert merged["model_name"] == "ab"

    def test_id_output_version_model_provider_stay_idempotent(self) -> None:
        merged = patch_module.merge_dicts(
            {"id": "run-1", "output_version": "v0", "model_provider": "openrouter"},
            {"id": "run-1", "output_version": "v0", "model_provider": "openrouter"},
        )
        assert merged == {"id": "run-1", "output_version": "v0", "model_provider": "openrouter"}

    def test_other_string_keys_still_concatenate(self) -> None:
        # finish_reason (and any other ordinary string field) keeps the original
        # concatenation behavior -- only the named identity fields are idempotent.
        merged = patch_module.merge_dicts({"finish_reason": "stop"}, {"finish_reason": "stop"})
        assert merged["finish_reason"] == "stopstop"


class TestAIMessageChunkMerge:
    def test_two_chunks_stamping_the_same_model_name_merge_to_one_name(self) -> None:
        # The real bug shape: ChatOpenRouter stamps response_metadata["model_name"]
        # on more than one chunk of a stream; AIMessageChunk.__add__ must not turn
        # that into a doubled pricing key.
        first = AIMessageChunk(
            content="",
            response_metadata={"model_name": "deepseek/deepseek-v4-flash-0731"},
        )
        second = AIMessageChunk(
            content="",
            response_metadata={"model_name": "deepseek/deepseek-v4-flash-0731"},
        )
        merged = first + second
        assert merged.response_metadata["model_name"] == "deepseek/deepseek-v4-flash-0731"

    def test_the_model_name_stays_a_valid_pricing_key_across_a_whole_stream(self) -> None:
        # Two chunks was the reported shape, but nothing caps it at two, and the
        # consequence scales: every extra stamp appends another copy, and any
        # doubled id misses the pricing catalog and bills at DEFAULT_PRICING.
        model = "deepseek/deepseek-v4-flash-0731"
        chunks = [
            AIMessageChunk(content="", response_metadata={"model_name": model}) for _ in range(5)
        ]

        merged = chunks[0]
        for chunk in chunks[1:]:
            merged = merged + chunk

        assert merged.response_metadata["model_name"] == model


class TestApply:
    def test_merge_module_is_rebound_to_the_wrapper(self) -> None:
        from langchain_core.utils import _merge

        assert _merge.merge_dicts is patch_module.merge_dicts

    def test_messages_ai_module_is_rebound_to_the_wrapper(self) -> None:
        from langchain_core.messages import ai

        assert ai.merge_dicts is patch_module.merge_dicts

    def test_apply_keeps_the_rebinding(self) -> None:
        patch_module.apply()

        from langchain_core.messages import ai

        assert ai.merge_dicts is patch_module.merge_dicts

    def test_apply_is_idempotent_and_rebinds_the_defining_module_too(self) -> None:
        # `_merge` is where every not-yet-imported consumer will look the name
        # up, so it is the one target the rebind-targets tuple does not cover
        # and the only one no other test re-checks after apply() runs.
        patch_module.apply()
        patch_module.apply()

        assert merge_module.merge_dicts is patch_module.merge_dicts
        assert [m.merge_dicts for m in patch_module._REBIND_TARGETS] == [
            patch_module.merge_dicts
        ] * len(patch_module._REBIND_TARGETS)


class TestUpstreamParity:
    """The patch is a verbatim copy of upstream plus one entry in the idempotent
    set. Anything else that diverges is drift — either an editing slip in the
    copy, or an upstream change the copy has not tracked."""

    @pytest.mark.parametrize(
        ("left", "right"),
        [pytest.param(left, right, id=name) for name, left, right in NON_IDENTITY_CASES],
    )
    def test_matches_upstream_on_every_non_identity_merge(
        self, left: dict[str, Any], right: dict[str, Any]
    ) -> None:
        assert patch_module.merge_dicts(left, right) == upstream.merge_dicts(left, right)

    @pytest.mark.parametrize(
        ("left", "right"),
        [pytest.param(left, right, id=name) for name, left, right in REJECTED_CASES],
    )
    def test_rejects_exactly_what_upstream_rejects(
        self, left: dict[str, Any], right: dict[str, Any]
    ) -> None:
        with pytest.raises(TypeError) as ours:
            patch_module.merge_dicts(left, right)
        with pytest.raises(TypeError) as theirs:
            upstream.merge_dicts(left, right)
        assert str(ours.value) == str(theirs.value)

    def test_model_name_is_the_one_deliberate_divergence(self) -> None:
        left = {"model_name": "deepseek/deepseek-v4-flash-0731"}

        assert upstream.merge_dicts(left, left) == {
            "model_name": "deepseek/deepseek-v4-flash-0731deepseek/deepseek-v4-flash-0731"
        }
        assert patch_module.merge_dicts(left, left) == left


class TestMergeBranches:
    """Concrete behaviour per branch, so a parity failure points somewhere."""

    def test_key_present_only_on_the_right_is_adopted(self) -> None:
        assert patch_module.merge_dicts({"a": 1}, {"b": "x"}) == {"a": 1, "b": "x"}

    def test_a_none_on_the_left_is_replaced_by_the_right_value(self) -> None:
        assert patch_module.merge_dicts({"a": None}, {"a": "x"}) == {"a": "x"}

    def test_a_none_on_the_right_never_clobbers_the_left_value(self) -> None:
        assert patch_module.merge_dicts({"a": "x"}, {"a": None}) == {"a": "x"}

    def test_a_none_value_skips_only_its_own_key_not_the_rest_of_the_dict(self) -> None:
        # A chunk's response_metadata routinely carries a None alongside real
        # values (finish_reason arrives before usage does). Abandoning the whole
        # right-hand dict at the first None would drop every field after it.
        merged = patch_module.merge_dicts(
            {"finish_reason": "stop", "model_name": "openrouter/x", "tokens": 3},
            {"finish_reason": None, "model_name": "openrouter/x", "tokens": 4},
        )

        assert merged == {"finish_reason": "stop", "model_name": "openrouter/x", "tokens": 7}

    def test_mismatched_types_are_refused(self) -> None:
        with pytest.raises(TypeError, match="but with a different type"):
            patch_module.merge_dicts({"a": "x"}, {"a": 1})

    def test_an_unmergeable_value_type_is_refused(self) -> None:
        with pytest.raises(TypeError, match="unsupported type"):
            patch_module.merge_dicts({"a": 1.5}, {"a": 2.5})

    def test_nested_dicts_merge_recursively(self) -> None:
        assert patch_module.merge_dicts({"m": {"n": 1}}, {"m": {"n": 2}}) == {"m": {"n": 3}}

    def test_model_name_stays_idempotent_when_nested(self) -> None:
        # response_metadata is itself merged as a nested dict, so the idempotent
        # set has to survive the recursion — a top-level-only fix would still
        # double the pricing key on real AIMessageChunk merges.
        nested = {"response_metadata": {"model_name": "openrouter/x", "finish_reason": "stop"}}
        merged = patch_module.merge_dicts(nested, nested)
        assert merged["response_metadata"]["model_name"] == "openrouter/x"
        assert merged["response_metadata"]["finish_reason"] == "stopstop"

    def test_lists_merge_by_index(self) -> None:
        merged = patch_module.merge_dicts(
            {"c": [{"index": 0, "text": "a"}]}, {"c": [{"index": 0, "text": "b"}]}
        )
        assert merged["c"] == [{"index": 0, "text": "ab"}]

    def test_equal_non_string_scalars_are_kept_once(self) -> None:
        assert patch_module.merge_dicts({"f": True}, {"f": True}) == {"f": True}

    def test_unequal_counters_add(self) -> None:
        assert patch_module.merge_dicts({"tokens": 3}, {"tokens": 4}) == {"tokens": 7}

    @pytest.mark.parametrize("key", ["index", "created", "timestamp"])
    def test_positional_and_clock_ints_are_replaced_not_summed(self, key: str) -> None:
        assert patch_module.merge_dicts({key: 100}, {key: 200}) == {key: 200}

    def test_an_lc_prefixed_index_string_is_idempotent(self) -> None:
        assert patch_module.merge_dicts({"index": "lc_1"}, {"index": "lc_1"}) == {"index": "lc_1"}
