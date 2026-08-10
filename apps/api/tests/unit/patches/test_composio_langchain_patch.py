"""Tests for the Composio/LangChain integration patch.

Two independent fixes, both applied at import time:

1. ``composio.utils.shared.json_schema_to_pydantic_type``: anyOf options are
   re-evaluated individually and combined into a plain union, instead of
   letting the library collapse them — the library's single-combiner path
   yields ``dict`` for bare object options (useless to Pydantic tooling),
   while the patch yields the generated model class.
2. ``langchain_core.tools.base._handle_validation_error``: a ``True`` flag
   surfaces the actual validation error text instead of swallowing it.
"""

from __future__ import annotations

import typing as t

from composio.utils import shared
from langchain_core.tools import base as lc_base

# Importing the patch module triggers both monkey-patches at import time.
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


class TestHandleValidationError:
    _ERROR = ValueError("boom")

    def test_string_flag_is_returned_verbatim(self) -> None:
        assert lc_base._handle_validation_error(self._ERROR, flag="custom message") == (
            "custom message"
        )

    def test_callable_flag_receives_the_error(self) -> None:
        assert lc_base._handle_validation_error(self._ERROR, flag=lambda e: f"wrapped:{e}") == (
            "wrapped:boom"
        )

    def test_true_flag_surfaces_the_actual_error(self) -> None:
        # The original returns the bare "Tool input validation error"; the
        # patch appends the error text so it reaches the model instead of
        # being swallowed.
        result = lc_base._handle_validation_error(self._ERROR, flag=True)
        assert result.startswith("Tool input validation error")
        assert "boom" in result

    def test_false_flag_also_surfaces_the_actual_error(self) -> None:
        result = lc_base._handle_validation_error(self._ERROR, flag=False)
        assert result.startswith("Tool input validation error")
        assert "boom" in result

    def test_unexpected_flag_type_returns_fallback_instead_of_raising(self) -> None:
        # The original raises ValueError for a flag outside its union.
        result = lc_base._handle_validation_error(self._ERROR, flag=42)
        assert result.startswith("Tool input validation error")
        assert "boom" in result


class TestPatchInstalled:
    def test_json_schema_converter_is_rebound(self) -> None:
        assert shared.json_schema_to_pydantic_type.__name__ == (
            "patched_json_schema_to_pydantic_type"
        )

    def test_handle_validation_error_is_rebound(self) -> None:
        assert lc_base._handle_validation_error.__name__ == "patched_handle_validation_error"
