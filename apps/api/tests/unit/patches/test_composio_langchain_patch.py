"""Tests for the Composio/LangChain integration patch.

composio.utils.shared.json_schema_to_pydantic_type is patched at import time:
anyOf options are re-evaluated individually and combined into a plain union,
instead of letting the library collapse them — the library's single-combiner
path yields dict for bare object options (useless to Pydantic tooling), while
the patch yields the generated model class.
"""

from __future__ import annotations

import typing as t

from composio.utils import shared

# Importing the patch module applies the monkey-patch at import time.
import app.patches.composio_langchain_patch as patch_module  # noqa: F401  # ratchet-allow -- import for the apply() side effect


class TestAnyOfFlattening:
    def test_single_valid_option_is_returned_directly(self) -> None:
        assert shared.json_schema_to_pydantic_type({"anyOf": [{"type": "integer"}]}) is int

    def test_multiple_options_become_a_union(self) -> None:
        result = shared.json_schema_to_pydantic_type(
            {"anyOf": [{"type": "string"}, {"type": "number"}]}
        )
        assert t.get_args(result) == (str, float)

    def test_object_option_is_not_collapsed_to_dict(self) -> None:
        # Unpatched, the library collapses a bare object option to `dict`.
        result = shared.json_schema_to_pydantic_type(
            {"anyOf": [{"type": "string"}, {"type": "object"}]}
        )
        args = t.get_args(result)
        assert str in args
        assert dict not in args

    def test_object_only_any_of_is_a_model_not_dict(self) -> None:
        result = shared.json_schema_to_pydantic_type({"anyOf": [{"type": "object"}]})
        assert result is not dict

    def test_nested_any_of_flattens_recursively(self) -> None:
        result = shared.json_schema_to_pydantic_type(
            {"anyOf": [{"anyOf": [{"type": "string"}, {"type": "integer"}]}]}
        )
        assert t.get_args(result) == (str, int)

    def test_empty_any_of_falls_back_to_str(self) -> None:
        assert shared.json_schema_to_pydantic_type({"anyOf": []}) is str

    def test_delegates_non_any_of_schemas_to_the_original(self) -> None:
        assert shared.json_schema_to_pydantic_type({"type": "string"}) is str
        assert shared.json_schema_to_pydantic_type(True) is t.Any
        assert shared.json_schema_to_pydantic_type(False) is None


class TestPatchInstalled:
    def test_json_schema_converter_is_rebound(self) -> None:
        assert shared.json_schema_to_pydantic_type.__name__ == (
            "patched_json_schema_to_pydantic_type"
        )
